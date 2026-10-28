"""Centro de Inventario de PC-DOCTOR: categorías y marcas, fichas de productos, unidades con serie y código interno, inventario inicial,
Kardex valorizado, reservas, traslados, garantías, etiquetas, importación y licencias digitales clasificadas.

- Existencias: siempre a partir de los movimientos (inventory_movements); las licencias, de sus unidades (license_units). No hay otro contador.
- Tres identificadores: SKU (modelo comercial, en la ficha), serie original (de la unidad, única si existe) y código interno (de la unidad,
  PCD-<PREFIJO>-000001, único y nunca reutilizado).
- Una reserva no descuenta existencias. Una venta o un consumo confirmado es una sola salida: el mismo documento no mueve dos veces el mismo
  artículo (índice único) y un repuesto consumido en una orden no se descuenta otra vez al facturar esa orden.
- Garantías: la de PC-DOCTOR y la del fabricante se configuran por separado en la ficha y se fechan por separado en cada unidad vendida.
- Las claves de las licencias siguen cifradas en su módulo: aquí nunca se leen ni se muestran."""
import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape

import inventory
from inventory import InventoryError, cents, event, quantity, stamp, usd

PERIODS = {'dias': 'días', 'meses': 'meses', 'anios': 'años'}
PERIOD_ONE = {'dias': 'día', 'meses': 'mes', 'anios': 'año'}
STARTS = {'venta': 'Desde la venta', 'entrega': 'Desde la entrega'}
TRACKING = {'serie': 'Por unidad (serie y código interno)', 'granel': 'Por cantidad (a granel)'}
ENTRY_REASONS = {'inicial': 'Inventario inicial', 'compra': 'Compra o ingreso de mercadería', 'ajuste_entrada': 'Ajuste autorizado (entrada)'}
EXIT_REASONS = {k: inventory.OUT_REASONS[k] for k in inventory.MANUAL_OUT}
SOON_DAYS = 30
MAX_UNITS = 300
LABEL_SIZES = {'50x30': (50, 30), '60x40': (60, 40), '80x50': (80, 50)}


def _text(data, key, size):
    return re.sub(r'\s+', ' ', str(data.get(key, '') or '')).strip()[:size]


def _id(value):
    return int(value) if str(value or '').isdigit() else None


def _json_list(value, field):
    if isinstance(value, list):
        return value
    try:
        out = json.loads(str(value or '[]'))
        assert isinstance(out, list)
        return out
    except (ValueError, AssertionError):
        raise InventoryError('Datos no válidos.', fields={field: 'Lista no válida.'})


def add_period(start, amount, unit):
    """Fin de una cobertura: días exactos, o meses y años de calendario (31/01 + 1 mes = último día de febrero)."""
    import licenses
    if not amount:
        return None
    if unit == 'dias':
        return start + timedelta(days=amount)
    return licenses.add_months(start, amount * (12 if unit == 'anios' else 1))


def period_label(amount, unit):
    return 'Sin garantía' if not amount else '%d %s' % (amount, PERIOD_ONE[unit] if amount == 1 else PERIODS[unit])


# ---- Categorías, prefijos, marcas y familias ---------------------------------------------------------------------------

def _category(c, category_id):
    row = c.execute('SELECT * FROM inventory_categories WHERE id=?', (category_id,)).fetchone() if _id(category_id) else None
    if not row:
        raise InventoryError('Categoría no encontrada.', 404, {'category_id': 'Elige una categoría.'})
    return row


def category_path(c, category_id):
    row = _category(c, category_id)
    if row['parent_id']:
        parent = _category(c, row['parent_id'])
        return parent['name'] + ' › ' + row['name']
    return row['name']


def taxonomy(c):
    """Árbol de categorías (con su prefijo propio o heredado y el próximo código), marcas, familias y prefijos asignados."""
    rows = [dict(r) for r in c.execute('SELECT * FROM inventory_categories ORDER BY kind,position,name COLLATE NOCASE')]
    numbers = {r['prefix']: dict(r) for r in c.execute('SELECT * FROM inventory_prefixes')}
    counts = {r[0]: r[1] for r in c.execute('SELECT category_id,COUNT(*) FROM inventory_items WHERE category_id IS NOT NULL GROUP BY category_id')}
    lic_counts = {r[0]: r[1] for r in c.execute('SELECT category_id,COUNT(*) FROM license_classification GROUP BY category_id')}
    by_id = {r['id']: r for r in rows}
    out = []
    for r in rows:
        own = r['prefix']
        effective = own or (by_id[r['parent_id']]['prefix'] if r['parent_id'] else '')
        last = numbers.get(effective, {}).get('last_number', 0)
        r.update(effective_prefix=effective, inherited=not own and bool(effective), next_code='PCD-%s-%06d' % (effective, last + 1) if effective else '',
                 products=counts.get(r['id'], 0) + lic_counts.get(r['id'], 0), children=[])
    for r in rows:
        if r['parent_id']:
            by_id[r['parent_id']]['children'].append(r)
        else:
            out.append(r)
    brands = [dict(r) for r in c.execute('SELECT b.*,(SELECT COUNT(*) FROM inventory_items i WHERE i.brand_id=b.id)+(SELECT COUNT(*) FROM license_classification l WHERE l.brand_id=b.id) products '
                                          'FROM inventory_brands b ORDER BY b.active DESC,b.name COLLATE NOCASE')]
    families = [dict(r, editions=[e for e in r['editions'].split('\n') if e.strip()]) for r in
                c.execute('SELECT f.*,b.name brand FROM inventory_families f JOIN inventory_brands b ON b.id=f.brand_id ORDER BY b.name COLLATE NOCASE,f.name COLLATE NOCASE')]
    prefixes = [dict(r, category=category_path(c, r['category_id'])) for r in c.execute('SELECT * FROM inventory_prefixes ORDER BY prefix')]
    return {'categories': out, 'brands': brands, 'families': families, 'prefixes': prefixes, 'tracking': TRACKING, 'periods': PERIODS, 'starts': STARTS,
            'catalog_categories': {'repuesto': 'Repuestos y componentes', 'otro': 'Productos'}, 'item_kinds': inventory.KINDS}


def _clean_prefix(value):
    prefix = re.sub(r'\s', '', str(value or '')).upper()
    if prefix and not re.fullmatch(r'[A-Z0-9]{2,6}', prefix):
        raise InventoryError('El prefijo admite de 2 a 6 letras o números, sin espacios.', fields={'prefix': 'Prefijo no válido (2 a 6 letras o números).'})
    return prefix


def _claim_prefix(c, prefix, category_id, now):
    """Un prefijo pertenece para siempre a una categoría: no se reutiliza en otra aunque se deje de usar."""
    owner = c.execute('SELECT category_id FROM inventory_prefixes WHERE prefix=?', (prefix,)).fetchone()
    if owner and owner[0] != category_id:
        raise InventoryError('El prefijo %s ya pertenece a «%s». Los prefijos no se reutilizan.' % (prefix, category_path(c, owner[0])), 409, {'prefix': 'Prefijo en uso.'})
    if not owner:
        c.execute('INSERT INTO inventory_prefixes(prefix,category_id,created_at) VALUES (?,?,?)', (prefix, category_id, stamp(now)))


def save_category(c, data, user, now):
    """Alta o edición de una categoría o subcategoría. Nunca se elimina: se desactiva y conserva su historial y sus códigos."""
    category_id = _id(data.get('id'))
    old = _category(c, category_id) if category_id else None
    parent = _category(c, data.get('parent_id')) if _id(data.get('parent_id')) else None
    if old:
        parent = _category(c, old['parent_id']) if old['parent_id'] else None
    if parent and parent['parent_id']:
        raise InventoryError('Las subcategorías van debajo de una categoría principal.', fields={'parent_id': 'Elige una categoría principal.'})
    kind = old['kind'] if old else parent['kind'] if parent else str(data.get('kind') or 'fisico')
    if kind not in ('fisico', 'licencia'):
        raise InventoryError('Tipo de categoría no válido.', fields={'kind': 'Físico o licencia.'})
    errors = {}
    name = _text(data, 'name', 80)
    if len(name) < 2:
        errors['name'] = 'Nombre de 2 a 80 caracteres.'
    elif c.execute('SELECT 1 FROM inventory_categories WHERE kind=? AND COALESCE(parent_id,0)=? AND name=? COLLATE NOCASE AND id!=?',
                   (kind, parent['id'] if parent else 0, name, category_id or 0)).fetchone():
        errors['name'] = 'Ya existe con ese nombre.'
    try:
        prefix = _clean_prefix(data.get('prefix'))
    except InventoryError as error:
        errors.update(error.fields)
        prefix = ''
    if not prefix and not parent:
        errors['prefix'] = 'Una categoría principal necesita su prefijo de código.'
    tracking = str(data.get('tracking') or (parent['tracking'] if parent else 'serie'))
    if tracking not in TRACKING:
        errors['tracking'] = 'Por serie o a granel.'
    catalog_category = parent['catalog_category'] if parent else str(data.get('catalog_category') or ('otro' if kind == 'fisico' else 'licencia'))
    allowed = ('repuesto', 'otro') if kind == 'fisico' else ('licencia', 'seguridad')
    if catalog_category not in allowed:
        errors['catalog_category'] = 'Categoría del catálogo no válida.'
    item_kind = parent['item_kind'] if parent else str(data.get('item_kind') or 'producto')
    if item_kind not in inventory.KINDS:
        errors['item_kind'] = 'Producto, repuesto o accesorio.'
    if errors:
        raise InventoryError('Revisa la categoría.', fields=errors)
    if old:
        c.execute('UPDATE inventory_categories SET name=?,prefix=?,tracking=?,catalog_category=?,item_kind=?,updated_at=?,updated_by=? WHERE id=?',
                  (name, prefix, tracking, catalog_category, item_kind, stamp(now), user['id'], old['id']))
        if prefix:
            _claim_prefix(c, prefix, old['id'], now)
        if not old['parent_id']:  # las subcategorías siguen la categoría del catálogo y el tipo de su principal
            c.execute('UPDATE inventory_categories SET catalog_category=?,item_kind=? WHERE parent_id=?', (catalog_category, item_kind, old['id']))
        event(c, now, user, 'categoria_editada', 'Categoría actualizada: %s%s.' % (name, ' (prefijo %s)' % prefix if prefix else ''))
        return old['id']
    position = c.execute('SELECT COALESCE(MAX(position),0)+1 FROM inventory_categories WHERE kind=? AND COALESCE(parent_id,0)=?', (kind, parent['id'] if parent else 0)).fetchone()[0]
    new_id = c.execute('INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (parent['id'] if parent else None, kind, name, prefix, catalog_category, item_kind, tracking, position, stamp(now), stamp(now), user['id'])).lastrowid
    if prefix:
        _claim_prefix(c, prefix, new_id, now)
    event(c, now, user, 'categoria_creada', 'Categoría creada: %s%s.' % ((parent['name'] + ' › ' if parent else '') + name, ' (prefijo %s)' % prefix if prefix else ''))
    return new_id


def set_category_active(c, category_id, active, user, now):
    row = _category(c, category_id)
    c.execute('UPDATE inventory_categories SET active=?,updated_at=?,updated_by=? WHERE id=?', (1 if active else 0, stamp(now), user['id'], row['id']))
    event(c, now, user, 'categoria_activada' if active else 'categoria_desactivada', ('Activada: ' if active else 'Desactivada: ') + category_path(c, row['id']))


def ensure_brand(c, name, user, now):
    """Marca por nombre (sin distinguir mayúsculas); si no existe, se crea."""
    name = re.sub(r'\s+', ' ', str(name or '')).strip()[:60]
    if not name:
        return None
    row = c.execute('SELECT id FROM inventory_brands WHERE name=? COLLATE NOCASE', (name,)).fetchone()
    if row:
        return row[0]
    new_id = c.execute('INSERT INTO inventory_brands(name,created_at,updated_at,updated_by) VALUES (?,?,?,?)', (name, stamp(now), stamp(now), user['id'] if user else None)).lastrowid
    event(c, now, user, 'marca_creada', 'Marca registrada: ' + name)
    return new_id


def save_brand(c, data, user, now):
    name = _text(data, 'name', 60)
    if not name:
        raise InventoryError('Indica el nombre de la marca.', fields={'name': 'Nombre obligatorio.'})
    brand_id = _id(data.get('id'))
    clash = c.execute('SELECT id FROM inventory_brands WHERE name=? COLLATE NOCASE AND id!=?', (name, brand_id or 0)).fetchone()
    if clash:
        raise InventoryError('Esa marca ya existe.', fields={'name': 'Marca repetida.'})
    if brand_id:
        if not c.execute('SELECT 1 FROM inventory_brands WHERE id=?', (brand_id,)).fetchone():
            raise InventoryError('Marca no encontrada.', 404)
        c.execute('UPDATE inventory_brands SET name=?,updated_at=?,updated_by=? WHERE id=?', (name, stamp(now), user['id'], brand_id))
        event(c, now, user, 'marca_editada', 'Marca actualizada: ' + name)
        return brand_id
    return ensure_brand(c, name, user, now)


def set_brand_active(c, brand_id, active, user, now):
    row = c.execute('SELECT * FROM inventory_brands WHERE id=?', (brand_id,)).fetchone() if _id(brand_id) else None
    if not row:
        raise InventoryError('Marca no encontrada.', 404)
    c.execute('UPDATE inventory_brands SET active=?,updated_at=?,updated_by=? WHERE id=?', (1 if active else 0, stamp(now), user['id'], row['id']))
    event(c, now, user, 'marca_activada' if active else 'marca_desactivada', row['name'])


def save_family(c, data, user, now):
    """Familia de licencias (Categoría → Marca → Familia) con su lista configurable de ediciones (una por línea)."""
    category = _category(c, data.get('category_id'))
    if category['kind'] != 'licencia':
        raise InventoryError('Las familias son de categorías de licencias.', fields={'category_id': 'Elige una categoría de licencias.'})
    brand_id = _id(data.get('brand_id')) or ensure_brand(c, data.get('brand'), user, now)
    if not brand_id or not c.execute('SELECT 1 FROM inventory_brands WHERE id=?', (brand_id,)).fetchone():
        raise InventoryError('Elige la marca.', fields={'brand_id': 'Marca obligatoria.'})
    name = _text(data, 'name', 80)
    if len(name) < 2:
        raise InventoryError('Indica el nombre de la familia.', fields={'name': 'Nombre de 2 a 80 caracteres.'})
    editions = '\n'.join(dict.fromkeys(e.strip()[:80] for e in str(data.get('editions', '')).replace(';', '\n').split('\n') if e.strip()))[:2000]
    family_id = _id(data.get('id'))
    if c.execute('SELECT 1 FROM inventory_families WHERE category_id=? AND brand_id=? AND name=? COLLATE NOCASE AND id!=?', (category['id'], brand_id, name, family_id or 0)).fetchone():
        raise InventoryError('Esa familia ya existe para la marca.', fields={'name': 'Familia repetida.'})
    if family_id:
        c.execute('UPDATE inventory_families SET category_id=?,brand_id=?,name=?,editions=?,updated_at=?,updated_by=? WHERE id=?', (category['id'], brand_id, name, editions, stamp(now), user['id'], family_id))
    else:
        family_id = c.execute('INSERT INTO inventory_families(category_id,brand_id,name,editions,created_at,updated_at,updated_by) VALUES (?,?,?,?,?,?,?)',
                              (category['id'], brand_id, name, editions, stamp(now), stamp(now), user['id'])).lastrowid
    event(c, now, user, 'familia_guardada', 'Familia de licencias: %s (%s).' % (name, category['name']))
    return family_id


def set_family_active(c, family_id, active, user, now):
    row = c.execute('SELECT * FROM inventory_families WHERE id=?', (family_id,)).fetchone() if _id(family_id) else None
    if not row:
        raise InventoryError('Familia no encontrada.', 404)
    c.execute('UPDATE inventory_families SET active=?,updated_at=?,updated_by=? WHERE id=?', (1 if active else 0, stamp(now), user['id'], row['id']))


# ---- Fichas de productos físicos ---------------------------------------------------------------------------------------

PRODUCT_SQL = ('SELECT i.*,g.name,g.code catalog_code,g.price_cents,g.description,g.category catalog_category,b.name brand,k.name category_name,k.parent_id category_parent,'
               'p.name parent_name,' + inventory.STOCK_SQL + ' stock,' + inventory.RESERVED_SQL + ' reserved FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id '
               'LEFT JOIN inventory_brands b ON b.id=i.brand_id LEFT JOIN inventory_categories k ON k.id=i.category_id LEFT JOIN inventory_categories p ON p.id=k.parent_id')


def _product_dict(c, r, with_cost=True):
    cost = inventory.average_cost(c, r['id']) if with_cost else 0
    stock = r['stock']
    path = (r['parent_name'] + ' › ' + r['category_name']) if r['parent_name'] else (r['category_name'] or 'Sin categoría')
    units = {}
    if r['tracking'] == 'serie':
        units = {k: v for k, v in c.execute('SELECT status,COUNT(*) FROM inventory_units WHERE item_id=? GROUP BY status', (r['id'],))}
    state = inventory.stock_state(stock, r['min_stock'])
    alerts = bool(r['alerts_enabled']) if 'alerts_enabled' in r.keys() else True
    return {'id': r['id'], 'catalog_id': r['catalog_id'], 'name': r['name'], 'code': r['catalog_code'] or '', 'sku': r['sku'], 'model': r['model'], 'brand': r['brand'] or '',
            'brand_id': r['brand_id'], 'category_id': r['category_id'], 'category': path, 'top_category_id': r['category_parent'] or r['category_id'],
            'tracking': r['tracking'], 'tracking_label': TRACKING[r['tracking']], 'kind': r['kind'], 'stock': stock, 'reserved': r['reserved'], 'available': max(0, stock - r['reserved']),
            'min_stock': r['min_stock'], 'stock_state': state, 'stock_state_label': inventory.STOCK_STATES[state], 'alerts_enabled': alerts,
            # «low»: necesita atención (agotado, crítico o en el mínimo); «urgent»: agotado o crítico. Solo si la ficha tiene las alertas activas.
            'low': bool(r['active']) and alerts and state != 'normal', 'urgent': bool(r['active']) and alerts and state in ('agotado', 'critico'),
            'out': stock <= 0, 'location': r['location'], 'active': r['active'], 'warranty_terms': r['warranty_terms'] if 'warranty_terms' in r.keys() else '',
            'barcode': r['barcode'] if 'barcode' in r.keys() else '', 'max_stock': r['max_stock'] if 'max_stock' in r.keys() else 0,
            'over_max': bool('max_stock' in r.keys() and r['max_stock'] and stock > r['max_stock']),
            'price_cents': r['price_cents'], 'average_cost_cents': cost, 'value_cents': max(0, stock) * cost, 'description': r['description'] or '',
            'warranty_store': {'qty': r['warranty_store_qty'], 'unit': r['warranty_store_unit'], 'from': r['warranty_store_from'], 'label': period_label(r['warranty_store_qty'], r['warranty_store_unit'])},
            'warranty_maker': {'qty': r['warranty_maker_qty'], 'unit': r['warranty_maker_unit'], 'from': r['warranty_maker_from'], 'label': period_label(r['warranty_maker_qty'], r['warranty_maker_unit'])},
            'units': units}


def product(c, item_id):
    row = c.execute(PRODUCT_SQL + ' WHERE i.id=?', (item_id,)).fetchone() if _id(item_id) else None
    if not row:
        raise InventoryError('Producto no encontrado.', 404)
    return _product_dict(c, row)


def _category_ids(c, category_id):
    if not _id(category_id):
        return None
    return [category_id and int(category_id)] + [r[0] for r in c.execute('SELECT id FROM inventory_categories WHERE parent_id=?', (int(category_id),))]


def products(c, q='', category_id='', brand_id='', state=''):
    """Catálogo de productos físicos. La búsqueda también encuentra el producto por el código interno o la serie de una de sus unidades."""
    rows = c.execute(PRODUCT_SQL + ' ORDER BY i.active DESC,g.name COLLATE NOCASE').fetchall()
    cats = _category_ids(c, category_id)
    words = [w for w in re.sub(r'\s+', ' ', str(q or '')).lower().split(' ') if w]
    unit_hits = set()
    if q:
        key = inventory.serial_key(q)
        unit_hits = {r[0] for r in c.execute('SELECT item_id FROM inventory_units WHERE serial_key LIKE ? OR internal_code LIKE ?', ('%' + key + '%', '%' + key + '%'))}
    archived = archived_ids(c)
    out = []
    for r in rows:
        if r['id'] in archived and state not in ('inactivo', 'archivado'):
            continue  # archivadas: fuera del catálogo activo (siguen en el Kardex, las ventas y las facturas)
        if state == 'archivado' and r['id'] not in archived:
            continue
        if cats and r['category_id'] not in cats:
            continue
        if _id(brand_id) and r['brand_id'] != int(brand_id):
            continue
        hay = ' '.join(str(v or '') for v in (r['name'], r['sku'], r['model'], r['brand'], r['category_name'], r['parent_name'], r['catalog_code'], r['location'])).lower()
        if words and r['id'] not in unit_hits and not all(w in hay for w in words):
            continue
        item = _product_dict(c, r)
        if (state == 'bajo' and not item['low'] or state in inventory.STOCK_STATES and (item['stock_state'] != state or not item['active'])
                or state == 'inactivo' and item['active'] or state == 'activo' and not item['active'] or state == 'sin_alertas' and item['alerts_enabled']):
            continue
        out.append(item)
    return out


def _warranty_fields(data, prefix, errors):
    qty_text = str(data.get(prefix + '_qty', '0') or '0').strip()
    unit = str(data.get(prefix + '_unit') or 'meses')
    start = str(data.get(prefix + '_from') or 'venta')
    if not re.fullmatch(r'\d{1,4}', qty_text) or int(qty_text) > 3650:
        errors[prefix + '_qty'] = 'Número entero de 0 a 3650.'
        qty_text = '0'
    if unit not in PERIODS:
        errors[prefix + '_unit'] = 'Días, meses o años.'
        unit = 'meses'
    if start not in STARTS:
        errors[prefix + '_from'] = 'Desde la venta o desde la entrega.'
        start = 'venta'
    return int(qty_text), unit, start


def save_product(c, data, user, now):
    """Ficha comercial (modelo): crea el producto en el catálogo (para presupuestos y facturas) y en el inventario, o la edita.
    Evita duplicados: misma marca y modelo en la misma categoría, mismo nombre o mismo SKU."""
    import quotes
    item_id = _id(data.get('id'))
    old = c.execute('SELECT * FROM inventory_items WHERE id=?', (item_id,)).fetchone() if item_id else None
    if item_id and not old:
        raise InventoryError('Producto no encontrado.', 404)
    errors = {}
    try:
        category = _category(c, data.get('category_id') or (old['category_id'] if old else None))
        if category['kind'] != 'fisico':
            errors['category_id'] = 'Las licencias se registran en el módulo Licencias.'
    except InventoryError:
        category = None
        errors['category_id'] = 'Elige la categoría.'
    brand_name = _text(data, 'brand', 60)
    model = _text(data, 'model', 120)
    name = _text(data, 'name', 120) or ' '.join(part for part in (category['name'] if category and category['parent_id'] else '', brand_name, model) if part)
    if len(name) < 2:
        errors['name'] = 'Indica el nombre del producto (2 a 120 caracteres).'
    sku = re.sub(r'\s', '', str(data.get('sku', '')))[:40]
    if sku and not re.fullmatch(r'[A-Za-z0-9._/-]{2,40}', sku):
        errors['sku'] = 'Letras, números, punto, barra, guion o guion bajo.'
    elif sku and c.execute('SELECT 1 FROM inventory_items WHERE sku=? AND id!=?', (sku, item_id or 0)).fetchone():
        errors['sku'] = 'Ese SKU ya pertenece a otro producto.'
    tracking = str(data.get('tracking') or (old['tracking'] if old else category['tracking'] if category else 'serie'))
    if tracking not in TRACKING:
        errors['tracking'] = 'Por serie o a granel.'
    try:
        minimum = int(str(data.get('min_stock', old['min_stock'] if old else '0') or '0'))
        assert 0 <= minimum <= 100000
    except (ValueError, AssertionError):
        errors['min_stock'] = 'Número entero de 0 en adelante.'
        minimum = 0
    try:
        price = cents(data.get('price', '0') or '0', 'price')
    except InventoryError:
        errors['price'] = 'Precio en USD con hasta dos decimales.'
        price = 0
    location = _text(data, 'location', 80)
    store = _warranty_fields(data, 'warranty_store', errors)
    maker = _warranty_fields(data, 'warranty_maker', errors)
    brand_id = ensure_brand(c, brand_name, user, now) if brand_name and not errors else None
    if not errors and brand_id and model and category:
        clash = c.execute('SELECT g.name FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE i.active=1 AND i.category_id=? AND i.brand_id=? AND lower(i.model)=lower(?) AND i.id!=?',
                          (category['id'], brand_id, model, item_id or 0)).fetchone()
        if clash:
            errors['model'] = 'Ya existe la ficha «%s» con esa marca y modelo: regístrale las unidades a ella.' % clash[0]
    if old and not errors and tracking != old['tracking']:
        stock = c.execute('SELECT COALESCE(SUM(direction*quantity),0) FROM inventory_movements WHERE item_id=?', (old['id'],)).fetchone()[0]
        if stock:
            errors['tracking'] = 'Solo se cambia con existencias en cero (hay %d).' % stock
    if errors:
        raise InventoryError('Revisa los datos del producto.', fields=errors)
    catalog_id = old['catalog_id'] if old else _id(data.get('catalog_id'))
    description = _text(data, 'description', 500) or model
    if catalog_id and not old:
        linked = c.execute("SELECT * FROM catalog_items WHERE id=? AND category IN ('repuesto','otro')", (catalog_id,)).fetchone()
        if not linked:
            raise InventoryError('Elige un producto físico del catálogo.', fields={'catalog_id': 'Producto no válido.'})
        if c.execute('SELECT 1 FROM inventory_items WHERE catalog_id=?', (catalog_id,)).fetchone():
            raise InventoryError('Ese producto del catálogo ya tiene su ficha de inventario.', 409, {'catalog_id': 'Ya está en el inventario.'})
    try:
        if old or catalog_id:
            current = c.execute('SELECT * FROM catalog_items WHERE id=?', (catalog_id,)).fetchone()
            quotes.save_catalog_item(c, {'id': str(catalog_id), 'name': name, 'description': current['description'] if not data.get('description') else description, 'category': current['category'],
                                         'brand': brand_name or current['brand'], 'price': '%d.%02d' % divmod(price, 100) if 'price' in data else '%d.%02d' % divmod(current['price_cents'], 100),
                                         'price_mode': 'incluido', 'available': bool(current['available'])}, user, now)
        else:
            catalog_id = quotes.save_catalog_item(c, {'name': name, 'description': description, 'category': category['catalog_category'], 'brand': brand_name,
                                                      'price': '%d.%02d' % divmod(price, 100), 'price_mode': 'incluido'}, user, now)
    except quotes.QuoteError as error:
        raise InventoryError(str(error), error.status, {('name' if k in ('name', 'category') else k): v for k, v in error.fields.items()})
    values = (category['id'], brand_id, model, tracking, sku, minimum, location, *store, *maker, stamp(now), user['id'])
    if old:
        c.execute('UPDATE inventory_items SET category_id=?,brand_id=?,model=?,tracking=?,sku=?,min_stock=?,location=?,warranty_store_qty=?,warranty_store_unit=?,warranty_store_from=?,'
                  'warranty_maker_qty=?,warranty_maker_unit=?,warranty_maker_from=?,kind=?,updated_at=?,updated_by=? WHERE id=?', (*values[:-2], category['item_kind'], *values[-2:], old['id']))
        _extra_fields(c, old['id'], data, old)
        event(c, now, user, 'ficha_editada', 'Ficha actualizada: %s.' % name, old['id'])
        return old['id']
    new_id = c.execute('INSERT INTO inventory_items(category_id,brand_id,model,tracking,sku,min_stock,location,warranty_store_qty,warranty_store_unit,warranty_store_from,'
                       'warranty_maker_qty,warranty_maker_unit,warranty_maker_from,catalog_id,kind,active,created_at,created_by,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)',
                       (*values[:-2], catalog_id, category['item_kind'], stamp(now), user['id'], stamp(now), user['id'])).lastrowid
    _extra_fields(c, new_id, data, None)
    event(c, now, user, 'ficha_creada', 'Ficha creada: %s (%s, %s).' % (name, category_path(c, category['id']), TRACKING[tracking].split(' (')[0].lower()), new_id)
    return new_id


def _extra_fields(c, item_id, data, old):
    """Alertas de la ficha y condiciones de garantía (migración 075); código de barras y existencia máxima (077). Si no se indican, se conservan."""
    if 'barcode' in data or 'max_stock' in data:
        _codes(c, item_id, data)
    if 'description' in data:
        text = re.sub(r'[ \t]+', ' ', str(data.get('description') or '')).strip()[:500]
        c.execute('UPDATE catalog_items SET description=? WHERE id=(SELECT catalog_id FROM inventory_items WHERE id=?)', (text, item_id))
    try:
        if str(data.get('alerts_enabled', '')) in ('0', '1', 'true', 'false'):
            c.execute('UPDATE inventory_items SET alerts_enabled=? WHERE id=?', (1 if str(data['alerts_enabled']) in ('1', 'true') else 0, item_id))
        if 'warranty_terms' in data:
            c.execute('UPDATE inventory_items SET warranty_terms=? WHERE id=?', (str(data.get('warranty_terms') or '').strip()[:500], item_id))
    except Exception as error:
        if 'no such column' not in str(error):
            raise


def _codes(c, item_id, data):
    """Código de barras único (sin duplicar fichas) y existencia máxima mayor o igual que la mínima."""
    if not _has_column(c, 'inventory_items', 'barcode'):
        return
    row = c.execute('SELECT min_stock,barcode,max_stock FROM inventory_items WHERE id=?', (item_id,)).fetchone()
    barcode = re.sub(r'\s', '', str(data.get('barcode', row['barcode']) or ''))[:40]
    if barcode and not re.fullmatch(r'[A-Za-z0-9.\-_/]{4,40}', barcode):
        raise InventoryError('Código de barras no válido.', 400, {'barcode': 'Entre 4 y 40 letras, números o guiones.'})
    if barcode:
        other = c.execute('SELECT i.id,g.name FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE i.barcode=? AND i.id!=?', (barcode, item_id)).fetchone()
        if other:
            raise InventoryError('Ese código de barras ya pertenece a «%s».' % other['name'], 409, {'barcode': 'Código de barras duplicado.'})
        unit = c.execute('SELECT internal_code FROM inventory_units WHERE serial_key=?', (inventory.serial_key(barcode),)).fetchone()
        if unit:
            raise InventoryError('Ese código coincide con la serie de la unidad %s.' % unit['internal_code'], 409, {'barcode': 'Coincide con una serie.'})
    raw = str(data.get('max_stock', row['max_stock']) if data.get('max_stock') not in (None, '') else '0').strip()
    if not raw.isdigit() or int(raw) > 1000000:
        raise InventoryError('Existencia máxima no válida.', 400, {'max_stock': 'Número entero.'})
    if int(raw) and int(raw) < row['min_stock']:
        raise InventoryError('La existencia máxima no puede ser menor que la mínima.', 400, {'max_stock': 'Menor que la mínima.'})
    c.execute('UPDATE inventory_items SET barcode=?,max_stock=? WHERE id=?', (barcode, int(raw), item_id))


def set_alerts(c, item_id, enabled, user, now):
    """Activa o desactiva las alertas de existencias de una ficha (p. ej., productos sin reposición automática)."""
    item = product(c, item_id)
    c.execute('UPDATE inventory_items SET alerts_enabled=?,updated_at=?,updated_by=? WHERE id=?', (1 if enabled else 0, stamp(now), user['id'], item['id']))
    event(c, now, user, 'alertas_' + ('activadas' if enabled else 'desactivadas'), 'Alertas de existencias %s: %s.' % ('activadas' if enabled else 'desactivadas', item['name']), item['id'])


def correct_cost(c, movement_id, cost, reason, user, now, document=''):
    """Corrige el costo de una entrada registrada con un costo equivocado. El movimiento original no cambia: la corrección queda auditada
    (costo anterior y nuevo, motivo, quién y cuándo) y el Kardex valorizado usa el costo corregido desde esa entrada."""
    m = c.execute('SELECT * FROM inventory_movements WHERE id=?', (movement_id,)).fetchone() if _id(movement_id) else None
    if not m or m['direction'] != 1 or m['reason'] not in ('inicial', 'compra', 'ajuste_entrada', 'devolucion_cliente'):
        raise InventoryError('Solo se corrige el costo de una entrada.', 404 if not m else 409)
    if m['reference_kind'] == 'compra':
        raise InventoryError('Esta entrada viene de una compra registrada: corrige el documento de compra, no el Kardex.', 409)
    if str(cost or '').strip() == '':
        raise InventoryError('Indica el costo unitario correcto.', fields={'cost': 'Costo obligatorio.'})
    new_cost = cents(cost, 'cost')
    reason = re.sub(r'\s+', ' ', str(reason or '')).strip()[:300]
    if len(reason) < 5:
        raise InventoryError('Indica el motivo de la corrección.', fields={'reason': 'Motivo obligatorio (al menos 5 caracteres).'})
    old = inventory.corrections(c, m['item_id']).get(m['id'], m['unit_cost_cents'])
    if new_cost == old:
        raise InventoryError('El costo indicado es igual al vigente.', fields={'cost': 'Sin cambio.'})
    c.execute('INSERT INTO inventory_cost_corrections(movement_id,item_id,old_cost_cents,new_cost_cents,reason,document,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
              (m['id'], m['item_id'], old, new_cost, reason, re.sub(r'\s+', ' ', str(document or '')).strip()[:80], user['id'], stamp(now)))
    c.execute('UPDATE inventory_units SET unit_cost_cents=?,updated_at=?,updated_by=? WHERE entry_movement_id=?', (new_cost, stamp(now), user['id'], m['id']))
    event(c, now, user, 'costo_corregido', 'Costo de la entrada #%d corregido de %s a %s: %s' % (m['id'], usd(old), usd(new_cost), reason), m['item_id'])
    return product(c, m['item_id'])


# ---- Registrar mercadería e inventario inicial -------------------------------------------------------------------------

def serial_check(c, serial):
    value = inventory.clean_serial(serial)
    owner = inventory.serial_owner(c, value)
    return {'serial': value, 'exists': bool(owner), 'unit': dict(owner) if owner else None}


def register(c, data, user, now):
    """Asistente «Registrar inventario inicial» / «Registrar mercadería»: crea la ficha si no existe y registra la entrada con sus unidades
    (cada una con su código interno y, si se escaneó, su serie). Todo en la misma transacción: si algo falla, no queda nada a medias."""
    reason = str(data.get('reason') or 'inicial')
    if reason not in ENTRY_REASONS:
        raise InventoryError('Motivo de ingreso no válido.', fields={'reason': 'Motivo no válido.'})
    key = str(data.get('request_key') or '')[:64] or None
    if key:
        done = c.execute('SELECT id,item_id FROM inventory_movements WHERE request_key=?', (key,)).fetchone()
        if done:  # reintento del mismo envío: devuelve lo ya registrado
            return _register_result(c, done['item_id'], done['id'])
    item_id = _id(data.get('item_id'))
    if not item_id:
        fields = data.get('product')
        fields = json.loads(fields) if isinstance(fields, str) and fields.strip().startswith('{') else fields if isinstance(fields, dict) else None
        if not isinstance(fields, dict):
            raise InventoryError('Elige el producto o crea uno nuevo.', fields={'item_id': 'Producto obligatorio.'})
        item_id = save_product(c, {k: v for k, v in fields.items() if isinstance(v, (str, bool))}, user, now)
    item = product(c, item_id)
    if not item['active']:
        raise InventoryError('El producto está desactivado.', 409)
    # Costo obligatorio: un campo vacío ya no se guarda como 0 (auditoría del 26/10/2026). Un costo 0 debe escribirse expresamente.
    if str(data.get('cost', '') or '').strip() == '':
        raise InventoryError('Indica el costo unitario (escribe 0 solo si el producto no tuvo costo).', fields={'cost': 'Costo obligatorio.'})
    try:
        cost = cents(data.get('cost'), 'cost')
    except InventoryError:
        raise InventoryError('Costo unitario no válido.', fields={'cost': 'Importe en USD con hasta dos decimales.'})
    supplier_id = _id(data.get('supplier_id'))
    if supplier_id and not c.execute('SELECT 1 FROM suppliers WHERE id=? AND active=1', (supplier_id,)).fetchone():
        raise InventoryError('Elige un proveedor activo.', fields={'supplier_id': 'Proveedor no válido.'})
    tax = {'': 0, '0': 0, '15': 1500}.get(str(data.get('tax', '') or ''), None)
    if tax is None:
        raise InventoryError('IVA del costo no válido.', fields={'tax': 'Elige 0 % o 15 %.'})
    document = _text(data, 'document', 80)
    if not data.get('product'):
        _update_commercial(c, item, data, user, now)
    serials = []
    if item['tracking'] == 'serie':
        units = _json_list(data.get('units'), 'units')
        if not units:
            raise InventoryError('Agrega al menos una unidad (escanea su serie o regístrala solo con código interno).', fields={'units': 'Sin unidades.'})
        if len(units) > MAX_UNITS:
            raise InventoryError('Máximo %d unidades por ingreso.' % MAX_UNITS, fields={'units': 'Demasiadas unidades.'})
        serials = [str(u.get('serial', '') if isinstance(u, dict) else u or '') for u in units]
        amount = str(len(serials))
    else:
        amount = str(data.get('quantity') or '')
    movement = inventory.move(c, item_id, 1, reason, amount, '%d.%02d' % divmod(cost, 100), user, now, note=_text(data, 'note', 300) or ENTRY_REASONS[reason],
                              request_key=key, serials=serials, location=_text(data, 'location', 80), supplier_id=supplier_id, document=document, tax_rate_bp=tax)
    if _text(data, 'location', 80) and item['tracking'] == 'granel':
        c.execute('UPDATE inventory_items SET location=? WHERE id=?', (_text(data, 'location', 80), item_id))
    return _register_result(c, item_id, movement)


def _update_commercial(c, item, data, user, now):
    """Producto existente: el asistente puede actualizar su precio de venta y sus garantías (queda en el historial de la ficha)."""
    import quotes
    price_text = str(data.get('price', '') or '').strip()
    if price_text:
        price = cents(price_text, 'price')
        if price != item['price_cents']:
            row = c.execute('SELECT * FROM catalog_items WHERE id=?', (item['catalog_id'],)).fetchone()
            try:
                quotes.save_catalog_item(c, {'id': str(row['id']), 'name': row['name'], 'description': row['description'], 'category': row['category'], 'brand': row['brand'],
                                             'price': '%d.%02d' % divmod(price, 100), 'price_mode': 'incluido', 'available': bool(row['available'])}, user, now)
            except quotes.QuoteError as error:
                raise InventoryError(str(error), error.status, {'price': str(error)})
            event(c, now, user, 'precio_actualizado', 'Precio de venta de %s: %s → %s.' % (item['name'], usd(item['price_cents']), usd(price)), item['id'])
    if any(k in data for k in ('warranty_store_qty', 'warranty_maker_qty')):
        errors = {}
        store, maker = _warranty_fields(data, 'warranty_store', errors), _warranty_fields(data, 'warranty_maker', errors)
        if errors:
            raise InventoryError('Revisa las garantías.', fields=errors)
        c.execute('UPDATE inventory_items SET warranty_store_qty=?,warranty_store_unit=?,warranty_store_from=?,warranty_maker_qty=?,warranty_maker_unit=?,warranty_maker_from=?,updated_at=?,updated_by=? WHERE id=?',
                  (*store, *maker, stamp(now), user['id'], item['id']))
        _extra_fields(c, item['id'], data, item)


def _register_result(c, item_id, movement_id):
    units = [dict(r) for r in c.execute('SELECT u.id,u.internal_code,u.serial,u.location FROM inventory_movement_units m JOIN inventory_units u ON u.id=m.unit_id WHERE m.movement_id=? ORDER BY u.id', (movement_id,))]
    move = c.execute('SELECT quantity,unit_cost_cents FROM inventory_movements WHERE id=?', (movement_id,)).fetchone()
    return {'item': product(c, item_id), 'movement_id': movement_id, 'quantity': move['quantity'], 'unit_cost_cents': move['unit_cost_cents'], 'units': units}


# ---- Unidades ------------------------------------------------------------------------------------------------------------

UNIT_SQL = ('SELECT u.*,g.name product,i.sku,i.tracking,b.name brand,c.name client,o.code order_code FROM inventory_units u JOIN inventory_items i ON i.id=u.item_id '
            'JOIN catalog_items g ON g.id=i.catalog_id LEFT JOIN inventory_brands b ON b.id=i.brand_id LEFT JOIN clients c ON c.id=u.client_id LEFT JOIN orders o ON o.id=u.order_id')


def units(c, item_id=None, q='', status=''):
    where, args = [], []
    if _id(item_id):
        where.append('u.item_id=?')
        args.append(int(item_id))
    if status in inventory.UNIT_STATUS:
        where.append('u.status=?')
        args.append(status)
    if q:
        key = inventory.serial_key(q)
        where.append('(u.serial_key LIKE ? OR u.internal_code LIKE ?)')
        args += ['%' + key + '%', '%' + key + '%']
    rows = c.execute(UNIT_SQL + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY u.id DESC LIMIT 500', args).fetchall()
    return [dict(r, status_label=inventory.UNIT_STATUS[r['status']]) for r in rows]


def unit_detail(c, unit_id):
    row = c.execute(UNIT_SQL + ' WHERE u.id=?', (unit_id,)).fetchone() if _id(unit_id) else None
    if not row:
        raise InventoryError('Unidad no encontrada.', 404)
    out = dict(row, status_label=inventory.UNIT_STATUS[row['status']])
    out['movements'] = [dict(r, reason_label=(inventory.IN_REASONS if r['direction'] == 1 else inventory.OUT_REASONS)[r['reason']]) for r in c.execute(
        "SELECT m.id,m.created_at,m.direction,m.reason,m.note,COALESCE(s.name,'Sistema') actor FROM inventory_movement_units x JOIN inventory_movements m ON m.id=x.movement_id "
        'LEFT JOIN users s ON s.id=m.created_by WHERE x.unit_id=? ORDER BY m.id', (row['id'],))]
    out['events'] = [dict(r) for r in c.execute('SELECT event,detail,actor,created_at FROM inventory_events WHERE unit_id=? ORDER BY id DESC', (row['id'],))]
    out['warranty'] = _unit_warranty(c, row, date.today())
    return out


def set_serial(c, unit_id, serial, reason, user, now):
    """Agrega la serie a una unidad registrada solo con código interno, o la corrige (con motivo y trazabilidad)."""
    row = c.execute('SELECT * FROM inventory_units WHERE id=?', (unit_id,)).fetchone() if _id(unit_id) else None
    if not row:
        raise InventoryError('Unidad no encontrada.', 404)
    value = inventory.clean_serial(serial)
    if not value:
        raise InventoryError('Escanea o escribe la serie.', fields={'serial': 'Serie obligatoria.'})
    owner = inventory.serial_owner(c, value)
    if owner and owner['id'] != row['id']:
        raise InventoryError('La serie %s ya está registrada (%s · %s).' % (value, owner['internal_code'], owner['name']), 409, {'serial': 'Serie duplicada.'})
    reason = re.sub(r'\s+', ' ', str(reason or '')).strip()[:200]
    if row['serial'] and len(reason) < 5:
        raise InventoryError('Indica el motivo de la corrección de la serie.', fields={'reason': 'Motivo obligatorio.'})
    c.execute('UPDATE inventory_units SET serial=?,serial_key=?,updated_at=?,updated_by=? WHERE id=?', (value, inventory.serial_key(value), stamp(now), user['id'], row['id']))
    event(c, now, user, 'serie_corregida' if row['serial'] else 'serie_registrada',
          ('Serie corregida de %s a %s: %s' % (row['serial'], value, reason)) if row['serial'] else 'Serie %s registrada en %s.' % (value, row['internal_code']), row['item_id'], unit_id=row['id'])
    return row['id']


# ---- Salidas (venta, consumo en orden y demás), garantías y reservas --------------------------------------------------

def _order_by_code(c, code):
    code = re.sub(r'\s', '', str(code or '')).upper()
    row = c.execute('SELECT o.id,o.code,d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE upper(o.code)=?', (code,)).fetchone() if code else None
    if not row:
        raise InventoryError('No existe la orden %s.' % (code or ''), 404, {'order_code': 'Orden no encontrada.'})
    return row


def _date_field(data, key, today, required=False):
    text = str(data.get(key) or '').strip()
    if not text:
        if required:
            raise InventoryError('Indica la fecha.', fields={key: 'Fecha obligatoria.'})
        return None
    try:
        value = date.fromisoformat(text)
    except ValueError:
        raise InventoryError('Fecha no válida.', fields={key: 'Fecha no válida.'})
    if value > today:
        raise InventoryError('La fecha no puede ser futura.', fields={key: 'Fecha futura.'})
    return value


def warranty_dates(item, sold, delivered):
    """Fechas de las dos coberturas según la política de cada una. Sin la fecha de inicio (por ejemplo, aún no entregado), sin fechas."""
    out = {}
    for key, column in (('store', 'warranty_store'), ('maker', 'warranty_maker')):
        amount, unit, start_on = item[column + '_qty'], item[column + '_unit'], item[column + '_from']
        start = sold if start_on == 'venta' else delivered
        end = add_period(start, amount, unit) if start and amount else None
        out[key + '_warranty_from'] = start.isoformat() if end else ''
        out[key + '_warranty_to'] = end.isoformat() if end else ''
    return out


def exit_stock(c, data, user, now):
    """Salida confirmada: una sola por documento y artículo. Venta (con cliente y fechas de garantía), consumo en una orden técnica,
    devolución al proveedor, ajuste o baja. Si consume una reserva, la reserva queda cerrada en la misma salida."""
    item_row = c.execute('SELECT * FROM inventory_items WHERE id=?', (data.get('item_id'),)).fetchone() if _id(data.get('item_id')) else None
    if not item_row:
        raise InventoryError('Producto no encontrado.', 404, {'item_id': 'Elige el producto.'})
    reason = str(data.get('reason', ''))
    if reason not in EXIT_REASONS:
        raise InventoryError('Motivo de salida no válido.', fields={'reason': 'Motivo no válido.'})
    today = now.date()
    reference_kind, reference_id, values, note = '', None, {}, _text(data, 'note', 300)
    order = None
    if reason == 'uso_orden':
        order = _order_by_code(c, data.get('order_code'))
        reference_kind, reference_id = 'orden', order['id']
        values.update(order_id=order['id'], client_id=order['client_id'])
        note = note or 'Consumo en la orden ' + order['code']
    document = _text(data, 'document', 80)
    if reason == 'venta':
        client = _id(data.get('client_id'))
        if client and not c.execute('SELECT 1 FROM clients WHERE id=?', (client,)).fetchone():
            raise InventoryError('Cliente no encontrado.', 404, {'client_id': 'Cliente no válido.'})
        values['client_id'] = client
        if _text(data, 'order_code', 40):
            order = _order_by_code(c, data.get('order_code'))
            values['order_id'] = order['id']
            values['client_id'] = values['client_id'] or order['client_id']
        note = note or ('Venta' + (' · ' + document if document else ''))
    if reason in ('venta', 'uso_orden'):
        sold = _date_field(data, 'sold_at', today) or today
        delivered = _date_field(data, 'delivered_at', today) if str(data.get('delivered', '1')) != '0' else None
        if str(data.get('delivered', '1')) != '0' and not delivered:
            delivered = sold
        if delivered and delivered < sold:
            raise InventoryError('La entrega no puede ser anterior a la venta.', fields={'delivered_at': 'Fecha anterior a la venta.'})
        values.update(document=document, sold_at=sold.isoformat(), delivered_at=delivered.isoformat() if delivered else '', **warranty_dates(item_row, sold, delivered))
    unit_ids = _json_list(data.get('unit_ids'), 'units') if item_row['tracking'] == 'serie' else None
    amount = str(len(unit_ids)) if unit_ids is not None else str(data.get('quantity') or '')
    sale = _sale_price(c, item_row, data, values.get('client_id'), user, now) if reason == 'venta' else None
    try:
        movement = inventory.move(c, item_row['id'], -1, reason, amount, '0', user, now, reference_kind, reference_id, note, str(data.get('request_key') or '')[:64] or None,
                                  unit_ids=unit_ids, reservation_id=_id(data.get('reservation_id')), unit_values=values, document=document if reason == 'venta' else '', sale=sale)
    except Exception as error:
        if 'UNIQUE' in str(error) and reference_kind == 'orden':
            raise InventoryError('La orden %s ya registró la salida de este producto: no se descuenta dos veces.' % order['code'], 409, {'order_code': 'Salida ya registrada.'})
        raise
    return {'movement_id': movement, 'item': product(c, item_row['id'])}


def pricing(c, item):
    """Costo, precio (con y sin IVA), IVA, margen bruto estimado, precio mínimo y descuento autorizado de una ficha."""
    import quotes
    row = c.execute('SELECT price_cents,taxed FROM catalog_items WHERE id=?', (item['catalog_id'],)).fetchone()
    rate = quotes.tax_rate(c) if row['taxed'] else 0
    price = row['price_cents']
    net = (2 * price * 10000 + (10000 + rate)) // (2 * (10000 + rate)) if rate else price
    cost = item['average_cost_cents']
    margin = net - cost
    keys = item.keys() if hasattr(item, 'keys') else item
    return {'price_cents': price, 'net_cents': net, 'tax_rate_bp': rate, 'tax_cents': price - net, 'cost_cents': cost, 'margin_cents': margin,
            'margin_bp': (margin * 10000 // net) if net else None, 'min_price_cents': item.get('min_price_cents', 0) if isinstance(item, dict) else 0,
            'max_discount_bp': item.get('max_discount_bp', 0) if isinstance(item, dict) else 0}


def _percent_bp(text, field):
    value = str(text or '').strip().replace(',', '.').rstrip('%').strip()
    if not value:
        return 0
    if not re.fullmatch(r'\d{1,3}(\.\d{1,2})?', value) or float(value) > 100:
        raise InventoryError('Porcentaje no válido.', fields={field: 'De 0 a 100 %.'})
    return int(round(float(value) * 100))


def save_pricing(c, item_id, data, user, now):
    """Precio de venta (IVA incluido), precio mínimo y descuento máximo autorizado de una ficha (solo administración)."""
    import quotes
    item = product(c, item_id)
    errors = {}
    try:
        price = cents(data.get('price', '') or '0', 'price')
    except InventoryError:
        errors['price'] = 'Precio en USD con hasta dos decimales.'
        price = 0
    try:
        minimum = cents(data.get('min_price', '') or '0', 'min_price')
    except InventoryError:
        errors['min_price'] = 'Precio en USD con hasta dos decimales.'
        minimum = 0
    try:
        discount = _percent_bp(data.get('max_discount'), 'max_discount')
    except InventoryError as error:
        errors.update(error.fields)
        discount = 0
    if not errors and minimum > price and price:
        errors['min_price'] = 'El precio mínimo no puede superar el precio de venta.'
    if errors:
        raise InventoryError('Revisa los precios.', fields=errors)
    if price != item['price_cents']:
        row = c.execute('SELECT * FROM catalog_items WHERE id=?', (item['catalog_id'],)).fetchone()
        try:
            quotes.save_catalog_item(c, {'id': str(row['id']), 'name': row['name'], 'description': row['description'], 'category': row['category'], 'brand': row['brand'],
                                         'price': '%d.%02d' % divmod(price, 100), 'price_mode': 'incluido', 'available': bool(row['available'])}, user, now)
        except quotes.QuoteError as error:
            raise InventoryError(str(error), error.status, {'price': str(error)})
    c.execute('UPDATE inventory_items SET min_price_cents=?,max_discount_bp=?,updated_at=?,updated_by=? WHERE id=?', (minimum, discount, stamp(now), user['id'], item['id']))
    event(c, now, user, 'precios', 'Precios de %s: venta %s, mínimo %s, descuento máximo %s %%.' % (item['name'], usd(price), usd(minimum), ('%g' % (discount / 100)).replace('.', ',')), item['id'])
    return product(c, item['id'])


def _sale_price(c, item_row, data, client_id, user, now):
    """Precio de una venta (por unidad, IVA incluido): de lista o el indicado, con el descuento autorizado. Un precio 0, por debajo del mínimo o
    con un descuento mayor al autorizado exige una autorización administrativa expresa con su motivo, que queda registrada."""
    listed = c.execute('SELECT price_cents FROM catalog_items WHERE id=?', (item_row['catalog_id'],)).fetchone()['price_cents']
    text = str(data.get('unit_price', '') or '').strip()
    try:
        price = cents(text, 'unit_price') if text else listed
    except InventoryError:
        raise InventoryError('Precio no válido.', fields={'unit_price': 'Precio en USD con hasta dos decimales.'})
    discount_bp = _percent_bp(data.get('discount'), 'discount')
    discount = (2 * price * discount_bp + 10000) // 20000
    final = price - discount
    keys = item_row.keys()
    minimum = item_row['min_price_cents'] if 'min_price_cents' in keys else 0
    allowed = item_row['max_discount_bp'] if 'max_discount_bp' in keys else 0
    problems = []
    if final <= 0:
        problems.append('el precio final es $0,00')
    if minimum and final < minimum:
        problems.append('es menor que el precio mínimo (%s)' % usd(minimum))
    if discount_bp > allowed:
        problems.append('el descuento supera el autorizado (%s %%)' % ('%g' % (allowed / 100)).replace('.', ','))
    authorization = ''
    if problems:
        reason = re.sub(r'\s+', ' ', str(data.get('authorization', '') or '')).strip()[:200]
        if str(data.get('authorize', '')) not in ('1', 'true') or len(reason) < 10:
            raise InventoryError('Esta venta requiere autorización administrativa expresa: ' + '; '.join(problems) + '.', 409,
                                 {'authorization': 'Marca la autorización e indica el motivo (al menos 10 caracteres).'})
        authorization = '%s · %s: %s' % (user['name'], '; '.join(problems), reason)
    return {'sale_price_cents': final, 'discount_cents': discount, 'client_id': client_id, 'price_authorization': authorization}


def sales_history(c, item_id):
    """Ventas del producto: fecha, cliente, documento, series vendidas, precio, estado actual de la unidad y garantía comercial."""
    try:
        rows = c.execute("SELECT m.*,COALESCE(k.name,'') client,COALESCE(s.name,'Sistema') actor FROM inventory_movements m LEFT JOIN clients k ON k.id=m.client_id "
                         "LEFT JOIN users s ON s.id=m.created_by WHERE m.item_id=? AND m.reason='venta' ORDER BY m.id DESC", (item_id,)).fetchall()
    except Exception:
        return []
    out = []
    for m in rows:
        units = [dict(u) for u in c.execute('SELECT u.id,u.internal_code,u.serial,u.status,u.store_warranty_to,COALESCE(k.name,\'\') client FROM inventory_movement_units x JOIN inventory_units u ON u.id=x.unit_id '
                                             'LEFT JOIN clients k ON k.id=u.client_id WHERE x.movement_id=?', (m['id'],))]
        client = m['client'] or next((u['client'] for u in units if u['client']), '')
        status = 'devuelta' if units and all(u['status'] == 'disponible' for u in units) else 'vendida'
        out.append({'id': m['id'], 'at': m['created_at'], 'client': client, 'document': m['document'] or m['note'], 'quantity': m['quantity'], 'units': units,
                    'price_cents': m['sale_price_cents'], 'discount_cents': m['discount_cents'], 'authorization': m['price_authorization'], 'status': status,
                    'warranty_to': next((u['store_warranty_to'] for u in units if u['store_warranty_to']), ''), 'actor': m['actor']})
    return out


def product_sheet(c, item_id, now):
    """Ficha comercial completa: datos, precios y margen, unidades, reservas, ventas, entradas (con correcciones de costo), Kardex y
    avisos de datos faltantes (sin inventar ningún valor)."""
    item = product(c, item_id)
    raw = c.execute('SELECT * FROM inventory_items WHERE id=?', (item['id'],)).fetchone()
    item['min_price_cents'] = raw['min_price_cents'] if 'min_price_cents' in raw.keys() else 0
    item['max_discount_bp'] = raw['max_discount_bp'] if 'max_discount_bp' in raw.keys() else 0
    price = pricing(c, item)
    fixed = inventory.corrections(c, item['id'])
    entries = [{'id': m['id'], 'at': m['created_at'], 'reason': m['reason'], 'reason_label': inventory.IN_REASONS[m['reason']], 'quantity': m['quantity'], 'cost_cents': fixed.get(m['id'], m['unit_cost_cents']),
                'original_cost_cents': m['unit_cost_cents'], 'corrected': m['id'] in fixed, 'supplier': m['supplier'] or '', 'document': m['document'] if 'document' in m.keys() else '',
                'correctable': m['reference_kind'] != 'compra'} for m in c.execute(
        'SELECT m.*,s.name supplier FROM inventory_movements m LEFT JOIN suppliers s ON s.id=' + ('m.supplier_id' if _has_column(c, 'inventory_movements', 'supplier_id') else 'NULL') + ' WHERE m.item_id=? AND m.direction=1 ORDER BY m.id', (item['id'],))]
    alerts = []
    if not price['price_cents']:
        alerts.append(('price', 'Sin precio de venta: configúralo en «Ventas y precios» antes de vender.'))
    if not item['warranty_store']['qty']:
        alerts.append(('warranty_store', 'Garantía de PC-DOCTOR sin configurar.'))
    if not item['warranty_maker']['qty']:
        alerts.append(('warranty_maker', 'Garantía del fabricante sin configurar.'))
    if any(not e['cost_cents'] for e in entries):
        alerts.append(('cost', 'Hay entradas con costo $0,00: corrígelas en «Kardex e historial» si tuvieron costo.'))
    units_list = []
    if item['tracking'] == 'serie':
        units_list = units(c, item['id'])
        if any(not u['location'] for u in units_list if u['status'] in ('disponible', 'reservada')):
            alerts.append(('location', 'Hay unidades sin ubicación registrada.'))
    elif not item['location']:
        alerts.append(('location', 'Ubicación sin registrar.'))
    today = now.date()
    for u in units_list:
        w = _unit_warranty(c, u, today)
        u['warranty_label'] = (w['store']['state'] if u['sold_at'] else 'sin_venta')
        u['warranty_to'] = u['store_warranty_to']
    res = [r for r in reservations(c) if r['item_id'] == item['id']]
    return {'product': item, 'pricing': price, 'units': units_list, 'reservations': res, 'sales': sales_history(c, item['id']), 'entries': entries,
            'kardex': kardex(c, {'item_id': str(item['id'])})['rows'][::-1], 'alerts': [{'field': f, 'text': t} for f, t in alerts]}


def _has_column(c, table, column):
    return any(r[1] == column for r in c.execute('PRAGMA table_info(' + table + ')'))


def register_delivery(c, unit_ids, delivered_at, user, now):
    """Entrega efectiva de unidades vendidas sin entregar: fija las garantías que cuentan desde la entrega."""
    day = _date_field({'delivered_at': delivered_at}, 'delivered_at', now.date(), True)
    done = 0
    for unit_id in _json_list(unit_ids, 'units'):
        unit = c.execute("SELECT u.*,i.warranty_store_qty,i.warranty_store_unit,i.warranty_store_from,i.warranty_maker_qty,i.warranty_maker_unit,i.warranty_maker_from "
                         "FROM inventory_units u JOIN inventory_items i ON i.id=u.item_id WHERE u.id=? AND u.status IN ('vendida','consumida')", (unit_id,)).fetchone() if _id(unit_id) else None
        if not unit:
            raise InventoryError('Solo se registra la entrega de unidades vendidas o consumidas.', 409, {'units': 'Unidad no válida.'})
        if unit['delivered_at']:
            continue
        sold = date.fromisoformat(unit['sold_at'][:10])
        if day < sold:
            raise InventoryError('La entrega no puede ser anterior a la venta (%s).' % sold.isoformat(), fields={'delivered_at': 'Fecha anterior a la venta.'})
        dates = warranty_dates(unit, sold, day)
        c.execute('UPDATE inventory_units SET delivered_at=?,store_warranty_from=?,store_warranty_to=?,maker_warranty_from=?,maker_warranty_to=?,updated_at=?,updated_by=? WHERE id=?',
                  (day.isoformat(), dates['store_warranty_from'], dates['store_warranty_to'], dates['maker_warranty_from'], dates['maker_warranty_to'], stamp(now), user['id'], unit['id']))
        event(c, now, user, 'unidad_entregada', 'Unidad %s entregada el %s.' % (unit['internal_code'], day.isoformat()), unit['item_id'], unit_id=unit['id'])
        done += 1
    return done


def consume_for_order(c, order_id, item_id, amount, user, now, unit_ids=None, request_key=None):
    """Consumo de un repuesto en una orden técnica: una sola salida por orden y producto."""
    order = c.execute('SELECT code FROM orders WHERE id=?', (order_id,)).fetchone()
    if not order:
        raise InventoryError('Orden no encontrada.', 404)
    return exit_stock(c, {'item_id': str(item_id), 'reason': 'uso_orden', 'order_code': order['code'], 'quantity': str(amount), 'unit_ids': json.dumps(unit_ids) if unit_ids else None,
                          'request_key': request_key or ''}, user, now)


def invoice_exit(c, invoice_id, user, now):
    """Salida por factura: descuenta solo lo que la orden de origen no consumió ya. Cada línea con producto de inventario sale una vez
    (referencia «factura»); lo consumido en la orden (referencia «orden») se omite. Devuelve lo descontado y lo omitido."""
    invoice = c.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,)).fetchone()
    if not invoice:
        raise InventoryError('Factura no encontrada.', 404)
    moved, skipped = [], []
    for line in c.execute('SELECT * FROM invoice_items WHERE invoice_id=? AND catalog_id IS NOT NULL ORDER BY position', (invoice_id,)).fetchall():
        item = c.execute('SELECT * FROM inventory_items WHERE catalog_id=?', (line['catalog_id'],)).fetchone()
        if not item:
            continue
        done = c.execute("SELECT reference_kind FROM inventory_movements WHERE item_id=? AND direction=-1 AND ((reference_kind='orden' AND reference_id=?) OR (reference_kind='factura' AND reference_id=?))",
                         (item['id'], invoice['order_id'] or 0, invoice_id)).fetchone()
        if done:
            skipped.append({'item_id': item['id'], 'description': line['description'], 'reason': 'Ya salió por la ' + ('orden' if done[0] == 'orden' else 'factura')})
            continue
        unit_ids = None
        if item['tracking'] == 'serie':
            reserved_units = [r[0] for r in c.execute("SELECT u.id FROM inventory_units u JOIN inventory_reservations r ON r.id=u.reservation_id WHERE u.item_id=? AND r.status='activa' AND r.order_id=? ORDER BY u.id",
                                                       (item['id'], invoice['order_id'] or 0))]
            free = [r[0] for r in c.execute("SELECT id FROM inventory_units WHERE item_id=? AND status='disponible' ORDER BY id", (item['id'],))]
            unit_ids = (reserved_units + free)[:line['quantity']]
        reservation = c.execute("SELECT id FROM inventory_reservations WHERE item_id=? AND order_id=? AND status='activa'", (item['id'], invoice['order_id'] or 0)).fetchone()
        sold = date.fromisoformat((invoice['issue_date'] or now.date().isoformat())[:10])
        values = {'invoice_id': invoice_id, 'client_id': invoice['client_id'] if 'client_id' in invoice.keys() else None, 'document': 'Factura %s' % invoice_id,
                  'sold_at': sold.isoformat(), 'delivered_at': sold.isoformat(), **warranty_dates(item, sold, sold)}
        movement = inventory.move(c, item['id'], -1, 'venta', str(line['quantity']), '0', user, now, 'factura', invoice_id, 'Factura ' + str(invoice_id), unit_ids=unit_ids,
                                  reservation_id=reservation[0] if reservation else None, unit_values=values)
        moved.append({'item_id': item['id'], 'movement_id': movement, 'quantity': line['quantity']})
    return {'moved': moved, 'skipped': skipped}


def reserve(c, data, user, now):
    """Reserva (orden, presupuesto, proforma o venta): aparta existencias sin descontarlas."""
    item = c.execute('SELECT * FROM inventory_items WHERE id=?', (data.get('item_id'),)).fetchone() if _id(data.get('item_id')) else None
    if not item:
        raise InventoryError('Producto no encontrado.', 404, {'item_id': 'Elige el producto.'})
    reference = _text(data, 'reference', 80)
    order = _order_by_code(c, data.get('order_code')) if _text(data, 'order_code', 40) else None
    reference = reference or (order['code'] if order else '')
    if not reference:
        raise InventoryError('Indica para qué es la reserva (orden, presupuesto o cliente).', fields={'reference': 'Referencia obligatoria.'})
    stock = c.execute('SELECT COALESCE(SUM(direction*quantity),0) FROM inventory_movements WHERE item_id=?', (item['id'],)).fetchone()[0]
    if item['tracking'] == 'serie':
        ids = [int(u) for u in _json_list(data.get('unit_ids'), 'units') if str(u).isdigit()]
        if not ids:
            raise InventoryError('Elige las unidades que se reservan.', fields={'units': 'Sin unidades.'})
        rows = [c.execute("SELECT * FROM inventory_units WHERE id=? AND item_id=? AND status='disponible'", (u, item['id'])).fetchone() for u in set(ids)]
        if not all(rows):
            raise InventoryError('Una unidad elegida ya no está disponible.', 409, {'units': 'Unidad no disponible.'})
        amount = len(rows)
    else:
        amount = quantity(data.get('quantity'))
        rows = []
    if stock - inventory.reserved(c, item['id']) < amount:
        raise InventoryError('No hay existencias libres suficientes para reservar %d.' % amount, 409, {'quantity': 'Supera lo disponible.'})
    client = _id(data.get('client_id')) or (order['client_id'] if order else None)
    if client and not c.execute('SELECT 1 FROM clients WHERE id=?', (client,)).fetchone():
        raise InventoryError('Cliente no encontrado.', 404, {'client_id': 'Cliente no válido.'})
    expires = _text(data, 'expires_at', 10)
    if expires:
        try:
            if date.fromisoformat(expires) < now.date():
                raise ValueError
        except ValueError:
            raise InventoryError('El vencimiento de la reserva debe ser hoy o una fecha futura.', fields={'expires_at': 'Fecha no válida.'})
    reservation = c.execute('INSERT INTO inventory_reservations(item_id,quantity,reference,order_id,status,note,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
                            (item['id'], amount, reference, order['id'] if order else None, 'activa', _text(data, 'note', 300), user['id'], stamp(now))).lastrowid
    if (client or expires) and _has_column(c, 'inventory_reservations', 'expires_at'):
        c.execute('UPDATE inventory_reservations SET client_id=?,expires_at=? WHERE id=?', (client, expires, reservation))
    for unit in rows:
        c.execute("UPDATE inventory_units SET status='reservada',reservation_id=?,updated_at=?,updated_by=? WHERE id=?", (reservation, stamp(now), user['id'], unit['id']))
    event(c, now, user, 'reserva', 'Reserva de %d para %s (no descuenta existencias).' % (amount, reference), item['id'])
    return reservation


def release(c, reservation_id, user, now):
    row = c.execute("SELECT * FROM inventory_reservations WHERE id=? AND status='activa'", (reservation_id,)).fetchone() if _id(reservation_id) else None
    if not row:
        raise InventoryError('La reserva ya no está activa.', 409)
    c.execute("UPDATE inventory_reservations SET status='liberada',closed_by=?,closed_at=? WHERE id=?", (user['id'], stamp(now), row['id']))
    c.execute("UPDATE inventory_units SET status='disponible',reservation_id=NULL,updated_at=?,updated_by=? WHERE reservation_id=? AND status='reservada'", (stamp(now), user['id'], row['id']))
    event(c, now, user, 'reserva_liberada', 'Reserva de %d para %s liberada.' % (row['quantity'], row['reference']), row['item_id'])


def reservations(c, status='activa'):
    where = 'WHERE r.status=?' if status in ('activa', 'liberada', 'consumida') else ''
    client = ",COALESCE(k.name,'') client" if _has_column(c, 'inventory_reservations', 'client_id') else ",'' client"
    join = ' LEFT JOIN clients k ON k.id=r.client_id' if client.startswith(',COALESCE') else ''
    rows = c.execute("SELECT r.*,g.name product,i.tracking,COALESCE(s.name,'') actor,o.code order_code" + client + " FROM inventory_reservations r JOIN inventory_items i ON i.id=r.item_id "
                     'JOIN catalog_items g ON g.id=i.catalog_id LEFT JOIN users s ON s.id=r.created_by LEFT JOIN orders o ON o.id=r.order_id' + join + ' ' + where + ' ORDER BY r.id DESC LIMIT 300',
                     (status,) if where else ()).fetchall()
    today = date.today().isoformat()
    out = []
    for r in rows:
        item = dict(r)
        item['expires_at'] = item.get('expires_at') or ''
        item['expired'] = bool(item['expires_at']) and item['expires_at'] < today and item['status'] == 'activa'
        item['units'] = [dict(u) for u in c.execute('SELECT id,internal_code,serial FROM inventory_units WHERE reservation_id=?', (r['id'],))]
        out.append(item)
    return out


def transfer(c, data, user, now):
    """Traslado entre ubicaciones: no cambia las existencias y queda en el Kardex."""
    item = c.execute('SELECT * FROM inventory_items WHERE id=?', (data.get('item_id'),)).fetchone() if _id(data.get('item_id')) else None
    if not item:
        raise InventoryError('Producto no encontrado.', 404, {'item_id': 'Elige el producto.'})
    target = _text(data, 'to_location', 80)
    if not target:
        raise InventoryError('Indica la nueva ubicación.', fields={'to_location': 'Ubicación obligatoria.'})
    note = _text(data, 'note', 300)
    if item['tracking'] == 'serie':
        ids = [int(u) for u in _json_list(data.get('unit_ids'), 'units') if str(u).isdigit()]
        units_ = [c.execute("SELECT * FROM inventory_units WHERE id=? AND item_id=? AND status IN ('disponible','reservada')", (u, item['id'])).fetchone() for u in set(ids)]
        if not ids or not all(units_):
            raise InventoryError('Elige unidades en existencia.', fields={'units': 'Unidad no válida.'})
        for unit in units_:
            c.execute('INSERT INTO inventory_transfers(item_id,unit_id,quantity,from_location,to_location,note,created_by,created_at) VALUES (?,?,1,?,?,?,?,?)',
                      (item['id'], unit['id'], unit['location'], target, note, user['id'], stamp(now)))
            c.execute('UPDATE inventory_units SET location=?,updated_at=?,updated_by=? WHERE id=?', (target, stamp(now), user['id'], unit['id']))
        moved = len(units_)
    else:
        stock = c.execute('SELECT COALESCE(SUM(direction*quantity),0) FROM inventory_movements WHERE item_id=?', (item['id'],)).fetchone()[0]
        if stock <= 0:
            raise InventoryError('No hay existencias para trasladar.', 409)
        c.execute('INSERT INTO inventory_transfers(item_id,quantity,from_location,to_location,note,created_by,created_at) VALUES (?,?,?,?,?,?,?)',
                  (item['id'], stock, item['location'], target, note, user['id'], stamp(now)))
        c.execute('UPDATE inventory_items SET location=?,updated_at=?,updated_by=? WHERE id=?', (target, stamp(now), user['id'], item['id']))
        moved = stock
    event(c, now, user, 'traslado', 'Traslado de %d a %s.' % (moved, target), item['id'])
    return moved


# ---- Kardex --------------------------------------------------------------------------------------------------------------

KARDEX_TYPES = {'entrada': 'Entradas', 'salida': 'Salidas', 'k:inicial': 'Inventario inicial', 'k:ajuste': 'Ajustes y bajas', 'k:devolucion': 'Devoluciones', 'reserva': 'Reservas y liberaciones',
                'traslado': 'Traslados', 'correccion': 'Correcciones de costo', 'precio': 'Cambios de precio', **{'m:' + k: v for k, v in inventory.IN_REASONS.items()},
                **{'m:' + k: v for k, v in inventory.OUT_REASONS.items()}}


def _reference(c, m):
    kind, ref = m['reference_kind'], m['reference_id']
    if kind == 'compra':
        row = c.execute('SELECT document_number FROM purchases WHERE id=?', (ref,)).fetchone()
        return 'Compra ' + (row[0] if row else str(ref))
    if kind == 'orden':
        row = c.execute('SELECT code FROM orders WHERE id=?', (ref,)).fetchone()
        return 'Orden ' + (row[0] if row else str(ref))
    if kind == 'factura':
        row = c.execute('SELECT establishment,emission_point,sequential FROM invoices WHERE id=?', (ref,)).fetchone()
        return 'Factura ' + ('%s-%s-%09d' % (row[0], row[1], row[2]) if row and row[2] else str(ref))
    return ''


MOVE_KINDS = {'inicial': ('inicial', 'Inventario inicial'), 'compra': ('entrada', 'Entrada'), 'devolucion_cliente': ('devolucion', 'Devolución del cliente'),
              'ajuste_entrada': ('ajuste', 'Ajuste (entrada)'), 'venta': ('salida', 'Venta'), 'uso_orden': ('salida', 'Consumo en orden'), 'devolucion_proveedor': ('devolucion', 'Devolución al proveedor'),
              'ajuste_salida': ('ajuste', 'Ajuste (salida)'), 'baja': ('ajuste', 'Baja'), 'anulacion_compra': ('salida', 'Anulación de compra')}


def _period_before(start, end):
    """Ventana anterior de la misma duración (para la variación de los indicadores)."""
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    span = (b - a).days + 1
    return (a - timedelta(days=span)).isoformat(), (a - timedelta(days=1)).isoformat()


def kardex(c, filters=None):
    """Kardex valorizado (costo promedio ponderado móvil) con reservas, traslados y correcciones de costo auditadas. El saldo se calcula sobre
    todo el historial del producto y después se aplican los filtros: el saldo mostrado siempre es el real. Las salidas conservan el costo
    aplicado en su momento; una corrección de costo no borra el movimiento original: se muestra como fila propia con su motivo."""
    f = filters or {}
    cats = _category_ids(c, f.get('category_id'))
    items = c.execute(PRODUCT_SQL + ' ORDER BY g.name COLLATE NOCASE').fetchall()
    serial = inventory.serial_key(f.get('serial') or '')
    kind = str(f.get('type') or '')
    user_id = _id(f.get('user_id'))
    doc = str(f.get('document') or '').strip().lower()
    start, end = str(f.get('from') or ''), str(f.get('to') or '')
    names = {r[0]: r[1] for r in c.execute('SELECT id,name FROM users')}
    has_extra = _has_column(c, 'inventory_movements', 'supplier_id')
    has_sale = _has_column(c, 'inventory_movements', 'client_id')
    rows, stock_now, value_now, opening, chosen = [], 0, 0, 0, []
    for item in items:
        if cats and item['category_id'] not in cats or _id(f.get('brand_id')) and item['brand_id'] != int(f['brand_id']) or _id(f.get('item_id')) and item['id'] != int(f['item_id']):
            continue
        chosen.append(item['id'])
        base = {'item_id': item['id'], 'product': item['name'], 'sku': item['sku'], 'code': item['catalog_code'] or item['sku'] or '', 'brand': item['brand'] or '', 'tracking': item['tracking'], 'model': item['model'],
                'category': (item['parent_name'] + ' › ' + item['category_name']) if item['parent_name'] else (item['category_name'] or 'Sin categoría')}
        fixed = inventory.corrections(c, item['id'])
        timeline, moved_at = [], {}
        history = inventory.valuation(c, item['id'])
        for m, balance, avg, value, applied in history:
            units_ = [dict(r) for r in c.execute('SELECT u.id,u.internal_code,u.serial,u.location FROM inventory_movement_units x JOIN inventory_units u ON u.id=x.unit_id WHERE x.movement_id=? ORDER BY u.id', (m['id'],))]
            moved_at[m['id']] = m['created_at']
            party = ''
            if has_extra and m['supplier_id']:
                party = (c.execute('SELECT name FROM suppliers WHERE id=?', (m['supplier_id'],)).fetchone() or [''])[0]
            if has_sale and m['client_id']:
                party = (c.execute('SELECT name FROM clients WHERE id=?', (m['client_id'],)).fetchone() or [''])[0]
            if not party and m['direction'] == -1 and units_:
                party = (c.execute('SELECT k.name FROM inventory_units u JOIN clients k ON k.id=u.client_id WHERE u.id=?', (units_[0]['id'],)).fetchone() or [''])[0]
            mk, mlabel = MOVE_KINDS[m['reason']]
            pending = m['direction'] == 1 and not applied and m['reason'] in ('inicial', 'compra', 'ajuste_entrada')
            document = _reference(c, m) or ((m['document'] if has_extra else '') or '')
            timeline.append((m['created_at'], 0, 2 * m['id'], dict(base, at=m['created_at'], id='m%d' % m['id'], movement_id=m['id'], type='entrada' if m['direction'] == 1 else 'salida', kind=mk, reason=m['reason'],
                             label=mlabel, entry=m['quantity'] if m['direction'] == 1 else 0, exit=m['quantity'] if m['direction'] == -1 else 0, unit_cost_cents=applied,
                             original_cost_cents=m['unit_cost_cents'], corrected=m['id'] in fixed, cost_pending=pending, average_cents=avg, balance=balance, balance_cents=value,
                             line_cents=m['quantity'] * applied, document=document, party=party, location=', '.join(sorted({u['location'] for u in units_ if u['location']})) or item['location'],
                             sale_price_cents=m['sale_price_cents'] if has_sale else None, tax_rate_bp=m['tax_rate_bp'] if has_extra else 0,
                             note=m['note'], user_id=m['created_by'], actor=names.get(m['created_by'], 'Sistema'), units=units_)))
        try:
            fixes = c.execute('SELECT * FROM inventory_cost_corrections WHERE item_id=? ORDER BY id', (item['id'],)).fetchall()
        except Exception:
            fixes = []
        for x in fixes:
            timeline.append((x['created_at'], 3, x['id'], dict(base, at=x['created_at'], id='c%d' % x['id'], movement_id=x['movement_id'], type='correccion', kind='correccion', reason='correccion',
                             label='Corrección de costo · sin movimiento de existencias', entry=0, exit=0, document=x['document'], party='', location='', note='Entrada #%d: %s → %s. %s' % (x['movement_id'], usd(x['old_cost_cents']), usd(x['new_cost_cents']), x['reason']),
                             old_cost_cents=x['old_cost_cents'], new_cost_cents=x['new_cost_cents'], user_id=x['created_by'], actor=names.get(x['created_by'], 'Sistema'), units=[])))
        for r in c.execute('SELECT * FROM inventory_reservations WHERE item_id=?', (item['id'],)).fetchall():
            units_ = [dict(u) for u in c.execute('SELECT id,internal_code,serial,location FROM inventory_units WHERE reservation_id=? OR id IN (SELECT unit_id FROM inventory_movement_units WHERE movement_id=?)',
                                                  (r['id'], r['movement_id'] or 0))]
            client = ''
            if 'client_id' in r.keys() and r['client_id']:
                client = (c.execute('SELECT name FROM clients WHERE id=?', (r['client_id'],)).fetchone() or [''])[0]
            # Una reserva consumida va siempre antes de la salida que la consumió (aunque ocurran en el mismo segundo).
            order_key = (r['created_at'], 0, 2 * r['movement_id'] - 1) if r['movement_id'] and r['created_at'] >= moved_at.get(r['movement_id'], '') else (r['created_at'], 1, r['id'])
            timeline.append((*order_key, dict(base, at=r['created_at'], id='r%d' % r['id'], type='reserva', kind='reserva', reason='reserva', label='Reserva (no descuenta)', entry=0, exit=0, reserved=r['quantity'],
                             document=r['reference'], party=client, location='', note=r['note'], user_id=r['created_by'], actor=names.get(r['created_by'], 'Sistema'), units=units_)))
            if r['status'] == 'liberada':
                timeline.append((r['closed_at'], 1, r['id'], dict(base, at=r['closed_at'], id='l%d' % r['id'], type='reserva', kind='reserva', reason='liberacion', label='Liberación de reserva', entry=0, exit=0,
                                 reserved=-r['quantity'], document=r['reference'], party=client, location='', note='', user_id=r['closed_by'], actor=names.get(r['closed_by'], 'Sistema'), units=units_)))
        # Cambios del precio de venta: no mueven existencias ni costos; se muestran aparte para no confundirlos con entradas o salidas.
        try:
            prices = c.execute('SELECT * FROM catalog_price_history WHERE item_id=? ORDER BY id', (item['catalog_id'],)).fetchall()
        except Exception:
            prices = []
        for x in prices:
            timeline.append((x['created_at'], 4, x['id'], dict(base, at=x['created_at'], id='p%d' % x['id'], type='precio', kind='precio', reason='precio', label='Cambio de precio de venta · sin movimiento de existencias',
                             entry=0, exit=0, document='', party='', location='', note='Precio de venta: %s → %s.' % (usd(x['old_cents']), usd(x['new_cents'])),
                             old_price_cents=x['old_cents'], new_price_cents=x['new_cents'], user_id=x['user_id'], actor=names.get(x['user_id'], 'Sistema'), units=[])))
        for t in c.execute('SELECT t.*,u.internal_code,u.serial FROM inventory_transfers t LEFT JOIN inventory_units u ON u.id=t.unit_id WHERE t.item_id=?', (item['id'],)).fetchall():
            timeline.append((t['created_at'], 2, t['id'], dict(base, at=t['created_at'], id='t%d' % t['id'], type='traslado', kind='traslado', reason='traslado',
                             label='Traslado: %s → %s' % (t['from_location'] or 'sin ubicación', t['to_location']), entry=0, exit=0, moved=t['quantity'], document='', party='', location=t['to_location'],
                             note=t['note'], user_id=t['created_by'], actor=names.get(t['created_by'], 'Sistema'), units=[{'internal_code': t['internal_code'], 'serial': t['serial']}] if t['internal_code'] else [])))
        timeline.sort(key=lambda e: (e[0], e[1], e[2]))
        last = {'balance': 0, 'average_cents': 0, 'balance_cents': 0}
        for _, _, _, row in timeline:
            if row['type'] in ('entrada', 'salida'):
                last = {k: row[k] for k in last}
                row['balance_before'] = row['balance'] - row['entry'] + row['exit']
            else:
                row.update(unit_cost_cents=0, line_cents=0, **last)
                row['balance_before'] = row['balance']
            row['stock_effect'] = row['type'] in ('entrada', 'salida')
            if start and row['at'][:10] < start:
                row['_before'] = True
            rows.append(row)
        if history:
            stock_now += history[-1][1]
            value_now += history[-1][3]
            if start:
                before = [h for h in history if h[0]['created_at'][:10] < start]
                opening += before[-1][1] if before else 0

    def keep(row, a, b):
        day = row['at'][:10]
        if a and day < a or b and day > b:
            return False
        if kind in ('entrada', 'salida', 'reserva', 'traslado', 'correccion', 'precio') and row['type'] != kind or kind.startswith('k:') and row.get('kind') != kind[2:] or kind.startswith('m:') and row['reason'] != kind[2:]:
            return False
        if user_id and row['user_id'] != user_id:
            return False
        if doc and doc not in (str(row.get('document') or '') + ' ' + str(row.get('note') or '')).lower():
            return False
        if serial and not any(serial in inventory.serial_key(u['serial'] or '') or serial in (u['internal_code'] or '') for u in row['units']):
            return False
        return True

    def summary(subset):
        return {'rows': len(subset), 'entries': sum(r['entry'] for r in subset), 'exits': sum(r['exit'] for r in subset),
                'entry_cents': sum(r.get('line_cents', 0) for r in subset if r['type'] == 'entrada'), 'exit_cents': sum(r.get('line_cents', 0) for r in subset if r['type'] == 'salida'),
                'adjustments': sum(r['entry'] + r['exit'] for r in subset if r.get('kind') == 'ajuste'), 'cost_pending': sum(1 for r in subset if r.get('cost_pending') and not r.get('corrected'))}
    out = sorted((r for r in rows if keep(r, start, end)), key=lambda r: r['at'])  # estable: conserva el orden real dentro del mismo segundo
    totals = summary(out)
    totals.update(stock_cents=value_now, stock_units=stock_now, products=len(chosen))
    if start:
        totals['opening'] = opening
        totals['closing'] = opening + sum(r['entry'] - r['exit'] for r in rows if keep(r, start, end or '9999-12-31') and r['type'] in ('entrada', 'salida'))
    previous = None
    if start and end:
        a, b = _period_before(start, end)
        previous = summary([r for r in rows if keep(r, a, b)])
    return {'rows': out[-2000:], 'totals': totals, 'previous': previous, 'truncated': len(out) > 2000}


KARDEX_COLUMNS = ['Fecha', 'Producto', 'SKU', 'Categoría', 'Marca', 'Serie / código', 'Movimiento', 'Entrada', 'Salida', 'Saldo anterior', 'Saldo', 'Costo unitario', 'Valor del movimiento', 'Costo promedio',
                  'Valor del saldo', 'Documento', 'Proveedor / cliente', 'Responsable', 'Observación']


def _units_text(units):
    return ', '.join((u['serial'] + ' (' + u['internal_code'] + ')') if u.get('serial') else u.get('internal_code') or '' for u in units)


def _kardex_cells(r):
    money = r['type'] in ('entrada', 'salida')
    return [r['at'].replace('T', ' ')[:16], r['product'], r['sku'], r['category'], r['brand'], _units_text(r['units']), r['label'] + (' · costo pendiente' if r.get('cost_pending') and not r.get('corrected') else ''),
            r['entry'] or '', r['exit'] or '', r.get('balance_before', r['balance']), r['balance'], r['unit_cost_cents'] / 100 if money else '', r.get('line_cents', 0) / 100 if money else '', r['average_cents'] / 100,
            r['balance_cents'] / 100, r.get('document') or '', r.get('party') or '', r['actor'], r.get('note') or '']


def _safe(value):
    text = str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@') else text  # evita fórmulas al abrir en Excel


def kardex_csv(rows):
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';')
    writer.writerow(KARDEX_COLUMNS)
    for r in rows:
        writer.writerow([_safe(v) if isinstance(v, str) else ('%.2f' % v).replace('.', ',') if isinstance(v, float) else v for v in _kardex_cells(r)])
    return '﻿' + out.getvalue()


def xlsx(title, columns, rows):
    """Libro de Excel (.xlsx) mínimo con una hoja: textos como cadenas en línea y números como números. Sin dependencias."""
    def ref(col, row):
        name = ''
        while col:
            col, rest = divmod(col - 1, 26)
            name = chr(65 + rest) + name
        return '%s%d' % (name, row)
    lines = []
    for r, values in enumerate([columns] + rows, 1):
        cells = []
        for col, value in enumerate(values, 1):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append('<c r="%s"%s><v>%s</v></c>' % (ref(col, r), ' s="2"' if isinstance(value, float) else '', ('%.2f' % value) if isinstance(value, float) else value))
            elif value not in ('', None):
                cells.append('<c r="%s" t="inlineStr"%s><is><t xml:space="preserve">%s</t></is></c>' % (ref(col, r), ' s="1"' if r == 1 else '', escape(_safe(value))))
        lines.append('<row r="%d">%s</row>' % (r, ''.join(cells)))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
             '<sheetData>' + ''.join(lines) + '</sheetData></worksheet>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders>'
              '<cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="3"><xf/><xf fontId="1" applyFont="1"/><xf numFmtId="164" applyNumberFormat="1"/></cellXfs></styleSheet>')
    files = {'[Content_Types].xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                                    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                                    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                                    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
             '_rels/.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
             'xl/workbook.xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>' % escape(title[:31]),
             'xl/_rels/workbook.xml.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                           '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                                           '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
             'xl/worksheets/sheet1.xml': sheet, 'xl/styles.xml': styles}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as book:
        for name, content in files.items():
            book.writestr(name, content)
    return buffer.getvalue()


def kardex_xlsx(rows):
    return xlsx('Kardex', KARDEX_COLUMNS, [_kardex_cells(r) for r in rows])


REPORTS = {'general': 'Kardex general', 'producto': 'Kardex por producto', 'categoria': 'Kardex por categoría', 'periodo': 'Entradas y salidas por período',
           'valorizado': 'Existencias valorizadas', 'sin_costo': 'Productos sin costo registrado', 'ajustes': 'Ajustes y devoluciones', 'responsable': 'Movimientos por responsable'}


def filters_text(c, f):
    parts = []
    if f.get('from') or f.get('to'):
        parts.append('Período: %s a %s' % (f.get('from') or 'inicio', f.get('to') or 'hoy'))
    for key, label, sql in (('category_id', 'Categoría', None), ('brand_id', 'Marca', 'SELECT name FROM inventory_brands WHERE id=?'),
                            ('item_id', 'Producto', 'SELECT g.name FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE i.id=?'), ('user_id', 'Responsable', 'SELECT name FROM users WHERE id=?')):
        if _id(f.get(key)):
            value = category_path(c, f[key]) if key == 'category_id' else (c.execute(sql, (int(f[key]),)).fetchone() or ['—'])[0]
            parts.append('%s: %s' % (label, value))
    for key, label in (('serial', 'Serie o código'), ('document', 'Documento')):
        if f.get(key):
            parts.append('%s: %s' % (label, f[key]))
    if f.get('type'):
        parts.append('Movimiento: %s' % KARDEX_TYPES.get(f['type'], f['type']))
    return ' · '.join(parts) or 'Sin filtros'


def report(c, kind, f):
    """Datos de un reporte: (título, columnas, filas con números utilizables, anchos para el PDF, línea de totales)."""
    if kind not in REPORTS:
        raise InventoryError('Reporte no válido.')
    title = REPORTS[kind]
    if kind in ('general', 'producto', 'categoria', 'ajustes'):
        if kind == 'producto' and not _id(f.get('item_id')):
            raise InventoryError('Elige el producto del reporte.', fields={'item_id': 'Producto obligatorio.'})
        if kind == 'categoria' and not _id(f.get('category_id')):
            raise InventoryError('Elige la categoría del reporte.', fields={'category_id': 'Categoría obligatoria.'})
        data = kardex(c, f)
        rows = data['rows'] if kind != 'ajustes' else [r for r in data['rows'] if r.get('kind') in ('ajuste', 'devolucion') or r['type'] == 'correccion']
        t = data['totals']
        totals = 'Movimientos: %d · Unidades ingresadas: %d · Unidades retiradas: %d · Valor de entradas: %s · Valor de salidas: %s · Existencias: %d · Valor actual: %s' % (
            len(rows), sum(r['entry'] for r in rows), sum(r['exit'] for r in rows), usd(sum(r.get('line_cents', 0) for r in rows if r['type'] == 'entrada')),
            usd(sum(r.get('line_cents', 0) for r in rows if r['type'] == 'salida')), t['stock_units'], usd(t['stock_cents']))
        if t.get('opening') is not None and f.get('from'):
            totals += ' · Saldo inicial: %d · Saldo final: %d' % (t['opening'], t['closing'])
        return title, KARDEX_COLUMNS, [_kardex_cells(r) for r in rows], [58, 104, 50, 0, 0, 92, 72, 30, 30, 34, 30, 46, 50, 0, 50, 70, 60, 54, 0], totals
    if kind == 'periodo':
        data = kardex(c, dict(f, type=''))
        per = {}
        for r in data['rows']:
            row = per.setdefault(r['item_id'], {'product': r['product'], 'sku': r['sku'], 'category': r['category'], 'in': 0, 'out': 0, 'in_c': 0, 'out_c': 0, 'last': r['balance'], 'value': r['balance_cents']})
            row['in'] += r['entry']
            row['out'] += r['exit']
            row['in_c'] += r.get('line_cents', 0) if r['type'] == 'entrada' else 0
            row['out_c'] += r.get('line_cents', 0) if r['type'] == 'salida' else 0
            row['last'], row['value'] = r['balance'], r['balance_cents']
        rows = [[v['product'], v['sku'], v['category'], v['in'], v['in_c'] / 100, v['out'], v['out_c'] / 100, v['last'], v['value'] / 100] for v in per.values()]
        return (title, ['Producto', 'SKU', 'Categoría', 'Unidades ingresadas', 'Valor ingresado', 'Unidades retiradas', 'Valor retirado', 'Saldo al cierre', 'Valor al cierre'], rows,
                [170, 70, 130, 60, 60, 60, 60, 50, 60], 'Productos: %d · Ingresadas: %d · Retiradas: %d' % (len(rows), sum(r[3] for r in rows), sum(r[5] for r in rows)))
    if kind == 'valorizado':
        items = [p for p in products(c, '', f.get('category_id', ''), f.get('brand_id', '')) if p['active']]
        rows = [[p['name'], p['sku'], p['category'], p['brand'], p['stock'], p['reserved'], p['average_cost_cents'] / 100, p['value_cents'] / 100, p['price_cents'] / 100, p['stock_state_label']] for p in items]
        return (title, ['Producto', 'SKU', 'Categoría', 'Marca', 'Existencias', 'Reservadas', 'Costo promedio', 'Valor', 'Precio de venta', 'Estado'], rows,
                [150, 66, 120, 66, 46, 46, 56, 56, 56, 50], 'Productos: %d · Unidades: %d · Valor total: %s' % (len(rows), sum(r[4] for r in rows), usd(round(sum(r[7] for r in rows) * 100))))
    if kind == 'sin_costo':
        data = kardex(c, dict(f, type=''))
        rows = [[r['at'][:16].replace('T', ' '), r['product'], r['sku'], r['label'], r['entry'], _units_text(r['units']), r['actor']] for r in data['rows'] if r.get('cost_pending') and not r.get('corrected')]
        return (title, ['Fecha', 'Producto', 'SKU', 'Movimiento', 'Unidades', 'Serie / código', 'Responsable'], rows, [70, 190, 80, 90, 50, 180, 90],
                'Entradas sin costo: %d · Unidades: %d. Indica el costo real con «Corregir costo» (queda auditado).' % (len(rows), sum(r[4] for r in rows)))
    data = kardex(c, f)
    per = {}
    for r in data['rows']:
        row = per.setdefault(r['actor'], [r['actor'], 0, 0, 0, 0, 0])
        row[1] += 1
        row[2] += r['entry']
        row[3] += r['exit']
        row[4] += r.get('line_cents', 0) / 100 if r['type'] == 'entrada' else 0
        row[5] += r.get('line_cents', 0) / 100 if r['type'] == 'salida' else 0
    rows = sorted(per.values(), key=lambda r: -r[1])
    return title, ['Responsable', 'Movimientos', 'Unidades ingresadas', 'Unidades retiradas', 'Valor ingresado', 'Valor retirado'], rows, [200, 90, 110, 110, 110, 110], 'Responsables: %d' % len(rows)


def report_csv(columns, rows):
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';')
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_safe(v) if isinstance(v, str) else ('%.2f' % v).replace('.', ',') if isinstance(v, float) else v for v in row])
    return '\ufeff' + out.getvalue()


def report_pdf(title, filters, columns, rows, widths, totals, now):
    """PDF A4 horizontal: logo original, título, fecha de generación, filtros, tabla paginada con encabezado repetido, totales y «Página n de N»."""
    from document_canvas import Canvas, BLUE, GRAY
    w, h = 842, 595
    keep = [i for i, width in enumerate(widths) if width]
    cols, ws = [columns[i] for i in keep], [widths[i] for i in keep]
    scale = (w - 48) / sum(ws)
    ws = [x * scale for x in ws]
    measure = Canvas(w, h, 'medida')
    money_cols = {i for i, name in enumerate(cols) if any(k in name for k in ('Costo', 'Valor', 'Precio'))}
    lines = []
    for row in rows:
        cells = []
        for n, i in enumerate(keep):
            value = row[i]
            text = usd(int(round(value * 100))) if n in money_cols and isinstance(value, (int, float)) and value != '' else str(value)
            cells.append(measure.wrap(text, ws[n] - 4, 7)[:3])
        lines.append((cells, 10 * max(len(x) for x in cells) + 4))
    pages, y, plan = 1, 96, []
    for cells, height in lines:
        if y + height > h - 56:
            pages, y = pages + 1, 96
        plan.append((pages, y, cells))
        y += height
    pdf = Canvas(w, h, title)
    for number in range(1, pages + 1):
        pdf.page()
        pdf.logo(24, 16, 70)
        pdf.text(title, 104, 18, 14, True, BLUE)
        pdf.text('Generado el %s · %s' % (now.strftime('%d/%m/%Y %H:%M'), filters)[:180], 104, 38, 8, False, GRAY)
        x = 24
        for name, width in zip(cols, ws):
            pdf.text(measure.wrap(name, width - 4, 7)[0], x, 70, 7, True, BLUE)
            x += width
        pdf.line(24, 84, w - 48)
        for page, y0, cells in plan:
            if page != number:
                continue
            x = 24
            for lines_, width in zip(cells, ws):
                for k, piece in enumerate(lines_):
                    pdf.text(piece, x, y0 + k * 10, 7)
                x += width
        if number == pages:
            last = max([y0 + 10 for page, y0, _ in plan if page == number] or [96])
            pdf.line(24, last + 6, w - 48)
            for k, piece in enumerate(measure.wrap(totals, w - 48, 8)[:3]):
                pdf.text(piece, 24, last + 12 + k * 11, 8, True)
        pdf.line(24, h - 34, w - 48)
        pdf.text('PC-DOCTOR S.A. · Centro de Inventario · ' + title, 24, h - 28, 7, False, GRAY)
        label = 'Página %d de %d' % (number, pages)
        pdf.text(label, w - 24 - len(label) * 3.6, h - 28, 7, False, GRAY)
    return pdf.finish()


# ---- Garantías ---------------------------------------------------------------------------------------------------------

def _coverage(start, end, today):
    if not end:
        return {'from': start or '', 'to': '', 'days_left': None, 'total_days': None, 'remaining': None, 'state': 'sin_fecha'}
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    total = max(1, (last - first).days)
    left = (last - today).days
    remaining = max(0.0, min(1.0, left / total))
    state = 'vencida' if left < 0 else 'por_vencer' if left <= SOON_DAYS else 'vigente'
    tone = 'gris' if left < 0 else 'verde' if remaining > .5 else 'amarillo' if remaining > .2 else 'rojo'
    return {'from': start, 'to': end, 'days_left': left, 'total_days': total, 'remaining': round(remaining, 4), 'state': state, 'tone': tone}


def _unit_warranty(c, unit, today):
    item = c.execute('SELECT * FROM inventory_items WHERE id=?', (unit['item_id'],)).fetchone()
    out = {}
    for key, column in (('store', 'warranty_store'), ('maker', 'warranty_maker')):
        info = _coverage(unit[key + '_warranty_from'], unit[key + '_warranty_to'], today)
        info['policy'] = period_label(item[column + '_qty'], item[column + '_unit']) + ' · ' + STARTS[item[column + '_from']].lower()
        if not item[column + '_qty']:
            info['state'] = 'sin_garantia'
        elif info['state'] == 'sin_fecha':
            info['state'] = 'pendiente_entrega' if unit['sold_at'] and not unit['delivered_at'] else 'sin_fecha'
        out[key] = info
    return out


WARRANTY_STATES = {'vigente': 'Vigente', 'por_vencer': 'Próxima a vencer', 'vencida': 'Vencida', 'pendiente_entrega': 'Comienza con la entrega', 'sin_garantia': 'Sin garantía', 'sin_fecha': 'Sin fecha'}


def warranties(c, today, state='', q=''):
    """Panel de garantías de las unidades vendidas o consumidas: PC-DOCTOR y fabricante por separado, con días restantes."""
    rows = c.execute(UNIT_SQL + " WHERE u.status IN ('vendida','consumida') AND u.sold_at!='' ORDER BY u.sold_at DESC,u.id DESC LIMIT 1000").fetchall()
    out = []
    words = [w for w in str(q or '').lower().split() if w]
    for r in rows:
        if words and not all(w in ' '.join(str(v or '') for v in (r['product'], r['serial'], r['internal_code'], r['client'], r['document'], r['order_code'], r['brand'])).lower() for w in words):
            continue
        info = _unit_warranty(c, r, today)
        invoice = ''
        if r['invoice_id']:
            row = c.execute('SELECT establishment,emission_point,sequential FROM invoices WHERE id=?', (r['invoice_id'],)).fetchone()
            invoice = '%s-%s-%09d' % (row[0], row[1], row[2]) if row and row[2] else 'Factura %d' % r['invoice_id']
        item = {'unit_id': r['id'], 'product': r['product'], 'brand': r['brand'] or '', 'internal_code': r['internal_code'], 'serial': r['serial'], 'status': r['status'],
                'client': r['client'] or '', 'order_code': r['order_code'] or '', 'invoice': invoice, 'document': r['document'], 'sold_at': r['sold_at'], 'delivered_at': r['delivered_at'],
                'store': info['store'], 'maker': info['maker']}
        if state and item['store']['state'] != state and item['maker']['state'] != state:
            continue
        out.append(item)
    counts = {}
    for item in out:
        counts[item['store']['state']] = counts.get(item['store']['state'], 0) + 1
    return {'rows': out, 'counts': counts, 'states': WARRANTY_STATES}


# ---- Etiquetas -----------------------------------------------------------------------------------------------------------

def labels_pdf(c, unit_ids=None, item_id=None, copies=1, size='60x40'):
    """Etiquetas con el logo original, nombre del producto, código interno en Code 128 y, si existe, la serie original.
    Productos a granel: el código de barras lleva el SKU o el código del catálogo."""
    from code128 import widths as bar_widths
    from document_canvas import Canvas, BLUE, GRAY
    width_mm, height_mm = LABEL_SIZES.get(size, LABEL_SIZES['60x40'])
    scale = 72 / 25.4
    w, h = width_mm * scale, height_mm * scale
    entries = []
    if unit_ids:
        for unit_id in _json_list(unit_ids, 'units')[:500]:
            row = c.execute('SELECT u.internal_code,u.serial,g.name FROM inventory_units u JOIN inventory_items i ON i.id=u.item_id JOIN catalog_items g ON g.id=i.catalog_id WHERE u.id=?',
                            (unit_id,)).fetchone() if _id(unit_id) else None
            if row:
                entries.append((row['name'], row['internal_code'], row['serial']))
    elif _id(item_id):
        row = c.execute('SELECT i.sku,g.code,g.name FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE i.id=?', (int(item_id),)).fetchone()
        if row:
            code = row['sku'] or row['code'] or ''
            entries = [(row['name'], code, '')] * max(1, min(int(copies) if str(copies).isdigit() else 1, 200))
    if not entries or not all(e[1] for e in entries):
        raise InventoryError('No hay etiquetas para imprimir (el producto a granel necesita SKU o código de catálogo).', 409)
    pdf = Canvas(w, h, 'Etiquetas de inventario')
    m = 6
    for name, code, serial in entries:
        pdf.page()
        logo_h = pdf.logo(m, m, min(46, w * .32))
        lines = pdf.wrap(name, w - 2 * m - min(46, w * .32) - 6, 7)[:2]
        for n, line in enumerate(lines):
            pdf.text(line, m + min(46, w * .32) + 6, m + n * 9, 7, True, BLUE)
        top = max(m + logo_h, m + 9 * len(lines)) + 3
        bars = bar_widths(code)
        unit = min(1.2, (w - 2 * m) / (sum(bars) + 20))
        bar_h = max(14, h - top - 30)
        left = (w - (sum(bars) + 20) * unit) / 2 + 10 * unit
        pdf.stream.set_color_rgb(0, 0, 0)
        for i, width in enumerate(bars):
            if i % 2 == 0:
                pdf.stream.rectangle(left, h - top - bar_h, width * unit, bar_h)
            left += width * unit
        pdf.stream.fill()
        y = top + bar_h + 2
        pdf.text(code, max(m, (w - len(code) * 4.6) / 2), y, 8, True)
        if serial:
            text = 'S/N: ' + serial
            pdf.text(text, max(m, (w - len(text) * 3.9) / 2), y + 11, 7, False, GRAY)
    return pdf.finish()


# ---- Importación (Excel o CSV) --------------------------------------------------------------------------------------------

IMPORT_FIELDS = {'categoria': ('categoria', 'categoría', 'category'), 'subcategoria': ('subcategoria', 'subcategoría', 'subcategory'), 'marca': ('marca', 'brand'),
                 'modelo': ('modelo', 'model'), 'producto': ('producto', 'nombre', 'nombre del producto', 'name', 'product'), 'sku': ('sku',),
                 'control': ('control', 'tipo', 'tipo de control'), 'serie': ('serie', 'serial', 'numero de serie', 'número de serie', 's/n'),
                 'cantidad': ('cantidad', 'qty', 'quantity'), 'costo': ('costo', 'costo unitario', 'cost'), 'precio': ('precio', 'precio de venta', 'pvp', 'price'),
                 'ubicacion': ('ubicacion', 'ubicación', 'location'), 'minimo': ('minimo', 'mínimo', 'stock minimo', 'stock mínimo'),
                 'garantia_pcdoctor': ('garantia pcdoctor', 'garantía pc-doctor', 'garantia pc-doctor', 'garantía pcdoctor', 'garantia_pcdoctor'),
                 'garantia_fabricante': ('garantia fabricante', 'garantía del fabricante', 'garantia del fabricante', 'garantia_fabricante')}
TEMPLATE = ['categoria', 'subcategoria', 'marca', 'modelo', 'producto', 'sku', 'control', 'serie', 'cantidad', 'costo', 'precio', 'ubicacion', 'minimo', 'garantia_pcdoctor', 'garantia_fabricante']


def import_template():
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';')
    writer.writerow(TEMPLATE)
    writer.writerow(['Almacenamiento', 'SSD SATA 2.5"', 'Kingston', 'A400 240 GB', 'SSD Kingston A400 240 GB', 'SA400S37/240G', 'serie', '50026B7682AB1234', '1', '18,50', '32,00', 'Bodega A', '2', '1 año', '3 años'])
    writer.writerow(['Consumibles de servicio técnico', 'Pasta térmica', 'Arctic', 'MX-4 4 g', 'Pasta térmica Arctic MX-4 4 g', '', 'granel', '', '10', '4,20', '9,00', 'Taller', '3', '', ''])
    return '﻿' + out.getvalue()


def _norm(text):
    import unicodedata
    return ''.join(ch for ch in unicodedata.normalize('NFD', str(text or '').strip().lower()) if unicodedata.category(ch) != 'Mn').replace('_', ' ')


def _parse_warranty(text):
    value = _norm(text)
    if not value or value in ('0', 'no', 'sin garantia', 'ninguna'):
        return 0, 'meses'
    found = re.fullmatch(r'(\d{1,4})\s*(d|dia|dias|m|mes|meses|a|ano|anos|year|years)?', value)
    if not found:
        raise ValueError
    unit = {'d': 'dias', 'dia': 'dias', 'dias': 'dias', 'a': 'anios', 'ano': 'anios', 'anos': 'anios', 'year': 'anios', 'years': 'anios'}.get(found[2] or 'meses', 'meses')
    return int(found[1]), unit


def import_analyze(c, raw, filename=''):
    """Vista previa de la importación: valida cada fila, detecta series repetidas (en el archivo o ya registradas) y dice qué ficha se usará."""
    import client_import
    try:
        rows = client_import.read_rows(raw, filename)
    except client_import.ImportError_ as error:
        raise InventoryError(str(error))
    header = [_norm(h) for h in rows[0]]
    mapping = {}
    for field, names in IMPORT_FIELDS.items():
        for n, h in enumerate(header):
            if h in [_norm(x) for x in names]:
                mapping[field] = n
                break
    missing = [f for f in ('categoria', 'producto') if f not in mapping]
    if missing:
        raise InventoryError('Faltan columnas obligatorias: ' + ', '.join(missing) + '. Descarga la plantilla para ver el formato.')
    cats = {}
    for r in c.execute('SELECT k.*,p.name parent FROM inventory_categories k LEFT JOIN inventory_categories p ON p.id=k.parent_id WHERE k.kind=\'fisico\''):
        cats[(_norm(r['parent'] or r['name']), _norm(r['name']) if r['parent'] else '')] = r
    out, seen = [], set()
    for n, values in enumerate(rows[1:], 2):
        get = lambda f: str(values[mapping[f]]).strip() if f in mapping and mapping[f] < len(values) else ''
        problems, row = [], {f: get(f) for f in IMPORT_FIELDS}
        category = cats.get((_norm(row['categoria']), _norm(row['subcategoria']))) or (cats.get((_norm(row['categoria']), '')) if not row['subcategoria'] else None)
        if not category:
            problems.append('Categoría o subcategoría inexistente: «%s%s».' % (row['categoria'], ' › ' + row['subcategoria'] if row['subcategoria'] else ''))
        existing = None
        if row['sku']:
            existing = c.execute('SELECT i.id,i.tracking,g.name FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE i.sku=?', (row['sku'],)).fetchone()
        if not existing and row['producto']:
            existing = c.execute('SELECT i.id,i.tracking,g.name FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE lower(g.name)=lower(?)', (row['producto'],)).fetchone()
            if not existing and c.execute("SELECT 1 FROM catalog_items WHERE lower(name)=lower(?)", (row['producto'],)).fetchone():
                problems.append('Ya hay un elemento del catálogo con ese nombre sin ficha de inventario: incorpóralo desde el asistente.')
        if len(row['producto']) < 2:
            problems.append('Falta el nombre del producto.')
        tracking = existing['tracking'] if existing else ('serie' if _norm(row['control']) in ('serie', 'por serie', 'unidad') else 'granel' if _norm(row['control']) in ('granel', 'cantidad', 'a granel')
                                                          else category['tracking'] if category else 'granel')
        qty = 1
        if tracking == 'serie':
            if row['cantidad'] not in ('', '1'):
                problems.append('Los productos por serie van una fila por unidad (cantidad 1).')
            if row['serie']:
                try:
                    clean = inventory.clean_serial(row['serie'])
                    key = inventory.serial_key(clean)
                    if key in seen:
                        problems.append('Serie repetida en el archivo: %s.' % clean)
                    elif inventory.serial_owner(c, clean):
                        owner = inventory.serial_owner(c, clean)
                        problems.append('Serie ya registrada: %s (%s).' % (clean, owner['internal_code']))
                    seen.add(key)
                except InventoryError as error:
                    problems.append(str(error))
        else:
            if row['serie']:
                problems.append('Un producto a granel no lleva serie.')
            if not re.fullmatch(r'\d{1,6}', row['cantidad'] or '') or int(row['cantidad']) <= 0:
                problems.append('Cantidad no válida.')
            else:
                qty = int(row['cantidad'])
        for field in ('costo', 'precio'):
            try:
                cents(row[field] or '0', field)
            except InventoryError:
                problems.append('%s no válido.' % field.capitalize())
        for field in ('garantia_pcdoctor', 'garantia_fabricante'):
            try:
                _parse_warranty(row[field])
            except ValueError:
                problems.append('Garantía no válida («%s»): usa, por ejemplo, 90 días, 12 meses o 1 año.' % row[field])
        if row['minimo'] and not re.fullmatch(r'\d{1,6}', row['minimo']):
            problems.append('Mínimo no válido.')
        out.append({'line': n, 'values': row, 'tracking': tracking, 'quantity': qty, 'category_id': category['id'] if category else None,
                    'action': ('Ficha existente: ' + existing['name']) if existing else 'Ficha nueva', 'item_id': existing['id'] if existing else None, 'problems': problems})
    if len(out) > 2000:
        raise InventoryError('El archivo supera las 2000 filas.')
    digest = hashlib.sha256(raw).hexdigest()
    return {'rows': out, 'sha': digest, 'valid': sum(1 for r in out if not r['problems']), 'errors': sum(1 for r in out if r['problems']),
            'units': sum(r['quantity'] for r in out if not r['problems']), 'columns': sorted(mapping)}


def import_commit(c, raw, filename, sha, user, now):
    """Importa el inventario inicial revisado. Exige la misma vista previa (huella del archivo) y ninguna fila con error: todo o nada."""
    analysis = import_analyze(c, raw, filename)
    if analysis['sha'] != sha:
        raise InventoryError('El archivo cambió desde la vista previa: vuelve a revisarlo.', 409)
    if analysis['errors']:
        raise InventoryError('Corrige las %d filas con error antes de importar.' % analysis['errors'], 409)
    groups = {}
    for r in analysis['rows']:
        v = r['values']
        key = r['item_id'] or ('nuevo', _norm(v['producto']))
        group = groups.setdefault(key, {'row': r, 'entries': {}})
        cost = v['costo'] or '0'
        group['entries'].setdefault(cost, {'serials': [], 'quantity': 0, 'location': v['ubicacion']})
        group['entries'][cost]['serials'].append(v['serie'])
        group['entries'][cost]['quantity'] += r['quantity']
    created, units_total = [], 0
    for key, group in groups.items():
        r, v = group['row'], group['row']['values']
        item_id = r['item_id']
        if not item_id:
            store, maker = _parse_warranty(v['garantia_pcdoctor']), _parse_warranty(v['garantia_fabricante'])
            item_id = save_product(c, {'category_id': str(r['category_id']), 'brand': v['marca'], 'model': v['modelo'], 'name': v['producto'], 'sku': v['sku'], 'tracking': r['tracking'],
                                       'price': v['precio'] or '0', 'min_stock': v['minimo'] or '0', 'location': v['ubicacion'], 'warranty_store_qty': str(store[0]), 'warranty_store_unit': store[1],
                                       'warranty_maker_qty': str(maker[0]), 'warranty_maker_unit': maker[1]}, user, now)
            created.append(item_id)
        for cost, entry in group['entries'].items():
            data = {'item_id': str(item_id), 'reason': 'inicial', 'cost': cost, 'location': entry['location'], 'note': 'Importación de inventario inicial (%s)' % (filename or 'archivo')[:80]}
            if r['tracking'] == 'serie':
                data['units'] = json.dumps([{'serial': s} for s in entry['serials']])
            else:
                data['quantity'] = str(entry['quantity'])
            register(c, data, user, now)
            units_total += entry['quantity']
    event(c, now, user, 'importacion', 'Importación de inventario inicial: %d filas, %d fichas nuevas, %d unidades.' % (len(analysis['rows']), len(created), units_total))
    return {'rows': len(analysis['rows']), 'products_created': len(created), 'units': units_total}


# ---- Licencias digitales (clasificadas; existencias desde su módulo) -------------------------------------------------------

def licenses_tree(c, now):
    """Categoría → Marca → Familia → Edición con las existencias reales de cada producto de licencia (license_units). Sin claves."""
    import licenses
    products_ = {p['id']: p for p in licenses.products(c, now)}
    classified = {r['item_id']: dict(r) for r in c.execute('SELECT l.*,b.name brand,f.name family FROM license_classification l JOIN inventory_brands b ON b.id=l.brand_id LEFT JOIN inventory_families f ON f.id=l.family_id')}
    cats = [dict(r) for r in c.execute("SELECT * FROM inventory_categories WHERE kind='licencia' ORDER BY position,name")]
    families = [dict(r) for r in c.execute('SELECT f.*,b.name brand FROM inventory_families f JOIN inventory_brands b ON b.id=f.brand_id WHERE f.active=1 ORDER BY b.name,f.name')]

    def stock(p):
        s = p['stock']
        return {'disponible': s.get('disponible', 0), 'reservada': s.get('reservada', 0), 'entregada': s.get('entregada', 0), 'vencida': s.get('vencida', 0)}
    nodes = []
    for cat in cats:
        node = {'id': cat['id'], 'name': cat['name'], 'parent_id': cat['parent_id'], 'prefix': cat['prefix'], 'brands': {}}
        for fam in [f for f in families if f['category_id'] == cat['id']]:
            brand = node['brands'].setdefault(fam['brand'], {'name': fam['brand'], 'families': {}})
            brand['families'][fam['name']] = {'id': fam['id'], 'name': fam['name'], 'editions': [e for e in fam['editions'].split('\n') if e], 'products': []}
        for item_id, cl in classified.items():
            if cl['category_id'] != cat['id'] or item_id not in products_:
                continue
            p = products_[item_id]
            brand = node['brands'].setdefault(cl['brand'], {'name': cl['brand'], 'families': {}})
            family = brand['families'].setdefault(cl['family'] or 'Sin familia', {'id': cl['family_id'], 'name': cl['family'] or 'Sin familia', 'editions': [], 'products': []})
            family['products'].append({'id': item_id, 'name': p['name'], 'edition': cl['edition'], 'sku': cl['sku'], 'region': cl['region'], 'price_cents': p['price_cents'],
                                       'purchase_cents': p['purchase_cents'], 'devices': p['devices'], 'duration': p['duration_label'], 'image': p['image'], 'available': p['available'], 'stock': stock(p)})
        node['brands'] = [dict(b, families=list(b['families'].values())) for b in sorted(node['brands'].values(), key=lambda b: b['name'].lower())]
        nodes.append(node)
    pending = [{'id': p['id'], 'name': p['name'], 'brand': p['brand'], 'line': p['line_label'], 'stock': stock(p)} for p in products_.values() if p['id'] not in classified]
    totals = {k: sum(stock(p)[k] for p in products_.values()) for k in ('disponible', 'reservada', 'entregada', 'vencida')}
    return {'categories': nodes, 'unclassified': pending, 'totals': totals}


def classify_license(c, data, user, now):
    item = c.execute("SELECT id,name,brand FROM catalog_items WHERE id=? AND category IN ('licencia','seguridad')", (data.get('item_id'),)).fetchone() if _id(data.get('item_id')) else None
    if not item:
        raise InventoryError('Elige un producto de licencia.', 404, {'item_id': 'Producto no válido.'})
    category = _category(c, data.get('category_id'))
    if category['kind'] != 'licencia':
        raise InventoryError('Elige una categoría de licencias.', fields={'category_id': 'Categoría no válida.'})
    brand_id = _id(data.get('brand_id')) or ensure_brand(c, data.get('brand') or item['brand'], user, now)
    if not brand_id:
        raise InventoryError('Elige la marca.', fields={'brand_id': 'Marca obligatoria.'})
    family_id = _id(data.get('family_id'))
    if family_id and not c.execute('SELECT 1 FROM inventory_families WHERE id=? AND category_id=? AND brand_id=?', (family_id, category['id'], brand_id)).fetchone():
        raise InventoryError('La familia no corresponde a esa categoría y marca.', fields={'family_id': 'Familia no válida.'})
    sku = re.sub(r'\s', '', str(data.get('sku', '')))[:40]
    if sku and c.execute('SELECT 1 FROM license_classification WHERE sku=? AND item_id!=?', (sku, item['id'])).fetchone():
        raise InventoryError('Ese SKU ya pertenece a otra licencia.', fields={'sku': 'SKU repetido.'})
    values = (category['id'], brand_id, family_id, _text(data, 'edition', 80), sku, _text(data, 'region', 60), stamp(now), user['id'])
    if c.execute('SELECT 1 FROM license_classification WHERE item_id=?', (item['id'],)).fetchone():
        c.execute('UPDATE license_classification SET category_id=?,brand_id=?,family_id=?,edition=?,sku=?,region=?,updated_at=?,updated_by=? WHERE item_id=?', (*values, item['id']))
    else:
        c.execute('INSERT INTO license_classification(category_id,brand_id,family_id,edition,sku,region,updated_at,updated_by,item_id) VALUES (?,?,?,?,?,?,?,?,?)', (*values, item['id']))
    event(c, now, user, 'licencia_clasificada', 'Licencia clasificada: %s → %s.' % (item['name'], category_path(c, category['id'])))
    return item['id']


def license_code(c, product_id):
    """Código interno de una licencia nueva según su clasificación (PCD-AV-000001, PCD-M365-000001). Sin clasificar: el del módulo (LIC-)."""
    try:
        row = c.execute('SELECT category_id FROM license_classification WHERE item_id=?', (product_id,)).fetchone()
    except Exception:
        return None  # base sin la migración del Centro de Inventario
    return inventory.next_code(c, row[0]) if row else None


# ---- Panel general, búsqueda y traslado futuro -----------------------------------------------------------------------------

def dashboard(c, now):
    """Panel ejecutivo: indicadores, alertas (agotados, críticos y en el mínimo), actividad reciente y garantías por vencer."""
    today = now.date()
    items = products(c)
    active = [p for p in items if p['active']]
    soon = (today + timedelta(days=SOON_DAYS)).isoformat()
    expiring = [dict(r) for r in c.execute(UNIT_SQL + " WHERE u.store_warranty_to!='' AND u.store_warranty_to>=? AND u.store_warranty_to<=? AND u.status IN ('vendida','consumida') ORDER BY u.store_warranty_to LIMIT 50",
                                           (today.isoformat(), soon))]
    try:
        import licenses
        lic_free = sum(p['stock'].get('disponible', 0) for p in licenses.products(c, now) if p['managed'])
    except Exception:
        lic_free = 0
    rows = kardex(c, {})['rows']
    week = (today - timedelta(days=6)).isoformat()
    alerts = {state: [p for p in active if p['alerts_enabled'] and p['stock_state'] == state] for state in ('agotado', 'critico', 'minimo')}
    serial_units = sum(p['units'].get('disponible', 0) for p in active if p['tracking'] == 'serie')
    return {'cards': {'products': len(active), 'available': sum(p['available'] for p in active), 'serial_units': serial_units,
                      'out': sum(1 for p in active if p['stock_state'] == 'agotado'), 'critical': sum(1 for p in active if p['stock_state'] == 'critico'),
                      'at_min': sum(1 for p in active if p['stock_state'] == 'minimo'), 'low': sum(1 for p in active if p['urgent']),
                      'value_cents': sum(p['value_cents'] for p in active), 'cost_pending': sum(1 for r in rows if r.get('cost_pending') and not r.get('corrected')),
                      'licenses': lic_free, 'warranties_soon': len(expiring), 'moves_week': sum(1 for r in rows if r['at'][:10] >= week and r['type'] in ('entrada', 'salida'))},
            'alerts': {k: v[:12] for k, v in alerts.items()}, 'low': [p for p in active if p['low']][:10],
            'expiring': [dict(e, days_left=(date.fromisoformat(e['store_warranty_to']) - today).days) for e in expiring[:10]],
            'recent': [r for r in rows if r['type'] not in ('correccion', 'precio')][-10:][::-1]}


UNLIMITED = re.compile(r'ilimitad|perpetu|de por vida|lifetime|permanente|vitalici', re.I)


def licenses_table(c, now):
    """Licencias en una tabla compacta: categoría, marca, producto, edición, duración, dispositivos, precio y existencias del módulo Licencias
    (sin claves). Señala para revisión (sin cambiar nada) las fichas cuyo nombre indica duración ilimitada pero su duración es otra."""
    import licenses
    classified = {r['item_id']: dict(r) for r in c.execute('SELECT l.*,b.name brand_name,f.name family FROM license_classification l JOIN inventory_brands b ON b.id=l.brand_id LEFT JOIN inventory_families f ON f.id=l.family_id')}
    rows = []
    for p in licenses.products(c, now):
        if not p['managed']:
            continue
        cl = classified.get(p['id'])
        s = p['stock']
        stock = {'disponible': s.get('disponible', 0), 'reservada': s.get('reservada', 0), 'entregada': s.get('entregada', 0), 'vencida': s.get('vencida', 0)}
        flags = []
        if UNLIMITED.search(p['name']) and (p.get('duration') or '') != 'perpetua':
            flags.append('El nombre indica duración ilimitada, pero la ficha registra «%s». Verifica la duración real del producto.' % (p.get('duration_label') or p.get('duration') or 'sin duración'))
        if not (p['brand'] or (cl and cl['brand_name'])):
            flags.append('Sin marca en el catálogo.')
        state = 'revisar' if flags else 'disponible' if stock['disponible'] else 'sin_stock'
        rows.append({'id': p['id'], 'name': p['name'], 'brand': (cl and cl['brand_name']) or p['brand'] or '', 'category': category_path(c, cl['category_id']) if cl else 'Sin clasificar',
                     'category_id': cl['category_id'] if cl else None, 'family': (cl and cl['family']) or '', 'edition': (cl and cl['edition']) or p.get('edition') or '', 'type': p['line_label'],
                     'duration': p.get('duration_label') or '', 'devices': p.get('devices'), 'price_cents': p['price_cents'], 'stock': stock, 'state': state, 'flags': flags,
                     'classified': bool(cl), 'available': bool(p['available']), 'image': p.get('image') or ''})
    rows.sort(key=lambda r: (r['category'], r['brand'].lower(), r['name'].lower()))
    return {'rows': rows, 'totals': {k: sum(r['stock'][k] for r in rows) for k in ('disponible', 'reservada', 'entregada', 'vencida')}}


def review(c, now):
    """Revisión de datos (solo lectura): existencias contra unidades, entradas sin costo, posibles marcas repetidas, licencias por revisar y
    productos de licencia sin unidades. No corrige nada: cada hallazgo indica dónde revisarlo."""
    found = []
    for p in products(c):
        if p['tracking'] == 'serie' and p['active']:
            in_stock = p['units'].get('disponible', 0) + p['units'].get('reservada', 0)
            if in_stock != p['stock']:
                found.append({'kind': 'existencias', 'level': 'error', 'item_id': p['id'], 'text': '%s: %d unidades en existencia y saldo del Kardex %d.' % (p['name'], in_stock, p['stock'])})
    for r in kardex(c, {})['rows']:
        if r.get('cost_pending') and not r.get('corrected'):
            found.append({'kind': 'costo', 'level': 'aviso', 'item_id': r['item_id'], 'movement_id': r['movement_id'], 'text': '%s: entrada del %s sin costo (%s).' % (r['product'], r['at'][:10], r['label'])})
    brands = [(b['id'], b['name']) for b in c.execute('SELECT id,name FROM inventory_brands WHERE active=1')]
    norm = lambda t: re.sub(r'[^a-z0-9]', '', t.lower())
    aliases = {'wd': 'westerndigital', 'hp': 'hewlettpackard'}
    for i, (a_id, a) in enumerate(brands):
        for b_id, b in brands[i + 1:]:
            na, nb = norm(a), norm(b)
            first_a, first_b = norm(a.split()[0]), norm(b.split()[0])
            if na == nb or aliases.get(first_a) == nb or aliases.get(first_b) == na or (len(first_a) > 1 and first_a == first_b):
                found.append({'kind': 'marca', 'level': 'aviso', 'text': 'Posibles marcas repetidas: «%s» y «%s».' % (a, b)})
    for row in licenses_table(c, now)['rows']:
        for flag in row['flags']:
            found.append({'kind': 'licencia', 'level': 'aviso', 'license_id': row['id'], 'text': '%s: %s' % (row['name'], flag)})
        if not any(row['stock'].values()):
            found.append({'kind': 'licencia', 'level': 'info', 'license_id': row['id'], 'text': '%s: sin licencias registradas.' % row['name']})
    return {'findings': found, 'counts': {k: sum(1 for f in found if f['level'] == k) for k in ('error', 'aviso', 'info')}}


def search(c, q):
    q = re.sub(r'\s+', ' ', str(q or '')).strip()[:80]
    if len(q) < 2:
        return {'products': [], 'units': [], 'licenses': []}
    unit_rows = units(c, q=q)[:20]
    found = products(c, q)[:20]
    import licenses
    words = q.lower().split()
    lic = [{'id': p['id'], 'name': p['name'], 'brand': p['brand'], 'available': p['stock'].get('disponible', 0)} for p in licenses.products(c, __import__('datetime').datetime.now())
           if all(w in (p['name'] + ' ' + (p['brand'] or '')).lower() for w in words)][:10]
    return {'products': found, 'units': unit_rows, 'licenses': lic}


def reports(c):
    items = [p for p in products(c) if p['active']]
    by_category, by_brand = {}, {}
    for p in items:
        top = p['category'].split(' › ')[0]
        for table, key in ((by_category, top), (by_brand, p['brand'] or 'Sin marca')):
            row = table.setdefault(key, {'name': key, 'products': 0, 'units': 0, 'value_cents': 0, 'low': 0})
            row['products'] += 1
            row['units'] += max(0, p['stock'])
            row['value_cents'] += p['value_cents']
            row['low'] += 1 if p['low'] else 0
    sort = lambda t: sorted(t.values(), key=lambda r: -r['value_cents'])
    return {'by_category': sort(by_category), 'by_brand': sort(by_brand), 'low': [p for p in items if p['low']],
            'totals': {'products': len(items), 'units': sum(max(0, p['stock']) for p in items), 'value_cents': sum(p['value_cents'] for p in items)}}


def stock_xlsx(c):
    rows = [[p['name'], p['sku'], p['category'], p['brand'], p['model'], p['tracking_label'].split(' (')[0], p['stock'], p['reserved'], p['available'], p['min_stock'],
             p['average_cost_cents'] / 100, p['value_cents'] / 100, p['price_cents'] / 100, p['location'], p['warranty_store']['label'], p['warranty_maker']['label']] for p in products(c) if p['active']]
    return xlsx('Existencias', ['Producto', 'SKU', 'Categoría', 'Marca', 'Modelo', 'Control', 'Existencias', 'Reservadas', 'Disponibles', 'Mínimo', 'Costo promedio', 'Valor', 'Precio de venta',
                                'Ubicación', 'Garantía PC-DOCTOR', 'Garantía del fabricante'], rows)


TRANSFER_TABLES = ('inventory_categories', 'inventory_prefixes', 'inventory_brands', 'inventory_families', 'license_classification', 'inventory_items', 'inventory_units',
                   'inventory_movements', 'inventory_movement_units', 'inventory_reservations', 'inventory_transfers', 'suppliers', 'purchases', 'purchase_items')


def export_package(c, now):
    """Paquete para el traslado futuro y controlado a producción (pendiente de autorización): conserva identificadores, códigos e historial.
    Incluye los productos del catálogo enlazados. No incluye claves de licencias ni datos de clientes."""
    tables = {}
    for name in TRANSFER_TABLES:
        tables[name] = [dict(r) for r in c.execute('SELECT * FROM ' + name + ' ORDER BY rowid')]
    ids = sorted({r['catalog_id'] for r in tables['inventory_items']})
    tables['catalog_items'] = [dict(r) for r in c.execute('SELECT * FROM catalog_items WHERE id IN (%s) ORDER BY id' % ','.join('?' * len(ids)), ids)] if ids else []
    for unit in tables['inventory_units']:
        unit['client_id'] = None  # los clientes de la base de pruebas no se trasladan; se vuelven a enlazar en producción
    body = json.dumps(tables, ensure_ascii=False, sort_keys=True, default=str)
    return {'format': 'ordenes-pro-inventario/1', 'generated_at': stamp(now), 'sha256': hashlib.sha256(body.encode()).hexdigest(),
            'counts': {k: len(v) for k, v in tables.items()}, 'tables': tables}


# ---- Reinicialización controlada de existencias -----------------------------------------------------------------------------------
REINIT_WORD = 'REINICIALIZAR'


def _reinit_ids(raw):
    ids = [int(x) for x in re.split(r'[,\s]+', str(raw or '')) if x.isdigit()]
    if not 1 <= len(ids) <= 200 or len(set(ids)) != len(ids):
        raise InventoryError('Elige los productos que se reinicializan.', 400, {'item_ids': 'Selecciona al menos un producto.'})
    return ids


def reinit_preview(c, raw_ids):
    """Qué hará la reinicialización con cada ficha (solo lectura): existencias, unidades, movimientos, correcciones, ventas, reservas y
    bloqueos. Nada se borra: las existencias quedan en 0 con una salida de ajuste trazable."""
    rows = []
    for item_id in _reinit_ids(raw_ids):
        item = product(c, item_id)
        units = [dict(u) for u in c.execute("SELECT id,internal_code,serial,status FROM inventory_units WHERE item_id=? ORDER BY id", (item_id,))]
        moves = c.execute('SELECT COUNT(*),COALESCE(SUM(CASE WHEN reason IN (\'venta\',\'uso_orden\') THEN 1 ELSE 0 END),0) FROM inventory_movements WHERE item_id=?', (item_id,)).fetchone()
        fixes = c.execute('SELECT COUNT(*) FROM inventory_cost_corrections WHERE item_id=?', (item_id,)).fetchone()[0] if _has_column(c, 'inventory_cost_corrections', 'id') else 0
        held = c.execute("SELECT COUNT(*) FROM inventory_reservations WHERE item_id=? AND status='activa'", (item_id,)).fetchone()[0]
        blockers = ['Tiene %d reserva(s) activa(s): libéralas antes.' % held] if held else []
        out = [u for u in units if u['status'] == 'disponible']
        if item['tracking'] == 'serie' and len(out) != item['stock'] and item['stock'] > 0:
            blockers.append('Las unidades disponibles (%d) no coinciden con las existencias (%d): revisa la ficha.' % (len(out), item['stock']))
        rows.append({'id': item_id, 'name': item['name'], 'sku': item['sku'], 'tracking': item['tracking'], 'stock': item['stock'], 'average_cost_cents': item['average_cost_cents'],
                     'value_cents': item['value_cents'], 'movements': moves[0], 'sales': moves[1], 'corrections': fixes, 'reservations': held,
                     'units': [{'internal_code': u['internal_code'], 'serial': u['serial'], 'status': u['status']} for u in units],
                     'action': ('Salida de ajuste por %d unidad(es); las unidades disponibles pasan a baja y liberan su serie para el nuevo ingreso' % item['stock']) if item['stock'] > 0 else 'Ya está en 0: no se registra nada',
                     'blockers': blockers})
    return {'rows': rows, 'word': REINIT_WORD, 'blocked': any(r['blockers'] for r in rows)}


def reinitialize(c, data, user, now):
    """Deja en 0 las existencias de las fichas elegidas, con autorización expresa (administración, motivo y la palabra de confirmación).
    Cada ficha recibe una salida de ajuste (los movimientos anteriores, las correcciones y las ventas no cambian); las unidades disponibles
    pasan a baja y liberan su serie para volver a ingresarlas. Idempotente con la clave de solicitud."""
    if user['role'] != 'administrador':
        raise InventoryError('Solo administración reinicializa el inventario.', 403)
    key = str(data.get('request_key', '') or '').strip()
    if key:
        if not re.fullmatch(r'[A-Za-z0-9-]{16,64}', key):
            raise InventoryError('Solicitud no válida. Recarga la página.', 400)
        same = c.execute('SELECT id,code,summary FROM inventory_reinit_batches WHERE request_key=?', (key,)).fetchone()
        if same:
            return {'batch': same['code'], 'rows': json.loads(same['summary']), 'duplicate': True}
    if str(data.get('confirm', '')).strip() != REINIT_WORD:
        raise InventoryError('Escribe %s para confirmar la reinicialización.' % REINIT_WORD, 400, {'confirm': 'Confirmación obligatoria.'})
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if not 10 <= len(reason) <= 300:
        raise InventoryError('Indica el motivo de la reinicialización (10 a 300 caracteres).', 400, {'reason': 'Motivo obligatorio.'})
    preview = reinit_preview(c, data.get('item_ids'))
    if preview['blocked']:
        raise InventoryError('Hay productos con bloqueos: ' + ' '.join(b for r in preview['rows'] for b in r['blockers']), 409)
    seq = c.execute("SELECT seq FROM sqlite_sequence WHERE name='inventory_reinit_batches'").fetchone()
    top = c.execute('SELECT COALESCE(MAX(id),0) FROM inventory_reinit_batches').fetchone()[0]
    bid = max(seq[0] if seq else 0, top) + 1
    code = 'RI-%06d' % bid
    summary = []
    for r in preview['rows']:
        if r['stock'] <= 0:
            summary.append({'id': r['id'], 'name': r['name'], 'before': r['stock'], 'after': r['stock'], 'movement_id': None})
            continue
        units = [u['id'] for u in c.execute("SELECT id FROM inventory_units WHERE item_id=? AND status='disponible' ORDER BY id", (r['id'],))] if r['tracking'] == 'serie' else None
        mid = inventory.move(c, r['id'], -1, 'ajuste_salida', str(r['stock']), '0', user, now, reference_kind='reinicializacion', reference_id=bid,
                             note='Reinicialización autorizada (%s): %s' % (code, reason), request_key='reinit-%d-%d' % (bid, r['id']), unit_ids=units)
        for uid in units or []:
            u = c.execute('SELECT serial,serial_key FROM inventory_units WHERE id=?', (uid,)).fetchone()
            c.execute("UPDATE inventory_units SET status='baja',serial_key='',released_serial=?,updated_at=?,updated_by=? WHERE id=?", (u['serial'], stamp(now), user['id'], uid))
        after = product(c, r['id'])['stock']
        event(c, now, user, 'reinicializacion', 'Reinicialización %s: existencias %d → %d. Motivo: %s' % (code, r['stock'], after, reason), r['id'])
        summary.append({'id': r['id'], 'name': r['name'], 'before': r['stock'], 'after': after, 'movement_id': mid})
    c.execute('INSERT INTO inventory_reinit_batches(id,code,reason,items,summary,request_key,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
              (bid, code, reason, json.dumps([r['id'] for r in preview['rows']]), json.dumps(summary, ensure_ascii=False), key or None, user['id'], stamp(now)))
    return {'batch': code, 'rows': summary, 'duplicate': False}


def reinit_batches(c):
    names = {r[0]: r[1] for r in c.execute('SELECT id,name FROM users')}
    return [dict(r, summary=json.loads(r['summary']), actor=names.get(r['created_by'], ''), kind='archivo' if r['code'].startswith('AR-') else 'reinicializacion')
            for r in c.execute('SELECT id,code,reason,summary,created_by,created_at FROM inventory_reinit_batches ORDER BY id DESC LIMIT 50')]



# ---- Archivo de productos físicos (limpieza autorizada del catálogo) ---------------------------------------------------------------
ARCHIVE_WORD = 'ARCHIVAR'
PHYSICAL = ('repuesto', 'otro')


def archived_ids(c):
    try:
        ids = set()
        for r in c.execute("SELECT items FROM inventory_reinit_batches WHERE code LIKE 'AR-%'"):
            ids.update(json.loads(r['items']).get('inventory', []) if r['items'].startswith('{') else [])
        return ids
    except Exception:
        return set()


def _license_catalog_ids(c):
    ids = {r[0] for r in c.execute('SELECT item_id FROM license_products')}
    ids |= {r[0] for r in c.execute("SELECT id FROM catalog_items WHERE category NOT IN ('repuesto','otro','servicio')")}
    return ids


def archive_preview(c):
    """Qué se archivaría (solo lectura): fichas físicas del inventario y productos físicos del catálogo sin ficha. Nunca incluye licencias,
    servicios ni productos con existencias; indica dónde se usan (presupuestos, facturas, ventas de licencias) para conservar el historial."""
    licenses = _license_catalog_ids(c)
    archived = archived_ids(c)
    uses = lambda table, col, i: c.execute('SELECT COUNT(*) FROM ' + table + ' WHERE ' + col + '=?', (i,)).fetchone()[0]
    inventory_rows = []
    for r in c.execute(PRODUCT_SQL + ' ORDER BY i.id').fetchall():
        if r['id'] in archived or r['catalog_id'] in licenses:
            continue
        blockers = []
        if r['stock'] > 0:
            blockers.append('Tiene %d en existencia: reinicialízalo antes.' % r['stock'])
        if r['reserved']:
            blockers.append('Tiene reservas activas.')
        inventory_rows.append({'id': r['id'], 'catalog_id': r['catalog_id'], 'name': r['name'], 'sku': r['sku'], 'barcode': r['barcode'] if 'barcode' in r.keys() else '', 'stock': r['stock'],
                               'price_cents': r['price_cents'], 'units': c.execute('SELECT COUNT(*) FROM inventory_units WHERE item_id=?', (r['id'],)).fetchone()[0],
                               'movements': c.execute('SELECT COUNT(*) FROM inventory_movements WHERE item_id=?', (r['id'],)).fetchone()[0],
                               'quotes': uses('quote_items', 'catalog_id', r['catalog_id']), 'invoices': uses('invoice_items', 'catalog_id', r['catalog_id']), 'blockers': blockers})
    linked = {r[0] for r in c.execute('SELECT catalog_id FROM inventory_items')}
    catalog_rows = [{'id': r['id'], 'name': r['name'], 'category': r['category'], 'price_cents': r['price_cents'], 'quotes': uses('quote_items', 'catalog_id', r['id']),
                     'invoices': uses('invoice_items', 'catalog_id', r['id'])}
                    for r in c.execute("SELECT * FROM catalog_items WHERE category IN ('repuesto','otro') AND available=1 ORDER BY id") if r['id'] not in linked and r['id'] not in licenses]
    licenses_state = {r[0]: r[1] for r in c.execute('SELECT status,COUNT(*) FROM license_units GROUP BY status')}
    return {'inventory': inventory_rows, 'catalog': catalog_rows, 'word': ARCHIVE_WORD, 'licenses': licenses_state,
            'blocked': any(r['blockers'] for r in inventory_rows)}


def archive(c, data, user, now):
    """Archiva (no borra) los productos físicos elegidos: las fichas quedan inactivas, sin alertas y fuera del catálogo; el nombre, el SKU y el
    código de barras se liberan para volver a registrarlos (los originales quedan en el lote). Kardex, unidades, ventas, presupuestos, facturas y
    garantías no cambian. Licencias y servicios nunca se tocan. Solo administración, con motivo y la palabra de confirmación; idempotente."""
    if user['role'] != 'administrador':
        raise InventoryError('Solo administración archiva productos.', 403)
    key = str(data.get('request_key', '') or '').strip()
    if key:
        if not re.fullmatch(r'[A-Za-z0-9-]{16,64}', key):
            raise InventoryError('Solicitud no válida. Recarga la página.', 400)
        same = c.execute('SELECT code,summary FROM inventory_reinit_batches WHERE request_key=?', (key,)).fetchone()
        if same:
            return {'batch': same['code'], 'rows': json.loads(same['summary']), 'duplicate': True}
    if str(data.get('confirm', '')).strip() != ARCHIVE_WORD:
        raise InventoryError('Escribe %s para confirmar.' % ARCHIVE_WORD, 400, {'confirm': 'Confirmación obligatoria.'})
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if not 10 <= len(reason) <= 300:
        raise InventoryError('Indica el motivo (10 a 300 caracteres).', 400, {'reason': 'Motivo obligatorio.'})
    ids = lambda raw: [int(x) for x in re.split(r'[,\s]+', str(raw or '')) if x.isdigit()]
    want_inv, want_cat = set(ids(data.get('item_ids'))), set(ids(data.get('catalog_ids')))
    if not want_inv and not want_cat:
        raise InventoryError('Elige los productos que se archivan.', 400, {'item_ids': 'Selecciona al menos un producto.'})
    preview = archive_preview(c)
    inv_rows = {r['id']: r for r in preview['inventory']}
    cat_rows = {r['id']: r for r in preview['catalog']}
    if not want_inv <= set(inv_rows) or not want_cat <= set(cat_rows):
        raise InventoryError('Hay productos que no se pueden archivar (licencias, servicios o ya archivados).', 409)
    blocked = [b for i in want_inv for b in inv_rows[i]['blockers']]
    if blocked:
        raise InventoryError('Hay productos con bloqueos: ' + ' '.join(blocked), 409)
    seq = c.execute("SELECT seq FROM sqlite_sequence WHERE name='inventory_reinit_batches'").fetchone()
    bid = max(seq[0] if seq else 0, c.execute('SELECT COALESCE(MAX(id),0) FROM inventory_reinit_batches').fetchone()[0]) + 1
    code = 'AR-%06d' % bid
    suffix = ' (archivado %s)' % code
    summary = []
    for i in sorted(want_inv):
        r = inv_rows[i]
        c.execute("UPDATE inventory_items SET active=0,sku='',updated_at=?,updated_by=? WHERE id=?", (stamp(now), user['id'], i))
        if _has_column(c, 'inventory_items', 'barcode'):
            c.execute("UPDATE inventory_items SET barcode='' WHERE id=?", (i,))
        if _has_column(c, 'inventory_items', 'alerts_enabled'):
            c.execute('UPDATE inventory_items SET alerts_enabled=0 WHERE id=?', (i,))
        c.execute('UPDATE catalog_items SET available=0,name=?,updated_at=?,updated_by=? WHERE id=?', ((r['name'] + suffix)[:200], stamp(now), user['id'], r['catalog_id']))
        event(c, now, user, 'archivado', 'Producto archivado (%s): %s. Motivo: %s' % (code, r['name'], reason), i)
        summary.append({'kind': 'inventario', 'id': i, 'catalog_id': r['catalog_id'], 'name': r['name'], 'sku': r['sku'], 'barcode': r['barcode'], 'price_cents': r['price_cents']})
    for i in sorted(want_cat):
        r = cat_rows[i]
        c.execute('UPDATE catalog_items SET available=0,name=?,updated_at=?,updated_by=? WHERE id=?', ((r['name'] + suffix)[:200], stamp(now), user['id'], i))
        summary.append({'kind': 'catalogo', 'id': i, 'name': r['name'], 'category': r['category'], 'price_cents': r['price_cents']})
    c.execute('INSERT INTO inventory_reinit_batches(id,code,reason,items,summary,request_key,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
              (bid, code, reason, json.dumps({'inventory': sorted(want_inv), 'catalog': sorted(want_cat)}), json.dumps(summary, ensure_ascii=False), key or None, user['id'], stamp(now)))
    return {'batch': code, 'rows': summary, 'duplicate': False}
