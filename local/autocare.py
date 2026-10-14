"""ADI AutoCare Pro: monitoreo, diagnóstico y recuperación segura de Órdenes Pro.

Reutiliza el motor de estabilidad (stability.py): las mismas verificaciones de solo lectura, las mismas tareas programadas de
Vercel y el mismo registro por versión. Este módulo añade:
- Registro de errores de ejecución (excepciones no controladas), clasificados por severidad, sin datos personales: solo la ruta
  (con los números sustituidos por «:id»), el tipo de error y el punto del código donde ocurrió.
- Historial técnico de actividades: incidencias detectadas y resueltas, recuperaciones automáticas y versiones verificadas.
- Avisos para el centro de notificaciones y el resumen del panel «ADI AutoCare Pro».

Límites deliberados (seguridad): no modifica datos de clientes, órdenes, presupuestos, autorizaciones ni registros financieros,
no borra información, no reinicia servicios ni cambia código. Las correcciones de código siguen el procedimiento de siempre
(rama de pruebas, batería completa, aprobación administrativa y publicación), y la reversión se hace desde Vercel.
"""
import json
import re
import traceback
from datetime import datetime, timedelta

import versioning

KEEP_EVENTS = 300
KEEP_ERRORS = 200
SEVERITY_ORDER = {'crítica': 0, 'alta': 1, 'media': 2, 'baja': 3}
DEFAULTS = {'incidents': True, 'recoveries': True, 'versions': True, 'min_severity': 'media'}
MODULES = (('/api/login', 'Autenticación'), ('/api/session', 'Autenticación'), ('/api/password', 'Autenticación'), ('/api/second-step', 'Autenticación'),
           ('/api/clients', 'Clientes'), ('/api/orders', 'Órdenes'), ('/api/order-status', 'Órdenes'), ('/api/tracking', 'Seguimiento'),
           ('/api/quotes', 'Presupuestos'), ('/presupuesto', 'Presupuestos'), ('/api/appointments', 'Agenda'), ('/api/public/appointments', 'Agenda'),
           ('/api/agenda', 'Agenda'), ('/citas', 'Agenda'), ('/api/mail', 'Mail Pro'), ('/api/adi', 'ADI'), ('/api/reports', 'Reportes'),
           ('/api/maintenance', 'Mantenimiento'), ('/api/system', 'Sistema'), ('/api/public', 'Servicios públicos'), ('/static', 'Interfaz'))


def _load(c, key, default):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (key,)).fetchone()
    try:
        return json.loads(row['value']) if row else default
    except (ValueError, TypeError):
        return default


def _save(c, key, value):
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))


def stamp(now):
    return now.isoformat(timespec='seconds')


def settings(c):
    saved = _load(c, 'autocare_settings', {})
    clean = {key: bool(saved.get(key, value)) for key, value in DEFAULTS.items() if key != 'min_severity'}
    clean['min_severity'] = saved.get('min_severity') if saved.get('min_severity') in SEVERITY_ORDER else DEFAULTS['min_severity']
    return clean


def save_settings(c, data):
    clean = {key: data.get(key) is True for key in ('incidents', 'recoveries', 'versions')}
    clean['min_severity'] = data.get('min_severity') if data.get('min_severity') in SEVERITY_ORDER else DEFAULTS['min_severity']
    _save(c, 'autocare_settings', clean)
    return clean


def module_of(path):
    return next((name for prefix, name in MODULES if path.startswith(prefix)), 'General')


def classify(method, path, error):
    """Severidad y causa probable de un error de ejecución.
    Crítica: datos, seguridad o disponibilidad · Alta: impide una operación importante · Media: afecta parte de una función · Baja: visual."""
    import sqlite3
    name = type(error).__name__
    module = module_of(path)
    if isinstance(error, (sqlite3.DatabaseError,)) or 'remote' in name.lower() or name in ('IntegrityError', 'OperationalError'):
        return 'crítica', 'Base de datos: la operación no se pudo leer o guardar (' + name + ').'
    if module == 'Autenticación':
        return 'crítica', 'El inicio de sesión o la seguridad de la cuenta falló (' + name + ').'
    if module == 'Interfaz':
        return 'baja', 'Un recurso de la interfaz no se pudo entregar (' + name + ').'
    if method == 'POST' and module in ('Clientes', 'Órdenes', 'Presupuestos', 'Agenda', 'Mail Pro'):
        return 'alta', 'No se pudo completar una operación de ' + module + ' (' + name + ').'
    if isinstance(error, (TimeoutError, ConnectionError)):
        return 'media', 'Conexión lenta o interrumpida con un servicio externo (' + name + ').'
    return 'media', 'Error al consultar ' + module + ' (' + name + ').'


def where(error):
    """Archivo y función del código propio donde ocurrió el error (sin valores ni datos)."""
    frames = [frame for frame in traceback.extract_tb(error.__traceback__) if '/local/' in frame.filename.replace('\\', '/') or frame.filename.endswith('.py')]
    frame = frames[-1] if frames else None
    return (frame.filename.replace('\\', '/').rsplit('/', 1)[-1] + ':' + str(frame.lineno) + ' · ' + frame.name) if frame else ''


def record_error(c, method, path, error, now):
    """Guarda un error de ejecución clasificado. Nunca guarda el cuerpo de la petición ni el mensaje (pueden contener datos)."""
    severity, cause = classify(method, path, error)
    try:
        version = versioning.load()['releases'][0]['version']
    except versioning.RegistryError:
        version = ''
    item = {'at': stamp(now), 'version': version, 'method': method, 'path': re.sub(r'/\d+', '/:id', path.split('?', 1)[0])[:120],
            'module': module_of(path), 'type': type(error).__name__, 'where': where(error)[:160], 'severity': severity, 'cause': cause}
    errors = _load(c, 'autocare_errors', [])
    errors.append(item)
    _save(c, 'autocare_errors', errors[-KEEP_ERRORS:])
    return item


def recent_errors(c, hours=24, now=None):
    if now is None:
        from reception import reception_now
        now = reception_now()
    since = stamp(now - timedelta(hours=hours))
    reviewed = _load(c, 'autocare_reviewed', '')
    return [item for item in _load(c, 'autocare_errors', []) if item['at'] >= since and item['at'] > reviewed]


def log(c, kind, severity, module, message, detail='', now=None, version=''):
    events = _load(c, 'autocare_events', [])
    if now is None:
        from reception import reception_now
        now = reception_now()
    events.append({'at': stamp(now), 'kind': kind, 'severity': severity, 'module': module, 'message': message,
                   'detail': detail[:300], 'version': version})
    _save(c, 'autocare_events', events[-KEEP_EVENTS:])


def after_run(c, entry, summary, previous_history, now):
    """Tras cada verificación: registra incidencias nuevas, las resueltas, las recuperaciones automáticas y la primera verificación de una versión."""
    version = entry['version']
    before = next((item for item in reversed(previous_history) if item['version'] == version), None)
    failed_before = {result['code'] for result in (before['results'] if before else []) if not result['ok']}
    for result in entry['results']:
        if not result['ok'] and result['code'] not in failed_before:
            log(c, 'incident', result.get('severity', 'media'), result['name'], 'ADI detectó una incidencia en «' + result['name'] + '».', result['detail'], now, version)
        elif result['ok'] and result['code'] in failed_before:
            log(c, 'resolved', result.get('severity', 'media'), result['name'], 'Incidencia resuelta en «' + result['name'] + '».', result['detail'], now, version)
        if result.get('recovered'):
            log(c, 'recovery', result.get('severity', 'media'), result['name'], 'ADI detectó un fallo temporal en «' + result['name'] + '». Recuperación automática completada.', result['detail'], now, version)
    if summary['runs'] == 1:
        ok = not entry['critical_failures'] and not entry['warnings']
        log(c, 'version', 'baja' if ok else 'alta', 'Versiones', ('Versión ' + version + ' instalada. Pruebas completadas correctamente (' + str(entry['passed']) + '/' + str(entry['total']) + ').') if ok
            else ('Versión ' + version + ' instalada con incidencias (' + str(entry['passed']) + '/' + str(entry['total']) + ').'), '', now, version)


def overview(c, now):
    """Resumen del panel: estado general, servicios, incidencias activas, recuperaciones, versiones e historial técnico."""
    import stability
    status = stability.status(c, now)
    history = stability._load(c, 'stability_runs', [])
    last = next((item for item in reversed(history) if item['version'] == status['version']), None)
    services = [{'code': r['code'], 'name': r['name'], 'severity': r.get('severity', 'crítica' if r['critical'] else 'media'), 'ok': r['ok'],
                 'detail': r['detail'], 'ms': r['ms'], 'recovered': r.get('recovered', False)} for r in (last['results'] if last else [])]
    active = [{'source': 'verificación', 'module': s['name'], 'severity': s['severity'], 'diagnosis': s['detail'], 'at': last['at'], 'version': last['version']}
              for s in services if not s['ok']]
    for error in recent_errors(c, 24, now):
        active.append({'source': 'ejecución', 'module': error['module'], 'severity': error['severity'], 'diagnosis': error['cause'] + (' En ' + error['where'] + '.' if error['where'] else ''),
                       'at': error['at'], 'version': error['version'], 'path': error['method'] + ' ' + error['path']})
    active.sort(key=lambda item: (SEVERITY_ORDER.get(item['severity'], 9), item['at']))
    worst = min((SEVERITY_ORDER.get(item['severity'], 9) for item in active), default=9)
    general = 'unverified' if not last else 'critical' if worst == 0 else 'degraded' if worst <= 2 else 'ok'
    events = _load(c, 'autocare_events', [])
    try:
        registry = versioning.load()
        releases = [{'version': item['version'], 'date': item.get('date', ''), 'summary': item.get('summary', '')} for item in registry['releases'][:8]]
        pending = sum(len(value) for value in registry.get('pending', {}).values()) if isinstance(registry.get('pending'), dict) else 0
    except versioning.RegistryError:
        releases, pending = [], 0
    public = _load(c, 'public_version_check', {}) or {}
    return {'general': general, 'stability': status, 'last_check': last['at'] if last else '', 'last_source': last.get('source', '') if last else '',
            'duration_ms': last.get('ms') if last else None, 'services': services, 'active': active[:30],
            'recoveries': [event for event in events if event['kind'] == 'recovery'][-10:][::-1],
            'resolved': [event for event in events if event['kind'] == 'resolved'][-10:][::-1],
            'events': events[-60:][::-1], 'releases': releases, 'pending_changes': pending,
            'update': {'state': public.get('state', ''), 'latest': public.get('latest', ''), 'checked_at': public.get('at', '')},
            'settings': settings(c), 'next_scheduled': status['next_scheduled']}


def notifications(c, now):
    """Avisos administrativos discretos, sin duplicados (cada uno con una clave estable)."""
    config, items = settings(c), []
    limit = SEVERITY_ORDER[config['min_severity']]
    since = stamp(now - timedelta(days=2))
    for event in _load(c, 'autocare_events', []):
        if event['at'] < since:
            continue
        key = 'autocare:' + event['kind'] + ':' + re.sub(r'[^A-Za-z0-9_.:-]', '', event['at'] + ':' + event['module'])[:60]
        if event['kind'] == 'incident' and config['incidents'] and SEVERITY_ORDER.get(event['severity'], 9) <= limit:
            items.append({'key': key, 'kind': 'error' if event['severity'] in ('crítica', 'alta') else 'warning', 'icon': 'alert', 'title': 'ADI AutoCare · Incidencia ' + event['severity'],
                          'detail': event['message'] + (' ' + event['detail'] if event['detail'] else ''), 'at': event['at'], 'href': '#system?autocare=1', 'group': 'event'})
        elif event['kind'] == 'recovery' and config['recoveries']:
            items.append({'key': key, 'kind': 'success', 'icon': 'check', 'title': 'ADI AutoCare · Recuperación automática', 'detail': event['message'], 'at': event['at'], 'href': '#system?autocare=1', 'group': 'event'})
        elif event['kind'] == 'version' and config['versions']:
            items.append({'key': key, 'kind': 'success' if event['severity'] == 'baja' else 'warning', 'icon': 'check', 'title': 'ADI AutoCare · Versión actualizada',
                          'detail': event['message'], 'at': event['at'], 'href': '#system?autocare=1', 'group': 'event'})
    errors = [error for error in recent_errors(c, 24, now) if SEVERITY_ORDER.get(error['severity'], 9) <= limit]
    if config['incidents'] and errors:
        worst = min(errors, key=lambda error: SEVERITY_ORDER.get(error['severity'], 9))
        items.append({'key': 'autocare:errors:' + str(len(errors)) + ':' + worst['at'], 'kind': 'error' if worst['severity'] in ('crítica', 'alta') else 'warning', 'icon': 'alert',
                      'title': 'ADI AutoCare · ' + ('1 error de ejecución' if len(errors) == 1 else str(len(errors)) + ' errores de ejecución') + ' en 24 h',
                      'detail': worst['cause'] + ' Módulo: ' + worst['module'] + '.', 'at': worst['at'], 'href': '#system?autocare=1', 'group': 'alert'})
    return items[-12:]


def mark_reviewed(c, now):
    """Administración revisó los errores de ejecución: dejan de contar como incidencias activas (el registro se conserva)."""
    _save(c, 'autocare_reviewed', stamp(now))
    log(c, 'review', 'baja', 'Errores de ejecución', 'Errores de ejecución revisados por administración.', '', now)
