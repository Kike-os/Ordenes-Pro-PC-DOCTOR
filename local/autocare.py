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
import hashlib
import json
import secrets
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
# Nivel que ve la persona para cada gravedad interna: Información, Advertencia, Error o Crítico.
LEVELS = {'baja': 'Información', 'media': 'Advertencia', 'alta': 'Error', 'crítica': 'Crítico'}
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
 'ai': ('La clave de OpenAI no es válida, el modelo no está disponible o OpenAI no responde.', 'Revisar la variable OPENAI_API_KEY y el modelo (OPENAI_MODEL) en Vercel; mientras tanto ADI responde con los datos del sistema, sin IA.'),
 'backups': ('El último respaldo verificado de la base central es antiguo, falló o no está registrado.', 'Ejecutar el respaldo verificado (maintenance/backup-cloud.py) con las variables de producción y comprobar su registro.'),
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


def open_incident(c, key, service, severity, description, cause, action, now, source, details=None):
    """Abre o actualiza una incidencia (sin duplicados: una por servicio o por tipo de error, con contador de repeticiones).
    Si vuelve a ocurrir después de resolverse, se reabre la MISMA incidencia (mismo código) y el seguimiento lo registra."""
    items = _load(c, 'autocare_incidents', [])
    found = next((item for item in reversed(items) if item['key'] == key), None)
    if found and found['status'] == 'resuelta':
        found.update(status='activa', reopened=True, reopened_at=stamp(now))
        found['history'] = (found.get('history', []) + [{'at': stamp(now), 'by': 'ADI AutoCare', 'status': 'activa', 'note': 'Reabierta automáticamente: el problema volvió a ocurrir después de resolverse.'}])[-20:]
        log(c, 'incident', severity, service, 'Incidencia ' + found['code'] + ' reabierta: el problema volvió a ocurrir.', description, now)
    if found:
        found.update(last_at=stamp(now), count=found['count'] + 1, description=description[:300], severity=severity)
    else:
        found = {'code': _incident_code(c, now), 'key': key, 'service': service, 'severity': severity, 'description': description[:300], 'cause': cause[:300], 'action': action[:300],
                 'source': source, 'first_at': stamp(now), 'last_at': stamp(now), 'count': 1, 'status': 'activa', 'history': [], 'reopened': False}
        items.append(found)
    if details:
        found['details'] = details
        found['occurrences'] = (found.get('occurrences', []) + [{key: details.get(key, '') for key in ('at', 'user', 'ref', 'status', 'origin')}])[-10:]
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


def _clean_message(error):
    """Mensaje técnico sin datos: sin correos, textos entre comillas, números largos ni rutas de archivo."""
    text = re.sub(r'\s+', ' ', str(error))[:220]
    text = re.sub(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', '[correo]', text)
    text = re.sub(r"'[^']*'|\"[^\"]*\"", "'…'", text)
    text = re.sub(r'\d{4,}', '[n]', text)
    return re.sub(r'(/[\w.-]+)+/', '', text)[:160]


def record_error(c, method, path, error, now, user=None, status=500):
    """Guarda un error de ejecución clasificado. Nunca guarda el cuerpo de la petición; el mensaje se depura (sin datos personales,
    valores ni secretos) y la operación de base de datos solo indica el verbo y la tabla."""
    severity, cause = classify(method, path, error)
    try:
        user = dict(user) if user is not None and not isinstance(user, dict) else user
    except (TypeError, ValueError):
        user = None
    try:
        version = versioning.load()['releases'][0]['version']
    except versioning.RegistryError:
        version = ''
    clean_path = re.sub(r'/\d+', '/:id', path.split('?', 1)[0])[:120]
    origin = error.__cause__ or error.__context__
    ref = re.search(r'/(\d+)', path.split('?', 1)[0])
    item = {'at': stamp(now), 'version': version, 'method': method, 'path': clean_path,
            'module': module_of(path), 'type': type(error).__name__, 'where': where(error)[:160], 'severity': severity, 'cause': cause,
            'status': status, 'user': str((user or {}).get('name') or (user or {}).get('username') or '')[:80], 'ref': ref[1] if ref else '',
            'operation': str(getattr(error, 'operation', '') or '')[:80], 'origin': type(origin).__name__ if origin else '', 'message': _clean_message(error)}
    key = 'error:' + item['module'] + ':' + item['type'] + ':' + item['where'].split(' · ')[0]
    item['code'] = 'ERR-' + hashlib.sha256(key.encode()).hexdigest()[:6].upper()
    errors = _load(c, 'autocare_errors', [])
    errors.append(item)
    _save(c, 'autocare_errors', errors[-KEEP_ERRORS:])
    incident = open_incident(c, key, item['module'], severity,
                  'Error de ejecución en ' + item['method'] + ' ' + item['path'] + (' (' + item['where'] + ')' if item['where'] else '') + '.', cause,
                  'Revisar el punto del código indicado y preparar la corrección en una rama de pruebas; no se ejecuta ninguna reparación automática.', now, 'ejecución', details=item)
    item['incident'] = incident['code']
    _save(c, 'autocare_errors', errors[-KEEP_ERRORS:])
    return item


def pending_errors(c, hours=1, now=None):
    """Errores recientes que siguen abiertos: los de una incidencia marcada como resuelta DESPUÉS del error ya no cuentan para la
    advertencia (el historial se conserva). Si el error vuelve a ocurrir, la incidencia se reabre y vuelve a contar."""
    items = {item['key']: item for item in _load(c, 'autocare_incidents', [])}
    out = []
    for error in recent_errors(c, hours, now):
        key = 'error:' + error['module'] + ':' + error['type'] + ':' + error['where'].split(' · ')[0]
        incident = items.get(key)
        if incident and incident['status'] == 'resuelta' and (incident.get('resolved_at') or '') >= error['at']:
            continue
        out.append(error)
    return out


def errors_summary(errors):
    """Problema concreto y acción recomendada a partir de los errores registrados (módulo, método, ruta y punto del código)."""
    if not errors:
        return None
    groups = {}
    for error in errors:
        groups.setdefault((error['module'], error['method'], error['path'], error['type'], error['where']), []).append(error)
    (module, method, path, kind, place), first = max(groups.items(), key=lambda pair: len(pair[1]))
    total = len(errors)
    problem = 'Se registr' + ('ó 1 fallo' if total == 1 else 'aron ' + str(total) + ' fallos') + ' en el módulo ' + module + ' durante operaciones ' + method + ' (' + path + ', ' + kind + (' en ' + place if place else '') + ').'
    if len(groups) > 1:
        problem += ' Hay ' + str(len(groups)) + ' tipos de error distintos; se muestra el más frecuente.'
    operation = next((e.get('operation') for e in first if e.get('operation')), '')
    action = 'Revisar ' + path + (' y la operación de base de datos asociada (' + operation + ').' if operation else ' y la operación de base de datos asociada.' if kind in ('OperationalError', 'IntegrityError') else ' en ' + (place or 'el punto del código indicado') + '.')
    return {'problem': problem, 'action': action, 'count': total, 'groups': len(groups)}


def recent_errors(c, hours=24, now=None):
    if now is None:
        from reception import reception_now
        now = reception_now()
    since = stamp(now - timedelta(hours=hours))
    reviewed = _load(c, 'autocare_reviewed', '')
    return [item for item in _load(c, 'autocare_errors', []) if item['at'] >= since and item['at'] > reviewed]


def log(c, kind, severity, module, message, detail='', now=None, version='', by=''):
    events = _load(c, 'autocare_events', [])
    if now is None:
        from reception import reception_now
        now = reception_now()
    events.append({'id': 'EV-' + secrets.token_hex(4).upper(), 'at': stamp(now), 'kind': kind, 'severity': severity, 'module': module, 'message': message,
                   'detail': detail[:300], 'version': version, 'by': by})
    _save(c, 'autocare_events', events[-KEEP_EVENTS:])


def after_recheck(c, result, by, now, version=''):
    """Tras repetir una sola comprobación: correcta → su incidencia se cierra con esa evidencia; con error o advertencia → la incidencia
    se abre o se actualiza (sin duplicados). Queda en la actividad técnica con quién la pidió."""
    status = result.get('status', 'ok' if result['ok'] else 'error')
    key = 'check:' + result['code']
    was_open = any(item['key'] == key and item['status'] != 'resuelta' for item in _load(c, 'autocare_incidents', []))
    if status == 'ok':
        close_incident(c, key, now, by or 'ADI AutoCare', 'Comprobación individual correcta: ' + result['detail'])
        if was_open:
            log(c, 'resolved', result.get('severity', 'media'), result['name'], 'Incidencia resuelta en «' + result['name'] + '» tras repetir la comprobación.', result['detail'], now, version, by)
    elif status in ('error', 'warning'):
        cause, action = GUIDE.get(result['code'], ('Fallo en la verificación del servicio.', 'Revisar el detalle de la verificación.'))
        open_incident(c, key, result['name'], result.get('severity', 'media') if status == 'error' else 'baja', result['detail'], cause, action, now, 'verificación')
    log(c, 'review', result.get('severity', 'media') if status == 'error' else 'baja', result['name'], 'Comprobación repetida: ' + {'ok': 'correcta', 'warning': 'con advertencia', 'error': 'con error', 'not_checked': 'sin comprobar', 'unavailable': 'no disponible'}.get(status, status) + '.', result['detail'], now, version, by)


# ---- Recuperación segura: solo estas acciones, sin parámetros libres, con confirmación de administración y comprobación posterior ----
ACTIONS = {
    'unlock_diagnosis': {'label': 'Liberar un diagnóstico bloqueado', 'check': 'internal',
                         'description': 'Quita la marca de «diagnóstico en curso» cuando quedó colgada más de 5 minutos (por ejemplo, si se cerró la ventana a mitad). No toca ningún dato.'},
    'license_expiry': {'label': 'Actualizar licencias vencidas del inventario', 'check': 'licenses',
                       'description': 'Marca como «Vencida» las licencias SIN VENDER cuya fecha de vencimiento ya pasó, para que no se ofrezcan. Las vendidas no cambian.'},
}


def run_action(c, now, action, user):
    """Ejecuta una acción de la lista cerrada y verifica el resultado con la comprobación del servicio. Devuelve lo hecho y la verificación."""
    import stability
    spec = ACTIONS.get(action)
    if not spec:
        raise ValueError('Acción no permitida.')
    if action == 'unlock_diagnosis':
        if stability._running(c, now):
            raise ValueError('El diagnóstico sigue activo (menos de 5 minutos): no se libera. Espera a que termine.')
        stuck = c.execute("SELECT COUNT(*) FROM system_state WHERE key IN ('stability_manual','stability_running')").fetchone()[0]
        c.execute("DELETE FROM system_state WHERE key IN ('stability_manual','stability_running')")
        done = 'Marca de diagnóstico liberada.' if stuck else 'No había ningún diagnóstico bloqueado.'
    else:
        import licenses
        # Copia del cambio: los identificadores y su estado anterior («disponible») quedan en el registro, así el cambio es reversible.
        ids = [row[0] for row in c.execute("SELECT id FROM license_units WHERE status='disponible' AND expires_at!='' AND expires_at<?", (now.date().isoformat(),)).fetchall()]
        licenses.expire(c, now)
        done = ('%d licencia(s) sin vender pasaron de «disponible» a «Vencida»: unidades %s.' % (len(ids), ', '.join('#' + str(i) for i in ids[:40]) + (' …' if len(ids) > 40 else ''))) if ids \
            else 'No había licencias sin vender vencidas por actualizar.'
    c.commit()
    version = versioning.load()['releases'][0]['version']
    log(c, 'recovery', 'media', spec['label'], 'Acción de recuperación autorizada por ' + user['name'] + ': ' + spec['label'] + '.', done, now, version, user['name'])
    result = stability.recheck(c, now, spec['check'], user['name'])
    return {'action': action, 'label': spec['label'], 'done': done, 'verification': result}


def history_rows(c, frm='', to='', service='', severity='', version='', who=''):
    """Actividad técnica filtrada (para la pantalla y la exportación): identificador, fecha, tipo, gravedad, servicio, acción, resultado,
    versión y usuario. Sin contraseñas, claves, tokens ni datos personales (se enmascaran correos y números largos)."""
    rows = []
    for index, ev in enumerate(_load(c, 'autocare_events', [])):
        at = ev.get('at', '')
        if (frm and at[:10] < frm) or (to and at[:10] > to) or (service and ev.get('module') != service) or (severity and ev.get('severity') != severity) \
                or (version and ev.get('version') != version) or (who and who.lower() not in (ev.get('by') or '').lower()):
            continue
        rows.append({'id': ev.get('id') or 'EV-H%05d' % index, 'at': at, 'kind': ev.get('kind', ''), 'severity': ev.get('severity', ''), 'module': ev.get('module', ''),
                     'message': _scrub(ev.get('message', '')), 'detail': _scrub(ev.get('detail', '')), 'version': ev.get('version', ''), 'by': ev.get('by', '')})
    return rows[::-1]


def _scrub(text):
    text = re.sub(r'[^\s@<>]+@[^\s@<>]+', '[correo]', str(text or ''))
    text = re.sub(r'(sk|pk|rk)-[A-Za-z0-9_-]{8,}', '[clave]', text)
    return re.sub(r'\b\d{9,}\b', '[número]', text)


def history_csv(rows):
    import csv
    import io
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Identificador', 'Fecha y hora (Ecuador)', 'Tipo', 'Gravedad', 'Servicio', 'Acción o evento', 'Resultado y evidencia', 'Versión', 'Usuario o proceso'])
    for row in rows:
        writer.writerow([row['id'], row['at'], row['kind'], row['severity'], row['module'], row['message'], row['detail'], row['version'], row['by'] or 'ADI AutoCare'])
    return '\ufeff' + out.getvalue()


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


SLOW_FLOOR_MS = 1500


def timing(history, code, ms=None):
    """Tiempos reales de un servicio (últimas 30 ejecuciones): mediana, p90 y umbral de advertencia (doble de la mediana, mínimo 1,5 s).
    El tiempo nunca convierte un servicio en Error: solo se señala como lento."""
    values = sorted(r['ms'] for run in history[-30:] for r in run['results'] if r['code'] == code and isinstance(r.get('ms'), (int, float)))
    if not values:
        return {'samples': 0, 'median': None, 'p90': None, 'threshold': SLOW_FLOOR_MS, 'slow': False}
    median = values[len(values) // 2]
    p90 = values[min(len(values) - 1, int(len(values) * 0.9))]
    threshold = max(SLOW_FLOOR_MS, 2 * median)
    return {'samples': len(values), 'median': median, 'p90': p90, 'threshold': threshold, 'slow': ms is not None and len(values) >= 5 and ms > threshold}


def service_detail(c, code, now):
    """Detalle de un servicio para el panel: historial de resultados y tiempos, y datos propios (licencias, correo)."""
    import stability
    history = stability._load(c, 'stability_runs', [])
    items = [dict(r, at=run['at'], source=run.get('source', '')) for run in reversed(history) for r in run['results'] if r['code'] == code][:30]
    if not items and code not in {item[0] for item in stability.checks(c)}:
        raise LookupError('Servicio no disponible.')
    cause, action = GUIDE.get(code, ('', ''))
    if code == 'errors':
        concrete = errors_summary(pending_errors(c, 1, now))
        if concrete:
            cause, action = 'Problema detectado: ' + concrete['problem'], concrete['action']
    out = {'code': code, 'name': items[0]['name'] if items else code, 'cause': cause, 'action': action, 'concrete': code == 'errors' and bool(cause) and cause.startswith('Problema detectado'),
           'history': [{'at': i['at'], 'source': i['source'], 'status': i.get('status', 'ok' if i['ok'] else 'error'), 'ms': i.get('ms'), 'detail': i['detail']} for i in items],
           'timing': timing(history, code, items[0].get('ms') if items else None)}
    if code == 'licenses':
        out['licenses'] = _license_detail(c, now)
    if code == 'mail':
        out['mail'] = _mail_detail(c, history, now)
    return out


def _license_detail(c, now):
    import licenses
    cols = [d[1] for d in c.execute('PRAGMA table_info(license_units)').fetchall()]
    rows = [dict(zip(cols, tuple(r))) for r in c.execute('SELECT * FROM license_units ORDER BY id').fetchall()]
    names = {r[0]: r[1] for r in c.execute('SELECT id,name FROM catalog_items').fetchall()}
    affected = [{'code': r['code'], 'product': names.get(r['product_id'], ''), 'status': licenses.STATUSES.get(r['status'], r['status']), 'activated_at': r['activated_at'], 'expires_at': r['expires_at'],
                 'delivered_at': (r['delivered_at'] or '')[:10], 'problems': licenses.issues(r)} for r in rows if licenses.issues(r)]
    products = {}
    for r in rows:
        item = products.setdefault(r['product_id'], {'product': names.get(r['product_id'], ''), 'registros': 0, **{key: 0 for key in licenses.STATUSES}})
        item['registros'] += 1
        item[r['status']] += 1
    # Posibles duplicados: misma terminación de clave o usuario dentro de un producto (la huella ya impide claves idénticas).
    groups, unreadable = {}, 0
    for r in rows:
        if r['status'] == 'anulada':
            continue
        try:
            values = licenses.unseal(r['secret'])
        except Exception:
            unreadable += 1
            continue
        tail = ''.join(ch for ch in (values.get('key') or values.get('username') or '') if ch.isalnum())[-6:].upper()
        if len(tail) >= 6:
            groups.setdefault((r['product_id'], tail), []).append(r['code'])
    duplicates = [{'product': names.get(pid, ''), 'codes': codes, 'hint': '•••• ' + tail[-4:]} for (pid, tail), codes in groups.items() if len(codes) > 1]
    tips = []
    if affected:
        tips.append('Usa Licencias → Inventario → «Revisar inconsistencias»: cada corrección pide motivo y queda en el historial.')
    if duplicates:
        tips.append('Revisa las licencias con la misma terminación de clave; si una sobra, retírala con «Ajustar stock» (queda anulada, no se borra).')
    if not tips:
        tips.append('Sin acciones pendientes en el inventario de licencias.')
    return {'affected': affected, 'products': sorted(products.values(), key=lambda item: item['product']), 'duplicates': duplicates, 'unreadable': unreadable,
            'stock_note': 'El stock disponible se calcula siempre desde los registros individuales (LIC-…): no hay un contador aparte que pueda diferir.', 'recommendations': tips}


def _mail_detail(c, history, now):
    import mail_pro
    info = mail_pro.status()
    last = None
    for run in reversed(history):
        if run.get('source') in ('manual', 'programada'):
            found = next((r for r in run['results'] if r['code'] == 'mail' and r.get('status', 'ok' if r['ok'] else 'error') in ('ok', 'error')), None)
            if found:
                last = {'at': run['at'], 'source': run['source'], 'status': found.get('status', 'ok' if found['ok'] else 'error'), 'detail': found['detail']}
                break
    since = (now - timedelta(days=7)).isoformat(timespec='seconds')
    failed = c.execute("SELECT COUNT(*) FROM mail_deliveries WHERE status IN ('fallido','rebotado','demorado') AND created_at>=?", (since,)).fetchone()[0]
    reason = c.execute("SELECT status,reason,created_at FROM mail_deliveries WHERE status IN ('fallido','rebotado','demorado') ORDER BY id DESC LIMIT 1").fetchone()
    fresh = last and last['at'] >= (now - timedelta(hours=24)).isoformat(timespec='seconds')
    state = ('Sin configurar' if not info.get('configured') else 'Fallo real' if fresh and last['status'] == 'error' else 'Comprobado' if fresh else 'Comprobación pendiente')
    return {'configured': bool(info.get('configured')), 'imap': info.get('imap', ''), 'smtp': info.get('smtp', ''), 'account': info.get('account', ''), 'password_set': info.get('password_set', False),
            'last_check': last, 'state': state, 'failed_7d': failed, 'last_failure': {'status': reason['status'], 'reason': (reason['reason'] or '')[:200], 'at': reason['created_at']} if reason else None,
            'note': 'Las verificaciones automáticas no abren el buzón (prueba omitida) y muestran el resultado real del último diagnóstico manual o programado de las últimas 24 h. No se envía ningún correo de prueba.'}


def build_info():
    """Compilación desplegada: en Vercel, el commit y la rama de la que se construyó; en el equipo local, «local»."""
    import os
    sha = os.environ.get('VERCEL_GIT_COMMIT_SHA', '')
    return {'commit': sha[:7], 'branch': os.environ.get('VERCEL_GIT_COMMIT_REF', ''), 'environment': os.environ.get('VERCEL_ENV', '') or ('vercel' if os.environ.get('VERCEL') else 'local'),
            'region': os.environ.get('VERCEL_REGION', '')}


def migrations(c):
    """Migraciones del paquete frente a las aplicadas en la base. En producción (Vercel) no se aplican solas: una pendiente es un aviso real."""
    from pathlib import Path
    files = sorted(p.name for p in (Path(__file__).resolve().parent / 'migrations').glob('*.sql'))
    try:
        applied = {row[0] for row in c.execute('SELECT name FROM migrations').fetchall()}
    except Exception:
        applied = set()
    done = [name for name in files if name in applied]
    return {'total': len(files), 'applied': len(done), 'last': done[-1] if done else '', 'pending': [name for name in files if name not in applied]}


def overview(c, now):
    """Resumen del panel: indicadores, servicios, incidencias, recuperaciones, historial técnico, versiones y configuración de avisos."""
    import stability
    status = stability.status(c, now)
    history = stability._load(c, 'stability_runs', [])
    last = next((item for item in reversed(history) if item['version'] == status['version']), None)
    services = [{'code': r['code'], 'name': r['name'], 'severity': r.get('severity', 'crítica' if r['critical'] else 'media'), 'ok': r['ok'], 'status': r.get('status', 'ok' if r['ok'] else 'error'),
                 'detail': r['detail'], 'ms': r['ms'], 'recovered': r.get('recovered', False), 'timing': timing(history, r['code'], r['ms'])} for r in (last['results'] if last else [])]
    # Un reintento individual posterior a la última verificación completa sustituye el estado de ese servicio (con quién y cuándo).
    latest = {}
    for item in stability._load(c, 'stability_rechecks', []):
        if last and item['at'] >= last['at'] and item['version'] == status['version']:
            latest[item['result']['code']] = item
    for service in services:
        again = latest.get(service['code'])
        if again:
            r = again['result']
            service.update({'ok': r['ok'], 'status': r.get('status', 'ok' if r['ok'] else 'error'), 'detail': r['detail'], 'ms': r['ms'], 'recovered': r.get('recovered', False),
                            'rechecked_at': again['at'], 'rechecked_by': again.get('by', '')})
        if service['status'] in ('error', 'warning'):
            service['cause'], service['action'] = GUIDE.get(service['code'], ('Fallo en la verificación del servicio.', 'Revisar el detalle de la verificación.'))
        service['limit_ms'] = stability.MAX_MS.get(service['code'], stability.DEFAULT_MAX_MS)
    counts = {key: sum(1 for s in services if s['status'] == key) for key in stability.STATUS_LABELS}
    items = incidents(c)
    open_items = [item for item in items if item['status'] != 'resuelta']
    worst = min((SEVERITY_ORDER.get(item['severity'], 9) for item in open_items), default=9)
    # «No disponible» (no configurado) solo degrada el estado general en servicios de gravedad crítica o alta.
    missing = any(s['status'] == 'unavailable' and SEVERITY_ORDER.get(s['severity'], 9) <= SEVERITY_ORDER['alta'] for s in services)
    general = 'unverified' if not last else 'critical' if worst == 0 or counts['error'] and any(s['status'] == 'error' and s['severity'] == 'crítica' for s in services) else 'degraded' if open_items or counts['error'] or counts['warning'] or missing else 'ok'
    events = _load(c, 'autocare_events', [])
    try:
        registry = versioning.load()
        releases = [{'version': item['version'], 'date': item.get('date', ''), 'type': item.get('type', ''), 'summary': item.get('summary', ''), 'changes': item.get('changes', {}),
                     'published_by': item.get('published_by', ''), 'authorized_by': item.get('authorized_by', '')} for item in registry['releases'][:10]]
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
    resolved = [event for event in events if event['kind'] == 'resolved']
    by_severity = {level: sum(1 for item in open_items if item['severity'] == level) for level in SEVERITY_ORDER}
    return {'general': general, 'stability': status, 'explanation': _explain(status), 'last_check': last['at'] if last else '', 'last_source': last.get('source', '') if last else '',
            'last_by': last.get('by', '') if last else '', 'duration_ms': last.get('ms') if last else None, 'services': services, 'counts': counts, 'status_labels': stability.STATUS_LABELS,
            'incidents': sorted(items, key=lambda item: (item['status'] == 'resuelta', SEVERITY_ORDER.get(item['severity'], 9), item['last_at']), reverse=False)[:120],
            'active': [{'code': item['code'], 'module': item['service'], 'severity': item['severity'], 'diagnosis': item['description'], 'at': item['last_at'], 'source': item['source']} for item in open_items],
            'incident_states': INCIDENT_STATES, 'incidents_by_severity': by_severity, 'recoveries_total': len(recoveries), 'recoveries': recoveries[-10:][::-1],
            'resolved_total': len(resolved), 'resolved': resolved[-10:][::-1], 'events': history_rows(c)[:120], 'runs': runs,
            'releases': releases, 'pending_changes': pending, 'build': build_info(), 'migrations': migrations(c),
            'rechecks': [{'at': item['at'], 'by': item.get('by', ''), 'version': item['version'], 'code': item['result']['code'], 'name': item['result']['name'],
                          'status': item['result'].get('status', ''), 'detail': item['result']['detail']} for item in stability._load(c, 'stability_rechecks', [])[-10:][::-1]],
            'actions': [{'code': key, 'label': value['label'], 'description': value['description']} for key, value in ACTIONS.items()],
            'alerts': notifications(c, now),
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
            # Las automáticas no tienen usuario; las acciones de recuperación las ejecuta (y firma) administración.
            title = 'Acción de recuperación ejecutada' if event.get('by') else 'Problema de conexión recuperado'
            items.append({'key': key, 'kind': 'success', 'icon': 'check', 'title': 'ADI AutoCare · ' + title, 'detail': event['message'] + (' ' + event['detail'] if event.get('by') and event.get('detail') else ''), 'at': event['at'], 'href': link, 'group': 'event'})
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
