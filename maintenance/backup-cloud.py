#!/usr/bin/env python
"""Respaldo completo y verificado de la base de datos central (libSQL/Turso), en este equipo y en Microsoft OneDrive.

Uso (desde la raíz del proyecto, con las variables de producción):
    vercel env run -e production -- python maintenance/backup-cloud.py          # copia local en este equipo (como hasta ahora)
    python maintenance/backup-cloud.py --verify <archivo>                         # prueba de restauración local en un entorno aislado
    python maintenance/backup-cloud.py --modo respaldo  [--solicitud ID]          # respaldo cifrado en OneDrive (GitHub Actions)
    python maintenance/backup-cloud.py --modo verificar [--archivo N] [--solicitud ID]
    python maintenance/backup-cloud.py --modo restaurar --archivo N [--solicitud ID]  # restauración de prueba aislada
    python maintenance/backup-cloud.py --descifrar <archivo.enc> --salida <base.sqlite3>  # recuperación manual (necesita la clave)

Procedimiento de copia (no basta con copiar el archivo de la base): el esquema y todas las filas se leen dentro de UNA transacción
de lectura (instantánea consistente) y se escriben en una base SQLite nueva; la copia se comprueba con integrity_check,
foreign_key_check y el recuento de cada tabla. Para OneDrive se comprime (gzip) y se cifra (AES-256-GCM con BACKUP_ENCRYPTION_KEY),
se sube, se DESCARGA de nuevo, se compara su SHA-256, se descifra y se restaura en una base aislada: solo entonces cuenta como válido.
Nunca imprime datos de clientes: solo recuentos. Solo lee la base de producción; escribe únicamente el historial de respaldos.
"""
import argparse
import base64
import gzip
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'local'))
DEFAULT_DIR = Path.home() / 'Respaldos-OrdenesPro'
KEEP = 30
ECUADOR = timezone(timedelta(hours=-5))
MAGIC = b'OPRB\x01'


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
    import onedrive_backup as od
    with app.connect() as c:
        od.save_run(c, run)


def backup(folder):
    """Copia local en este equipo (independiente de OneDrive). Conserva las últimas 30."""
    import app
    import remote_db
    import onedrive_backup as od
    if not remote_db.configured():
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
        # El resultado queda también en la base central para que la aplicación avise si los respaldos se atrasan.
        source.execute("INSERT INTO system_state VALUES ('cloud_backup',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps({key: result[key] for key in ('ok', 'at', 'bytes', 'sha256', 'clients', 'orders')}),))
        source.commit()
        run = od.new_run('respaldo', 'programado', 'equipo')
        run.update(status='correcto', started_at=result['at'], finished_at=od.stamp(), file=target.name, bytes=result['bytes'], raw_bytes=result['bytes'], sha256=result['sha256'],
                   verified=True, verify=_summary(check), runner='equipo-local')
        od.save_run(source, run)
    return result


def _summary(check):
    counts = check['counts']
    return {'integrity': check['integrity'], 'foreign_key_errors': check['foreign_key_errors'], 'tables': len(counts), 'rows': sum(counts.values()),
            'clients': counts.get('clients', 0), 'orders': counts.get('orders', 0), 'orders_linked_to_clients': check.get('orders_linked_to_clients', 0)}


# ---------------------------------------------------------------- cifrado de respaldos (AES-256-GCM)
def encryption_key():
    raw = os.getenv('BACKUP_ENCRYPTION_KEY', '').strip()
    try:
        key = base64.b64decode(raw + '=' * (-len(raw) % 4)) if raw else b''
    except ValueError:
        key = b''
    if len(key) != 32:
        raise SystemExit('Falta BACKUP_ENCRYPTION_KEY (32 bytes en base64). Sin ella no se cifra ni se recupera ningún respaldo.')
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
        raise RuntimeError('El SHA-256 del archivo en OneDrive no coincide con el registrado al subirlo.')
    with tempfile.TemporaryDirectory(prefix='ordenes-restauracion-') as folder:
        path = Path(folder) / 'restaurada.sqlite3'
        path.write_bytes(decrypt(blob))
        check = verify(path)
    if check['integrity'] != 'ok' or check['foreign_key_errors']:
        raise RuntimeError('La base restaurada no superó la comprobación de integridad.')
    return sha, check


# ---------------------------------------------------------------- OneDrive
def _start(kind, run_id, file=''):
    import app
    import onedrive_backup as od
    for name in ('ONEDRIVE_TOKEN_KEY', 'MS_CLIENT_ID', 'MS_CLIENT_SECRET'):
        if not os.getenv(name, '').strip():
            raise SystemExit('Falta la variable ' + name + ' en el generador de respaldos.')
    with app.connect() as c:
        run = (od.find_run(c, run_id) if run_id else None) or od.new_run(kind, 'manual' if run_id else 'programado', 'onedrive', file=file)
        run.update(status='en_curso', started_at=od.stamp(), runner=os.getenv('BACKUP_RUNNER', 'github-actions' if os.getenv('GITHUB_ACTIONS') else 'equipo-local'), error='')
        if file:
            run['file'] = file
        od.save_run(c, run)
        owner = run['id']
        if not od.acquire_lock(c, owner):
            run.update(status='error', finished_at=od.stamp(), error='Ya había otro respaldo en curso; esta ejecución no se hizo para no duplicarlo.')
            od.save_run(c, run)
            raise SystemExit(run['error'])
    return run


def _finish(run, error=None):
    import app
    import onedrive_backup as od
    with app.connect() as c:
        if error is not None:
            run.update(status='error', finished_at=od.stamp(), error=(type(error).__name__ + ': ' + str(error))[:300] if not isinstance(error, od.BackupError) else str(error)[:300])
        else:
            run.update(status='correcto', finished_at=od.stamp())
        od.save_run(c, run)
        od.release_lock(c, run['id'])


def onedrive_backup(run_id=None):
    import app
    import onedrive_backup as od
    encryption_key()
    run = _start('respaldo', run_id)
    try:
        moment = od.now()
        with tempfile.TemporaryDirectory(prefix='ordenes-respaldo-') as folder:
            target = Path(folder) / 'base.sqlite3'
            remote, tables, check = snapshot(target)
            raw = target.read_bytes()
        blob = encrypt(raw)
        name = od.file_name(moment)
        run.update(file=name, raw_bytes=len(raw), bytes=len(blob), sha256=digest(blob), tier=od.tier(moment))
        _record(run)
        with app.connect() as c:
            token = od.access_token(c)
        od.ensure_folder(token)
        item = od.upload(token, name, blob)
        run['remote_id'] = item['id']
        # Verificación real: se descarga lo que quedó en OneDrive, se compara el SHA-256, se descifra y se restaura aislado.
        sha, restored = restore_check(od.download(token, item['id']), run['sha256'])
        if restored['counts'] != remote:
            raise RuntimeError('La base restaurada desde OneDrive no tiene el mismo número de filas que la central.')
        run.update(verified=True, verify=_summary(restored), verified_at=od.stamp())
        with app.connect() as c:
            od.set_state(c, 'cloud_backup', {'ok': True, 'at': run['started_at'], 'bytes': run['bytes'], 'sha256': run['sha256'], 'clients': remote.get('clients', 0), 'orders': remote.get('orders', 0), 'destination': 'onedrive'})
            c.commit()
        # Retención 30/12/12 solo sobre respaldos de Órdenes Pro de esa carpeta; lo borrado va a la papelera de OneDrive.
        existing = od.list_backups(token)
        doomed = set(od.retention([entry['name'] for entry in existing]))
        removed = 0
        for entry in existing:
            if entry['name'] in doomed and entry['name'] != name:
                od.delete(token, entry['id'])
                removed += 1
        run['retention'] = {'kept': len(existing) - removed, 'removed': removed}
        _finish(run)
        return run
    except BaseException as error:
        _finish(run, error)
        raise


def onedrive_verify(kind, file, run_id=None):
    import app
    import onedrive_backup as od
    encryption_key()
    run = _start(kind, run_id, file)
    try:
        with app.connect() as c:
            history = od.runs(c)
            token = od.access_token(c)
        source = next((item for item in history if item.get('destination') == 'onedrive' and item.get('kind') == 'respaldo' and item.get('status') == 'correcto' and (not file or item.get('file') == file)), None)
        if not source:
            raise RuntimeError('No hay un respaldo correcto de OneDrive con ese nombre en el historial.')
        run['file'] = source['file']
        remote = {entry['name']: entry for entry in od.list_backups(token)}
        entry = remote.get(source['file'])
        if not entry:
            raise RuntimeError('El respaldo ya no está en la carpeta de OneDrive (¿se eliminó o pasó a la papelera?).')
        sha, restored = restore_check(od.download(token, entry['id']), source.get('sha256'))
        run.update(bytes=int(entry.get('size') or 0), sha256=sha, verified=True, verify=_summary(restored), verified_at=od.stamp(), source=source['id'])
        _finish(run)
        return run
    except BaseException as error:
        _finish(run, error)
        raise


def main():
    parser = argparse.ArgumentParser(description='Respaldo de la base de datos central de Órdenes Pro.')
    parser.add_argument('--dir', type=Path, default=Path(os.getenv('ORDENES_BACKUP_DIR', DEFAULT_DIR)))
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--modo', choices=('respaldo', 'verificar', 'restaurar'))
    parser.add_argument('--archivo', default='')
    parser.add_argument('--solicitud', default='')
    parser.add_argument('--descifrar', type=Path)
    parser.add_argument('--salida', type=Path)
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.verify), ensure_ascii=False))
        return
    if args.descifrar:
        if not args.salida or args.salida.exists():
            raise SystemExit('Indica con --salida un archivo NUEVO para la base descifrada (nunca se sobrescribe nada).')
        plain = decrypt(args.descifrar.read_bytes())
        old_mask = os.umask(0o077)
        try:
            args.salida.write_bytes(plain)
        finally:
            os.umask(old_mask)
        print(json.dumps(_summary(verify(args.salida)), ensure_ascii=False))
        return
    if args.modo:
        if args.modo == 'respaldo':
            run = onedrive_backup(args.solicitud or None)
        else:
            run = onedrive_verify('verificacion' if args.modo == 'verificar' else 'restauracion', args.archivo, args.solicitud or None)
        print(json.dumps({key: run.get(key) for key in ('id', 'kind', 'status', 'file', 'bytes', 'sha256', 'verified', 'verify', 'retention')}, ensure_ascii=False))
        return
    log = args.dir / 'respaldos.log'
    try:
        result = backup(args.dir)
    except BaseException as error:
        args.dir.mkdir(parents=True, exist_ok=True)
        with open(log, 'a', encoding='utf-8') as handle:
            handle.write(datetime.now(ECUADOR).isoformat(timespec='seconds') + ' ERROR ' + type(error).__name__ + ': ' + str(error)[:200] + '\n')
        raise
    with open(log, 'a', encoding='utf-8') as handle:
        handle.write(result['at'] + ' OK ' + result['file'] + ' ' + str(result['bytes']) + ' bytes clientes=' + str(result['clients']) + ' ordenes=' + str(result['orders']) + ' sha256=' + result['sha256'] + '\n')
    os.chmod(log, 0o600)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
