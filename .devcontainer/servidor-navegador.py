"""Servidor SOLO para Codespaces abierto en el navegador (puerto 8011).

El servidor local (`app.py serve`) solo acepta peticiones cuyo origen sea 127.0.0.1/localhost. Eso funciona desde
VS Code de escritorio, que reenvía el puerto a tu Windows, pero no desde https://<codespace>-8011.app.github.dev.
Aquí se sirve la misma aplicación WSGI con APP_URL igual a esa dirección privada de Codespaces.
No modifica la aplicación ni relaja la comprobación de origen: solo cambia el origen esperado.
"""
import os
import sys
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

PORT = 8011
name = os.environ.get('CODESPACE_NAME', '').strip()
domain = os.environ.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', '').strip()
if not name or not domain:
    raise SystemExit('Este servidor solo se usa dentro de GitHub Codespaces.')
if os.environ.get('TURSO_DATABASE_URL') or os.environ.get('TURSO_AUTH_TOKEN'):
    raise SystemExit('ALTO: hay variables TURSO_* (base de producción). No se inicia.')

origin = f'https://{name}-{PORT}.{domain}'
os.environ['APP_URL'] = origin
os.environ['PUBLIC_APP_URL'] = origin
os.environ['SESSION_SECURE'] = 'true'

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'local'))
import wsgi_app  # noqa: E402


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


with make_server('127.0.0.1', PORT, wsgi_app.application, server_class=ThreadingWSGIServer) as server:
    print(f'ÓRDENES PRO (navegador): {origin}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
