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
        raw, manifest, remote = build_full_archive(run)
        _stage(run, 'cifrado')
        blob = encrypt_archive(raw)
        name = od.file_name(moment, full=True)
        sha = digest(blob)
        run.update(file=name, raw_bytes=len(raw), bytes=len(blob), sha256=sha, tier=od.tier(moment), full=True,
                   contents={'base_bytes': manifest['base']['bytes'], 'tablas': manifest['base']['tablas'], 'filas': manifest['base']['filas'],
                             'filas_de_archivos': manifest['base']['filas_de_archivos'], 'codigo_archivos': manifest['codigo']['archivos'],
                             'version': manifest['version'], 'commit': manifest['commit'][:12], 'variables': len(manifest['configuracion']['variables']),
                             'tareas': len(manifest['tareas_programadas']), 'faltantes': manifest['faltantes']})
        with app.connect() as c:
            od.save_run(c, run)
            token = gd.access_token(c)
            link = od.get_state(c, 'gdrive_link') or {}
            # Espacio antes de subir: hace falta el tamaño del respaldo con margen.
            quota = gd.drive_about(token).get('storageQuota') or {}
            if quota.get('limit') and int(quota['limit']) - int(quota.get('usage', 0)) < len(blob) * 2:
                raise gd.BackupError('Espacio insuficiente en Google Drive para el respaldo completo (%d MB).' % (len(blob) // 1048576 + 1), 507)
        folder_id = link.get('folder_id') or gd.ensure_folder(token)['id']
        _stage(run, 'subida')
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
        _stage(run, 'verificacion')
        # 1) Google confirma que existe y su SHA-256 coincide; 2) se descarga, se comprueba cada archivo y se restaura la base aislada.
        info = gd.file_info(token, item['id'])
        if info.get('trashed') or int(info.get('size', -1)) != len(blob):
            raise RuntimeError('Google Drive no muestra el archivo completo tras la subida.')
        if info.get('sha256Checksum') and info['sha256Checksum'].lower() != sha:
            gd.trash(token, item['id'])
            raise RuntimeError('El SHA-256 que calcula Google no coincide con el del archivo subido; se envió a la papelera.')
        got, inspected = inspect_archive(gd.download(token, item['id']), sha)
        if inspected['db']['counts'] != remote:
            raise RuntimeError('La base restaurada desde Google Drive no tiene el mismo número de filas que la central.')
        if inspected['bad']:
            raise RuntimeError('Archivos alterados tras la descarga: ' + ', '.join(inspected['bad'][:5]))
        summary = _summary(inspected['db'])
        summary.update(files_checked=inspected['files_checked'], env_vars=inspected['env_vars'], complete=inspected['completo'], missing=inspected['faltantes'])
        run.update(verified=True, verify=summary, verified_at=od.stamp(), google_sha256=info.get('sha256Checksum', ''), complete=inspected['completo'])
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
        _stage(run, 'conservacion')
        existing = gd.list_backups(token, folder_id)
        doomed = set(od.retention([entry['name'] for entry in existing]))
        removed = 0
        for entry in existing:
            if entry['name'] in doomed and entry['name'] != name:
                gd.trash(token, entry['id'])
                removed += 1
        run['retention'] = {'kept': len(existing) - removed, 'removed': removed}
        run['stage'] = ''
        _finish(run)
        if not run.get('complete'):
            # Subido y verificado, pero NO se llama «completo» si falta algo: queda como incompleto con la lista de lo que falta.
            with app.connect() as c:
                run.update(status='incompleto', error='Falta: ' + '; '.join(run['verify'].get('missing') or ['sin detalle'])[:280])
                od.save_run(c, run)
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
        source = next((item for item in history if item.get('destination') == 'gdrive' and item.get('kind') == 'respaldo' and item.get('status') in ('correcto', 'incompleto') and item.get('file') == file), None)
        if not source:
            raise RuntimeError('No hay un respaldo de Google Drive verificado con ese nombre en el historial.')
        entry = next((f for f in gd.list_backups(token, link.get('folder_id') or gd.ensure_folder(token)['id']) if f['name'] == file), None)
        if not entry:
            raise RuntimeError('El respaldo ya no está en la carpeta de Google Drive (¿se eliminó o está en la papelera?).')
        info = gd.file_info(token, entry['id'])
        if info.get('sha256Checksum') and info['sha256Checksum'].lower() != source.get('sha256'):
            raise RuntimeError('El SHA-256 del archivo en Google Drive no coincide con el registrado al subirlo.')
        if kind == 'restauracion':
            _stage(run, 'restauracion')
        with tempfile.TemporaryDirectory(prefix='ordenes-restaurado-') as folder:
            sha, inspected = inspect_archive(gd.download(token, entry['id']), source.get('sha256'), extract_to=folder if kind == 'restauracion' else None)
            if inspected['tipo'] == 'completo' and inspected['bad']:
                raise RuntimeError('Archivos alterados en el respaldo: ' + ', '.join(inspected['bad'][:5]))
            summary = _summary(inspected['db'])
            summary.update(files_checked=inspected.get('files_checked', 0), env_vars=inspected.get('env_vars', 0), complete=inspected['completo'], missing=inspected['faltantes'])
            if kind == 'restauracion' and inspected['tipo'] == 'completo':
                summary['functional'] = functional_check(folder)
        run.update(bytes=int(entry.get('size') or 0), sha256=sha, verified=True, verify=summary, verified_at=od.stamp(), source=source['id'], complete=inspected['completo'], stage='')
        _finish(run)
        if kind == 'restauracion' and summary.get('functional') and not summary['functional']['correcto']:
            with app.connect() as c:
                run.update(status='error', error='El sistema restaurado no superó las pruebas: ' + ', '.join(summary['functional']['fallidas'])[:240])
                od.save_run(c, run)
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


# ================================================================ RESPALDO COMPLETO (1.5.313): base + código + configuración + instrucciones
import io
import re
import tarfile

CODE_SKIP_DIRS = {'__pycache__', '.git', 'node_modules', 'tmp', 'revision', 'output', 'Ordenes-Pro-PC-DOCTOR', '.pytest_cache', '.venv', 'venv'}
CODE_SKIP_SUFFIX = ('.pyc', '.sqlite3', '.sqlite3-wal', '.sqlite3-shm', '.sqlite3-journal', '.zip', '.parcial', '.key', '.env')
REQUIRED_CODE = ('api/index.py', 'api/backup.py', 'local/app.py', 'local/backup_runner.py', 'local/gdrive_backup.py', 'local/backups.py', 'local/wsgi_app.py',
                 'local/static/app.js', 'local/static/app.css', 'local/static/logo-original.png', 'local/templates/dashboard.html', 'local/data/releases.json',
                 'vercel.json', 'requirements.txt', 'maintenance/backup-cloud.py', 'docs/RESPALDOS-GOOGLE-DRIVE.md')
MIN_MIGRATIONS = 100
REQUIRED_ENV = ('TURSO_DATABASE_URL', 'TURSO_AUTH_TOKEN', 'CRON_SECRET')
ENV_PREFIXES = ('TURSO_', 'SMTP_', 'MAIL_', 'FACTURACION_', 'AZUR_', 'WHATSAPP_', 'OPENAI_', 'OPEN_API', 'ANTHROPIC_', 'ADI_', 'TURNSTILE_', 'DELL_',
                'GOOGLE_CLIENT', 'MS_', 'CRON_', 'LOGIN_', 'SESSION_', 'APP_', 'PUBLIC_APP', 'PRODUCTION_', 'REQUIRE_', 'WEATHER_', 'APPOINTMENTS_',
                'MAINTENANCE_', 'UPDATE_', 'PASSWORD_', 'BACKUP_TOKEN', 'ONEDRIVE_TOKEN', 'LICENSE_', 'MFA_')
ENV_EXCLUDED = {'BACKUP_ENCRYPTION_KEY': 'Clave de descifrado de los respaldos: no se guarda dentro de lo que protege; se recupera con la copia offline.',
                'APP_DB': 'Ruta local de pruebas.', 'PORT': 'Puerto local.', 'BIND_HOST': 'Dirección local.'}
STAGES = {'base': 'Copia consistente de la base', 'codigo': 'Código y configuración', 'cifrado': 'Compresión y cifrado', 'subida': 'Subida a Google Drive',
          'verificacion': 'Verificación (SHA-256 de Google, descarga y restauración)', 'conservacion': 'Conservación de versiones', 'restauracion': 'Restauración de prueba aislada'}


def required_env():
    """Variables imprescindibles según dónde corre: con base central (Turso) sus credenciales; en Vercel, además, CRON_SECRET."""
    import remote_db
    names = []
    if remote_db.configured():
        names += ['TURSO_DATABASE_URL', 'TURSO_AUTH_TOKEN']
    if os.getenv('VERCEL'):
        names.append('CRON_SECRET')
    return names


def code_root():
    return Path(__file__).resolve().parents[1]


def code_files(root=None):
    """Código desplegado tal cual (frontend, backend, migraciones, plantillas, logos, dependencias, tareas, guiones y documentación)."""
    root = Path(root or code_root())
    files = []
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        parts = rel.parts
        if not path.is_file() or any(part in CODE_SKIP_DIRS for part in parts) or (len(parts) > 1 and parts[0] == 'local' and parts[1] == 'var'):
            continue
        if path.name.endswith(CODE_SKIP_SUFFIX) or path.name.startswith('.env'):
            continue
        files.append(rel.as_posix())
    return files


def referenced_env(root=None):
    names = set()
    root = Path(root or code_root())
    for folder in ('local', 'api', 'maintenance'):
        for path in (root / folder).glob('*.py'):
            names.update(re.findall(r"(?:getenv|environ\.get|environ\[)\(?\s*'([A-Z][A-Z0-9_]+)'", path.read_text(errors='ignore')))
    return names


def environment_snapshot(root=None):
    """Variables del servidor necesarias para reinstalar (credenciales incluidas; el archivo completo va cifrado). Nunca se imprimen."""
    wanted = referenced_env(root)
    out = {}
    for name, value in os.environ.items():
        if name in ENV_EXCLUDED or name.startswith(('VERCEL', 'AWS_', 'LAMBDA_')):
            continue
        if name in wanted or name.startswith(ENV_PREFIXES):
            out[name] = value
    return out


def _installed_version(root):
    try:
        data = json.loads((Path(root) / 'local' / 'data' / 'releases.json').read_text())
        return (data.get('releases') or [{}])[0].get('version', '')
    except (OSError, ValueError):
        return ''


def restore_guide(manifest):
    env = manifest['configuracion']
    crons = '\n'.join('  - `%s` → %s (UTC)' % (c.get('path'), c.get('schedule')) for c in manifest.get('tareas_programadas', [])) or '  - (sin tareas)'
    return """# Restaurar Órdenes Pro desde este respaldo completo

Versión %(version)s · commit %(commit)s · creado %(creado)s.

Este archivo es un respaldo COMPLETO: base de datos (todas las tablas, registros, fotos, documentos, firmas y comprobantes guardados en la
base), código desplegado (%(files)d archivos), configuración y credenciales del servidor (%(vars)d variables) y estas instrucciones.

## 0. Antes de empezar
- Necesitas la CLAVE DE RESPALDOS (BACKUP_ENCRYPTION_KEY). No está dentro de este archivo: es la copia offline que guardaste
  (gestor de contraseñas o impresa). Su huella SHA-256 empieza por: %(key_fp)s
- Descifrar:  BACKUP_ENCRYPTION_KEY=… python maintenance/backup-cloud.py --descifrar-completo ARCHIVO.tar.gz.enc --salida carpeta-nueva
  (o, sin el código a mano: python -c con cryptography; ver docs/RESTAURACION-COMPLETA.md dentro de codigo/).
- Comprueba el manifiesto: cada archivo trae su SHA-256 en manifiesto.json.

## 1. Base de datos
- base/ordenes-pro.sqlite3 es una base SQLite íntegra (integrity_check correcto al crearla).
- Turso (producción): crea una base NUEVA desde el archivo:  turso db create ordenes-pro-restaurada --from-file base/ordenes-pro.sqlite3
  y un token:  turso db tokens create ordenes-pro-restaurada.  La base anterior, si existe, no se toca.
- Sin Turso (servidor local): copia el archivo a codigo/local/var/ordenes.sqlite3.

## 2. Código
- codigo/ contiene el proyecto tal como estaba desplegado (api/, local/, maintenance/, docs/, vercel.json, requirements.txt).
- Súbelo a un repositorio y despliega en Vercel (Framework «Python», instalación «pip install -r requirements.txt»), o ejecuta
  localmente: python local/app.py serve (requiere Python 3.12+ y las dependencias de requirements.txt).

## 3. Configuración y credenciales
- configuracion/variables-entorno.json tiene las variables del servidor. Cárgalas en Vercel → Settings → Environment Variables (Production).
- Cambia TURSO_DATABASE_URL y TURSO_AUTH_TOKEN por los de la base restaurada.
- Añade BACKUP_ENCRYPTION_KEY con tu copia offline.
- Variables guardadas: %(var_names)s
- Faltaban en el servidor al crear el respaldo (no configuradas): %(missing_vars)s

## 4. Tareas programadas (vercel.json)
%(crons)s

## 5. Servicios externos a reconectar
- Vercel (hosting), Turso (base), dominio ordenes-pro.vercel.app.
- Google Drive (respaldos): Configuración → Respaldos; añade la nueva URI de redirección en Google Cloud si cambia el dominio.
- Correo Mail Pro (SMTP/IMAP), WhatsApp Business (Meta), Azur (facturación electrónica SRI), Cloudflare Turnstile, OpenAI/Anthropic (ADI),
  API de Dell: sus datos están en la base (cifrados con las claves de configuracion/) o en las variables. Si cambia el dominio, actualiza
  las URL de retorno/webhooks en cada servicio.

## 6. Comprobación
- Entra como administración, revisa Inicio, Órdenes, Clientes y un PDF de una orden.
- Configuración → Respaldos → «Crear respaldo completo ahora» para volver a proteger el sistema.
""" % {'version': manifest['version'], 'commit': manifest['commit'] or 'desconocido', 'creado': manifest['creado'], 'files': manifest['codigo']['archivos'],
       'vars': len(env['variables']), 'key_fp': manifest['clave_huella'], 'var_names': ', '.join(env['variables']) or '—',
       'missing_vars': ', '.join(env['referenciadas_no_configuradas']) or 'ninguna', 'crons': crons}


def _stage(run, stage):
    import app
    run['stage'] = stage
    run['stage_label'] = STAGES.get(stage, stage)
    with app.connect() as c:
        od.save_run(c, run)


def build_full_archive(run=None, root=None):
    """Construye el respaldo completo (tar) en memoria. Devuelve (tar_bytes, manifest, counts_central)."""
    import hashlib as _h
    root = Path(root or code_root())
    if run:
        _stage(run, 'base')
    with tempfile.TemporaryDirectory(prefix='ordenes-completo-') as folder:
        db = Path(folder) / 'base.sqlite3'
        remote, tables, check = snapshot(db)
        db_bytes = db.read_bytes()
    if run:
        _stage(run, 'codigo')
    files = code_files(root)
    listing, members = [], []
    for rel in files:
        data = (root / rel).read_bytes()
        listing.append({'ruta': rel, 'sha256': _h.sha256(data).hexdigest(), 'bytes': len(data)})
        members.append(('codigo/' + rel, data))
    missing_code = [name for name in REQUIRED_CODE if name not in files]
    migrations = len([f for f in files if f.startswith('local/migrations/') and f.endswith('.sql')])
    if migrations < MIN_MIGRATIONS:
        missing_code.append('local/migrations (%d de al menos %d)' % (migrations, MIN_MIGRATIONS))
    env = environment_snapshot(root)
    referenced = referenced_env(root)
    missing_env = [name for name in required_env() if not env.get(name)]
    try:
        crons = json.loads((root / 'vercel.json').read_text()).get('crons', [])
    except (OSError, ValueError):
        crons = []
    key = encryption_key()
    counts = check['counts']
    file_tables = {name: counts[name] for name in counts if re.search(r'(photo|upload|file|signature|image|document|receipt|evidence)', name)}
    manifest = {
        'tipo': 'completo', 'version': _installed_version(root), 'commit': os.getenv('VERCEL_GIT_COMMIT_SHA', '')[:40], 'creado': od.stamp(),
        'origen': os.getenv('VERCEL_REGION', '') or 'equipo-local', 'clave_huella': _h.sha256(key).hexdigest()[:16],
        'base': {'archivo': 'base/ordenes-pro.sqlite3', 'sha256': _h.sha256(db_bytes).hexdigest(), 'bytes': len(db_bytes), 'integridad': check['integrity'],
                 'errores_claves': check['foreign_key_errors'], 'tablas': len(counts), 'filas': sum(counts.values()), 'clientes': counts.get('clients', 0),
                 'ordenes': counts.get('orders', 0), 'tablas_de_archivos': file_tables, 'filas_de_archivos': sum(file_tables.values())},
        'codigo': {'archivos': len(files), 'bytes': sum(item['bytes'] for item in listing), 'migraciones': migrations, 'faltan': missing_code, 'lista': listing},
        'configuracion': {'archivo': 'configuracion/variables-entorno.json', 'variables': sorted(env), 'faltan_obligatorias': missing_env,
                          'referenciadas_no_configuradas': sorted(name for name in referenced if name not in env and name not in ENV_EXCLUDED and not name.startswith(('VERCEL', 'GOOGLE_ACCOUNTS', 'GOOGLE_OAUTH', 'GOOGLE_API'))),
                          'excluidas': ENV_EXCLUDED},
        'tareas_programadas': crons,
    }
    gaps = []
    if check['integrity'] != 'ok' or check['foreign_key_errors']:
        gaps.append('la base no superó la comprobación de integridad')
    gaps += ['falta el archivo de código ' + name for name in missing_code]
    gaps += ['falta la variable obligatoria ' + name for name in missing_env]
    manifest['faltantes'] = gaps
    manifest['completo'] = not gaps
    guide = restore_guide(manifest).encode()
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=1).encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as tar:
        def add(name, data):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = int(time.time())
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(data))
        add('manifiesto.json', manifest_bytes)
        add('LEEME-RESTAURAR.md', guide)
        add('base/ordenes-pro.sqlite3', db_bytes)
        add('configuracion/variables-entorno.json', json.dumps(env, ensure_ascii=False, indent=1, sort_keys=True).encode())
        for name, data in members:
            add(name, data)
    return buffer.getvalue(), manifest, remote


def encrypt_archive(tar_bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(encryption_key()).encrypt(nonce, gzip.compress(tar_bytes, 6), MAGIC)


def inspect_archive(blob, expected_sha=None, extract_to=None):
    """Comprobación de un respaldo descargado: SHA-256, descifrado, huella de CADA archivo del manifiesto, integridad y recuentos
    de la base. Respaldos antiguos (solo la base) se comprueban también, marcados como «solo base»."""
    import hashlib as _h
    sha = digest(blob)
    if expected_sha and sha != expected_sha:
        raise RuntimeError('El SHA-256 del archivo descargado no coincide con el registrado al subirlo.')
    plain = decrypt(blob)
    if not plain.startswith(b'SQLite format 3') and tarfile.is_tarfile(io.BytesIO(plain)) is False:
        raise RuntimeError('El respaldo descifrado no tiene un formato reconocible.')
    if plain.startswith(b'SQLite format 3'):
        with tempfile.TemporaryDirectory(prefix='ordenes-restauracion-') as folder:
            path = Path(folder) / 'restaurada.sqlite3'
            path.write_bytes(plain)
            check = verify(path)
        return sha, {'tipo': 'solo base', 'completo': False, 'faltantes': ['respaldo anterior: solo contiene la base de datos'], 'db': check}
    bad, seen = [], {}
    with tarfile.open(fileobj=io.BytesIO(plain), mode='r') as tar:
        manifest = json.loads(tar.extractfile('manifiesto.json').read())
        for member in tar.getmembers():
            if member.isfile():
                seen[member.name] = tar.extractfile(member).read()
    for item in manifest['codigo']['lista']:
        data = seen.get('codigo/' + item['ruta'])
        if data is None or _h.sha256(data).hexdigest() != item['sha256']:
            bad.append(item['ruta'])
    db_bytes = seen.get('base/ordenes-pro.sqlite3', b'')
    if _h.sha256(db_bytes).hexdigest() != manifest['base']['sha256']:
        bad.append('base/ordenes-pro.sqlite3')
    for name in ('LEEME-RESTAURAR.md', 'configuracion/variables-entorno.json'):
        if name not in seen:
            bad.append(name)
    env = json.loads(seen.get('configuracion/variables-entorno.json', b'{}') or b'{}')
    with tempfile.TemporaryDirectory(prefix='ordenes-restauracion-') as folder:
        path = Path(folder) / 'restaurada.sqlite3'
        path.write_bytes(db_bytes)
        check = verify(path)
    if extract_to:
        target = Path(extract_to)
        for name, data in seen.items():
            if '..' in Path(name).parts or name.startswith('/'):
                continue
            out = target / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
    gaps = list(manifest.get('faltantes', [])) + ['archivo alterado o ausente: ' + name for name in bad]
    if check['integrity'] != 'ok' or check['foreign_key_errors']:
        gaps.append('la base restaurada no superó la comprobación de integridad')
    return sha, {'tipo': 'completo', 'manifest': manifest, 'db': check, 'env_vars': len(env), 'files_checked': len(manifest['codigo']['lista']),
                 'bad': bad, 'faltantes': gaps, 'completo': manifest.get('completo', False) and not bad and check['integrity'] == 'ok' and not check['foreign_key_errors']}


FUNCTIONAL_CHECK = r'''
import io, json, sys, socket, smtplib, urllib.request, http.client
# Entorno AISLADO: ninguna conexión de red de salida (sin correos, notificaciones ni facturas).
def _blocked(*a, **k):
    raise OSError('Red de salida bloqueada en la restauración de prueba')
socket.create_connection = _blocked
smtplib.SMTP = smtplib.SMTP_SSL = _blocked
urllib.request.urlopen = _blocked
http.client.HTTPConnection.connect = _blocked
sys.path.insert(0, sys.argv[1])
import app
from email.message import Message
out = {}
with app.connect() as c:
    admin = c.execute("SELECT id FROM users WHERE role='administrador' AND active=1 ORDER BY id LIMIT 1").fetchone()
    order = c.execute('SELECT id FROM orders ORDER BY id DESC LIMIT 1').fetchone()
    token = app.make_session(c, admin[0], False, 'restauracion-de-prueba')[0] if admin else ''
    c.commit()
def get(path):
    h = object.__new__(app.Handler); h.path = path; h.client_address = ('127.0.0.1', 1); h.headers = Message()
    h.headers['Cookie'] = 'pcdoctor_session=' + token; h.rfile = io.BytesIO(b''); res = {}
    def reply(status, body, content_type=None, cookie=None, filename=None):
        res.update(status=status, bytes=len(body) if isinstance(body, (bytes, str)) else len(json.dumps(body, default=str)), tipo=(content_type or 'application/json').split(';')[0])
    h.reply = reply
    try:
        h.do_GET()
    except Exception as error:
        res.update(status=599, error=type(error).__name__ + ': ' + str(error)[:120])
    return res
paths = ['/api/me', '/api/orders', '/api/clients', '/api/catalog', '/api/system', '/']
if order:
    paths += ['/api/orders/%d' % order[0], '/api/orders/%d/receipt.pdf' % order[0]]
for p in paths:
    out[p] = get(p)
print(json.dumps({'admin': bool(admin), 'pruebas': out}))
'''


def functional_check(restored_root):
    """Arranca el código RESTAURADO contra la base RESTAURADA (copia aislada, sin credenciales ni red de salida) y prueba las funciones
    principales: sesión, órdenes, clientes, catálogo, sistema, panel, detalle de una orden y su PDF."""
    import subprocess
    import sys
    root = Path(restored_root) / 'codigo'
    var = root / 'local' / 'var'
    var.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(restored_root) / 'base' / 'ordenes-pro.sqlite3', var / 'ordenes.sqlite3')
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'LD_LIBRARY_PATH') if key in os.environ}
    # Las dependencias (argon2, cryptography…) se buscan donde las encuentra este proceso; en Vercel no llegan por PYTHONPATH.
    env['PYTHONPATH'] = os.pathsep.join(p for p in sys.path if p and Path(p).exists())
    env.update({'APP_ENV': 'restauracion-de-prueba', 'PRODUCTION_ENABLED': 'false', 'HTTP_PROXY': 'http://127.0.0.1:9', 'HTTPS_PROXY': 'http://127.0.0.1:9', 'PYTHONDONTWRITEBYTECODE': '1'})
    done = subprocess.run([sys.executable, '-c', FUNCTIONAL_CHECK, str(root / 'local')], capture_output=True, text=True, timeout=180, env=env, cwd=str(root / 'local'))
    try:
        result = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RuntimeError('El sistema restaurado no arrancó: ' + ' '.join((done.stderr or '').split())[-240:])
    failed = [path for path, res in result['pruebas'].items() if res.get('status') != 200]
    result['correcto'] = result['admin'] and not failed
    result['fallidas'] = failed
    return result
