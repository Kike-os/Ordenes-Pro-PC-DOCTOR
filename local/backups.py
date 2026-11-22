"""Respaldos de la base central en MEGA Cloud — 1.5.311 (sustituye a la integración con Microsoft OneDrive).

Reparto de funciones:
  · El AGENTE de respaldos (maintenance/backup-cloud.py en el equipo de la oficina, con MEGAcmd OFICIAL dentro de un contenedor) hace
    la copia consistente, la cifra (AES-256-GCM), la sube a MEGA, la DESCARGA de nuevo, compara el SHA-256 y la restaura en una base
    aislada. Si MEGA o internet fallan, el archivo cifrado queda PENDIENTE en el disco del equipo y se reintenta automáticamente.
  · El SERVIDOR (este módulo) guarda el historial, el estado que informa el agente y las órdenes que deja el panel (respaldo ahora,
    verificar, restaurar aislado, descargar, espacio, carpeta, reintentar). Nunca recibe la contraseña ni la sesión de MEGA.

La sesión de MEGA vive solo en el equipo del agente (inicio de sesión hecho una vez en su terminal). Ni el navegador ni el servidor
guardan credenciales de MEGA.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone

ECUADOR = timezone(timedelta(hours=-5))
FOLDER = 'PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos'
PREFIX = 'ordenes-pro-'
SUFFIX = '.sqlite.gz.enc'
SCHEDULE_HOUR = 2                      # 02:00, hora de Ecuador
LATE_HOURS = 30                        # un respaldo diario + margen
AGENT_SILENT_MINUTES = 10              # sin señal del agente en este tiempo: «sin conexión»
PENDING_WARN_HOURS = 2                 # un pendiente más antiguo que esto genera alerta
SPACE_WARN = 0.9                       # aviso con el 90 % del espacio de MEGA ocupado
KEEP = {'diario': 30, 'semanal': 12, 'mensual': 12}
MAX_RUNS = 200
MAX_REQUESTS = 40
RUN_KINDS = {'respaldo': 'Respaldo', 'verificacion': 'Verificación', 'restauracion': 'Restauración de prueba'}
ACTIONS = {'respaldo': 'Realizar respaldo ahora', 'verificar': 'Verificar respaldo', 'restaurar': 'Restaurar en entorno aislado',
           'descargar': 'Preparar descarga', 'espacio': 'Verificar conexión y espacio', 'carpeta': 'Crear carpeta de respaldos',
           'reintentar': 'Reintentar subidas pendientes'}


class BackupError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(ECUADOR)


def stamp(moment=None):
    return (moment or now()).isoformat(timespec='seconds')


# ---------------------------------------------------------------- estado en system_state
def get_state(c, key, default=None):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except ValueError:
        return default


def set_state(c, key, value):
    c.execute("INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))


def runs(c):
    value = get_state(c, 'backup_runs', [])
    return value if isinstance(value, list) else []


def save_run(c, run):
    """Añade o actualiza un registro del historial (más reciente primero). Nunca borra respaldos: solo acota el historial visible."""
    items = [item for item in runs(c) if item.get('id') != run['id']]
    items.insert(0, run)
    items.sort(key=lambda item: item.get('requested_at') or item.get('started_at') or '', reverse=True)
    set_state(c, 'backup_runs', items[:MAX_RUNS])
    c.commit()
    return run


def new_run(kind, trigger, destination, requested_by=None, file=''):
    return {'id': 'r' + now().strftime('%Y%m%d%H%M%S') + secrets.token_hex(3), 'kind': kind, 'trigger': trigger, 'destination': destination,
            'status': 'en_curso', 'requested_at': stamp(), 'requested_by': requested_by, 'started_at': stamp(), 'finished_at': '', 'file': file,
            'bytes': 0, 'raw_bytes': 0, 'sha256': '', 'tier': '', 'verified': False, 'verify': None, 'error': '', 'runner': ''}


def acquire_lock(c, owner, minutes=45):
    """Impide respaldos simultáneos: un único dueño hasta que termina o vence el plazo (si el proceso murió sin liberarlo)."""
    until = (now() + timedelta(minutes=minutes)).isoformat(timespec='seconds')
    c.execute("INSERT INTO system_state(key,value) VALUES ('backup_lock',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value "
              "WHERE json_extract(system_state.value,'$.until') < ? OR json_extract(system_state.value,'$.owner') = ?",
              (json.dumps({'owner': owner, 'until': until}), stamp(), owner))
    c.commit()
    return (get_state(c, 'backup_lock', {}) or {}).get('owner') == owner


def release_lock(c, owner):
    c.execute("DELETE FROM system_state WHERE key='backup_lock' AND json_extract(value,'$.owner')=?", (owner,))
    c.commit()


# ---------------------------------------------------------------- nombres, conservación y calendario
def tier(moment):
    if moment.day == 1:
        return 'mensual'
    if moment.isoweekday() == 1:
        return 'semanal'
    return 'diario'


def file_name(moment):
    return PREFIX + moment.strftime('%Y%m%d-%H%M%S') + '-' + tier(moment) + SUFFIX


def moment_of(name):
    try:
        return datetime.strptime(name[len(PREFIX):len(PREFIX) + 15], '%Y%m%d-%H%M%S').replace(tzinfo=ECUADOR)
    except ValueError:
        return None


def retention(names):
    """Abuelo-padre-hijo sobre las fechas: el último respaldo de cada uno de los 30 días, 12 semanas y 12 meses más recientes con
    respaldo. Devuelve los nombres que sobran; nunca incluye archivos ajenos a Órdenes Pro."""
    dated = sorted(((moment_of(n), n) for n in names if n.startswith(PREFIX) and n.endswith(SUFFIX) and moment_of(n)), reverse=True)
    keep = set()
    for key, limit in ((lambda m: m.date(), KEEP['diario']), (lambda m: m.isocalendar()[:2], KEEP['semanal']), (lambda m: (m.year, m.month), KEEP['mensual'])):
        seen = []
        for moment, name in dated:
            k = key(moment)
            if k in seen:
                continue
            seen.append(k)
            if len(seen) > limit:
                break
            keep.add(name)
    return [name for _, name in dated if name not in keep]


def next_run(moment=None):
    moment = moment or now()
    target = moment.replace(hour=SCHEDULE_HOUR, minute=0, second=0, microsecond=0)
    return target if target > moment else target + timedelta(days=1)


# ---------------------------------------------------------------- órdenes del panel al agente
def requests(c):
    value = get_state(c, 'backup_requests', [])
    return value if isinstance(value, list) else []


def request(c, user_id, action, file=''):
    """El panel deja la orden; el agente la recoge en menos de un minuto y anota el resultado. Sin duplicar órdenes en curso."""
    if action not in ACTIONS:
        raise BackupError('Operación de respaldo no válida.', 400)
    if action in ('verificar', 'restaurar', 'descargar') and not any(item.get('file') == file and item.get('destination') == 'mega' and item.get('status') == 'correcto' for item in runs(c)):
        raise BackupError('Elige un respaldo de MEGA verificado del historial.', 400)
    agent = get_state(c, 'mega_agent')
    if not agent:
        raise BackupError('El agente de respaldos todavía no está instalado en el equipo de la oficina.', 409)
    items = requests(c)
    if any(item.get('status') in ('pendiente', 'en_curso') and item.get('action') == action and item.get('file', '') == file for item in items):
        raise BackupError('Esa operación ya está solicitada; el agente la está atendiendo.', 409)
    entry = {'id': 'q' + now().strftime('%Y%m%d%H%M%S') + secrets.token_hex(3), 'action': action, 'file': file, 'requested_by': user_id,
             'requested_at': stamp(), 'status': 'pendiente', 'result': '', 'finished_at': ''}
    items.insert(0, entry)
    set_state(c, 'backup_requests', items[:MAX_REQUESTS])
    c.commit()
    return entry


def agent_online(agent, moment=None):
    if not agent or not agent.get('seen_at'):
        return False
    try:
        return (moment or now()) - datetime.fromisoformat(agent['seen_at']) <= timedelta(minutes=AGENT_SILENT_MINUTES)
    except ValueError:
        return False


# ---------------------------------------------------------------- estado para el panel
def last_good(c):
    """Último respaldo CORRECTO Y VERIFICADO (restaurado en una base aislada), de MEGA o de la copia local de la oficina."""
    good = [item for item in runs(c) if item.get('kind') == 'respaldo' and item.get('status') == 'correcto' and item.get('verified')]
    if good:
        return max(good, key=lambda item: item.get('finished_at') or '')
    legacy = get_state(c, 'cloud_backup')
    if legacy and legacy.get('ok'):
        return _legacy_entry(legacy)
    return None


def _legacy_entry(legacy):
    return {'id': 'legado-' + (legacy.get('at') or ''), 'kind': 'respaldo', 'trigger': 'programado', 'destination': 'equipo', 'status': 'correcto', 'verified': True,
            'finished_at': legacy.get('at', ''), 'started_at': legacy.get('at', ''), 'requested_at': legacy.get('at', ''), 'bytes': legacy.get('bytes', 0),
            'sha256': legacy.get('sha256', ''), 'file': '', 'legacy': True,
            'verify': {'integrity': 'ok', 'foreign_key_errors': 0, 'clients': legacy.get('clients', 0), 'orders': legacy.get('orders', 0)}}


def keep_legacy(c):
    """Antes de sobrescribir el resumen anterior (cloud_backup), conserva en el historial la copia que solo constaba allí."""
    legacy = get_state(c, 'cloud_backup')
    if legacy and legacy.get('ok') and legacy.get('destination') not in ('onedrive', 'mega') and legacy.get('sha256') and not any(item.get('sha256') == legacy['sha256'] for item in runs(c)):
        save_run(c, _legacy_entry(legacy))


def overview(c):
    items = runs(c)
    agent = get_state(c, 'mega_agent') or None
    local = next((item for item in items if item.get('destination') == 'equipo' and item.get('kind') == 'respaldo' and item.get('status') == 'correcto'), None)
    legacy = get_state(c, 'cloud_backup')
    history = list(items)
    if legacy and legacy.get('ok') and legacy.get('destination') not in ('onedrive', 'mega') and not any(item.get('sha256') and item.get('sha256') == legacy.get('sha256') for item in items):
        entry = _legacy_entry(legacy)
        history.append(entry)
        history.sort(key=lambda item: item.get('requested_at') or item.get('finished_at') or '', reverse=True)
        if not local or (entry['finished_at'] > (local.get('finished_at') or '')):
            local = entry
    mega_ok = next((item for item in items if item.get('destination') == 'mega' and item.get('kind') == 'respaldo' and item.get('status') == 'correcto' and item.get('verified')), None)
    public_agent = None
    if agent:
        public_agent = {key: agent.get(key) for key in ('seen_at', 'host', 'version', 'mega_version', 'connected', 'account', 'space', 'folder', 'folder_ok', 'pending', 'last_error', 'schedule')}
        public_agent['online'] = agent_online(agent)
    downloads = [item for item in (get_state(c, 'mega_downloads', []) or []) if (item.get('expires_at') or '') > stamp()]
    return {'folder': FOLDER, 'agent': public_agent, 'last_local': local, 'last_mega': mega_ok, 'last_good': last_good(c),
            'next_run': next_run().isoformat(timespec='seconds'), 'late_hours': LATE_HOURS, 'keep': KEEP, 'runs': history[:60],
            'requests': requests(c)[:12], 'downloads': downloads, 'actions': ACTIONS}


def alerts(c, moment=None):
    """Alertas reales y separadas. Se retiran solas cuando se corrige la causa (nuevo respaldo verificado, subida hecha, etc.)."""
    moment = moment or now()
    out = []
    good = last_good(c)
    try:
        age = (moment - datetime.fromisoformat(good['finished_at'])).total_seconds() / 3600 if good and good.get('finished_at') else None
    except ValueError:
        age = None
    if age is None or age > LATE_HOURS:
        out.append({'key': 'backup:late:' + moment.date().isoformat(), 'kind': 'warning', 'title': 'Respaldo de la base central atrasado',
                    'detail': ('El último respaldo correcto y verificado es del ' + good['finished_at'][:10] + '.') if good else 'Todavía no se registra ningún respaldo correcto y verificado.'})
    agent = get_state(c, 'mega_agent')
    latest = next((item for item in runs(c) if item.get('destination') == 'mega' and item.get('kind') == 'respaldo' and item.get('status') in ('correcto', 'error')), None)
    if latest and latest['status'] == 'error':
        out.append({'key': 'backup:failed:' + latest['id'], 'kind': 'warning', 'title': 'Falló el último respaldo en MEGA', 'detail': (latest.get('error') or 'Error sin detalle.')[:180]})
    if agent:
        pending = agent.get('pending') or []
        old = [item for item in pending if item.get('created_at') and (moment - datetime.fromisoformat(item['created_at'])).total_seconds() > PENDING_WARN_HOURS * 3600]
        if old:
            out.append({'key': 'backup:pending:' + old[-1].get('file', ''), 'kind': 'warning', 'title': 'Respaldos pendientes de subir a MEGA',
                        'detail': '%d respaldo(s) cifrado(s) esperan en el equipo de la oficina. Último error: %s' % (len(pending), (old[-1].get('last_error') or 'sin detalle')[:120])})
        if not agent_online(agent, moment):
            out.append({'key': 'backup:agent:' + moment.date().isoformat(), 'kind': 'info', 'title': 'Agente de respaldos sin señal',
                        'detail': 'El equipo de la oficina no informa desde ' + (agent.get('seen_at') or '')[:16].replace('T', ' ') + ' (apagado o sin internet). Los respaldos a MEGA se reanudarán al encenderlo.'})
        elif agent.get('connected') is False:
            reason = agent.get('last_error') or 'El agente no tiene sesión iniciada en MEGA.'
            out.append({'key': 'backup:mega-off:' + moment.date().isoformat(), 'kind': 'warning', 'title': 'MEGA desconectado',
                        'detail': reason[:160] + ' Los respaldos se guardan cifrados en el equipo y se suben al reconectar.'})
        space = agent.get('space') or {}
        if space.get('total') and space.get('used', 0) / space['total'] >= SPACE_WARN:
            out.append({'key': 'backup:space:' + moment.date().isoformat(), 'kind': 'warning', 'title': 'Espacio en MEGA casi lleno',
                        'detail': 'Ocupado el %d %% de la cuenta MEGA.' % round(100 * space['used'] / space['total'])})
    return out
