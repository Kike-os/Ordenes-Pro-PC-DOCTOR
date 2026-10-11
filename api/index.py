"""Entrada de Vercel: publica la aplicación WSGI existente sin iniciar un servidor ni migrar la base."""
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'local'))

# Sin valores explícitos, el origen y los QR usan el dominio de producción asignado por Vercel.
production = os.getenv('VERCEL_PROJECT_PRODUCTION_URL', '').strip()
if production:
    os.environ.setdefault('APP_URL', 'https://' + production)
    os.environ.setdefault('PUBLIC_APP_URL', 'https://' + production)

import passenger_wsgi  # noqa: E402


# Único nombre exportado: Vercel también acepta «application» y lo usaría sin este ajuste de ruta.
def app(environ, start_response):
    # Vercel sobrescribe estas cabeceras con la IP real; sin esto todos los límites por IP compartirían la del proxy.
    client = environ.get('HTTP_X_REAL_IP') or environ.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
    if client:
        environ['REMOTE_ADDR'] = client
    # La reescritura de vercel.json sustituye la ruta por /api/index y entrega la original en __path.
    query = parse_qsl(environ.get('QUERY_STRING', ''), keep_blank_values=True)
    routed = [value for key, value in query if key == '__path']
    if routed:
        environ['PATH_INFO'] = '/' + routed[0].lstrip('/')
        environ['QUERY_STRING'] = urlencode([(key, value) for key, value in query if key != '__path'])
    return passenger_wsgi.application(environ, start_response)
