#!/usr/bin/env python
"""Copia local verificada de la base de datos central (libSQL/Turso) en el equipo de la oficina, y herramientas de recuperación.

El respaldo diario CIFRADO en Microsoft OneDrive lo hace el servidor (tarea programada de Vercel a las 02:00, motor local/backup_runner.py).
Esta copia de la oficina es independiente de OneDrive: si la nube falla, sigue habiendo una copia local verificada.

Uso (desde la raíz del proyecto, con las variables de producción):
    vercel env run -e production -- python maintenance/backup-cloud.py          # copia local (temporizador ordenes-pro-respaldo, 02:30)
    python maintenance/backup-cloud.py --verify <archivo>                         # prueba de restauración local en un entorno aislado
    python maintenance/backup-cloud.py --descifrar <archivo.enc> --salida <base.sqlite3>  # recuperar un respaldo de OneDrive (con la clave)

Nunca imprime datos de clientes: solo recuentos. Solo lee la base de producción; escribe únicamente el historial de respaldos.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'local'))
from backup_runner import ECUADOR, backup, decrypt, verify, _summary  # noqa: E402
DEFAULT_DIR = Path.home() / 'Respaldos-OrdenesPro'


def main():
    parser = argparse.ArgumentParser(description='Respaldo de la base de datos central de Órdenes Pro.')
    parser.add_argument('--dir', type=Path, default=Path(os.getenv('ORDENES_BACKUP_DIR', DEFAULT_DIR)))
    parser.add_argument('--verify', type=Path)
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
