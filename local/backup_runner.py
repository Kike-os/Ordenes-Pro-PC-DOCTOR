"""Motor de respaldos de Órdenes Pro y AGENTE MEGA (1.5.311). Corre en el equipo de la oficina (maintenance/backup-cloud.py).

Procedimiento: el esquema y todas las filas de la base central se leen dentro de UNA transacción de lectura (instantánea consistente) y
se escriben en una base SQLite nueva, comprobada con integrity_check, foreign_key_check y el recuento de cada tabla. Esa copia queda en el
equipo (copia local independiente) y, comprimida y cifrada (AES-256-GCM), pasa a la cola de PENDIENTES en disco. Desde ahí se sube a MEGA
con MEGAcmd OFICIAL, se DESCARGA de nuevo, se compara el SHA-256, se descifra y se restaura en una base aislada: solo entonces cuenta
como respaldada en MEGA. Si MEGA o internet fallan, sigue pendiente y se reintenta. Nunca se registran datos de clientes: solo recuentos."""
import base64
import gzip
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import shlex
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import backups as od

KEEP = 30
ECUADOR = timezone(timedelta(hours=-5))
MAGIC = b'OPRB\x01'


class KeyMissing(Exception):
    pass


def digest(path_or_bytes):
    hasher = hashlib.sha256()
    if isinstance(path_or_bytes, (bytes, bytearray)):
        hasher.update(path_or_bytes)
        return hasher.hexdigest()
    with open(path_or_bytes, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            hasher.update(block)
    return hasher.hexdigest()


def table_counts(connection):
    names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {name: connection.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0] for name in names}


def verify(path):
    """Restauración de prueba: abre una copia en un directorio temporal aislado y valida integridad, claves y recuentos."""
    with tempfile.TemporaryDirectory(prefix='ordenes-restauracion-') as folder:
        copy = Path(folder) / 'restaurada.sqlite3'
        shutil.copy2(path, copy)
        connection = sqlite3.connect(copy)
        try:
            integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
            foreign = len(connection.execute('PRAGMA foreign_key_check').fetchall())
            counts = table_counts(connection)
            linked = connection.execute('SELECT COUNT(*) FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id').fetchone()[0]
        finally:
            connection.close()
    return {'integrity': integrity, 'foreign_key_errors': foreign, 'counts': counts, 'orders_linked_to_clients': linked}


def _copy(source, partial, use_transaction):
    """Copia esquema y filas a un archivo SQLite nuevo. Con use_transaction, todo se lee dentro de una sola transacción de lectura."""
    if use_transaction:
        source.execute('BEGIN')
    try:
        objects = source.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END,rowid").fetchall()
        tables = [row['name'] for row in objects if row['type'] == 'table']
        copy = sqlite3.connect(partial)
        try:
            for row in objects:
                if row['type'] == 'table':
                    copy.execute(row['sql'])
            remote = {}
            for name in tables:
                rows = source.execute('SELECT * FROM "' + name + '"').fetchall()
                remote[name] = len(rows)
                if rows:
                    columns = rows[0].keys()
                    copy.executemany('INSERT INTO "' + name + '" (' + ','.join('"' + column + '"' for column in columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', [tuple(row[column] for column in columns) for row in rows])
            for row in objects:
                if row['type'] != 'table':
                    copy.execute(row['sql'])
            copy.commit()
        finally:
            copy.close()
        if not use_transaction:
            # Sin transacción: la copia solo vale si nadie cambió el número de filas mientras se leía.
            again = {name: source.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0] for name in tables}
            if again != remote:
                raise RuntimeError('La base cambió durante la copia; se repite.')
        return remote, tables
    finally:
        if use_transaction and getattr(source, 'in_transaction', False):
            source.rollback()


def snapshot(target):
    """Instantánea verificada de la base central en `target`. Hasta 3 intentos (red o cambios durante la copia)."""
    import app
    partial = Path(str(target) + '.parcial')
    last = None
    for attempt in range(3):
        partial.unlink(missing_ok=True)
        try:
            with app.connect() as source:
                try:
                    remote, tables = _copy(source, partial, use_transaction=True)
                except Exception as error:
                    # Si la transacción de lectura no se sostiene (red o plazo del servicio), copia sin ella con doble recuento.
                    last = error
                    partial.unlink(missing_ok=True)
                    remote, tables = _copy(source, partial, use_transaction=False)
            check = verify(partial)
            if check['integrity'] != 'ok' or check['foreign_key_errors'] or check['counts'] != remote:
                raise RuntimeError('La copia no coincide con la base central; no se conserva.')
            partial.rename(target)
            return remote, tables, check
        except Exception as error:
            last = error
            partial.unlink(missing_ok=True)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('No se pudo obtener una copia consistente: ' + type(last).__name__ + ': ' + str(last)[:160])


def _record(run):
    import app
    import backups as od
    with app.connect() as c:
        od.save_run(c, run)


def _central():
    import remote_db
    return remote_db.configured()


def backup(folder):
    """Copia local en este equipo (independiente de la nube). Conserva las últimas 30."""
    import app
    import backups as od
    if not _central():
        raise SystemExit('No hay base central configurada (TURSO_DATABASE_URL). Ejecuta con las variables de producción.')
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    stamp = datetime.now(ECUADOR)
    target = folder / ('ordenes-pro-nube-' + stamp.strftime('%Y%m%d-%H%M%S') + '.sqlite3')
    old_mask = os.umask(0o077)
    try:
        remote, tables, check = snapshot(target)
    finally:
        os.umask(old_mask)
    for old in sorted(folder.glob('ordenes-pro-nube-*.sqlite3'))[:-KEEP]:
        old.unlink()
    result = {'ok': True, 'at': stamp.isoformat(timespec='seconds'), 'file': target.name, 'bytes': target.stat().st_size, 'sha256': digest(target), 'clients': remote.get('clients', 0), 'orders': remote.get('orders', 0), 'tables': len(tables), 'kept': len(list(folder.glob('ordenes-pro-nube-*.sqlite3')))}
    with app.connect() as source:
        od.keep_legacy(source)
        # El resultado queda también en la base central para que la aplicación avise si los respaldos se atrasan.
        source.execute("INSERT INTO system_state VALUES ('cloud_backup',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps({key: result[key] for key in ('ok', 'at', 'bytes', 'sha256', 'clients', 'orders')}),))
        source.commit()
        run = od.new_run('respaldo', 'programado', 'equipo')
        run.update(status='correcto', started_at=result['at'], finished_at=od.stamp(), file=target.name, bytes=result['bytes'], raw_bytes=result['bytes'], sha256=result['sha256'],
                   verified=True, verify=_summary(check), runner='equipo-local')
        od.save_run(source, run)
        import_office_log(source, folder / 'respaldos.log')
    return result


def import_office_log(c, log):
    """Historial unificado SIN inventar: incorpora las copias del equipo de la oficina que constan en su registro real (respaldos.log)
    y todavía no están en el historial. Esas copias se verificaron restaurándolas antes de anotarlas, igual que ahora."""
    import re
    import backups as od
    if not log.exists():
        return 0
    known = {item.get('file') for item in od.runs(c)}
    added = 0
    for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
        found = re.match(r'(\S+) OK (ordenes-pro-nube-\S+\.sqlite3) (\d+) bytes clientes=(\d+) ordenes=(\d+) sha256=([0-9a-f]{64})', line)
        if not found or found[2] in known:
            continue
        run = od.new_run('respaldo', 'programado', 'equipo')
        run.update(id='l' + found[2][16:31].replace('-', ''), status='correcto', requested_at=found[1], started_at=found[1], finished_at=found[1], file=found[2],
                   bytes=int(found[3]), raw_bytes=int(found[3]), sha256=found[6], verified=True, runner='equipo-local', imported=True,
                   verify={'integrity': 'ok', 'foreign_key_errors': 0, 'clients': int(found[4]), 'orders': int(found[5])})
        items = od.runs(c)
        items.append(run)
        items.sort(key=lambda item: item.get('requested_at') or '', reverse=True)
        od.set_state(c, 'backup_runs', items[:od.MAX_RUNS])
        known.add(found[2])
        added += 1
    c.commit()
    return added


def _summary(check):
    counts = check['counts']
    return {'integrity': check['integrity'], 'foreign_key_errors': check['foreign_key_errors'], 'tables': len(counts), 'rows': sum(counts.values()),
            'clients': counts.get('clients', 0), 'orders': counts.get('orders', 0), 'orders_linked_to_clients': check.get('orders_linked_to_clients', 0)}


# ---------------------------------------------------------------- cifrado de respaldos (AES-256-GCM)
def encryption_key():
    raw = os.getenv('BACKUP_ENCRYPTION_KEY', '').strip()
    key_file = Path(os.getenv('BACKUP_KEY_FILE', str(Path.home() / '.config' / 'ordenes-pro' / 'backup.key')))
    if not raw and key_file.exists():
        raw = key_file.read_text().strip().splitlines()[-1].strip()
    try:
        key = base64.b64decode(raw + '=' * (-len(raw) % 4)) if raw else b''
    except ValueError:
        key = b''
    if len(key) != 32:
        raise KeyMissing('Falta la clave de cifrado de los respaldos (BACKUP_ENCRYPTION_KEY o el archivo ~/.config/ordenes-pro/backup.key en el equipo del agente). Sin ella no se cifra ni se recupera ningún respaldo.')
    return key


def encrypt(plain):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(encryption_key()).encrypt(nonce, gzip.compress(plain, 9), MAGIC)


def decrypt(blob):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
    if blob[:5] != MAGIC:
        raise RuntimeError('El archivo no es un respaldo cifrado de Órdenes Pro.')
    try:
        return gzip.decompress(AESGCM(encryption_key()).decrypt(blob[5:17], blob[17:], MAGIC))
    except InvalidTag:
        raise RuntimeError('El respaldo no se pudo descifrar: la clave no corresponde o el archivo está alterado.') from None


def restore_check(blob, expected_sha=None):
    """Prueba de restauración aislada de un respaldo cifrado: checksum, descifrado, integridad, claves y recuentos."""
    sha = digest(blob)
    if expected_sha and sha != expected_sha:
        raise RuntimeError('El SHA-256 del archivo descargado no coincide con el registrado al subirlo.')
    with tempfile.TemporaryDirectory(prefix='ordenes-restauracion-') as folder:
        path = Path(folder) / 'restaurada.sqlite3'
        path.write_bytes(decrypt(blob))
        check = verify(path)
    if check['integrity'] != 'ok' or check['foreign_key_errors']:
        raise RuntimeError('La base restaurada no superó la comprobación de integridad.')
    return sha, check




# ================================================================ AGENTE MEGA (MEGAcmd oficial)
REMOTE = '/' + 'PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos'
DEFAULT_EXCHANGE = Path.home() / 'Respaldos-OrdenesPro' / 'mega-intercambio'
AGENT_VERSION = '1.5.311'


def exchange_dir():
    """Carpeta compartida con el contenedor de MEGAcmd (misma ruta dentro y fuera). Persistente: sobrevive a reinicios y cortes."""
    folder = Path(os.getenv('MEGA_EXCHANGE_DIR', str(DEFAULT_EXCHANGE)))
    for sub in ('', 'pendientes', 'verificacion'):
        (folder / sub).mkdir(parents=True, exist_ok=True)
        os.chmod(folder / sub, 0o700)
    return folder


class MegaError(RuntimeError):
    pass


class Mega:
    """Llamadas a MEGAcmd. Por defecto dentro del contenedor «ordenes-mega» (paquete oficial de MEGA para Ubuntu 24.04).
    Nunca recibe ni guarda la contraseña: usa la sesión iniciada una vez en el equipo con mega-login."""

    def __init__(self, prefix=None):
        self.prefix = shlex.split(prefix if prefix is not None else os.getenv('MEGA_CMD', 'podman exec ordenes-mega'))

    def run(self, command, *args, timeout=900, check=True):
        try:
            done = subprocess.run(self.prefix + [command, *args], capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise MegaError('MEGAcmd no está instalado o el contenedor «ordenes-mega» no existe en este equipo.') from None
        except subprocess.TimeoutExpired:
            raise MegaError(command + ' no respondió a tiempo (conexión lenta o caída).') from None
        text = (done.stdout or '') + (done.stderr or '')
        if check and done.returncode != 0:
            raise MegaError(command + ' falló (código %d): %s' % (done.returncode, ' '.join(text.split())[:200]))
        return done.returncode, text

    def whoami(self):
        """Cuenta con sesión iniciada, None si no hay sesión. Un fallo de red NO se confunde con «sin sesión»: se informa tal cual."""
        import re
        code, text = self.run('mega-whoami', check=False, timeout=60)
        found = re.search(r'[\w.+-]+@[\w-]+(\.[\w-]+)+', text)
        if code == 0 and found:
            return found.group(0)
        if re.search(r'not logged in|no.*sesi', text, re.I):
            return None
        raise MegaError('Sin conexión con MEGA: ' + ' '.join(text.split())[:180])

    def space(self):
        import re
        code, text = self.run('mega-df', check=False, timeout=120)
        found = re.search(r'USED STORAGE:\s*(\d+)\s+[\d.,]+%\s+of\s+(\d+)', text)
        return {'used': int(found[1]), 'total': int(found[2])} if code == 0 and found else None

    def mkdir(self, path):
        self.run('mega-mkdir', '-p', path, check=False, timeout=120)
        if self.run('mega-ls', path, check=False, timeout=120)[0] != 0:
            raise MegaError('No se pudo crear la carpeta ' + path + ' en MEGA.')

    def ls(self, path):
        code, text = self.run('mega-ls', path, check=False, timeout=120)
        if code != 0:
            raise MegaError('No se pudo leer la carpeta de respaldos en MEGA.')
        return [line.strip() for line in text.splitlines() if line.strip()]

    def put(self, local, remote_dir):
        self.run('mega-put', str(local), remote_dir.rstrip('/') + '/', timeout=1800)

    def get(self, remote, local_dir):
        self.run('mega-get', remote, str(local_dir) + '/', timeout=1800)

    def trash(self, remote):
        """A la papelera de MEGA (recuperable allí), nunca borrado definitivo."""
        self.run('mega-mv', remote, '//bin/', timeout=300)

    def export(self, remote):
        import re
        code, text = self.run('mega-export', '-a', '-f', remote, timeout=300)
        found = re.search(r'https://mega\.nz/\S+', text)
        if not found:
            raise MegaError('MEGA no devolvió el enlace de descarga.')
        return found.group(0)

    def unexport(self, remote):
        self.run('mega-export', '-d', remote, check=False, timeout=300)


def _pending(folder):
    items = []
    for meta in sorted((folder / 'pendientes').glob('*.json')):
        try:
            data = json.loads(meta.read_text())
        except ValueError:
            continue
        if (folder / 'pendientes' / data.get('file', '')).exists():
            items.append(data)
    return items


def _save_meta(folder, data):
    path = folder / 'pendientes' / (data['file'] + '.json')
    path.write_text(json.dumps(data, ensure_ascii=False))
    os.chmod(path, 0o600)


def daily(local_folder, trigger='programado', user_id=None, mega=None):
    """Respaldo completo: copia local verificada + archivo cifrado en la cola de pendientes + intento de subida a MEGA."""
    import app
    folder = exchange_dir()
    encryption_key()
    result = backup(local_folder)
    source = Path(local_folder) / result['file']
    moment = datetime.fromisoformat(result['at'])
    name = od.file_name(moment)
    blob = encrypt(source.read_bytes())
    target = folder / 'pendientes' / name
    old_mask = os.umask(0o077)
    try:
        target.write_bytes(blob)
    finally:
        os.umask(old_mask)
    with app.connect() as c:
        run = od.new_run('respaldo', trigger, 'mega', user_id, name)
        run.update(status='pendiente', file=name, bytes=len(blob), raw_bytes=result['bytes'], sha256=digest(blob), tier=od.tier(moment), runner='equipo-local',
                   source_sha256=result['sha256'], error='Pendiente de subir a MEGA.')
        od.save_run(c, run)
    _save_meta(folder, {'file': name, 'run': run['id'], 'sha256': run['sha256'], 'bytes': len(blob), 'created_at': run['started_at'],
                        'counts': {'clients': result['clients'], 'orders': result['orders']}, 'tables': result['tables'], 'attempts': 0, 'last_error': ''})
    upload_pending(mega)
    with app.connect() as c:
        return next((item for item in od.runs(c) if item['id'] == run['id']), run)


def upload_pending(mega=None):
    """Sube, verifica y confirma cada pendiente (el más antiguo primero). Sin MEGA o sin internet, quedan pendientes con su motivo."""
    import app
    mega = mega or Mega()
    folder = exchange_dir()
    pending = _pending(folder)
    if not pending:
        return {'uploaded': 0, 'pending': 0}
    owner = 'agente-' + secrets.token_hex(4)
    with app.connect() as c:
        if not od.acquire_lock(c, owner):
            return {'uploaded': 0, 'pending': len(pending), 'busy': True}
    uploaded = 0
    try:
        account = None
        try:
            account = mega.whoami()
            if not account:
                raise MegaError('MEGA desconectado: el agente no tiene sesión iniciada.')
            space = mega.space()
            need = sum(item['bytes'] for item in pending)
            if space and space['total'] - space['used'] < need * 2:
                raise MegaError('Espacio insuficiente en MEGA para subir %d respaldo(s).' % len(pending))
            mega.mkdir(REMOTE)
        except MegaError as error:
            _mark_failed(folder, pending, str(error))
            return {'uploaded': 0, 'pending': len(pending), 'error': str(error)}
        for item in pending:
            try:
                _upload_one(mega, folder, item)
                uploaded += 1
            except (MegaError, RuntimeError, OSError) as error:
                _mark_failed(folder, [item], str(error))
        if uploaded:
            _apply_retention(mega)
        return {'uploaded': uploaded, 'pending': len(_pending(folder))}
    finally:
        with app.connect() as c:
            od.release_lock(c, owner)


def _mark_failed(folder, items, reason):
    import app
    with app.connect() as c:
        for item in items:
            item['attempts'] = int(item.get('attempts', 0)) + 1
            item['last_error'] = reason[:240]
            item['last_try'] = od.stamp()
            _save_meta(folder, item)
            run = next((r for r in od.runs(c) if r.get('id') == item.get('run')), None)
            if run:
                # No se oculta: queda pendiente con el motivo real; solo un fallo de integridad del archivo subido es «error».
                run.update(status='error' if 'no coincide' in reason or 'descifrar' in reason else 'pendiente', error=reason[:240], attempts=item['attempts'])
                od.save_run(c, run)


def _upload_one(mega, folder, item):
    import app
    local = folder / 'pendientes' / item['file']
    remote = REMOTE + '/' + item['file']
    if item['file'] not in mega.ls(REMOTE):
        mega.put(local, REMOTE)
    # Verificación real: se descarga lo que quedó en MEGA, se compara el SHA-256, se descifra y se restaura en una base aislada.
    with tempfile.TemporaryDirectory(prefix='verificacion-', dir=folder / 'verificacion') as temp:
        mega.get(remote, temp)
        copy = Path(temp) / item['file']
        if not copy.exists():
            raise MegaError('La descarga de comprobación desde MEGA no trajo el archivo.')
        blob = copy.read_bytes()
    if digest(blob) != item['sha256']:
        mega.trash(remote)
        raise RuntimeError('El archivo en MEGA no coincide (SHA-256) con el subido; se envió a la papelera y se volverá a subir.')
    sha, restored = restore_check(blob, item['sha256'])
    if restored['counts'].get('clients', 0) != item['counts'].get('clients') or restored['counts'].get('orders', 0) != item['counts'].get('orders'):
        raise RuntimeError('La base restaurada desde MEGA no tiene los mismos recuentos que la copia original.')
    with app.connect() as c:
        run = next((r for r in od.runs(c) if r.get('id') == item.get('run')), None) or od.new_run('respaldo', 'programado', 'mega', None, item['file'])
        run.update(status='correcto', verified=True, verify=_summary(restored), verified_at=od.stamp(), finished_at=od.stamp(), error='', remote=remote, runner='equipo-local')
        od.save_run(c, run)
        od.keep_legacy(c)
        od.set_state(c, 'cloud_backup', {'ok': True, 'at': run.get('started_at') or od.stamp(), 'bytes': item['bytes'], 'sha256': item['sha256'],
                                         'clients': item['counts'].get('clients', 0), 'orders': item['counts'].get('orders', 0), 'destination': 'mega'})
        c.commit()
    local.unlink(missing_ok=True)
    (folder / 'pendientes' / (item['file'] + '.json')).unlink(missing_ok=True)


def _apply_retention(mega):
    names = [name for name in mega.ls(REMOTE) if name.startswith(od.PREFIX) and name.endswith(od.SUFFIX)]
    for name in od.retention(names):
        mega.trash(REMOTE + '/' + name)


def verify_remote(file, kind='verificacion', user_id=None, mega=None):
    """Verificación o restauración de prueba de un respaldo de MEGA: descarga, SHA-256, descifrado y restauración aislada."""
    import app
    mega = mega or Mega()
    folder = exchange_dir()
    with app.connect() as c:
        source = next((r for r in od.runs(c) if r.get('destination') == 'mega' and r.get('kind') == 'respaldo' and r.get('status') == 'correcto' and r.get('file') == file), None)
        run = od.new_run(kind, 'manual' if user_id else 'programado', 'mega', user_id, file)
        run['runner'] = 'equipo-local'
        od.save_run(c, run)
    try:
        if not source:
            raise RuntimeError('No hay un respaldo de MEGA verificado con ese nombre en el historial.')
        with tempfile.TemporaryDirectory(prefix='verificacion-', dir=folder / 'verificacion') as temp:
            mega.get(REMOTE + '/' + file, temp)
            blob = (Path(temp) / file).read_bytes()
        sha, restored = restore_check(blob, source.get('sha256'))
        run.update(status='correcto', verified=True, verify=_summary(restored), bytes=len(blob), sha256=sha, finished_at=od.stamp(), source=source['id'])
    except Exception as error:
        run.update(status='error', error=(type(error).__name__ + ': ' + str(error))[:240], finished_at=od.stamp())
    with app.connect() as c:
        od.save_run(c, run)
    if run['status'] != 'correcto':
        raise RuntimeError(run['error'])
    return run


def prepare_download(file, mega=None):
    """Enlace de MEGA del archivo CIFRADO, válido 24 h (después el agente lo retira). Sin la clave no se puede abrir."""
    import app
    mega = mega or Mega()
    link = mega.export(REMOTE + '/' + file)
    with app.connect() as c:
        items = [item for item in (od.get_state(c, 'mega_downloads', []) or []) if item.get('file') != file]
        items.insert(0, {'file': file, 'link': link, 'created_at': od.stamp(), 'expires_at': (od.now() + timedelta(hours=24)).isoformat(timespec='seconds')})
        od.set_state(c, 'mega_downloads', items[:10])
        c.commit()
    return link


def expire_downloads(mega=None):
    import app
    mega = mega or Mega()
    with app.connect() as c:
        items = od.get_state(c, 'mega_downloads', []) or []
        keep = []
        for item in items:
            if (item.get('expires_at') or '') <= od.stamp():
                mega.unexport(REMOTE + '/' + item['file'])
            else:
                keep.append(item)
        if len(keep) != len(items):
            od.set_state(c, 'mega_downloads', keep)
            c.commit()


def heartbeat(mega=None, full=True, error=''):
    """Estado real que ve el panel: señal del agente, sesión de MEGA, espacio, carpeta y pendientes."""
    import app
    import socket
    mega = mega or Mega()
    folder = exchange_dir()
    with app.connect() as c:
        state = od.get_state(c, 'mega_agent', {}) or {}
    state.update(seen_at=od.stamp(), host=socket.gethostname(), version=AGENT_VERSION, folder=REMOTE,
                 schedule='Todos los días a las 02:00 (hora de Ecuador) y reintentos cada hora', last_error=error or state.get('last_error', ''))
    state['pending'] = [{key: item.get(key) for key in ('file', 'bytes', 'created_at', 'attempts', 'last_error', 'last_try')} for item in _pending(folder)]
    if full:
        try:
            account = mega.whoami()
            state['connected'] = bool(account)
            state['account'] = account or ''
            if account:
                state['space'] = mega.space() or state.get('space')
                try:
                    mega.ls(REMOTE)
                    state['folder_ok'] = True
                except MegaError:
                    state['folder_ok'] = False
            code, text = mega.run('mega-version', check=False, timeout=60)
            state['mega_version'] = ' '.join(text.split())[:60] if code == 0 else state.get('mega_version', '')
            state['last_error'] = error
        except MegaError as problem:
            state.update(connected=False, last_error=str(problem)[:240])
    with app.connect() as c:
        od.set_state(c, 'mega_agent', state)
        c.commit()
    return state


def handle_requests(local_folder, mega=None):
    """Atiende las órdenes del panel (una a la vez) y anota el resultado real."""
    import app
    mega = mega or Mega()
    with app.connect() as c:
        items = od.requests(c)
        todo = [item for item in reversed(items) if item.get('status') == 'pendiente']
    for item in todo:
        _set_request(item['id'], status='en_curso')
        try:
            action = item['action']
            if action == 'respaldo':
                run = daily(local_folder, 'manual', item.get('requested_by'), mega)
                result = 'Respaldo ' + run['file'] + (' subido a MEGA y verificado.' if run['status'] == 'correcto' else ' guardado y pendiente de subir: ' + (run.get('error') or ''))
            elif action in ('verificar', 'restaurar'):
                run = verify_remote(item['file'], 'verificacion' if action == 'verificar' else 'restauracion', item.get('requested_by'), mega)
                result = 'Correcto: SHA-256 coincide y la base se restauró aislada (%s tablas).' % run['verify']['tables']
            elif action == 'descargar':
                prepare_download(item['file'], mega)
                result = 'Enlace de descarga preparado (válido 24 h). El archivo está cifrado.'
            elif action == 'carpeta':
                mega.mkdir(REMOTE)
                result = 'Carpeta ' + REMOTE + ' lista en MEGA.'
            elif action == 'reintentar':
                done = upload_pending(mega)
                result = 'Subidos %d; pendientes %d.' % (done.get('uploaded', 0), done.get('pending', 0)) + (' ' + done['error'] if done.get('error') else '')
            else:
                state = heartbeat(mega)
                space = state.get('space') or {}
                result = ('Conectado como ' + state['account'] + (' · %.1f de %.1f GB usados' % (space['used'] / 1e9, space['total'] / 1e9) if space.get('total') else '')) if state.get('connected') else 'MEGA desconectado: ' + (state.get('last_error') or 'sin sesión iniciada.')
            # Primero el estado real (pendientes, espacio) y después la orden como hecha: el panel nunca ve un estado anterior.
            heartbeat(mega)
            _set_request(item['id'], status='hecho', result=result)
        except Exception as error:
            heartbeat(mega)
            _set_request(item['id'], status='error', result=(str(error) or type(error).__name__)[:240])


def _set_request(request_id, **changes):
    import app
    with app.connect() as c:
        items = od.requests(c)
        for item in items:
            if item['id'] == request_id:
                item.update(changes)
                if changes.get('status') in ('hecho', 'error'):
                    item['finished_at'] = od.stamp()
        od.set_state(c, 'backup_requests', items)
        c.commit()


def weekly_restore_test(mega=None):
    """Prueba periódica: una vez por semana se descarga y restaura aislado el respaldo de MEGA más reciente."""
    import app
    with app.connect() as c:
        items = od.runs(c)
    week = (od.now() - timedelta(days=7)).isoformat(timespec='seconds')
    if any(item.get('kind') == 'restauracion' and item.get('status') == 'correcto' and (item.get('finished_at') or '') > week for item in items):
        return None
    latest = next((item for item in items if item.get('destination') == 'mega' and item.get('kind') == 'respaldo' and item.get('status') == 'correcto'), None)
    return verify_remote(latest['file'], 'restauracion', None, mega) if latest else None


def serve(local_folder, mega=None, cycles=None, pause=30):
    """Servicio del agente: señal y órdenes del panel cada 30 s; reintento de pendientes cada hora; prueba de restauración semanal."""
    mega = mega or Mega()
    last_retry = last_full = 0.0
    count = 0
    while cycles is None or count < cycles:
        count += 1
        moment = time.time()
        try:
            heartbeat(mega, full=moment - last_full > 300)
            if moment - last_full > 300:
                last_full = moment
            handle_requests(local_folder, mega)
            if moment - last_retry > 3600:
                last_retry = moment
                upload_pending(mega)
                expire_downloads(mega)
                try:
                    weekly_restore_test(mega)
                except Exception:
                    pass
        except Exception as error:
            print('agente:', type(error).__name__, str(error)[:200], flush=True)
        if cycles is None or count < cycles:
            time.sleep(pause)
