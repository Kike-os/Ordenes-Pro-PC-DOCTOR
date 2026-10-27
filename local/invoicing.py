"""Facturación electrónica integrada en Órdenes Pro: de la orden pagada (presupuesto aprobado) o de la venta de licencias pagada a la
factura del SRI.

Reglas que se aplican SIEMPRE en el servidor (la interfaz solo las refleja):
- Una sola factura vigente por operación (índice único en la base; un borrador descartado no cuenta).
- Consumidor final solo si el total, con impuestos y en centavos, es de hasta USD 50,00 (ficha técnica SRI v2.34, 9.10).
- La emisión solo existe en el ambiente de PRUEBAS del SRI. La emisión real no está implementada ni activable desde la interfaz.
- Los precios del catálogo y de los presupuestos ya incluyen el IVA: la base y el impuesto se descomponen por línea de forma exacta.
- Un comprobante emitido no se modifica (disparadores en la base) y todo queda en un historial inmutable."""
import json
import re
from datetime import datetime

import quotes
import reception
import sri_xml

CONSUMER_FINAL_LIMIT_CENTS = 5000  # «Si el valor de la factura es mayor a 50 USD se deberá especificar obligatoriamente los datos del adquirente»
STATUS = {'borrador': 'Borrador', 'pendiente': 'Pendiente', 'enviado': 'Enviado', 'autorizado': 'Autorizado', 'rechazado': 'Rechazado', 'descartado': 'Descartado'}
REGIMES = {'general': 'Régimen General', 'rimpe_emprendedor': 'RIMPE Emprendedor', 'rimpe_negocio_popular': 'RIMPE Negocio Popular'}
# Forma de pago del SRI (tabla 24) según el método registrado en Órdenes Pro. Pendiente de confirmar con el contador (tarjeta de débito = 16).
PAYMENT_CODES = {'efectivo': '01', 'transferencia': '20', 'deposito': '20', 'tarjeta': '19', 'otro': '20'}
PAYMENT_LABELS = {'01': 'Sin utilización del sistema financiero', '16': 'Tarjeta de débito', '19': 'Tarjeta de crédito', '20': 'Otros con utilización del sistema financiero'}
TEST_ENVIRONMENT = '1'
# MODO DE PRUEBAS del centro de Facturación Electrónica (hasta la firma electrónica y la autorización de activación real):
# - todo lo que se registre (facturas, cajas, depósitos, inventario, compras, proveedores, cuentas) queda en las tablas propias del
#   módulo, que se vaciarán con respaldo previo al activarlo; ningún registro existente se modifica;
# - los clientes no ven ningún cambio: los datos bancarios no aparecen en la página ni en el PDF del presupuesto;
# - solo administración usa el módulo, incluida la caja.
TEST_MODE = True


class InvoiceError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def stamp(now):
    return now.isoformat(timespec='seconds')


def _half(numerator, denominator):
    return (2 * numerator + denominator) // (2 * denominator)


def split_inclusive(amount_cents, rate_bp):
    """Base e IVA de un importe que ya incluye el IVA, de modo que base + round(base × tarifa) = importe (lo que valida el SRI).
    Algunos importes no tienen una base exacta: se usa la más cercana y se marca el ajuste de un centavo para revisarlo."""
    if not rate_bp:
        return amount_cents, 0, False
    guess = _half(amount_cents * 10000, 10000 + rate_bp)
    for base in (guess, guess - 1, guess + 1, guess - 2, guess + 2):
        if base >= 0 and base + _half(base * rate_bp, 10000) == amount_cents:
            return base, amount_cents - base, False
    return guess, amount_cents - guess, True


def settings(c):
    row = dict(c.execute('SELECT * FROM invoice_settings WHERE id=1').fetchone())
    row['regime_label'] = REGIMES.get(row['regime'], 'Sin definir')
    row['missing'] = missing_settings(row)
    row['test_mode'] = TEST_MODE
    row['emission'] = {'environment': TEST_ENVIRONMENT, 'environment_label': 'Pruebas (SRI)', 'real_enabled': False,
                       'note': 'Todo lo que se registre aquí es de prueba: no cambia clientes, órdenes, presupuestos ni pagos, y no se envía nada al SRI.'}
    return row


def missing_settings(row):
    need = {'ruc': 'RUC', 'legal_name': 'Razón social', 'head_office_address': 'Dirección de la matriz', 'keeps_accounts': 'Obligado a llevar contabilidad', 'regime': 'Régimen tributario'}
    return [label for key, label in need.items() if not str(row.get(key) or '').strip()]


def save_settings(c, data, user, now):
    """Datos fiscales de la empresa (solo administración). Se validan aquí; nunca se inventan ni se completan solos."""
    clean, errors = {}, {}
    text = lambda key, size: re.sub(r'\s+', ' ', str(data.get(key, '') or '')).strip()[:size]
    ruc = re.sub(r'\D', '', str(data.get('ruc', '')))
    if ruc:
        problem, _ = reception.document_check(ruc, 'ruc')
        if problem:
            errors['ruc'] = problem
    clean['ruc'] = ruc
    for key, size in (('legal_name', 300), ('trade_name', 300), ('head_office_address', 300), ('branch_address', 300)):
        clean[key] = text(key, size)
    for key in ('establishment', 'emission_point'):
        value = str(data.get(key, '') or '').strip()
        if not re.fullmatch(r'\d{3}', value) or value == '000':
            errors[key] = 'Tres dígitos, por ejemplo 001.'
        clean[key] = value
    clean['keeps_accounts'] = str(data.get('keeps_accounts', '')).upper() if str(data.get('keeps_accounts', '')).upper() in ('SI', 'NO') else ''
    clean['regime'] = data.get('regime') if data.get('regime') in REGIMES else ''
    special = re.sub(r'\D', '', str(data.get('special_taxpayer', '')))
    if special and not 3 <= len(special) <= 13:
        errors['special_taxpayer'] = 'Número de resolución de 3 a 13 dígitos.'
    clean['special_taxpayer'] = special
    clean['withholding_agent'] = re.sub(r'\D', '', str(data.get('withholding_agent', '')))[:8]
    if errors:
        raise InvoiceError('Revisa los datos fiscales señalados.', fields=errors)
    c.execute('UPDATE invoice_settings SET ruc=?,legal_name=?,trade_name=?,head_office_address=?,branch_address=?,establishment=?,emission_point=?,keeps_accounts=?,special_taxpayer=?,regime=?,'
              'withholding_agent=?,updated_at=?,updated_by=? WHERE id=1', (clean['ruc'], clean['legal_name'], clean['trade_name'], clean['head_office_address'], clean['branch_address'],
                                                                       clean['establishment'], clean['emission_point'], clean['keeps_accounts'], clean['special_taxpayer'], clean['regime'],
                                                                       clean['withholding_agent'], stamp(now), user['id']))
    return settings(c)


# ---- Origen de la factura ------------------------------------------------------------------------------------------------

def _line(position, code, description, quantity, gross_incl, net_incl, rate_bp, source_item_id=None, catalog_id=None):
    """Línea del SRI a partir de importes con IVA incluido (antes y después del descuento)."""
    base, tax, adjusted = split_inclusive(net_incl, rate_bp)
    gross_base = split_inclusive(gross_incl, rate_bp)[0]
    discount = max(0, gross_base - base)
    return {'position': position, 'code': code or 'ITEM-%02d' % position, 'description': re.sub(r'\s+', ' ', description).strip()[:300], 'quantity': quantity,
            'unit_price_micros': _half(gross_base * 10000, quantity), 'discount_cents': discount, 'base_cents': base,
            'tax_code': sri_xml.IVA_CODES.get(rate_bp, '4' if rate_bp else '0'), 'tax_rate_bp': rate_bp, 'tax_cents': tax, 'total_cents': base + tax,
            'adjusted': adjusted, 'source_item_id': source_item_id, 'catalog_id': catalog_id}


def _order_source(c, order_id):
    """Partidas autorizadas del presupuesto y pagos del equipo. Solo se factura un equipo totalmente pagado y sin cargos manuales sin IVA definido."""
    import equipment
    order = c.execute('SELECT o.id,o.code,d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?', (order_id,)).fetchone()
    if not order:
        raise InvoiceError('La orden no existe.', 404)
    found = quotes.authorized(c, order_id)
    blockers = []
    if not found:
        blockers.append('La orden no tiene un presupuesto aprobado.')
    money = equipment.money(c, order_id)
    items = found['items'] if found else []
    approved = sum(item['net_cents'] for item in items)
    if items and money['budget_cents'] != approved:
        blockers.append('El total a cobrar (%s) incluye cargos manuales sin IVA definido: no coincide con lo aprobado (%s).' % (quotes.usd(money['budget_cents']), quotes.usd(approved)))
    if money['budget_cents'] <= 0 or money['paid_cents'] < money['budget_cents']:
        blockers.append('La orden no está totalmente pagada (saldo %s).' % quotes.usd(max(0, money['budget_cents'] - money['paid_cents'])))
    rates = {row['id']: (row['tax_rate_bp'], row['discount_bp']) for row in c.execute('SELECT id,tax_rate_bp,discount_bp FROM quotes WHERE order_id=?', (order_id,))}
    lines = []
    for n, item in enumerate(items, 1):
        rate_bp, discount_bp = rates[item['quote_id']]
        gross = item['quantity'] * item['unit_cents']
        lines.append(_line(n, item.get('reference') or '', item['description'], item['quantity'], gross, item['net_cents'], rate_bp if item['taxed'] else 0, item['id'], item.get('catalog_id')))
    payments = {}
    for row in c.execute("SELECT p.method,SUM(CASE p.kind WHEN 'devolucion' THEN -p.amount_cents ELSE p.amount_cents END) total FROM order_payments p WHERE p.order_id=? AND p.scope='equipo' AND p.voided_at IS NULL GROUP BY p.method", (order_id,)):
        payments[row['method']] = payments.get(row['method'], 0) + row['total']
    for row in c.execute('SELECT p.method,SUM(a.amount_cents) total FROM order_payment_allocations a JOIN order_payments p ON p.id=a.payment_id WHERE a.order_id=? AND p.voided_at IS NULL GROUP BY p.method', (order_id,)):
        payments[row['method']] = payments.get(row['method'], 0) + row['total']
    return {'kind': 'orden', 'id': order_id, 'order_id': order_id, 'quote_id': items[0]['quote_id'] if items else None, 'license_sale_id': None, 'client_id': order['client_id'],
            'reference': order['code'], 'lines': lines, 'payments': payments, 'blockers': blockers}


def _sale_source(c, sale_id):
    sale = c.execute('SELECT * FROM license_sales WHERE id=?', (sale_id,)).fetchone()
    if not sale:
        raise InvoiceError('La venta no existe.', 404)
    blockers = []
    if sale['cancelled_at']:
        blockers.append('La venta está cancelada.')
    if sale['payment_status'] != 'pagado':
        blockers.append('La venta no está totalmente pagada.')
    lines = []
    for n, item in enumerate(c.execute('SELECT s.*,i.code,i.taxed FROM license_sale_items s JOIN catalog_items i ON i.id=s.product_id WHERE s.sale_id=? ORDER BY s.position,s.id', (sale_id,)), 1):
        gross = item['quantity'] * item['unit_price_cents']
        lines.append(_line(n, item['code'] or '', item['product_name'], item['quantity'], gross, gross - item['discount_cents'], quotes.tax_rate(c) if item['taxed'] else 0, item['id'], item['product_id']))
    if sale['discount_cents'] and lines:
        blockers.append('La venta tiene un descuento general: todavía no se reparte entre las partidas de la factura.')
    payments = {}
    for row in c.execute("SELECT method,SUM(amount_cents) total FROM license_sale_payments WHERE sale_id=? AND status='confirmado' GROUP BY method", (sale_id,)):
        payments[row['method']] = row['total']
    return {'kind': 'venta_licencia', 'id': sale_id, 'order_id': sale['order_id'], 'quote_id': None, 'license_sale_id': sale_id, 'client_id': sale['client_id'],
            'reference': sale['code'], 'lines': lines, 'payments': payments, 'blockers': blockers}


def source(c, kind, source_id):
    if kind == 'orden':
        return _order_source(c, source_id)
    if kind == 'venta_licencia':
        return _sale_source(c, source_id)
    raise InvoiceError('Origen de factura no válido.')


def _payments_for(total, by_method):
    """Formas de pago del SRI que suman exactamente el total (lo pagado de más no se factura)."""
    out, left = [], total
    for method, amount in sorted(by_method.items(), key=lambda kv: -kv[1]):
        take = min(left, max(0, amount))
        if take > 0:
            out.append({'method': method, 'sri_code': PAYMENT_CODES.get(method, '20'), 'amount_cents': take})
            left -= take
    if left > 0:
        out.append({'method': 'otro', 'sri_code': '20', 'amount_cents': left})
    merged = {}
    for item in out:
        key = item['sri_code']
        merged.setdefault(key, {'method': item['method'], 'sri_code': key, 'amount_cents': 0})['amount_cents'] += item['amount_cents']
    return list(merged.values())


def totals(lines):
    subtotal = sum(line['base_cents'] for line in lines)
    tax = sum(line['tax_cents'] for line in lines)
    return {'subtotal_cents': subtotal, 'discount_cents': sum(line['discount_cents'] for line in lines), 'tax_cents': tax, 'total_cents': subtotal + tax,
            'by_rate': {line['tax_rate_bp']: [0, 0] for line in lines}}


def consumer_final_allowed(total_cents):
    return 0 < total_cents <= CONSUMER_FINAL_LIMIT_CENTS


def _buyer_from_client(c, client_id):
    row = c.execute('SELECT name,identification,document_type,address,main_street,email,phone FROM clients WHERE id=?', (client_id,)).fetchone() if client_id else None
    if not row:
        return {'buyer_id_type': '', 'buyer_id': '', 'buyer_name': '', 'buyer_address': '', 'buyer_email': '', 'buyer_phone': ''}
    ident = re.sub(r'\s', '', row['identification'] or '')
    kind = {'cedula': '05', 'ruc': '04', 'pasaporte': '06'}.get(row['document_type'] or '', '05' if len(ident) == 10 else '04' if len(ident) == 13 else '06')
    return {'buyer_id_type': kind, 'buyer_id': ident, 'buyer_name': row['name'] or '', 'buyer_address': (row['address'] or row['main_street'] or '')[:300],
            'buyer_email': row['email'] or '', 'buyer_phone': row['phone'] or ''}


def event(c, invoice_id, name, detail, now, user=None, actor=''):
    c.execute('INSERT INTO invoice_events(invoice_id,event,detail,actor_id,actor,created_at) VALUES (?,?,?,?,?,?)',
              (invoice_id, name, detail[:1000], user['id'] if user else None, actor or (user['name'] if user else 'Sistema'), stamp(now)))


# ---- Borrador, comprador y emisión -----------------------------------------------------------------------------------------

def current(c, kind, source_id):
    return c.execute("SELECT * FROM invoices WHERE source_kind=? AND source_id=? AND environment=? AND status!='descartado'", (kind, source_id, TEST_ENVIRONMENT)).fetchone()


def eligibility(c, kind, source_id):
    """Para la interfaz: si se puede generar la factura de esta operación y, si ya existe, cuál es."""
    existing = current(c, kind, source_id)
    found = source(c, kind, source_id)
    return {'invoice': brief(existing) if existing else None, 'can_generate': not found['blockers'] and bool(found['lines']), 'blockers': found['blockers'],
            'total_cents': totals(found['lines'])['total_cents'] if found['lines'] else 0}


def brief(row):
    row = dict(row)
    return {'id': row['id'], 'status': row['status'], 'status_label': STATUS[row['status']], 'number': number(row), 'total_cents': row['total_cents'], 'environment': row['environment']}


def number(row):
    return '%s-%s-%09d' % (row['establishment'], row['emission_point'], row['sequential']) if row['sequential'] else ''


def _write_lines(c, invoice_id, lines):
    c.execute('DELETE FROM invoice_items WHERE invoice_id=?', (invoice_id,))
    for line in lines:
        c.execute('INSERT INTO invoice_items(invoice_id,position,code,description,quantity,unit_price_micros,discount_cents,base_cents,tax_code,tax_rate_bp,tax_cents,total_cents,source_item_id,catalog_id) '
                  'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (invoice_id, line['position'], line['code'], line['description'], line['quantity'], line['unit_price_micros'], line['discount_cents'],
                                                         line['base_cents'], line['tax_code'], line['tax_rate_bp'], line['tax_cents'], line['total_cents'], line['source_item_id'], line['catalog_id']))


def draft(c, kind, source_id, user, now):
    """Borrador de la factura de una operación pagada. Idempotente: si ya hay una factura vigente, la devuelve (no crea otra)."""
    existing = current(c, kind, source_id)
    if existing:
        if existing['status'] == 'borrador':
            refresh(c, existing['id'], now)
        return existing['id']
    found = source(c, kind, source_id)
    if found['blockers']:
        raise InvoiceError(' '.join(found['blockers']), 409)
    if not found['lines']:
        raise InvoiceError('No hay partidas que facturar.', 409)
    t = totals(found['lines'])
    buyer = _buyer_from_client(c, found['client_id'])
    cfg = settings(c)
    invoice_id = c.execute('INSERT INTO invoices(status,environment,source_kind,source_id,order_id,quote_id,license_sale_id,client_id,buyer_id_type,buyer_id,buyer_name,buyer_address,buyer_email,buyer_phone,'
                           'subtotal_cents,discount_cents,tax_cents,total_cents,establishment,emission_point,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           ('borrador', TEST_ENVIRONMENT, kind, source_id, found['order_id'], found['quote_id'], found['license_sale_id'], found['client_id'], buyer['buyer_id_type'], buyer['buyer_id'],
                            buyer['buyer_name'], buyer['buyer_address'], buyer['buyer_email'], buyer['buyer_phone'], t['subtotal_cents'], t['discount_cents'], t['tax_cents'], t['total_cents'],
                            cfg['establishment'], cfg['emission_point'], user['id'], stamp(now), stamp(now))).lastrowid
    _write_lines(c, invoice_id, found['lines'])
    for p in _payments_for(t['total_cents'], found['payments']):
        c.execute('INSERT INTO invoice_payments(invoice_id,method,sri_code,amount_cents) VALUES (?,?,?,?)', (invoice_id, p['method'], p['sri_code'], p['amount_cents']))
    event(c, invoice_id, 'creado', 'Borrador generado desde %s %s. Total %s.' % ('la orden' if kind == 'orden' else 'la venta', found['reference'], quotes.usd(t['total_cents'])), now, user)
    return invoice_id


def refresh(c, invoice_id, now):
    """Un borrador se mantiene igual a su origen (partidas, importes y pagos) hasta que se emite."""
    inv = c.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,)).fetchone()
    if not inv or inv['status'] != 'borrador':
        return
    found = source(c, inv['source_kind'], inv['source_id'])
    t = totals(found['lines'])
    _write_lines(c, invoice_id, found['lines'])
    c.execute('DELETE FROM invoice_payments WHERE invoice_id=?', (invoice_id,))
    for p in _payments_for(t['total_cents'], found['payments']):
        c.execute('INSERT INTO invoice_payments(invoice_id,method,sri_code,amount_cents) VALUES (?,?,?,?)', (invoice_id, p['method'], p['sri_code'], p['amount_cents']))
    consumer = inv['consumer_final'] if consumer_final_allowed(t['total_cents']) else 0
    c.execute('UPDATE invoices SET subtotal_cents=?,discount_cents=?,tax_cents=?,total_cents=?,consumer_final=?,updated_at=? WHERE id=?',
              (t['subtotal_cents'], t['discount_cents'], t['tax_cents'], t['total_cents'], consumer, stamp(now), invoice_id))
    if inv['consumer_final'] and not consumer:
        c.execute("UPDATE invoices SET buyer_id_type='',buyer_id='',buyer_name='' WHERE id=?", (invoice_id,))


def buyer_problems(inv):
    """Datos del comprador que impiden emitir. El límite de consumidor final se comprueba con el total con impuestos, en centavos."""
    if inv['consumer_final']:
        if not consumer_final_allowed(inv['total_cents']):
            return {'consumer_final': 'El total supera USD 50,00: no se puede emitir a consumidor final. Ingresa la identificación del comprador.'}
        return {}
    problems = {}
    kind, ident = inv['buyer_id_type'], inv['buyer_id']
    if kind not in ('04', '05', '06', '08'):
        problems['buyer_id_type'] = 'Elige el tipo de identificación del comprador.'
    elif kind in ('04', '05'):
        problem, _ = reception.document_check(ident, 'ruc' if kind == '04' else 'cedula')
        if problem:
            problems['buyer_id'] = problem
    elif not re.fullmatch(r'[A-Za-z0-9]{3,20}', ident or ''):
        problems['buyer_id'] = 'Identificación de 3 a 20 letras o números.'
    if len((inv['buyer_name'] or '').strip()) < 3:
        problems['buyer_name'] = 'Nombre o razón social del comprador.'
    return problems


def set_buyer(c, invoice_id, data, user, now):
    inv = _get(c, invoice_id)
    if inv['status'] != 'borrador':
        raise InvoiceError('Solo se modifica el comprador de un borrador.', 409)
    consumer = str(data.get('consumer_final', '')) in ('1', 'true', 'True', 'on')
    if consumer and not consumer_final_allowed(inv['total_cents']):
        raise InvoiceError('El total de la factura (%s) supera USD 50,00: la opción «Consumidor final» no está permitida. Ingresa la identificación del comprador.' % quotes.usd(inv['total_cents']), 409,
                           {'consumer_final': 'No permitido por encima de USD 50,00.'})
    if consumer:
        values = ('07', sri_xml.CONSUMER_FINAL_ID, 'CONSUMIDOR FINAL', '', inv['buyer_email'], inv['buyer_phone'], 1)
    else:
        kind = str(data.get('buyer_id_type', ''))
        ident = re.sub(r'\s', '', str(data.get('buyer_id', '')))[:20]
        values = (kind, ident, re.sub(r'\s+', ' ', str(data.get('buyer_name', ''))).strip()[:300], re.sub(r'\s+', ' ', str(data.get('buyer_address', ''))).strip()[:300],
                  str(data.get('buyer_email', '')).strip()[:300], str(data.get('buyer_phone', '')).strip()[:40], 0)
        if kind == '07':
            raise InvoiceError('Para consumidor final usa la opción «Consumidor final».')
    c.execute('UPDATE invoices SET buyer_id_type=?,buyer_id=?,buyer_name=?,buyer_address=?,buyer_email=?,buyer_phone=?,consumer_final=?,updated_at=? WHERE id=?', (*values, stamp(now), invoice_id))
    event(c, invoice_id, 'comprador', 'Consumidor final.' if consumer else 'Comprador: %s (%s).' % (values[2], sri_xml.ID_TYPES.get(values[0], values[0])), now, user)
    problems = buyer_problems(_get(c, invoice_id))
    if problems:
        raise InvoiceError('Revisa los datos del comprador.', 400, problems)


def _get(c, invoice_id):
    row = c.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,)).fetchone()
    if not row:
        raise InvoiceError('Factura no encontrada.', 404)
    return row


def emit(c, invoice_id, user, now, environment=TEST_ENVIRONMENT):
    """Confirma el borrador: comprueba todo de nuevo en el servidor, asigna el secuencial y la clave de acceso y genera el XML.
    Solo en ambiente de pruebas. La firma y el envío al SRI de pruebas son la etapa siguiente (falta el certificado)."""
    if environment != TEST_ENVIRONMENT:
        raise InvoiceError('La emisión real está desactivada: solo se permite el ambiente de pruebas del SRI.', 403)
    before = _get(c, invoice_id)
    refresh(c, invoice_id, now)
    inv = dict(_get(c, invoice_id))
    if inv['status'] != 'borrador':
        raise InvoiceError('Esta factura ya fue emitida.', 409)
    if before['consumer_final'] and not consumer_final_allowed(inv['total_cents']):
        raise InvoiceError('El total (%s) supera USD 50,00: no se puede emitir a consumidor final. Ingresa la identificación del comprador.' % quotes.usd(inv['total_cents']), 409,
                           {'consumer_final': 'No permitido por encima de USD 50,00.'})
    cfg = settings(c)
    if cfg['missing']:
        raise InvoiceError('Faltan datos fiscales en la configuración: ' + ', '.join(cfg['missing']) + '.', 409)
    found = source(c, inv['source_kind'], inv['source_id'])
    if found['blockers']:
        raise InvoiceError(' '.join(found['blockers']), 409)
    problems = buyer_problems(inv)
    if problems:
        raise InvoiceError(next(iter(problems.values())), 409, problems)
    if inv['total_cents'] <= 0:
        raise InvoiceError('La factura no tiene importe.', 409)
    key = (environment, cfg['establishment'], cfg['emission_point'], '01')
    c.execute('INSERT OR IGNORE INTO invoice_sequences(environment,establishment,emission_point,doc_type,last_number) VALUES (?,?,?,?,0)', key)
    c.execute('UPDATE invoice_sequences SET last_number=last_number+1 WHERE environment=? AND establishment=? AND emission_point=? AND doc_type=?', key)
    sequential = c.execute('SELECT last_number FROM invoice_sequences WHERE environment=? AND establishment=? AND emission_point=? AND doc_type=?', key).fetchone()[0]
    issue = now.date()
    access = sri_xml.access_key(issue, '01', cfg['ruc'], environment, cfg['establishment'], cfg['emission_point'], sequential)
    inv.update(environment=environment, establishment=cfg['establishment'], emission_point=cfg['emission_point'], sequential=sequential, access_key=access,
               issue_date_sri=issue.strftime('%d/%m/%Y'), reference=found['reference'])
    items = [dict(r) for r in c.execute('SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY position', (invoice_id,))]
    payments = [dict(r) for r in c.execute('SELECT * FROM invoice_payments WHERE invoice_id=? ORDER BY id', (invoice_id,))]
    account = c.execute('SELECT * FROM bank_accounts WHERE id=?', (inv['bank_account_id'],)).fetchone() if inv.get('bank_account_id') else None
    if account:
        import banking
        inv['bank_info'] = '%s · %s · %s · %s · %s' % (account['bank'], banking.TYPES[account['account_type']], account['number'], account['holder'], account['holder_id'])
    xml = sri_xml.invoice_xml(cfg, inv, items, payments)
    c.execute("UPDATE invoices SET status='pendiente',environment=?,establishment=?,emission_point=?,sequential=?,access_key=?,issue_date=?,xml_unsigned=?,emitted_by=?,emitted_at=?,updated_at=? WHERE id=?",
              (environment, cfg['establishment'], cfg['emission_point'], sequential, access, issue.isoformat(), xml, user['id'], stamp(now), stamp(now), invoice_id))
    event(c, invoice_id, 'emitido', 'Factura %s preparada en ambiente de PRUEBAS (clave de acceso %s). Pendiente de firma electrónica y envío al SRI de pruebas.' % (number(inv), access), now, user)
    # Políticas comerciales vigentes al emitir: quedan asociadas a esta factura y no cambian después.
    import invoice_documents
    invoice_documents.attach_policies(c, invoice_id, now)
    return invoice_id


def set_bank(c, invoice_id, account_id, user, now):
    """Cuenta para depósito o transferencia que se muestra en la factura (catálogo central). Solo en borradores y comprobantes no autorizados."""
    import banking
    inv = _get(c, invoice_id)
    if inv['status'] not in ('borrador', 'pendiente'):
        raise InvoiceError('La cuenta bancaria solo se cambia antes del envío al SRI.', 409)
    try:
        account = banking.get(c, account_id, active=True) if str(account_id or '') else None
    except banking.BankError as error:
        raise InvoiceError(str(error), error.status)
    c.execute('UPDATE invoices SET bank_account_id=?,updated_at=? WHERE id=?', (account['id'] if account else None, stamp(now), invoice_id))
    event(c, invoice_id, 'cuenta_bancaria', ('Cuenta para depósito o transferencia: ' + banking.label(account)) if account else 'Sin cuenta bancaria indicada.', now, user)


def discard(c, invoice_id, user, now, reason=''):
    inv = _get(c, invoice_id)
    if inv['status'] != 'borrador':
        raise InvoiceError('Solo se descarta un borrador. Una factura emitida se anula con los documentos que admite el SRI.', 409)
    c.execute("UPDATE invoices SET status='descartado',updated_at=? WHERE id=?", (stamp(now), invoice_id))
    event(c, invoice_id, 'descartado', ('Borrador descartado. ' + reason.strip())[:500], now, user)


def detail(c, invoice_id):
    inv = dict(_get(c, invoice_id))
    items = [dict(r) for r in c.execute('SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY position', (invoice_id,))]
    payments = [dict(r, label=PAYMENT_LABELS.get(r['sri_code'], r['sri_code'])) for r in c.execute('SELECT * FROM invoice_payments WHERE invoice_id=? ORDER BY id', (invoice_id,))]
    events = [dict(r) for r in c.execute('SELECT event,detail,actor,created_at FROM invoice_events WHERE invoice_id=? ORDER BY id DESC', (invoice_id,))]
    rates = {}
    for item in items:
        group = rates.setdefault(item['tax_rate_bp'], {'rate_bp': item['tax_rate_bp'], 'base_cents': 0, 'tax_cents': 0})
        group['base_cents'] += item['base_cents']
        group['tax_cents'] += item['tax_cents']
    ref = c.execute('SELECT code FROM orders WHERE id=?', (inv['order_id'],)).fetchone() if inv['order_id'] else None
    sale = c.execute('SELECT code FROM license_sales WHERE id=?', (inv['license_sale_id'],)).fetchone() if inv['license_sale_id'] else None
    found = source(c, inv['source_kind'], inv['source_id']) if inv['status'] == 'borrador' else None
    for key in ('xml_signed', 'xml_authorized'):
        inv[key] = bool(inv[key])
    inv.update(status_label=STATUS[inv['status']], number=number(inv), id_type_label=sri_xml.ID_TYPES.get(inv['buyer_id_type'], ''), order_code=ref['code'] if ref else '',
               sale_code=sale['code'] if sale else '', consumer_final_allowed=consumer_final_allowed(inv['total_cents']), consumer_final_limit_cents=CONSUMER_FINAL_LIMIT_CENTS,
               problems=buyer_problems(inv) if inv['status'] == 'borrador' else {}, blockers=found['blockers'] if found else [],
               adjusted=any(line.get('adjusted') for line in (found['lines'] if found else [])), sri_messages=json.loads(inv['sri_messages'] or '[]'))
    import banking
    account = c.execute('SELECT * FROM bank_accounts WHERE id=?', (inv['bank_account_id'],)).fetchone() if inv.get('bank_account_id') else None
    return {'invoice': inv, 'items': items, 'payments': payments, 'rates': sorted(rates.values(), key=lambda g: g['rate_bp']), 'events': events, 'settings': settings(c),
            'bank_account': banking.public(account), 'bank_accounts': banking.listing(c, active_only=True)}


def listing(c, status='', q=''):
    where, args = ["i.status!='descartado'" if not status else 'i.status=?'], [] if not status else [status]
    if q:
        where.append("instr(lower(i.buyer_name||' '||i.buyer_id||' '||COALESCE(o.code,'')||' '||COALESCE(s.code,'')||' '||COALESCE(i.access_key,'')),lower(?))>0")
        args.append(q[:80])
    rows = [dict(r) for r in c.execute('SELECT i.*,o.code order_code,s.code sale_code FROM invoices i LEFT JOIN orders o ON o.id=i.order_id LEFT JOIN license_sales s ON s.id=i.license_sale_id WHERE '
                                      + ' AND '.join(where) + ' ORDER BY i.id DESC LIMIT 200', args)]
    out = [{'id': r['id'], 'number': number(r), 'status': r['status'], 'status_label': STATUS[r['status']], 'buyer_name': r['buyer_name'], 'buyer_id': r['buyer_id'],
            'consumer_final': bool(r['consumer_final']), 'total_cents': r['total_cents'], 'reference': r['order_code'] or r['sale_code'] or '', 'source_kind': r['source_kind'],
            'order_id': r['order_id'], 'created_at': r['created_at'], 'issue_date': r['issue_date'], 'environment': r['environment'], 'has_xml': bool(r['access_key'])} for r in rows]
    counts = {code: c.execute('SELECT COUNT(*) FROM invoices WHERE status=?', (code,)).fetchone()[0] for code in STATUS if code != 'descartado'}
    return {'rows': out, 'counts': counts, 'statuses': {k: v for k, v in STATUS.items() if k != 'descartado'}, 'settings': settings(c), 'summary': summary(c, counts)}


def summary(c, counts):
    """Indicadores del panel, solo con lo registrado (nada estimado). «Facturado» suma lo emitido sin rechazo; los saldos salen de los pagos
    actuales de las órdenes y ventas ya facturadas (por ejemplo, un pago anulado después de facturar)."""
    import equipment
    live = "status NOT IN ('descartado','rechazado')"
    billed = c.execute("SELECT COALESCE(SUM(total_cents),0) FROM invoices WHERE status IN ('pendiente','enviado','autorizado')").fetchone()[0]
    dues = [r[0] for r in c.execute('SELECT ' + equipment.BUDGET + '-' + equipment.PAID + " FROM orders o WHERE o.id IN (SELECT order_id FROM invoices WHERE source_kind='orden' AND " + live + ')')]
    dues += [r[0] for r in c.execute("SELECT s.total_cents-COALESCE((SELECT SUM(amount_cents) FROM license_sale_payments p WHERE p.sale_id=s.id AND p.status='confirmado'),0) FROM license_sales s "
                                     "WHERE s.cancelled_at='' AND s.id IN (SELECT license_sale_id FROM invoices WHERE source_kind='venta_licencia' AND " + live + ')')]
    dues = [d for d in dues if d > 0]
    return {'emitted': sum(counts.get(k, 0) for k in ('pendiente', 'enviado', 'autorizado', 'rechazado')), 'pending': sum(counts.get(k, 0) for k in ('borrador', 'pendiente', 'enviado')),
            'drafts': counts.get('borrador', 0), 'to_send': counts.get('pendiente', 0) + counts.get('enviado', 0), 'authorized': counts.get('autorizado', 0),
            'rejected': counts.get('rechazado', 0), 'billed_cents': billed, 'unpaid_count': len(dues), 'unpaid_cents': sum(dues)}


ENVIRONMENTS = {'1': 'Pruebas', '2': 'Producción'}
EVENT_LABELS = {'creado': 'Borrador creado', 'comprador': 'Comprador actualizado', 'emitido': 'Emitida en pruebas', 'descartado': 'Borrador descartado',
                'cuenta_bancaria': 'Cuenta bancaria'}


def dashboard(c, now):
    """Panel general (solo lectura): indicadores separados por ambiente (pruebas y producción), facturación mensual de los últimos 12 meses,
    actividad reciente y documentos que requieren atención. Solo cuenta lo registrado: nada se estima."""
    by_env = {env: {code: 0 for code in STATUS if code != 'descartado'} for env in ENVIRONMENTS}
    billed = {env: 0 for env in ENVIRONMENTS}
    for r in c.execute("SELECT environment,status,COUNT(*) n,COALESCE(SUM(total_cents),0) total FROM invoices WHERE status!='descartado' GROUP BY 1,2"):
        if r['environment'] in by_env:
            by_env[r['environment']][r['status']] = r['n']
            if r['status'] in ('pendiente', 'enviado', 'autorizado'):
                billed[r['environment']] += r['total']
    counts = {code: sum(by_env[env][code] for env in ENVIRONMENTS) for code in by_env['1']}
    s = summary(c, counts)
    first = now.date().replace(day=1)
    months = []
    for back in range(11, -1, -1):
        y, m = first.year, first.month - back
        while m <= 0:
            y, m = y - 1, m + 12
        months.append('%04d-%02d' % (y, m))
    monthly = {key: {env: 0 for env in ENVIRONMENTS} for key in months}
    for r in c.execute("SELECT substr(issue_date,1,7) month,environment,COALESCE(SUM(total_cents),0) total FROM invoices WHERE status IN ('pendiente','enviado','autorizado') "
                       "AND issue_date>=? GROUP BY 1,2", (months[0] + '-01',)):
        if r['month'] in monthly and r['environment'] in ENVIRONMENTS:
            monthly[r['month']][r['environment']] = r['total']
    recent = [{'invoice_id': r['invoice_id'], 'event': r['event'], 'label': EVENT_LABELS.get(r['event'], r['event'].replace('_', ' ').capitalize()), 'detail': r['detail'],
               'actor': r['actor'], 'at': r['created_at'], 'number': number(r), 'buyer_name': r['buyer_name'], 'environment': r['environment']}
              for r in c.execute('SELECT e.invoice_id,e.event,e.detail,e.actor,e.created_at,i.establishment,i.emission_point,i.sequential,i.buyer_name,i.environment '
                                 'FROM invoice_events e JOIN invoices i ON i.id=e.invoice_id ORDER BY e.id DESC LIMIT 8')]
    attention = []
    for r in c.execute("SELECT * FROM invoices WHERE status IN ('borrador','pendiente','rechazado') ORDER BY id DESC LIMIT 30"):
        inv = dict(r)
        if inv['status'] == 'rechazado':
            reason = 'Rechazada: revisa los mensajes del SRI y corrige los datos.'
        elif inv['status'] == 'pendiente':
            reason = 'Emitida en pruebas: pendiente de firma electrónica y envío al SRI de pruebas.'
        else:
            try:
                found = source(c, inv['source_kind'], inv['source_id'])
            except InvoiceError:
                found = {'blockers': ['El origen de este borrador ya no está disponible.']}
            problems = list(buyer_problems(inv).values())
            reason = (found['blockers'] + problems)[0] if found['blockers'] or problems else 'Borrador listo para revisar y emitir en pruebas.'
        attention.append({'id': inv['id'], 'status': inv['status'], 'status_label': STATUS[inv['status']], 'number': number(inv), 'buyer_name': inv['buyer_name'],
                          'total_cents': inv['total_cents'], 'reason': reason, 'environment': inv['environment']})
    cfg = settings(c)
    return {'summary': s, 'environments': {env: {'label': ENVIRONMENTS[env], 'counts': by_env[env], 'billed_cents': billed[env],
                                                 'documents': sum(by_env[env].values())} for env in ENVIRONMENTS},
            'monthly': [{'month': key, 'test_cents': monthly[key]['1'], 'real_cents': monthly[key]['2']} for key in months],
            'has_monthly': any(v['1'] or v['2'] for v in monthly.values()), 'recent': recent, 'attention': attention[:8], 'attention_total': len(attention),
            'settings': {'test_mode': TEST_MODE, 'missing': cfg['missing'], 'environment': ENVIRONMENTS[TEST_ENVIRONMENT]}}
