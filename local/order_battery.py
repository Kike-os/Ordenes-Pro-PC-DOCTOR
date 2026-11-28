"""Private, revisioned battery assessment for a repair-order unit."""
import base64
import binascii
from decimal import Decimal
import hashlib
import json
import re
from uuid import uuid4

import battery_diagnostics as diagnostics

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


def advanced_installed(c):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_battery_diagnostics'").fetchone() is not None


def _decode_advanced(row):
    return {'battery_key': row['battery_key'], **json.loads(row['payload'])} if row else {'battery_key': 'original'}


def _advanced(c, oid, revision_id):
    row = c.execute('SELECT battery_key,payload FROM order_battery_diagnostics WHERE order_id=? AND revision_id=?',
                    (oid, revision_id)).fetchone()
    return _decode_advanced(row)


def preview_report(c, oid, data):
    _unit(c, oid)
    if not advanced_installed(c):
        raise BatteryError('Aplica la migración 135 para importar informes.', 503)
    try:
        return diagnostics.parse_report(data)
    except ValueError as error:
        raise BatteryError(str(error)) from error


def _extended(c, oid, row, ready):
    result = _detail(row)
    if ready:
        result['advanced'] = _advanced(c, oid, result['id'])
    return result


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


def current_assessment(c, oid, *, trend=False):
    """Return the current summary for an eligible unit with the migration installed."""
    try:
        _unit(c, oid)
    except BatteryError:
        return None
    if installed(c):
        record = _current(c, oid)
        summary = _summary(record)
        if record and advanced_installed(c):
            summary['advanced'] = _advanced(c, oid, record['id'])
            if trend:
                summary['trend'] = _trend(c, oid, summary['advanced']['battery_key'])
        return summary


def _trend(c, oid, battery_key):
    rows = c.execute("SELECT r.health_bp,r.created_at FROM order_battery_revisions r "
                     "LEFT JOIN order_battery_diagnostics d ON d.revision_id=r.id AND d.order_id=r.order_id "
                     "WHERE r.order_id=? AND COALESCE(d.battery_key,'original')=? AND r.health_bp IS NOT NULL "
                     "ORDER BY r.id DESC LIMIT ?", (oid, battery_key, HISTORY_PAGE)).fetchall()
    if len(rows) < 2:
        return None
    return {'previous': rows[-1]['health_bp'] / 100, 'previous_date': rows[-1]['created_at'][:10],
            'latest': rows[0]['health_bp'] / 100, 'latest_date': rows[0]['created_at'][:10]}


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
    ready = advanced_installed(c)
    rows_on_page = rows[:HISTORY_PAGE]
    details = {}
    if ready and rows_on_page:
        marks = ','.join('?' for _ in rows_on_page)
        details = {item['revision_id']: item for item in c.execute(
            f'SELECT revision_id,battery_key,payload FROM order_battery_diagnostics WHERE order_id=? AND revision_id IN ({marks})',
            (oid, *(row['id'] for row in rows_on_page)))}
    history = []
    for row in rows_on_page:
        previous = {'status': row['previous_status'] or 'pendiente',
                    'percent': row['previous_health_bp'] / 100 if row['previous_health_bp'] is not None else None}
        previous.update({key: row['previous_'+key] for key in ('reason','notes','source','image_id')})
        entry = dict(_detail(row), previous=previous)
        if ready:
            entry['advanced'] = _decode_advanced(details.get(row['id']))
        history.append(entry)
    current = _extended(c, oid, _current(c, oid), ready)
    result = {'available': True, 'advanced_available': ready, 'battery': current, 'history': history,
              'next_before': history[-1]['id'] if len(rows) > HISTORY_PAGE else None}
    if ready and not before:
        from adi_order import battery_explanation
        current['trend'] = _trend(c, oid, current['advanced']['battery_key'])
        result['guidance'] = battery_explanation(current)['technical']
    return result


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
    if not c.in_transaction:
        c.execute('BEGIN IMMEDIATE')
    current = _current(c, oid)
    if data.get('revision') != str(current['id'] if current else 0):
        raise BatteryError('El diagnóstico cambió. Vuelve a abrirlo para revisar la última versión.', 409)
    status = data.get('status')
    if status not in STATES:
        raise BatteryError('Selecciona un estado de evaluación.')
    ready = advanced_installed(c)
    previous_advanced = _advanced(c, oid, current['id'] if current else 0) if ready else {}
    advanced = dict(previous_advanced)
    replacing = data.get('replace') is True
    if ('advanced' in data or replacing or data.get('report')) and not ready:
        raise BatteryError('Aplica la migración 135 desde Sistema → Migraciones.', 503)
    if 'advanced' in data or replacing:
        try:
            advanced = diagnostics.normalize(data.get('advanced', {}), {} if replacing else previous_advanced)
            advanced.update({key: previous_advanced[key] for key in ('installation', 'report') if key in previous_advanced and not replacing})
            advanced['battery_key'] = previous_advanced['battery_key']
            if replacing:
                if not any(advanced['identity'].get(k) for k in ('model', 'part', 'serial')):
                    raise ValueError('Identifica la batería instalada por modelo, parte o serie.')
                old_serial = previous_advanced.get('identity', {}).get('serial', '')
                if old_serial and advanced['identity']['serial'].casefold() == old_serial.casefold():
                    raise ValueError('La serie coincide con la batería activa.')
                advanced['battery_key'] = uuid4().hex
                prior = current['health_bp'] if current else None
                advanced['installation'] = {'date': now.date().isoformat(),
                                            'before_bp': prior, 'warranty': diagnostics.clean(data.get('warranty', ''), 300)}
                status = 'pendiente'
                advanced['method'] = 'manual'
                advanced['readings'] = {}
            if data.get('report') is not None:
                if replacing:
                    raise ValueError('Registra el reemplazo antes de asociar un informe nuevo.')
                raw = diagnostics.mapping(data['report'])
                report = diagnostics.parse_report(raw)
                index = raw.get('index')
                if type(index) is not int or not 0 <= index < len(report['batteries']):
                    raise ValueError('Selecciona una batería del informe.')
                selected = report['batteries'][index]
                detected_serial = selected['identity'].get('serial', '')
                entered_serial = advanced['identity'].get('serial') or previous_advanced.get('identity', {}).get('serial', '')
                if detected_serial and entered_serial and detected_serial.casefold() != entered_serial.casefold():
                    raise ValueError('La serie del informe difiere de la batería identificada.')
                advanced['report'] = {'name': report['name'], 'size': report['size'], 'date': report['date'],
                                      'index': index, 'history': report['history'][-120:]}
            elif data.get('remove_report') is True:
                advanced.pop('report', None)
        except ValueError as error:
            raise BatteryError(str(error)) from error
    health_bp = None
    if status == 'evaluada' and advanced.get('method') == 'capacity':
        try:
            health_bp, warning = diagnostics.capacity_health(advanced['readings'])
        except ValueError as error:
            raise BatteryError(str(error)) from error
        review_changed = advanced['readings'] != previous_advanced.get('readings') or not previous_advanced.get('capacity_warning')
        if warning and review_changed and data.get('acknowledge_capacity') is not True:
            raise BatteryError('La carga completa supera el diseño. Revisa los valores y confirma la lectura.')
        advanced['capacity_warning'] = warning
    elif status == 'evaluada':
        advanced.pop('capacity_warning', None)
        percent, wear = data.get('percent', ''), data.get('wear', '')
        wear_bp = _basis_points(wear) if wear != '' else None
        health_bp = _basis_points(percent) if percent != '' or wear_bp is None else 10000 - wear_bp
        if wear_bp is not None and health_bp + wear_bp != 10000:
            raise BatteryError('La salud y el desgaste deben sumar 100 %.')
    reason, notes, source = (_text(data, key, size) for key, size in (('reason',300),('notes',1500),('source',200)))
    if status == 'no_evaluada' and not reason:
        raise BatteryError('Indica por qué no se pudo evaluar la batería.')
    image_id = current['image_id'] if current and not replacing else None
    if data.get('image') and not replacing:
        image_id = _image(c, oid, data['image'])
    elif data.get('remove_image') is True:
        image_id = None
    values = (status, health_bp, reason, notes, source, image_id)
    previous = tuple(current[key] for key in FIELDS) if current else ('pendiente', None, '', '', '', None)
    if replacing:
        reason, notes, source = '', '', ''
        values = (status, health_bp, reason, notes, source, None)
    if not current or previous != values or advanced != previous_advanced:
        c.execute('INSERT INTO order_battery_revisions(order_id,previous_id,status,health_bp,reason,notes,source,image_id,created_by,created_at) '
                  'VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (oid, current['id'] if current else None, *values, user['id'], now.isoformat(timespec='seconds')))
        if ready and len(advanced) > 1:
            revision = _current(c, oid)['id']
            payload = {key: value for key, value in advanced.items() if key != 'battery_key'}
            c.execute('INSERT INTO order_battery_diagnostics(revision_id,order_id,battery_key,payload) VALUES (?,?,?,?)',
                      (revision, oid, advanced['battery_key'], json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    return _extended(c, oid, _current(c, oid), ready)


def image(c, oid, image_id):
    _unit(c, oid)
    if installed(c):
        row = c.execute('SELECT mime,data FROM order_battery_images WHERE order_id=? AND id=?', (oid, image_id)).fetchone()
        if row:
            return row['mime'], bytes(row['data'])
    raise BatteryError('Fotografía no disponible.', 404)


def customer_assessment(c, oid):
    record = current_assessment(c, oid)
    if not record:
        return []
    advanced = record.get('advanced', {})
    share = advanced.get('share', [])
    if not share:
        return []
    from adi_order import battery_explanation
    rows = [('Diagnóstico', {'pendiente': 'Pendiente de evaluación', 'evaluada': 'Evaluada',
                             'no_evaluada': 'No evaluada'}[record['status']])]
    percent = record['percent']
    if 'health' in share and percent is not None:
        rows.extend((('Salud', f'{percent:g} %'), ('Desgaste', f'{round(100-percent, 2):g} %'),
                     ('Fecha de evaluación', record['created_at'][:10])))
    if 'safety' in share and advanced.get('hazards'):
        rows.append(('Advertencia de seguridad', 'No utilice ni cargue la batería.'))
    for key, title in PUBLIC_MEASUREMENTS.items():
        reading = advanced.get('readings', {}).get(key, {})
        if key in share and reading.get('value'):
            rows.append((title, (reading['value'] + ' ' + reading['unit']).strip()))
    if 'replacement' in share and advanced.get('installation'):
        install = advanced['installation']
        rows.append(('Reemplazo', 'Batería instalada el ' + install['date'] +
                     (' · Pendiente de evaluación' if percent is None else '')))
        if install['warranty']:
            rows.append(('Garantía', install['warranty']))
        if install['before_bp'] is not None and percent is not None:
            before = install['before_bp'] / 100
            rows.append(('Antes y después', f'{before:g} % → {percent:g} % ({round(percent-before, 2):+g} pp)'))
    if 'explanation' in share:
        rows.append(('Explicación técnica', battery_explanation(record)['customer']))
    return rows


PUBLIC_MEASUREMENTS = {
    'cycles': 'Ciclos de carga', 'charge': 'Carga actual', 'temperature': 'Temperatura registrada',
    'battery_nominal': 'Voltaje nominal de batería', 'battery_measured': 'Voltaje registrado de batería',
    'charger_nominal': 'Voltaje nominal del cargador', 'charger_measured': 'Voltaje registrado del cargador',
    'current': 'Corriente de carga', 'design': 'Capacidad de diseño',
    'full': 'Capacidad de carga completa', 'remaining': 'Capacidad restante',
}
