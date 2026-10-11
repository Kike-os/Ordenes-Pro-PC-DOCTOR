#!/usr/bin/env python
"""Respaldo completo y verificado de la base de datos central (libSQL/Turso) en un archivo SQLite independiente.

Uso (desde la raíz del proyecto, con las variables de producción):
    vercel env run -e production -- python maintenance/backup-cloud.py
    python maintenance/backup-cloud.py --verify <archivo>      # prueba de restauración en un entorno aislado

Solo lee la base de producción. Copia esquema y datos a un archivo nuevo fuera del proyecto, comprueba la integridad,
compara el número de filas de cada tabla, calcula su SHA-256, conserva las últimas versiones y anota el resultado.
Nunca imprime datos de clientes: solo recuentos.
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'local'))
DEFAULT_DIR = Path.home() / 'Respaldos-OrdenesPro'
KEEP = 30
ECUADOR = timezone(timedelta(hours=-5))


def digest(path):
    hasher = hashlib.sha256()
    with open(path, 'rb') as handle:
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


def backup(folder):
    import app
    import remote_db
    if not remote_db.configured():
        raise SystemExit('No hay base central configurada (TURSO_DATABASE_URL). Ejecuta con las variables de producción.')
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    stamp = datetime.now(ECUADOR)
    target = folder / ('ordenes-pro-nube-' + stamp.strftime('%Y%m%d-%H%M%S') + '.sqlite3')
    partial = target.with_suffix('.parcial')
    old_mask = os.umask(0o077)
    try:
        with app.connect() as source:
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
        check = verify(partial)
        if check['integrity'] != 'ok' or check['foreign_key_errors'] or check['counts'] != remote:
            raise RuntimeError('La copia no coincide con la base central; no se conserva.')
        partial.rename(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        os.umask(old_mask)
    for old in sorted(folder.glob('ordenes-pro-nube-*.sqlite3'))[:-KEEP]:
        old.unlink()
    result = {'ok': True, 'at': stamp.isoformat(timespec='seconds'), 'file': target.name, 'bytes': target.stat().st_size, 'sha256': digest(target), 'clients': remote.get('clients', 0), 'orders': remote.get('orders', 0), 'tables': len(tables), 'kept': len(list(folder.glob('ordenes-pro-nube-*.sqlite3')))}
    with app.connect() as source:
        # El resultado queda también en la base central para que la aplicación avise si los respaldos se atrasan.
        source.execute("INSERT INTO system_state VALUES ('cloud_backup',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps({key: result[key] for key in ('ok', 'at', 'bytes', 'sha256', 'clients', 'orders')}),))
    return result


def main():
    parser = argparse.ArgumentParser(description='Respaldo de la base de datos central de Órdenes Pro.')
    parser.add_argument('--dir', type=Path, default=Path(os.getenv('ORDENES_BACKUP_DIR', DEFAULT_DIR)))
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    log = args.dir / 'respaldos.log'
    if args.verify:
        print(json.dumps(verify(args.verify), ensure_ascii=False))
        return
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
