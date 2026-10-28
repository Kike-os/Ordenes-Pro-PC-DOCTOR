"""Cotizaciones y proformas: productos del inventario o del catálogo y servicios, descuentos autorizados, impuestos (precios con IVA
incluido, como en el catálogo), forma de pago y financiamiento con tarjeta (tabla DATAFAST de la base), vigencia, condiciones, envío por
enlace privado, aprobación del cliente con evidencia, versiones, anticipos y conversión controlada a factura.

- Una proforma no es un comprobante tributario. La conversión crea un borrador de factura en el ambiente de pruebas; nada se emite al SRI.
- Un descuento mayor al autorizado exige la aprobación de administración con su motivo, que queda registrada en la partida.
- La aprobación del cliente guarda fecha, hora, versión aceptada, identidad comprobada (últimos cuatro dígitos de su identificación),
  firma manuscrita y una huella de la evidencia. Lo aprobado no se cambia: un cambio es una versión nueva.
- El financiamiento es informativo: el interés del diferido lo cobra el banco emisor y no altera los importes ni los impuestos facturables."""
import hashlib
import json
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta

import banking
import card_finance
import invoicing
import quotes

STATUS = {'borrador': 'Borrador', 'enviada': 'Enviada', 'vista': 'Vista por el cliente', 'aprobada': 'Aprobada', 'parcial': 'Aprobada parcialmente', 'rechazada': 'Rechazada',
          'modificacion': 'Modificación solicitada', 'vencida': 'Vencida', 'convertida': 'Convertida a factura', 'reemplazada': 'Reemplazada por otra versión', 'cancelada': 'Cancelada'}
ORIGINS = {'cliente': 'Desde el cliente', 'orden': 'Desde una orden', 'catalogo': 'Desde el catálogo', 'directa': 'Factura directa', 'inventario': 'Venta del inventario'}
PAYMENT = {'efectivo': 'Efectivo', 'transferencia': 'Transferencia bancaria', 'deposito': 'Depósito bancario', 'debito': 'Tarjeta de débito', 'credito_corriente': 'Tarjeta de crédito corriente',
           'diferido_con_intereses': 'Tarjeta de crédito diferida con intereses', 'diferido_sin_intereses': 'Tarjeta de crédito diferida sin intereses', 'mixto': 'Pago mixto'}
EDITABLE = ('borrador', 'modificacion')
ADVANCE_LABELS = {'efectivo': 'Efectivo', 'transferencia': 'Transferencia', 'deposito': 'Depósito', 'debito': 'Tarjeta de débito', 'credito': 'Tarjeta de crédito', 'cheque': 'Cheque', 'otro': 'Otro'}
DECIDABLE = ('enviada', 'vista')
FREE_DISCOUNT_BP = 1000  # hasta 10 % sin autorización; por encima, solo administración con motivo
LINK_DAYS = 15
MAX_FAILED = 6
METHOD = 'Enlace privado y últimos cuatro dígitos de la identificación del cliente'
CONDITIONS = '\n'.join((
    '1. Vigencia', 'Los precios y la disponibilidad se mantienen hasta la fecha de vencimiento indicada.',
    '2. Naturaleza del documento', 'Esta proforma no es un comprobante de venta ni tiene validez tributaria. La factura se emite al confirmar la venta.',
    '3. Financiamiento', 'Las cuotas con tarjeta son referenciales: el interés del diferido lo cobra el banco emisor según su calendario.',
    '4. Garantías', 'Las garantías de PC-DOCTOR y del fabricante se detallan en la factura y en el certificado de garantía.'))


class ProformaError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def stamp(now):
    return now.isoformat(timespec='seconds')


usd = quotes.usd


def event(c, pid, name, detail, now, user=None, actor=''):
    c.execute('INSERT INTO proforma_events(proforma_id,event,detail,actor_id,actor,created_at) VALUES (?,?,?,?,?,?)',
              (pid, name, detail[:800], user['id'] if user else None, actor or (user['name'] if user else 'Sistema'), stamp(now)))


def get(c, pid):
    row = c.execute('SELECT * FROM proformas WHERE id=?', (pid,)).fetchone() if str(pid).isdigit() else None
    if not row:
        raise ProformaError('Proforma no encontrada.', 404)
    return row


def items_of(c, pid):
    return [dict(r) for r in c.execute('SELECT * FROM proforma_items WHERE proforma_id=? ORDER BY position,id', (pid,))]


def line_amounts(item, rate_bp):
    gross = item['quantity'] * item['unit_cents']
    net = max(0, gross - item['discount_cents'])
    base, tax, _ = invoicing.split_inclusive(net, rate_bp if item['taxed'] else 0)
    return {'gross_cents': gross, 'net_cents': net, 'base_cents': base, 'tax_cents': tax}


def totals(items, rate_bp, only_approved=False):
    rows = [i for i in items if not only_approved or i['status'] == 'aprobado']
    amounts = [line_amounts(i, rate_bp) for i in rows]
    return {'subtotal_cents': sum(a['base_cents'] for a in amounts), 'tax_cents': sum(a['tax_cents'] for a in amounts), 'discount_cents': sum(i['discount_cents'] for i in rows),
            'total_cents': sum(a['net_cents'] for a in amounts), 'count': len(rows)}


def expire(c, row, today):
    """Una proforma enviada o vista cuya fecha de vencimiento pasó queda «vencida» (solo al consultarla; no se borra nada)."""
    if row['status'] in DECIDABLE and row['valid_until'] < today:
        c.execute("UPDATE proformas SET status='vencida',updated_at=? WHERE id=? AND status IN ('enviada','vista')", (today + 'T00:00:00', row['id']))
        c.execute("UPDATE proforma_links SET revoked_at=? WHERE proforma_id=? AND revoked_at=''", (today + 'T00:00:00', row['id']))
        return get(c, row['id'])
    return row


def _client(c, data):
    cid = str(data.get('client_id', '') or '')
    if cid.isdigit():
        row = c.execute('SELECT id,name,identification,address,main_street,phone,email FROM clients WHERE id=?', (int(cid),)).fetchone()
        if not row:
            raise ProformaError('Cliente no encontrado.', 404, {'client_id': 'Cliente no encontrado.'})
        return {'client_id': row['id'], 'client_name': row['name'] or '', 'client_identification': re.sub(r'\s', '', row['identification'] or ''),
                'client_address': (row['address'] or row['main_street'] or '')[:300], 'client_phone': row['phone'] or '', 'client_email': row['email'] or ''}
    text = lambda key, size: re.sub(r'\s+', ' ', str(data.get(key, '') or '')).strip()[:size]
    out = {'client_id': None, 'client_name': text('client_name', 300), 'client_identification': re.sub(r'\s', '', str(data.get('client_identification', '') or ''))[:20],
           'client_address': text('client_address', 300), 'client_phone': text('client_phone', 40), 'client_email': text('client_email', 200).lower()}
    errors = {}
    if len(out['client_name']) < 3:
        errors['client_name'] = 'Nombre o razón social del cliente.'
    if out['client_identification'] and not re.fullmatch(r'[A-Za-z0-9]{5,20}', out['client_identification']):
        errors['client_identification'] = 'Identificación no válida.'
    if out['client_email'] and not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+', out['client_email']):
        errors['client_email'] = 'Correo no válido.'
    if errors:
        raise ProformaError('Revisa los datos del cliente.', 400, errors)
    return out


def _items(c, raw, user, rate_bp):
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except ValueError:
        raise ProformaError('Partidas no válidas.', 400, {'items': 'Partidas no válidas.'})
    if not isinstance(items, list) or not 1 <= len(items) <= 60:
        raise ProformaError('Agrega entre 1 y 60 productos o servicios.', 400, {'items': 'Agrega al menos una partida.'})
    out, errors = [], {}
    for n, item in enumerate(items):
        if not isinstance(item, dict):
            raise ProformaError('Partidas no válidas.', 400, {'items': 'Partidas no válidas.'})
        kind = 'producto' if item.get('kind') == 'producto' else 'servicio'
        catalog = inventory = None
        code = ''
        if str(item.get('inventory_item_id', '')).isdigit():
            inventory = c.execute('SELECT i.*,k.name,k.price_cents,k.taxed,k.code FROM inventory_items i JOIN catalog_items k ON k.id=i.catalog_id WHERE i.id=? AND i.active=1',
                                  (int(item['inventory_item_id']),)).fetchone()
            if not inventory:
                errors['item_%d' % n] = 'Producto del inventario no disponible.'
                continue
            catalog, kind, code = inventory['catalog_id'], 'producto', inventory['code'] or inventory['sku'] or ''
        elif str(item.get('catalog_id', '')).isdigit():
            row = c.execute('SELECT id,code FROM catalog_items WHERE id=?', (int(item['catalog_id']),)).fetchone()
            if not row:
                errors['item_%d' % n] = 'Producto o servicio del catálogo no disponible.'
                continue
            catalog, code = row['id'], row['code'] or ''
        else:
            code = re.sub(r'[^A-Za-z0-9._/-]', '', str(item.get('code', '') or ''))  # código propio de una partida manual
        description = re.sub(r'\s+', ' ', str(item.get('description', '') or '')).strip()[:300]
        if len(description) < 2:
            errors['item_%d' % n] = 'Describe la partida.'
            continue
        try:
            quantity = int(str(item.get('quantity', '1')).strip())
        except ValueError:
            quantity = 0
        if not 1 <= quantity <= 100000:
            errors['item_%d' % n] = 'Cantidad entera mayor que cero.'
            continue
        try:
            unit = quotes.cents(str(item.get('unit_price', '')).strip(), 'unit_price')
            discount = quotes.cents(str(item.get('discount', '') or '0').strip() or '0', 'discount') if str(item.get('discount', '') or '').strip() not in ('', '0', '0,00', '0.00') else 0
        except quotes.QuoteError:
            errors['item_%d' % n] = 'Precio o descuento no válido (USD con hasta dos decimales).'
            continue
        gross = quantity * unit
        if discount > gross:
            errors['item_%d' % n] = 'El descuento supera el importe de la partida.'
            continue
        authorization = ''
        allowed = inventory['max_discount_bp'] if inventory is not None and 'max_discount_bp' in inventory.keys() and inventory['max_discount_bp'] else FREE_DISCOUNT_BP
        minimum = inventory['min_price_cents'] if inventory is not None and 'min_price_cents' in inventory.keys() else 0
        problems = []
        if gross and discount * 10000 > gross * allowed:
            problems.append('descuento mayor al %s %%' % ('%g' % (allowed / 100)).replace('.', ','))
        if minimum and quantity and (gross - discount) < minimum * quantity:
            problems.append('precio menor al mínimo (%s)' % usd(minimum))
        if unit == 0:
            problems.append('precio $0,00')
        if problems:
            reason = re.sub(r'\s+', ' ', str(item.get('authorization', '') or '')).strip()[:200]
            if user['role'] != 'administrador' or len(reason) < 10:
                errors['item_%d' % n] = 'Requiere autorización de administración con motivo: ' + '; '.join(problems) + '.'
                continue
            authorization = '%s · %s: %s' % (user['name'], '; '.join(problems), reason)
        taxed = 0 if str(item.get('taxed', '1')) in ('0', 'false') else 1
        out.append({'position': n + 1, 'kind': kind, 'catalog_id': catalog, 'inventory_item_id': inventory['id'] if inventory is not None else None, 'code': code[:25],
                    'description': description, 'quantity': quantity, 'unit_cents': unit, 'discount_cents': discount, 'taxed': taxed, 'status': 'pendiente', 'authorization': authorization})
    if errors:
        raise ProformaError('Revisa las partidas señaladas.', 400, errors)
    return out


def _financing(c, method, data, total, today):
    """Detalle informativo del financiamiento con tarjeta (con los factores de la base). Vacío si la forma de pago no es tarjeta."""
    if method not in ('credito_corriente', 'diferido_con_intereses', 'diferido_sin_intereses') or total <= 0:
        return {}
    try:
        result = card_finance.simulate(c, {'amount': '%d.%02d' % divmod(total, 100), 'method': method, 'bank': data.get('card_bank', ''), 'brand': data.get('card_brand', ''),
                                           'category': data.get('card_category', ''), 'months': data.get('card_months', '')}, today)
    except card_finance.CardError as error:
        fields = {'card_' + ('bank' if k == 'category' else k): v for k, v in error.fields.items()}
        raise ProformaError(str(error), error.status, fields or {'card_bank': str(error)})
    keep = ('method', 'method_label', 'bank', 'brand', 'category', 'group', 'months', 'base_cents', 'surcharge_cents', 'surcharge_bp', 'financeable_cents', 'factor_bp', 'interest_cents',
            'total_cents', 'installment_cents', 'installments', 'factor_source', 'warnings')
    return {k: result[k] for k in keep}


def save(c, data, user, now, pid=None):
    """Crea o actualiza una proforma en borrador (o con modificación solicitada)."""
    today = now.date()
    row = get(c, pid) if pid else None
    if row and row['status'] not in EDITABLE:
        raise ProformaError('Esta proforma ya fue enviada o decidida: crea una versión nueva para cambiarla.', 409)
    key = str(data.get('request_key', '') or '').strip()
    if not row and key:
        if not re.fullmatch(r'[A-Za-z0-9-]{16,64}', key):
            raise ProformaError('Solicitud no válida. Recarga la página.', 400)
        same = c.execute('SELECT id FROM proformas WHERE request_key=?', (key,)).fetchone()
        if same:
            return same['id']
    origin = str(data.get('origin', row['origin'] if row else 'cliente'))
    if origin not in ORIGINS:
        raise ProformaError('Origen no válido.', 400)
    client = _client(c, data)
    rate = quotes.tax_rate(c)
    items = _items(c, data.get('items', '[]'), user, rate)
    valid = str(data.get('valid_until', '') or '').strip() or (today + timedelta(days=15)).isoformat()
    try:
        valid_date = date.fromisoformat(valid)
    except ValueError:
        raise ProformaError('Fecha de vencimiento no válida.', 400, {'valid_until': 'Fecha no válida.'})
    if valid_date < today or valid_date > today + timedelta(days=365):
        raise ProformaError('La vigencia debe estar entre hoy y un año.', 400, {'valid_until': 'Fecha fuera de rango.'})
    method = str(data.get('payment_method', 'efectivo'))
    if method not in PAYMENT:
        raise ProformaError('Elige la forma de pago.', 400, {'payment_method': 'Forma de pago no válida.'})
    t = totals(items, rate)
    financing = _financing(c, method, data, t['total_cents'], today.isoformat())
    account = None
    if str(data.get('bank_account_id', '') or '').isdigit():
        account = c.execute('SELECT * FROM bank_accounts WHERE id=? AND active=1', (int(data['bank_account_id']),)).fetchone()
        if not account:
            raise ProformaError('Cuenta bancaria no disponible.', 400, {'bank_account_id': 'Cuenta no disponible.'})
        if not account['verified']:
            raise ProformaError('Esa cuenta está pendiente de verificación: no se puede usar en documentos para clientes.', 409, {'bank_account_id': 'Cuenta sin verificar.'})
    notes = re.sub(r'[ \t]+', ' ', str(data.get('notes', '') or '')).strip()[:1000]
    conditions = str(data.get('conditions', '') or '').strip()[:4000] or CONDITIONS
    order_id = int(data['order_id']) if origin == 'orden' and str(data.get('order_id', '')).isdigit() and c.execute('SELECT 1 FROM orders WHERE id=?', (int(data['order_id']),)).fetchone() else None
    values = dict(client, valid_until=valid_date.isoformat(), payment_method=method, financing=json.dumps(financing, ensure_ascii=False), bank_account_id=account['id'] if account else None,
                  notes=notes, conditions=conditions, tax_rate_bp=rate, subtotal_cents=t['subtotal_cents'], discount_cents=t['discount_cents'], tax_cents=t['tax_cents'],
                  total_cents=t['total_cents'], updated_at=stamp(now))
    if row:
        c.execute('UPDATE proformas SET ' + ','.join(k + '=?' for k in values) + ",status='borrador' WHERE id=?", (*values.values(), row['id']))
        c.execute('DELETE FROM proforma_items WHERE proforma_id=?', (row['id'],))
        pid = row['id']
        event(c, pid, 'editada', 'Proforma actualizada: %d partidas, total %s.' % (len(items), usd(t['total_cents'])), now, user)
    else:
        nid, code = banking.next_code(c, 'proformas', 'PF')
        c.execute('INSERT INTO proformas(id,code,version,origin,order_id,issue_date,status,created_by,created_at,request_key,' + ','.join(values) + ') VALUES (?,?,1,?,?,?,?,?,?,?,' + ','.join('?' * len(values)) + ')',
                  (nid, code, origin, order_id, today.isoformat(), 'borrador', user['id'], stamp(now), key or None, *values.values()))
        pid = nid
        event(c, pid, 'creada', 'Proforma %s creada (%s): %d partidas, total %s.' % (code, ORIGINS[origin], len(items), usd(t['total_cents'])), now, user)
    for item in items:
        c.execute('INSERT INTO proforma_items(proforma_id,position,kind,catalog_id,inventory_item_id,code,description,quantity,unit_cents,discount_cents,taxed,status,authorization) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (pid, item['position'], item['kind'], item['catalog_id'], item['inventory_item_id'], item['code'], item['description'], item['quantity'], item['unit_cents'],
                   item['discount_cents'], item['taxed'], 'aprobado' if origin == 'directa' else 'pendiente', item['authorization']))
        if item['authorization']:
            event(c, pid, 'autorizacion', 'Partida «%s» autorizada: %s' % (item['description'], item['authorization']), now, user)
    if origin == 'directa' and str(data.get('finalize', '')) in ('1', 'true'):
        # Venta directa (sin cotización al cliente): queda aprobada internamente para facturarla; no es una aceptación del cliente.
        c.execute("UPDATE proformas SET status='aprobada',decided_at=? WHERE id=?", (stamp(now), pid))
        event(c, pid, 'aprobada', 'Venta directa registrada por el personal (sin cotización enviada al cliente).', now, user)
    return pid


def detail(c, pid, now):
    row = expire(c, get(c, pid), now.date().isoformat())
    items = items_of(c, row['id'])
    for item in items:
        item.update(line_amounts(item, row['tax_rate_bp']))
    p = dict(row, status_label=STATUS[row['status']], origin_label=ORIGINS[row['origin']], payment_label=PAYMENT[row['payment_method']], financing=json.loads(row['financing'] or '{}'))
    account = c.execute('SELECT * FROM bank_accounts WHERE id=?', (row['bank_account_id'],)).fetchone() if row['bank_account_id'] else None
    advances = [dict(a, method_label=ADVANCE_LABELS.get(a['method'], a['method']))
                for a in c.execute("SELECT a.*,COALESCE(u.name,'') actor,(SELECT t.status FROM bank_transfers t WHERE t.advance_id=a.id) transfer_status FROM advances a LEFT JOIN users u ON u.id=a.created_by "
                                   'WHERE a.proforma_id=? ORDER BY a.id', (row['id'],))]
    paid = sum(a['amount_cents'] for a in advances if not a['voided_at'])
    approved = totals(items, row['tax_rate_bp'], only_approved=True)
    versions = [dict(v, status_label=STATUS[v['status']]) for v in c.execute('SELECT id,code,version,status,total_cents,created_at FROM proformas WHERE id IN (WITH RECURSIVE up(id,parent) AS '
                                                                            '(SELECT id,parent_id FROM proformas WHERE id=? UNION SELECT p.id,p.parent_id FROM proformas p JOIN up ON p.id=up.parent) SELECT id FROM up) '
                                                                            'OR parent_id=? ORDER BY version', (row['id'], row['id']))]
    acceptance = c.execute('SELECT decision,signer_name,method,evidence_hash,created_at FROM proforma_acceptances WHERE proforma_id=? ORDER BY id DESC LIMIT 1', (row['id'],)).fetchone()
    invoice = c.execute('SELECT id,status,total_cents,establishment,emission_point,sequential FROM invoices WHERE id=?', (row['invoice_id'],)).fetchone() if row['invoice_id'] else None
    events = [dict(r) for r in c.execute('SELECT event,detail,actor,created_at FROM proforma_events WHERE proforma_id=? ORDER BY id DESC', (row['id'],))]
    return {'proforma': p, 'items': items, 'totals': totals(items, row['tax_rate_bp']), 'approved_totals': approved, 'advances': advances, 'paid_cents': paid,
            'balance_cents': max(0, (approved['total_cents'] if row['status'] in ('aprobada', 'parcial', 'convertida') else row['total_cents']) - paid),
            'bank_account': banking.public(account), 'versions': versions, 'acceptance': dict(acceptance) if acceptance else None,
            'invoice': dict(invoice, number=invoicing.number(invoice)) if invoice else None, 'events': events, 'statuses': STATUS, 'payment_methods': PAYMENT,
            'can_edit': row['status'] in EDITABLE, 'can_send': row['status'] in ('borrador', 'modificacion', 'enviada', 'vista'),
            'can_convert': row['status'] in ('aprobada', 'parcial') and not row['invoice_id'], 'can_version': row['status'] in ('enviada', 'vista', 'rechazada', 'modificacion', 'vencida', 'parcial', 'aprobada')}


def listing(c, f, now):
    today = now.date().isoformat()
    for row in c.execute("SELECT * FROM proformas WHERE status IN ('enviada','vista') AND valid_until<?", (today,)).fetchall():
        expire(c, row, today)
    where, args = ['1=1'], []
    if f.get('status') in STATUS:
        where.append('p.status=?')
        args.append(f['status'])
    if f.get('q'):
        where.append("instr(lower(p.code||' '||p.client_name||' '||p.client_identification),lower(?))>0")
        args.append(str(f['q'])[:80])
    rows = [dict(r, status_label=STATUS[r['status']], origin_label=ORIGINS[r['origin']]) for r in c.execute(
        "SELECT p.id,p.code,p.version,p.status,p.origin,p.client_name,p.client_identification,p.issue_date,p.valid_until,p.total_cents,p.payment_method,p.invoice_id,"
        "COALESCE((SELECT SUM(a.amount_cents) FROM advances a WHERE a.proforma_id=p.id AND a.voided_at=''),0) paid_cents FROM proformas p WHERE " + ' AND '.join(where) + ' ORDER BY p.id DESC LIMIT 300', args)]
    counts = {k: c.execute('SELECT COUNT(*) FROM proformas WHERE status=?', (k,)).fetchone()[0] for k in STATUS}
    return {'rows': rows, 'counts': counts, 'statuses': STATUS}


def send(c, pid, user, now, recipient=''):
    """Genera un enlace privado nuevo (el anterior se revoca) y marca la proforma como enviada. Devuelve el token (solo existe aquí)."""
    row = expire(c, get(c, pid), now.date().isoformat())
    if row['status'] not in ('borrador', 'modificacion', 'enviada', 'vista'):
        raise ProformaError('Esta proforma no se puede enviar (%s).' % STATUS[row['status']].lower(), 409)
    if not re.sub(r'\D', '', row['client_identification'] or '') or len(re.sub(r'\D', '', row['client_identification'])) < 6:
        raise ProformaError('El cliente necesita una identificación registrada para comprobar su identidad al aprobar.', 409, {'client_identification': 'Identificación obligatoria para enviar.'})
    token = secrets.token_urlsafe(32)
    stamp_ = stamp(now)
    c.execute("UPDATE proforma_links SET revoked_at=? WHERE proforma_id=? AND revoked_at=''", (stamp_, row['id']))
    c.execute('INSERT INTO proforma_links(proforma_id,token_hash,created_at,expires_at) VALUES (?,?,?,?)',
              (row['id'], quotes.digest(token), stamp_, min(now + timedelta(days=LINK_DAYS), datetime.combine(date.fromisoformat(row['valid_until']), datetime.max.time(), now.tzinfo)).isoformat(timespec='seconds')))
    c.execute("UPDATE proformas SET status='enviada',sent_at=?,sent_to=?,updated_at=? WHERE id=?", (stamp_, recipient[:200], stamp_, row['id']))
    event(c, row['id'], 'enviada', 'Enlace privado generado' + (' y enviado a ' + recipient if recipient else ' (para compartir por WhatsApp o copiar)') + '.', now, user)
    return token


def lookup(c, token, now):
    if not re.fullmatch(r'[A-Za-z0-9_-]{30,80}', token or ''):
        return None, None
    link = c.execute('SELECT * FROM proforma_links WHERE token_hash=?', (quotes.digest(token),)).fetchone()
    if not link:
        return None, None
    row = expire(c, get(c, link['proforma_id']), now.date().isoformat())
    usable = not link['revoked_at'] and datetime.fromisoformat(link['expires_at']) >= now and link['failed'] < MAX_FAILED and row['status'] in DECIDABLE
    return row, dict(link, usable=usable)


def verify(c, row, link, last4, now):
    number = re.sub(r'\D', '', row['client_identification'] or '')
    if len(number) < 6:
        raise ProformaError('El cliente no tiene una identificación registrada. Comunícate con PC-DOCTOR.', 409)
    if not re.fullmatch(r'\d{4}', str(last4 or '')) or not secrets.compare_digest(number[-4:], str(last4)):
        c.execute('UPDATE proforma_links SET failed=failed+1 WHERE id=?', (link['id'],))
        return False
    if not link['viewed_at']:
        c.execute('UPDATE proforma_links SET viewed_at=? WHERE id=?', (stamp(now), link['id']))
    if row['status'] == 'enviada':
        c.execute("UPDATE proformas SET status='vista',viewed_at=? WHERE id=? AND status='enviada'", (stamp(now), row['id']))
        event(c, row['id'], 'vista', 'El cliente abrió la proforma y comprobó su identidad.', now, actor='Cliente')
    return True


def passkey(row, token):
    """Clave de la segunda página (firma): solo existe para quien comprobó su identidad con el enlace vigente."""
    return hashlib.sha256(('proforma:%d:%s' % (row['id'], token)).encode()).hexdigest()[:32]


def decide(c, row, link, form, now, origin):
    """Decisión del cliente por partida, o solicitud de modificación, con evidencia inmutable."""
    if not link['usable']:
        raise ProformaError('Esta proforma ya no admite una decisión desde este enlace.', 409)
    items = items_of(c, row['id'])
    comment = str(form.get('comment', '')).strip()[:600]
    name = re.sub(r'\s+', ' ', str(form.get('name', ''))).strip()
    if form.get('action') == 'change':
        if len(comment) < 5:
            raise ProformaError('Describe qué cambio necesitas.', 400, {'comment': 'Escribe tu solicitud.'})
        return _record(c, row, link, 'modificacion', name or 'Cliente', [], comment, items, now, origin)
    decisions = {i['id']: form.get('decision_%d' % i['id'], '') for i in items}
    errors = {}
    if any(v not in ('aprobado', 'rechazado') for v in decisions.values()):
        errors['items'] = 'Indica si apruebas o rechazas cada partida.'
    if not 5 <= len(name) <= 120:
        errors['name'] = 'Escribe tu nombre completo.'
    if form.get('accept') != 'on':
        errors['accept'] = 'Debes aceptar expresamente los importes y las condiciones.'
    signature = quotes.clean_signature(form.get('signature', ''))
    if any(v == 'aprobado' for v in decisions.values()) and not signature:
        errors['signature'] = 'Firma en el recuadro para aprobar.'
    if errors:
        raise ProformaError('Revisa los datos señalados.', 400, errors)
    for item in items:
        c.execute('UPDATE proforma_items SET status=? WHERE id=?', (decisions[item['id']], item['id']))
    approved = [i for i in items if decisions[i['id']] == 'aprobado']
    decision = 'aprobada' if len(approved) == len(items) else 'parcial' if approved else 'rechazada'
    return _record(c, row, link, decision, name, signature, comment, items_of(c, row['id']), now, origin)


def _record(c, row, link, decision, name, signature, comment, items, now, origin):
    evidence = {'proforma': row['code'], 'version': row['version'], 'decision': decision, 'signer': name, 'method': METHOD, 'decided_at': stamp(now), 'comment': comment,
                'identification_last4': re.sub(r'\D', '', row['client_identification'] or '')[-4:], 'tax_rate_bp': row['tax_rate_bp'],
                'items': [{'description': i['description'], 'quantity': i['quantity'], 'unit_cents': i['unit_cents'], 'discount_cents': i['discount_cents'], 'taxed': bool(i['taxed']), 'decision': i['status']} for i in items],
                'totals': totals(items, row['tax_rate_bp'], only_approved=True), 'payment_method': row['payment_method'], 'financing': json.loads(row['financing'] or '{}'),
                'conditions': row['conditions'], 'signature_points': sum(len(s) for s in signature), 'ip': origin.get('ip', ''), 'agent': origin.get('agent', '')}
    payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    c.execute('INSERT INTO proforma_acceptances(proforma_id,decision,signer_name,method,signature,evidence,evidence_hash,created_at) VALUES (?,?,?,?,?,?,?,?)',
              (row['id'], decision, name, METHOD, json.dumps(signature), payload, quotes.digest(payload + json.dumps(signature)), stamp(now)))
    stamp_ = stamp(now)
    c.execute('UPDATE proformas SET status=?,decided_at=?,updated_at=? WHERE id=?', (decision, stamp_, stamp_, row['id']))
    c.execute("UPDATE proforma_links SET revoked_at=? WHERE id=?", (stamp_, link['id']))
    event(c, row['id'], decision, {'aprobada': 'El cliente aprobó la proforma', 'parcial': 'El cliente aprobó parte de la proforma', 'rechazada': 'El cliente rechazó la proforma',
                                   'modificacion': 'El cliente solicitó una modificación'}[decision] + ((': ' + comment) if comment else '.') + ' Firmó: ' + name + '.', now, actor='Cliente: ' + name)
    return decision


def staff_decide(c, pid, data, user, now):
    """Aprobación registrada por el personal (por ejemplo, confirmada por teléfono): queda identificada como tal en la evidencia."""
    row = expire(c, get(c, pid), now.date().isoformat())
    if row['status'] not in ('enviada', 'vista', 'borrador'):
        raise ProformaError('Esta proforma no admite una decisión (%s).' % STATUS[row['status']].lower(), 409)
    note = re.sub(r'\s+', ' ', str(data.get('note', '') or '')).strip()
    if len(note) < 10:
        raise ProformaError('Indica cómo y quién confirmó la decisión del cliente.', 400, {'note': 'Detalle obligatorio (10 caracteres).'})
    decision = str(data.get('decision', ''))
    if decision not in ('aprobada', 'rechazada'):
        raise ProformaError('Decisión no válida.', 400)
    c.execute('UPDATE proforma_items SET status=? WHERE proforma_id=?', ('aprobado' if decision == 'aprobada' else 'rechazado', row['id']))
    items = items_of(c, row['id'])
    evidence = {'proforma': row['code'], 'version': row['version'], 'decision': decision, 'method': 'Registrada por el personal', 'registered_by': user['name'], 'note': note, 'decided_at': stamp(now),
                'totals': totals(items, row['tax_rate_bp'], only_approved=True)}
    payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    c.execute('INSERT INTO proforma_acceptances(proforma_id,decision,signer_name,method,signature,evidence,evidence_hash,created_at) VALUES (?,?,?,?,?,?,?,?)',
              (row['id'], decision, user['name'], 'Registrada por el personal', '[]', payload, quotes.digest(payload + '[]'), stamp(now)))
    c.execute('UPDATE proformas SET status=?,decided_at=?,updated_at=? WHERE id=?', (decision, stamp(now), stamp(now), row['id']))
    c.execute("UPDATE proforma_links SET revoked_at=? WHERE proforma_id=? AND revoked_at=''", (stamp(now), row['id']))
    event(c, row['id'], decision, 'Decisión registrada por el personal: ' + note, now, user)


def new_version(c, pid, user, now):
    """Versión nueva para cambiar una proforma enviada o decidida: la anterior queda reemplazada y conserva su historial."""
    row = get(c, pid)
    if row['status'] in ('borrador', 'convertida', 'reemplazada', 'cancelada'):
        raise ProformaError('Esta proforma no admite una versión nueva (%s).' % STATUS[row['status']].lower(), 409)
    if c.execute("SELECT 1 FROM advances WHERE proforma_id=? AND voided_at=''", (row['id'],)).fetchone():
        raise ProformaError('Esta proforma tiene anticipos: factúrala o anula los anticipos antes de crear otra versión.', 409)
    base = row['code'].split('-V')[0]
    version = c.execute('SELECT COALESCE(MAX(version),1)+1 FROM proformas WHERE code=? OR code LIKE ?', (base, base + '-V%')).fetchone()[0]
    nid, _ = banking.next_code(c, 'proformas', 'PF')
    code = '%s-V%d' % (base, version)
    cols = ('origin', 'order_id', 'client_id', 'client_name', 'client_identification', 'client_address', 'client_phone', 'client_email', 'valid_until', 'tax_rate_bp', 'payment_method',
            'financing', 'bank_account_id', 'notes', 'conditions', 'subtotal_cents', 'discount_cents', 'tax_cents', 'total_cents')
    valid = max(row['valid_until'], (now.date() + timedelta(days=15)).isoformat())
    c.execute('INSERT INTO proformas(id,code,version,parent_id,issue_date,status,created_by,created_at,updated_at,' + ','.join(cols) + ') SELECT ?,?,?,?,?,?,?,?,?,' +
              ','.join('?' if k == 'valid_until' else k for k in cols) + ' FROM proformas WHERE id=?',
              (nid, code, version, row['id'], now.date().isoformat(), 'borrador', user['id'], stamp(now), stamp(now), valid, row['id']))
    c.execute("INSERT INTO proforma_items(proforma_id,position,kind,catalog_id,inventory_item_id,code,description,quantity,unit_cents,discount_cents,taxed,status,authorization) "
              "SELECT ?,position,kind,catalog_id,inventory_item_id,code,description,quantity,unit_cents,discount_cents,taxed,'pendiente',authorization FROM proforma_items WHERE proforma_id=?", (nid, row['id']))
    c.execute("UPDATE proformas SET status='reemplazada',replaced_by=?,updated_at=? WHERE id=?", (nid, stamp(now), row['id']))
    c.execute("UPDATE proforma_links SET revoked_at=? WHERE proforma_id=? AND revoked_at=''", (stamp(now), row['id']))
    event(c, row['id'], 'reemplazada', 'Reemplazada por la versión %s.' % code, now, user)
    event(c, nid, 'creada', 'Versión %d creada a partir de %s.' % (version, row['code']), now, user)
    return nid


def cancel(c, pid, data, user, now):
    row = get(c, pid)
    if row['status'] in ('convertida', 'reemplazada', 'cancelada'):
        raise ProformaError('Esta proforma no se puede cancelar (%s).' % STATUS[row['status']].lower(), 409)
    if c.execute("SELECT 1 FROM advances WHERE proforma_id=? AND voided_at=''", (row['id'],)).fetchone():
        raise ProformaError('Tiene anticipos registrados: anúlalos o devuélvelos antes de cancelar.', 409)
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if len(reason) < 5:
        raise ProformaError('Indica el motivo.', 400, {'reason': 'Motivo obligatorio.'})
    c.execute("UPDATE proformas SET status='cancelada',updated_at=? WHERE id=?", (stamp(now), row['id']))
    c.execute("UPDATE proforma_links SET revoked_at=? WHERE proforma_id=? AND revoked_at=''", (stamp(now), row['id']))
    event(c, row['id'], 'cancelada', 'Proforma cancelada: ' + reason, now, user)


def convert(c, pid, user, now):
    """Convierte una proforma aprobada en un borrador de factura (ambiente de pruebas). Idempotente: si ya tiene factura, devuelve esa."""
    row = expire(c, get(c, pid), now.date().isoformat())
    if row['invoice_id']:
        return row['invoice_id']
    if row['status'] not in ('aprobada', 'parcial'):
        raise ProformaError('Solo se factura una proforma aprobada (%s).' % STATUS[row['status']].lower(), 409)
    try:
        invoice_id = invoicing.draft(c, 'proforma', row['id'], user, now)
    except invoicing.InvoiceError as error:
        raise ProformaError(str(error), error.status, error.fields)
    c.execute("UPDATE proformas SET status='convertida',invoice_id=?,updated_at=? WHERE id=?", (invoice_id, stamp(now), row['id']))
    event(c, row['id'], 'convertida', 'Convertida en borrador de factura (ambiente de pruebas).', now, user)
    return invoice_id


# ---- Anticipos ------------------------------------------------------------------------------------------------------------------

ADVANCE_METHODS = ('efectivo', 'transferencia', 'deposito', 'debito', 'credito', 'cheque', 'otro')


def add_advance(c, pid, data, user, now, file_id=None, operation=''):
    """Anticipo o abono antes de facturar. No supera el total aprobado (o el total, si aún no se decide)."""
    row = get(c, pid)
    if row['status'] in ('cancelada', 'reemplazada', 'rechazada', 'vencida'):
        raise ProformaError('No se registran anticipos en una proforma %s.' % STATUS[row['status']].lower(), 409)
    key = str(data.get('request_key', '') or '').strip()
    if key:
        if not re.fullmatch(r'[A-Za-z0-9-]{16,64}', key):
            raise ProformaError('Solicitud no válida. Recarga la página.', 400)
        same = c.execute('SELECT id FROM advances WHERE request_key=?', (key,)).fetchone()
        if same:
            return same['id']
    method = str(data.get('method', ''))
    if method not in ADVANCE_METHODS:
        raise ProformaError('Elige la forma de pago.', 400, {'method': 'Forma de pago no válida.'})
    import cash_sessions
    try:
        amount = cash_sessions.cents_of(data.get('amount', ''))
        paid_at = banking.when(data.get('paid_at', ''), now)
    except cash_sessions.CashError as error:
        raise ProformaError(str(error), 400, error.fields)
    except banking.BankError as error:
        raise ProformaError(str(error), 400, error.fields)
    items = items_of(c, row['id'])
    limit = totals(items, row['tax_rate_bp'], only_approved=row['status'] in ('aprobada', 'parcial', 'convertida'))['total_cents'] - c.execute(
        "SELECT COALESCE(SUM(amount_cents),0) FROM advances WHERE proforma_id=? AND voided_at=''", (row['id'],)).fetchone()[0]
    if row['invoice_id'] and c.execute("SELECT status FROM invoices WHERE id=?", (row['invoice_id'],)).fetchone()['status'] != 'borrador':
        raise ProformaError('La factura de esta proforma ya fue emitida: registra el cobro de la factura.', 409)
    if amount > limit:
        raise ProformaError('El anticipo supera el saldo de la proforma (%s).' % usd(max(0, limit)), 400, {'amount': 'Mayor que el saldo.'})
    reference = re.sub(r'\s+', ' ', str(data.get('reference', '') or '')).strip()[:60]
    account = None
    if method in ('transferencia', 'deposito'):
        account = c.execute('SELECT * FROM bank_accounts WHERE id=? AND active=1', (str(data.get('bank_account_id', '')),)).fetchone() if str(data.get('bank_account_id', '')).isdigit() else None
        if not account:
            raise ProformaError('Elige la cuenta que recibe el dinero.', 400, {'bank_account_id': 'Cuenta no disponible.'})
        if len(reference) < 3:
            raise ProformaError('Indica la referencia bancaria.', 400, {'reference': 'Referencia obligatoria.'})
        if c.execute("SELECT 1 FROM bank_transfers WHERE bank_account_id=? AND lower(reference)=lower(?) AND status!='rechazado'", (account['id'], reference)).fetchone():
            raise ProformaError('Esa referencia ya está registrada en esta cuenta.', 409, {'reference': 'Referencia repetida.'})
    nid, code = banking.next_code(c, 'advances', 'AN')
    session = cash_sessions.current_for(c, user)
    note = re.sub(r'\s+', ' ', str(data.get('note', '') or '')).strip()[:300]
    c.execute('INSERT INTO advances(id,code,client_id,proforma_id,method,bank_account_id,reference,amount_cents,paid_at,cash_session_id,note,request_key,created_by,created_at,operation_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (nid, code, row['client_id'], row['id'], method, account['id'] if account else None, reference, amount, paid_at, session, note, key or None, user['id'], stamp(now), operation))
    if account:
        banking.register_transfer(c, {'method': method, 'bank_account_id': account['id'], 'reference': reference, 'amount_cents': amount, 'paid_at': paid_at, 'source_kind': 'proforma',
                                      'source_id': row['id'], 'client_id': row['client_id'] or '', 'payer': row['client_name']}, user, now, advance_id=nid, file_id=file_id)
    event(c, row['id'], 'anticipo', 'Anticipo %s: %s por %s%s.' % (code, usd(amount), method, (' (ref. ' + reference + ')') if reference else ''), now, user)
    return nid


def void_advance(c, advance_id, data, user, now):
    if user['role'] != 'administrador':
        raise ProformaError('Solo administración anula un anticipo.', 403)
    a = c.execute('SELECT * FROM advances WHERE id=?', (advance_id,)).fetchone() if str(advance_id).isdigit() else None
    if not a or a['voided_at']:
        raise ProformaError('Anticipo no disponible.', 404)
    row = get(c, a['proforma_id'])
    if row['invoice_id'] and c.execute('SELECT status FROM invoices WHERE id=?', (row['invoice_id'],)).fetchone()['status'] != 'borrador':
        raise ProformaError('El anticipo ya se aplicó a una factura emitida: corrígelo con una nota de crédito.', 409)
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if len(reason) < 10:
        raise ProformaError('Indica el motivo de la anulación.', 400, {'reason': 'Motivo obligatorio (10 caracteres).'})
    c.execute('UPDATE advances SET voided_at=?,voided_by=?,void_reason=? WHERE id=?', (stamp(now), user['id'], reason, a['id']))
    event(c, row['id'], 'anticipo_anulado', 'Anticipo %s anulado: %s' % (a['code'], reason), now, user)


def all_payments(c, f):
    """Pagos y anticipos: cobros de órdenes, anticipos de proformas y cobros de licencias en una sola consulta (solo lectura)."""
    rows = []
    q = str(f.get('q', '') or '').lower()[:60]
    for r in c.execute("SELECT p.id,p.amount_cents,p.kind,p.method,p.method_detail,p.reference,p.paid_at,p.created_at,p.voided_at,p.operation_id,o.code,o.id order_id,COALESCE(k.name,'') client,"
                       "COALESCE(u.name,'') actor,(SELECT t.status FROM bank_transfers t WHERE t.payment_id=p.id) transfer_status,(SELECT v.status FROM card_vouchers v WHERE v.payment_id=p.id AND v.status!='rechazada' LIMIT 1) voucher_status "
                       "FROM order_payments p JOIN orders o ON o.id=p.order_id JOIN devices d ON d.id=o.device_id LEFT JOIN clients k ON k.id=d.client_id LEFT JOIN users u ON u.id=p.created_by ORDER BY p.id DESC LIMIT 400"):
        rows.append({'ref': 'REC-%06d' % r['id'], 'id': r['id'], 'type': 'devolucion' if r['kind'] == 'devolucion' else 'pago', 'type_label': 'Devolución' if r['kind'] == 'devolucion' else 'Cobro de orden',
                     'document': r['code'], 'order_id': r['order_id'], 'client': r['client'], 'amount_cents': r['amount_cents'],
                     'method': r['method_detail'] or r['method'], 'reference': r['reference'], 'at': r['paid_at'] or r['created_at'], 'actor': r['actor'], 'voided': bool(r['voided_at']),
                     'operation': r['operation_id'], 'verification': r['transfer_status'] or r['voucher_status'] or ''})
    for r in c.execute("SELECT a.*,COALESCE(f.code,'') proforma,COALESCE(k.name,f.client_name,'') client,COALESCE(u.name,'') actor,(SELECT t.status FROM bank_transfers t WHERE t.advance_id=a.id) transfer_status "
                       'FROM advances a LEFT JOIN proformas f ON f.id=a.proforma_id LEFT JOIN clients k ON k.id=a.client_id LEFT JOIN users u ON u.id=a.created_by ORDER BY a.id DESC LIMIT 400'):
        rows.append({'ref': r['code'], 'id': r['id'], 'type': 'anticipo', 'type_label': 'Anticipo', 'document': r['proforma'], 'proforma_id': r['proforma_id'], 'client': r['client'],
                     'amount_cents': r['amount_cents'], 'method': r['method'], 'reference': r['reference'], 'at': r['paid_at'], 'actor': r['actor'], 'voided': bool(r['voided_at']),
                     'operation': r['operation_id'], 'verification': r['transfer_status'] or ''})
    if q:
        rows = [r for r in rows if q in ' '.join(str(r[k]) for k in ('ref', 'document', 'client', 'reference')).lower()]
    if f.get('type') in ('pago', 'devolucion', 'anticipo'):
        rows = [r for r in rows if r['type'] == f['type']]
    rows.sort(key=lambda r: r['at'], reverse=True)
    return rows[:500]


# ---- Documento PDF y página del cliente -------------------------------------------------------------------------------------

def pdf(c, pid, now, staff_url=''):
    """Proforma comercial A4 con la identidad de PC-DOCTOR: encabezado (logo, contacto, número, fechas y estado), cliente, partidas con el
    encabezado repetido en cada página, resumen financiero, información comercial, condiciones y un Code 128 con el código único de la
    proforma. El QR (solo en la copia interna) abre la proforma en Órdenes Pro y exige iniciar sesión. No es un comprobante tributario."""
    import document_style as ds
    import invoicing as inv_
    from document_canvas import GRAY, INK
    d = detail(c, pid, now)
    p, items, t = d['proforma'], d['items'], d['totals']
    company = __import__('corporate').settings()
    fiscal = inv_.settings(c)
    rate = p['tax_rate_bp']
    pct = ('%g' % (rate / 100)).replace('.', ',')
    doc = ds.Doc('Proforma ' + p['code'])
    left, right = ds.M, ds.A4[0] - ds.M

    def continuation():
        doc.page()
        doc.logo(left, 26, 46)
        doc.text(ds.TRADE_NAME, left + 56, 30, 12, True, ds.NAVY)
        doc.text('Proforma %s · continuación' % p['code'], left + 56, 46, 8.5, False, GRAY)
        doc.hline(left, 66, right - left, ds.NAVY, 1)
        return 78

    def room(y, need):
        return continuation() if y + need > ds.BOTTOM else y

    doc.page()
    # Encabezado: marca y contacto (izquierda), datos del documento (derecha).
    address = fiscal.get('branch_address') or fiscal.get('head_office_address') or ''
    contact = [(address, False)] if address else []
    contact += [('Tel. / WhatsApp: ' + company['whatsapp'], False)] if company.get('whatsapp') else []
    contact += [(company['support_email'], False)] if company.get('support_email') else []
    used = doc.brand(left, 26, contact)
    bx, bw = right - 196, 196
    doc.rect(bx, 26, bw, 96, fill=ds.SOFT)
    doc.text('PROFORMA', bx + 12, 34, 15, True, ds.NAVY)
    doc.text('No. ' + p['code'] + (' · versión %d' % p['version'] if p['version'] > 1 else ''), bx + 12, 54, 10, True)
    for n, (k, v) in enumerate((('Emisión', _d(p['issue_date'])), ('Vence', _d(p['valid_until'])), ('Estado', p['status_label']))):
        doc.text(k, bx + 12, 72 + n * 14, 8, False, GRAY)
        doc.right(v, bx + bw - 12, 72 + n * 14, 8.5, True)
    y = max(26 + used, 122) + 10
    doc.hline(left, y, right - left, ds.NAVY, 1.2)
    y += 12
    # Cliente.
    doc.label('Datos del cliente', left, y)
    y += 14
    fields = [('Nombres o razón social', p['client_name']), ('Cédula o RUC', p['client_identification'] or '—'), ('Dirección', p['client_address'] or '—'),
              ('Teléfono', p['client_phone'] or '—'), ('Correo electrónico', p['client_email'] or '—')]
    half = (right - left) / 2
    doc.text(fields[0][0], left, y + 1, 7.5, False, GRAY)
    doc.text(doc.wrap(fields[0][1], right - left - 120, 10)[0], left + 110, y, 10, True)
    y += 16
    pairs = [fields[1:3], fields[3:5]]
    for pair in pairs:
        tall = 1
        for n, (k, v) in enumerate(pair):
            x = left + n * half
            doc.text(k, x, y + 1, 7.5, False, GRAY)
            pieces = doc.wrap(v, half - 118, 8.5)[:2]
            for i, piece in enumerate(pieces):
                doc.text(piece, x + 110, y + i * 10.5, 8.5)
            tall = max(tall, len(pieces))
        y += 10.5 * tall + 3
    y += 8
    # Partidas.
    warranty = {}
    try:
        import inventory_center
        for i in items:
            if i.get('inventory_item_id'):
                w = c.execute('SELECT warranty_store_qty,warranty_store_unit,warranty_maker_qty,warranty_maker_unit FROM inventory_items WHERE id=?', (i['inventory_item_id'],)).fetchone()
                if w and (w[0] or w[2]):
                    parts = ([('tienda ' + inventory_center.period_label(w[0], w[1]))] if w[0] else []) + ([('fabricante ' + inventory_center.period_label(w[2], w[3]))] if w[2] else [])
                    warranty[i['description']] = ' · '.join(parts)
    except Exception:
        warranty = {}
    rows = []
    for i in items:
        rows.append({'code': i.get('code') or '—', 'desc': i['description'], 'qty': str(i['quantity']), 'unit': usd(i['unit_cents']),
                     'disc': usd(i['discount_cents']) if i['discount_cents'] else '—', 'tax': (pct + ' %') if i['taxed'] else '0 %', 'total': usd(i['net_cents']),
                     '_note': ('Decisión del cliente: ' + i['status']) if i['status'] != 'pendiente' else ''})
    cols = [('Código', 64, 'l', 'code', True), ('Descripción', 205, 'l', 'desc', True), ('Cant.', 38, 'r', 'qty', False), ('P. unitario', 64, 'r', 'unit', False),
            ('Descuento', 56, 'r', 'disc', False), ('IVA', 34, 'r', 'tax', False), ('Total', 62, 'r', 'total', False)]
    y = doc.table(cols, rows, y, continuation)
    # Resumen financiero (derecha) y código de barras con el identificador único (izquierda).
    gross = sum(i['quantity'] * i['unit_cents'] for i in items)
    base_taxed = sum(line_amounts(i, rate)['base_cents'] for i in items if i['taxed'])
    base_zero = sum(line_amounts(i, rate)['base_cents'] for i in items if not i['taxed'])
    lines = [('Subtotal (IVA incluido)', usd(gross)), ('Descuentos', '-' + usd(t['discount_cents']) if t['discount_cents'] else usd(0)),
             ('Base imponible ' + pct + ' %', usd(base_taxed))] + ([('Base imponible 0 %', usd(base_zero))] if base_zero else []) + [('IVA ' + pct + ' %', usd(t['tax_cents']))]
    need = 14 * len(lines) + 40
    y = room(y + 6, max(need, 96))
    tw = 228
    end = doc.totals(right - tw, y + 8, tw, lines, ('TOTAL GENERAL', usd(t['total_cents'])))
    doc.label('Identificador de la proforma', left, y + 4)
    doc.barcode(p['code'], left - 4, y + 18, 190, 38)
    doc.center(p['code'], left + 91, y + 60, 9, True)
    if staff_url:
        doc.qr(staff_url, left + 200, y + 10, 66)
        doc.text('Consulta interna', left + 205, y + 78, 7, False, GRAY)
    y = max(end, y + 92) + 6
    # Información comercial.
    info = [('Forma de pago', p['payment_label']), ('Vigencia de la oferta', 'Hasta el %s' % _d(p['valid_until']))]
    f = p['financing']
    if f:
        info.append(('Financiamiento con tarjeta', '%s · %s · %s · %d %s. PRECIO %s + RECARGO %s + INTERESES %s = TOTAL A PAGAR %s; %d letras de %s. El interés del diferido lo cobra '
                     'el banco emisor; la factura se emite por el precio.' % (f['bank'], f['brand'], f['category'], f['months'], 'mes' if f['months'] == 1 else 'meses', usd(f['base_cents']),
                                                                             usd(f['surcharge_cents']), usd(f['interest_cents']), usd(f['total_cents']), f['months'], usd(f['installment_cents']))))
    account = d['bank_account']
    if account:
        info.append(('Depósito o transferencia', '%s · %s · %s · %s · %s' % (account['bank'], account['type_label'], account['number'], account['holder'], account['holder_ruc'] or account['holder_id'])))
    if d['paid_cents']:
        info.append(('Anticipos registrados', '%s · saldo %s' % (usd(d['paid_cents']), usd(d['balance_cents']))))
    info.append(('Garantía aplicable', '; '.join('%s: %s' % (k, v) for k, v in warranty.items()) or 'Según las políticas comerciales vigentes y la garantía de cada producto o servicio.'))
    if p['notes']:
        info.append(('Observaciones', p['notes']))
    y = room(y, 40)
    doc.label('Información comercial', left, y)
    y += 14
    for k, v in info:
        pieces = doc.wrap(v, right - left - 132, 8.5)
        y = room(y, 11 * len(pieces) + 4)
        doc.text(k, left, y, 8, True, ds.NAVY)
        for piece in pieces:
            doc.text(piece, left + 132, y, 8.5)
            y += 11
        y += 3
    y += 6
    clauses = quotes.clauses(p['conditions'])
    if clauses:
        y = room(y, 40)
        doc.label('Condiciones comerciales', left, y)
        y += 14
        for title, body in clauses:
            for n, piece in enumerate(doc.wrap(((title.rstrip('.') + '. ') if title else '') + body, right - left, 7.8)):
                y = room(y, 10)
                doc.text(piece, left, y, 7.8, False, INK)
                y += 10
            y += 2
    if d['acceptance']:
        a = d['acceptance']
        y = room(y + 4, 14)
        doc.text('Decisión: %s · %s · %s · %s · huella %s' % (a['decision'], a['signer_name'], a['method'], _dt(a['created_at']), a['evidence_hash'][:16]), left, y, 7.5, False, GRAY)
    doc.footer('PROFORMA COMERCIAL — NO ES COMPROBANTE TRIBUTARIO')
    return doc.finish()


def _d(value):
    try:
        return date.fromisoformat(value[:10]).strftime('%d/%m/%Y')
    except ValueError:
        return value


def _dt(value):
    try:
        return datetime.fromisoformat(value).strftime('%d/%m/%Y %H:%M')
    except ValueError:
        return value


def identify_page(token, row, error=''):
    import html
    e = html.escape
    return quotes._shell('Proforma ' + row['code'], '<section class="tracking-card quote-card"><small>PROFORMA</small><h1>%s</h1><p class="quote-device">%s</p>'
                         '<form class="auth-form" method="post" action="/proforma/%s" autocomplete="off">%s<p class="auth-step">Paso 1 de 2 · Comprueba tu identidad</p>'
                         '<label for="last4">Escribe los <strong>últimos cuatro dígitos</strong> de tu cédula o RUC</label><input id="last4" name="last4" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" required autofocus>'
                         '<button class="quote-primary" type="submit">Ver mi proforma</button></form></section>' % (e(row['code']), e(row['client_name']), e(token),
                                                                                                                   '<p class="quote-error" role="alert">%s</p>' % e(error) if error else ''))


def missing_page():
    return quotes._shell('Enlace no disponible', '<section class="tracking-card"><h1>Enlace no disponible</h1><p>Este enlace de proforma no existe, venció o ya se usó para registrar una decisión. Comunícate con PC-DOCTOR.</p></section>')


def result_page(row, decision):
    import html
    text = {'aprobada': 'Gracias. Registramos tu aprobación de la proforma.', 'parcial': 'Gracias. Registramos tu aprobación de las partidas elegidas.', 'rechazada': 'Registramos que no apruebas la proforma.',
            'modificacion': 'Recibimos tu solicitud de modificación. Te enviaremos una versión nueva.'}.get(decision, 'Decisión registrada.')
    return quotes._shell('Proforma ' + row['code'], '<section class="tracking-card"><small>PROFORMA</small><h1>%s</h1><p>%s</p></section>' % (html.escape(row['code']), html.escape(text)))


def decision_page(c, token, key, row, errors=None, form=None):
    import html
    e, errors, form = html.escape, errors or {}, form or {}
    items = items_of(c, row['id'])
    t = totals(items, row['tax_rate_bp'])
    rows = ''
    for item in items:
        amounts = line_amounts(item, row['tax_rate_bp'])
        chosen = form.get('decision_%d' % item['id'], '')
        rows += ('<fieldset class="quote-item"><legend>%s</legend><p class="quote-amount">%s%s%s · <strong>%s</strong>%s</p>'
                 '<label><input type="radio" name="decision_%d" value="aprobado"%s required> Apruebo</label><label><input type="radio" name="decision_%d" value="rechazado"%s> No apruebo</label></fieldset>'
                 ) % (e(item['description']), '%d × ' % item['quantity'] if item['quantity'] > 1 else '', e(usd(item['unit_cents'])), (' − ' + e(usd(item['discount_cents'])) + ' de descuento') if item['discount_cents'] else '',
                      e(usd(amounts['net_cents'])), '' if item['taxed'] else ' <small>(tarifa 0 %)</small>', item['id'], ' checked' if chosen == 'aprobado' else '', item['id'], ' checked' if chosen == 'rechazado' else '')
    problem = lambda k: '<p class="quote-error" role="alert">%s</p>' % e(errors[k]) if errors.get(k) else ''
    f = json.loads(row['financing'] or '{}')
    finance = ''
    if f:
        finance = ('<section class="quote-bank"><h2>Pago con tarjeta (referencial)</h2><dl><div><dt>Tarjeta</dt><dd>%s · %s · %s</dd></div><div><dt>Precio + recargo + intereses</dt><dd>%s + %s + %s</dd></div>'
                   '<div><dt>Total a pagar</dt><dd>%s</dd></div><div><dt>%d letras de</dt><dd>%s</dd></div></dl><p class="quote-bank-note">El interés del diferido lo cobra el banco emisor.</p></section>'
                   ) % (e(f['bank']), e(f['brand']), e(PAYMENT.get(f['method'], '')), e(usd(f['base_cents'])), e(usd(f['surcharge_cents'])), e(usd(f['interest_cents'])), e(usd(f['total_cents'])), f['months'], e(usd(f['installment_cents'])))
    account = c.execute('SELECT * FROM bank_accounts WHERE id=? AND active=1 AND verified=1', (row['bank_account_id'],)).fetchone() if row['bank_account_id'] else None
    bank = quotes.bank_html(banking.public(account)) if account and not invoicing.TEST_MODE else ''
    conditions = ''.join('<li>%s%s</li>' % ('<strong>%s.</strong> ' % e(title.rstrip('.')) if title else '', e(body)) for title, body in quotes.clauses(row['conditions']))
    body = ('<section class="tracking-card quote-card"><small>PROFORMA</small><h1>%s</h1><p class="quote-device">%s · válida hasta el %s</p>'
            '<form class="auth-form quote-form" method="post" action="/proforma/%s" autocomplete="off"><input type="hidden" name="passkey" value="%s">'
            '<p class="auth-step">Paso 2 de 2 · Revisa y decide cada partida</p><div class="quote-bulk"><button type="button" data-quote-all="aprobado">Aprobar todo</button><button type="button" data-quote-all="rechazado">Rechazar todo</button></div>%s%s'
            '<dl class="quote-totals"><div><dt>Subtotal sin impuestos</dt><dd>%s</dd></div><div><dt>IVA</dt><dd>%s</dd></div><div class="quote-total"><dt>Total</dt><dd>%s</dd></div>'
            '<div class="quote-chosen"><dt>Total que apruebas</dt><dd data-quote-approved>—</dd></div></dl>%s%s'
            '<h2>Condiciones</h2><ul class="quote-conditions">%s</ul>'
            '<label for="name">Nombre completo de quien aprueba</label><input id="name" name="name" maxlength="120" value="%s" required>%s'
            '<label for="comment">Observaciones (opcional)</label><textarea id="comment" name="comment" rows="2" maxlength="600">%s</textarea>%s'
            '<p class="quote-sign-label">Firma con el dedo o el ratón dentro del recuadro</p><div class="quote-sign" data-quote-sign><canvas width="1000" height="300" aria-label="Recuadro de firma"></canvas><button type="button" data-quote-clear>Borrar firma</button></div><input type="hidden" name="signature" value="">%s'
            '<label class="quote-accept"><input type="checkbox" name="accept"%s required> Estoy de acuerdo con los importes y las condiciones de esta proforma.</label>%s'
            '<button class="quote-primary" type="submit" name="action" value="decide">Estoy de acuerdo · Confirmar mi decisión</button>'
            '<button class="quote-secondary" type="submit" name="action" value="change" formnovalidate>Solicitar una modificación</button></form>'
            '<p class="quote-pdf"><a href="/proforma/%s/documento.pdf?k=%s">Descargar la proforma en PDF</a></p></section>'
            ) % (e(row['code']), e(row['client_name']), e(_d(row['valid_until'])), e(token), e(key), problem('items'), rows, e(usd(t['subtotal_cents'])), e(usd(t['tax_cents'])), e(usd(t['total_cents'])),
                 finance, bank, conditions, e(form.get('name', '')), problem('name'), e(form.get('comment', '')), problem('comment'), problem('signature'),
                 ' checked' if form.get('accept') == 'on' else '', problem('accept'), e(token), e(key))
    return quotes._shell('Proforma ' + row['code'], body)


def handle(c, token, row, link, form, now, origin):
    """Formulario público en dos pasos: identidad (últimos cuatro dígitos) y decisión firmada. Devuelve (página, decisión o None)."""
    if not link['usable']:
        return (result_page(row, row['status']) if row['status'] in ('aprobada', 'parcial', 'rechazada', 'modificacion', 'convertida') else missing_page()), None
    if form.get('passkey'):
        if not secrets.compare_digest(str(form.get('passkey')), passkey(row, token)):
            return identify_page(token, row, 'Vuelve a comprobar tu identidad.'), None
        try:
            decision = decide(c, row, link, form, now, origin)
        except ProformaError as error:
            return decision_page(c, token, passkey(row, token), row, error.fields or {'items': str(error)}, form), None
        return result_page(get(c, row['id']), decision), decision
    if not verify(c, row, link, form.get('last4', ''), now):
        left = MAX_FAILED - c.execute('SELECT failed FROM proforma_links WHERE id=?', (link['id'],)).fetchone()['failed']
        return identify_page(token, row, 'Los dígitos no coinciden.' + (' Te quedan %d intentos.' % left if left > 0 else ' El enlace quedó bloqueado: comunícate con PC-DOCTOR.')), None
    return decision_page(c, token, passkey(row, token), get(c, row['id'])), None


def valid_passkey(row, token, key):
    return bool(key) and secrets.compare_digest(str(key), passkey(row, token))



def checkout(c, pid, data, user, now):
    """Cierra una factura directa en una sola transacción: aprueba la venta, registra los pagos (uno o varios: pago mixto) como anticipos
    vinculados a la caja abierta y crea el borrador de factura con esos pagos aplicados. Idempotente: si ya tiene factura, devuelve esa."""
    import secrets
    row = get(c, pid)
    if row['origin'] != 'directa':
        raise ProformaError('Solo una factura directa se cierra desde aquí.', 409)
    if row['invoice_id']:
        return row['invoice_id']
    if row['status'] not in ('borrador', 'aprobada'):
        raise ProformaError('Esta venta no se puede facturar (%s).' % STATUS[row['status']].lower(), 409)
    try:
        lines = json.loads(data.get('payments', '[]')) if isinstance(data.get('payments'), str) else (data.get('payments') or [])
    except ValueError:
        raise ProformaError('Formas de pago no válidas.', 400, {'payments': 'Formas de pago no válidas.'})
    if not isinstance(lines, list) or len(lines) > 5:
        raise ProformaError('Hasta cinco formas de pago.', 400, {'payments': 'Hasta cinco formas de pago.'})
    stamp_ = stamp(now)
    c.execute("UPDATE proforma_items SET status='aprobado' WHERE proforma_id=?", (row['id'],))
    if row['status'] != 'aprobada':
        c.execute("UPDATE proformas SET status='aprobada',decided_at=?,updated_at=? WHERE id=?", (stamp_, stamp_, row['id']))
        event(c, row['id'], 'aprobada', 'Venta directa confirmada por el personal (sin cotización enviada al cliente).', now, user)
    note = re.sub(r'\s+', ' ', str(data.get('internal_note', '') or '')).strip()[:500]
    if note:
        event(c, row['id'], 'nota_interna', 'Nota interna: ' + note, now, user)
    key = str(data.get('request_key', '') or '').strip()[:48]
    operation = ('OP-' + secrets.token_hex(6).upper()) if len(lines) > 1 else ''
    for n, line in enumerate(lines, 1):
        if not isinstance(line, dict):
            raise ProformaError('Formas de pago no válidas.', 400, {'payments': 'Formas de pago no válidas.'})
        add_advance(c, row['id'], {**line, 'request_key': (key + '-p%d' % n) if len(key) >= 16 else '', 'paid_at': data.get('paid_at', ''), 'note': 'Cobro de la factura directa'}, user, now, operation=operation)
    return convert(c, row['id'], user, now)
