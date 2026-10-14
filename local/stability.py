"""Estabilidad de la versión instalada: verificaciones reales, seguras (solo lectura) y registradas con fecha, hora, versión y resultado.

Estados (nunca se deducen del despliegue ni se inventan):
- unverified  «No verificada»: esta versión todavía no tiene ninguna verificación completa registrada.
- verifying   «Verificando»: hay una verificación en curso.
- observing   «En observación»: todas las verificaciones superadas, pero aún no se completa el período de seguimiento
               (OBSERVATION_HOURS desde la primera verificación correcta y al menos MIN_PASSES verificaciones correctas).
- stable      «Estable»: período de seguimiento completo, sin fallos críticos desde la primera verificación correcta.
- attention   «Requiere atención»: la última verificación detectó un fallo crítico.

Las verificaciones no crean, modifican ni borran datos: leen la base, el registro de versiones y los archivos desplegados, y
ejecutan en modo lectura las consultas de las funciones principales. Se guardan en system_state (sin migración), las últimas 60.
"""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import versioning

ROOT = Path(__file__).resolve().parent
OBSERVATION_HOURS = 24
MIN_PASSES = 3
EVERY_MINUTES = 30
KEEP = 60
LABELS = {'unverified': 'No verificada', 'verifying': 'Verificando', 'observing': 'En observación', 'stable': 'Estable', 'attention': 'Requiere atención'}


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


def run(c, now, source='automática'):
    """Ejecuta todas las verificaciones y registra el resultado. Devuelve la ejecución registrada."""
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
    history.append(entry)
    _save(c, 'stability_runs', history[-KEEP:])
    c.commit()
    return entry


def due(c, now):
    """¿Toca una verificación? Si esta versión no tiene ninguna o la última tiene más de EVERY_MINUTES (y no hay otra en curso)."""
    version = versioning.load()['releases'][0]['version']
    running = _load(c, 'stability_running', None)
    if running and running.get('since', '') > (now - timedelta(minutes=5)).isoformat(timespec='seconds'):
        return False
    mine = [entry for entry in _load(c, 'stability_runs', []) if entry['version'] == version]
    return not mine or mine[-1]['at'] < (now - timedelta(minutes=EVERY_MINUTES)).isoformat(timespec='seconds')


def status(c, now):
    """Estado actual de la versión instalada con el detalle para la ventana informativa. Solo datos ya públicos (sin datos de clientes)."""
    registry = versioning.load()
    installed = registry['releases'][0]
    version = installed['version']
    mine = [entry for entry in _load(c, 'stability_runs', []) if entry['version'] == version]
    running = _load(c, 'stability_running', None)
    last = mine[-1] if mine else None
    passes = [entry for entry in mine if not entry['critical_failures']]
    if running and running.get('version') == version and running.get('since', '') > (now - timedelta(minutes=5)).isoformat(timespec='seconds'):
        state = 'verifying'
    elif not last:
        state = 'unverified'
    elif last['critical_failures']:
        state = 'attention'
    else:
        first = passes[0]['at']
        failed_since = any(entry['critical_failures'] for entry in mine if entry['at'] >= first)
        watched = datetime.fromisoformat(first) <= now - timedelta(hours=OBSERVATION_HOURS)
        state = 'stable' if watched and len(passes) >= MIN_PASSES and not failed_since else 'observing'
    remaining = None
    if state == 'observing':
        end = datetime.fromisoformat(passes[0]['at']) + timedelta(hours=OBSERVATION_HOURS)
        remaining = max(0, round((end - now).total_seconds() / 3600, 1))
    incidents = [{'at': entry['at'], 'items': entry['critical_failures'] + entry['warnings'], 'critical': bool(entry['critical_failures'])}
                 for entry in mine if entry['critical_failures'] or entry['warnings']][-5:]
    return {'version': version, 'date': installed.get('date', ''), 'state': state, 'label': LABELS[state],
            'last_check': last['at'] if last else '', 'checks_run': len(mine), 'checks_passed': len(passes),
            'tests': [{'name': r['name'], 'ok': r['ok'], 'critical': r['critical']} for r in (last['results'] if last else [])],
            'passed': last['passed'] if last else 0, 'total': last['total'] if last else len(checks(c)),
            'incidents': incidents, 'observation_hours': OBSERVATION_HOURS, 'min_passes': MIN_PASSES, 'remaining_hours': remaining,
            'first_pass': passes[0]['at'] if passes else ''}
