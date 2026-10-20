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
KEEP_INCIDENTS = 200
SEVERITY_ORDER = {'crítica': 0, 'alta': 1, 'media': 2, 'baja': 3}
# Avisos configurables (cada uno una sola vez por evento). Los nombres antiguos (incidents, recoveries, versions) se respetan al leer.
DEFAULTS = {'critical': True, 'unavailable': True, 'recurrent': True, 'connection': True, 'scheduled': False, 'updates': True, 'min_severity': 'media'}
NOTICE_KEYS = ('critical', 'unavailable', 'recurrent', 'connection', 'scheduled', 'updates')
INCIDENT_STATES = {'activa': 'Activa', 'en_revision': 'En revisión', 'resuelta': 'Resuelta'}
RECURRENT = 3
# Posible causa y acción recomendada por servicio verificado. ADI solo sugiere: nunca ejecuta reparaciones ni modifica datos.
GUIDE = {
 'database': ('La base de datos no responde, responde lento o hay migraciones sin aplicar.', 'Revisar el estado de la base de datos en la nube (Turso) y aplicar las migraciones pendientes con respaldo previo.'),
 'auth': ('El cifrado de contraseñas, las cuentas de administración o las sesiones no responden como se espera.', 'Comprobar que existe una cuenta de administración activa y revisar la configuración de seguridad.'),
 'clients': ('El registro de clientes no se puede consultar o le faltan campos.', 'Revisar las migraciones del registro de clientes y los errores de ejecución del módulo.'),
 'orders': ('El seguimiento de órdenes, el ticket PDF o el contador de números de orden fallan.', 'Revisar la orden más reciente y el contador de órdenes; no registrar órdenes nuevas hasta corregirlo si hay riesgo de números repetidos.'),
 'quotes': ('El presupuesto más reciente no se puede generar en PDF.', 'Abrir el presupuesto más reciente y revisar sus partidas; revisar los errores de ejecución de Presupuestos.'),
 'licenses': ('El cifrado de credenciales falla o hay licencias con datos inconsistentes.', 'Revisar la clave LICENSE_ENCRYPTION_KEY y usar «Revisar inconsistencias» en Licencias (corrección manual autorizada).'),
 'sales': ('El estado de pago de alguna venta no coincide con sus pagos confirmados, o los saldos no se pueden calcular.', 'Abrir la venta indicada y revisar sus pagos; registrar o anular pagos solo con autorización administrativa.'),
 'agenda': ('La agenda no tiene servicios o no puede calcular la disponibilidad.', 'Revisar Configuración → Agenda (servicios, horarios y feriados).'),
 'mail': ('El correo del sistema no está configurado o el buzón no responde.', 'Revisar la configuración de Mail Pro y las credenciales del buzón en Vercel.'),
 'notifications': ('El centro de notificaciones falla o hay avisos que no se pudieron enviar.', 'Revisar Licencias → Notificaciones de renovación y el servicio de correo.'),
 'integrations': ('Falta una variable de configuración necesaria en el servidor.', 'Definir la variable indicada en Vercel → Settings → Environment Variables y volver a desplegar.'),
 'internal': ('Falta un archivo del despliegue o las tareas programadas no se ejecutan.', 'Revisar el último despliegue en Vercel y las tareas programadas (Cron Jobs).'),
 'errors': ('Se produjeron errores de ejecución recientes.', 'Revisar las incidencias de ejecución (ruta y punto del código) y preparar la corrección en una rama de pruebas.'),
}
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
    legacy = {'critical': saved.get('incidents'), 'unavailable': saved.get('incidents'), 'recurrent': saved.get('incidents'), 'connection': saved.get('recoveries'), 'updates': saved.get('versions')}
    clean = {key: bool(saved[key]) if key in saved else (bool(legacy[key]) if legacy.get(key) is not None else DEFAULTS[key]) for key in NOTICE_KEYS}
    clean['min_severity'] = saved.get('min_severity') if saved.get('min_severity') in SEVERITY_ORDER else DEFAULTS['min_severity']
    return clean


def save_settings(c, data):
    clean = {key: data.get(key) is True for key in NOTICE_KEYS}
    clean['min_severity'] = data.get('min_severity') if data.get('min_severity') in SEVERITY_ORDER else DEFAULTS['min_severity']
    _save(c, 'autocare_settings', clean)
    return clean


# ---- Incidencias: código, servicio, descripción, gravedad, fecha, causa, acción recomendada y estado de resolución ----
def _incident_code(c, now):
    counter = _load(c, 'autocare_incident_seq', {})
    day = now.strftime('%Y%m%d')
    number = counter.get(day, 0) + 1
    _save(c, 'autocare_incident_seq', {day: number})
    return 'INC-' + day + '-' + str(number).zfill(3)


def open_incident(c, key, service, severity, description, cause, action, now, source):
    """Abre o actualiza una incidencia (sin duplicados: una por servicio o por tipo de error). Una resuelta que vuelve se reabre."""
    items = _load(c, 'autocare_incidents', [])
    found = next((item for item in reversed(items) if item['key'] == key and item['status'] != 'resuelta'), None)
    if found:
        found.update(last_at=stamp(now), count=found['count'] + 1, description=description[:300], severity=severity)
    else:
        previous = next((item for item in reversed(items) if item['key'] == key), None)
        found = {'code': _incident_code(c, now), 'key': key, 'service': service, 'severity': severity, 'description': description[:300], 'cause': cause[:300], 'action': action[:300],
                 'source': source, 'first_at': stamp(now), 'last_at': stamp(now), 'count': 1, 'status': 'activa', 'history': [], 'reopened': bool(previous)}
        items.append(found)
    _save(c, 'autocare_incidents', items[-KEEP_INCIDENTS:])
    return found


def close_incident(c, key, now, by, note):
    items = _load(c, 'autocare_incidents', [])
    for item in items:
        if item['key'] == key and item['status'] != 'resuelta':
            item.update(status='resuelta', resolved_at=stamp(now), resolved_by=by)
            item['history'] = (item.get('history', []) + [{'at': stamp(now), 'by': by, 'status': 'resuelta', 'note': note}])[-20:]
    _save(c, 'autocare_incidents', items)


def update_incident(c, code, status, note, user_name, now):
    """Cambio de estado hecho por administración (en revisión, resuelta o reabierta), con nota, persona y hora."""
    if status not in INCIDENT_STATES:
        raise ValueError('Estado no válido.')
    items = _load(c, 'autocare_incidents', [])
    item = next((entry for entry in items if entry['code'] == code), None)
    if not item:
        raise LookupError('Incidencia no disponible.')
    note = re.sub(r'\s+', ' ', str(note or '')).strip()[:300]
    if status == 'resuelta' and len(note) < 5:
        raise ValueError('Indica cómo se resolvió la incidencia.')
    item['status'] = status
    if status == 'resuelta':
        item.update(resolved_at=stamp(now), resolved_by=user_name)
    item['history'] = (item.get('history', []) + [{'at': stamp(now), 'by': user_name, 'status': status, 'note': note}])[-20:]
    _save(c, 'autocare_incidents', items)
    log(c, 'incident_update', item['severity'], item['service'], 'Incidencia ' + code + ' marcada como «' + INCIDENT_STATES[status] + '» por ' + user_name + '.', note, now)
    return item


def incidents(c):
    return _load(c, 'autocare_incidents', [])


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
    open_incident(c, 'error:' + item['module'] + ':' + item['type'] + ':' + item['where'].split(' · ')[0], item['module'], severity,
                  'Error de ejecución en ' + item['method'] + ' ' + item['path'] + (' (' + item['where'] + ')' if item['where'] else '') + '.', cause,
                  'Revisar el punto del código indicado y preparar la corrección en una rama de pruebas; no se ejecuta ninguna reparación automática.', now, 'ejecución')
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
        status = result.get('status', 'ok' if result['ok'] else 'error')
        cause, action = GUIDE.get(result['code'], ('Fallo en la verificación del servicio.', 'Revisar el detalle de la verificación.'))
        if status in ('error', 'warning'):
            open_incident(c, 'check:' + result['code'], result['name'], result.get('severity', 'media') if status == 'error' else 'baja', result['detail'], cause, action, now, 'verificación')
        elif status == 'ok':
            close_incident(c, 'check:' + result['code'], now, 'Verificación ' + entry.get('source', ''), 'La verificación volvió a ser correcta: ' + result['detail'])
        if not result['ok'] and result['code'] not in failed_before:
            log(c, 'incident', result.get('severity', 'media'), result['name'], 'ADI detectó una incidencia en «' + result['name'] + '».', result['detail'], now, version)
        elif result['ok'] and result['code'] in failed_before:
            log(c, 'resolved', result.get('severity', 'media'), result['name'], 'Incidencia resuelta en «' + result['name'] + '».', result['detail'], now, version)
        if result.get('recovered'):
            log(c, 'recovery', result.get('severity', 'media'), result['name'], 'ADI detectó un fallo temporal en «' + result['name'] + '». Recuperación automática completada.', result['detail'], now, version)
    if entry.get('source') == 'programada':
        counts = entry.get('counts') or {}
        log(c, 'scheduled', 'baja' if not entry['critical_failures'] and not entry['warnings'] else 'alta', 'Diagnóstico programado',
            'Diagnóstico programado: ' + str(counts.get('ok', entry['passed'])) + ' correctas, ' + str(counts.get('warning', 0)) + ' advertencias, ' + str(counts.get('error', entry['total'] - entry['passed'])) + ' errores y ' + str(counts.get('not_checked', 0)) + ' sin comprobar.', '', now, version)
    if summary['runs'] == 1:
        ok = not entry['critical_failures'] and not entry['warnings']
        log(c, 'version', 'baja' if ok else 'alta', 'Versiones', ('Versión ' + version + ' instalada. Pruebas completadas correctamente (' + str(entry['passed']) + '/' + str(entry['total']) + ').') if ok
            else ('Versión ' + version + ' instalada con incidencias (' + str(entry['passed']) + '/' + str(entry['total']) + ').'), '', now, version)


def _explain(status):
    """Por qué la versión está en su estado actual, en lenguaje claro y con datos reales."""
    state = status['state']
    if state == 'unverified':
        return 'Todavía no se ha completado ninguna verificación de esta versión. La primera se ejecuta en la próxima tarea programada o al pulsar «Ejecutar diagnóstico».'
    if state == 'verifying':
        return 'Hay una verificación en curso.'
    if state == 'attention':
        return 'La última verificación detectó un fallo crítico. El período de seguimiento vuelve a empezar desde la siguiente verificación correcta.'
    if state == 'stable':
        return 'Versión estable: superó al menos ' + str(status['min_passes']) + ' verificaciones correctas durante ' + str(status['observation_hours']) + ' h sin fallos.'
    parts = []
    if status['missing_passes']:
        parts.append('faltan ' + str(status['missing_passes']) + ' verificación(es) correcta(s) de las ' + str(status['min_passes']) + ' necesarias')
    if status['remaining_hours']:
        parts.append('quedan ' + (str(status['remaining_hours']).replace('.', ',')) + ' h del período de ' + str(status['observation_hours']) + ' h')
    if not status['clean']:
        parts.append('la última verificación tuvo un fallo no crítico que debe corregirse')
    return 'En observación: todas las verificaciones críticas son correctas, pero ' + (', '.join(parts) if parts else 'el período de seguimiento aún no termina') + '.'


def overview(c, now):
    """Resumen del panel: indicadores, servicios, incidencias, recuperaciones, historial técnico, versiones y configuración de avisos."""
    import stability
    status = stability.status(c, now)
    history = stability._load(c, 'stability_runs', [])
    last = next((item for item in reversed(history) if item['version'] == status['version']), None)
    services = [{'code': r['code'], 'name': r['name'], 'severity': r.get('severity', 'crítica' if r['critical'] else 'media'), 'ok': r['ok'], 'status': r.get('status', 'ok' if r['ok'] else 'error'),
                 'detail': r['detail'], 'ms': r['ms'], 'recovered': r.get('recovered', False)} for r in (last['results'] if last else [])]
    counts = {key: sum(1 for s in services if s['status'] == key) for key in stability.STATUS_LABELS}
    items = incidents(c)
    open_items = [item for item in items if item['status'] != 'resuelta']
    worst = min((SEVERITY_ORDER.get(item['severity'], 9) for item in open_items), default=9)
    general = 'unverified' if not last else 'critical' if worst == 0 or counts['error'] and any(s['status'] == 'error' and s['severity'] == 'crítica' for s in services) else 'degraded' if open_items or counts['error'] or counts['warning'] else 'ok'
    events = _load(c, 'autocare_events', [])
    try:
        registry = versioning.load()
        releases = [{'version': item['version'], 'date': item.get('date', ''), 'summary': item.get('summary', ''), 'changes': item.get('changes', {})} for item in registry['releases'][:10]]
        unreleased = registry.get('unreleased') or {}
        pending = sum(len(value) for value in unreleased.values()) if isinstance(unreleased, dict) else len(unreleased)
    except versioning.RegistryError:
        releases, pending = [], 0
    public = _load(c, 'public_version_check', {}) or {}
    first = next((item for item in history if item['version'] == status['version']), None)
    runs = [{'at': item['at'], 'source': item.get('source', ''), 'by': item.get('by', ''), 'version': item['version'], 'ms': item.get('ms'),
             'counts': item.get('counts') or {'ok': item['passed'], 'warning': 0, 'error': item['total'] - item['passed'], 'not_checked': 0}, 'total': item['total'],
             'results': [{'code': r['code'], 'name': r['name'], 'severity': r.get('severity', ''), 'status': r.get('status', 'ok' if r['ok'] else 'error'), 'detail': r['detail'], 'recovered': r.get('recovered', False)} for r in item['results']]}
            for item in reversed(history)]
    recoveries = [event for event in events if event['kind'] == 'recovery']
    return {'general': general, 'stability': status, 'explanation': _explain(status), 'last_check': last['at'] if last else '', 'last_source': last.get('source', '') if last else '',
            'last_by': last.get('by', '') if last else '', 'duration_ms': last.get('ms') if last else None, 'services': services, 'counts': counts, 'status_labels': stability.STATUS_LABELS,
            'incidents': sorted(items, key=lambda item: (item['status'] == 'resuelta', SEVERITY_ORDER.get(item['severity'], 9), item['last_at']), reverse=False)[:120],
            'active': [{'code': item['code'], 'module': item['service'], 'severity': item['severity'], 'diagnosis': item['description'], 'at': item['last_at'], 'source': item['source']} for item in open_items],
            'incident_states': INCIDENT_STATES, 'recoveries_total': len(recoveries), 'recoveries': recoveries[-10:][::-1],
            'resolved': [event for event in events if event['kind'] == 'resolved'][-10:][::-1], 'events': events[-120:][::-1], 'runs': runs,
            'releases': releases, 'pending_changes': pending,
            'post_deploy': {'at': first['at'], 'passed': first['passed'], 'total': first['total'], 'counts': first.get('counts')} if first else None,
            'update': {'state': public.get('state', ''), 'latest': public.get('latest', ''), 'checked_at': public.get('at', '')},
            'settings': settings(c), 'next_scheduled': status['next_scheduled']}


def notifications(c, now):
    """Avisos administrativos según la configuración, sin duplicados (cada uno con una clave estable y una sola vez por evento)."""
    config, items = settings(c), []
    limit = SEVERITY_ORDER[config['min_severity']]
    since = stamp(now - timedelta(days=2))
    link = '#system?autocare=1'
    for event in _load(c, 'autocare_events', []):
        if event['at'] < since:
            continue
        key = 'autocare:' + event['kind'] + ':' + re.sub(r'[^A-Za-z0-9_.:-]', '', event['at'] + ':' + event['module'])[:60]
        severe = SEVERITY_ORDER.get(event['severity'], 9) <= limit
        if event['kind'] == 'incident' and severe and ((event['severity'] == 'crítica' and (config['critical'] or config['unavailable'])) or (event['severity'] != 'crítica' and config['critical'])):
            items.append({'key': key, 'kind': 'error' if event['severity'] in ('crítica', 'alta') else 'warning', 'icon': 'alert', 'title': 'ADI AutoCare · ' + ('Servicio no disponible' if event['severity'] == 'crítica' else 'Incidencia ' + event['severity']),
                          'detail': event['message'] + (' ' + event['detail'] if event['detail'] else ''), 'at': event['at'], 'href': link, 'group': 'event'})
        elif event['kind'] == 'recovery' and config['connection']:
            items.append({'key': key, 'kind': 'success', 'icon': 'check', 'title': 'ADI AutoCare · Problema de conexión recuperado', 'detail': event['message'], 'at': event['at'], 'href': link, 'group': 'event'})
        elif event['kind'] == 'version' and config['updates']:
            items.append({'key': key, 'kind': 'success' if event['severity'] == 'baja' else 'warning', 'icon': 'check', 'title': 'ADI AutoCare · Versión actualizada', 'detail': event['message'], 'at': event['at'], 'href': link, 'group': 'event'})
        elif event['kind'] == 'scheduled' and config['scheduled']:
            items.append({'key': key, 'kind': 'info' if event['severity'] == 'baja' else 'warning', 'icon': 'check', 'title': 'ADI AutoCare · Diagnóstico programado', 'detail': event['message'], 'at': event['at'], 'href': link, 'group': 'event'})
    if config['recurrent']:
        for item in incidents(c):
            if item['status'] != 'resuelta' and item['source'] == 'ejecución' and item['count'] >= RECURRENT and SEVERITY_ORDER.get(item['severity'], 9) <= limit:
                items.append({'key': 'autocare:recurrent:' + item['code'] + ':' + str(item['count'] // RECURRENT), 'kind': 'warning', 'icon': 'alert', 'title': 'ADI AutoCare · Error recurrente',
                              'detail': item['code'] + ' · ' + item['service'] + ': ' + str(item['count']) + ' veces. ' + item['action'], 'at': item['last_at'], 'href': link, 'group': 'alert'})
    if config['connection']:
        connection = [error for error in recent_errors(c, 24, now) if error['type'] in ('ConnectionError', 'TimeoutError', 'OSError', 'URLError') or 'remote' in error['type'].lower()]
        if connection:
            items.append({'key': 'autocare:connection:' + connection[-1]['at'], 'kind': 'warning', 'icon': 'alert', 'title': 'ADI AutoCare · Problemas de conexión',
                          'detail': str(len(connection)) + ' error(es) de conexión en 24 h. ' + connection[-1]['cause'], 'at': connection[-1]['at'], 'href': link, 'group': 'alert'})
    public = _load(c, 'public_version_check', {}) or {}
    if config['updates'] and public.get('state') in ('available', 'important'):
        items.append({'key': 'autocare:update:' + str(public.get('latest', '')), 'kind': 'warning' if public['state'] == 'important' else 'info', 'icon': 'check', 'title': 'ADI AutoCare · Actualización disponible',
                      'detail': 'Versión ' + str(public.get('latest', '')) + ' disponible. No se instala automáticamente: requiere autorización administrativa.', 'at': public.get('at', stamp(now)), 'href': link, 'group': 'alert'})
    errors = [error for error in recent_errors(c, 24, now) if SEVERITY_ORDER.get(error['severity'], 9) <= limit]
    if config['critical'] and errors:
        worst = min(errors, key=lambda error: SEVERITY_ORDER.get(error['severity'], 9))
        items.append({'key': 'autocare:errors:' + str(len(errors)) + ':' + worst['at'], 'kind': 'error' if worst['severity'] in ('crítica', 'alta') else 'warning', 'icon': 'alert',
                      'title': 'ADI AutoCare · ' + ('1 error de ejecución' if len(errors) == 1 else str(len(errors)) + ' errores de ejecución') + ' en 24 h',
                      'detail': worst['cause'] + ' Módulo: ' + worst['module'] + '.', 'at': worst['at'], 'href': link, 'group': 'alert'})
    return items[-12:]


def mark_reviewed(c, now):
    """Administración revisó los errores de ejecución: dejan de contar como incidencias activas (el registro se conserva)."""
    _save(c, 'autocare_reviewed', stamp(now))
    log(c, 'review', 'baja', 'Errores de ejecución', 'Errores de ejecución revisados por administración.', '', now)
