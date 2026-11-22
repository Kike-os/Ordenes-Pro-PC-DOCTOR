"""Motor de respaldos de Órdenes Pro (1.5.312): copia consistente, cifrado, verificación y Google Drive (en el servidor).

Procedimiento: el esquema y todas las filas de la base central se leen dentro de UNA transacción de lectura (instantánea consistente) y
se escriben en una base SQLite nueva, comprobada con integrity_check, foreign_key_check y el recuento de cada tabla. Para Google Drive se
comprime (gzip) y se cifra (AES-256-GCM con BACKUP_ENCRYPTION_KEY), se sube, se compara con el SHA-256 que calcula Google, se DESCARGA,
se descifra y se restaura en una base aislada: solo entonces cuenta como respaldado. La copia local del equipo de la oficina
(maintenance/backup-cloud.py) es independiente. Nunca se registran datos de clientes: solo recuentos."""
import base64
import gzip
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
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
        raise KeyMissing('Falta la clave de cifrado de los respaldos (BACKUP_ENCRYPTION_KEY en el servidor, o ~/.config/ordenes-pro/backup.key en el equipo). Sin ella no se cifra ni se recupera ningún respaldo.')
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




# ================================================================ GOOGLE DRIVE (en el servidor)
def _start(kind, trigger, user_id=None, file=''):
    """Comprueba la configuración ANTES de registrar nada y toma el bloqueo. Errores con explicación para el panel."""
    import app
    import gdrive_backup as gd
    encryption_key()
    with app.connect() as c:
        problem = gd.not_ready(c)
        if problem:
            raise gd.BackupError(problem, 409)
        run = od.new_run(kind, trigger, 'gdrive', user_id, file)
        run.update(runner='servidor' if os.getenv('VERCEL') else 'equipo-local')
        if not od.acquire_lock(c, run['id']):
            raise gd.BackupError('Ya hay un respaldo o una verificación en curso. Espera a que termine.', 409)
        od.save_run(c, run)
    return run


def _finish(run, error=None):
    import app
    import gdrive_backup as gd
    with app.connect() as c:
        if error is not None:
            run.update(status='error', finished_at=od.stamp(), error=str(error)[:300] if isinstance(error, gd.BackupError) else (type(error).__name__ + ': ' + str(error))[:300])
        else:
            run.update(status='correcto', finished_at=od.stamp())
        od.save_run(c, run)
        od.release_lock(c, run['id'])


def drive_backup(trigger='programado', user_id=None):
    """Copia consistente → comprobación → gzip + AES-256-GCM → subida a Google Drive → comparación con el SHA-256 que calcula
    Google → nueva DESCARGA → descifrado → restauración aislada con los mismos recuentos. Solo entonces es válido."""
    import app
    import gdrive_backup as gd
    run = _start('respaldo', trigger, user_id)
    try:
        moment = od.now()
        with tempfile.TemporaryDirectory(prefix='ordenes-respaldo-') as folder:
            target = Path(folder) / 'base.sqlite3'
            remote, tables, check = snapshot(target)
            raw = target.read_bytes()
        blob = encrypt(raw)
        name = od.file_name(moment)
        sha = digest(blob)
        run.update(file=name, raw_bytes=len(raw), bytes=len(blob), sha256=sha, tier=od.tier(moment))
        with app.connect() as c:
            od.save_run(c, run)
            token = gd.access_token(c)
            link = od.get_state(c, 'gdrive_link') or {}
        folder_id = link.get('folder_id') or gd.ensure_folder(token)['id']
        try:
            item = gd.upload(token, folder_id, name, blob, sha)
        except gd.GoogleError as error:
            if error.http_status == 404:
                # La carpeta se borró desde Drive: se vuelve a crear y se reintenta una vez.
                folder_id = gd.ensure_folder(token)['id']
                item = gd.upload(token, folder_id, name, blob, sha)
            else:
                raise
        run['remote_id'] = item['id']
        # 1) Google confirma que existe y su SHA-256 coincide; 2) se descarga y se restaura aislada.
        info = gd.file_info(token, item['id'])
        if info.get('trashed') or int(info.get('size', -1)) != len(blob):
            raise RuntimeError('Google Drive no muestra el archivo completo tras la subida.')
        if info.get('sha256Checksum') and info['sha256Checksum'].lower() != sha:
            gd.trash(token, item['id'])
            raise RuntimeError('El SHA-256 que calcula Google no coincide con el del archivo subido; se envió a la papelera.')
        got, restored = restore_check(gd.download(token, item['id']), sha)
        if restored['counts'] != remote:
            raise RuntimeError('La base restaurada desde Google Drive no tiene el mismo número de filas que la central.')
        run.update(verified=True, verify=_summary(restored), verified_at=od.stamp(), google_sha256=info.get('sha256Checksum', ''))
        with app.connect() as c:
            od.keep_legacy(c)
            od.set_state(c, 'cloud_backup', {'ok': True, 'at': run['started_at'], 'bytes': len(blob), 'sha256': sha, 'clients': remote.get('clients', 0), 'orders': remote.get('orders', 0), 'destination': 'gdrive'})
            link = od.get_state(c, 'gdrive_link') or {}
            link['folder_id'] = folder_id
            try:
                link['quota'] = gd.drive_about(token).get('storageQuota') or link.get('quota')
            except Exception:
                pass
            od.set_state(c, 'gdrive_link', link)
            c.commit()
        # Conservación 30/12/12 solo sobre respaldos de Órdenes Pro; lo que sobra va a la papelera de Google Drive.
        existing = gd.list_backups(token, folder_id)
        doomed = set(od.retention([entry['name'] for entry in existing]))
        removed = 0
        for entry in existing:
            if entry['name'] in doomed and entry['name'] != name:
                gd.trash(token, entry['id'])
                removed += 1
        run['retention'] = {'kept': len(existing) - removed, 'removed': removed}
        _finish(run)
        return run
    except BaseException as error:
        _finish(run, error)
        raise


def drive_verify(kind, file, trigger='manual', user_id=None):
    """«Verificar integridad» y «Restauración de prueba»: el archivo existe en Drive, su SHA-256 coincide, se descarga y se restaura aislado."""
    import app
    import gdrive_backup as gd
    run = _start(kind, trigger, user_id, file)
    try:
        with app.connect() as c:
            history = od.runs(c)
            token = gd.access_token(c)
            link = od.get_state(c, 'gdrive_link') or {}
        source = next((item for item in history if item.get('destination') == 'gdrive' and item.get('kind') == 'respaldo' and item.get('status') == 'correcto' and item.get('file') == file), None)
        if not source:
            raise RuntimeError('No hay un respaldo de Google Drive verificado con ese nombre en el historial.')
        entry = next((f for f in gd.list_backups(token, link.get('folder_id') or gd.ensure_folder(token)['id']) if f['name'] == file), None)
        if not entry:
            raise RuntimeError('El respaldo ya no está en la carpeta de Google Drive (¿se eliminó o está en la papelera?).')
        info = gd.file_info(token, entry['id'])
        if info.get('sha256Checksum') and info['sha256Checksum'].lower() != source.get('sha256'):
            raise RuntimeError('El SHA-256 del archivo en Google Drive no coincide con el registrado al subirlo.')
        sha, restored = restore_check(gd.download(token, entry['id']), source.get('sha256'))
        run.update(bytes=int(entry.get('size') or 0), sha256=sha, verified=True, verify=_summary(restored), verified_at=od.stamp(), source=source['id'])
        _finish(run)
        return run
    except BaseException as error:
        _finish(run, error)
        raise


def weekly_restore_test():
    """Prueba periódica: una vez por semana se descarga y restaura aislado el respaldo de Google Drive más reciente."""
    import app
    with app.connect() as c:
        items = od.runs(c)
    week = (od.now() - timedelta(days=7)).isoformat(timespec='seconds')
    if any(item.get('kind') == 'restauracion' and item.get('status') == 'correcto' and (item.get('finished_at') or '') > week for item in items):
        return None
    latest = next((item for item in items if item.get('destination') == 'gdrive' and item.get('kind') == 'respaldo' and item.get('status') == 'correcto'), None)
    return drive_verify('restauracion', latest['file'], 'programado') if latest else None
