"""Entrada WSGI para Passenger/cPanel, sin iniciar un servidor local."""
import json
import logging
import os
import sys
from email.message import Message
from http import HTTPStatus
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app

app.load_env()
os.environ.setdefault('APP_URL', 'https://ordenes-pro.ecuadorpcdoctor.com')
os.environ.setdefault('SESSION_SECURE', 'true')


class WSGIHandler(app.Handler):
    def reply(self, status, body, content_type='application/json; charset=utf-8', cookie=None):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.response_status = f'{status} {HTTPStatus(status).phrase}'
        self.response_headers = [
            ('Content-Type', content_type), ('Content-Length', str(len(body))),
            ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
            ('Referrer-Policy', 'no-referrer'),
            ('Content-Security-Policy', "default-src 'self'; frame-src 'self' blob: https://challenges.cloudflare.com; script-src 'self' https://challenges.cloudflare.com; style-src 'self'; img-src 'self'; connect-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"),
        ]
        if cookie:
            self.response_headers.append(('Set-Cookie', cookie))
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
    except Exception:
        logging.getLogger(__name__).exception("Error WSGI: %s %s", method, path)
        handler.reply(500, {'error': 'No se pudo completar la operación.'})
    start_response(handler.response_status, handler.response_headers)
    return [b'' if method == 'HEAD' else handler.response_body]
