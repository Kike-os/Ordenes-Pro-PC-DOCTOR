"""Smart Catalog & Inventory Pro 3.0 (docs/SMART-CATALOG.md).

- Tipos y subcategorías administrables (catalog_types, catalog_subcategories). Cada tipo se apoya en una categoría base existente
  (servicio, repuesto, otro, licencia, seguridad), que sigue rigiendo inventario, facturación y licencias: nada de eso cambia.
- Ciclo de vida (catalog_profiles): los artículos creados desde un presupuesto nacen TEMPORALES; los creados desde Inventario o el
  Catálogo, PERMANENTES. Cualquier temporal puede conservarse como permanente o protegerse.
- Smart Catalog Cleanup: el plazo (30 días por defecto) empieza cuando el artículo ya no tiene presupuestos vigentes ni aprobados ni
  operaciones activas. Depurar es ARCHIVAR (sale del catálogo activo, nada se borra) y se puede restaurar. Nunca se tocan importes ni
  partidas de presupuestos, facturas, ventas u órdenes.
- Arranca en modo SIMULACIÓN: solo informa qué depuraría. La depuración real exige que administración la active expresamente.

Protección: solo puede depurarse un artículo temporal, sin protección, cuyas ÚNICAS referencias sean líneas de presupuestos que
nunca se aprobaron y ya terminaron (rechazados, cancelados o vencidos). Cualquier referencia a proformas, ventas, facturas, compras,
inventario, licencias, repuestos de órdenes, coberturas o una tabla desconocida lo protege. Los artículos antiguos solo se consideran
si su origen en un presupuesto puede verificarse; si no, se informan como «origen no verificable» y nunca se depuran.
"""
import json
import re
from datetime import datetime, timedelta

import catalog_cleanup

SETTINGS_KEY = 'smart_catalog_settings'
DEFAULTS = {'days': 30, 'mode': 'simulacion', 'quote_photos': False, 'last_run': '', 'last_result': {}}
CONFIRM_ACTIVATE = 'ACTIVAR DEPURACION'
NEAR_DAYS = 7
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_STORED_BYTES = 1_200_000
MAX_GALLERY = 8
PHOTO_TYPES = {'image/jpeg': (b'\xff\xd8\xff',), 'image/png': (b'\x89PNG\r\n\x1a\n',), 'image/webp': (b'RIFF',)}

# Tipos iniciales (se crean una sola vez; después se administran desde Configuración). fields: qué pide la ventana de alta.
TYPES = (
    ('servicio', 'Servicio técnico', 'servicio', 'wrench', ''),
    ('repuesto', 'Repuesto', 'repuesto', 'cpu', 'marca,modelo,foto'),
    ('producto', 'Producto', 'otro', 'box', 'marca,modelo,foto'),
    ('consumible', 'Consumible', 'otro', 'droplet', 'marca,modelo,foto'),
    ('impresion', 'Cabezal y repuesto de impresión', 'repuesto', 'printer', 'marca,modelo,foto'),
    ('accesorio', 'Accesorio', 'otro', 'mouse', 'marca,modelo,foto'),
    ('licencia', 'Licencia digital', 'licencia', 'key', 'marca'),
    ('componente', 'Componente electrónico', 'repuesto', 'chip', 'marca,modelo,foto'),
)
SUBCATEGORIES = {
    'consumible': ('Tintas originales', 'Tintas compatibles', 'Tóneres originales', 'Tóneres compatibles', 'Cartuchos', 'Cintas de impresión', 'Otros consumibles'),
    'impresion': ('Cabezales originales', 'Cabezales compatibles', 'Rodillos', 'Almohadillas', 'Cajas de mantenimiento', 'Bombas de tinta', 'Flex de impresión', 'Otros repuestos'),
    'repuesto': ('Pantallas', 'Teclados', 'Baterías', 'Bisagras', 'Carcasas', 'Ventiladores', 'Placas base', 'Otros repuestos'),
    'componente': ('Chips BIOS', 'MOSFET', 'Circuitos integrados', 'Resistencias', 'Condensadores', 'Conectores', 'Componentes SMD'),
}
# Tipo que se muestra para un artículo anterior según su categoría base (no se guarda: solo se deduce para mostrarlo).
BASE_TO_TYPE = {'servicio': 'servicio', 'repuesto': 'repuesto', 'otro': 'producto', 'licencia': 'licencia', 'seguridad': 'licencia'}
BASE_CATEGORIES = ('servicio', 'repuesto', 'otro', 'licencia', 'seguridad')
ICONS = ('wrench', 'cpu', 'box', 'droplet', 'printer', 'mouse', 'key', 'chip', 'shield', 'tag', 'cable', 'monitor', 'battery', 'tool')
# Referencias de un presupuesto: vigentes (impiden depurar y detienen el plazo), aprobadas (protegen siempre) y terminadas.
OPEN_QUOTE = ('borrador', 'enviado', 'modificacion')
APPROVED_QUOTE = ('aprobado', 'parcial')


class SmartCatalogError(Exception):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def installed(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_profiles'").fetchone())


def _stamp(now):
    return now.isoformat(timespec='seconds')


def _dt(value):
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _clean(text, limit):
    return re.sub(r'\s+', ' ', str(text or '')).strip()[:limit]


# ---- Configuración ------------------------------------------------------------------------------------------------------------------

def settings(c):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (SETTINGS_KEY,)).fetchone()
    try:
        stored = json.loads(row[0]) if row else {}
    except (TypeError, ValueError):
        stored = {}
    out = dict(DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS})
    out['days'] = max(7, min(365, int(out['days']) if str(out['days']).isdigit() else 30))
    out['mode'] = 'activa' if out['mode'] == 'activa' else 'simulacion'
    out['quote_photos'] = out['quote_photos'] is True
    return out


def _save_settings(c, value):
    c.execute('INSERT INTO system_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (SETTINGS_KEY, json.dumps(value, ensure_ascii=False)))


def update_settings(c, data, user, now):
    """Plazo de conservación, fotografías en presupuestos impresos y modo de depuración. Activar la depuración real exige escribir la
    frase de confirmación; volver a simulación siempre se permite."""
    if user['role'] != 'administrador':
        raise SmartCatalogError('Solo administración configura Smart Catalog.', 403)
    cfg = settings(c)
    if 'days' in data:
        days = str(data.get('days', '')).strip()
        if not days.isdigit() or not 7 <= int(days) <= 365:
            raise SmartCatalogError('El plazo debe estar entre 7 y 365 días.', fields={'days': 'Entre 7 y 365.'})
        cfg['days'] = int(days)
    if 'quote_photos' in data:
        cfg['quote_photos'] = data.get('quote_photos') is True
    if 'mode' in data:
        mode = str(data.get('mode'))
        if mode == 'activa' and cfg['mode'] != 'activa':
            if str(data.get('confirm', '')).strip().upper() != CONFIRM_ACTIVATE:
                raise SmartCatalogError('Para activar la depuración real escribe «%s».' % CONFIRM_ACTIVATE, fields={'confirm': 'Confirmación requerida.'})
        elif mode not in ('activa', 'simulacion'):
            raise SmartCatalogError('Modo no válido.')
        cfg['mode'] = mode
    _save_settings(c, cfg)
    return cfg


# ---- Tipos y subcategorías ----------------------------------------------------------------------------------------------------------

def ensure_types(c, now):
    """Crea los tipos y subcategorías iniciales la primera vez (no pisa los cambios hechos desde Configuración)."""
    if not installed(c) or c.execute('SELECT 1 FROM catalog_types LIMIT 1').fetchone():
        return
    stamp = _stamp(now)
    for position, (code, label, base, icon, fields) in enumerate(TYPES):
        c.execute('INSERT OR IGNORE INTO catalog_types(code,label,base_category,icon,fields,position,active,custom,created_at,updated_at) VALUES(?,?,?,?,?,?,1,0,?,?)',
                  (code, label, base, icon, fields, position, stamp, stamp))
        for n, name in enumerate(SUBCATEGORIES.get(code, ())):
            c.execute('INSERT OR IGNORE INTO catalog_subcategories(type_code,name,position,active,created_at,updated_at) VALUES(?,?,?,1,?,?)', (code, name, n, stamp, stamp))


def taxonomy(c, now, include_inactive=False):
    if not installed(c):
        return {'installed': False, 'types': []}
    ensure_types(c, now)
    where = '' if include_inactive else ' WHERE active=1'
    types = [dict(r) for r in c.execute('SELECT code,label,base_category,icon,fields,position,active,custom FROM catalog_types' + where + ' ORDER BY position,label')]
    subs = {}
    for r in c.execute('SELECT id,type_code,name,position,active FROM catalog_subcategories' + where + ' ORDER BY position,name'):
        subs.setdefault(r['type_code'], []).append(dict(r))
    for t in types:
        t['fields'] = [f for f in t['fields'].split(',') if f]
        t['subcategories'] = subs.get(t['code'], [])
    return {'installed': True, 'types': types, 'base_categories': BASE_CATEGORIES, 'icons': ICONS}


def save_type(c, data, user, now):
    """Alta o edición de un tipo desde Configuración. Los tipos iniciales conservan su categoría base."""
    if user['role'] != 'administrador':
        raise SmartCatalogError('Solo administración administra las clasificaciones.', 403)
    ensure_types(c, now)
    label, stamp = _clean(data.get('label'), 60), _stamp(now)
    if len(label) < 3:
        raise SmartCatalogError('Escribe el nombre del tipo.', fields={'label': 'Obligatorio.'})
    icon = str(data.get('icon') or 'tag')
    icon = icon if icon in ICONS else 'tag'
    fields = ','.join(f for f in ('marca', 'modelo', 'foto') if data.get(f) is True)
    code = str(data.get('code') or '')
    current = c.execute('SELECT * FROM catalog_types WHERE code=?', (code,)).fetchone() if code else None
    if current:
        active = 0 if data.get('active') is False else 1
        c.execute('UPDATE catalog_types SET label=?,icon=?,fields=?,active=?,updated_at=?,updated_by=? WHERE code=?', (label, icon, fields, active, stamp, user['id'], code))
        return code
    base = str(data.get('base_category') or '')
    if base not in BASE_CATEGORIES:
        raise SmartCatalogError('Elige la categoría base (define su tratamiento en inventario y facturación).', fields={'base_category': 'Obligatoria.'})
    code = re.sub(r'[^a-z0-9]+', '_', label.lower().translate(str.maketrans('áéíóúñü', 'aeiounu'))).strip('_')[:30] or 'tipo'
    if c.execute('SELECT 1 FROM catalog_types WHERE code=?', (code,)).fetchone():
        raise SmartCatalogError('Ya existe un tipo con ese nombre.', 409, {'label': 'Duplicado.'})
    position = (c.execute('SELECT COALESCE(MAX(position),0)+1 FROM catalog_types').fetchone()[0])
    c.execute('INSERT INTO catalog_types(code,label,base_category,icon,fields,position,active,custom,created_at,updated_at,updated_by) VALUES(?,?,?,?,?,?,1,1,?,?,?)',
              (code, label, base, icon, fields, position, stamp, stamp, user['id']))
    return code


def save_subcategory(c, data, user, now):
    if user['role'] != 'administrador':
        raise SmartCatalogError('Solo administración administra las clasificaciones.', 403)
    ensure_types(c, now)
    name, stamp = _clean(data.get('name'), 60), _stamp(now)
    if len(name) < 2:
        raise SmartCatalogError('Escribe el nombre de la subcategoría.', fields={'name': 'Obligatorio.'})
    sid = str(data.get('id') or '')
    if sid.isdigit():
        row = c.execute('SELECT type_code FROM catalog_subcategories WHERE id=?', (int(sid),)).fetchone()
        if not row:
            raise SmartCatalogError('La subcategoría ya no existe.', 404)
        if c.execute('SELECT 1 FROM catalog_subcategories WHERE type_code=? AND name=? AND id!=?', (row[0], name, int(sid))).fetchone():
            raise SmartCatalogError('Ya existe esa subcategoría.', 409, {'name': 'Duplicada.'})
        c.execute('UPDATE catalog_subcategories SET name=?,active=?,updated_at=?,updated_by=? WHERE id=?', (name, 0 if data.get('active') is False else 1, stamp, user['id'], int(sid)))
        return int(sid)
    type_code = str(data.get('type_code') or '')
    if not c.execute('SELECT 1 FROM catalog_types WHERE code=?', (type_code,)).fetchone():
        raise SmartCatalogError('Tipo no válido.', fields={'type_code': 'Tipo no válido.'})
    if c.execute('SELECT 1 FROM catalog_subcategories WHERE type_code=? AND name=?', (type_code, name)).fetchone():
        raise SmartCatalogError('Ya existe esa subcategoría.', 409, {'name': 'Duplicada.'})
    position = c.execute('SELECT COALESCE(MAX(position),0)+1 FROM catalog_subcategories WHERE type_code=?', (type_code,)).fetchone()[0]
    return c.execute('INSERT INTO catalog_subcategories(type_code,name,position,active,created_at,updated_at,updated_by) VALUES(?,?,?,1,?,?,?)',
                     (type_code, name, position, stamp, stamp, user['id'])).lastrowid


def resolve_type(c, data, now):
    """Del tipo elegido en la ventana: (código de tipo, categoría base, id de subcategoría). Sin tipo, se usa la categoría base enviada."""
    ensure_types(c, now)
    code = str(data.get('type') or '')
    if not code:
        return '', None, None
    row = c.execute('SELECT code,base_category,active FROM catalog_types WHERE code=?', (code,)).fetchone()
    if not row or not row['active']:
        raise SmartCatalogError('Elige un tipo válido.', fields={'type': 'Tipo no válido.'})
    sub = str(data.get('subcategory') or '')
    sub_id = None
    if sub:
        found = c.execute('SELECT id FROM catalog_subcategories WHERE id=? AND type_code=? AND active=1', (int(sub) if sub.isdigit() else -1, code)).fetchone()
        if not found:
            raise SmartCatalogError('La subcategoría no corresponde al tipo elegido.', fields={'subcategory': 'No corresponde.'})
        sub_id = found[0]
    return row['code'], row['base_category'], sub_id


# ---- Ciclo de vida --------------------------------------------------------------------------------------------------------------------

def record_creation(c, item_id, data, user, now, origin, type_code='', sub_id=None):
    """Perfil del artículo recién creado. Desde presupuestos nace temporal (salvo que se pida conservarlo); desde Inventario o el
    Catálogo, permanente (salvo que se pida temporal)."""
    if not installed(c):
        return
    default = 'temporal' if origin == 'presupuesto' else 'permanente'
    mode = data.get('mode') if data.get('mode') in ('temporal', 'permanente') else default
    quote = str(data.get('quote_id') or '')
    stamp = _stamp(now)
    c.execute('INSERT OR REPLACE INTO catalog_profiles(item_id,type_code,subcategory_id,model,mode,origin,origin_quote_id,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
              (item_id, type_code, sub_id, _clean(data.get('model'), 80), mode, origin if origin in ('presupuesto', 'inventario', 'catalogo') else 'catalogo',
               int(quote) if quote.isdigit() else None, user['id'], stamp, stamp))
    _event(c, item_id, 'creado', 'Registrado como %s desde %s.' % (mode, {'presupuesto': 'un presupuesto', 'inventario': 'Inventario'}.get(origin, 'el Catálogo')), user, now)


def update_profile(c, item_id, data, user, now, type_code=None, sub_id=None):
    """Edición del tipo, subcategoría y modelo de un artículo existente (crea el perfil si el artículo es anterior)."""
    if not installed(c):
        return
    stamp = _stamp(now)
    if not c.execute('SELECT 1 FROM catalog_profiles WHERE item_id=?', (item_id,)).fetchone():
        created = c.execute('SELECT created_at FROM catalog_items WHERE id=?', (item_id,)).fetchone()
        c.execute("INSERT INTO catalog_profiles(item_id,mode,origin,created_at,updated_at) VALUES(?,'permanente','desconocido',?,?)", (item_id, created[0] if created else stamp, stamp))
    if type_code is not None:
        c.execute('UPDATE catalog_profiles SET type_code=?,subcategory_id=?,updated_at=? WHERE item_id=?', (type_code, sub_id, stamp, item_id))
    if 'model' in data:
        c.execute('UPDATE catalog_profiles SET model=?,updated_at=? WHERE item_id=?', (_clean(data.get('model'), 80), stamp, item_id))


def _event(c, item_id, event, detail, user, now, simulated=False):
    c.execute('INSERT INTO catalog_cleanup_events(item_id,event,detail,simulated,actor_id,actor,created_at) VALUES(?,?,?,?,?,?,?)',
              (item_id, event, detail[:400], 1 if simulated else 0, user['id'] if user else None, user['name'] if user else 'Smart Catalog Cleanup', _stamp(now)))


def set_mode(c, item_id, data, user, now):
    """Conservar como permanente, volver a temporal, proteger o quitar la protección. Solo administración."""
    if user['role'] != 'administrador':
        raise SmartCatalogError('Solo administración cambia la conservación de un artículo.', 403)
    if not c.execute('SELECT 1 FROM catalog_items WHERE id=?', (item_id,)).fetchone():
        raise SmartCatalogError('El artículo ya no existe.', 404)
    update_profile(c, item_id, {}, user, now)
    action, stamp = str(data.get('action') or ''), _stamp(now)
    if action == 'permanente':
        c.execute("UPDATE catalog_profiles SET mode='permanente',updated_at=? WHERE item_id=?", (stamp, item_id))
        _event(c, item_id, 'permanente', 'Se conserva permanentemente.', user, now)
    elif action == 'temporal':
        c.execute("UPDATE catalog_profiles SET mode='temporal',updated_at=? WHERE item_id=?", (stamp, item_id))
        _event(c, item_id, 'temporal', 'Pasa a registro temporal: entra en la depuración si cumple las condiciones.', user, now)
    elif action in ('proteger', 'desproteger'):
        reason = _clean(data.get('reason'), 200)
        if action == 'proteger' and len(reason) < 5:
            raise SmartCatalogError('Indica el motivo de la protección.', fields={'reason': 'Obligatorio.'})
        on = action == 'proteger'
        c.execute('UPDATE catalog_profiles SET protected=?,protected_by=?,protected_at=?,protect_reason=?,updated_at=? WHERE item_id=?',
                  (1 if on else 0, user['id'] if on else None, stamp if on else '', reason if on else '', stamp, item_id))
        _event(c, item_id, 'protegido' if on else 'desprotegido', reason or 'Protección retirada.', user, now)
    else:
        raise SmartCatalogError('Acción no válida.')


def restore(c, item_id, user, now):
    """Devuelve al catálogo activo un artículo depurado (sin perder su historial). Queda protegido para no volver a depurarse solo."""
    if user['role'] != 'administrador':
        raise SmartCatalogError('Solo administración restaura artículos.', 403)
    row = c.execute('SELECT p.cleanup_state,i.archived_at FROM catalog_profiles p JOIN catalog_items i ON i.id=p.item_id WHERE p.item_id=?', (item_id,)).fetchone()
    if not row or row['cleanup_state'] != 'depurado':
        raise SmartCatalogError('El artículo no fue depurado por Smart Catalog.', 409)
    stamp = _stamp(now)
    c.execute("UPDATE catalog_items SET archived_at='',archived_by=NULL,updated_at=?,updated_by=? WHERE id=?", (stamp, user['id'], item_id))
    c.execute("UPDATE catalog_profiles SET cleanup_state='restaurado',restored_at=?,restored_by=?,protected=1,protected_by=?,protected_at=?,protect_reason=?,updated_at=? WHERE item_id=?",
              (stamp, user['id'], user['id'], stamp, 'Restaurado desde el historial', stamp, item_id))
    _event(c, item_id, 'restaurado', 'Restaurado al catálogo activo y protegido.', user, now)


# ---- Evaluación (solo lectura) -----------------------------------------------------------------------------------------------------

def _quote_refs(c, item_id, today):
    """Líneas de presupuesto del artículo: (vigentes, aprobadas, terminadas, fin más reciente, códigos)."""
    open_, approved, ended, last_end, codes = 0, 0, 0, '', []
    for r in c.execute('SELECT q.id,q.code,q.status,q.valid_until,q.created_at,q.updated_at,q.decided_at,COALESCE(q.deleted_at,\'\') deleted_at,i.status item_status '
                       'FROM quote_items i JOIN quotes q ON q.id=i.quote_id WHERE i.catalog_id=?', (item_id,)):
        codes.append(r['code'] or 'P%d' % r['id'])
        if r['status'] in APPROVED_QUOTE and r['item_status'] != 'rechazado' and not r['deleted_at']:
            approved += 1
            continue
        expired = r['status'] in OPEN_QUOTE and r['valid_until'] and r['valid_until'][:10] < today
        if r['status'] in OPEN_QUOTE and not expired and not r['deleted_at']:
            open_ += 1
            continue
        ended += 1
        end = r['valid_until'][:10] + 'T23:59:59' if expired else (r['decided_at'] or r['updated_at'] or r['created_at'])
        last_end = max(last_end, str(end))
    return open_, approved, ended, last_end, sorted(set(codes))


def _verified_quote_origin(c, item_id, created_at):
    """Para artículos anteriores sin perfil: el origen en un presupuesto se considera verificado si el artículo se creó mientras ese
    presupuesto estaba en preparación (entre su creación y su envío o decisión). Devuelve el id del presupuesto o None."""
    created = _dt(created_at)
    if not created:
        return None
    for r in c.execute('SELECT q.id,q.created_at,q.sent_at,q.decided_at,q.updated_at FROM quote_items i JOIN quotes q ON q.id=i.quote_id WHERE i.catalog_id=? ORDER BY q.id', (item_id,)):
        start, end = _dt(r['created_at']), _dt(r['sent_at'] or r['decided_at'] or r['updated_at'])
        if start and end and start - timedelta(minutes=2) <= created <= end + timedelta(minutes=2):
            return r['id']
    return None


def _base_names():
    import quotes
    return {name.lower() for name, *_ in quotes.INITIAL} | {name.lower() for name, *_ in quotes.ADDITIONS}


def _bulk_refs(c, tables):
    """Referencias que protegen, contadas con una consulta agrupada por tabla (y no por artículo): {artículo: [etiquetas]}."""
    out = {}
    pairs = [(t, col, label) for t, col, label in catalog_cleanup.PROTECTED if t != 'quote_items' and t in tables]
    pairs += [(t, col, 'otros registros (%s)' % t) for t, col in catalog_cleanup._unknown_refs(c, tables)]
    pairs += [(t, col, catalog_cleanup.OWNED_LABELS.get(t, t)) for t, col in catalog_cleanup._immutable_owned(c, tables)]
    for table, column, label in pairs:
        for item, count in c.execute('SELECT "%s",COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL GROUP BY "%s"' % (column, table, column, column)):
            if count:
                out.setdefault(item, []).append(label)
    return out


def _bulk_quotes(c, today):
    """Líneas de presupuesto de todos los artículos en una sola consulta: {artículo: (vigentes, aprobadas, terminadas, fin, códigos, filas)}."""
    found = {}
    for r in c.execute("SELECT i.catalog_id,q.id,q.code,q.status,q.valid_until,q.created_at,q.updated_at,q.sent_at,q.decided_at,COALESCE(q.deleted_at,'') deleted_at,i.status item_status "
                       "FROM quote_items i JOIN quotes q ON q.id=i.quote_id WHERE i.catalog_id IS NOT NULL ORDER BY q.id"):
        open_, approved, ended, last_end, codes, rows = found.get(r['catalog_id'], (0, 0, 0, '', [], []))
        rows.append(dict(r))
        codes = codes + [r['code'] or 'P%d' % r['id']]
        if r['status'] in APPROVED_QUOTE and r['item_status'] != 'rechazado' and not r['deleted_at']:
            approved += 1
        else:
            expired = r['status'] in OPEN_QUOTE and r['valid_until'] and r['valid_until'][:10] < today
            if r['status'] in OPEN_QUOTE and not expired and not r['deleted_at']:
                open_ += 1
            else:
                ended += 1
                last_end = max(last_end, str(r['valid_until'][:10] + 'T23:59:59' if expired else (r['decided_at'] or r['updated_at'] or r['created_at'])))
        found[r['catalog_id']] = (open_, approved, ended, last_end, codes, rows)
    return found


def _verified_from_rows(created_at, rows):
    created = _dt(created_at)
    if not created:
        return None
    for r in rows:
        start, end = _dt(r['created_at']), _dt(r['sent_at'] or r['decided_at'] or r['updated_at'])
        if start and end and start - timedelta(minutes=2) <= created <= end + timedelta(minutes=2):
            return r['id']
    return None


def evaluate(c, now, include_permanent=True, only=None):
    """Estado de cada artículo para el centro de control y la depuración. Solo lee, con consultas agrupadas (rápido también con la base
    en la nube). `only`: limitar a un artículo."""
    cfg = settings(c)
    today = now.date().isoformat()
    tables = catalog_cleanup._tables(c)
    archived = catalog_cleanup.archived_ids(c)
    profiles = {r['item_id']: dict(r) for r in c.execute('SELECT * FROM catalog_profiles')} if installed(c) else {}
    types = {r['code']: dict(r) for r in c.execute('SELECT code,label,icon,base_category FROM catalog_types')} if installed(c) else {}
    subs = {r['id']: r['name'] for r in c.execute('SELECT id,name FROM catalog_subcategories')} if installed(c) else {}
    refs = _bulk_refs(c, tables)
    quotes_by = _bulk_quotes(c, today) if 'quote_items' in tables else {}
    base_names = _base_names()
    rows = []
    sql = "SELECT id,code,name,category,brand,price_cents,available,created_at,updated_at,COALESCE(archived_at,'') archived_at FROM catalog_items"
    for item in c.execute(sql + (' WHERE id=?' if only else '') + ' ORDER BY id', (only,) if only else ()):
        prof = profiles.get(item['id'])
        open_q, approved_q, ended_q, last_end, codes, qrows = quotes_by.get(item['id'], (0, 0, 0, '', [], []))
        origin, mode, origin_quote = (prof['origin'], prof['mode'], prof['origin_quote_id']) if prof else ('', '', None)
        if not prof:
            # Artículo anterior: el origen se deduce con evidencia; sin evidencia, nunca se depura.
            if item['name'].lower() in base_names:
                origin, mode = 'catalogo_base', 'permanente'
            else:
                origin_quote = _verified_from_rows(item['created_at'], qrows)
                origin, mode = ('presupuesto', 'temporal') if origin_quote else ('desconocido', 'permanente')
        blockers = refs.get(item['id'], [])
        codes = sorted(set(codes))
        type_code = (prof or {}).get('type_code') or BASE_TO_TYPE.get(item['category'], 'producto')
        t = types.get(type_code, {})
        row = {'id': item['id'], 'code': item['code'] or '', 'name': item['name'], 'category': item['category'], 'brand': item['brand'] or '', 'price_cents': item['price_cents'],
               'type': type_code, 'type_label': t.get('label', ''), 'icon': t.get('icon', ''), 'subcategory': subs.get((prof or {}).get('subcategory_id'), ''),
               'model': (prof or {}).get('model', ''), 'created_at': item['created_at'], 'origin': origin, 'origin_quote_id': origin_quote, 'mode': mode,
               'profiled': bool(prof), 'protected': bool(prof and prof['protected']), 'protect_reason': (prof or {}).get('protect_reason', ''),
               'quotes': codes, 'open_quotes': open_q, 'approved_quotes': approved_q, 'ended_quotes': ended_q, 'blockers': blockers,
               'archived': item['id'] in archived, 'cleanup_state': (prof or {}).get('cleanup_state', ''), 'cleaned_at': (prof or {}).get('cleaned_at', ''),
               'start': '', 'due': '', 'days_left': None, 'percent': None, 'state': '', 'reason': ''}
        if row['cleanup_state'] == 'depurado' and row['archived']:
            row['state'], row['reason'] = 'depurado', (prof or {}).get('cleanup_reason', '')
        elif row['archived']:
            row['state'], row['reason'] = 'archivado', 'Archivado manualmente: fuera del alcance de la depuración automática.'
        elif mode != 'temporal':
            row['state'] = 'permanente'
            row['reason'] = {'desconocido': 'Origen no verificable: no se depura.', 'catalogo_base': 'Catálogo base de PC-DOCTOR.'}.get(origin, 'Registro permanente.')
        elif row['protected']:
            row['state'], row['reason'] = 'protegido', 'Protegido manualmente: ' + row['protect_reason']
        elif blockers:
            row['state'], row['reason'] = 'protegido', 'Tiene operaciones que deben conservarse: ' + ', '.join(blockers) + '.'
        elif approved_q:
            row['state'], row['reason'] = 'protegido', 'Forma parte de un presupuesto aprobado.'
        elif open_q:
            row['state'], row['reason'] = 'en_uso', 'Está en %d presupuesto%s vigente%s: el plazo está suspendido.' % (open_q, 's' if open_q > 1 else '', 's' if open_q > 1 else '')
        else:
            start = max(str((prof or {}).get('restored_at') or ''), str(item['created_at'] or ''), last_end)
            begin = _dt(start) or now
            if begin.tzinfo is None:
                begin = begin.replace(tzinfo=now.tzinfo)
            due = begin + timedelta(days=cfg['days'])
            left = (due - now).total_seconds() / 86400
            row.update(start=begin.isoformat(timespec='seconds'), due=due.isoformat(timespec='seconds'), days_left=round(left, 2),
                       percent=max(0.0, min(100.0, round(left * 100 / cfg['days'], 1))))
            why = 'presupuesto%s %s sin aprobar' % ('s' if len(codes) > 1 else '', ', '.join(codes)) if codes else 'sin presupuestos'
            if left <= 0:
                row['state'], row['reason'] = 'pendiente', 'Temporal %s, sin existencias ni operaciones; cumplió %d días.' % (why, cfg['days'])
            else:
                row['state'] = 'proximo' if left <= NEAR_DAYS else 'en_plazo'
                row['reason'] = 'Temporal %s; se depura en %d día%s si nadie lo vuelve a usar.' % (why, max(1, int(left + .999)), '' if int(left + .999) == 1 else 's')
        if include_permanent or row['state'] != 'permanente':
            rows.append(row)
    return rows


def overview(c, now):
    rows = evaluate(c, now)
    count = lambda *states: sum(1 for r in rows if r['state'] in states)
    kpis = {'permanentes': count('permanente'), 'temporales': sum(1 for r in rows if r['mode'] == 'temporal' and r['state'] not in ('depurado',)),
            'proximos': count('proximo'), 'pendientes': count('pendiente'), 'depurados': count('depurado'), 'protegidos': count('protegido'),
            'recuperables': count('depurado'), 'en_uso': count('en_uso'), 'sin_origen': sum(1 for r in rows if r['origin'] == 'desconocido')}
    cfg = settings(c)
    history = [dict(r) for r in c.execute('SELECT e.id,e.item_id,i.name,e.event,e.detail,e.simulated,e.actor,e.created_at FROM catalog_cleanup_events e '
                                          'LEFT JOIN catalog_items i ON i.id=e.item_id ORDER BY e.id DESC LIMIT 60')] if installed(c) else []
    return {'installed': installed(c), 'settings': {k: cfg[k] for k in ('days', 'mode', 'quote_photos', 'last_run', 'last_result')}, 'kpis': kpis, 'rows': rows,
            'history': history, 'near_days': NEAR_DAYS, 'confirm_text': CONFIRM_ACTIVATE, 'server_time': _stamp(now)}


def report(c, now):
    """Reporte de candidatos (simulación): nombre, categoría, creación, presupuesto relacionado, estado, antigüedad, existencias y motivo."""
    out = []
    for r in evaluate(c, now):
        if r['mode'] != 'temporal' and r['origin'] != 'desconocido':
            continue
        created = _dt(r['created_at'])
        age = (now - (created if created and created.tzinfo else (created.replace(tzinfo=now.tzinfo) if created else now))).days
        out.append({'id': r['id'], 'name': r['name'], 'type': r['type_label'] or r['category'], 'created_at': r['created_at'], 'quotes': r['quotes'],
                    'state': r['state'], 'age_days': age, 'stock': 'sin ficha de inventario' if 'ficha de inventario' not in r['blockers'] else 'con ficha de inventario',
                    'origin': r['origin'], 'reason': r['reason'], 'due': r['due']})
    order = {'pendiente': 0, 'proximo': 1, 'en_plazo': 2, 'en_uso': 3, 'protegido': 4, 'permanente': 5}
    return sorted(out, key=lambda r: (order.get(r['state'], 9), r['due'] or '9999'))


# ---- Ejecución (tarea programada del servidor o manual) -------------------------------------------------------------------------

def run(c, now, user=None, source='programada'):
    """Revisa todos los artículos. En simulación solo registra qué depuraría (un evento por artículo y día). En modo activo archiva los
    pendientes. Devuelve el resumen."""
    if not installed(c):
        return {'installed': False}
    ensure_types(c, now)
    cfg = settings(c)
    simulate = cfg['mode'] != 'activa'
    day = now.date().isoformat()
    done, would = [], []
    for row in evaluate(c, now, include_permanent=False):
        if row['state'] != 'pendiente':
            continue
        if simulate:
            would.append(row['id'])
            seen = c.execute("SELECT 1 FROM catalog_cleanup_events WHERE item_id=? AND event='simulacion' AND substr(created_at,1,10)=?", (row['id'], day)).fetchone()
            if not seen:
                _event(c, row['id'], 'simulacion', 'Se depuraría: ' + row['reason'], user, now, simulated=True)
            continue
        # Antes de archivar se vuelve a comprobar con la base actual (nada cambia si apareció una referencia nueva).
        again = next(iter(evaluate(c, now, include_permanent=False, only=row['id'])), None)
        if not again or again['state'] != 'pendiente':
            continue
        stamp = _stamp(now)
        c.execute("UPDATE catalog_items SET archived_at=?,archived_by=?,updated_at=? WHERE id=? AND COALESCE(archived_at,'')=''", (stamp, user['id'] if user else None, stamp, row['id']))
        if not c.execute('SELECT 1 FROM catalog_profiles WHERE item_id=?', (row['id'],)).fetchone():
            c.execute("INSERT INTO catalog_profiles(item_id,mode,origin,origin_quote_id,created_at,updated_at) VALUES(?,'temporal',?,?,?,?)",
                      (row['id'], row['origin'] or 'presupuesto', row['origin_quote_id'], row['created_at'] or stamp, stamp))
        c.execute("UPDATE catalog_profiles SET cleanup_state='depurado',cleaned_at=?,cleanup_reason=?,updated_at=? WHERE item_id=?", (stamp, row['reason'], stamp, row['id']))
        _event(c, row['id'], 'depurado', row['reason'], user, now)
        done.append(row['id'])
    result = {'at': _stamp(now), 'source': source, 'mode': cfg['mode'], 'would_clean': len(would), 'cleaned': len(done)}
    cfg.update(last_run=result['at'], last_result=result)
    _save_settings(c, cfg)
    return result


# ---- Fotografías ----------------------------------------------------------------------------------------------------------------

def validate_photo(mime, raw):
    """Tipo real del archivo (por su firma, no por el nombre) y tamaño."""
    if mime not in PHOTO_TYPES:
        raise SmartCatalogError('Formato no admitido: usa JPG, PNG o WEBP.', fields={'photo': 'Formato no admitido.'})
    if not raw or len(raw) > MAX_STORED_BYTES:
        raise SmartCatalogError('La fotografía supera el tamaño permitido después de optimizarla.', fields={'photo': 'Muy grande.'})
    if not any(raw.startswith(sig) for sig in PHOTO_TYPES[mime]) or (mime == 'image/webp' and raw[8:12] != b'WEBP'):
        raise SmartCatalogError('El archivo no es una imagen válida.', fields={'photo': 'Contenido no válido.'})


def gallery(c, item_id):
    if not installed(c):
        return []
    return [dict(r) for r in c.execute("SELECT id,position,mime,size,width,height,created_at FROM catalog_gallery WHERE item_id=? AND deleted_at='' ORDER BY position,id", (item_id,))]


def add_gallery(c, item_id, mime, raw, width, height, user, now):
    import base64
    validate_photo(mime, raw)
    if not c.execute('SELECT 1 FROM catalog_items WHERE id=?', (item_id,)).fetchone():
        raise SmartCatalogError('El artículo ya no existe.', 404)
    if c.execute("SELECT COUNT(*) FROM catalog_gallery WHERE item_id=? AND deleted_at=''", (item_id,)).fetchone()[0] >= MAX_GALLERY:
        raise SmartCatalogError('La galería admite hasta %d imágenes adicionales.' % MAX_GALLERY, 409)
    position = c.execute("SELECT COALESCE(MAX(position),0)+1 FROM catalog_gallery WHERE item_id=? AND deleted_at=''", (item_id,)).fetchone()[0]
    return c.execute('INSERT INTO catalog_gallery(item_id,position,mime,size,width,height,data,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                     (item_id, position, mime, len(raw), int(width or 0), int(height or 0), base64.b64encode(raw).decode(), user['id'], _stamp(now))).lastrowid


def remove_gallery(c, item_id, photo_id, user, now):
    found = c.execute("UPDATE catalog_gallery SET deleted_at=?,deleted_by=? WHERE id=? AND item_id=? AND deleted_at=''", (_stamp(now), user['id'], photo_id, item_id)).rowcount
    if not found:
        raise SmartCatalogError('La imagen ya no existe.', 404)


def gallery_photo(c, item_id, photo_id):
    import base64
    row = c.execute("SELECT mime,data FROM catalog_gallery WHERE id=? AND item_id=? AND deleted_at=''", (photo_id, item_id)).fetchone()
    return (row['mime'], base64.b64decode(row['data'])) if row else None


def duplicates(c, name, brand='', model='', exclude=None):
    """Coincidencias en el catálogo antes de crear un artículo: mismo nombre (sin mayúsculas, tildes ni espacios extra) o nombre muy
    parecido con la misma marca y modelo."""
    def fold(text):
        return re.sub(r'[^a-z0-9]+', ' ', str(text or '').lower().translate(str.maketrans('áéíóúñü', 'aeiounu'))).strip()
    target, words = fold(name), set(fold(name).split())
    if len(target) < 3:
        return []
    out = []
    for r in c.execute("SELECT id,code,name,brand,category,price_cents,COALESCE(archived_at,'') archived_at FROM catalog_items"):
        other = fold(r['name'])
        same = other == target
        close = not same and words and len(words & set(other.split())) >= max(2, int(len(words) * .8)) and (not brand or fold(brand) == fold(r['brand']))
        if (same or close) and r['id'] != exclude:
            out.append({'id': r['id'], 'code': r['code'] or '', 'name': r['name'], 'brand': r['brand'] or '', 'category': r['category'], 'price_cents': r['price_cents'],
                        'archived': bool(r['archived_at']), 'exact': same})
    return sorted(out, key=lambda r: (not r['exact'], r['name']))[:6]
