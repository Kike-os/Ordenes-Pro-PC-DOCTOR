"""MEGAcmd SIMULADO para las pruebas (no contacta con MEGA). Guarda la «nube» en FAKE_MEGA_DIR y reproduce la salida de los comandos
oficiales que usa el agente. Modos (archivos en FAKE_MEGA_DIR): «sin-red» (todo falla como sin internet), «sin-sesion» (no hay sesión
iniciada), «dañar» (el archivo guardado queda alterado), «lleno» (sin espacio)."""
import os
import shutil
import sys
from pathlib import Path

root = Path(os.environ['FAKE_MEGA_DIR'])
cloud = root / 'nube'
cloud.mkdir(parents=True, exist_ok=True)
cmd, args = sys.argv[1], sys.argv[2:]


def flag(name):
    return (root / name).exists()


def remote(path):
    return cloud / path.strip('/').replace('//bin', '_papelera')


if flag('sin-red') and cmd != 'mega-version':
    print('[API:err] Unable to connect to service: network error', file=sys.stderr)
    sys.exit(9)
if cmd == 'mega-version':
    print('MEGAcmd version: 2.7.1.0: code 2070100 (simulado)')
elif cmd == 'mega-whoami':
    if flag('sin-sesion'):
        print('[err: ] Not logged in.', file=sys.stderr)
        sys.exit(57)
    print('Account e-mail: respaldos@example.invalid')
elif flag('sin-sesion'):
    print('[err: ] Not logged in.', file=sys.stderr)
    sys.exit(57)
elif cmd == 'mega-df':
    used = sum(f.stat().st_size for f in cloud.rglob('*') if f.is_file())
    total = used + 1000 if flag('lleno') else 21474836480
    print('Cloud drive:          %d in    3 file(s) and    3 folder(s)' % used)
    print('-' * 60)
    print('USED STORAGE:          %d                 %.2f%% of %d' % (used, 100.0 * used / total, total))
elif cmd == 'mega-mkdir':
    remote(args[-1]).mkdir(parents=True, exist_ok=True)
elif cmd == 'mega-ls':
    target = remote(args[-1])
    if not target.exists():
        print("[err: ] Couldn't find " + args[-1], file=sys.stderr)
        sys.exit(53)
    for item in sorted(target.iterdir()):
        print(item.name)
elif cmd == 'mega-put':
    local, dest = Path(args[0]), remote(args[1])
    if not dest.exists():
        print('[err: ] Upload failed: folder not found', file=sys.stderr)
        sys.exit(53)
    data = local.read_bytes()
    if flag('dañar'):
        data = data[:-1] + bytes([data[-1] ^ 1])
    (dest / local.name).write_bytes(data)
    print('TRANSFERRING ||################################|| 100.00 %')
elif cmd == 'mega-get':
    source, dest = remote(args[0]), Path(args[1])
    if not source.exists():
        print("[err: ] Couldn't find " + args[0], file=sys.stderr)
        sys.exit(53)
    shutil.copy2(source, dest / source.name)
elif cmd == 'mega-mv':
    source = remote(args[0])
    bin_ = cloud / '_papelera'
    bin_.mkdir(exist_ok=True)
    shutil.move(str(source), str(bin_ / source.name))
elif cmd == 'mega-export':
    if args[0] == '-a':
        exports = root / 'enlaces'
        exports.mkdir(exist_ok=True)
        (exports / Path(args[-1]).name).write_text('1')
        print('Exported ' + args[-1] + ': https://mega.nz/file/FICTICIO#clave-ficticia')
    else:
        (root / 'enlaces' / Path(args[-1]).name).unlink(missing_ok=True)
else:
    print('comando simulado no disponible: ' + cmd, file=sys.stderr)
    sys.exit(2)
