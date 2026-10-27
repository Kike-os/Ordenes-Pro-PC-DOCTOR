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
    return {'id': r['id'], 'catalog_id': r['catalog_id'], 'name': r['name'], 'code': r['catalog_code'] or '', 'sku': r['sku'], 'model': r['model'], 'brand': r['brand'] or '',
            'brand_id': r['brand_id'], 'category_id': r['category_id'], 'category': path, 'top_category_id': r['category_parent'] or r['category_id'],
            'tracking': r['tracking'], 'tracking_label': TRACKING[r['tracking']], 'kind': r['kind'], 'stock': stock, 'reserved': r['reserved'], 'available': max(0, stock - r['reserved']),
            'min_stock': r['min_stock'], 'low': bool(r['active']) and stock <= r['min_stock'], 'out': stock <= 0, 'location': r['location'], 'active': r['active'],
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
    out = []
    for r in rows:
        if cats and r['category_id'] not in cats:
            continue
        if _id(brand_id) and r['brand_id'] != int(brand_id):
            continue
        hay = ' '.join(str(v or '') for v in (r['name'], r['sku'], r['model'], r['brand'], r['category_name'], r['parent_name'], r['catalog_code'], r['location'])).lower()
        if words and r['id'] not in unit_hits and not all(w in hay for w in words):
            continue
        item = _product_dict(c, r)
        if state == 'bajo' and not item['low'] or state == 'agotado' and not item['out'] or state == 'inactivo' and item['active'] or state == 'activo' and not item['active']:
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
        clash = c.execute('SELECT g.name FROM inventory_items i JOIN catalog_items g ON g.id=i.catalog_id WHERE i.category_id=? AND i.brand_id=? AND lower(i.model)=lower(?) AND i.id!=?',
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
        event(c, now, user, 'ficha_editada', 'Ficha actualizada: %s.' % name, old['id'])
        return old['id']
    new_id = c.execute('INSERT INTO inventory_items(category_id,brand_id,model,tracking,sku,min_stock,location,warranty_store_qty,warranty_store_unit,warranty_store_from,'
                       'warranty_maker_qty,warranty_maker_unit,warranty_maker_from,catalog_id,kind,active,created_at,created_by,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)',
                       (*values[:-2], catalog_id, category['item_kind'], stamp(now), user['id'], stamp(now), user['id'])).lastrowid
    event(c, now, user, 'ficha_creada', 'Ficha creada: %s (%s, %s).' % (name, category_path(c, category['id']), TRACKING[tracking].split(' (')[0].lower()), new_id)
    return new_id


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
    try:
        cost = cents(data.get('cost', '0') or '0', 'cost')
    except InventoryError:
        raise InventoryError('Costo unitario no válido.', fields={'cost': 'Importe en USD con hasta dos decimales.'})
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
                              request_key=key, serials=serials, location=_text(data, 'location', 80))
    if _text(data, 'location', 80) and item['tracking'] == 'granel':
        c.execute('UPDATE inventory_items SET location=? WHERE id=?', (_text(data, 'location', 80), item_id))
    return _register_result(c, item_id, movement)


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
    try:
        movement = inventory.move(c, item_row['id'], -1, reason, amount, '0', user, now, reference_kind, reference_id, note, str(data.get('request_key') or '')[:64] or None,
                                  unit_ids=unit_ids, reservation_id=_id(data.get('reservation_id')), unit_values=values)
    except Exception as error:
        if 'UNIQUE' in str(error) and reference_kind == 'orden':
            raise InventoryError('La orden %s ya registró la salida de este producto: no se descuenta dos veces.' % order['code'], 409, {'order_code': 'Salida ya registrada.'})
        raise
    return {'movement_id': movement, 'item': product(c, item_row['id'])}


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
    reservation = c.execute('INSERT INTO inventory_reservations(item_id,quantity,reference,order_id,status,note,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
                            (item['id'], amount, reference, order['id'] if order else None, 'activa', _text(data, 'note', 300), user['id'], stamp(now))).lastrowid
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
    rows = c.execute("SELECT r.*,g.name product,i.tracking,COALESCE(s.name,'') actor,o.code order_code FROM inventory_reservations r JOIN inventory_items i ON i.id=r.item_id "
                     'JOIN catalog_items g ON g.id=i.catalog_id LEFT JOIN users s ON s.id=r.created_by LEFT JOIN orders o ON o.id=r.order_id ' + where + ' ORDER BY r.id DESC LIMIT 300',
                     (status,) if where else ()).fetchall()
    out = []
    for r in rows:
        item = dict(r)
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

KARDEX_TYPES = {'entrada': 'Entradas', 'salida': 'Salidas', 'reserva': 'Reservas y liberaciones', 'traslado': 'Traslados', **{'m:' + k: v for k, v in inventory.IN_REASONS.items()},
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


def kardex(c, filters=None):
    """Kardex valorizado (costo promedio ponderado móvil) con reservas y traslados. El saldo se calcula sobre todo el historial del producto y
    después se aplican los filtros: el saldo mostrado siempre es el real."""
    f = filters or {}
    cats = _category_ids(c, f.get('category_id'))
    items = c.execute(PRODUCT_SQL + ' ORDER BY g.name COLLATE NOCASE').fetchall()
    serial = inventory.serial_key(f.get('serial') or '')
    kind = str(f.get('type') or '')
    user_id = _id(f.get('user_id'))
    start, end = str(f.get('from') or ''), str(f.get('to') or '')
    names = {r[0]: r[1] for r in c.execute('SELECT id,name FROM users')}
    rows = []
    for item in items:
        if cats and item['category_id'] not in cats or _id(f.get('brand_id')) and item['brand_id'] != int(f['brand_id']) or _id(f.get('item_id')) and item['id'] != int(f['item_id']):
            continue
        base = {'item_id': item['id'], 'product': item['name'], 'sku': item['sku'], 'brand': item['brand'] or '', 'tracking': item['tracking'],
                'category': (item['parent_name'] + ' › ' + item['category_name']) if item['parent_name'] else (item['category_name'] or 'Sin categoría')}
        timeline, moved_at = [], {}
        for m, balance, avg, value, applied in inventory.valuation(c, item['id']):
            serials = [dict(r) for r in c.execute('SELECT u.internal_code,u.serial FROM inventory_movement_units x JOIN inventory_units u ON u.id=x.unit_id WHERE x.movement_id=? ORDER BY u.id', (m['id'],))]
            moved_at[m['id']] = m['created_at']
            timeline.append((m['created_at'], 0, 2 * m['id'], dict(base, at=m['created_at'], type='entrada' if m['direction'] == 1 else 'salida', reason=m['reason'],
                             label=(inventory.IN_REASONS if m['direction'] == 1 else inventory.OUT_REASONS)[m['reason']], entry=m['quantity'] if m['direction'] == 1 else 0,
                             exit=m['quantity'] if m['direction'] == -1 else 0, unit_cost_cents=applied, average_cents=avg, balance=balance, balance_cents=value,
                             document=_reference(c, m), note=m['note'], user_id=m['created_by'], actor=names.get(m['created_by'], 'Sistema'), units=serials)))
        for r in c.execute('SELECT * FROM inventory_reservations WHERE item_id=?', (item['id'],)).fetchall():
            units_ = [dict(u) for u in c.execute('SELECT internal_code,serial FROM inventory_units WHERE reservation_id=? OR id IN (SELECT unit_id FROM inventory_movement_units WHERE movement_id=?)',
                                                  (r['id'], r['movement_id'] or 0))]
            # Una reserva consumida va siempre antes de la salida que la consumió (aunque ocurran en el mismo segundo).
            order_key = (r['created_at'], 0, 2 * r['movement_id'] - 1) if r['movement_id'] and r['created_at'] >= moved_at.get(r['movement_id'], '') else (r['created_at'], 1, r['id'])
            timeline.append((*order_key, dict(base, at=r['created_at'], type='reserva', reason='reserva', label='Reserva (no descuenta)', entry=0, exit=0, reserved=r['quantity'],
                             document=r['reference'], note=r['note'], user_id=r['created_by'], actor=names.get(r['created_by'], 'Sistema'), units=units_)))
            if r['status'] == 'liberada':
                timeline.append((r['closed_at'], 1, r['id'], dict(base, at=r['closed_at'], type='reserva', reason='liberacion', label='Liberación de reserva', entry=0, exit=0, reserved=-r['quantity'],
                                 document=r['reference'], note='', user_id=r['closed_by'], actor=names.get(r['closed_by'], 'Sistema'), units=units_)))
        for t in c.execute('SELECT t.*,u.internal_code,u.serial FROM inventory_transfers t LEFT JOIN inventory_units u ON u.id=t.unit_id WHERE t.item_id=?', (item['id'],)).fetchall():
            timeline.append((t['created_at'], 2, t['id'], dict(base, at=t['created_at'], type='traslado', reason='traslado', label='Traslado: %s → %s' % (t['from_location'] or 'sin ubicación', t['to_location']),
                             entry=0, exit=0, moved=t['quantity'], document='', note=t['note'], user_id=t['created_by'], actor=names.get(t['created_by'], 'Sistema'),
                             units=[{'internal_code': t['internal_code'], 'serial': t['serial']}] if t['internal_code'] else [])))
        timeline.sort(key=lambda e: (e[0], e[1], e[2]))
        last = {'balance': 0, 'average_cents': 0, 'balance_cents': 0}
        for _, _, _, row in timeline:
            if row['type'] in ('entrada', 'salida'):
                last = {k: row[k] for k in last}
            else:
                row.update(unit_cost_cents=0, **last)
            rows.append(row)
    out = []
    for row in rows:
        day = row['at'][:10]
        if start and day < start or end and day > end:
            continue
        if kind in ('entrada', 'salida', 'reserva', 'traslado') and row['type'] != kind or kind.startswith('m:') and row['reason'] != kind[2:]:
            continue
        if user_id and row['user_id'] != user_id:
            continue
        if serial and not any(serial in inventory.serial_key(u['serial'] or '') or serial in (u['internal_code'] or '') for u in row['units']):
            continue
        out.append(row)
    out.sort(key=lambda r: r['at'])
    totals = {'entries': sum(r['entry'] for r in out), 'exits': sum(r['exit'] for r in out), 'rows': len(out),
              'entry_cents': sum(r['entry'] * r['unit_cost_cents'] for r in out if r['type'] == 'entrada'), 'exit_cents': sum(r['exit'] * r['unit_cost_cents'] for r in out if r['type'] == 'salida')}
    return {'rows': out[-2000:], 'totals': totals, 'truncated': len(out) > 2000}


KARDEX_COLUMNS = ['Fecha', 'Producto', 'SKU', 'Categoría', 'Marca', 'Serie / código', 'Movimiento', 'Entrada', 'Salida', 'Costo unitario', 'Costo promedio', 'Saldo', 'Valor del saldo', 'Documento', 'Responsable']


def _kardex_cells(r):
    units_text = ', '.join((u['serial'] + ' (' + u['internal_code'] + ')') if u['serial'] else u['internal_code'] for u in r['units'])
    return [r['at'].replace('T', ' ')[:16], r['product'], r['sku'], r['category'], r['brand'], units_text, r['label'], r['entry'] or '', r['exit'] or '',
            r['unit_cost_cents'] / 100 if r['type'] in ('entrada', 'salida') else '', r['average_cents'] / 100, r['balance'], r['balance_cents'] / 100, r['document'] or r['note'], r['actor']]


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


def kardex_pdf(rows, totals, subtitle=''):
    """Kardex en PDF A4 horizontal con el logo original de PC-DOCTOR, paginado."""
    from document_canvas import Canvas, BLUE, GRAY
    w, h = 842, 595
    pdf = Canvas(w, h, 'Kardex de inventario')
    widths = [62, 120, 52, 70, 50, 100, 78, 34, 34, 46, 46, 36, 50, 64]
    heads = ['Fecha', 'Producto', 'SKU', 'Categoría', 'Marca', 'Serie / código', 'Movimiento', 'Ent.', 'Sal.', 'C. unit.', 'C. prom.', 'Saldo', 'Valor', 'Documento']
    pages = 0

    def header():
        nonlocal pages
        pdf.page()
        pages += 1
        pdf.logo(24, 18, 70)
        pdf.text('Kardex valorizado de inventario', 104, 22, 14, True, BLUE)
        pdf.text('Costo promedio ponderado móvil · ' + (subtitle or 'todos los productos') + ' · página %d' % pages, 104, 42, 8, False, GRAY)
        x = 24
        for title, width in zip(heads, widths):
            pdf.text(title, x, 74, 7, True, BLUE)
            x += width
        pdf.line(24, 86, w - 48)
        return 92
    y = header()
    for r in rows:
        cells = _kardex_cells(r)
        values = [cells[0], cells[1], cells[2], cells[3], cells[4], cells[5], cells[6], str(cells[7]), str(cells[8]),
                  usd(int(round(cells[9] * 100))) if cells[9] != '' else '', usd(r['average_cents']), str(r['balance']), usd(r['balance_cents']), cells[13]]
        wrapped = [pdf.wrap(v, width - 4, 7)[:2] for v, width in zip(values, widths)]
        height = 10 * max(len(x) for x in wrapped) + 4
        if y + height > h - 40:
            y = header()
        x = 24
        for lines, width in zip(wrapped, widths):
            for n, line in enumerate(lines):
                pdf.text(line, x, y + n * 10, 7)
            x += width
        y += height
    pdf.line(24, y + 2, w - 48)
    pdf.text('Movimientos: %d · Entradas: %d · Salidas: %d · Valor de entradas: %s · Valor de salidas: %s' % (totals['rows'], totals['entries'], totals['exits'], usd(totals['entry_cents']), usd(totals['exit_cents'])),
             24, y + 8, 8, True)
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
    recent = kardex(c, {})['rows'][-12:][::-1]
    return {'cards': {'products': len(active), 'available': sum(p['available'] for p in active), 'low': sum(1 for p in active if p['low']),
                      'value_cents': sum(p['value_cents'] for p in active), 'licenses': lic_free, 'warranties_soon': len(expiring)},
            'low': [p for p in active if p['low']][:10], 'expiring': [dict(e, days_left=(date.fromisoformat(e['store_warranty_to']) - today).days) for e in expiring[:10]], 'recent': recent}


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
