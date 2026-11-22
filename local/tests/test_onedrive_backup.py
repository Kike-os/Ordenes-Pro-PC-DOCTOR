"""1.5.309/1.5.310 · Respaldos automáticos en Microsoft OneDrive (asistente en el panel y ejecución en el servidor). Datos FICTICIOS en una base temporal y un servidor local que imita SOLO lo
que se usa de Microsoft (OAuth 2.0 y OneDrive) y de GitHub: nada sale a internet, no se usa ninguna cuenta real.

Cubre: vinculación OAuth con PKCE y «state» de un solo uso (sin sesión en la vuelta), token guardado cifrado y rotado, carpeta
PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos, respaldo cifrado y comprimido, subida por partes sin reemplazar, verificación
por descarga + SHA-256 + restauración aislada, retención 30/12/12 sin tocar archivos ajenos, bloqueo contra ejecuciones simultáneas,
conexión vencida, alertas separadas, permisos y auditoría, y recuperación manual con --descifrar."""
import base64
import hashlib
import importlib.util
import json
import os
import secrets
import tempfile
import threading
import unittest
import urllib.parse
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import test_app
import app
import onedrive_backup as od

try:
    import cryptography  # noqa: F401
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

ROOT = Path(__file__).resolve().parents[2]
SECRET = 'secreto~ficticio~de~prueba~123'
CLIENT = '11111111-2222-3333-4444-555555555555'


def load_worker():
    spec = importlib.util.spec_from_file_location('backup_cloud', ROOT / 'maintenance' / 'backup-cloud.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCloud:
    """Microsoft (login + Graph) y GitHub de mentira en 127.0.0.1."""

    def __init__(self):
        self.items = {'root': {'id': 'root', 'name': '', 'folder': {}, 'parent': None}}
        self.blobs = {}
        self.sessions = {}
        self.dispatches = []
        self.refresh_valid = {'ref-1'}
        self.revoked = False
        self.auth_on_download = []
        self.challenge = None
        self.counter = 1
        cloud = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, status, payload=None, headers=None, raw=None):
                body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else b'')
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                if raw is None and payload is not None:
                    self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def body(self):
                return self.rfile.read(int(self.headers.get('Content-Length') or 0))

            def authorized(self):
                return (self.headers.get('Authorization') or '').startswith('Bearer acc-')

            def do_POST(self):
                path = urllib.parse.urlsplit(self.path).path
                data = self.body()
                if path.endswith('/oauth2/v2.0/token'):
                    form = dict(urllib.parse.parse_qsl(data.decode()))
                    if form.get('scope') != od.SCOPES or form.get('client_secret') != SECRET:
                        return self.send(400, {'error': 'invalid_request'})
                    if form['grant_type'] == 'authorization_code':
                        good = form.get('code') == 'codigo-ficticio' and base64.urlsafe_b64encode(hashlib.sha256(form.get('code_verifier', '').encode()).digest()).decode().rstrip('=') == cloud.challenge
                        if not good:
                            return self.send(400, {'error': 'invalid_grant'})
                        return self.send(200, {'access_token': 'acc-0', 'refresh_token': 'ref-1', 'token_type': 'Bearer'})
                    if cloud.revoked or form.get('refresh_token') not in cloud.refresh_valid:
                        return self.send(400, {'error': 'invalid_grant', 'error_description': 'revocado'})
                    cloud.counter += 1
                    new = 'ref-%d' % cloud.counter
                    cloud.refresh_valid = {new}
                    return self.send(200, {'access_token': 'acc-%d' % cloud.counter, 'refresh_token': new})
                if path.startswith('/repos/') and path.endswith('/dispatches'):
                    if self.headers.get('Authorization') != 'Bearer gh-ficticio':
                        return self.send(401, {})
                    cloud.dispatches.append(json.loads(data))
                    return self.send(204)
                if not self.authorized():
                    return self.send(401, {'error': {'code': 'InvalidAuthenticationToken'}})
                if path.startswith('/v1.0/me/drive/items/') and path.endswith('/children'):
                    parent = path.split('/')[5]
                    info = json.loads(data)
                    if any(i['parent'] == parent and i['name'] == info['name'] for i in cloud.items.values()):
                        return self.send(409, {'error': {'code': 'nameAlreadyExists'}})
                    new = 'f%d' % len(cloud.items)
                    cloud.items[new] = {'id': new, 'name': info['name'], 'folder': {}, 'parent': parent}
                    return self.send(201, cloud.items[new])
                if path.endswith(':/createUploadSession'):
                    target = urllib.parse.unquote(path[len('/v1.0/me/drive/root:/'):-len(':/createUploadSession')])
                    folder, name = target.rsplit('/', 1)
                    parent = cloud.find(folder)
                    if any(i['parent'] == parent['id'] and i['name'] == name for i in cloud.items.values()):
                        return self.send(409, {'error': {'code': 'nameAlreadyExists'}})
                    sid = secrets.token_hex(4)
                    cloud.sessions[sid] = {'parent': parent['id'], 'name': name, 'data': b''}
                    return self.send(200, {'uploadUrl': 'http://127.0.0.1:%d/upload/%s' % (cloud.port, sid)})
                return self.send(404, {})

            def do_PUT(self):
                path = urllib.parse.urlsplit(self.path).path
                data = self.body()
                if path.startswith('/upload/'):
                    if self.headers.get('Authorization'):
                        return self.send(400, {'error': 'la URL de sesión no lleva token'})
                    session = cloud.sessions[path.split('/')[2]]
                    start, rest = self.headers['Content-Range'][6:].split('-')
                    end, total = rest.split('/')
                    assert int(start) == len(session['data'])
                    session['data'] += data
                    if len(session['data']) < int(total):
                        return self.send(202, {'nextExpectedRanges': ['%d-' % len(session['data'])]})
                    new = 'i%d' % len(cloud.items)
                    cloud.items[new] = {'id': new, 'name': session['name'], 'file': {}, 'parent': session['parent'], 'size': len(session['data']), 'createdDateTime': '2026-11-21T07:00:00Z'}
                    cloud.blobs[new] = session['data']
                    return self.send(201, cloud.items[new])
                return self.send(404, {})

            def do_GET(self):
                split = urllib.parse.urlsplit(self.path)
                path = split.path
                if path.endswith('/oauth2/v2.0/authorize'):
                    # Pantalla de Microsoft simulada: la persona «acepta» y vuelve a la aplicación con el código.
                    query = dict(urllib.parse.parse_qsl(split.query))
                    cloud.challenge = query.get('code_challenge')
                    back = query['redirect_uri'] + '?' + urllib.parse.urlencode({'code': 'codigo-ficticio', 'state': query['state']})
                    return self.send(302, headers={'Location': back})
                if path.startswith('/dl/'):
                    cloud.auth_on_download.append(self.headers.get('Authorization'))
                    return self.send(200, raw=cloud.blobs[path[4:]])
                if not self.authorized():
                    return self.send(401, {'error': {'code': 'InvalidAuthenticationToken'}})
                if path == '/v1.0/me':
                    return self.send(200, {'displayName': 'Cuenta Ficticia', 'mail': 'respaldos@example.invalid'})
                if path.startswith('/v1.0/me/drive/root:/') and path.endswith(':/children'):
                    folder = cloud.find(urllib.parse.unquote(path[len('/v1.0/me/drive/root:/'):-len(':/children')]))
                    return self.send(200, {'value': [dict(i) for i in cloud.items.values() if i['parent'] == folder['id']]})
                if path.startswith('/v1.0/me/drive/root:/'):
                    found = cloud.find(urllib.parse.unquote(path[len('/v1.0/me/drive/root:/'):]))
                    return self.send(200, found) if found else self.send(404, {'error': {'code': 'itemNotFound'}})
                if path.startswith('/v1.0/me/drive/items/') and path.endswith('/content'):
                    item_id = path.split('/')[5]
                    return self.send(302, headers={'Location': 'http://127.0.0.1:%d/dl/%s' % (cloud.port, item_id)})
                return self.send(404, {})

            def do_DELETE(self):
                if not self.authorized():
                    return self.send(401, {})
                item_id = urllib.parse.urlsplit(self.path).path.split('/')[5]
                cloud.items.pop(item_id, None)
                cloud.blobs.pop(item_id, None)
                return self.send(204)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def find(self, path):
        parent = 'root'
        node = None
        for name in path.strip('/').split('/'):
            node = next((i for i in self.items.values() if i['parent'] == parent and i['name'] == name), None)
            if not node:
                return None
            parent = node['id']
        return node

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class OneDriveBackupTests(unittest.TestCase):
    Base = test_app.SecurityTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    request, login = Base.request, Base.login

    def setUp(self):
        self.Base.setUp(self)
        self.cloud = FakeCloud()
        base = 'http://127.0.0.1:%d' % self.cloud.port
        self.keydir = tempfile.TemporaryDirectory()
        clean = {k: '' for k in ('MS_CLIENT_ID', 'MS_CLIENT_SECRET', 'MS_TENANT_ID', 'VERCEL')}
        self.env2 = patch.dict(os.environ, dict(clean, ONEDRIVE_TOKEN_KEY=base64.b64encode(secrets.token_bytes(32)).decode(),
                                                BACKUP_ENCRYPTION_KEY=base64.b64encode(secrets.token_bytes(32)).decode(), GRAPH_BASE=base + '/v1.0',
                                                MS_LOGIN_BASE=base, ORDENES_BACKUP_DIR=self.keydir.name, CRON_SECRET='cron-ficticio'))
        self.env2.start()
        for key in ('MS_CLIENT_ID', 'MS_CLIENT_SECRET', 'MS_TENANT_ID', 'VERCEL'):
            os.environ.pop(key, None)
        self.nosleep = patch('time.sleep', lambda *_: None)
        self.nosleep.start()
        self.worker = load_worker()
        import backup_runner
        self.runner = backup_runner

    def tearDown(self):
        self.nosleep.stop()
        self.env2.stop()
        self.cloud.stop()
        self.keydir.cleanup()
        self.Base.tearDown(self)

    # ---- ayudas ----
    def configure(self, kind='personal', cookie=None, csrf=None, **extra):
        if not cookie:
            cookie, csrf = self.login()
        body = dict({'client_id': CLIENT, 'account_type': kind, 'client_secret': SECRET}, **extra)
        r = self.request('/api/backups/onedrive/app', body, cookie=cookie, csrf=csrf)
        return cookie, csrf, r

    def link(self, kind='personal'):
        cookie, csrf, r = self.configure(kind)
        self.assertEqual(r['status'], 200, r['body'])
        r = self.request('/api/backups/onedrive/connect', {}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200, r['body'])
        url = urllib.parse.urlsplit(r['body']['url'])
        query = dict(urllib.parse.parse_qsl(url.query))
        query['_tenant'] = url.path.split('/')[1]
        self.cloud.challenge = query['code_challenge']
        back = self.request('/api/backups/onedrive/callback?' + urllib.parse.urlencode({'state': query['state'], 'code': 'codigo-ficticio'}))
        self.assertEqual(back['status'], 200, back['body'])
        return cookie, csrf, query

    def state(self, key):
        with app.connect() as c:
            return od.get_state(c, key)

    def runs(self):
        with app.connect() as c:
            return od.runs(c)

    def _cron(self, secret):
        """Llamada GET a /api/cron/backup con la cabecera Authorization que envía la plataforma."""
        import io
        from email.message import Message
        handler = object.__new__(app.Handler)
        handler.path = '/api/cron/backup'
        handler.client_address = ('127.0.0.1', 1)
        handler.headers = Message()
        handler.headers['Authorization'] = 'Bearer ' + secret
        handler.rfile = io.BytesIO(b'')
        out = {}
        handler.reply = lambda status, body, *a, **k: out.update(status=status, body=body)
        handler.do_GET()
        return out

    # ---- asistente (paso 1) ----
    def test_wizard_validates_and_stores_the_app_secret_encrypted_without_returning_it(self):
        cookie, csrf, r = self.configure('personal', client_id='no-es-un-guid', client_secret='corto')
        self.assertEqual(r['status'], 400)
        self.assertIn('client_id', r['body']['fields'])
        self.assertIn('client_secret', r['body']['fields'])
        cookie, csrf, r = self.configure('empresa', cookie, csrf)
        self.assertEqual(r['status'], 400)
        self.assertIn('tenant_id', r['body']['fields'])
        cookie, csrf, r = self.configure('personal', cookie, csrf)
        self.assertEqual(r['status'], 200, r['body'])
        saved = self.state('onedrive_app')
        self.assertEqual((saved['client_id'], saved['tenant'], saved['account_type']), (CLIENT, 'consumers', 'personal'))
        self.assertTrue(saved['secret'].startswith('od1:'))
        with app.connect() as c:
            self.assertNotIn(SECRET, c.execute("SELECT value FROM system_state WHERE key='onedrive_app'").fetchone()[0])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='onedrive_app_saved'").fetchone()[0], 1)
        panel = self.request('/api/backups', cookie=cookie)['body']
        self.assertNotIn(SECRET, json.dumps(panel))
        self.assertEqual(panel['app']['source'], 'panel')
        self.assertTrue(panel['app']['has_secret'])
        self.assertIn('Conecta Microsoft OneDrive', panel['ready'])
        # Dejar el secreto en blanco conserva el anterior; el de empresa exige su directorio.
        r = self.request('/api/backups/onedrive/app', {'client_id': CLIENT, 'account_type': 'empresa', 'tenant_id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', 'client_secret': ''}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200, r['body'])
        self.assertEqual(self.state('onedrive_app')['tenant'], 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
        with app.connect() as c:
            self.assertEqual(od.app_config(c)['secret'], SECRET)

    def test_server_variables_take_precedence_over_the_wizard(self):
        with patch.dict(os.environ, {'MS_CLIENT_ID': CLIENT, 'MS_CLIENT_SECRET': SECRET, 'MS_TENANT_ID': 'consumers'}):
            cookie, csrf, r = self.configure('personal')
            self.assertEqual(r['status'], 409)
            with app.connect() as c:
                self.assertEqual(od.app_config(c)['source'], 'servidor')

    def test_changing_the_app_requires_connecting_again(self):
        cookie, csrf, _ = self.link()
        self.assertIsNotNone(self.state('onedrive_link'))
        r = self.request('/api/backups/onedrive/app', {'client_id': '99999999-2222-3333-4444-555555555555', 'account_type': 'personal', 'client_secret': ''}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200)
        self.assertIsNone(self.state('onedrive_link'))

    # ---- conexión (paso 2) ----
    def test_personal_account_link_uses_consumers_pkce_and_stores_the_token_encrypted(self):
        cookie, csrf, query = self.link('personal')
        self.assertEqual(query['_tenant'], 'consumers')
        self.assertEqual(query['client_id'], CLIENT)
        self.assertEqual(query['code_challenge_method'], 'S256')
        self.assertEqual(query['scope'], 'offline_access User.Read Files.ReadWrite')
        link = self.state('onedrive_link')
        self.assertEqual((link['status'], link['account'], link['folder']), ('vinculado', 'respaldos@example.invalid', od.FOLDER))
        with app.connect() as c:
            raw = c.execute("SELECT value FROM system_state WHERE key='onedrive_link'").fetchone()[0]
            self.assertNotIn('ref-1', raw)
            self.assertEqual(od.unseal(link['refresh']), 'ref-1')
        self.assertIsNotNone(self.cloud.find(od.FOLDER), 'crea PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos')
        again = self.request('/api/backups/onedrive/callback?' + urllib.parse.urlencode({'state': query['state'], 'code': 'codigo-ficticio'}))
        self.assertEqual(again['status'], 400)
        self.assertNotIn('refresh', json.dumps(self.request('/api/backups', cookie=cookie)['body']))

    def test_connect_requires_step_one_and_microsoft_errors_are_explained(self):
        cookie, csrf = self.login()
        r = self.request('/api/backups/onedrive/connect', {}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 409)
        self.assertIn('paso 1', r['body']['error'])
        for code, expected in (('unauthorized_client', 'tipo de cuenta'), ('access_denied', 'Aceptar'), ('invalid_client', 'secreto')):
            page = self.request('/api/backups/onedrive/callback?' + urllib.parse.urlencode({'error': code, 'error_description': 'AADSTS ficticio <b>'}))
            self.assertEqual(page['status'], 400)
            self.assertIn(expected, page['body'])
            self.assertNotIn('<b>', page['body'])
        page = self.request('/api/backups/onedrive/callback?' + urllib.parse.urlencode({'error': 'invalid_request', 'error_description': 'AADSTS50020: User account from live.com'}))
        self.assertIn('Personal o Familiar', page['body'])

    def test_only_admins_with_csrf_manage_backups(self):
        cookie, csrf = self.login()
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico1','tec@example.invalid','Técnico ficticio',?,'tecnico',1)", (self.hash,))
            c.commit()
        tc = self.request('/api/login', {'login': 'tecnico1', 'password': 'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        tcsrf = self.request('/api/me', cookie=tc)['body']['user']['csrf']
        self.assertEqual(self.request('/api/backups', cookie=tc)['status'], 403)
        for path in ('/api/backups/onedrive/connect', '/api/backups/onedrive/disconnect', '/api/backups/run', '/api/backups/onedrive/app'):
            self.assertEqual(self.request(path, {}, cookie=tc, csrf=tcsrf)['status'], 403, path)
            self.assertEqual(self.request(path, {}, cookie=cookie, csrf='malo')['status'], 403, path)

    # ---- respaldo en el servidor (paso 3) ----
    def test_manual_backup_is_blocked_with_a_clear_reason_until_everything_is_ready(self):
        cookie, csrf = self.login()
        r = self.request('/api/backups/run', {'kind': 'respaldo'}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 409)
        self.assertIn('paso 1', r['body']['error'])
        self.configure('personal', cookie, csrf)
        r = self.request('/api/backups/run', {'kind': 'respaldo'}, cookie=cookie, csrf=csrf)
        self.assertIn('paso 2', r['body']['error'])
        self.assertEqual(self.runs(), [], 'no registra respaldos que no se hicieron')

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_server_backup_is_encrypted_uploaded_downloaded_and_restored_before_counting_as_valid(self):
        cookie, csrf, _ = self.link()
        r = self.request('/api/backups/run', {'kind': 'respaldo'}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200, r['body'])
        run = r['body']['run']
        self.assertEqual((run['status'], run['verified'], run['trigger']), ('correcto', True, 'manual'))
        self.assertEqual(run['verify']['integrity'], 'ok')
        self.assertRegex(run['file'], r'^ordenes-pro-\d{8}-\d{6}-(diario|semanal|mensual)\.sqlite\.gz\.enc$')
        blob = self.cloud.blobs[self.cloud.find(od.FOLDER + '/' + run['file'])['id']]
        self.assertEqual(hashlib.sha256(blob).hexdigest(), run['sha256'])
        self.assertTrue(blob.startswith(b'OPRB\x01'))
        self.assertNotIn(b'SQLite format 3', blob)
        self.assertEqual(self.cloud.auth_on_download, [None], 'el token no viaja a la URL de descarga')
        self.assertEqual(od.unseal(self.state('onedrive_link')['refresh']), 'ref-2')
        panel = r['body']['backups']
        self.assertEqual(panel['last_onedrive']['file'], run['file'])
        # La copia anterior de la oficina sigue en el historial aunque el resumen se actualice.
        with app.connect() as c:
            self.assertEqual(od.alerts(c), [])
            self.assertIsNone(od.get_state(c, 'backup_lock'))
        # Recuperación manual con la clave: nunca sobrescribe.
        with tempfile.TemporaryDirectory() as folder:
            enc = Path(folder) / run['file']
            enc.write_bytes(blob)
            out = Path(folder) / 'recuperada.sqlite3'
            with patch('sys.argv', ['backup-cloud.py', '--descifrar', str(enc), '--salida', str(out)]):
                self.worker.main()
            self.assertTrue(out.exists())
            with patch('sys.argv', ['backup-cloud.py', '--descifrar', str(enc), '--salida', str(out)]), self.assertRaises(SystemExit):
                self.worker.main()

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_scheduled_task_needs_cron_secret_and_never_claims_a_cloud_backup_without_onedrive(self):
        self.assertEqual(self._cron('malo')['status'], 404)
        out = self._cron('cron-ficticio')
        self.assertEqual(out['status'], 200)
        cron = self.state('backup_cron')
        self.assertEqual(cron['status'], 'omitido')
        self.assertIn('paso 1', cron['detail'])
        self.assertEqual(self.runs(), [])
        with app.connect() as c:
            self.assertIn('Respaldo de la base central atrasado', [a['title'] for a in od.alerts(c)])
        self.link()
        self._cron('cron-ficticio')
        cron = self.state('backup_cron')
        self.assertEqual(cron['status'], 'correcto', cron)
        last = self.runs()[0]
        self.assertEqual((last['trigger'], last['destination'], last['verified']), ('programado', 'onedrive', True))
        with app.connect() as c:
            self.assertEqual(od.alerts(c), [])

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_without_encryption_key_the_backup_explains_what_is_missing(self):
        cookie, csrf, _ = self.link()
        os.environ.pop('BACKUP_ENCRYPTION_KEY')
        r = self.request('/api/backups/run', {'kind': 'respaldo'}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 409)
        self.assertIn('BACKUP_ENCRYPTION_KEY', r['body']['error'])

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_verify_and_isolated_restore_from_the_panel_and_tamper_detection(self):
        cookie, csrf, _ = self.link()
        done = self.request('/api/backups/run', {'kind': 'respaldo'}, cookie=cookie, csrf=csrf)['body']['run']
        r = self.request('/api/backups/run', {'kind': 'verificacion', 'file': done['file']}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200, r['body'])
        self.assertEqual((r['body']['run']['status'], r['body']['run']['verified']), ('correcto', True))
        self.assertEqual(self.request('/api/backups/run', {'kind': 'restauracion', 'file': done['file']}, cookie=cookie, csrf=csrf)['status'], 400)
        r = self.request('/api/backups/run', {'kind': 'restauracion', 'file': done['file'], 'confirm': 'RESTAURAR'}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['body']['run']['status'], 'correcto')
        item = self.cloud.find(od.FOLDER + '/' + done['file'])
        self.cloud.blobs[item['id']] = self.cloud.blobs[item['id']][:-1] + b'\x00'
        r = self.request('/api/backups/run', {'kind': 'verificacion', 'file': done['file']}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 502)
        self.assertIn('SHA-256', r['body']['error'])
        self.assertEqual(self.runs()[0]['status'], 'error')

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_retention_keeps_30_daily_12_weekly_12_monthly_and_never_touches_other_files(self):
        self.link()
        folder = self.cloud.find(od.FOLDER)
        start = od.now() - timedelta(days=500)
        names = [od.file_name(start + timedelta(days=d)) for d in range(500)]
        for name in names + ['notas-personales.docx', 'ordenes-pro-copia-manual.sqlite']:
            new = 'x%d' % len(self.cloud.items)
            self.cloud.items[new] = {'id': new, 'name': name, 'file': {}, 'parent': folder['id'], 'size': 1}
            self.cloud.blobs[new] = b'x'
        kept = sorted(set(names) - set(od.retention(names)))
        self.assertLessEqual(len(kept), 30 + 12 + 12)
        self.assertIn(names[-1], kept)
        run = self.runner.onedrive_backup('programado')
        left = {i['name'] for i in self.cloud.items.values() if i.get('parent') == folder['id']}
        self.assertIn('notas-personales.docx', left)
        self.assertIn('ordenes-pro-copia-manual.sqlite', left)
        self.assertIn(run['file'], left)
        self.assertLessEqual(len([n for n in left if n.endswith(od.SUFFIX)]), 30 + 12 + 12)

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_lock_prevents_simultaneous_runs(self):
        cookie, csrf, _ = self.link()
        with app.connect() as c:
            self.assertTrue(od.acquire_lock(c, 'otro-proceso'))
        r = self.request('/api/backups/run', {'kind': 'respaldo'}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 409)
        self.assertEqual(self.cloud.sessions, {}, 'no sube nada')
        with app.connect() as c:
            od.release_lock(c, 'otro-proceso')

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_revoked_access_marks_connection_expired_and_raises_separate_alerts(self):
        self.link()
        self.assertEqual(self.runner.onedrive_backup('programado')['status'], 'correcto')
        self.cloud.revoked = True
        with self.assertRaises(od.BackupError):
            self.runner.onedrive_backup('programado')
        self.assertEqual(self.state('onedrive_link')['status'], 'vencida')
        with app.connect() as c:
            titles = [a['title'] for a in od.alerts(c)]
            self.assertIn('venció', od.not_ready(c))
        self.assertIn('Falló el último respaldo en OneDrive', titles)
        self.assertIn('Conexión con OneDrive vencida', titles)
        self.assertNotIn('Respaldo de la base central atrasado', titles)
        self.assertIsNone(self.state('backup_lock'))

    # ---- historial unificado y copia de la oficina ----
    def test_office_copy_imports_its_real_log_and_old_summary_appears_without_inventing(self):
        with app.connect() as c:
            od.set_state(c, 'cloud_backup', {'ok': True, 'at': '2026-11-21T16:37:42-05:00', 'bytes': 39665664, 'sha256': '61cf' + '0' * 60, 'clients': 202, 'orders': 23})
            c.commit()
        cookie, csrf = self.login()
        panel = self.request('/api/backups', cookie=cookie)['body']
        self.assertEqual(len(panel['runs']), 1)
        legacy = panel['runs'][0]
        self.assertEqual((legacy['destination'], legacy['bytes'], legacy['legacy']), ('equipo', 39665664, True))
        self.assertIsNone(panel['last_onedrive'], 'la copia de la oficina no cuenta como respaldo en la nube')
        self.assertEqual(panel['office']['bytes'], 39665664)
        with app.connect() as c:
            od.keep_legacy(c)
            od.keep_legacy(c)
            self.assertEqual(len([r for r in od.runs(c) if r.get('legacy')]), 1, 'se conserva una sola vez')
        # Copia local nueva: importa las líneas reales de su registro sin duplicar.
        folder = Path(self.keydir.name) / 'copias'
        folder.mkdir()
        (folder / 'respaldos.log').write_text('2026-11-19T02:31:35-05:00 OK ordenes-pro-nube-20261119-023135.sqlite3 35131392 bytes clientes=201 ordenes=20 sha256=' + '3e' * 32 + '\n'
                                              '2026-11-19T02:40:00-05:00 ERROR RuntimeError: fallo ficticio\n', encoding='utf-8')
        import remote_db
        answers = iter([True])
        with patch.object(remote_db, 'configured', side_effect=lambda: next(answers, False)):
            result = self.runner.backup(folder)
        files = [item['file'] for item in self.runs()]
        self.assertIn(result['file'], files)
        self.assertIn('ordenes-pro-nube-20261119-023135.sqlite3', files)
        self.assertEqual(len([f for f in files if f]), 2, 'la línea de error no se convierte en respaldo')
        self.assertEqual(len([r for r in self.runs() if r.get('legacy')]), 1, 'la copia anterior (37,8 MB) se conserva')
        with app.connect() as c:
            self.assertEqual(self.runner.import_office_log(c, folder / 'respaldos.log'), 0, 'no duplica')

    def test_late_alert_depends_on_a_verified_backup_and_clears_by_itself(self):
        with app.connect() as c:
            self.assertIn('Respaldo de la base central atrasado', [a['title'] for a in od.alerts(c)])
            unverified = od.new_run('respaldo', 'programado', 'onedrive')
            unverified.update(status='correcto', verified=False, finished_at=od.stamp())
            od.save_run(c, unverified)
            self.assertIn('Respaldo de la base central atrasado', [a['title'] for a in od.alerts(c)])
            fresh = od.new_run('respaldo', 'programado', 'equipo')
            fresh.update(status='correcto', verified=True, finished_at=od.stamp())
            od.save_run(c, fresh)
            self.assertNotIn('Respaldo de la base central atrasado', [a['title'] for a in od.alerts(c)])

    def test_disconnect_removes_access_but_not_backups(self):
        cookie, csrf, _ = self.link()
        r = self.request('/api/backups/onedrive/disconnect', {}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200)
        self.assertIsNone(self.state('onedrive_link'))
        self.assertIsNotNone(self.state('onedrive_app'), 'los datos de la aplicación se conservan')
        self.assertIsNotNone(self.cloud.find(od.FOLDER))

    def test_schedule_names_and_retention_rules(self):
        moment = od.now().replace(year=2026, month=11, day=22, hour=1, minute=0)
        self.assertEqual(od.next_run(moment).strftime('%Y-%m-%d %H:%M'), '2026-11-22 02:00')
        self.assertEqual(od.next_run(moment.replace(hour=3)).strftime('%Y-%m-%d %H:%M'), '2026-11-23 02:00')
        self.assertEqual(od.tier(moment.replace(day=1)), 'mensual')
        self.assertEqual(od.tier(moment.replace(day=23)), 'semanal')
        self.assertEqual(od.retention(['otro.txt', 'ordenes-pro-mal.sqlite.gz.enc']), [])


if __name__ == '__main__':
    unittest.main()
