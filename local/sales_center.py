"""Centro de Ventas: reúne lo que ya existe sin duplicarlo. Las ventas son las facturas directas y las cotizaciones convertidas sin orden
técnica (proformas), las ventas de licencias (VLIC) y las ventas registradas desde el inventario; los cobros, la caja, la facturación
electrónica (solo pruebas) y el Kardex siguen en sus módulos. Lo único propio son los pedidos comerciales (PED-000001) y los indicadores.
Nada se borra: una venta se anula descartando su borrador de factura o con nota de crédito; un pedido se cancela con motivo."""
import re
import secrets
from datetime import date

import invoicing
import quotes
from proformas import stamp


class SalesError(Exception):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status = status
        self.fields = fields or {}


KINDS = {'directa': 'Venta directa', 'cotizacion': 'Desde cotización', 'licencia': 'Licencias', 'inventario': 'Registrada en inventario'}
STATES = {'pagada': 'Pagada', 'por_cobrar': 'Saldo pendiente', 'anulada': 'Anulada', 'sin_cobro': 'Cobro no registrado'}
GROUPS = {'dia': 'Día', 'producto': 'Producto', 'cliente': 'Cliente', 'usuario': 'Usuario', 'tipo': 'Tipo de venta'}
REQUEST_KINDS = {'producto': 'Producto', 'licencia': 'Licencia', 'servicio': 'Servicio', 'otro': 'Otro'}
REQUEST_STATUS = {'solicitado': 'Solicitado por el cliente', 'pedido_proveedor': 'Pedido al proveedor', 'recibido': 'Recibido · por entregar',
                  'entregado': 'Entregado', 'cancelado': 'Cancelado'}
FLOW = {'solicitado': ('pedido_proveedor', 'recibido', 'entregado', 'cancelado'), 'pedido_proveedor': ('recibido', 'cancelado'), 'recibido': ('entregado', 'cancelado')}
OPEN = ('solicitado', 'pedido_proveedor', 'recibido')


def _admin(user):
    if user['role'] != 'administrador':
        raise SalesError('Solo administración gestiona las ventas.', 403)


def _text(data, key, limit):
    return re.sub(r'\s+', ' ', str(data.get(key, '') or '')).strip()[:limit]


def _iso(value, key):
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise SalesError('Fecha no válida.', 400, {key: 'Usa una fecha válida.'})


def _range(f, today=None):
    start, end = _iso(f.get('from'), 'from'), _iso(f.get('to'), 'to')
    if today and not (start or end):
        start, end = today[:8] + '01', today
    if start and end and start > end:
        raise SalesError('La fecha inicial es posterior a la final.', 400, {'from': 'Revisa el rango.'})
    return start, end


def _within(at, start, end):
    day = str(at or '')[:10]
    return (not start or day >= start) and (not end or day <= end)


# ---- Historial unificado -----------------------------------------------------------------------------------------------------------

def ledger(c, f=None):
    """Todas las ventas, de la más reciente a la más antigua. Filtros: from, to, q (código o cliente), kind, state, user, client."""
    f = f or {}
    start, end = _range(f)
    rows = []
    for r in c.execute("SELECT p.id,p.code,p.origin,p.client_id,COALESCE(k.name,p.client_name) client,COALESCE(i.total_cents,p.total_cents) total,"
                       "COALESCE(i.created_at,p.updated_at) at,p.created_by,u.name user,p.invoice_id,i.status inv_status,i.establishment,i.emission_point,i.sequential,"
                       "(SELECT COALESCE(SUM(a.amount_cents),0) FROM advances a WHERE a.proforma_id=p.id AND COALESCE(a.voided_at,'')='') paid "
                       "FROM proformas p LEFT JOIN clients k ON k.id=p.client_id LEFT JOIN users u ON u.id=p.created_by LEFT JOIN invoices i ON i.id=p.invoice_id "
                       "WHERE p.status='convertida' AND p.order_id IS NULL"):
        void = r['inv_status'] == 'descartado'
        balance = 0 if void else max(r['total'] - r['paid'], 0)
        rows.append({'kind': 'directa' if r['origin'] == 'directa' else 'cotizacion', 'id': r['id'], 'code': r['code'], 'at': r['at'], 'client_id': r['client_id'],
                     'client': r['client'] or 'Consumidor final', 'user_id': r['created_by'], 'user': r['user'] or '', 'total_cents': r['total'], 'paid_cents': min(r['paid'], r['total']),
                     'balance_cents': balance, 'state': 'anulada' if void else 'por_cobrar' if balance else 'pagada', 'invoice_id': r['invoice_id'],
                     'invoice_status': r['inv_status'] or '', 'invoice_number': invoicing.number(r) if r['inv_status'] else '', 'delivery': ''})
    for r in c.execute("SELECT s.id,s.code,s.client_id,k.name client,s.total_cents,s.created_at,s.created_by,u.name user,s.payment_status,s.delivery_status,"
                       "(SELECT COALESCE(SUM(amount_cents),0) FROM license_sale_payments WHERE sale_id=s.id AND status='confirmado') paid,"
                       "(SELECT id FROM invoices WHERE license_sale_id=s.id AND status!='descartado' ORDER BY id DESC LIMIT 1) invoice_id "
                       "FROM license_sales s LEFT JOIN clients k ON k.id=s.client_id LEFT JOIN users u ON u.id=s.created_by"):
        void = r['payment_status'] == 'cancelado'
        balance = 0 if void else max(r['total_cents'] - r['paid'], 0)
        invoice = c.execute('SELECT status,establishment,emission_point,sequential FROM invoices WHERE id=?', (r['invoice_id'],)).fetchone() if r['invoice_id'] else None
        rows.append({'kind': 'licencia', 'id': r['id'], 'code': r['code'], 'at': r['created_at'], 'client_id': r['client_id'], 'client': r['client'] or '', 'user_id': r['created_by'],
                     'user': r['user'] or '', 'total_cents': r['total_cents'], 'paid_cents': min(r['paid'], r['total_cents']), 'balance_cents': balance,
                     'state': 'anulada' if void else 'por_cobrar' if balance else 'pagada', 'invoice_id': r['invoice_id'], 'invoice_status': invoice['status'] if invoice else '',
                     'invoice_number': invoicing.number(invoice) if invoice else '', 'delivery': '' if void else r['delivery_status']})
    for r in c.execute("SELECT m.id,m.quantity,m.sale_price_cents,m.client_id,k.name client,m.created_at,m.created_by,u.name user,g.name product,"
                       "(SELECT id FROM invoices WHERE source_kind='venta_inventario' AND source_id=m.id AND status!='descartado' ORDER BY id DESC LIMIT 1) invoice_id "
                       "FROM inventory_movements m JOIN inventory_items i ON i.id=m.item_id JOIN catalog_items g ON g.id=i.catalog_id LEFT JOIN clients k ON k.id=m.client_id "
                       "LEFT JOIN users u ON u.id=m.created_by WHERE m.reason='venta' AND m.direction=-1 AND m.reference_kind NOT IN ('factura','orden')"):
        invoice = c.execute('SELECT status,establishment,emission_point,sequential FROM invoices WHERE id=?', (r['invoice_id'],)).fetchone() if r['invoice_id'] else None
        rows.append({'kind': 'inventario', 'id': r['id'], 'code': 'INV-%d' % r['id'], 'at': r['created_at'], 'client_id': r['client_id'], 'client': r['client'] or 'Sin cliente',
                     'user_id': r['created_by'], 'user': r['user'] or '', 'total_cents': (r['sale_price_cents'] or 0) * r['quantity'], 'paid_cents': 0, 'balance_cents': 0,
                     'state': 'sin_cobro', 'invoice_id': r['invoice_id'], 'invoice_status': invoice['status'] if invoice else '',
                     'invoice_number': invoicing.number(invoice) if invoice else '', 'delivery': '', 'detail': '%d × %s' % (r['quantity'], r['product'])})
    q = _text(f, 'q', 80).lower()
    kind, state = str(f.get('kind') or ''), str(f.get('state') or '')
    who, client = str(f.get('user') or ''), str(f.get('client') or '')
    out = [dict(r, kind_label=KINDS[r['kind']], state_label=STATES[r['state']], invoice_label=invoicing.STATUS.get(r['invoice_status'], 'Sin factura'))
           for r in rows if _within(r['at'], start, end) and (not q or q in (r['code'] + ' ' + r['client']).lower()) and (not kind or r['kind'] == kind)
           and (not state or r['state'] == state) and (not who.isdigit() or r['user_id'] == int(who)) and (not client.isdigit() or r['client_id'] == int(client))]
    return sorted(out, key=lambda r: r['at'], reverse=True)


def lines(c, start='', end=''):
    """Partidas vendidas (no anuladas) para los productos más vendidos y el reporte por producto."""
    out = []
    for r in c.execute("SELECT x.description name,x.quantity,x.quantity*x.unit_cents-x.discount_cents total,COALESCE(i.created_at,p.updated_at) at FROM proforma_items x "
                       "JOIN proformas p ON p.id=x.proforma_id LEFT JOIN invoices i ON i.id=p.invoice_id WHERE p.status='convertida' AND p.order_id IS NULL "
                       "AND x.status='aprobado' AND COALESCE(i.status,'')!='descartado'"):
        out.append(dict(r))
    for r in c.execute("SELECT x.product_name name,x.quantity,x.quantity*x.unit_price_cents-x.discount_cents total,s.created_at at FROM license_sale_items x "
                       "JOIN license_sales s ON s.id=x.sale_id WHERE s.payment_status!='cancelado'"):
        out.append(dict(r))
    for r in c.execute("SELECT g.name,m.quantity,COALESCE(m.sale_price_cents,0)*m.quantity total,m.created_at at FROM inventory_movements m JOIN inventory_items i ON i.id=m.item_id "
                       "JOIN catalog_items g ON g.id=i.catalog_id WHERE m.reason='venta' AND m.direction=-1 AND m.reference_kind NOT IN ('factura','orden')"):
        out.append(dict(r))
    return [r for r in out if _within(r['at'], start, end)]


def _top(rows, limit=5):
    grouped = {}
    for r in rows:
        key = re.sub(r'\s+', ' ', r['name'] or '').strip().casefold()
        g = grouped.setdefault(key, {'name': r['name'], 'quantity': 0, 'total_cents': 0})
        g['quantity'] += r['quantity']
        g['total_cents'] += r['total']
    return sorted(grouped.values(), key=lambda g: (-g['quantity'], -g['total_cents'], g['name']))[:limit]


# ---- Panel -------------------------------------------------------------------------------------------------------------------------

def dashboard(c, now):
    today = now.date().isoformat()
    month = today[:7]
    rows = ledger(c)
    live = [r for r in rows if r['state'] != 'anulada']
    day = [r for r in live if r['at'][:10] == today]
    mon = [r for r in live if r['at'][:7] == month]
    invoiced = c.execute("SELECT COALESCE(SUM(i.total_cents),0),COUNT(*) FROM invoices i LEFT JOIN proformas p ON i.source_kind='proforma' AND p.id=i.source_id "
                         "WHERE i.status IN ('pendiente','enviado','autorizado') AND substr(COALESCE(NULLIF(i.emitted_at,''),i.created_at),1,7)=? "
                         "AND (i.source_kind IN ('venta_licencia','venta_inventario') OR (i.source_kind='proforma' AND p.order_id IS NULL))", (month,)).fetchone()
    drafts = c.execute("SELECT COUNT(*) FROM proformas WHERE origin='directa' AND status IN ('borrador','aprobada')").fetchone()[0]
    to_deliver = c.execute("SELECT COUNT(*) FROM license_sales WHERE delivery_status='pendiente' AND payment_status!='cancelado'").fetchone()[0]
    to_emit = len([r for r in live if r['invoice_status'] == 'borrador'])
    requests_open = c.execute("SELECT COUNT(*) FROM sales_requests WHERE status IN ('solicitado','pedido_proveedor','recibido')").fetchone()[0]
    due = [r for r in live if r['balance_cents'] > 0]
    return {'today': {'count': len(day), 'total_cents': sum(r['total_cents'] for r in day)},
            'month': {'count': len(mon), 'total_cents': sum(r['total_cents'] for r in mon)},
            'invoiced': {'count': invoiced[1], 'total_cents': invoiced[0], 'test_mode': invoicing.TEST_MODE},
            'pending': {'count': drafts + to_deliver + to_emit + requests_open, 'drafts': drafts, 'to_deliver': to_deliver, 'to_emit': to_emit, 'requests': requests_open},
            'collections': {'count': len(due), 'total_cents': sum(r['balance_cents'] for r in due)},
            'top': _top(lines(c, month + '-01', today)), 'latest': rows[:8]}


# ---- Reportes ----------------------------------------------------------------------------------------------------------------------

def report(c, f, now):
    start, end = _range(f, now.date().isoformat())
    group = str(f.get('group') or 'dia')
    if group not in GROUPS:
        raise SalesError('Agrupación no válida.', 400, {'group': 'Elige una agrupación.'})
    out = {}
    if group == 'producto':
        for g in _top(lines(c, start, end), limit=1000):
            out[g['name']] = {'label': g['name'], 'count': g['quantity'], 'total_cents': g['total_cents'], 'paid_cents': None, 'balance_cents': None}
    else:
        for r in ledger(c, {'from': start, 'to': end}):
            if r['state'] == 'anulada':
                continue
            key, label = {'dia': (r['at'][:10], r['at'][:10]), 'cliente': (r['client_id'] or r['client'], r['client']), 'usuario': (r['user_id'], r['user'] or 'Sin usuario'),
                          'tipo': (r['kind'], r['kind_label'])}[group]
            g = out.setdefault(key, {'label': label, 'count': 0, 'total_cents': 0, 'paid_cents': 0, 'balance_cents': 0})
            g['count'] += 1
            g['total_cents'] += r['total_cents']
            g['paid_cents'] += r['paid_cents']
            g['balance_cents'] += r['balance_cents']
    rows = sorted(out.values(), key=lambda g: g['label'], reverse=True) if group == 'dia' else sorted(out.values(), key=lambda g: (-g['total_cents'], str(g['label'])))
    return {'group': group, 'group_label': GROUPS[group], 'from': start, 'to': end, 'rows': rows,
            'totals': {'count': sum(g['count'] for g in rows), 'total_cents': sum(g['total_cents'] for g in rows)}}


# ---- Pedidos comerciales -----------------------------------------------------------------------------------------------------------

def _event(c, rid, status, detail, user, now):
    c.execute('INSERT INTO sales_request_events(request_id,status,detail,created_by,created_at) VALUES (?,?,?,?,?)', (rid, status, detail[:500], user['id'], stamp(now)))


def _request(c, rid):
    row = c.execute('SELECT * FROM sales_requests WHERE id=?', (int(rid),)).fetchone() if str(rid).isdigit() else None
    if not row:
        raise SalesError('Pedido no encontrado.', 404)
    return row


def _optional_id(c, data, key, table, label):
    value = str(data.get(key) or '').strip()
    if not value:
        return None
    if not value.isdigit() or not c.execute('SELECT 1 FROM %s WHERE id=?' % table, (int(value),)).fetchone():
        raise SalesError('%s no encontrado.' % label, 404, {key: '%s no válido.' % label})
    return int(value)


def save_request(c, data, user, now):
    _admin(user)
    key = str(data.get('request_key') or '').strip()
    if key:
        if not re.fullmatch(r'[A-Za-z0-9-]{16,64}', key):
            raise SalesError('Solicitud inválida.', 400)
        found = c.execute('SELECT id FROM sales_requests WHERE request_key=?', (key,)).fetchone()
        if found:
            return found[0]  # el mismo envío repetido no crea otro pedido
    errors = {}
    client = _optional_id(c, data, 'client_id', 'clients', 'Cliente')
    if not client:
        errors['client_id'] = 'Selecciona el cliente.'
    kind = str(data.get('kind') or 'producto')
    if kind not in REQUEST_KINDS:
        errors['kind'] = 'Tipo no válido.'
    description = _text(data, 'description', 300)
    if len(description) < 2:
        errors['description'] = 'Describe lo que pide el cliente.'
    try:
        quantity = int(str(data.get('quantity') or '1').strip())
    except ValueError:
        quantity = 0
    if not 1 <= quantity <= 10000:
        errors['quantity'] = 'Cantidad entera mayor que cero.'
    estimate = None
    if str(data.get('estimate') or '').strip():
        try:
            estimate = quotes.cents(data.get('estimate'), 'estimate')
        except quotes.QuoteError:
            errors['estimate'] = 'Importe en USD con hasta dos decimales.'
    if errors:
        raise SalesError('Revisa los datos del pedido.', 400, errors)
    item = _optional_id(c, data, 'inventory_item_id', 'inventory_items', 'Producto')
    supplier = _optional_id(c, data, 'supplier_id', 'suppliers', 'Proveedor')
    expected = _iso(data.get('expected_at'), 'expected_at')
    moment = stamp(now)
    rid = c.execute('INSERT INTO sales_requests(code,client_id,kind,description,quantity,inventory_item_id,supplier_id,estimate_cents,expected_at,notes,request_key,created_by,created_at,updated_at) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', ('PED-T-' + secrets.token_hex(8), client, kind, description, quantity, item, supplier, estimate, expected, _text(data, 'notes', 300),
                                                            key or None, user['id'], moment, moment)).lastrowid
    c.execute('UPDATE sales_requests SET code=? WHERE id=?', ('PED-%06d' % rid, rid))
    _event(c, rid, 'solicitado', 'Pedido registrado: %d × %s.' % (quantity, description), user, now)
    return rid


def _sale_link(c, code):
    """Vincula la venta con que se entregó el pedido: una proforma (PF-…) convertida o una venta de licencias (VLIC-…)."""
    code = str(code or '').strip().upper()
    if not code:
        return None, None
    row = c.execute("SELECT id FROM proformas WHERE code=? AND status='convertida'", (code,)).fetchone()
    if row:
        return row[0], None
    row = c.execute("SELECT id FROM license_sales WHERE code=? AND payment_status!='cancelado'", (code,)).fetchone()
    if row:
        return None, row[0]
    raise SalesError('No hay una venta confirmada con ese número.', 404, {'sale_code': 'Venta no encontrada.'})


def request_action(c, rid, data, user, now):
    _admin(user)
    row = _request(c, rid)
    action = str(data.get('action') or '')
    moment = stamp(now)
    if action == 'status':
        target = str(data.get('status') or '')
        if target not in FLOW.get(row['status'], ()):
            raise SalesError('El pedido no puede pasar de «%s» a ese estado.' % REQUEST_STATUS[row['status']], 409)
        note = _text(data, 'note', 300)
        if target == 'cancelado':
            if len(note) < 5:
                raise SalesError('Indica el motivo de la cancelación.', 400, {'note': 'Motivo obligatorio (al menos 5 caracteres).'})
            c.execute('UPDATE sales_requests SET status=?,cancel_reason=?,updated_at=? WHERE id=? AND status=?', (target, note, moment, row['id'], row['status']))
        else:
            supplier = _optional_id(c, data, 'supplier_id', 'suppliers', 'Proveedor') if target == 'pedido_proveedor' else None
            proforma, sale = _sale_link(c, data.get('sale_code')) if target == 'entregado' else (None, None)
            expected = _iso(data.get('expected_at'), 'expected_at') if target == 'pedido_proveedor' else ''
            if not c.execute('UPDATE sales_requests SET status=?,supplier_id=COALESCE(?,supplier_id),expected_at=CASE WHEN ?!=\'\' THEN ? ELSE expected_at END,'
                             'proforma_id=COALESCE(?,proforma_id),license_sale_id=COALESCE(?,license_sale_id),updated_at=? WHERE id=? AND status=?',
                             (target, supplier, expected, expected, proforma, sale, moment, row['id'], row['status'])).rowcount:
                raise SalesError('El pedido cambió mientras se actualizaba. Vuelve a intentarlo.', 409)
            if target == 'entregado' and data.get('sale_code'):
                note = ('Venta ' + str(data.get('sale_code')).strip().upper() + '. ' + note).strip()
        _event(c, row['id'], target, (REQUEST_STATUS[target] + ('. ' + note if note else '.'))[:500], user, now)
    elif action == 'note':
        note = _text(data, 'note', 300)
        if len(note) < 2:
            raise SalesError('Escribe la nota.', 400, {'note': 'Nota obligatoria.'})
        _event(c, row['id'], row['status'], 'Nota: ' + note, user, now)
    else:
        raise SalesError('Acción no válida.', 400)
    return row['id']


def requests(c, f):
    status = str(f.get('status') or 'abiertos')
    q = _text(f, 'q', 80).lower()
    out = []
    for r in c.execute('SELECT r.*,k.name client,k.phone client_phone,s.name supplier,u.name created_name,p.code proforma_code,l.code license_sale_code FROM sales_requests r '
                       'JOIN clients k ON k.id=r.client_id LEFT JOIN suppliers s ON s.id=r.supplier_id LEFT JOIN users u ON u.id=r.created_by '
                       'LEFT JOIN proformas p ON p.id=r.proforma_id LEFT JOIN license_sales l ON l.id=r.license_sale_id ORDER BY r.id DESC'):
        r = dict(r)
        if status == 'abiertos' and r['status'] not in OPEN or status in REQUEST_STATUS and r['status'] != status:
            continue
        if q and q not in ' '.join(str(r[k] or '') for k in ('code', 'client', 'description', 'supplier')).lower():
            continue
        r.pop('request_key', None)
        out.append(dict(r, status_label=REQUEST_STATUS[r['status']], kind_label=REQUEST_KINDS[r['kind']], next=list(FLOW.get(r['status'], ()))))
    return out


def request_detail(c, rid):
    row = dict(_request(c, rid))
    row.pop('request_key', None)
    events = [dict(e) for e in c.execute('SELECT e.status,e.detail,e.created_at,u.name actor FROM sales_request_events e LEFT JOIN users u ON u.id=e.created_by '
                                          'WHERE e.request_id=? ORDER BY e.id DESC', (row['id'],))]
    return {'request': dict(row, status_label=REQUEST_STATUS[row['status']], next=list(FLOW.get(row['status'], ()))), 'events': events}


# ---- Desde una orden técnica -------------------------------------------------------------------------------------------------------

def from_order(c, code, user, now):
    """Lleva a facturación los conceptos de una orden técnica sin copiarlos: usa el borrador de factura de la orden (si ya existe, el mismo)."""
    _admin(user)
    order = c.execute('SELECT id,code FROM orders WHERE code=?', (str(code or '').strip().upper()[:40],)).fetchone()
    if not order:
        raise SalesError('No hay una orden con ese número.', 404, {'order_code': 'Orden no encontrada.'})
    try:
        return invoicing.draft(c, 'orden', order['id'], user, now)
    except invoicing.InvoiceError as error:
        raise SalesError(str(error), error.status, getattr(error, 'fields', {}))
