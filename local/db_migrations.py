"""Migraciones pendientes de la base central, aplicadas por administración desde Sistema (1.5.317).

En producción Vercel no ejecuta `migrate()`. Este módulo permite aplicar desde el propio servidor (que ya tiene las credenciales de la
base) SOLO migraciones aditivas: cada sentencia debe ser `CREATE TABLE IF NOT EXISTS` o `CREATE [UNIQUE] INDEX IF NOT EXISTS`. Cualquier
otra (ALTER, UPDATE, DELETE, DROP, INSERT…) se rechaza y debe aplicarse a mano con respaldo. Antes de aplicar se exige un respaldo
correcto y verificado de las últimas 24 horas; se cuentan las filas de todas las tablas antes y después, y ninguna puede perder filas.
Cada migración va en su propia transacción con su registro en `migrations`: si falla, no queda a medias. Todo queda en la auditoría."""
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKUP_HOURS = 24
ALLOWED = re.compile(r'^CREATE\s+(?:TABLE|(?:UNIQUE\s+)?INDEX)\s+IF\s+NOT\s+EXISTS\s+[A-Za-z_][A-Za-z0-9_]*\b', re.I | re.S)
NAME = re.compile(r'^\d{3}_[a-z0-9_]+\.sql$')
# Tablas que el propio sistema vacía mientras funciona (caducidades): pueden perder filas sin que la migración tenga que ver.
VOLATILE = {'sessions', 'attempts', 'login_attempt_events', 'order_checks', 'reset_tokens', 'wa_identity_state', 'trusted_devices', 'second_step_challenges'}


class MigrationError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _statements(sql):
    """Sentencias sin comentarios, separadas por «;» fuera de comillas. None si el texto no se puede leer de forma segura."""
    out, cur, quote, i = [], [], '', 0
    while i < len(sql):
        ch = sql[i]
        if quote:
            cur.append(ch)
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:  # comilla escapada ('')
                    cur.append(sql[i + 1])
                    i += 1
                else:
                    quote = ''
        elif ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif sql.startswith('--', i):
            j = sql.find('\n', i)
            i = len(sql) if j < 0 else j
            continue
        elif sql.startswith('/*', i):
            j = sql.find('*/', i + 2)
            if j < 0:
                return None
            i = j + 2
            continue
        elif ch == ';':
            out.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    if quote:
        return None
    out.append(''.join(cur).strip())
    return [part for part in out if part]


def check(path):
    """(es_aditiva, motivo)."""
    if not NAME.fullmatch(path.name):
        return False, 'Nombre de archivo no reconocido.'
    parts = _statements(path.read_text(encoding='utf-8'))
    if not parts:
        return False, 'No se pudo leer la migración de forma segura.' if parts is None else 'La migración está vacía.'
    for stmt in parts:
        if not ALLOWED.match(stmt):
            return False, 'Contiene «' + ' '.join(stmt.split()[:3]) + '…»: no es solo creación de tablas o índices nuevos. Debe aplicarse a mano con respaldo.'
    return True, '%d sentencia(s): solo crea tablas o índices nuevos.' % len(parts)


def pending(c):
    files = sorted(p for p in (ROOT / 'migrations').glob('*.sql'))
    applied = {row[0] for row in c.execute('SELECT name FROM migrations')}
    out = []
    for p in files:
        if p.name in applied:
            continue
        ok, why = check(p)
        out.append({'name': p.name, 'additive': ok, 'reason': why})
    return out, len(files), len(applied)


def _backup(c, now):
    import backups as bk
    good = bk.last_good(c)
    if not good or not good.get('finished_at'):
        return None, 'No hay ningún respaldo correcto y verificado.'
    try:
        moment = datetime.fromisoformat(good['finished_at'])
    except ValueError:
        return None, 'No se pudo leer la fecha del último respaldo verificado.'
    if moment.tzinfo is None or now.tzinfo is None:
        moment, ref = moment.replace(tzinfo=None), now.replace(tzinfo=None)
    else:
        ref = now
    info = {'finished_at': good['finished_at'], 'destination': good.get('destination', ''), 'file': good.get('file', '')}
    if ref - moment > timedelta(hours=BACKUP_HOURS):
        return info, 'El último respaldo verificado tiene más de %d horas.' % BACKUP_HOURS
    return info, ''


def status(c, now):
    items, total, applied = pending(c)
    backup, problem = _backup(c, now)
    applicable = []
    for item in items:  # en orden: se detiene en la primera que no sea aditiva
        if not item['additive']:
            break
        applicable.append(item['name'])
    return {'pending': items, 'total': total, 'applied': applied, 'applicable': applicable, 'backup': backup, 'backup_problem': problem,
            'backup_hours': BACKUP_HOURS, 'ready': bool(applicable) and not problem}


INTERNAL = ('sqlite_', 'libsql_', '_litestream', '_cf_', '_turso')


def _counts(c):
    """Filas por tabla. Excluye las tablas internas del motor o del proveedor (Turso/libSQL) y cuenta por grupos; si un grupo falla,
    cuenta tabla por tabla y omite solo la que no se pueda leer (queda en «unreadable»)."""
    import sqlite3
    tables = [row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
              if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', row[0]) and not row[0].lower().startswith(INTERNAL)]
    out, unreadable = {}, []
    for start in range(0, len(tables), 25):
        group = tables[start:start + 25]
        try:
            out.update({row[0]: int(row[1]) for row in c.execute(' UNION ALL '.join("SELECT '%s',COUNT(*) FROM \"%s\"" % (t, t) for t in group))})
        except sqlite3.Error:
            for t in group:
                try:
                    out[t] = int(c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0])
                except sqlite3.Error:
                    unreadable.append(t)
    out['__unreadable__'] = unreadable
    return out


def apply(c, user, now, confirm):
    if not user or user['role'] != 'administrador':
        raise MigrationError('Solo administración aplica migraciones.', 403)
    if str(confirm or '').strip().upper() != 'APLICAR':
        raise MigrationError('Escribe APLICAR para confirmar.')
    info = status(c, now)
    if info['backup_problem']:
        raise MigrationError(info['backup_problem'] + ' Crea primero un respaldo completo en Configuración → Respaldos y vuelve a intentarlo.', 409)
    if not info['applicable']:
        blocked = next((i for i in info['pending'] if not i['additive']), None)
        raise MigrationError(('No hay migraciones aplicables desde aquí. ' + blocked['name'] + ': ' + blocked['reason']) if blocked else 'No hay migraciones pendientes.', 409)
    import sqlite3
    import time
    import db_guardian as guard
    import versioning
    c.commit()  # libera la transacción de la petición: el recuento y las migraciones no retienen la base
    # Database Guardian (1.5.331): una sola ejecución a la vez entre instancias (bloqueo distribuido con caducidad).
    info_user = {k: user[k] for k in user.keys()} if hasattr(user, 'keys') else {}
    owner = str(info_user.get('username') or info_user.get('name') or 'administración')
    before = _counts(c)  # antes del bloqueo: la fila del bloqueo no cuenta como dato perdido
    if not guard.acquire(c, str(owner), now):
        held = guard.lock_info(c) or {}
        raise MigrationError('Ya hay una aplicación de migraciones en curso (%s, desde %s). Espera a que termine; no se ejecuta dos veces.' % (held.get('owner', '—'), held.get('at', '—')), 409)
    try:
        done, verified = [], []
        version = versioning.load()['releases'][0]['version']
        for name in info['applicable']:
            path = ROOT / 'migrations' / name
            ok, why = check(path)  # se vuelve a comprobar justo antes de aplicar
            if not ok:
                break
            if c.execute('SELECT 1 FROM migrations WHERE name=?', (name,)).fetchone():
                continue
            started = time.monotonic()
            try:
                c.executescript('BEGIN IMMEDIATE;\n' + path.read_text(encoding='utf-8') + "\nINSERT INTO migrations VALUES ('" + name.replace("'", "''") + "');\nCOMMIT;")
            except sqlite3.Error as error:
                try:
                    c.rollback()  # SQLite local deja abierta la transacción del script fallido: se descarta entera (Turso ya la descarta)
                except sqlite3.Error:
                    pass
                # Otra instancia pudo registrarla en el mismo instante: se comprueba antes de informar un fallo (nunca se repite a ciegas).
                if c.execute('SELECT 1 FROM migrations WHERE name=?', (name,)).fetchone():
                    continue
                # La transacción se descarta entera: la migración no queda a medias. Se informa el motivo real (sin datos ni credenciales).
                detail = re.sub(r'\s+', ' ', str(error))[:220]
                raise MigrationError('La base de datos no aceptó ' + name + ' (' + type(error).__name__ + ': ' + detail + '). No se aplicó nada de esa migración.'
                                     + (' Antes se aplicaron: ' + ', '.join(done) + '.' if done else ''), 502) from None
            ms = round((time.monotonic() - started) * 1000)
            # Verificación posterior: cada tabla, columna e índice declarado debe existir.
            item = next(i for i in guard.migrations(c)['items'] if i['name'] == name)
            good = item['state'] == 'verificada'
            if good:
                verified.append(name)
            try:
                c.execute('INSERT INTO migration_ledger(name,checksum,applied_at,duration_ms,result,version,executor,verified) VALUES (?,?,?,?,?,?,?,?)',
                          (name, guard.checksum(path), now.isoformat(timespec='seconds'), ms, 'aplicada y verificada' if good else 'aplicada · verificación: ' + item['state'],
                           version, str(owner)[:80], 1 if good else 0))
                c.commit()
            except sqlite3.Error:
                c.rollback()  # sin libro (migración 122 aún no aplicada): la migración ya quedó registrada en `migrations`
            done.append(name)
            if not good:
                break
    finally:
        guard.release(c)
    after = _counts(c)
    skipped = sorted(set(before.pop('__unreadable__', [])) | set(after.pop('__unreadable__', [])))
    lost = [t for t, n in before.items() if t not in VOLATILE and (t not in after or after[t] < n)]
    return {'applied': done, 'verified': verified, 'lost': lost, 'unreadable': skipped, 'tables_before': len(before), 'tables_after': len(after), 'status': status(c, now)}
