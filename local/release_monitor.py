"""ADI Release Monitor 2.0: complementa el motor de estabilidad (stability.py) sin cambiar sus reglas.

- Cuatro comprobaciones adicionales de SOLO LECTURA (migraciones, interfaz, facturación electrónica y WhatsApp Business): no envían
  mensajes, no emiten comprobantes, no llaman a servicios externos y no escriben en la base.
- Detalle técnico para administración (resultado, tiempo y detalle de cada comprobación, incidencias con resolución, tareas programadas,
  informe copiable). La ventana pública sigue mostrando solo datos públicos.
- Avisos para el Centro de Notificaciones con clave estable (sin duplicados): versión en observación, versión estable y tarea
  programada no recibida. Las incidencias ya las avisa ADI AutoCare.
"""
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND_FILES = ('app.js', 'app.css', 'i18n.js', 'ui-select.js', 'inventory.js', 'adi-widget.js', 'logo-original.png')
TEMPLATES = ('dashboard.html',)


def _table(c, name):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def migrations_check(c):
    """Migraciones publicadas frente a las aplicadas en la base (sin aplicar nada)."""
    files = sorted(p.name for p in (ROOT / 'migrations').glob('*.sql'))
    applied = {row[0] for row in c.execute('SELECT name FROM migrations')}
    pending = [name for name in files if name not in applied]
    if pending:
        return ('warning', '%d de %d migraciones aplicadas · pendiente%s: %s (se aplican desde Sistema)' % (
            len(files) - len(pending), len(files), 's' if len(pending) > 1 else '', ', '.join(name.split('_', 1)[0] for name in pending[:6])))
    return '%d de %d migraciones aplicadas' % (len(files), len(files))


def frontend_check(c):
    """Archivos de la interfaz desplegados y legibles (no vacíos)."""
    missing = [name for name in FRONTEND_FILES if not (ROOT / 'static' / name).is_file() or (ROOT / 'static' / name).stat().st_size == 0]
    missing += ['plantilla ' + name for name in TEMPLATES if not (ROOT / 'templates' / name).is_file()]
    if missing:
        raise RuntimeError('Faltan archivos de la interfaz: ' + ', '.join(missing))
    size = sum((ROOT / 'static' / name).stat().st_size for name in FRONTEND_FILES)
    return '%d archivos principales de la interfaz disponibles (%s KB)' % (len(FRONTEND_FILES), format(round(size / 1024), ',').replace(',', '.'))


def invoicing_check(c):
    """Facturación electrónica: configuración, bloqueo de emisión y comprobantes rechazados recientes. No consulta a AZUR ni al SRI."""
    if not _table(c, 'invoice_settings'):
        return ('not_checked', 'La facturación electrónica no está instalada en esta base.')
    import invoicing
    cfg = invoicing.settings(c)
    since = (datetime.now(invoicing_tz()) - timedelta(days=7)).isoformat(timespec='seconds')
    rejected = c.execute("SELECT COUNT(*) FROM invoices WHERE status='rechazado' AND updated_at>=?", (since,)).fetchone()[0] if _has_column(c, 'invoices', 'updated_at') else 0
    waiting = c.execute("SELECT COUNT(*) FROM invoices WHERE status IN ('pendiente','enviado')").fetchone()[0]
    env = cfg['emission']['environment_label']
    lock = 'emisión bloqueada' if cfg['emission_lock']['locked'] else 'emisión habilitada'
    base = '%s · %s · %d en trámite' % (env, lock, waiting)
    if cfg['missing']:
        return ('warning', base + ' · faltan datos fiscales: ' + ', '.join(cfg['missing']))
    if rejected:
        return ('warning', base + ' · %d rechazado%s en los últimos 7 días' % (rejected, 's' if rejected > 1 else ''))
    return base


def whatsapp_check(c):
    """WhatsApp Business: configuración presente (sin mostrar credenciales), uso del mes frente a los límites y envíos fallidos recientes."""
    import whatsapp_business as wa
    if not wa.ready():
        return ('not_checked', 'WhatsApp Business no está configurado en este servidor.')
    if not _table(c, 'whatsapp_outbox'):
        return ('not_checked', 'Falta la tabla de envíos de WhatsApp.')
    now = datetime.now(invoicing_tz())
    used, limit = wa.monthly_outbound_count(c, now), wa.MAX_MONTHLY_WA_MESSAGES
    since = (now - timedelta(hours=24)).isoformat(timespec='seconds')
    sent, failed = c.execute("SELECT COALESCE(SUM(status IN ('enviado','entregado','leido')),0),COALESCE(SUM(status='fallido'),0) FROM whatsapp_outbox WHERE created_at>=?", (since,)).fetchone()
    base = 'Configurado · %d de %d envíos este mes · últimas 24 h: %d enviados, %d fallidos' % (used, limit, sent or 0, failed or 0)
    if used >= limit:
        return ('warning', base + ' · límite mensual alcanzado')
    if failed and failed >= max(3, sent or 0):
        return ('warning', base + ' · revisa los envíos fallidos en Integraciones')
    return base


def invoicing_tz():
    from reception import ECUADOR_TZ
    return ECUADOR_TZ


def _has_column(c, table, column):
    return any(row[1] == column for row in c.execute('PRAGMA table_info(%s)' % table))


def extra_checks():
    """Comprobaciones añadidas por Release Monitor 2.0 (código, nombre, gravedad, prueba)."""
    return [('migrations', 'Migraciones de la base de datos', 'alta', None), ('frontend', 'Interfaz y archivos estáticos', 'alta', None),
            ('invoicing', 'Facturación electrónica', 'media', None), ('whatsapp', 'WhatsApp Business', 'media', None)]


def bind(c):
    """Las mismas comprobaciones con su función, enlazadas a la conexión."""
    tests = {'migrations': migrations_check, 'frontend': frontend_check, 'invoicing': invoicing_check, 'whatsapp': whatsapp_check}
    return [(code, name, severity, (lambda fn=tests[code]: fn(c))) for code, name, severity, _ in extra_checks()]


# ---- Detalle técnico para administración ------------------------------------------------------------------------------------------------

COMPONENTS = {'database': 'Base de datos', 'auth': 'Autenticación y seguridad', 'clients': 'Clientes', 'orders': 'Órdenes de reparación', 'quotes': 'Presupuestos',
              'licenses': 'Licencias e inventario', 'sales': 'Ventas y pagos', 'agenda': 'Agenda', 'mail': 'Correo', 'notifications': 'Notificaciones',
              'integrations': 'Servicios externos', 'ai': 'ADI Intelligence', 'internal': 'Backend y tareas programadas', 'backups': 'Respaldos automáticos',
              'errors': 'Backend y API', 'migrations': 'Migraciones', 'frontend': 'Frontend', 'invoicing': 'Facturación electrónica', 'whatsapp': 'WhatsApp Business'}


def compare_runs(history, version):
    """Compare the latest run with the preceding run of the same version."""
    current = [entry for entry in history if entry['version'] == version][-2:]
    if len(current) < 2:
        return {'available': False, 'changes': []}
    before, after = current
    def statuses(run):
        return {result['code']: (result['name'], result.get('status', 'ok' if result['ok'] else 'error'))
                for result in run['results']}
    old, new = statuses(before), statuses(after)
    changes = []
    for code in sorted(old.keys() | new.keys()):
        previous = old.get(code)
        latest = new.get(code)
        from_status = previous[1] if previous else 'absent'
        to_status = latest[1] if latest else 'absent'
        if from_status != to_status:
            changes.append({'code': code, 'name': (latest or previous)[0], 'before': from_status, 'after': to_status})
    return {'available': True, 'from_at': before['at'], 'to_at': after['at'], 'changes': changes}


def details(c, now):
    """Datos ampliados de la ventana para administración: cada comprobación con su detalle, incidencias con resolución y tareas programadas."""
    import stability
    import autocare
    info = stability.status(c, now)
    history = stability._load(c, 'stability_runs', [])
    last = next((entry for entry in reversed(history) if entry['version'] == info['version']), None)
    tests = [{'code': r['code'], 'name': r['name'], 'component': COMPONENTS.get(r['code'], r['name']), 'status': r.get('status', 'ok' if r['ok'] else 'error'),
              'severity': r.get('severity', ''), 'critical': r['critical'], 'detail': r.get('detail', ''), 'ms': r.get('ms'), 'recovered': r.get('recovered', False)}
             for r in (last['results'] if last else [])]
    incidents = []
    for item in autocare.incidents(c)[-25:][::-1]:
        note = next((h['note'] for h in reversed(item.get('history', [])) if h.get('status') == 'resuelta'), '')
        incidents.append({'code': item['code'], 'at': item['first_at'], 'last_at': item['last_at'], 'component': item['service'], 'severity': item['severity'],
                          'description': item['description'], 'cause': item.get('cause', ''), 'action': item.get('action', ''), 'status': item['status'],
                          'resolution': note if item['status'] == 'resuelta' else '', 'resolved_at': item.get('resolved_at', ''), 'count': item['count'],
                          'version': item.get('version', '')})
    last_cron = stability.last_cron(c)
    missed = bool(last_cron) and last_cron < (now - timedelta(hours=stability.CRON_GRACE_HOURS)).isoformat(timespec='seconds')
    runs = [{'at': entry['at'], 'version': entry['version'], 'source': entry.get('source', ''), 'by': entry.get('by', ''), 'passed': entry['passed'], 'total': entry['total'],
             'critical': entry['critical_failures'], 'warnings': entry['warnings'], 'ms': entry.get('ms')} for entry in history[-12:][::-1]]
    return dict(info, comparison=compare_runs(history, info['version']), detail_tests=tests, detail_incidents=incidents, runs=runs, last_cron=last_cron, cron_missed=missed,
                last_source=last.get('source', '') if last else '', last_by=last.get('by', '') if last else '', last_ms=last.get('ms') if last else None,
                schedule='01:00, 09:00 y 17:00 (hora de Ecuador)', report=report(info, tests, incidents, last_cron, missed))


def report(info, tests, incidents, last_cron, missed):
    """Informe técnico en texto plano para copiar. Sin credenciales ni datos de clientes."""
    mark = {'ok': 'OK', 'warning': 'ADVERTENCIA', 'error': 'ERROR', 'not_checked': 'NO COMPROBADO', 'unavailable': 'NO DISPONIBLE'}
    lines = ['ADI Release Monitor 2.0 · Órdenes Pro · PC-DOCTOR S.A.', 'Versión: v%s · Estado: %s' % (info['version'], info['label']),
             'Hora del servidor: %s (America/Guayaquil)' % info['server_time'], 'Última verificación: %s' % (info['last_check'] or 'sin resultados'),
             'Próxima programada: %s' % (info['next_scheduled'] or '—'), 'Última tarea programada recibida: %s%s' % (last_cron or '—', ' · NO SE RECIBEN TAREAS PROGRAMADAS' if missed else ''),
             'Seguimiento: %s de %s verificaciones correctas · inicio %s · fin %s' % (info['window_passes'], info['min_passes'], info['window_start'] or '—', info['window_end'] or '—'), '',
             'Comprobaciones (%d de %d superadas):' % (info['passed'], info['total'])]
    for t in tests:
        lines.append('- [%s] %s (%s, %s ms): %s' % (mark.get(t['status'], t['status']), t['name'], t['severity'], t['ms'] if t['ms'] is not None else '—', t['detail']))
    lines += ['', 'Incidencias registradas:']
    lines += ['- %s · %s · %s · %s · %s%s' % (i['code'], i['at'], i['component'], i['severity'], i['description'], (' · Resolución: ' + i['resolution']) if i['resolution'] else ' · ' + i['status'])
              for i in incidents[:15]] or ['- Ninguna.']
    return '\n'.join(lines)


# ---- Avisos al Centro de Notificaciones -------------------------------------------------------------------------------------------------

def notifications(c, now):
    """Avisos sin duplicados (clave estable por versión o por día). Solo lectura."""
    import stability
    items = []
    try:
        info = stability.status(c, now)
    except Exception as error:
        print('release monitor avisos', type(error).__name__, flush=True)
        return items
    version, link = info['version'], '#system?autocare=1'
    if info['state'] == 'observing':
        items.append({'key': 'release:observing:' + version, 'kind': 'info', 'icon': 'status', 'title': 'Versión v%s en observación' % version,
                      'detail': '%d de %d verificaciones correctas; la versión se declara estable tras %d h de seguimiento sin incidencias.' % (info['window_passes'], info['min_passes'], info['observation_hours']),
                      'at': info['first_pass'] or info['last_check'] or info['server_time'], 'href': link, 'group': 'event'})
    elif info['state'] == 'stable':
        items.append({'key': 'release:stable:' + version, 'kind': 'success', 'icon': 'check', 'title': 'Versión v%s estable' % version,
                      'detail': 'Superó %d verificaciones y %d h de seguimiento sin incidencias.' % (info['window_passes'], info['observation_hours']),
                      'at': info['window_end'] or info['last_check'], 'href': link, 'group': 'event'})
    last_cron = stability.last_cron(c)
    if last_cron and last_cron < (now - timedelta(hours=stability.CRON_GRACE_HOURS)).isoformat(timespec='seconds'):
        items.append({'key': 'release:cron-missed:' + last_cron[:13], 'kind': 'warning', 'icon': 'alert', 'title': 'Verificación programada no recibida',
                      'detail': 'La última tarea programada llegó el %s. Revisa las tareas programadas del servidor (Vercel Cron).' % last_cron[:16].replace('T', ' '),
                      'at': now.isoformat(timespec='seconds'), 'href': link, 'group': 'alert'})
    return items
