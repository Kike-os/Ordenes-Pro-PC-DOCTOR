"""Limpieza segura del catálogo de productos y servicios (1.5.268).

Regla: un producto solo se ELIMINA si está inactivo y no tiene ninguna referencia que deba conservarse (presupuestos de órdenes,
proformas y ventas, facturas electrónicas, licencias vendidas o en inventario, ficha de inventario con sus movimientos, compras, unidades
y garantías). Con referencias se puede CONSERVAR ARCHIVADO: sale del catálogo operativo y su historial no cambia. Nunca se tocan
facturas, ventas, movimientos de inventario ni documentos; cada producto se revisa por separado, también en la eliminación masiva.
Cada resultado queda en catalog_removals (inmutable) y en la auditoría."""
import json
import re

# Referencias que impiden eliminar: (tabla, columna, etiqueta para la persona).
PROTECTED = (
    ('quote_items', 'catalog_id', 'presupuestos de órdenes técnicas'),
    ('proforma_items', 'catalog_id', 'proformas y ventas'),
    ('invoice_items', 'catalog_id', 'facturas electrónicas'),
    ('license_sale_items', 'product_id', 'ventas de licencias'),
    ('license_units', 'product_id', 'licencias registradas'),
    ('license_batches', 'product_id', 'compras de licencias'),
    ('license_events', 'product_id', 'historial de licencias'),
    ('inventory_items', 'catalog_id', 'ficha de inventario'),
)
# Detalle de una ficha de inventario (solo para explicar por qué se conserva; la ficha ya basta para impedir la eliminación).
INVENTORY_DETAIL = (
    ('inventory_movements', 'movimientos de existencias'), ('purchase_items', 'compras a proveedores'), ('inventory_units', 'unidades y garantías'),
    ('inventory_reservations', 'reservas'), ('sales_requests', 'solicitudes de venta'), ('order_part_requests', 'repuestos de órdenes'),
)
# Datos propios del producto, que se eliminan con él (no son historial de terceros).
OWNED = (('catalog_images', 'item_id'), ('catalog_price_history', 'item_id'), ('license_products', 'item_id'), ('license_classification', 'item_id'))
DETAIL_COLUMN = {'sales_requests': 'inventory_item_id', 'order_part_requests': 'inventory_item_id'}
MAX_IDS = 500


class CleanupError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _tables(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


OWNED_LABELS = {'catalog_price_history': 'historial de precios', 'catalog_images': 'imagen', 'license_products': 'ficha de licencia', 'license_classification': 'clasificación de licencia'}


def _immutable_owned(c, tables):
    """Tablas propias del producto con un disparador que impide borrar filas: no se tocan."""
    out = []
    for table, column in OWNED:
        if table in tables and c.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=? AND upper(sql) LIKE '%BEFORE DELETE%'", (table,)).fetchone():
            out.append((table, column))
    return out


def _unknown_refs(c, tables):
    """Red de seguridad: tablas que apuntan a catalog_items con clave foránea y no están en las listas conocidas (una tabla futura).
    Cuentan como protección: nunca se elimina un producto referenciado por algo que esta limpieza no conoce."""
    known = {(t, col) for t, col, _ in PROTECTED} | set(OWNED)
    found = []
    for table in sorted(tables):
        if table.startswith('sqlite_'):
            continue
        for fk in c.execute('PRAGMA foreign_key_list("%s")' % table):
            if fk[2] == 'catalog_items' and (table, fk[3]) not in known:
                found.append((table, fk[3]))
    return found


def archived_ids(c):
    """Productos archivados: por esta limpieza (archived_at) o por un lote AR- de Inventario (catálogo o ficha de inventario)."""
    ids = {r[0] for r in c.execute("SELECT id FROM catalog_items WHERE COALESCE(archived_at,'')!=''")}
    try:
        inventory = set()
        for r in c.execute("SELECT items FROM inventory_reinit_batches WHERE code LIKE 'AR-%'"):
            data = json.loads(r[0]) if str(r[0]).startswith('{') else {}
            ids.update(data.get('catalog', []))
            inventory.update(data.get('inventory', []))
        if inventory:
            marks = ','.join('?' * len(inventory))
            ids.update(r[0] for r in c.execute('SELECT catalog_id FROM inventory_items WHERE id IN (' + marks + ')', sorted(inventory)))
    except Exception:
        pass
    return ids


def reference_counts(c):
    """{producto: total de referencias protegidas} con una consulta agrupada por tabla (para la lista)."""
    tables, out = _tables(c), {}
    for table, column, _label in PROTECTED:
        if table not in tables:
            continue
        for item, count in c.execute('SELECT %s,COUNT(*) FROM %s WHERE %s IS NOT NULL GROUP BY %s' % (column, table, column, column)):
            out[item] = out.get(item, 0) + count
    return out


def check(c, item_id, archived=None, tables=None):
    """Revisión de un producto: si se puede eliminar y, si no, qué lo protege (con cantidades)."""
    row = c.execute('SELECT id,code,name,category,price_cents,available,COALESCE(archived_at,\'\') archived_at FROM catalog_items WHERE id=?', (item_id,)).fetchone()
    if not row:
        return None
    tables = tables or _tables(c)
    archived = archived_ids(c) if archived is None else archived
    reasons = []
    for table, column, label in PROTECTED:
        if table in tables:
            n = c.execute('SELECT COUNT(*) FROM %s WHERE %s=?' % (table, column), (item_id,)).fetchone()[0]
            if n:
                reasons.append({'label': label, 'count': n})
    # Datos propios que el sistema declara inmutables (p. ej., el historial de precios: «no se elimina») son historia que se conserva.
    for table, column in _immutable_owned(c, tables):
        n = c.execute('SELECT COUNT(*) FROM %s WHERE %s=?' % (table, column), (item_id,)).fetchone()[0]
        if n:
            reasons.append({'label': OWNED_LABELS.get(table, table), 'count': n})
    for table, column in _unknown_refs(c, tables):
        n = c.execute('SELECT COUNT(*) FROM "%s" WHERE "%s"=?' % (table, column), (item_id,)).fetchone()[0]
        if n:
            reasons.append({'label': 'otros registros (%s)' % table, 'count': n})
    inv = c.execute('SELECT id FROM inventory_items WHERE catalog_id=?', (item_id,)).fetchone() if 'inventory_items' in tables else None
    if inv:
        for table, label in INVENTORY_DETAIL:
            if table in tables:
                n = c.execute('SELECT COUNT(*) FROM %s WHERE %s=?' % (table, DETAIL_COLUMN.get(table, 'item_id')), (inv[0],)).fetchone()[0]
                if n:
                    reasons.append({'label': label, 'count': n, 'detail': True})
    orders = c.execute('SELECT COUNT(DISTINCT q.order_id) FROM quote_items i JOIN quotes q ON q.id=i.quote_id WHERE i.catalog_id=?', (item_id,)).fetchone()[0] if 'quote_items' in tables else 0
    active = bool(row['available'])
    blocked = [r for r in reasons if not r.get('detail')]
    state = 'activo' if active else 'protegido' if blocked else 'eliminable'
    message = ('Está activo: desactívalo antes de eliminarlo.' if active else
               'Tiene referencias que deben conservarse: ' + ', '.join('%s (%d)' % (r['label'], r['count']) for r in reasons) + '. Se puede conservar archivado.' if blocked else
               'Sin ventas, facturas, órdenes, presupuestos ni movimientos: se puede eliminar definitivamente.')
    return {'id': row['id'], 'code': row['code'] or '', 'name': row['name'], 'category': row['category'], 'price_cents': row['price_cents'], 'available': active,
            'archived': row['id'] in archived, 'archived_here': bool(row['archived_at']), 'state': state, 'deletable': state == 'eliminable',
            'reasons': reasons, 'orders': orders, 'message': message}


def _ids(raw):
    values = raw if isinstance(raw, list) else re.split(r'[,\s]+', str(raw or ''))
    ids = []
    for value in values:
        text = str(value).strip()
        if text.isdigit() and int(text) not in ids:
            ids.append(int(text))
    if not ids:
        raise CleanupError('Selecciona al menos un producto.')
    if len(ids) > MAX_IDS:
        raise CleanupError('Selecciona como máximo %d productos por operación.' % MAX_IDS)
    return ids


def review(c, raw_ids):
    """Resumen previo (solo lectura) de una selección: cada producto revisado individualmente."""
    ids, tables, archived = _ids(raw_ids), _tables(c), archived_ids(c)
    rows = [r for r in (check(c, i, archived, tables) for i in ids) if r]
    return {'rows': rows, 'deletable': sum(1 for r in rows if r['deletable']), 'protected': sum(1 for r in rows if r['state'] == 'protegido'),
            'active': sum(1 for r in rows if r['state'] == 'activo'), 'missing': len(ids) - len(rows)}


def _record(c, r, outcome, detail, batch, user, now):
    c.execute('INSERT INTO catalog_removals(item_id,code,name,category,price_cents,outcome,detail,batch,user_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
              (r['id'], r['code'], r['name'], r['category'], r['price_cents'], outcome, detail[:500], batch, user['id'], now.isoformat(timespec='seconds')))


def apply(c, data, user, now, audit):
    """Ejecuta la limpieza confirmada. action: 'delete' (elimina los que se pueden y, si archive_protected, archiva los protegidos),
    'archive' (conserva archivados) o 'restore' (vuelve al catálogo operativo, inactivo). Cada producto se revisa de nuevo aquí."""
    if user['role'] != 'administrador':
        raise CleanupError('Solo administración puede eliminar o archivar productos del catálogo.', 403)
    action = str(data.get('action', ''))
    if action not in ('delete', 'archive', 'restore'):
        raise CleanupError('Operación no válida.')
    if data.get('confirm') is not True:
        raise CleanupError('Confirma la operación.')
    ids, tables, archived = _ids(data.get('ids')), _tables(c), archived_ids(c)
    archive_protected = data.get('archive_protected') is True
    batch = 'LC-' + now.strftime('%Y%m%d%H%M%S')
    stamp = now.isoformat(timespec='seconds')
    result = {'deleted': [], 'archived': [], 'restored': [], 'kept': [], 'skipped': [], 'batch': batch}
    for item in ids:
        r = check(c, item, archived, tables)
        if not r:
            result['skipped'].append({'id': item, 'reason': 'Ya no existe.'})
            continue
        brief = {'id': r['id'], 'code': r['code'], 'name': r['name']}
        if action == 'restore':
            if not r['archived_here']:
                result['skipped'].append(dict(brief, reason='No está archivado desde el catálogo.'))
                continue
            c.execute("UPDATE catalog_items SET archived_at='',archived_by=NULL,updated_at=?,updated_by=? WHERE id=?", (stamp, user['id'], item))
            audit(c, user['id'], 'catalog_item_restored', item)
            result['restored'].append(brief)
            continue
        if r['available']:
            result['skipped'].append(dict(brief, reason='Está activo: no se elimina ni se archiva.'))
            continue
        if action == 'delete' and r['deletable']:
            frozen = set(_immutable_owned(c, tables))
            for table, column in OWNED:
                if table in tables and (table, column) not in frozen:
                    c.execute('DELETE FROM %s WHERE %s=?' % (table, column), (item,))
            c.execute('DELETE FROM catalog_items WHERE id=? AND available=0', (item,))
            _record(c, r, 'eliminado', 'Sin referencias que conservar.', batch, user, now)
            audit(c, user['id'], 'catalog_item_deleted', item)
            result['deleted'].append(brief)
        elif action == 'archive' or archive_protected:
            if r['archived']:
                result['kept'].append(dict(brief, reason='Ya estaba archivado.'))
                continue
            c.execute('UPDATE catalog_items SET archived_at=?,archived_by=?,updated_at=?,updated_by=? WHERE id=?', (stamp, user['id'], stamp, user['id'], item))
            detail = '; '.join('%s (%d)' % (x['label'], x['count']) for x in r['reasons']) or 'Archivado a pedido.'
            _record(c, r, 'archivado', detail, batch, user, now)
            audit(c, user['id'], 'catalog_item_archived', item)
            result['archived'].append(brief)
        else:
            result['kept'].append(dict(brief, reason=r['message']))
    return result


def history(c, limit=50):
    """Últimas eliminaciones y archivos (con quién y cuándo)."""
    return [dict(r) for r in c.execute("SELECT r.item_id,r.code,r.name,r.category,r.price_cents,r.outcome,r.detail,r.batch,r.created_at,COALESCE(u.name,'') actor "
                                       'FROM catalog_removals r LEFT JOIN users u ON u.id=r.user_id ORDER BY r.id DESC LIMIT ?', (limit,))]
