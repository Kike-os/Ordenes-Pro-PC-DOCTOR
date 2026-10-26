"""Entrada WSGI para Passenger/cPanel, sin iniciar un servidor local.

No debe llamarse passenger_wsgi.py: Setup Python App de cPanel genera ese archivo como cargador
del archivo de inicio y, si coinciden los nombres, lo sobrescribe y se carga a sí mismo.
"""
import json
import re
import logging
import os
import sqlite3
import sys
from email.message import Message
from http import HTTPStatus
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as core

core.load_env()
os.environ.setdefault('APP_URL', 'https://ordenes-pro.ecuadorpcdoctor.com')
os.environ.setdefault('SESSION_SECURE', 'true')


class WSGIHandler(core.Handler):
    def reply(self, status, body, content_type='application/json; charset=utf-8', cookie=None, filename=None):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.response_status = f'{status} {HTTPStatus(status).phrase}'
        policy, self.cache_policy = getattr(self, 'cache_policy', None), None
        self.response_headers = [
            ('Content-Type', content_type), ('Content-Length', str(len(body))),
            ('Cache-Control', policy or 'no-store'), ('X-Content-Type-Options', 'nosniff'),
            ('Referrer-Policy', 'no-referrer'),
            ('Content-Security-Policy', getattr(self,'content_policy',None) or core.DEFAULT_CSP),
        ]
        # Mismo criterio que el servidor local: los documentos de la orden se guardan con su número real.
        if filename:
            self.response_headers.append(('Content-Disposition', core.content_disposition(filename)))
        if cookie:
            # Una cabecera Set-Cookie por cookie (por ejemplo, la sesión y el equipo de confianza en la misma respuesta).
            for value in (cookie if isinstance(cookie, (list, tuple)) else [cookie]):
                self.response_headers.append(('Set-Cookie', value))
        self.response_body = body


def application(environ, start_response):
    handler = object.__new__(WSGIHandler)
    path = environ.get('PATH_INFO', '/')
    query = environ.get('QUERY_STRING', '')
    handler.path = path + ('?' + query if query else '')
    handler.client_address = (environ.get('REMOTE_ADDR', ''), 0)
    handler.headers = Message()
    for key, value in environ.items():
        if key.startswith('HTTP_'):
            handler.headers[key[5:].replace('_', '-')] = value
    for key in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
        if environ.get(key):
            handler.headers[key.replace('_', '-')] = environ[key]
    handler.rfile = environ['wsgi.input']
    method = environ.get('REQUEST_METHOD', 'GET')
    try:
        if method in ('GET', 'HEAD'):
            handler.do_GET()
        elif method == 'POST':
            handler.do_POST()
        else:
            handler.reply(405, {'error': 'Método no permitido.'})
            handler.response_headers.append(('Allow', 'GET, HEAD, POST'))
    except Exception as error:
        logging.getLogger(__name__).exception("Error WSGI: %s %s", method, path)
        # Base de datos momentáneamente inaccesible (ya se reintentó): 503 con Retry-After, como en POST. La consulta no cambió nada y
        # los sondeos periódicos (agenda, notificaciones) vuelven a intentarlo solos; no es un fallo del servidor (500).
        busy = isinstance(error, sqlite3.OperationalError)
        try:
            core.note_runtime_error(method, path, error, status=503 if busy else 500)
        except Exception:
            pass
        if busy:
            handler.reply(503, {'error': 'No se pudo consultar por un problema temporal de base de datos. Intente nuevamente en unos segundos.'})
            handler.response_headers.append(('Retry-After', '5'))
        else:
            handler.reply(500, {'error': 'No se pudo completar la operación.'})
    start_response(handler.response_status, handler.response_headers)
    return [b'' if method == 'HEAD' else handler.response_body]


# Vercel busca una aplicación invocable llamada app; Passenger usa application.
app = application
