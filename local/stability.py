"""Estabilidad de la versión instalada: verificaciones reales, seguras (solo lectura) y registradas con fecha, hora, versión y resultado.

Estados (nunca se deducen del despliegue ni se inventan):
- unverified  «No verificada»: esta versión todavía no tiene ninguna verificación completa registrada.
- verifying   «Verificando»: hay una verificación en curso.
- observing   «En observación»: todas las verificaciones superadas, pero aún no se completa el período de seguimiento
               (OBSERVATION_HOURS desde la primera verificación correcta y al menos MIN_PASSES verificaciones correctas).
- stable      «Versión estable»: al menos MIN_PASSES verificaciones correctas durante OBSERVATION_HOURS, sin ningún fallo crítico en ese período.
- attention   «Requiere atención»: la última verificación detectó un fallo crítico. El período de seguimiento vuelve a empezar desde
              la siguiente verificación correcta: un fallo crítico nunca se pasa por alto.

Ejecución automática en el servidor: tareas programadas de Vercel (SCHEDULE_UTC, ver vercel.json → /api/cron/stability, /api/cron/stability-night
y /api/cron/reminders) y, además, como mucho cada EVERY_MINUTES al consultarse el indicador.
Registro: cada ejecución en `stability_runs` (las últimas KEEP, con el detalle de cada prueba) y un resumen permanente por versión en
`stability_versions` (las últimas KEEP_VERSIONS versiones), que conserva el historial al publicar una versión nueva.

Las verificaciones no crean, modifican ni borran datos: leen la base, el registro de versiones y los archivos desplegados, y
ejecutan en modo lectura las consultas de las funciones principales. Se guardan en system_state (sin migración), las últimas 60.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import versioning

ROOT = Path(__file__).resolve().parent
OBSERVATION_HOURS = 24
MIN_PASSES = 3
EVERY_MINUTES = 30
KEEP = 60
KEEP_VERSIONS = 40
# Horas (UTC) de las tareas programadas en Vercel que ejecutan las verificaciones; deben coincidir con vercel.json.
SCHEDULE_UTC = (6, 14, 22)
LABELS = {'unverified': 'No verificada', 'verifying': 'Verificando', 'observing': 'En observación', 'stable': 'Versión estable', 'attention': 'Requiere atención'}
SHORT = {'unverified': 'No verificada', 'verifying': 'Verificando', 'observing': 'En observación', 'stable': 'Estable', 'attention': 'Requiere atención'}


def _load(c, key, default):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (key,)).fetchone()
    try:
        return json.loads(row['value']) if row else default
    except (ValueError, TypeError):
        return default


def _save(c, key, value):
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))


def checks(c):
    """Lista de (código, nombre, crítico, función). Cada función devuelve un detalle breve o lanza una excepción si falla."""
    def deployment():
        registry = versioning.load()
        installed = registry['releases'][0]
        versioning.parse(installed['version'])
        build = (os.getenv('VERCEL_GIT_COMMIT_SHA', '') or 'local')[:7]
        return 'Versión ' + installed['version'] + ' registrada · compilación ' + build

    def database():
        c.execute('SELECT 1').fetchone()
        files = {p.name for p in (ROOT / 'migrations').glob('*.sql')}
        applied = {row[0] for row in c.execute('SELECT name FROM migrations')}
        missing = sorted(files - applied)
        if missing:
            raise RuntimeError('Faltan migraciones: ' + ', '.join(missing[:3]))
        return str(len(files)) + ' migraciones aplicadas'

    def essential_data():
        totals = {table: c.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in ('users', 'clients', 'orders', 'statuses')}
        if not totals['users'] or not totals['statuses']:
            raise RuntimeError('No hay usuarios o estados configurados.')
        return 'Usuarios, clientes, órdenes y estados accesibles'

    def static_files():
        for name in ('app.js', 'app.css', 'form-validation.js'):
            path = ROOT / 'static' / name
            if not path.exists() or path.stat().st_size < 1000:
                raise RuntimeError('Archivo de interfaz ausente: ' + name)
        for name in ('login.html', 'dashboard.html'):
            if not (ROOT / 'templates' / name).exists():
                raise RuntimeError('Plantilla ausente: ' + name)
        return 'Interfaz y plantillas presentes'

    def orders_tracking():
        import tracking_board
        board = tracking_board.build(c, tracking_board.parse({}))
        return 'Seguimiento de órdenes: ' + str(board['total']) + ' órdenes consultadas'

    def agenda():
        import appointments
        services = appointments.services(c)
        if not services:
            raise RuntimeError('La agenda no tiene servicios de cita.')
        return 'Agenda: ' + str(len(services)) + ' servicios disponibles'

    def reports():
        import equipment
        today = datetime.now().date()
        equipment.receivables(c, today - timedelta(days=30), today)
        return 'Reportes y saldos consultados'

    def mail():
        import mail_pro
        try:
            ready = mail_pro.configured()
        except mail_pro.MailError:
            ready = False
        if not ready:
            raise RuntimeError('El correo del sistema no está configurado.')
        return 'Correo del sistema configurado'

    return [('deployment', 'Despliegue y registro de versión', True, deployment), ('database', 'Base de datos y migraciones', True, database),
            ('data', 'Datos esenciales accesibles', True, essential_data), ('interface', 'Archivos de la interfaz', True, static_files),
            ('orders', 'Seguimiento de órdenes', True, orders_tracking), ('agenda', 'Agenda de citas', True, agenda),
            ('reports', 'Reportes y saldos', False, reports), ('mail', 'Servicio de correo', False, mail)]


def _summary(c, version, history=None):
    """Resumen permanente de una versión. Si aún no existe (versiones verificadas antes de este registro), se reconstruye con las ejecuciones guardadas."""
    summaries = _load(c, 'stability_versions', {})
    if version in summaries:
        return summaries[version]
    summary = {'version': version, 'first_run': '', 'last_run': '', 'runs': 0, 'passes': 0, 'window_start': '', 'window_passes': 0, 'last_ok': None, 'criticals': [], 'warnings': 0}
    for entry in history if history is not None else _load(c, 'stability_runs', []):
        if entry['version'] == version:
            _account(summary, entry)
    return summary


def _account(summary, entry):
    """Suma una ejecución al resumen. Un fallo crítico reinicia el período de seguimiento: cuenta desde la siguiente verificación correcta."""
    ok = not entry['critical_failures']
    summary['first_run'] = summary['first_run'] or entry['at']
    summary['last_run'] = entry['at']
    summary['runs'] += 1
    summary['last_ok'] = ok
    summary['warnings'] += 1 if entry['warnings'] else 0
    if ok:
        summary['passes'] += 1
        summary['window_start'] = summary['window_start'] or entry['at']
        summary['window_passes'] += 1
    else:
        summary['criticals'] = (summary['criticals'] + [{'at': entry['at'], 'items': entry['critical_failures']}])[-20:]
        summary['window_start'], summary['window_passes'] = '', 0


def run(c, now, source='automática'):
    """Ejecuta todas las verificaciones y registra el resultado (ejecución detallada y resumen de la versión). Devuelve la ejecución."""
    version = versioning.load()['releases'][0]['version']
    _save(c, 'stability_running', {'version': version, 'since': now.isoformat(timespec='seconds')})
    c.commit()
    results = []
    try:
        for code, name, critical, test in checks(c):
            began = time.monotonic()
            try:
                detail, ok = test(), True
            except Exception as error:
                detail, ok = (str(error) or type(error).__name__)[:160], False
                print('stability', code, type(error).__name__, flush=True)
            results.append({'code': code, 'name': name, 'critical': critical, 'ok': ok, 'detail': detail, 'ms': round((time.monotonic() - began) * 1000)})
    finally:
        c.execute("DELETE FROM system_state WHERE key='stability_running'")
    entry = {'version': version, 'at': now.isoformat(timespec='seconds'), 'source': source, 'passed': sum(1 for r in results if r['ok']), 'total': len(results),
             'critical_failures': [r['name'] for r in results if r['critical'] and not r['ok']], 'warnings': [r['name'] for r in results if not r['critical'] and not r['ok']],
             'results': results}
    history = _load(c, 'stability_runs', [])
    summary = _summary(c, version, history)
    _account(summary, entry)
    summaries = _load(c, 'stability_versions', {})
    # Versiones verificadas antes de existir el resumen: se incorporan desde las ejecuciones guardadas para no perder su historial.
    for other in {item['version'] for item in history} - set(summaries) - {version}:
        summaries[other] = _summary(c, other, history)
    summaries[version] = summary
    if len(summaries) > KEEP_VERSIONS:
        for old in sorted(summaries, key=lambda key: summaries[key]['last_run'])[:len(summaries) - KEEP_VERSIONS]:
            summaries.pop(old)
    history.append(entry)
    _save(c, 'stability_runs', history[-KEEP:])
    _save(c, 'stability_versions', summaries)
    c.commit()
    return entry


def _known(c, history):
    """Resúmenes guardados más los que aún solo constan en las ejecuciones (sin escribir nada)."""
    summaries = dict(_load(c, 'stability_versions', {}))
    for other in {item['version'] for item in history} - set(summaries):
        summaries[other] = _summary(c, other, history)
    return summaries


def _running(c, now):
    running = _load(c, 'stability_running', None)
    return running if running and running.get('since', '') > (now - timedelta(minutes=5)).isoformat(timespec='seconds') else None


def due(c, now, minutes=EVERY_MINUTES):
    """¿Toca una verificación? Si esta versión no tiene ninguna o la última tiene más de `minutes` (y no hay otra en curso)."""
    version = versioning.load()['releases'][0]['version']
    if _running(c, now):
        return False
    last = _summary(c, version)['last_run']
    return not last or last < (now - timedelta(minutes=minutes)).isoformat(timespec='seconds')


def next_scheduled(now):
    """Próxima tarea programada del servidor (hora de Ecuador), según SCHEDULE_UTC."""
    utc = now.astimezone(timezone.utc)
    for days in (0, 1):
        for hour in SCHEDULE_UTC:
            moment = (utc + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
            if moment > utc:
                return moment.astimezone(now.tzinfo).isoformat(timespec='seconds')
    return ''


def status(c, now):
    """Estado actual de la versión instalada con el detalle para la ventana informativa. Solo datos ya públicos (sin datos de clientes)."""
    registry = versioning.load()
    installed = registry['releases'][0]
    version = installed['version']
    summary = _summary(c, version)
    history = _load(c, 'stability_runs', [])
    last = next((entry for entry in reversed(history) if entry['version'] == version), None)
    remaining, missing = None, max(0, MIN_PASSES - summary['window_passes'])
    if _running(c, now) and _running(c, now).get('version') == version:
        state = 'verifying'
    elif not summary['runs']:
        state = 'unverified'
    elif not summary['last_ok']:
        state = 'attention'
    else:
        end = datetime.fromisoformat(summary['window_start']) + timedelta(hours=OBSERVATION_HOURS)
        # La decisión usa el instante exacto; el redondeo es solo para mostrar el tiempo restante.
        complete = now >= end
        remaining = 0.0 if complete else max(0.01, round((end - now).total_seconds() / 3600, 2))
        state = 'stable' if complete and not missing else 'observing'
    incidents = [{'at': item['at'], 'items': item['items'], 'critical': True} for item in summary['criticals']]
    incidents += [{'at': entry['at'], 'items': entry['warnings'], 'critical': False} for entry in history if entry['version'] == version and entry['warnings'] and not entry['critical_failures']]
    incidents = sorted(incidents, key=lambda item: item['at'])[-5:]
    previous = [{'version': key, 'runs': value['runs'], 'passes': value['passes'], 'last_run': value['last_run'], 'stable': bool(value['window_start']) and value['window_passes'] >= MIN_PASSES
                 and datetime.fromisoformat(value['window_start']) + timedelta(hours=OBSERVATION_HOURS) <= datetime.fromisoformat(value['last_run'])}
                for key, value in sorted(_known(c, history).items(), key=lambda pair: pair[1]['last_run'], reverse=True) if key != version][:5]
    return {'version': version, 'date': installed.get('date', ''), 'state': state, 'label': LABELS[state], 'short': SHORT[state],
            'last_check': summary['last_run'], 'checks_run': summary['runs'], 'checks_passed': summary['passes'],
            'window_start': summary['window_start'], 'window_passes': summary['window_passes'], 'missing_passes': missing,
            'tests': [{'name': r['name'], 'ok': r['ok'], 'critical': r['critical']} for r in (last['results'] if last else [])],
            'passed': last['passed'] if last else 0, 'total': last['total'] if last else len(checks(c)),
            'incidents': incidents, 'observation_hours': OBSERVATION_HOURS, 'min_passes': MIN_PASSES, 'remaining_hours': remaining,
            'first_pass': summary['window_start'], 'next_scheduled': next_scheduled(now), 'previous': previous}
