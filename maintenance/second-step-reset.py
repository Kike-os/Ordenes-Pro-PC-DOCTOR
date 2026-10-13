#!/usr/bin/env python
"""Retira la verificación en dos pasos de una cuenta cuando su titular perdió el teléfono Y los códigos de recuperación, y no hay
otro administrador que pueda hacerlo desde «Usuarios y accesos».

Uso (desde la raíz del proyecto, con las variables de producción):
    vercel env run -e production -- python maintenance/second-step-reset.py <usuario> --confirmar

Solo quien tiene acceso al servidor puede ejecutarlo. No cambia la contraseña: la cuenta vuelve a entrar con su contraseña y puede
activar de nuevo el segundo paso. Cierra las sesiones abiertas de esa cuenta y deja constancia en la auditoría. No imprime secretos.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'local'))


def main():
    parser = argparse.ArgumentParser(description='Retira la verificación en dos pasos de una cuenta.')
    parser.add_argument('usuario')
    parser.add_argument('--confirmar', action='store_true', help='sin esta opción solo informa, no cambia nada')
    args = parser.parse_args()
    import app, two_factor
    with app.connect() as c:
        row = c.execute('SELECT id,username,name FROM users WHERE username=?', (args.usuario,)).fetchone()
        if not row:
            print('No existe una cuenta con ese usuario.')
            return 1
        if not two_factor.active(c, row['id']):
            print('La cuenta «%s» no tiene activa la verificación en dos pasos.' % row['username'])
            return 0
        if not args.confirmar:
            print('La cuenta «%s» tiene activa la verificación en dos pasos. Repite la orden con --confirmar para retirarla.' % row['username'])
            return 0
        c.execute('BEGIN IMMEDIATE')
        two_factor.remove(c, row['id'])
        c.execute('DELETE FROM sessions WHERE user_id=?', (row['id'],))
        app.audit(c, None, 'second_step_reset_by_maintenance', row['id'])
        c.commit()
        print('Verificación en dos pasos retirada de «%s». Sus sesiones se cerraron.' % row['username'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
