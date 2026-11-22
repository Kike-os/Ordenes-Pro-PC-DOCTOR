"""Historial y reglas comunes de los respaldos de la base central (1.5.312): historial unificado, bloqueo contra ejecuciones
simultáneas, nombres, conservación 30/12/12, calendario y la copia anterior de la oficina. El proveedor (Google Drive) está en
gdrive_backup.py y el motor de copia, cifrado y verificación en backup_runner.py."""
import json
import secrets
from datetime import datetime, timedelta, timezone

ECUADOR = timezone(timedelta(hours=-5))
PREFIX = 'ordenes-pro-'
SUFFIX = '.sqlite.gz.enc'
SCHEDULE_HOUR = 2                      # 02:00, hora de Ecuador
LATE_HOURS = 30                        # un respaldo diario + margen
SPACE_WARN = 0.9                       # aviso con el 90 % del espacio de la nube ocupado
KEEP = {'diario': 30, 'semanal': 12, 'mensual': 12}
MAX_RUNS = 200
RUN_KINDS = {'respaldo': 'Respaldo', 'verificacion': 'Verificación', 'restauracion': 'Restauración de prueba'}


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


# ---------------------------------------------------------------- estado para el panel
def last_good(c):
    """Último respaldo CORRECTO Y VERIFICADO (restaurado en una base aislada), de la nube o de la copia local de la oficina."""
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
    if legacy and legacy.get('ok') and legacy.get('destination') not in ('onedrive', 'mega', 'gdrive') and legacy.get('sha256') and not any(item.get('sha256') == legacy['sha256'] for item in runs(c)):
        save_run(c, _legacy_entry(legacy))
