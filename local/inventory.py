"""Inventario físico (productos, repuestos y accesorios), proveedores y compras, sobre el catálogo compartido de Órdenes Pro.

- Las existencias se calculan siempre sumando los movimientos (no hay contador que pueda desajustarse).
- Una salida nunca deja existencias negativas: se comprueba dentro de la misma transacción.
- Un mismo documento (compra, factura, orden) no mueve dos veces el mismo artículo (índice único en la base).
- Las compras en borrador no mueven nada; al recibirlas se registran las entradas una sola vez.
- Las licencias digitales siguen en su módulo: aquí solo se muestran sus existencias (lectura).
- Productos controlados por serie: cada entrada crea sus unidades (código interno único y, si existe, la serie original única) y cada
  salida indica qué unidades salen. Las reservas apartan existencias sin descontarlas.
- Costo promedio ponderado móvil: cada entrada se promedia con el saldo que queda; las salidas salen al promedio vigente."""
import re
from datetime import date

KINDS = {'producto': 'Producto', 'repuesto': 'Repuesto', 'accesorio': 'Accesorio'}
IN_REASONS = {'inicial': 'Inventario inicial', 'compra': 'Compra', 'devolucion_cliente': 'Devolución del cliente', 'ajuste_entrada': 'Ajuste (entrada)'}
OUT_REASONS = {'venta': 'Venta', 'uso_orden': 'Uso en una orden', 'devolucion_proveedor': 'Devolución al proveedor', 'ajuste_salida': 'Ajuste (salida)', 'baja': 'Baja por daño o pérdida', 'anulacion_compra': 'Anulación de compra'}
MANUAL_IN = ('devolucion_cliente', 'ajuste_entrada')
MANUAL_OUT = ('venta', 'uso_orden', 'devolucion_proveedor', 'ajuste_salida', 'baja')
PURCHASE_STATUS = {'borrador': 'Borrador', 'recibida': 'Recibida', 'anulada': 'Anulada'}
STOCK_SQL = 'COALESCE((SELECT SUM(m.direction*m.quantity) FROM inventory_movements m WHERE m.item_id=i.id),0)'
RESERVED_SQL = "COALESCE((SELECT SUM(r.quantity) FROM inventory_reservations r WHERE r.item_id=i.id AND r.status='activa'),0)"
# Estado de una unidad según el motivo de su salida.
UNIT_STATUS_OUT = {'venta': 'vendida', 'uso_orden': 'consumida', 'devolucion_proveedor': 'devuelta', 'ajuste_salida': 'baja', 'baja': 'baja', 'anulacion_compra': 'devuelta'}
UNIT_STATUS = {'disponible': 'Disponible', 'reservada': 'Reservada', 'vendida': 'Vendida', 'consumida': 'Consumida en una orden', 'devuelta': 'Devuelta al proveedor', 'baja': 'De baja'}


class InventoryError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def stamp(now):
    return now.isoformat(timespec='seconds')


def usd(cents):
    return '$' + format(cents // 100, ',').replace(',', '.') + ',%02d' % (cents % 100)


def cents(value, field='amount'):
    text = str(value or '').strip().replace('$', '').replace(' ', '')
    if re.fullmatch(r'\d{1,3}(\.\d{3})+(,\d{1,2})?|\d+(,\d{1,2})?', text):
        text = text.replace('.', '').replace(',', '.')
    elif not re.fullmatch(r'\d+(\.\d{1,2})?', text):
        raise InventoryError('Importe no válido.', fields={field: 'Importe no válido.'})
    whole, _, frac = text.partition('.')
    value = int(whole) * 100 + int((frac + '00')[:2])
    if value > 100_000_000:
        raise InventoryError('Importe no válido.', fields={field: 'Importe no válido.'})
    return value


def quantity(value, field='quantity'):
    text = str(value or '').strip()
    if not re.fullmatch(r'\d{1,6}', text) or int(text) <= 0:
        raise InventoryError('Cantidad no válida.', fields={field: 'Número entero mayor que cero.'})
    return int(text)


def event(c, now, user, name, detail, item_id=None, purchase_id=None, supplier_id=None, unit_id=None):
    c.execute('INSERT INTO inventory_events(item_id,purchase_id,supplier_id,unit_id,event,detail,actor_id,actor,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
              (item_id, purchase_id, supplier_id, unit_id, name, detail[:500], user['id'] if user else None, user['name'] if user else 'Sistema', stamp(now)))


# ---- Códigos internos y series -----------------------------------------------------------------------------------------

def prefix_of(c, category_id):
    """Prefijo de la categoría o, si no tiene uno propio, el de su categoría principal."""
    row = c.execute('SELECT id,parent_id,prefix,name FROM inventory_categories WHERE id=?', (category_id,)).fetchone() if category_id else None
    while row and not row['prefix'] and row['parent_id']:
        row = c.execute('SELECT id,parent_id,prefix,name FROM inventory_categories WHERE id=?', (row['parent_id'],)).fetchone()
    if not row or not row['prefix']:
        raise InventoryError('La categoría no tiene prefijo de código interno: configúralo en «Categorías y marcas».', 409, {'category_id': 'Sin prefijo de código.'})
    return row['prefix']


def next_code(c, category_id):
    """Siguiente código interno de la categoría (PCD-SSD-000001). La numeración solo avanza: un código nunca se reutiliza."""
    prefix = prefix_of(c, category_id)
    while True:
        c.execute('UPDATE inventory_prefixes SET last_number=last_number+1 WHERE prefix=?', (prefix,))
        code = 'PCD-%s-%06d' % (prefix, c.execute('SELECT last_number FROM inventory_prefixes WHERE prefix=?', (prefix,)).fetchone()[0])
        if not c.execute('SELECT 1 FROM inventory_units WHERE internal_code=? UNION ALL SELECT 1 FROM license_units WHERE code=?', (code, code)).fetchone():
            return code


def serial_key(serial):
    """Serie normalizada para detectar duplicados (sin espacios ni diferencias de mayúsculas)."""
    return re.sub(r'\s+', '', str(serial or '')).upper()


def clean_serial(serial):
    text = re.sub(r'[\x00-\x1f\x7f]', '', str(serial or '')).strip()
    if text and (len(text) > 60 or not re.fullmatch(r'[\x20-\x7e]+', text)):
        raise InventoryError('Serie no válida: solo letras, números y signos simples (hasta 60).', fields={'serial': 'Serie no válida.'})
    return text


def serial_owner(c, serial):
    key = serial_key(serial)
    return c.execute('SELECT u.id,u.internal_code,u.status,g.name FROM inventory_units u JOIN inventory_items i ON i.id=u.item_id JOIN catalog_items g ON g.id=i.catalog_id WHERE u.serial_key=?',
                     (key,)).fetchone() if key else None


# ---- Artículos ---------------------------------------------------------------------------------------------------------

def _item_row(c, item_id):
    row = c.execute('SELECT i.*,g.name,g.code catalog_code,g.category,g.price_cents,g.taxed,' + STOCK_SQL + ' stock,' + RESERVED_SQL + ' reserved FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE i.id=?',
                    (item_id,)).fetchone() if str(item_id).isdigit() else None
    if not row:
        raise InventoryError('Artículo de inventario no encontrado.', 404)
    return row


def _half(numerator, denominator):
    return (2 * numerator + denominator) // (2 * denominator)


def valuation(c, item_id):
    """Kardex valorizado de un artículo con costo promedio ponderado móvil: [(movimiento, saldo, costo promedio, valor del saldo, costo aplicado)].
    Una entrada sin costo (por ejemplo, una devolución del cliente) entra al promedio vigente; las salidas salen al promedio vigente."""
    out, qty, value, avg = [], 0, 0, 0
    for m in c.execute('SELECT * FROM inventory_movements WHERE item_id=? ORDER BY id', (item_id,)).fetchall():
        if m['direction'] == 1:
            applied = m['unit_cost_cents'] or avg
            value += m['quantity'] * applied
            qty += m['quantity']
        else:
            applied = avg
            taken = value if m['quantity'] >= qty else _half(value * m['quantity'], qty) if qty else 0
            value -= taken
            qty -= m['quantity']
        avg = _half(value, qty) if qty > 0 else avg
        out.append((m, qty, avg, max(0, value), applied))
    return out


def average_cost(c, item_id):
    rows = valuation(c, item_id)
    return rows[-1][2] if rows else 0


def reserved(c, item_id):
    return c.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory_reservations WHERE item_id=? AND status='activa'", (item_id,)).fetchone()[0]


def items(c, q='', alerts_only=False):
    rows = c.execute('SELECT i.*,g.name,g.code catalog_code,g.category,g.price_cents,g.available,' + STOCK_SQL + ' stock FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id '
                     'ORDER BY i.active DESC,g.name COLLATE NOCASE').fetchall()
    out = []
    words = [w for w in re.sub(r'\s+', ' ', str(q or '')).lower().split(' ') if w]
    for r in rows:
        if words and not all(w in ' '.join((r['name'], r['sku'], r['catalog_code'] or '', r['location'], KINDS[r['kind']])).lower() for w in words):
            continue
        low = bool(r['active']) and r['stock'] <= r['min_stock']
        if alerts_only and not low:
            continue
        cost = average_cost(c, r['id'])
        out.append({'id': r['id'], 'catalog_id': r['catalog_id'], 'name': r['name'], 'code': r['catalog_code'] or '', 'sku': r['sku'], 'kind': r['kind'], 'kind_label': KINDS[r['kind']],
                    'stock': r['stock'], 'min_stock': r['min_stock'], 'location': r['location'], 'active': r['active'], 'price_cents': r['price_cents'], 'average_cost_cents': cost,
                    'value_cents': max(0, r['stock']) * cost, 'low': low, 'out': r['stock'] <= 0})
    return out


def alert_count(c):
    return c.execute('SELECT COUNT(*) FROM inventory_items i WHERE i.active=1 AND ' + STOCK_SQL + '<=i.min_stock').fetchone()[0]


def overview(c, now, q=''):
    rows = items(c, q)
    import licenses
    lic = [{'name': p['name'], 'available': p['stock'].get('disponible', 0), 'reserved': p['stock'].get('reservada', 0), 'delivered': p['stock'].get('entregada', 0)}
           for p in licenses.products(c, now) if p['managed']]
    candidates = [dict(r) for r in c.execute("SELECT g.id,g.name,g.code,g.category FROM catalog_items g WHERE g.category IN ('repuesto','otro') AND NOT EXISTS (SELECT 1 FROM inventory_items i WHERE i.catalog_id=g.id) ORDER BY g.name COLLATE NOCASE")]
    return {'items': rows, 'alerts': [r for r in rows if r['low']], 'licenses': lic, 'kinds': KINDS, 'in_reasons': {k: IN_REASONS[k] for k in MANUAL_IN},
            'out_reasons': {k: OUT_REASONS[k] for k in MANUAL_OUT}, 'catalog_candidates': candidates,
            'totals': {'items': len([r for r in rows if r['active']]), 'units': sum(max(0, r['stock']) for r in rows if r['active']), 'value_cents': sum(r['value_cents'] for r in rows if r['active']),
                       'alerts': len([r for r in rows if r['low']])}}


def save_item(c, data, user, now):
    """Alta (enlazando un artículo del catálogo) o edición de un artículo de inventario. La existencia inicial es un movimiento."""
    errors = {}
    kind = str(data.get('kind', ''))
    if kind not in KINDS:
        errors['kind'] = 'Elige producto, repuesto o accesorio.'
    sku = re.sub(r'\s', '', str(data.get('sku', '')))[:40]
    if sku and not re.fullmatch(r'[A-Za-z0-9._-]{2,40}', sku):
        errors['sku'] = 'Letras, números, punto, guion o guion bajo.'
    try:
        minimum = int(str(data.get('min_stock', '0') or '0'))
        if not 0 <= minimum <= 100000:
            raise ValueError
    except ValueError:
        errors['min_stock'] = 'Número entero de 0 en adelante.'
        minimum = 0
    location = re.sub(r'\s+', ' ', str(data.get('location', ''))).strip()[:80]
    item_id = str(data.get('id', '') or '')
    if sku and c.execute('SELECT 1 FROM inventory_items WHERE sku=?' + (' AND id!=?' if item_id else ''), (sku, *([int(item_id)] if item_id else []))).fetchone():
        errors['sku'] = 'Ese código ya existe.'
    if item_id:
        if errors:
            raise InventoryError('Revisa los datos del artículo.', fields=errors)
        row = _item_row(c, item_id)
        c.execute('UPDATE inventory_items SET kind=?,sku=?,min_stock=?,location=?,updated_at=?,updated_by=? WHERE id=?', (kind, sku, minimum, location, stamp(now), user['id'], row['id']))
        event(c, now, user, 'articulo_editado', 'Artículo actualizado: %s (mínimo %d).' % (row['name'], minimum), row['id'])
        return row['id']
    catalog = c.execute("SELECT id,name,category FROM catalog_items WHERE id=?", (str(data.get('catalog_id', '')),)).fetchone() if str(data.get('catalog_id', '')).isdigit() else None
    if not catalog:
        errors['catalog_id'] = 'Elige el artículo del catálogo.'
    elif catalog['category'] not in ('repuesto', 'otro'):
        errors['catalog_id'] = 'Solo productos y repuestos físicos: las licencias tienen su propio inventario.'
    elif c.execute('SELECT 1 FROM inventory_items WHERE catalog_id=?', (catalog['id'],)).fetchone():
        errors['catalog_id'] = 'Ese artículo ya está en el inventario.'
    initial = str(data.get('initial_stock', '') or '').strip()
    if errors:
        raise InventoryError('Revisa los datos del artículo.', fields=errors)
    new_id = c.execute('INSERT INTO inventory_items(catalog_id,kind,sku,min_stock,location,active,created_at,created_by,updated_at,updated_by) VALUES (?,?,?,?,?,1,?,?,?,?)',
                       (catalog['id'], kind, sku, minimum, location, stamp(now), user['id'], stamp(now), user['id'])).lastrowid
    event(c, now, user, 'articulo_creado', 'Artículo incorporado al inventario: %s.' % catalog['name'], new_id)
    if initial and initial != '0':
        move(c, new_id, 1, 'inicial', initial, data.get('initial_cost', '0') or '0', user, now, note='Existencia inicial al incorporar el artículo.')
    return new_id


def set_active(c, item_id, active, user, now):
    row = _item_row(c, item_id)
    c.execute('UPDATE inventory_items SET active=?,updated_at=?,updated_by=? WHERE id=?', (1 if active else 0, stamp(now), user['id'], row['id']))
    event(c, now, user, 'articulo_activado' if active else 'articulo_desactivado', ('Activado: ' if active else 'Desactivado: ') + row['name'], row['id'])


def move(c, item_id, direction, reason, qty, cost='0', user=None, now=None, reference_kind='', reference_id=None, note='', request_key=None, serials=None, unit_ids=None,
         location='', reservation_id=None, unit_values=None):
    """Registra una entrada (+1) o salida (−1). Las salidas no pueden dejar existencias negativas ni tomar lo reservado para otro.
    Producto con serie: la entrada crea una unidad por cantidad (con las series indicadas; el resto, solo con código interno) y la salida
    exige las unidades que salen. `unit_values` actualiza las unidades que salen (cliente, documento, garantías)."""
    row = _item_row(c, item_id)
    if direction == 1 and reason not in IN_REASONS or direction == -1 and reason not in OUT_REASONS:
        raise InventoryError('Motivo no válido.', fields={'reason': 'Motivo no válido.'})
    amount = quantity(qty)
    unit_cost = cents(cost, 'cost') if direction == 1 else 0
    if request_key and c.execute('SELECT id FROM inventory_movements WHERE request_key=?', (request_key,)).fetchone():
        return c.execute('SELECT id FROM inventory_movements WHERE request_key=?', (request_key,)).fetchone()[0]  # reintento: no se duplica
    held = c.execute("SELECT * FROM inventory_reservations WHERE id=? AND item_id=? AND status='activa'", (reservation_id, row['id'])).fetchone() if reservation_id else None
    if reservation_id and not held:
        raise InventoryError('La reserva ya no está activa.', 409)
    if direction == -1:
        free = row['stock'] - reserved(c, row['id']) + (held['quantity'] if held else 0)
        if row['stock'] < amount:
            raise InventoryError('Existencias insuficientes de %s: hay %d y se intentan sacar %d.' % (row['name'], row['stock'], amount), 409, {'quantity': 'Supera las existencias.'})
        if free < amount:
            raise InventoryError('Existencias reservadas: de %s hay %d libres y se intentan sacar %d. Libera o usa la reserva.' % (row['name'], free, amount), 409, {'quantity': 'Supera lo disponible.'})
    if not row['active'] and direction == -1 and reason not in ('baja', 'ajuste_salida', 'devolucion_proveedor', 'anulacion_compra'):
        raise InventoryError('El artículo está inactivo.', 409)
    serial_item = row['tracking'] == 'serie'
    picked = []
    if serial_item and (direction == -1 or reason == 'devolucion_cliente'):
        ids = [int(u) for u in (unit_ids or []) if str(u).isdigit()]
        if len(set(ids)) != amount:
            raise InventoryError('Indica %s de %s que %s.' % ('la unidad' if amount == 1 else 'las %d unidades' % amount, row['name'], 'sale' if direction == -1 and amount == 1 else 'salen' if direction == -1 else 'vuelven'),
                                 fields={'units': 'Elige o escanea las unidades.'})
        allowed = ('vendida', 'consumida') if direction == 1 else ('disponible', 'reservada')
        for unit_id in ids:
            unit = c.execute('SELECT * FROM inventory_units WHERE id=? AND item_id=?', (unit_id, row['id'])).fetchone()
            if not unit or unit['status'] not in allowed:
                raise InventoryError('La unidad %s no está %s.' % (unit['internal_code'] if unit else unit_id, 'vendida ni consumida' if direction == 1 else 'disponible'), 409, {'units': 'Unidad no válida.'})
            if unit['status'] == 'reservada' and (not held or unit['reservation_id'] != held['id']):
                raise InventoryError('La unidad %s está reservada para otra operación.' % unit['internal_code'], 409, {'units': 'Unidad reservada.'})
            picked.append(unit)
    entry_serials = []
    if serial_item and direction == 1 and reason != 'devolucion_cliente':
        entry_serials = [clean_serial(v) for v in (serials or [])]
        if len(entry_serials) > amount:
            raise InventoryError('Hay más series (%d) que unidades (%d).' % (len(entry_serials), amount), fields={'quantity': 'Revisa la cantidad.'})
        keys = [serial_key(v) for v in entry_serials if v]
        if len(keys) != len(set(keys)):
            raise InventoryError('Una serie está repetida en este ingreso.', 409, {'serials': 'Serie repetida.'})
        for value in entry_serials:
            owner = serial_owner(c, value)
            if owner:
                raise InventoryError('La serie %s ya está registrada (%s · %s).' % (value, owner['internal_code'], owner['name']), 409, {'serials': 'Serie duplicada.'})
    applied = 0
    if direction == -1:
        history = valuation(c, row['id'])
        applied = history[-1][2] if history else 0
    movement = c.execute('INSERT INTO inventory_movements(item_id,direction,reason,quantity,unit_cost_cents,reference_kind,reference_id,note,request_key,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         (row['id'], direction, reason, amount, unit_cost if direction == 1 else applied, reference_kind, reference_id, re.sub(r'\s+', ' ', str(note or '')).strip()[:300], request_key,
                          user['id'] if user else None, stamp(now))).lastrowid
    created = []
    if serial_item and direction == 1 and reason != 'devolucion_cliente':
        place = re.sub(r'\s+', ' ', str(location or row['location'] or '')).strip()[:80]
        for n in range(amount):
            value = entry_serials[n] if n < len(entry_serials) else ''
            unit = c.execute('INSERT INTO inventory_units(item_id,internal_code,serial,serial_key,status,location,unit_cost_cents,entry_movement_id,created_at,created_by,updated_at,updated_by) '
                             "VALUES (?,?,?,?,'disponible',?,?,?,?,?,?,?)", (row['id'], next_code(c, row['category_id']), value, serial_key(value), place, unit_cost or applied, movement,
                                                                            stamp(now), user['id'] if user else None, stamp(now), user['id'] if user else None)).lastrowid
            created.append(unit)
    for unit in picked:
        if direction == 1:  # devolución del cliente: la unidad vuelve a estar disponible; su historial queda en los eventos
            c.execute("UPDATE inventory_units SET status='disponible',client_id=NULL,order_id=NULL,invoice_id=NULL,document='',sold_at='',delivered_at='',store_warranty_from='',store_warranty_to='',"
                      'maker_warranty_from=\'\',maker_warranty_to=\'\',exit_movement_id=NULL,reservation_id=NULL,updated_at=?,updated_by=? WHERE id=?', (stamp(now), user['id'] if user else None, unit['id']))
            event(c, now, user, 'unidad_devuelta', 'Unidad %s devuelta por el cliente (vendida el %s; garantía PC-DOCTOR hasta %s).' % (unit['internal_code'], unit['sold_at'][:10] or '—', unit['store_warranty_to'] or '—'),
                  row['id'], unit_id=unit['id'])
        else:
            values = dict(unit_values or {})
            sets = ['status=?', 'exit_movement_id=?', 'reservation_id=NULL', 'updated_at=?', 'updated_by=?']
            args = [UNIT_STATUS_OUT[reason], movement, stamp(now), user['id'] if user else None]
            for key in ('client_id', 'order_id', 'invoice_id', 'document', 'sold_at', 'delivered_at', 'store_warranty_from', 'store_warranty_to', 'maker_warranty_from', 'maker_warranty_to'):
                if key in values:
                    sets.append(key + '=?')
                    args.append(values[key])
            c.execute('UPDATE inventory_units SET ' + ','.join(sets) + ' WHERE id=?', (*args, unit['id']))
        created.append(unit['id'])
    for unit_id in created:
        c.execute('INSERT INTO inventory_movement_units(movement_id,unit_id) VALUES (?,?)', (movement, unit_id))
    if held:
        c.execute("UPDATE inventory_reservations SET status='consumida',movement_id=?,closed_by=?,closed_at=? WHERE id=?", (movement, user['id'] if user else None, stamp(now), held['id']))
    label = (IN_REASONS if direction == 1 else OUT_REASONS)[reason]
    event(c, now, user, 'entrada' if direction == 1 else 'salida', '%s: %s %d × %s%s.' % (label, '+' if direction == 1 else '−', amount, row['name'], (' a ' + usd(unit_cost)) if unit_cost else ''), row['id'])
    return movement


def movements(c, item_id):
    row = _item_row(c, item_id)
    out, balance = [], 0
    rows = c.execute('SELECT m.*,u.name actor FROM inventory_movements m LEFT JOIN users u ON u.id=m.created_by WHERE m.item_id=? ORDER BY m.id', (row['id'],)).fetchall()
    for m in rows:
        balance += m['direction'] * m['quantity']
        out.append({'id': m['id'], 'at': m['created_at'], 'direction': m['direction'], 'reason': m['reason'], 'reason_label': (IN_REASONS if m['direction'] == 1 else OUT_REASONS)[m['reason']],
                    'quantity': m['quantity'], 'unit_cost_cents': m['unit_cost_cents'], 'reference': ('%s %s' % (m['reference_kind'], m['reference_id'])).strip() if m['reference_kind'] else '',
                    'note': m['note'], 'actor': m['actor'] or 'Sistema', 'balance': balance})
    return {'item': {'id': row['id'], 'name': row['name'], 'stock': row['stock'], 'min_stock': row['min_stock']}, 'movements': out[::-1]}


# ---- Proveedores -------------------------------------------------------------------------------------------------------

def suppliers(c, active_only=False):
    return [dict(r) for r in c.execute('SELECT * FROM suppliers' + (' WHERE active=1' if active_only else '') + ' ORDER BY active DESC,name COLLATE NOCASE')]


def save_supplier(c, data, user, now):
    text = lambda key, size: re.sub(r'\s+', ' ', str(data.get(key, '') or '')).strip()[:size]
    clean = {'name': text('name', 300), 'identification': re.sub(r'\s', '', str(data.get('identification', '')))[:20], 'contact_name': text('contact_name', 120),
             'phone': text('phone', 40), 'email': text('email', 200), 'address': text('address', 300)}
    errors = {}
    if len(clean['name']) < 2:
        errors['name'] = 'Nombre o razón social.'
    if clean['identification']:
        if re.fullmatch(r'\d{10}|\d{13}', clean['identification']):
            import reception
            problem, _ = reception.document_check(clean['identification'])
            if problem:
                errors['identification'] = problem
        elif not re.fullmatch(r'[A-Za-z0-9]{3,20}', clean['identification']):
            errors['identification'] = 'RUC, cédula o identificación del exterior.'
    if clean['email'] and not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(\.[^\s@<>.]+)+', clean['email']):
        errors['email'] = 'Correo no válido.'
    supplier_id = str(data.get('id', '') or '')
    if clean['identification'] and c.execute('SELECT 1 FROM suppliers WHERE identification=?' + (' AND id!=?' if supplier_id else ''), (clean['identification'], *([int(supplier_id)] if supplier_id else []))).fetchone():
        errors['identification'] = 'Ya hay un proveedor con esa identificación.'
    if errors:
        raise InventoryError('Revisa los datos del proveedor.', fields=errors)
    if supplier_id:
        if not c.execute('SELECT 1 FROM suppliers WHERE id=?', (supplier_id,)).fetchone():
            raise InventoryError('Proveedor no encontrado.', 404)
        c.execute('UPDATE suppliers SET name=?,identification=?,contact_name=?,phone=?,email=?,address=?,updated_at=?,updated_by=? WHERE id=?', (*clean.values(), stamp(now), user['id'], int(supplier_id)))
        event(c, now, user, 'proveedor_editado', 'Proveedor actualizado: ' + clean['name'], supplier_id=int(supplier_id))
        return int(supplier_id)
    new_id = c.execute('INSERT INTO suppliers(name,identification,contact_name,phone,email,address,active,created_at,created_by,updated_at,updated_by) VALUES (?,?,?,?,?,?,1,?,?,?,?)',
                       (*clean.values(), stamp(now), user['id'], stamp(now), user['id'])).lastrowid
    event(c, now, user, 'proveedor_creado', 'Proveedor registrado: ' + clean['name'], supplier_id=new_id)
    return new_id


def set_supplier_active(c, supplier_id, active, user, now):
    row = c.execute('SELECT * FROM suppliers WHERE id=?', (str(supplier_id),)).fetchone()
    if not row:
        raise InventoryError('Proveedor no encontrado.', 404)
    c.execute('UPDATE suppliers SET active=?,updated_at=?,updated_by=? WHERE id=?', (1 if active else 0, stamp(now), user['id'], row['id']))
    event(c, now, user, 'proveedor_activado' if active else 'proveedor_desactivado', row['name'], supplier_id=row['id'])


# ---- Compras -----------------------------------------------------------------------------------------------------------

def _purchase(c, purchase_id):
    row = c.execute('SELECT * FROM purchases WHERE id=?', (str(purchase_id),)).fetchone() if str(purchase_id).isdigit() else None
    if not row:
        raise InventoryError('Compra no encontrada.', 404)
    return row


def purchase_detail(c, purchase_id):
    p = dict(_purchase(c, purchase_id))
    p['status_label'] = PURCHASE_STATUS[p['status']]
    p['supplier'] = dict(c.execute('SELECT id,name,identification FROM suppliers WHERE id=?', (p['supplier_id'],)).fetchone())
    p['items'] = [dict(r) for r in c.execute('SELECT p.*,g.name,i.sku FROM purchase_items p JOIN inventory_items i ON i.id=p.item_id JOIN catalog_items g ON g.id=i.catalog_id WHERE p.purchase_id=? ORDER BY p.id', (p['id'],))]
    for item in p['items']:
        base = item['quantity'] * item['unit_cost_cents']
        item['base_cents'], item['tax_cents'] = base, (2 * base * item['tax_rate_bp'] + 10000) // 20000
    p['events'] = [dict(r) for r in c.execute('SELECT event,detail,actor,created_at FROM inventory_events WHERE purchase_id=? ORDER BY id DESC', (p['id'],))]
    return p


def purchases(c, status=''):
    where, args = ('WHERE p.status=?', (status,)) if status in PURCHASE_STATUS else ('', ())
    return [dict(r, status_label=PURCHASE_STATUS[r['status']]) for r in c.execute('SELECT p.id,p.document_number,p.issue_date,p.status,p.total_cents,p.created_at,s.name supplier FROM purchases p JOIN suppliers s ON s.id=p.supplier_id '
                                                                                 + where + ' ORDER BY p.id DESC LIMIT 200', args)]


def save_purchase(c, data, user, now):
    """Borrador de compra (alta o edición). Calcula base, IVA y total; no mueve inventario."""
    import json
    errors = {}
    supplier = c.execute('SELECT * FROM suppliers WHERE id=? AND active=1', (str(data.get('supplier_id', '')),)).fetchone()
    if not supplier:
        errors['supplier_id'] = 'Elige un proveedor activo.'
    number = re.sub(r'\s', '', str(data.get('document_number', '')))[:40]
    if not re.fullmatch(r'[A-Za-z0-9-]{1,40}', number):
        errors['document_number'] = 'Número del documento del proveedor.'
    try:
        issue = date.fromisoformat(str(data.get('issue_date', '')))
        if issue > now.date():
            errors['issue_date'] = 'La fecha no puede ser futura.'
    except ValueError:
        errors['issue_date'] = 'Fecha del documento.'
        issue = None
    try:
        lines = json.loads(str(data.get('items', '[]')))
        assert isinstance(lines, list)
    except (ValueError, AssertionError):
        lines = []
    clean = []
    for n, line in enumerate(lines[:100]):
        try:
            item = _item_row(c, line.get('item_id'))
            clean.append((item['id'], quantity(line.get('quantity')), cents(line.get('unit_cost'), 'unit_cost'), 1500 if str(line.get('taxed', '')) in ('1', 'true', 'True') else 0))
        except (InventoryError, AttributeError):
            errors['items'] = 'Revisa la partida %d: artículo, cantidad y costo.' % (n + 1)
            break
    if not clean and 'items' not in errors:
        errors['items'] = 'Agrega al menos un artículo.'
    purchase_id = str(data.get('id', '') or '')
    if not errors and c.execute("SELECT 1 FROM purchases WHERE supplier_id=? AND document_number=? AND status!='anulada'" + (' AND id!=?' if purchase_id else ''),
                                (supplier['id'], number, *([int(purchase_id)] if purchase_id else []))).fetchone():
        errors['document_number'] = 'Ese documento de este proveedor ya está registrado.'
    if errors:
        raise InventoryError('Revisa la compra.', fields=errors)
    subtotal = sum(q * cost for _, q, cost, _ in clean)
    tax = sum((2 * q * cost * rate + 10000) // 20000 for _, q, cost, rate in clean)
    notes = re.sub(r'\s+', ' ', str(data.get('notes', ''))).strip()[:500]
    if purchase_id:
        row = _purchase(c, purchase_id)
        if row['status'] != 'borrador':
            raise InventoryError('Solo se edita una compra en borrador.', 409)
        c.execute('UPDATE purchases SET supplier_id=?,document_number=?,issue_date=?,subtotal_cents=?,tax_cents=?,total_cents=?,notes=? WHERE id=?',
                  (supplier['id'], number, issue.isoformat(), subtotal, tax, subtotal + tax, notes, row['id']))
        c.execute('DELETE FROM purchase_items WHERE purchase_id=?', (row['id'],))
        pid = row['id']
    else:
        pid = c.execute('INSERT INTO purchases(supplier_id,document_number,issue_date,status,subtotal_cents,tax_cents,total_cents,notes,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (supplier['id'], number, issue.isoformat(), 'borrador', subtotal, tax, subtotal + tax, notes, user['id'], stamp(now))).lastrowid
    for item_id, q, cost, rate in clean:
        c.execute('INSERT INTO purchase_items(purchase_id,item_id,quantity,unit_cost_cents,tax_rate_bp) VALUES (?,?,?,?,?)', (pid, item_id, q, cost, rate))
    event(c, now, user, 'compra_guardada', 'Compra %s de %s en borrador: %s.' % (number, supplier['name'], usd(subtotal + tax)), purchase_id=pid, supplier_id=supplier['id'])
    return pid


def receive(c, purchase_id, user, now):
    """Recibe la compra: registra las entradas (una por partida y documento; nunca dos veces)."""
    row = _purchase(c, purchase_id)
    if row['status'] != 'borrador':
        raise InventoryError('Esta compra ya fue recibida o anulada.', 409)
    for item in c.execute('SELECT * FROM purchase_items WHERE purchase_id=?', (row['id'],)).fetchall():
        move(c, item['item_id'], 1, 'compra', str(item['quantity']), '%d.%02d' % divmod(item['unit_cost_cents'], 100), user, now, 'compra', row['id'], 'Compra ' + row['document_number'])
    c.execute("UPDATE purchases SET status='recibida',received_by=?,received_at=? WHERE id=?", (user['id'], stamp(now), row['id']))
    event(c, now, user, 'compra_recibida', 'Compra %s recibida: existencias actualizadas.' % row['document_number'], purchase_id=row['id'], supplier_id=row['supplier_id'])


def void_purchase(c, purchase_id, reason, user, now):
    """Anula una compra. Si ya se recibió, registra la salida de lo que entró (solo si las existencias alcanzan)."""
    row = _purchase(c, purchase_id)
    reason = re.sub(r'\s+', ' ', str(reason or '')).strip()[:300]
    if len(reason) < 5:
        raise InventoryError('Indica el motivo de la anulación.', fields={'reason': 'Motivo obligatorio.'})
    if row['status'] == 'anulada':
        raise InventoryError('La compra ya está anulada.', 409)
    if row['status'] == 'recibida':
        for item in c.execute('SELECT * FROM purchase_items WHERE purchase_id=?', (row['id'],)).fetchall():
            units = None
            if _item_row(c, item['item_id'])['tracking'] == 'serie':
                entry = c.execute("SELECT id FROM inventory_movements WHERE reference_kind='compra' AND reference_id=? AND item_id=? AND direction=1", (row['id'], item['item_id'])).fetchone()
                units = [u[0] for u in c.execute("SELECT id FROM inventory_units WHERE entry_movement_id=? AND status='disponible' ORDER BY id", (entry[0] if entry else 0,))]
                if len(units) < item['quantity']:
                    raise InventoryError('No se puede anular: ya salieron unidades de esta compra (%d de %d disponibles).' % (len(units), item['quantity']), 409)
            move(c, item['item_id'], -1, 'anulacion_compra', str(item['quantity']), '0', user, now, 'compra', row['id'], 'Anulación de la compra ' + row['document_number'], unit_ids=units)
    c.execute("UPDATE purchases SET status='anulada',voided_by=?,voided_at=?,void_reason=? WHERE id=?", (user['id'], stamp(now), reason, row['id']))
    event(c, now, user, 'compra_anulada', 'Compra %s anulada: %s' % (row['document_number'], reason), purchase_id=row['id'], supplier_id=row['supplier_id'])
