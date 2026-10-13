"""Presupuestos profesionales de una orden: catálogo, versiones, estado por ítem, aprobación y evidencia.

- Los precios del catálogo incluyen IVA. El presupuesto guarda la tarifa vigente al crearse y desglosa base e impuesto.
- Cada presupuesto copia descripción y precio de sus ítems: cambiar el catálogo después no altera los ya emitidos.
- Las decisiones solo cambian mediante acciones registradas (cliente por enlace privado o personal con sesión).
- Una aprobación no cambia el estado de la orden ni inicia trabajos: el técnico confirma el inicio."""
import hashlib
import json
import re
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

CATEGORIES = {'servicio': 'Servicios técnicos y reparaciones', 'licencia': 'Licencias de Windows y Office', 'seguridad': 'Antivirus y seguridad', 'repuesto': 'Repuestos y componentes', 'otro': 'Otros productos'}
# Categoría del presupuesto anterior de la orden a la que se traslada cada ítem aprobado (de ahí salen el total a cobrar y el saldo).
BUDGET_KEY = {'servicio': 'labor', 'repuesto': 'parts', 'licencia': 'digital', 'seguridad': 'digital', 'otro': 'services'}
STATUS = {'borrador': 'Borrador', 'enviado': 'Enviado al cliente', 'aprobado': 'Aprobado', 'parcial': 'Parcialmente aprobado', 'rechazado': 'Rechazado', 'modificacion': 'Modificación solicitada', 'cancelado': 'Cancelado'}
ITEM_STATUS = {'pendiente': 'Pendiente', 'aprobado': 'Aprobado', 'rechazado': 'Rechazado', 'cancelado': 'Cancelado'}
EDITABLE = ('borrador', 'modificacion')
DEFAULT_TAX_BP = 1500
LINK_DAYS = 15
MAX_ITEMS = 60
MAX_FAILED = 6
METHOD = 'Enlace privado enviado al correo registrado y últimos cuatro dígitos de la identificación'
CONDITIONS = ('Al aprobar y firmar este presupuesto, el cliente autoriza a PC-DOCTOR S.A. a ejecutar exclusivamente los servicios aceptados.\n'
              'Una vez iniciados los trabajos, cualquier solicitud de cancelación será evaluada según su avance y las disposiciones legales aplicables.\n'
              'En caso de desistimiento, podrán cobrarse los trabajos efectivamente realizados y los gastos debidamente justificados que legalmente correspondan.\n'
              'Los servicios no autorizados no serán ejecutados sin una aprobación posterior.')


class QuoteError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def usd(cents):
    return '$%d,%02d' % (cents // 100, cents % 100)


def cents(value, field='price'):
    """Importe en USD escrito por una persona (coma o punto decimal) a centavos."""
    try:
        amount = Decimal(str(value).strip().replace(',', '.'))
        if not amount.is_finite() or amount < 0 or amount > Decimal('999999.99') or amount.as_tuple().exponent < -2:
            raise InvalidOperation()
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise QuoteError('Indica un importe en USD, no negativo, con hasta dos decimales.', fields={field: 'Importe inválido.'})


# --- Impuesto y totales -----------------------------------------------------------------------------------------------

def tax_rate(c):
    row = c.execute("SELECT value FROM system_state WHERE key='quote_tax_bp'").fetchone()
    try:
        return max(0, min(3000, int(row['value']))) if row else DEFAULT_TAX_BP
    except (TypeError, ValueError):
        return DEFAULT_TAX_BP


def set_tax_rate(c, value):
    try:
        rate = Decimal(str(value).strip().replace(',', '.').rstrip('%'))
        if not rate.is_finite() or rate < 0 or rate > 30 or rate.as_tuple().exponent < -2:
            raise InvalidOperation()
    except (InvalidOperation, ValueError):
        raise QuoteError('Indica la tarifa de IVA entre 0 y 30 %.', fields={'tax': 'Tarifa inválida.'})
    c.execute("INSERT INTO system_state(key,value) VALUES ('quote_tax_bp',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(int(rate * 100)),))
    return int(rate * 100)


def split(line_cents, taxed, rate_bp):
    """Base e impuesto de un importe que ya incluye IVA. Un ítem con tarifa 0 % no lleva impuesto."""
    if not taxed or not rate_bp:
        return line_cents, 0
    base = (line_cents * 10000 + (10000 + rate_bp) // 2) // (10000 + rate_bp)
    return base, line_cents - base


def totals(items, rate_bp):
    """Importes cotizado, aprobado, rechazado y pendiente, con el desglose de base e IVA de lo cotizado y de lo aprobado."""
    result = {'quoted': 0, 'approved': 0, 'rejected': 0, 'pending': 0, 'cancelled': 0, 'base_taxed': 0, 'base_zero': 0, 'tax': 0, 'approved_base_taxed': 0, 'approved_base_zero': 0, 'approved_tax': 0,
              'count': {'aprobado': 0, 'rechazado': 0, 'pendiente': 0, 'cancelado': 0}}
    for item in items:
        line = item['quantity'] * item['unit_cents']
        base, tax = split(line, item['taxed'], rate_bp)
        status = item.get('status', 'pendiente')
        result['count'][status] += 1
        if status == 'cancelado':
            result['cancelled'] += line
            continue
        result['quoted'] += line
        result['tax'] += tax
        result['base_taxed' if item['taxed'] else 'base_zero'] += base
        result[{'aprobado': 'approved', 'rechazado': 'rejected', 'pendiente': 'pending'}[status]] += line
        if status == 'aprobado':
            result['approved_tax'] += tax
            result['approved_base_taxed' if item['taxed'] else 'approved_base_zero'] += base
    return result


# --- Catálogo ---------------------------------------------------------------------------------------------------------

def catalog(c, query='', only_available=False):
    rows = [dict(r) for r in c.execute('SELECT id,name,description,category,price_cents,taxed,available,updated_at FROM catalog_items ORDER BY category,name COLLATE NOCASE')]
    words = [w for w in re.sub(r'\s+', ' ', str(query or '')).strip().lower().split(' ') if w]
    return [r for r in rows if (r['available'] or not only_available) and all(w in (r['name'] + ' ' + r['description'] + ' ' + CATEGORIES[r['category']]).lower() for w in words)]


def save_catalog_item(c, data, user, now):
    name = re.sub(r'\s+', ' ', str(data.get('name', ''))).strip()
    description = str(data.get('description', '')).strip()
    category = str(data.get('category', ''))
    errors = {}
    if not 2 <= len(name) <= 120:
        errors['name'] = 'Indica un nombre de 2 a 120 caracteres.'
    if len(description) > 500:
        errors['description'] = 'La descripción admite hasta 500 caracteres.'
    if category not in CATEGORIES:
        errors['category'] = 'Selecciona una categoría.'
    try:
        price = cents(data.get('price', ''))
    except QuoteError:
        price = 0
        errors['price'] = 'Indica el precio final (con IVA incluido) en USD.'
    if errors:
        raise QuoteError('Revisa los campos señalados.', fields=errors)
    taxed, available, stamp = 1 if data.get('taxed') is not False else 0, 1 if data.get('available') is not False else 0, now.isoformat(timespec='seconds')
    item_id = str(data.get('id', ''))
    if item_id:
        if not item_id.isdigit() or not c.execute('SELECT 1 FROM catalog_items WHERE id=?', (item_id,)).fetchone():
            raise QuoteError('El elemento del catálogo ya no existe.', 404)
        c.execute('UPDATE catalog_items SET name=?,description=?,category=?,price_cents=?,taxed=?,available=?,updated_at=?,updated_by=? WHERE id=?', (name, description, category, price, taxed, available, stamp, user['id'], item_id))
        return int(item_id)
    return c.execute('INSERT INTO catalog_items(name,description,category,price_cents,taxed,available,created_at,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?)', (name, description, category, price, taxed, available, stamp, stamp, user['id'])).lastrowid


# --- Presupuestos -----------------------------------------------------------------------------------------------------

def event(c, quote_id, name, detail, now, user=None, actor=''):
    c.execute('INSERT INTO quote_events(quote_id,actor_id,actor,event,detail,created_at) VALUES (?,?,?,?,?,?)', (quote_id, user['id'] if user else None, actor or (user['name'] if user else ''), name, detail[:500], now.isoformat(timespec='seconds')))


def order_code(c, order_id):
    row = c.execute('SELECT id,code FROM orders WHERE id=?', (order_id,)).fetchone()
    if not row:
        raise QuoteError('Orden no disponible.', 404)
    return row['code'] or 'OP-%05d' % row['id']


def items_of(c, quote_id):
    return [dict(r) for r in c.execute('SELECT id,position,catalog_id,description,category,quantity,unit_cents,taxed,status FROM quote_items WHERE quote_id=? ORDER BY position,id', (quote_id,))]


def get(c, quote_id):
    row = c.execute('SELECT * FROM quotes WHERE id=?', (quote_id,)).fetchone()
    if not row:
        raise QuoteError('Presupuesto no disponible.', 404)
    return dict(row)


def detail(c, quote):
    items = items_of(c, quote['id'])
    acceptance = c.execute('SELECT signer_name,method,signature,evidence_hash,created_at FROM quote_acceptances WHERE quote_id=?', (quote['id'],)).fetchone()
    link = c.execute("SELECT created_at,expires_at,verified_at FROM quote_links WHERE quote_id=? AND revoked_at='' ORDER BY id DESC LIMIT 1", (quote['id'],)).fetchone()
    for item in items:
        item['line_cents'] = item['quantity'] * item['unit_cents']
        item['status_label'] = ITEM_STATUS[item['status']]
        item['category_label'] = CATEGORIES[item['category']]
    return dict(quote, status_label=STATUS[quote['status']], editable=quote['status'] in EDITABLE, items=items, totals=totals(items, quote['tax_rate_bp']),
                acceptance=dict(acceptance, signed=bool(acceptance['signature'])) if acceptance else None, link=dict(link) if link else None,
                events=[dict(r) for r in c.execute('SELECT event,detail,actor,created_at FROM quote_events WHERE quote_id=? ORDER BY id DESC LIMIT 60', (quote['id'],))])


def for_order(c, order_id):
    """Presupuesto vigente de la orden (su última versión) y la lista de versiones."""
    rows = [dict(r) for r in c.execute('SELECT * FROM quotes WHERE order_id=? ORDER BY version DESC', (order_id,))]
    return {'current': detail(c, rows[0]) if rows else None, 'versions': [{'id': r['id'], 'code': r['code'], 'version': r['version'], 'status': r['status'], 'status_label': STATUS[r['status']], 'created_at': r['created_at']} for r in rows],
            'tax_rate_bp': tax_rate(c), 'categories': CATEGORIES, 'conditions': CONDITIONS}


def create(c, order_id, user, now, copy_from=None):
    """Nueva versión del presupuesto de la orden: P1, P2… La anterior, si seguía abierta, queda cancelada."""
    code = order_code(c, order_id)
    last = c.execute('SELECT * FROM quotes WHERE order_id=? ORDER BY version DESC LIMIT 1', (order_id,)).fetchone()
    if last and last['status'] in ('borrador',):
        raise QuoteError('Esta orden ya tiene un presupuesto en borrador. Edítalo o cancélalo antes de crear otra versión.', 409)
    version, stamp = (last['version'] + 1 if last else 1), now.isoformat(timespec='seconds')
    quote_id = c.execute("INSERT INTO quotes(order_id,version,code,status,tax_rate_bp,created_by,created_at,updated_at) VALUES (?,?,?,'borrador',?,?,?,?)", (order_id, version, '%s-P%d' % (code, version), tax_rate(c), user['id'], stamp, stamp)).lastrowid
    if last and last['status'] in ('enviado', 'modificacion'):
        c.execute("UPDATE quotes SET status='cancelado',updated_at=? WHERE id=?", (stamp, last['id']))
        c.execute("UPDATE quote_links SET revoked_at=? WHERE quote_id=? AND revoked_at=''", (stamp, last['id']))
        event(c, last['id'], 'cancelado', 'Sustituido por la versión P%d.' % version, now, user)
    source = copy_from if copy_from is not None else (last['id'] if last else None)
    if source:
        for item in items_of(c, source):
            if item['status'] != 'cancelado':
                c.execute("INSERT INTO quote_items(quote_id,position,catalog_id,description,category,quantity,unit_cents,taxed) VALUES (?,?,?,?,?,?,?,?)", (quote_id, item['position'], item['catalog_id'], item['description'], item['category'], item['quantity'], item['unit_cents'], item['taxed']))
    event(c, quote_id, 'creado', 'Presupuesto %s-P%d creado%s.' % (code, version, ' a partir de la versión anterior' if source else ''), now, user)
    return quote_id


def save(c, quote, data, user, now):
    """Guarda el borrador: ítems, vigencia y notas. Solo mientras el presupuesto es editable."""
    if quote['status'] not in EDITABLE:
        raise QuoteError('Este presupuesto ya fue enviado o decidido. Crea una nueva versión para modificarlo.', 409)
    rows = data.get('items')
    if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
        raise QuoteError('El presupuesto admite hasta %d ítems.' % MAX_ITEMS)
    clean = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise QuoteError('Revisa los ítems del presupuesto.')
        description = re.sub(r'[ \t]+', ' ', str(row.get('description', ''))).strip()
        category = str(row.get('category', ''))
        quantity = row.get('quantity')
        unit = row.get('unit_cents')
        if not 2 <= len(description) <= 300 or category not in CATEGORIES or type(quantity) is not int or not 1 <= quantity <= 999 or type(unit) is not int or not 0 <= unit <= 99999999:
            raise QuoteError('El ítem %d necesita descripción, categoría, cantidad e importe válidos.' % (index + 1))
        catalog_id = row.get('catalog_id')
        if catalog_id is not None and (type(catalog_id) is not int or not c.execute('SELECT 1 FROM catalog_items WHERE id=?', (catalog_id,)).fetchone()):
            catalog_id = None
        clean.append((index, catalog_id, description, category, quantity, unit, 1 if row.get('taxed') is not False else 0))
    valid = str(data.get('valid_until', '')).strip()
    if valid:
        try:
            if date.fromisoformat(valid).isoformat() != valid:
                raise ValueError()
        except ValueError:
            raise QuoteError('Indica una fecha de vigencia válida.', fields={'valid_until': 'Fecha inválida.'})
    notes = str(data.get('notes', '')).strip()
    if len(notes) > 1500:
        raise QuoteError('Las observaciones admiten hasta 1500 caracteres.', fields={'notes': 'Texto demasiado largo.'})
    c.execute('DELETE FROM quote_items WHERE quote_id=?', (quote['id'],))
    c.executemany('INSERT INTO quote_items(quote_id,position,catalog_id,description,category,quantity,unit_cents,taxed) VALUES (?,?,?,?,?,?,?,?)', [(quote['id'], *row) for row in clean])
    c.execute("UPDATE quotes SET valid_until=?,notes=?,status='borrador',updated_at=? WHERE id=?", (valid, notes, now.isoformat(timespec='seconds'), quote['id']))
    event(c, quote['id'], 'guardado', 'Borrador guardado con %d %s. Total cotizado: %s.' % (len(clean), 'ítem' if len(clean) == 1 else 'ítems', usd(sum(row[4] * row[5] for row in clean))), now, user)


def send(c, quote, recipient, user, now):
    """Marca el presupuesto como enviado y crea su enlace privado. Devuelve el token (solo existe aquí)."""
    if quote['status'] not in EDITABLE + ('enviado',):
        raise QuoteError('Este presupuesto ya fue decidido o cancelado.', 409)
    items = items_of(c, quote['id'])
    if not items:
        raise QuoteError('Agrega al menos un ítem antes de enviar el presupuesto.')
    if quote['valid_until'] and quote['valid_until'] < now.date().isoformat():
        raise QuoteError('La vigencia del presupuesto ya venció. Actualízala antes de enviarlo.', fields={'valid_until': 'Fecha vencida.'})
    stamp, token = now.isoformat(timespec='seconds'), secrets.token_urlsafe(32)
    c.execute("UPDATE quote_links SET revoked_at=? WHERE quote_id=? AND revoked_at=''", (stamp, quote['id']))
    c.execute('INSERT INTO quote_links(quote_id,token_hash,created_at,expires_at) VALUES (?,?,?,?)', (quote['id'], digest(token), stamp, (now + timedelta(days=LINK_DAYS)).isoformat(timespec='seconds')))
    c.execute("UPDATE quotes SET status='enviado',conditions=?,sent_at=?,sent_to=?,updated_at=? WHERE id=?", (CONDITIONS, stamp, recipient, stamp, quote['id']))
    c.execute("UPDATE quote_items SET status='pendiente' WHERE quote_id=? AND status!='cancelado'", (quote['id'],))
    event(c, quote['id'], 'enviado', 'Enviado para aprobación a ' + recipient + '.', now, user)
    return token


def sync_budget(c, quote):
    """Traslada lo aprobado al presupuesto de la orden (del que salen el total a cobrar y el saldo). No toca pagos ni estado."""
    lines = [(BUDGET_KEY[item['category']], ('%d × ' % item['quantity'] if item['quantity'] > 1 else '') + item['description'], item['quantity'] * item['unit_cents']) for item in items_of(c, quote['id']) if item['status'] == 'aprobado']
    sums = {key: sum(amount for category, _, amount in lines if category == key) for key in ('labor', 'parts', 'services', 'digital')}
    c.execute('INSERT INTO order_budget(order_id,labor_cents,parts_cents,services_cents,digital_cents) VALUES (?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET labor_cents=excluded.labor_cents,parts_cents=excluded.parts_cents,services_cents=excluded.services_cents,digital_cents=excluded.digital_cents',
              (quote['order_id'], sums['labor'], sums['parts'], sums['services'], sums['digital']))
    c.execute('DELETE FROM order_budget_lines WHERE order_id=?', (quote['order_id'],))
    c.executemany('INSERT INTO order_budget_lines(order_id,category,description,amount_cents) VALUES (?,?,?,?)', [(quote['order_id'], category, description[:250], amount) for category, description, amount in lines])


def decide(c, quote, decisions, now, user=None, actor='', note=''):
    """Registra la decisión sobre cada ítem pendiente. `decisions`: {id de ítem: 'aprobado' | 'rechazado'}."""
    if quote['status'] != 'enviado':
        raise QuoteError('Este presupuesto no está pendiente de decisión.', 409)
    items = [item for item in items_of(c, quote['id']) if item['status'] != 'cancelado']
    if set(decisions) != {item['id'] for item in items} or any(value not in ('aprobado', 'rechazado') for value in decisions.values()):
        raise QuoteError('Indica si apruebas o rechazas cada uno de los ítems.')
    paid = c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM order_payments WHERE order_id=? AND voided_at IS NULL', (quote['order_id'],)).fetchone()[0]
    approved_total = sum(item['quantity'] * item['unit_cents'] for item in items if decisions[item['id']] == 'aprobado')
    if paid > approved_total:
        raise QuoteError('La orden ya tiene pagos registrados por %s, más que el total aprobado (%s). Revisa los pagos antes de registrar esta decisión.' % (usd(paid), usd(approved_total)), 409)
    for item in items:
        c.execute('UPDATE quote_items SET status=? WHERE id=?', (decisions[item['id']], item['id']))
    approved = sum(1 for value in decisions.values() if value == 'aprobado')
    status, stamp = ('aprobado' if approved == len(items) else 'rechazado' if not approved else 'parcial'), now.isoformat(timespec='seconds')
    c.execute('UPDATE quotes SET status=?,decided_at=?,decided_by=?,updated_at=? WHERE id=?', (status, stamp, 'cliente' if not user else 'personal:%d' % user['id'], stamp, quote['id']))
    c.execute("UPDATE quote_links SET revoked_at=? WHERE quote_id=? AND revoked_at=''", (stamp, quote['id']))
    sync_budget(c, quote)
    event(c, quote['id'], status, '%d de %d ítems aprobados. Total autorizado: %s.%s' % (approved, len(items), usd(approved_total), ' ' + note if note else ''), now, user, actor)
    return status


def cancel(c, quote, user, now, reason=''):
    if quote['status'] in ('cancelado',):
        raise QuoteError('El presupuesto ya estaba cancelado.', 409)
    if quote['status'] in ('aprobado', 'parcial'):
        raise QuoteError('Un presupuesto con servicios aprobados no se cancela: crea una nueva versión si cambian los trabajos.', 409)
    stamp = now.isoformat(timespec='seconds')
    c.execute("UPDATE quotes SET status='cancelado',updated_at=? WHERE id=?", (stamp, quote['id']))
    c.execute("UPDATE quote_links SET revoked_at=? WHERE quote_id=? AND revoked_at=''", (stamp, quote['id']))
    event(c, quote['id'], 'cancelado', 'Presupuesto cancelado.' + (' Motivo: ' + reason[:300] if reason else ''), now, user)


# --- Aprobación del cliente por enlace privado ------------------------------------------------------------------------

def lookup(c, token, now):
    """Presupuesto del enlace, o None si el enlace no existe, venció o fue revocado."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{30,80}', token or ''):
        return None, None
    link = c.execute('SELECT * FROM quote_links WHERE token_hash=?', (digest(token),)).fetchone()
    if not link:
        return None, None
    quote = get(c, link['quote_id'])
    # Un enlace revocado sigue sirviendo para consultar el resultado ya registrado, nunca para decidir de nuevo.
    usable = not link['revoked_at'] and datetime.fromisoformat(link['expires_at']) >= now and link['failed'] < MAX_FAILED
    return quote, dict(link, usable=usable)


def verify(c, link, identification, last4, now):
    """Comprobación de identidad: últimos cuatro dígitos de la identificación registrada del cliente."""
    number = re.sub(r'\D', '', str(identification or ''))
    if len(number) < 6:
        raise QuoteError('El cliente no tiene una identificación registrada con la que comprobar su identidad. Comunícate con el taller.', 409)
    if not re.fullmatch(r'\d{4}', str(last4 or '')) or not secrets.compare_digest(number[-4:], str(last4)):
        c.execute('UPDATE quote_links SET failed=failed+1 WHERE id=?', (link['id'],))
        return False
    return True


def clean_signature(raw):
    """Firma manuscrita como trazos vectoriales [[x,y],…] en una rejilla de 1000 × 300. Vacía si no es válida."""
    try:
        strokes = json.loads(raw) if isinstance(raw, str) and raw else []
    except ValueError:
        return []
    if not isinstance(strokes, list) or len(strokes) > 80:
        return []
    clean, points = [], 0
    for stroke in strokes:
        if not isinstance(stroke, list):
            return []
        line = [[int(p[0]), int(p[1])] for p in stroke if isinstance(p, list) and len(p) == 2 and all(type(v) in (int, float) for v in p) and 0 <= p[0] <= 1000 and 0 <= p[1] <= 300]
        points += len(line)
        if len(line) >= 2:
            clean.append(line)
    return clean if points <= 4000 and sum(len(line) for line in clean) >= 8 else []


def accept(c, quote, link, form, order, now, origin):
    """Decisión del cliente con su evidencia. `form`: decision_<id>, accept, name, signature, comment, action."""
    if quote['status'] != 'enviado' or not link['usable']:
        raise QuoteError('Este presupuesto ya no admite una decisión desde este enlace.', 409)
    items = [item for item in items_of(c, quote['id']) if item['status'] != 'cancelado']
    comment = str(form.get('comment', '')).strip()[:600]
    if form.get('action') == 'change':
        if len(comment) < 5:
            raise QuoteError('Describe qué cambio necesitas en el presupuesto.', fields={'comment': 'Escribe tu solicitud.'})
        stamp = now.isoformat(timespec='seconds')
        c.execute("UPDATE quotes SET status='modificacion',updated_at=? WHERE id=?", (stamp, quote['id']))
        c.execute("UPDATE quote_links SET revoked_at=? WHERE id=?", (stamp, link['id']))
        event(c, quote['id'], 'modificacion', 'El cliente solicitó una modificación: ' + comment, now, actor='Cliente')
        return 'modificacion'
    decisions = {item['id']: form.get('decision_%d' % item['id'], '') for item in items}
    errors = {}
    if any(value not in ('aprobado', 'rechazado') for value in decisions.values()):
        errors['items'] = 'Indica si apruebas o rechazas cada servicio.'
    name = re.sub(r'\s+', ' ', str(form.get('name', ''))).strip()
    if not 5 <= len(name) <= 120:
        errors['name'] = 'Escribe tu nombre completo.'
    if form.get('accept') != 'on':
        errors['accept'] = 'Debes aceptar expresamente las condiciones.'
    signature = clean_signature(form.get('signature', ''))
    approving = any(value == 'aprobado' for value in decisions.values())
    if approving and not signature:
        errors['signature'] = 'Firma en el recuadro para autorizar los servicios aprobados.'
    if errors:
        raise QuoteError('Revisa los datos señalados.', fields=errors)
    status = decide(c, quote, decisions, now, actor='Cliente: ' + name, note=('Observación del cliente: ' + comment) if comment else '')
    final = items_of(c, quote['id'])
    evidence = {'quote': quote['code'], 'order': order['code'], 'signer': name, 'method': METHOD, 'accepted_at': now.isoformat(timespec='seconds'), 'conditions': quote['conditions'] or CONDITIONS, 'comment': comment,
                'tax_rate_bp': quote['tax_rate_bp'], 'items': [{'description': item['description'], 'quantity': item['quantity'], 'unit_cents': item['unit_cents'], 'taxed': bool(item['taxed']), 'decision': item['status']} for item in final],
                'totals': {key: value for key, value in totals(final, quote['tax_rate_bp']).items() if key != 'count'}, 'signature_points': sum(len(line) for line in signature), 'ip': origin.get('ip', ''), 'agent': origin.get('agent', '')}
    payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    c.execute('INSERT INTO quote_acceptances(quote_id,signer_name,method,signature,evidence,evidence_hash,created_at) VALUES (?,?,?,?,?,?,?)', (quote['id'], name, METHOD, json.dumps(signature), payload, digest(payload + json.dumps(signature)), now.isoformat(timespec='seconds')))
    return status


def evidence_ok(c, quote_id):
    row = c.execute('SELECT evidence,signature,evidence_hash FROM quote_acceptances WHERE quote_id=?', (quote_id,)).fetchone()
    return bool(row) and digest(row['evidence'] + row['signature']) == row['evidence_hash']


# --- Páginas del enlace privado ---------------------------------------------------------------------------------------

def _shell(title, body):
    import html
    from corporate import settings
    company = settings()
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta name="robots" content="noindex,nofollow">'
            '<title>%s | PC-DOCTOR S.A.</title><link rel="icon" href="/favicon.ico?v=2" sizes="48x48"><link rel="stylesheet" href="/static/tracking.css"><link rel="stylesheet" href="/static/quote.css"><script defer src="/static/quote-sign.js"></script></head>'
            '<body><main class="tracking-page quote-page"><header><img src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="150"><p>%s</p></header>%s'
            '<footer><p>WhatsApp: %s</p><p class="tracking-note">La firma de esta página es un trazo manuscrito digitalizado con registro de fecha, hora y método de verificación. No es una firma electrónica certificada.</p></footer></main></body></html>'
            ) % (html.escape(title), html.escape(company['specialty']), body, html.escape(company['whatsapp']))


def missing_page():
    return _shell('Enlace no disponible', '<section class="tracking-card"><h1>Enlace no disponible</h1><p>Este enlace de presupuesto no existe, venció o fue reemplazado por una versión más reciente. Comunícate con el taller.</p></section>')


def _summary_block(quote, order):
    import html
    e = html.escape
    device = ' '.join(part for part in (order.get('brand') or '', order.get('model') or '') if part) or 'Equipo'
    return '<small>PRESUPUESTO</small><h1>%s</h1><p class="quote-device">Orden %s · %s</p>' % (e(quote['code']), e(order['code']), e(device))


def identify_page(token, quote, order, error=''):
    import html
    return _shell('Presupuesto ' + quote['code'], '<section class="tracking-card quote-card">%s<form class="auth-form" method="post" action="/presupuesto/%s" autocomplete="off">%s'
                  '<p class="auth-step">Paso 1 de 2 · Comprueba tu identidad</p><label for="last4">Escribe los <strong>últimos cuatro dígitos</strong> de tu cédula o RUC</label>'
                  '<input id="last4" name="last4" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" required autofocus><button class="quote-primary" type="submit">Ver mi presupuesto</button></form></section>'
                  % (_summary_block(quote, order), html.escape(token), '<p class="quote-error" role="alert">%s</p>' % html.escape(error) if error else ''))


def decision_page(token, passkey, quote, order, items, errors=None, form=None):
    import html
    e, errors, form = html.escape, errors or {}, form or {}
    summary = totals(items, quote['tax_rate_bp'])
    rows = ''
    for item in items:
        if item['status'] == 'cancelado':
            continue
        chosen = form.get('decision_%d' % item['id'], '')
        rows += ('<fieldset class="quote-item"><legend>%s</legend><p class="quote-amount">%s%s · <strong>%s</strong>%s</p>'
                 '<label><input type="radio" name="decision_%d" value="aprobado"%s required> Apruebo este servicio</label>'
                 '<label><input type="radio" name="decision_%d" value="rechazado"%s> No lo apruebo</label></fieldset>'
                 ) % (e(item['description']), '%d × ' % item['quantity'] if item['quantity'] > 1 else '', e(usd(item['unit_cents'])), e(usd(item['quantity'] * item['unit_cents'])), '' if item['taxed'] else ' <small>(tarifa 0 %)</small>',
                      item['id'], ' checked' if chosen == 'aprobado' else '', item['id'], ' checked' if chosen == 'rechazado' else '')
    problem = lambda key: '<p class="quote-error" role="alert">%s</p>' % e(errors[key]) if errors.get(key) else ''
    rate = quote['tax_rate_bp'] / 100
    conditions = ''.join('<li>%s</li>' % e(line) for line in (quote['conditions'] or CONDITIONS).split('\n'))
    body = ('<section class="tracking-card quote-card">%s<p class="quote-valid">%s</p>'
            '<form class="auth-form quote-form" method="post" action="/presupuesto/%s" autocomplete="off"><input type="hidden" name="passkey" value="%s">'
            '<p class="auth-step">Paso 2 de 2 · Revisa y decide cada servicio</p><div class="quote-bulk"><button type="button" data-quote-all="aprobado">Aprobar todo</button><button type="button" data-quote-all="rechazado">Rechazar todo</button></div>%s%s'
            '<dl class="quote-totals"><div><dt>Subtotal con IVA %g %%</dt><dd>%s</dd></div><div><dt>Subtotal tarifa 0 %%</dt><dd>%s</dd></div><div><dt>IVA %g %%</dt><dd>%s</dd></div><div class="quote-total"><dt>Total cotizado</dt><dd>%s</dd></div>'
            '<div class="quote-chosen"><dt>Total que apruebas</dt><dd data-quote-approved>—</dd></div></dl>'
            '<h2>Condiciones de autorización</h2><ul class="quote-conditions">%s</ul>'
            '<label for="name">Nombre completo de quien autoriza</label><input id="name" name="name" maxlength="120" value="%s" required>%s'
            '<label for="comment">Observaciones (opcional)</label><textarea id="comment" name="comment" rows="2" maxlength="600">%s</textarea>%s'
            '<p class="quote-sign-label">Firma con el dedo o el ratón dentro del recuadro</p><div class="quote-sign" data-quote-sign><canvas width="1000" height="300" aria-label="Recuadro de firma"></canvas><button type="button" data-quote-clear>Borrar firma</button></div><input type="hidden" name="signature" value="">%s'
            '<label class="quote-accept"><input type="checkbox" name="accept"%s required> He leído los importes y las condiciones, y confirmo mi decisión sobre cada servicio.</label>%s'
            '<button class="quote-primary" type="submit" name="action" value="decide">Confirmar mi decisión</button>'
            '<button class="quote-secondary" type="submit" name="action" value="change" formnovalidate>Solicitar una modificación</button></form>'
            '<p class="quote-pdf"><a href="/presupuesto/%s/documento.pdf?k=%s">Descargar el presupuesto en PDF</a></p></section>'
            ) % (_summary_block(quote, order), 'Válido hasta el ' + e(date.fromisoformat(quote['valid_until']).strftime('%d/%m/%Y')) if quote['valid_until'] else 'Sin fecha límite indicada', e(token), e(passkey), problem('items'), rows,
                 rate, e(usd(summary['base_taxed'])), e(usd(summary['base_zero'])), rate, e(usd(summary['tax'])), e(usd(summary['quoted'])), conditions, e(form.get('name', '')), problem('name'), e(form.get('comment', '')), problem('comment'), problem('signature'),
                 ' checked' if form.get('accept') == 'on' else '', problem('accept'), e(token), e(passkey))
    return _shell('Presupuesto ' + quote['code'], body)


def result_page(token, quote, order, items):
    import html
    e = html.escape
    summary = totals(items, quote['tax_rate_bp'])
    lines = ''.join('<li data-status="%s"><span>%s</span><strong>%s</strong><em>%s</em></li>' % (e(item['status']), e(item['description']), e(usd(item['quantity'] * item['unit_cents'])), e(ITEM_STATUS[item['status']])) for item in items if item['status'] != 'cancelado')
    message = {'modificacion': 'Recibimos tu solicitud de modificación. El taller revisará el presupuesto y te enviará una nueva versión.', 'rechazado': 'Registramos que no apruebas este presupuesto. No se ejecutará ningún trabajo sin tu autorización.',
               'cancelado': 'Este presupuesto fue cancelado por el taller.'}.get(quote['status'], 'Registramos tu decisión. El taller ejecutará únicamente los servicios aprobados y te avisará del avance.')
    extra = '<dl class="quote-totals"><div><dt>Total cotizado</dt><dd>%s</dd></div><div class="quote-total"><dt>Total aprobado</dt><dd>%s</dd></div><div><dt>Importe rechazado</dt><dd>%s</dd></div></dl>' % (e(usd(summary['quoted'])), e(usd(summary['approved'])), e(usd(summary['rejected']))) if quote['status'] in ('aprobado', 'parcial', 'rechazado') else ''
    return _shell('Presupuesto ' + quote['code'], '<section class="tracking-card quote-card">%s<p class="tracking-state quote-state" data-status="%s">%s</p><p>%s</p><ul class="quote-result">%s</ul>%s</section>' % (_summary_block(quote, order), e(quote['status']), e(STATUS[quote['status']]), e(message), lines, extra))


def handle(c, token, quote, link, order, form, now, origin):
    """Atiende el formulario del enlace. Devuelve (página HTML, estado nuevo o None)."""
    items = items_of(c, quote['id'])
    if quote['status'] != 'enviado' or not link['usable']:
        return (result_page(token, quote, order, items) if quote['status'] != 'enviado' else missing_page()), None
    passkey = str(form.get('passkey', ''))
    if not passkey:
        # Paso 1: comprobación de identidad. Al acertar se emite una llave de un solo uso para el paso 2 (treinta minutos).
        if not verify(c, link, order.get('identification'), form.get('last4'), now):
            return identify_page(token, quote, order, 'Los dígitos no coinciden con la identificación registrada.'), None
        passkey = secrets.token_urlsafe(24)
        c.execute('UPDATE quote_links SET verified_at=?,passkey_hash=?,failed=0 WHERE id=?', (now.isoformat(timespec='seconds'), digest(passkey), link['id']))
        return decision_page(token, passkey, quote, order, items), None
    if not valid_passkey(link, passkey, now):
        return identify_page(token, quote, order, 'La comprobación de identidad caducó. Vuelve a escribir los cuatro dígitos.'), None
    try:
        status = accept(c, quote, link, form, order, now, origin)
    except QuoteError as error:
        if not error.fields:
            return identify_page(token, quote, order, str(error)), None
        return decision_page(token, passkey, quote, order, items, error.fields, form), None
    return result_page(token, get(c, quote['id']), order, items_of(c, quote['id'])), status


def valid_passkey(link, passkey, now):
    if not link.get('passkey_hash') or not link.get('verified_at') or not secrets.compare_digest(link['passkey_hash'], digest(str(passkey))):
        return False
    return datetime.fromisoformat(link['verified_at']) + timedelta(minutes=30) >= now
