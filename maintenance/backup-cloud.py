#!/usr/bin/env python
"""Agente de respaldos de Órdenes Pro (equipo de la oficina): copia local verificada + respaldo cifrado en MEGA Cloud.

Uso (desde la raíz del proyecto, con las variables de producción):
    vercel env run -e production -- python maintenance/backup-cloud.py             # respaldo diario: copia local + MEGA (02:00)
    vercel env run -e production -- python maintenance/backup-cloud.py --agente    # servicio: panel, reintentos y pruebas semanales
    vercel env run -e production -- python maintenance/backup-cloud.py --reintentar   # subir ahora los pendientes a MEGA
    vercel env run -e production -- python maintenance/backup-cloud.py --solo-local   # solo la copia local (sin MEGA)
    python maintenance/backup-cloud.py --verify <archivo>                            # prueba de restauración local aislada
    python maintenance/backup-cloud.py --descifrar <archivo.enc> --salida <base.sqlite3>  # recuperar un respaldo de MEGA (con la clave)

MEGAcmd OFICIAL corre en el contenedor «ordenes-mega» (maintenance/mega-agente). La sesión de MEGA se inicia una sola vez en este equipo;
la contraseña nunca pasa por Órdenes Pro. Nunca imprime datos de clientes: solo recuentos.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'local'))
import backup_runner  # noqa: E402
from backup_runner import ECUADOR, backup, decrypt, verify, _summary  # noqa: E402
DEFAULT_DIR = Path.home() / 'Respaldos-OrdenesPro'


def main():
    parser = argparse.ArgumentParser(description='Respaldo de la base de datos central de Órdenes Pro.')
    parser.add_argument('--dir', type=Path, default=Path(os.getenv('ORDENES_BACKUP_DIR', DEFAULT_DIR)))
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--descifrar', type=Path)
    parser.add_argument('--agente', action='store_true')
    parser.add_argument('--reintentar', action='store_true')
    parser.add_argument('--solo-local', action='store_true')
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
    if args.agente:
        backup_runner.serve(args.dir)
        return
    if args.reintentar:
        print(json.dumps(backup_runner.upload_pending(), ensure_ascii=False))
        return
    log = args.dir / 'respaldos.log'
    if not args.solo_local:
        try:
            run = backup_runner.daily(args.dir)
        except BaseException as error:
            args.dir.mkdir(parents=True, exist_ok=True)
            with open(log, 'a', encoding='utf-8') as handle:
                handle.write(datetime.now(ECUADOR).isoformat(timespec='seconds') + ' ERROR ' + type(error).__name__ + ': ' + str(error)[:200] + '\n')
            raise
        with open(log, 'a', encoding='utf-8') as handle:
            handle.write(datetime.now(ECUADOR).isoformat(timespec='seconds') + ' MEGA ' + run['status'] + ' ' + run['file'] + ' ' + str(run.get('bytes', 0)) + ' bytes ' + (run.get('error') or '')[:120] + '\n')
        os.chmod(log, 0o600)
        print(json.dumps({key: run.get(key) for key in ('file', 'status', 'bytes', 'verified', 'error')}, ensure_ascii=False))
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
