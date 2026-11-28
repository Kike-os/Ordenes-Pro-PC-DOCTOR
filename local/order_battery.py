"""Private, revisioned battery assessment for a repair-order unit."""
import base64
import binascii
from decimal import Decimal
import hashlib
import re

from order_evidence import sniff

TYPES = frozenset(('portatil', 'gaming'))
STATES = ('pendiente', 'evaluada', 'no_evaluada')
MAX_IMAGE = 750_000
HISTORY_PAGE = 20

SUMMARY = "r.id,r.status,r.health_bp,r.created_at,COALESCE(u.name,'') actor"
FIELDS = ('status', 'health_bp', 'reason', 'notes', 'source', 'image_id')


class BatteryError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def installed(c):
    return c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                     "AND name IN ('order_battery_images','order_battery_revisions')").fetchone()[0] == 2


def _unit(c, oid):
    row = c.execute("SELECT COALESCE(NULLIF(d.kind,''),d.category) kind FROM orders o "
                    "JOIN devices d ON d.id=o.device_id WHERE o.id=?", (oid,)).fetchone()
    if not row or row['kind'] not in TYPES:
        raise BatteryError('El diagnóstico de batería solo está disponible para portátiles.', 404)


def _summary(row=None):
    if not row:
        return {'id': 0, 'status': 'pendiente', 'percent': None, 'created_at': '', 'actor': ''}
    return {'id': row['id'], 'status': row['status'],
            'percent': row['health_bp'] / 100 if row['health_bp'] is not None else None,
            'created_at': row['created_at'], 'actor': row['actor']}


def attach(c, units):
    eligible = [unit for unit in units if unit['type'] in TYPES]
    if not eligible:
        return
    ready = installed(c)
    for unit in eligible:
        unit['battery'] = dict(_summary(), available=ready)
    if not ready:
        return
    ids = tuple(unit['id'] for unit in eligible)
    sql = ("SELECT r.order_id," + SUMMARY + " FROM order_battery_revisions r "
           "LEFT JOIN users u ON u.id=r.created_by WHERE r.id IN "
           "(SELECT MAX(id) FROM order_battery_revisions WHERE order_id IN (" +
           ','.join('?' for _ in ids) + ") GROUP BY order_id)")
    latest = {row['order_id']: row for row in c.execute(sql, ids)}
    for unit in eligible:
        unit['battery'].update(_summary(latest.get(unit['id'])))


def _current(c, oid):
    return c.execute("SELECT " + SUMMARY + ",r.reason,r.notes,r.source,r.image_id "
                     "FROM order_battery_revisions r LEFT JOIN users u ON u.id=r.created_by "
                     "WHERE r.order_id=? ORDER BY r.id DESC LIMIT 1", (oid,)).fetchone()


def _detail(row=None):
    return dict(_summary(row), reason=row['reason'] if row else '', notes=row['notes'] if row else '',
                source=row['source'] if row else '', image_id=row['image_id'] if row else None)


def current_assessment(c, oid):
    """Return the current summary for an eligible unit with the migration installed."""
    try:
        _unit(c, oid)
    except BatteryError:
        return None
    if installed(c):
        return _summary(_current(c, oid))


def read(c, oid, before=None):
    _unit(c, oid)
    if not installed(c):
        return {'available': False, 'battery': _detail(), 'history': [], 'next_before': None}
    sql = ("SELECT " + SUMMARY + ",r.reason,r.notes,r.source,r.image_id,"
           "p.status previous_status,p.health_bp previous_health_bp,p.reason previous_reason,"
           "p.notes previous_notes,p.source previous_source,p.image_id previous_image_id "
           "FROM order_battery_revisions r LEFT JOIN users u ON u.id=r.created_by "
           "LEFT JOIN order_battery_revisions p ON p.id=r.previous_id AND p.order_id=r.order_id "
           "WHERE r.order_id=?")
    params = (oid,)
    if before:
        sql += ' AND r.id<?'
        params += (before,)
    rows = c.execute(sql + ' ORDER BY r.id DESC LIMIT ?', (*params, HISTORY_PAGE + 1)).fetchall()
    history = []
    for row in rows[:HISTORY_PAGE]:
        previous = {'status': row['previous_status'] or 'pendiente',
                    'percent': row['previous_health_bp'] / 100 if row['previous_health_bp'] is not None else None}
        previous.update({key: row['previous_'+key] for key in ('reason','notes','source','image_id')})
        history.append(dict(_detail(row), previous=previous))
    return {'available': True, 'battery': _detail(_current(c, oid)), 'history': history,
            'next_before': history[-1]['id'] if len(rows) > HISTORY_PAGE else None}


def _text(data, key, size):
    value = data.get(key, '')
    if not isinstance(value, str) or '\x00' in value or len(value.strip()) > size:
        raise BatteryError('Revisa el texto ingresado. Uno de los campos supera el límite permitido.')
    return value.strip()


def _image(c, oid, value):
    if not isinstance(value, str) or len(value) > ((MAX_IMAGE + 2) // 3) * 4:
        raise BatteryError('La fotografía supera el límite de 750 KB.')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise BatteryError('La fotografía no se pudo leer.') from error
    mime = sniff(raw)
    if len(raw) > MAX_IMAGE or mime not in ('image/jpeg', 'image/png', 'image/webp'):
        raise BatteryError('Adjunta una imagen JPG, PNG o WebP de hasta 750 KB.')
    digest = hashlib.sha256(raw).hexdigest()
    c.execute('INSERT INTO order_battery_images(order_id,sha256,mime,data) VALUES (?,?,?,?) '
              'ON CONFLICT(order_id,sha256) DO NOTHING', (oid, digest, mime, raw))
    return c.execute('SELECT id FROM order_battery_images WHERE order_id=? AND sha256=?', (oid, digest)).fetchone()[0]


def _basis_points(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,3}(?:[.,][0-9]{1,2})?', value):
        raise BatteryError('Ingresa un porcentaje entre 0 y 100 con hasta dos decimales.')
    points = int(Decimal(value.replace(',', '.')) * 100)
    if points > 10000:
        raise BatteryError('El porcentaje debe estar entre 0 y 100.')
    return points


def save(c, oid, data, user, now):
    _unit(c, oid)
    if not installed(c):
        raise BatteryError('Aplica la migración 133 para guardar diagnósticos de batería.', 503)
    current = _current(c, oid)
    if data.get('revision') != str(current['id'] if current else 0):
        raise BatteryError('El diagnóstico cambió. Vuelve a abrirlo para revisar la última versión.', 409)
    status = data.get('status')
    if status not in STATES:
        raise BatteryError('Selecciona un estado de evaluación.')
    health_bp = None
    if status == 'evaluada':
        percent, wear = data.get('percent', ''), data.get('wear', '')
        wear_bp = _basis_points(wear) if wear != '' else None
        health_bp = _basis_points(percent) if percent != '' or wear_bp is None else 10000 - wear_bp
        if wear_bp is not None and health_bp + wear_bp != 10000:
            raise BatteryError('La salud y el desgaste deben sumar 100 %.')
    reason, notes, source = (_text(data, key, size) for key, size in (('reason',300),('notes',1500),('source',200)))
    if status == 'no_evaluada' and not reason:
        raise BatteryError('Indica por qué no se pudo evaluar la batería.')
    image_id = current['image_id'] if current else None
    if data.get('image'):
        image_id = _image(c, oid, data['image'])
    elif data.get('remove_image') is True:
        image_id = None
    values = (status, health_bp, reason, notes, source, image_id)
    previous = tuple(current[key] for key in FIELDS) if current else ('pendiente', None, '', '', '', None)
    if not current or previous != values:
        c.execute('INSERT INTO order_battery_revisions(order_id,previous_id,status,health_bp,reason,notes,source,image_id,created_by,created_at) '
                  'VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (oid, current['id'] if current else None, *values, user['id'], now.isoformat(timespec='seconds')))
    return _detail(_current(c, oid))


def image(c, oid, image_id):
    _unit(c, oid)
    if installed(c):
        row = c.execute('SELECT mime,data FROM order_battery_images WHERE order_id=? AND id=?', (oid, image_id)).fetchone()
        if row:
            return row['mime'], bytes(row['data'])
    raise BatteryError('Fotografía no disponible.', 404)
