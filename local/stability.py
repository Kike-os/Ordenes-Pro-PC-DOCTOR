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
LABELS = {'unverified': 'Verificación pendiente', 'verifying': 'Verificando', 'observing': 'En observación', 'stable': 'Versión estable', 'attention': 'Incidencia detectada'}
SHORT = {'unverified': 'Pendiente', 'verifying': 'Verificando', 'observing': 'En observación', 'stable': 'Estable', 'attention': 'Incidencia'}


def _load(c, key, default):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (key,)).fetchone()
    try:
        return json.loads(row['value']) if row else default
    except (ValueError, TypeError):
        return default


def _save(c, key, value):
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))


SEVERITIES = ('crítica', 'alta', 'media', 'baja')
# Fallos que suelen ser pasajeros (red, servidor de base de datos ocupado): se reintentan una vez antes de registrarlos.
TRANSIENT = (ConnectionError, TimeoutError)


def _transient(error):
    import sqlite3
    if isinstance(error, TRANSIENT):
        return True
    if isinstance(error, sqlite3.OperationalError) and any(word in str(error).lower() for word in ('locked', 'busy', 'timeout', 'connection')):
        return True
    return getattr(error, 'kind', '') in ('red', 'temporal', 'conexion')


STATUS_LABELS = {'ok': 'Correcto', 'warning': 'Advertencia', 'error': 'Error', 'not_checked': 'No comprobado'}


def checks(c, deep=False, now=None):
    """Lista de (código, nombre, severidad, función) de los 13 servicios de Órdenes Pro. Cada función devuelve un detalle (Correcto),
    una tupla («warning» o «not_checked», detalle) o lanza una excepción (Error). Todas son de solo lectura: no crean, modifican ni
    borran datos. `deep` añade las que usan la red (inicio de sesión real en el buzón), solo en ejecuciones programadas o manuales."""
    if now is None:
        from reception import reception_now
        now = reception_now()

    def last_deep(code):
        """Último resultado de una comprobación que solo se hace en diagnósticos manuales o programados (correcto o error)."""
        for run in reversed(_load(c, 'stability_runs', [])):
            if run.get('source') not in ('manual', 'programada'):
                continue
            found = next((r for r in run['results'] if r['code'] == code and r.get('status', 'ok' if r['ok'] else 'error') in ('ok', 'error')), None)
            if found:
                return dict(found, at=run['at'], source=run['source'])
        return None

    def database():
        began = time.monotonic()
        c.execute('SELECT 1').fetchone()
        ms = round((time.monotonic() - began) * 1000)
        files = {p.name for p in (ROOT / 'migrations').glob('*.sql')}
        applied = {row[0] for row in c.execute('SELECT name FROM migrations')}
        missing = sorted(files - applied)
        if missing:
            raise RuntimeError('Faltan migraciones: ' + ', '.join(missing[:3]))
        detail = str(len(files)) + ' migraciones aplicadas · respuesta en ' + str(ms) + ' ms'
        return ('warning', detail + ' (respuesta lenta)') if ms > 1500 else detail

    def authentication():
        import secrets
        import app
        probe = secrets.token_urlsafe(18)
        if not app.password_ok(probe, app.password_hash(probe)) or app.password_ok(probe + 'x', app.password_hash(probe)):
            raise RuntimeError('La verificación de contraseñas no responde como se espera.')
        admins = c.execute("SELECT COUNT(*) FROM users WHERE role='administrador' AND active=1 AND approval='approved'").fetchone()[0]
        if not admins:
            raise RuntimeError('No hay ninguna cuenta de administración activa.')
        sessions = c.execute('SELECT COUNT(*) FROM sessions WHERE expires>?', (int(time.time()),)).fetchone()[0]
        return 'Cifrado de contraseñas correcto · ' + str(admins) + ' cuenta(s) de administración · ' + str(sessions) + ' sesión(es) vigentes'

    def clients():
        columns = {row[1] for row in c.execute('PRAGMA table_info(clients)')}
        missing = {'name', 'phone', 'email', 'identification'} - columns
        if missing:
            raise RuntimeError('Faltan campos del registro de clientes: ' + ', '.join(sorted(missing)))
        total, review = c.execute('SELECT COUNT(*),COALESCE(SUM(needs_review),0) FROM clients').fetchone()
        c.execute('SELECT id,name FROM clients ORDER BY id DESC LIMIT 5').fetchall()
        return str(total) + ' clientes · ' + str(review) + ' fichas por completar'

    def orders():
        import app
        import order_tracking
        import tracking_board
        from thermal_pdf import render_thermal
        if not c.execute('SELECT COUNT(*) FROM statuses').fetchone()[0]:
            raise RuntimeError('No hay estados de orden configurados.')
        began = time.monotonic()
        board = tracking_board.build(c, tracking_board.parse({}))
        board_ms = round((time.monotonic() - began) * 1000)
        serial = c.execute('SELECT value FROM order_serial WHERE id=1').fetchone()
        top = c.execute("SELECT MAX(daily_sequence) FROM orders WHERE number_date GLOB '[0-9]*'").fetchone()[0] or 0
        if serial is None or serial[0] < top:
            raise RuntimeError('El contador de órdenes está por detrás del último número asignado: riesgo de números repetidos.')
        row = c.execute('SELECT id FROM orders ORDER BY id DESC LIMIT 1').fetchone()
        # El ticket PDF (lo más pesado) se genera solo en los diagnósticos manuales y programados.
        ticket = 'ticket PDF no generado en verificaciones automáticas'
        if row and deep:
            began = time.monotonic()
            order = app.order_document(c, row['id'])
            order['tracking_url'] = order_tracking.active(c, row['id'])['url'] or app.public_base_url()
            if not render_thermal(order, 'cliente').startswith(b'%PDF'):
                raise RuntimeError('El ticket de la orden no se generó como PDF.')
            ticket = 'ticket PDF generado en ' + str(round((time.monotonic() - began) * 1000)) + ' ms'
        elif not row:
            ticket = 'sin órdenes para generar ticket'
        return str(board['total']) + ' órdenes en seguimiento (' + str(board_ms) + ' ms) · ' + ticket + ' · siguiente número ' + str(serial[0] + 1).zfill(4)

    def quotes():
        import app
        import quote_pdf
        import quotes as quote_module
        total = c.execute("SELECT COUNT(*) FROM quotes WHERE deleted_at=''").fetchone()[0]
        quote = c.execute("SELECT id,order_id FROM quotes WHERE deleted_at='' ORDER BY id DESC LIMIT 1").fetchone()
        if not quote:
            return 'Sin presupuestos registrados todavía'
        if not quote_pdf.render(quote_module.detail(c, quote_module.get(c, quote['id'])), app.order_document(c, quote['order_id'])).startswith(b'%PDF'):
            raise RuntimeError('El presupuesto no se generó como PDF.')
        return str(total) + ' presupuestos · PDF del más reciente generado'

    def licenses_check():
        import licenses
        probe = {'key': 'AUTOCARE-PRUEBA-0000'}
        if licenses.unseal(licenses.seal(probe)) != probe:
            raise RuntimeError('El cifrado de credenciales de licencias no responde como se espera.')
        board = licenses.dashboard(c, now)
        detail = str(board['disponibles']) + ' disponibles · ' + str(board['activas']) + ' activas · ' + str(board['por_vencer']) + ' por vencer · cifrado correcto'
        if board.get('revision'):
            return ('warning', str(board['revision']) + ' licencia(s) con datos inconsistentes (Licencias → Revisar inconsistencias) · ' + detail)
        return detail

    def sales():
        import equipment
        today = now.date()
        equipment.receivables(c, today - timedelta(days=30), today)
        mismatched = []
        for sale in c.execute("SELECT id,code,total_cents,payment_status FROM license_sales WHERE payment_status!='cancelado'").fetchall():
            paid = c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM license_sale_payments WHERE sale_id=? AND status='confirmado'", (sale['id'],)).fetchone()[0]
            expected = 'pagado' if paid >= sale['total_cents'] else 'parcial' if paid > 0 else 'pendiente'
            if expected != sale['payment_status']:
                mismatched.append(sale['code'])
        count = c.execute('SELECT COUNT(*) FROM license_sales').fetchone()[0]
        detail = 'Cobros y saldos consultados · ' + str(count) + ' venta(s) de licencias'
        if mismatched:
            return ('warning', 'Estado de pago distinto de los pagos confirmados en: ' + ', '.join(mismatched[:5]) + ' · ' + detail)
        return detail

    def agenda():
        import appointments
        began = time.monotonic()
        services = appointments.services(c)
        services_ms = round((time.monotonic() - began) * 1000)
        if not services:
            raise RuntimeError('La agenda no tiene servicios de cita.')
        day = (datetime.now(appointments.TZ).date() + timedelta(days=1)).isoformat()
        began = time.monotonic()
        slots = appointments.available_slots(c, day, services[0]['code'])
        slots_ms = round((time.monotonic() - began) * 1000)
        return str(len(services)) + ' servicios de cita (' + str(services_ms) + ' ms) · disponibilidad de mañana calculada: ' + str(len(slots)) + ' horarios (' + str(slots_ms) + ' ms)'

    def mail():
        import mail_pro
        try:
            ready = mail_pro.configured()
        except mail_pro.MailError:
            ready = False
        if not ready:
            raise RuntimeError('El correo del sistema no está configurado (faltan servidor, usuario o contraseña).')
        if deep:
            began = time.monotonic()
            mail_pro.test_imap()
            return 'Buzón accesible: autenticación IMAP correcta en ' + str(round((time.monotonic() - began) * 1000)) + ' ms'
        # Verificación automática: no abre el buzón (prueba omitida) y usa el último resultado real de las últimas 24 h.
        last = last_deep('mail')
        fresh = last and last['at'] >= (now - timedelta(hours=24)).isoformat(timespec='seconds')
        origin = lambda item: ('diagnóstico manual' if item['source'] == 'manual' else 'diagnóstico programado') + ' del ' + item['at'][8:10] + '/' + item['at'][5:7] + ' ' + item['at'][11:16]
        if fresh and last['status'] == 'error':
            raise RuntimeError('Fallo real en la última comprobación del buzón (' + origin(last) + '): ' + last['detail'])
        if fresh:
            return 'Buzón comprobado en el ' + origin(last) + ' · prueba omitida en esta verificación automática'
        return ('not_checked', 'Comprobación pendiente: el buzón no se ha comprobado en las últimas 24 h. Se comprueba en los diagnósticos manuales y programados.')

    def notices():
        import notifications
        admin = c.execute("SELECT * FROM users WHERE role='administrador' AND active=1 ORDER BY id LIMIT 1").fetchone()
        if not admin:
            raise RuntimeError('No hay ninguna cuenta de administración para recibir avisos.')
        items = notifications.build(c, dict(admin), now)
        failed = c.execute("SELECT COUNT(*) FROM license_notices WHERE status='error' AND created_at>=?", ((now - timedelta(hours=24)).isoformat(timespec='seconds'),)).fetchone()[0]
        detail = 'Centro de notificaciones operativo (' + str(len(items)) + ' avisos para administración)'
        if failed:
            return ('warning', str(failed) + ' aviso(s) de renovación con error de envío en 24 h · ' + detail)
        return detail

    def integrations():
        import adi_ai
        import remote_db
        info = adi_ai.status(c)
        parts = ['base de datos ' + ('en la nube' if remote_db.configured() else 'local')]
        parts.append('IA de ADI ' + ('no configurada (opcional)' if not info['configured'] else 'desactivada' if not info['enabled'] else 'con ' + str(info['provider'])))
        missing = []
        if os.getenv('VERCEL'):
            if not os.getenv('CRON_SECRET'):
                missing.append('CRON_SECRET (tareas programadas sin protección)')
            if not os.getenv('LICENSE_ENCRYPTION_KEY'):
                missing.append('LICENSE_ENCRYPTION_KEY (cifrado de licencias)')
        if missing:
            return ('warning', 'Falta configurar: ' + ', '.join(missing) + ' · ' + ' · '.join(parts))
        return 'Configuración revisada: ' + ' · '.join(parts) + ' (la IA no se llama para no generar costos)'

    def internal():
        registry = versioning.load()
        installed = registry['releases'][0]
        versioning.parse(installed['version'])
        for name in ('app.js', 'app.css', 'form-validation.js', 'licenses.js'):
            path = ROOT / 'static' / name
            if not path.exists() or path.stat().st_size < 1000:
                raise RuntimeError('Archivo de interfaz ausente: ' + name)
        for name in ('login.html', 'dashboard.html'):
            if not (ROOT / 'templates' / name).exists():
                raise RuntimeError('Plantilla ausente: ' + name)
        detail = 'Versión ' + installed['version'] + ' · compilación ' + (os.getenv('VERCEL_GIT_COMMIT_SHA', '') or 'local')[:7] + ' · interfaz y plantillas presentes'
        if os.getenv('VERCEL'):
            last = next((run for run in reversed(_load(c, 'stability_runs', [])) if run.get('source') == 'programada'), None)
            if not last or last['at'] < (now - timedelta(hours=12)).isoformat(timespec='seconds'):
                return ('warning', 'Las tareas programadas no se ejecutan desde ' + (last['at'][:16].replace('T', ' ') if last else 'hace más de 12 h') + ' · ' + detail)
        return detail

    def runtime_errors():
        import autocare
        recent = autocare.recent_errors(c, hours=1)
        if len(recent) >= 5:
            raise RuntimeError(str(len(recent)) + ' errores de ejecución en la última hora.')
        if recent:
            return ('warning', str(len(recent)) + ' error(es) de ejecución en la última hora (ver incidencias)')
        return 'Sin errores de ejecución en la última hora'

    return [('database', 'Conectividad con la base de datos', 'crítica', database), ('auth', 'Autenticación y sesiones', 'crítica', authentication),
            ('clients', 'Registro de clientes', 'alta', clients), ('orders', 'Órdenes de reparación', 'crítica', orders),
            ('quotes', 'Presupuestos', 'alta', quotes), ('licenses', 'Licencias e inventario', 'alta', licenses_check),
            ('sales', 'Ventas y pagos', 'alta', sales), ('agenda', 'Agenda y citas', 'crítica', agenda),
            ('mail', 'Envío de correos', 'media', mail), ('notifications', 'Notificaciones', 'media', notices),
            ('integrations', 'Integraciones configuradas', 'baja', integrations), ('internal', 'Servicios internos', 'crítica', internal),
            ('errors', 'Registros de errores', 'media', runtime_errors)]


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


def execute(code, name, severity, test):
    """Ejecuta una comprobación y devuelve su resultado: Correcto, Advertencia, No comprobado o Error. Un fallo transitorio se
    reintenta una sola vez tras 1,5 s (recuperación automática, sin tocar datos)."""
    began = time.monotonic()
    recovered = False

    def outcome(value):
        if isinstance(value, tuple) and value and value[0] in ('warning', 'not_checked'):
            return value[0], str(value[1])[:200]
        return 'ok', str(value)[:200]
    try:
        status, detail = outcome(test())
    except Exception as error:
        status, detail = 'error', (str(error) or type(error).__name__)[:200]
        if _transient(error):
            time.sleep(1.5)
            try:
                (status, detail), recovered = outcome(test()), True
            except Exception as again:
                detail = (str(again) or type(again).__name__)[:200]
        print('stability', code, type(error).__name__, 'recuperado' if recovered else '', flush=True)
    return {'code': code, 'name': name, 'severity': severity, 'critical': severity == 'crítica', 'ok': status != 'error', 'status': status,
            'detail': detail, 'recovered': recovered, 'ms': round((time.monotonic() - began) * 1000)}


def finish(c, now, source, results, total_ms, by=''):
    """Registra una ejecución completa (detalle y resumen de la versión) y avisa a AutoCare. Devuelve la ejecución."""
    version = versioning.load()['releases'][0]['version']
    counts = {key: sum(1 for r in results if r.get('status', 'ok' if r['ok'] else 'error') == key) for key in STATUS_LABELS}
    entry = {'version': version, 'at': now.isoformat(timespec='seconds'), 'source': source, 'by': by, 'passed': sum(1 for r in results if r['ok']), 'total': len(results),
             'critical_failures': [r['name'] for r in results if r['critical'] and not r['ok']], 'warnings': [r['name'] for r in results if not r['critical'] and not r['ok']],
             'advisories': [r['name'] for r in results if r.get('status') == 'warning'], 'unchecked': [r['name'] for r in results if r.get('status') == 'not_checked'],
             'counts': counts, 'results': results, 'ms': total_ms}
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
    try:
        import autocare
        autocare.after_run(c, entry, summary, history[:-1], now)
        c.commit()
    except Exception as error:
        print('autocare', type(error).__name__, flush=True)
    return entry


def run(c, now, source='automática', by=''):
    """Ejecuta todas las verificaciones y registra el resultado (ejecución detallada y resumen de la versión). Devuelve la ejecución."""
    version = versioning.load()['releases'][0]['version']
    _save(c, 'stability_running', {'version': version, 'since': now.isoformat(timespec='seconds')})
    c.commit()
    began_all = time.monotonic()
    try:
        results = [execute(*item) for item in checks(c, source in ('programada', 'manual'), now)]
    finally:
        c.execute("DELETE FROM system_state WHERE key='stability_running'")
    return finish(c, now, source, results, round((time.monotonic() - began_all) * 1000), by)


# ---- Diagnóstico manual paso a paso: el panel muestra el progreso real (cada paso ejecuta una comprobación en el servidor) ----
def start_manual(c, now, by):
    import secrets
    version = versioning.load()['releases'][0]['version']
    plan = [{'code': code, 'name': name, 'severity': severity} for code, name, severity, _ in checks(c, True)]
    state = {'id': secrets.token_hex(8), 'version': version, 'since': now.isoformat(timespec='seconds'), 'by': by, 'plan': plan, 'results': [], 'ms': 0}
    _save(c, 'stability_manual', state)
    _save(c, 'stability_running', {'version': version, 'since': now.isoformat(timespec='seconds')})
    return {'id': state['id'], 'plan': plan}


def step_manual(c, now, run_id, code):
    """Ejecuta la siguiente comprobación del diagnóstico en curso. Al completar la última, registra la ejecución."""
    state = _load(c, 'stability_manual', None)
    if not state or state.get('id') != run_id or state['since'] < (now - timedelta(minutes=10)).isoformat(timespec='seconds'):
        raise ValueError('El diagnóstico ya no está en curso. Vuelve a iniciarlo.')
    done = len(state['results'])
    if done >= len(state['plan']) or state['plan'][done]['code'] != code:
        raise ValueError('Comprobación fuera de orden.')
    item = next(entry for entry in checks(c, True, now) if entry[0] == code)
    result = execute(*item)
    state['results'].append(result)
    state['ms'] += result['ms']
    if len(state['results']) < len(state['plan']):
        _save(c, 'stability_manual', state)
        _save(c, 'stability_running', {'version': state['version'], 'since': now.isoformat(timespec='seconds')})
        return {'result': result, 'done': False}
    c.execute("DELETE FROM system_state WHERE key IN ('stability_manual','stability_running')")
    entry = finish(c, now, 'manual', state['results'], state['ms'], state.get('by', ''))
    return {'result': result, 'done': True, 'entry': {key: entry[key] for key in ('at', 'passed', 'total', 'counts', 'critical_failures', 'warnings', 'advisories', 'unchecked')}}


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
    remaining, missing, end = None, max(0, MIN_PASSES - summary['window_passes']), None
    # Una prueba no crítica fallida en la última verificación no reinicia el período, pero impide declarar la versión estable.
    clean = bool(last) and not last['warnings'] and not last['critical_failures']
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
        state = 'stable' if complete and not missing and clean else 'observing'
    incidents = [{'at': item['at'], 'items': item['items'], 'critical': True} for item in summary['criticals']]
    incidents += [{'at': entry['at'], 'items': entry['warnings'], 'critical': False} for entry in history if entry['version'] == version and entry['warnings'] and not entry['critical_failures']]
    incidents = sorted(incidents, key=lambda item: item['at'])[-5:]
    previous = [{'version': key, 'runs': value['runs'], 'passes': value['passes'], 'last_run': value['last_run'], 'stable': bool(value['window_start']) and value['window_passes'] >= MIN_PASSES
                 and datetime.fromisoformat(value['window_start']) + timedelta(hours=OBSERVATION_HOURS) <= datetime.fromisoformat(value['last_run'])}
                for key, value in sorted(_known(c, history).items(), key=lambda pair: pair[1]['last_run'], reverse=True) if key != version][:5]
    return {'version': version, 'date': installed.get('date', ''), 'state': state, 'label': LABELS[state], 'short': SHORT[state],
            'last_check': summary['last_run'], 'checks_run': summary['runs'], 'checks_passed': summary['passes'],
            'window_start': summary['window_start'], 'window_passes': summary['window_passes'], 'missing_passes': missing,
            'tests': [{'name': r['name'], 'ok': r['ok'], 'status': r.get('status', 'ok' if r['ok'] else 'error'), 'critical': r['critical'], 'severity': r.get('severity', 'crítica' if r['critical'] else 'media'), 'recovered': r.get('recovered', False)} for r in (last['results'] if last else [])],
            'passed': last['passed'] if last else 0, 'total': last['total'] if last else len(checks(c)),
            'incidents': incidents, 'observation_hours': OBSERVATION_HOURS, 'min_passes': MIN_PASSES, 'remaining_hours': remaining,
            'first_pass': summary['window_start'], 'next_scheduled': next_scheduled(now), 'previous': previous,
            'window_end': end.isoformat(timespec='seconds') if end else '', 'clean': clean, 'server_time': now.isoformat(timespec='seconds')}
