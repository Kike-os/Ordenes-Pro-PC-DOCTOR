"""PC-DOCTOR — Database Guardian Pro 1.0 · Self-Healing & Migration Control (docs/DATABASE-GUARDIAN.md).

Migration Manager: el estado de cada migración se determina con evidencia, no comparando cantidades:
- registro en `migrations` (nombre) y, desde 1.5.331, en `migration_ledger` (checksum SHA-256, fecha, duración, resultado, versión, ejecutor);
- verificación del esquema: cada tabla e índice que la migración crea existe, y cada tabla tiene las columnas que declara;
- checksum del archivo frente al del MANIFIESTO publicado (local/migrations/MANIFEST.json) y al registrado al aplicarla.
Estados: verificada · pendiente · incompleta (registrada, pero falta parte de su estructura) · sin_registro (su estructura existe pero no
está registrada: aplicada a medias o a mano) · modificada (el archivo cambió después de publicarse o de aplicarse) · duplicada.

Ejecución controlada: bloqueo distribuido en system_state (una sola ejecución a la vez entre instancias de Vercel, con caducidad), cada
migración en una sola petición atómica (BEGIN IMMEDIATE … COMMIT), registro y libro mayor dentro de la misma transacción, verificación
posterior de la estructura y recuento de filas antes y después. Nunca se marca aplicada una migración que no terminó.

Recuperación segura (self-healing): solo operaciones sin riesgo — repetir comprobaciones de LECTURA con reintentos limitados, espera
exponencial con jitter y circuito abierto tras fallos seguidos; liberar un bloqueo caducado; actualizar el estado. Nunca ejecuta
migraciones destructivas ni repite escrituras financieras o tributarias. Aplicar migraciones aditivas sigue exigiendo administración,
respaldo verificado de menos de 24 h y la confirmación APLICAR.

Estados del monitor: verde operativo · amarillo advertencia · rojo incidencia crítica · azul recuperación en curso · gris sin verificar.
La gravedad POTENCIAL de un componente (p. ej. «crítico») se muestra aparte de su estado ACTUAL. Datos en system_state (sin secretos)."""
import hashlib
import json
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / 'migrations'
MANIFEST = MIGRATIONS / 'MANIFEST.json'
LOCK_KEY, LOCK_SECONDS = 'migration_lock', 300
STATE_KEY, LAT_KEY, INC_KEY = 'db_guardian_state', 'db_guardian_latency', 'db_guardian_incidents'
SLOW_MS, VERY_SLOW_MS = 800, 2500
LAT_KEEP, INC_KEEP = 120, 60
STALE_MINUTES = 60
PENDING_GRACE_MINUTES = 30          # migraciones aditivas pendientes tras un despliegue: advertencia; más tiempo: requiere intervención
RETRIES, BASE_PAUSE, MAX_PAUSE = 3, 0.25, 2.0
CIRCUIT_FAILS, CIRCUIT_SECONDS = 3, 60
LEVELS = {'verde': 'Operativo', 'amarillo': 'Advertencia', 'rojo': 'Incidencia crítica', 'azul': 'Recuperación en curso', 'gris': 'Sin verificar'}
INCIDENT_STATES = {'activa': 'Activa', 'diagnostico': 'En diagnóstico', 'recuperacion': 'En recuperación', 'resuelta': 'Resuelta', 'intervencion': 'Requiere intervención'}
TYPES = {'DB-CONN': ('Conexión', 'Base de datos'), 'DB-SLOW': ('Latencia elevada', 'Base de datos'), 'MIG-PEND': ('Migraciones pendientes', 'Migraciones'),
         'MIG-PARTIAL': ('Migración incompleta', 'Esquema'), 'MIG-NOREC': ('Estructura sin registro', 'Esquema'), 'MIG-MOD': ('Migración modificada', 'Migraciones'),
         'MIG-DUP': ('Migración duplicada', 'Migraciones'), 'MIG-NONADD': ('Migración no aditiva pendiente', 'Migraciones'), 'MIG-LOCK': ('Bloqueo de migración caducado', 'Migraciones')}
CREATE_TABLE = re.compile(r'^CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$', re.I | re.S)
CREATE_INDEX = re.compile(r'^CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+([A-Za-z_][A-Za-z0-9_]*)\s+ON\s+([A-Za-z_][A-Za-z0-9_]*)', re.I | re.S)
CONSTRAINTS = ('PRIMARY', 'UNIQUE', 'CHECK', 'FOREIGN', 'CONSTRAINT')


class GuardianError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _get(c, key, default):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (key,)).fetchone()
    try:
        return json.loads(row['value']) if row else default
    except (TypeError, ValueError):
        return default


def _set(c, key, value):
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value, ensure_ascii=False)))


def _has(c, table):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def checksum(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def manifest():
    try:
        return json.loads(MANIFEST.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def build_manifest():
    """Manifiesto de checksums de las migraciones publicadas (se regenera solo al añadir una migración NUEVA)."""
    return {p.name: checksum(p) for p in sorted(MIGRATIONS.glob('*.sql'))}


# ---- Estructura declarada por cada migración --------------------------------------------------------------------------------------------

def _split_columns(body):
    parts, depth, cur, quote = [], 0, [], ''
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ''
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if cur:
        parts.append(''.join(cur).strip())
    return parts


def declared(path):
    """{'tables': {nombre: [columnas]}, 'indexes': {nombre: tabla}} o None si no se puede leer de forma segura."""
    import db_migrations
    parts = db_migrations._statements(path.read_text(encoding='utf-8'))
    if parts is None:
        return None
    out = {'tables': {}, 'indexes': {}}
    for stmt in parts:
        m = CREATE_TABLE.match(stmt)
        if m:
            cols = []
            for part in _split_columns(m.group(2)):
                found = re.match(r'\s*["`\[]?([A-Za-z_][A-Za-z0-9_]*)', part)
                word = found.group(1) if found else ''
                if word and word.upper() not in CONSTRAINTS:
                    cols.append(word)
            out['tables'][m.group(1)] = cols
            continue
        m = CREATE_INDEX.match(stmt)
        if m:
            out['indexes'][m.group(1)] = m.group(2)
    return out


def _schema(c):
    objects = {(r[0], r[1]) for r in c.execute("SELECT type,name FROM sqlite_master WHERE type IN ('table','index')")}
    return objects


# ---- Migration Manager ------------------------------------------------------------------------------------------------------------------

def migrations(c, folder=None):
    """Estado individual verificado de cada migración (evidencia: registro, libro, estructura y checksum)."""
    import db_migrations
    files = sorted((folder or MIGRATIONS).glob('*.sql'))
    applied = {row[0] for row in c.execute('SELECT name FROM migrations')}
    ledger = {}
    if _has(c, 'migration_ledger'):
        for r in c.execute('SELECT * FROM migration_ledger ORDER BY id'):
            ledger[r['name']] = dict(r)
    known = manifest()
    schema = _schema(c)
    # Objetos que una migración POSTERIOR elimina o renombra (p. ej., 111 reemplaza un índice de 110): no cuentan como faltantes.
    dropped = {}
    for p in files:
        text = p.read_text(encoding='utf-8')
        for kind, name in re.findall(r'DROP\s+(TABLE|INDEX)\s+(?:IF\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)', text, re.I):
            dropped.setdefault(name, p.name)
        for name in re.findall(r'ALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+RENAME\s+TO', text, re.I):
            dropped.setdefault(name, p.name)
        for table, col in re.findall(r'ALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:DROP|RENAME)\s+COLUMN\s+([A-Za-z_][A-Za-z0-9_]*)', text, re.I):
            dropped.setdefault('%s.%s' % (table, col), p.name)
    prefixes = {}
    for p in files:
        prefixes.setdefault(p.name[:3], []).append(p.name)
    columns_cache = {}
    try:  # una sola consulta para todas las columnas (en Turso cada consulta es una petición HTTP)
        for t, col in c.execute("SELECT m.name,p.name FROM sqlite_master m JOIN pragma_table_info(m.name) p WHERE m.type='table'"):
            columns_cache.setdefault(t, set()).add(col)
        bulk = True
    except Exception:
        bulk = False

    def cols(table):
        if table not in columns_cache:
            columns_cache[table] = set() if bulk or ('table', table) not in schema else {r[1] for r in c.execute('PRAGMA table_info("%s")' % table)}
        return columns_cache[table]

    out = []
    for order, p in enumerate(files, 1):
        sha = checksum(p)
        ok, why = db_migrations.check(p)
        spec = declared(p) or {'tables': {}, 'indexes': {}}
        later = lambda obj: obj in dropped and dropped[obj] > p.name
        missing = [t for t in spec['tables'] if ('table', t) not in schema and not later(t)] + [i for i in spec['indexes'] if ('index', i) not in schema and not later(i)]
        present = [t for t in spec['tables'] if ('table', t) in schema] + [i for i in spec['indexes'] if ('index', i) in schema]
        missing_cols = ['%s.%s' % (t, col) for t, cl in spec['tables'].items() if ('table', t) in schema and not later(t) for col in cl if col not in cols(t) and not later('%s.%s' % (t, col))]
        led = ledger.get(p.name)
        problems = []
        if len(prefixes[p.name[:3]]) > 1:
            problems.append(('duplicada', 'El número %s está repetido: %s.' % (p.name[:3], ', '.join(prefixes[p.name[:3]]))))
        if known.get(p.name) and known[p.name] != sha:
            problems.append(('modificada', 'El archivo cambió después de publicarse (checksum distinto del manifiesto).'))
        if led and led.get('checksum') and led['checksum'] != sha:
            problems.append(('modificada', 'El archivo cambió después de aplicarse (checksum distinto del registrado).'))
        if p.name in applied:
            if missing or missing_cols:
                state = 'incompleta'
                problems.append(('incompleta', 'Registrada como aplicada, pero falta: ' + ', '.join((missing + missing_cols)[:6]) + '.'))
            else:
                state = 'verificada'
        else:
            if present and (spec['tables'] or spec['indexes']):
                state = 'sin_registro'
                problems.append(('sin_registro', 'Su estructura existe (%s) pero no está registrada: aplicada a medias o a mano.' % ', '.join(present[:4])))
            else:
                state = 'pendiente'
        if problems and state in ('verificada', 'pendiente'):
            state = problems[0][0]
        out.append({'order': order, 'name': p.name, 'id': p.name[:-4], 'checksum': sha[:16], 'additive': ok, 'reason': why, 'state': state,
                    'applied': p.name in applied, 'applied_at': (led or {}).get('applied_at', ''), 'duration_ms': (led or {}).get('duration_ms'),
                    'result': (led or {}).get('result', 'aplicada (sin registro detallado: anterior a 1.5.331)' if p.name in applied else ''),
                    'version': (led or {}).get('version', ''), 'executor': (led or {}).get('executor', ''),
                    'objects': {'tables': list(spec['tables']), 'indexes': list(spec['indexes'])}, 'missing': missing + missing_cols,
                    'problems': [{'code': code, 'detail': detail} for code, detail in problems]})
    extra = sorted(applied - {p.name for p in files})
    return {'items': out, 'total': len(files), 'applied': sum(1 for i in out if i['applied']), 'verified': sum(1 for i in out if i['state'] == 'verificada'),
            'pending': [i for i in out if i['state'] == 'pendiente'], 'problems': [i for i in out if i['problems']],
            'unknown_applied': extra, 'manifest': bool(known)}


# ---- Bloqueo distribuido ---------------------------------------------------------------------------------------------------------------

def acquire(c, owner, now):
    """Bloqueo único entre instancias: INSERT con clave primaria (atómico en SQLite y libSQL). Un bloqueo caducado se libera y se registra."""
    value = json.dumps({'owner': owner, 'at': now.isoformat(timespec='seconds'), 'epoch': time.time()})
    try:
        c.execute('INSERT INTO system_state(key,value) VALUES (?,?)', (LOCK_KEY, value))
        c.commit()
        return True
    except Exception:
        c.rollback() if getattr(c, 'in_transaction', False) else None
    held = _get(c, LOCK_KEY, {})
    if held and time.time() - float(held.get('epoch', 0)) > LOCK_SECONDS:
        c.execute('DELETE FROM system_state WHERE key=? AND value=?', (LOCK_KEY, json.dumps(held)))
        c.commit()
        incident(c, 'MIG-LOCK', 'Bloqueo de migración de %s caducado y liberado de forma segura.' % held.get('owner', '—'), now, status='resuelta',
                 action='Bloqueo caducado liberado (operación segura).')
        try:
            c.execute('INSERT INTO system_state(key,value) VALUES (?,?)', (LOCK_KEY, value))
            c.commit()
            return True
        except Exception:
            return False
    return False


def release(c):
    c.execute('DELETE FROM system_state WHERE key=?', (LOCK_KEY,))
    c.commit()


def lock_info(c):
    held = _get(c, LOCK_KEY, {})
    if not held:
        return None
    return {'owner': held.get('owner', ''), 'at': held.get('at', ''), 'expired': time.time() - float(held.get('epoch', 0)) > LOCK_SECONDS}


# ---- Latencia y comprobaciones con recuperación segura ---------------------------------------------------------------------------------

def _pause(attempt):
    """Espera exponencial con jitter (nunca supera MAX_PAUSE)."""
    base = min(MAX_PAUSE, BASE_PAUSE * (2 ** attempt))
    return base * (0.5 + random.random() / 2)


def ping(c, sleep=time.sleep):
    """SELECT 1 de solo lectura con reintentos limitados. Devuelve (ms, intentos) o lanza la última excepción."""
    last = None
    for attempt in range(RETRIES):
        started = time.monotonic()
        try:
            c.execute('SELECT 1').fetchone()
            return round((time.monotonic() - started) * 1000), attempt + 1
        except Exception as error:   # solo lectura: es seguro repetir
            last = error
            if attempt + 1 < RETRIES:
                sleep(_pause(attempt))
    raise last


def percentiles(samples):
    values = sorted(s['ms'] for s in samples if s.get('ok'))
    if not values:
        return {'p50': None, 'p90': None, 'p95': None, 'n': 0}

    def pct(p):
        k = max(0, min(len(values) - 1, int(round(p / 100 * (len(values) - 1)))))
        return values[k]
    return {'p50': pct(50), 'p90': pct(90) if len(values) >= 5 else None, 'p95': pct(95) if len(values) >= 20 else None, 'n': len(values)}


def incident(c, code, cause, now, status='activa', action='', version=''):
    """Registra o actualiza una incidencia agrupada por código (un mismo origen no satura el historial)."""
    import versioning
    items = _get(c, INC_KEY, [])
    at = now.isoformat(timespec='seconds')
    version = version or versioning.load()['releases'][0]['version']
    open_ = next((i for i in items if i['code'] == code and i['status'] not in ('resuelta',)), None)
    kind, component = TYPES.get(code, (code, 'Base de datos'))
    if open_ and status != 'resuelta':
        open_.update(last_at=at, count=open_.get('count', 1) + 1, cause=cause, status=status)
        if action:
            open_.setdefault('actions', []).append({'at': at, 'action': action})
            open_['attempts'] = open_.get('attempts', 0) + 1
    elif open_ and status == 'resuelta':
        start = datetime.fromisoformat(open_['detected_at'])
        open_.update(status='resuelta', resolved_at=at, duration_min=max(0, round((now - start).total_seconds() / 60)), last_at=at)
        open_.setdefault('actions', []).append({'at': at, 'action': action or 'Condición verificada como resuelta.'})
    elif status != 'resuelta' or action:
        items.insert(0, {'id': '%s-%s-%03d' % (code, now.strftime('%Y%m%d'), len(items) + 1), 'code': code, 'type': kind, 'component': component, 'cause': cause,
                         'status': status, 'detected_at': at, 'last_at': at, 'count': 1, 'attempts': 1 if action else 0, 'version': version,
                         'resolved_at': at if status == 'resuelta' else '', 'duration_min': 0 if status == 'resuelta' else None,
                         'actions': [{'at': at, 'action': action}] if action else []})
    _set(c, INC_KEY, items[:INC_KEEP])


def resolve_absent(c, active_codes, now):
    for i in _get(c, INC_KEY, []):
        if i['status'] != 'resuelta' and i['code'] not in active_codes and i['code'] in TYPES and i['code'] != 'MIG-LOCK':
            incident(c, i['code'], i['cause'], now, status='resuelta', action='Comprobación posterior correcta: resuelta y verificada.')


def import_history(c, now):
    """Conserva como incidencias resueltas los fallos de «Faltan migraciones» ya registrados por el monitor de estabilidad (no se borran)."""
    if _get(c, 'db_guardian_imported', False):
        return
    items = _get(c, INC_KEY, [])
    runs = _get(c, 'stability_runs', [])
    seen = set()
    for run in runs:
        for r in run.get('results', []):
            if r.get('code') == 'database' and not r.get('ok') and 'Faltan migraciones' in str(r.get('detail', '')):
                key = (run.get('version'), str(r.get('detail')))
                if key in seen:
                    continue
                seen.add(key)
                nxt = next((x for x in runs if x.get('at', '') > run.get('at', '') and any(y.get('code') == 'database' and y.get('ok') for y in x.get('results', []))), None)
                items.append({'id': 'MIG-PEND-HIST-%03d' % len(seen), 'code': 'MIG-PEND', 'type': 'Migraciones pendientes', 'component': 'Migraciones',
                              'cause': 'Versión %s desplegada en Vercel antes de aplicar sus migraciones aditivas (%s). La conexión con la base fue correcta.'
                                       % (run.get('version', '—'), str(r.get('detail'))[:160]),
                              'status': 'resuelta', 'detected_at': run.get('at', ''), 'last_at': (nxt or run).get('at', ''), 'count': 1, 'attempts': 0,
                              'version': run.get('version', ''), 'resolved_at': (nxt or {}).get('at', ''), 'duration_min': None,
                              'actions': [{'at': (nxt or run).get('at', ''), 'action': 'Migraciones aplicadas desde Sistema; verificación posterior correcta.'}], 'historical': True})
    _set(c, INC_KEY, sorted(items, key=lambda i: i.get('detected_at', ''), reverse=True)[:INC_KEEP])
    _set(c, 'db_guardian_imported', True)


def check(c, now, deep=True, sleep=time.sleep):
    """Comprobación completa de solo lectura: conexión (con recuperación segura), latencia, migraciones e integridad del esquema."""
    import versioning
    state = _get(c, STATE_KEY, {})
    circuit = state.get('circuit_until', 0)
    result = {'checked_at': now.isoformat(timespec='seconds'), 'version': versioning.load()['releases'][0]['version']}
    if circuit and time.time() < circuit:
        result.update(ok=False, level='rojo', reason='Circuito abierto tras %d fallos seguidos: se esperan %d s antes de volver a intentar (evita solicitudes excesivas).'
                      % (CIRCUIT_FAILS, CIRCUIT_SECONDS), circuit=True)
        _set(c, STATE_KEY, dict(state, **result))
        return status(c, now)
    try:
        ms, attempts = ping(c, sleep)
    except Exception as error:
        fails = state.get('fails', 0) + 1
        open_until = time.time() + CIRCUIT_SECONDS if fails >= CIRCUIT_FAILS else 0
        result.update(ok=False, level='rojo', reason='Sin conexión con la base de datos tras %d intentos (%s).' % (RETRIES, type(error).__name__), fails=fails,
                      circuit_until=open_until, last_ok=state.get('last_ok', ''))
        try:
            _set(c, STATE_KEY, dict(state, **result))
            incident(c, 'DB-CONN', result['reason'], now, status='recuperacion' if fails < CIRCUIT_FAILS else 'intervencion',
                     action='Reintentos de lectura con espera exponencial y jitter (%d).' % RETRIES)
            c.commit()
        except Exception:
            pass
        return dict(result, label=LEVELS['rojo'], level='rojo', migrations=None, latency=percentiles(_get_safe(c, LAT_KEY)))
    samples = _get(c, LAT_KEY, [])
    samples.append({'at': result['checked_at'], 'ms': ms, 'ok': True, 'attempts': attempts})
    _set(c, LAT_KEY, samples[-LAT_KEEP:])
    import_history(c, now)
    mig = migrations(c)
    active = set()
    level, reasons = 'verde', []
    if attempts > 1:
        reasons.append('Conexión recuperada tras %d intentos.' % attempts)
        level = 'amarillo'
    if ms >= VERY_SLOW_MS or ms >= SLOW_MS:
        level = 'amarillo'
        reasons.append('Respuesta lenta de la base de datos (%d ms).' % ms)
        if ms >= VERY_SLOW_MS:
            active.add('DB-SLOW')
            incident(c, 'DB-SLOW', 'Respuesta de %d ms.' % ms, now)
    deploy = _deployed_at()
    for item in mig['items']:
        for p in item['problems']:
            code = {'incompleta': 'MIG-PARTIAL', 'sin_registro': 'MIG-NOREC', 'modificada': 'MIG-MOD', 'duplicada': 'MIG-DUP'}[p['code']]
            active.add(code)
            incident(c, code, '%s: %s' % (item['name'], p['detail']), now, status='intervencion')
            level = 'rojo'
            reasons.append('%s: %s' % (item['name'], p['detail']))
    pending = mig['pending']
    if pending:
        active.add('MIG-PEND')
        nonadd = [i['name'] for i in pending if not i['additive']]
        late = deploy and (now - deploy) > timedelta(minutes=PENDING_GRACE_MINUTES)
        cause = 'Pendientes: %s. %s' % (', '.join(i['name'] for i in pending), 'Vercel no aplica migraciones: se aplican desde Sistema (aditivas) con respaldo verificado.')
        incident(c, 'MIG-PEND', cause, now, status='intervencion' if late or nonadd else 'activa')
        if nonadd:
            active.add('MIG-NONADD')
            level = 'rojo'
            reasons.append('Migración no aditiva pendiente (%s): requiere procedimiento manual con respaldo.' % ', '.join(nonadd))
        elif level != 'rojo':
            level = 'amarillo'
            reasons.append('%d migración(es) aditiva(s) pendiente(s) desde el despliegue%s. El código las tolera; aplícalas en Sistema.'
                           % (len(pending), ' (más de %d min: requiere intervención)' % PENDING_GRACE_MINUTES if late else ''))
    lock = lock_info(c)
    if lock and lock['expired']:
        acquire(c, 'guardian-cleanup', now) and release(c)
    resolve_absent(c, active, now)
    result.update(ok=True, level=level, reason=' '.join(reasons), latency_ms=ms, attempts=attempts, fails=0, circuit_until=0, last_ok=result['checked_at'], circuit=False)
    _set(c, STATE_KEY, dict(state, **result))
    c.commit()
    return status(c, now)


def _get_safe(c, key):
    try:
        return _get(c, key, [])
    except Exception:
        return []


def _deployed_at():
    import versioning
    try:
        return datetime.fromisoformat(versioning.load()['releases'][0]['date'])
    except Exception:
        return None


def status(c, now):
    """Estado del monitor SIN nuevas consultas de diagnóstico (lo guardado + migraciones verificadas)."""
    import versioning
    state = _get(c, STATE_KEY, {})
    samples = _get(c, LAT_KEY, [])
    incidents = _get(c, INC_KEY, [])
    lock = lock_info(c)
    mig = migrations(c)
    level = state.get('level', 'gris') if state else 'gris'
    reason = state.get('reason', '') if state else 'Todavía no hay una comprobación de Database Guardian.'
    stale = True
    if state.get('checked_at'):
        try:
            stale = (now - datetime.fromisoformat(state['checked_at'])) > timedelta(minutes=STALE_MINUTES)
        except ValueError:
            stale = True
    if state and stale and level == 'verde':
        level, reason = 'gris', 'La última comprobación tiene más de %d minutos: sin información reciente suficiente.' % STALE_MINUTES
    if lock and not lock['expired']:
        level, reason = 'azul', 'Aplicando migraciones (%s, desde %s): recuperación controlada en curso.' % (lock['owner'], lock['at'][11:16])
    active = [i for i in incidents if i['status'] != 'resuelta']
    return {'level': level, 'label': LEVELS[level], 'reason': reason, 'checked_at': state.get('checked_at', ''), 'last_ok': state.get('last_ok', ''),
            'latency_ms': state.get('latency_ms'), 'latency': percentiles(samples), 'samples': [s['ms'] for s in samples[-30:] if s.get('ok')],
            'version': versioning.load()['releases'][0]['version'], 'migrations': {k: mig[k] for k in ('total', 'applied', 'verified', 'manifest', 'unknown_applied')},
            'pending': [i['name'] for i in mig['pending']], 'schema_ok': not mig['problems'], 'schema_problems': [{'name': i['name'], 'problems': i['problems']} for i in mig['problems']],
            'incidents_active': len(active), 'incidents_resolved': sum(1 for i in incidents if i['status'] == 'resuelta'), 'lock': lock,
            'component': {'name': 'Base de datos (Turso / libSQL)', 'potential_severity': 'crítica',
                          'note': 'Gravedad potencial del componente; no indica una incidencia activa.'},
            'circuit': bool(state.get('circuit_until') and time.time() < state['circuit_until'])}


def history(c, status_filter=''):
    items = _get(c, INC_KEY, [])
    return [dict(i, status_label=INCIDENT_STATES.get(i['status'], i['status'])) for i in items if not status_filter or i['status'] == status_filter]


def export(c, now):
    """Diagnóstico exportable (JSON, sin credenciales ni datos de clientes)."""
    st = status(c, now)
    return {'generated_at': now.isoformat(timespec='seconds'), 'product': 'Órdenes Pro', 'guardian': 'Database Guardian Pro 1.0', 'status': st,
            'migrations': migrations(c)['items'], 'incidents': history(c), 'latency_samples': _get(c, LAT_KEY, [])[-60:]}


def notifications(c, now):
    """Avisos para el centro de notificaciones (claves estables: no se duplican; cambian si cambia la situación)."""
    out = []
    try:
        st = status(c, now)
    except Exception:
        return out
    stamp = now.isoformat(timespec='seconds')
    if st['pending']:
        out.append({'key': 'guardian:pending:' + ','.join(st['pending']), 'kind': 'warning', 'icon': 'status', 'title': 'Migraciones pendientes en la base de datos',
                    'detail': ', '.join(st['pending']) + '. Aplícalas en Sistema → Database Guardian.', 'at': stamp, 'href': '#system', 'group': 'alert'})
    if st['schema_problems']:
        out.append({'key': 'guardian:schema:' + ','.join(p['name'] for p in st['schema_problems']), 'kind': 'danger', 'icon': 'status', 'title': 'Inconsistencia en el esquema de la base de datos',
                    'detail': '; '.join(p['name'] for p in st['schema_problems']) + '. Requiere revisión.', 'at': stamp, 'href': '#system', 'group': 'alert'})
    for i in _get(c, INC_KEY, [])[:20]:
        if i['status'] == 'intervencion':
            out.append({'key': 'guardian:inc:%s:%s' % (i['id'], i['count']), 'kind': 'danger', 'icon': 'status', 'title': 'Base de datos: ' + i['type'] + ' requiere intervención',
                        'detail': i['cause'][:200], 'at': i['last_at'], 'href': '#system', 'group': 'alert'})
        elif i['status'] == 'resuelta' and i.get('resolved_at') and not i.get('historical') and i['code'] in ('DB-CONN', 'MIG-PARTIAL', 'MIG-NOREC', 'MIG-MOD', 'MIG-NONADD', 'MIG-PEND'):
            try:
                recent = now - datetime.fromisoformat(i['resolved_at']) < timedelta(hours=24)
            except ValueError:
                recent = False
            if recent:
                out.append({'key': 'guardian:ok:%s' % i['id'], 'kind': 'success', 'icon': 'status', 'title': 'Base de datos: incidencia resuelta y verificada',
                            'detail': i['type'] + ' · ' + i['cause'][:160], 'at': i['resolved_at'], 'href': '#system', 'group': 'alert'})
    return out


def precheck():
    """Control previo a la publicación (sin base de datos): nombres válidos y únicos, solo aditivas o marcadas como manuales, y ninguna
    migración ya publicada modificada respecto del manifiesto. Devuelve la lista de problemas (vacía = se puede publicar)."""
    import db_migrations
    problems = []
    files = sorted(MIGRATIONS.glob('*.sql'))
    known = manifest()
    seen = {}
    for p in files:
        if not db_migrations.NAME.fullmatch(p.name):
            problems.append('%s: nombre no válido.' % p.name)
        if p.name[:3] in seen:
            problems.append('%s: número repetido con %s.' % (p.name, seen[p.name[:3]]))
        seen[p.name[:3]] = p.name
        if p.name in known and known[p.name] != checksum(p):
            problems.append('%s: se modificó después de publicarse. Crea una migración nueva en lugar de editarla.' % p.name)
        if p.name not in known:
            problems.append('%s: falta en el manifiesto (python local/db_guardian.py manifest).' % p.name)
        if declared(p) is None:
            problems.append('%s: no se puede leer de forma segura.' % p.name)
    for name in known:
        if not (MIGRATIONS / name).exists():
            problems.append('%s: está en el manifiesto pero el archivo no existe (las migraciones publicadas no se borran).' % name)
    return problems


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'manifest':
        data = build_manifest()
        old = manifest()
        changed = [n for n in old if n in data and old[n] != data[n]]
        if changed:
            raise SystemExit('No se regenera: cambiaron migraciones ya publicadas: ' + ', '.join(changed))
        MANIFEST.write_text(json.dumps(data, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        print('Manifiesto con %d migraciones.' % len(data))
    else:
        found = precheck()
        print('\n'.join(found) or 'Migraciones correctas.')
        raise SystemExit(1 if found else 0)


CRITICAL_TABLES = ('clients', 'orders', 'quotes', 'invoices', 'invoice_sequences', 'order_payments', 'payment_commitments', 'financial_rates', 'cash_sessions',
                   'inventory_items', 'license_sales', 'migrations')


def integrity(c):
    """Consulta de integridad de SOLO LECTURA: esquema de las migraciones, quick_check y claves foráneas (si el servicio lo permite) y
    recuento de las tablas críticas (solo cantidades: ningún dato de clientes)."""
    out = {'schema': [], 'quick_check': '', 'foreign_keys': '', 'tables': {}}
    mig = migrations(c)
    out['schema'] = [{'name': i['name'], 'problems': i['problems']} for i in mig['problems']]
    try:
        rows = [r[0] for r in c.execute('PRAGMA quick_check(20)')]
        out['quick_check'] = 'ok' if rows == ['ok'] else '; '.join(map(str, rows))[:400]
    except Exception as error:
        out['quick_check'] = 'No disponible en este servicio (%s).' % type(error).__name__
    try:
        rows = c.execute('PRAGMA foreign_key_check').fetchall()
        out['foreign_keys'] = 'ok' if not rows else '%d referencia(s) sin destino (p. ej., tabla %s).' % (len(rows), rows[0][0])
    except Exception as error:
        out['foreign_keys'] = 'No disponible en este servicio (%s).' % type(error).__name__
    for t in CRITICAL_TABLES:
        if _has(c, t):
            out['tables'][t] = int(c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0])
        else:
            out['tables'][t] = None
    out['ok'] = not out['schema'] and out['quick_check'] in ('ok',) or (not out['schema'] and out['quick_check'].startswith('No disponible'))
    return out
