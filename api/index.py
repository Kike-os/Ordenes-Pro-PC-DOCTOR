"""Entrada de Vercel: publica la aplicación WSGI existente sin iniciar un servidor ni migrar la base."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'local'))

# Sin valores explícitos, el origen y los QR usan el dominio de producción asignado por Vercel.
production = os.getenv('VERCEL_PROJECT_PRODUCTION_URL', '').strip()
if production:
    os.environ.setdefault('APP_URL', 'https://' + production)
    os.environ.setdefault('PUBLIC_APP_URL', 'https://' + production)

from passenger_wsgi import application  # noqa: E402


def app(environ, start_response):
    # Vercel sobrescribe estas cabeceras con la IP real; sin esto todos los límites por IP compartirían la del proxy.
    client = environ.get('HTTP_X_REAL_IP') or environ.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
    if client:
        environ['REMOTE_ADDR'] = client
    return application(environ, start_response)
