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


def _counts(c):
    tables = [row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    if not tables:
        return {}
    sql = ' UNION ALL '.join("SELECT '%s',COUNT(*) FROM \"%s\"" % (t, t) for t in tables if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', t))
    return {row[0]: int(row[1]) for row in c.execute(sql)}


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
    before = _counts(c)
    c.commit()
    done = []
    for name in info['applicable']:
        path = ROOT / 'migrations' / name
        ok, why = check(path)  # se vuelve a comprobar justo antes de aplicar
        if not ok:
            break
        if c.execute('SELECT 1 FROM migrations WHERE name=?', (name,)).fetchone():
            continue
        c.executescript('BEGIN IMMEDIATE;\n' + path.read_text(encoding='utf-8') + "\nINSERT INTO migrations VALUES ('" + name.replace("'", "''") + "');\nCOMMIT;")
        done.append(name)
    after = _counts(c)
    lost = [t for t, n in before.items() if t not in VOLATILE and (t not in after or after[t] < n)]
    return {'applied': done, 'lost': lost, 'tables_before': len(before), 'tables_after': len(after), 'status': status(c, now)}
