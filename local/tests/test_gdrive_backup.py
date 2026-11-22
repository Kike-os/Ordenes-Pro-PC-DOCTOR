"""1.5.312 · Respaldos en Google Drive, ejecutados por el servidor. Datos FICTICIOS en una base temporal y un servidor local que imita
SOLO lo que se usa de Google (OAuth 2.0 y Drive v3): nada sale a internet, no se usa ninguna cuenta real.

Cubre: asistente (cliente OAuth con secreto cifrado que nunca se devuelve), conexión OAuth con PKCE y «state» de un solo uso, permiso
mínimo drive.file, carpeta PC-DOCTOR S.A./Órdenes Pro/Respaldos Base de Datos, verificar conexión y espacio, respaldo cifrado con subida
reanudable, comprobación del SHA-256 que calcula Google, nueva descarga y restauración aislada, verificar integridad, restauración de
prueba, archivo alterado en Drive, conservación 30/12/12 con papelera, bloqueo, tarea programada y reintentos (solo si hace falta),
acceso vencido, alertas que se retiran solas, indicador de pendientes de proveedores retirados, permisos y CSRF."""
import base64
import hashlib
import json
import os
import secrets
import threading
import unittest
import urllib.parse
from datetime import timedelta
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import test_app
import app
import backups as bk
import gdrive_backup as gd

try:
    import cryptography  # noqa: F401
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

CLIENT = '123456789012-abcdefghijklmnopqrstuvwxyz012345.apps.googleusercontent.com'
SECRET = 'GOCSPX-secretoFicticioDePrueba123'


class FakeGoogle:
    def __init__(self):
        self.files = {'root': {'id': 'root', 'name': '', 'mimeType': gd.FOLDER_MIME, 'parents': [], 'trashed': False}}
        self.blobs = {}
        self.sessions = {}
        self.refresh_valid = {'rt-1'}
        self.challenge = None
        self.revoked = False
        self.tamper = False
        self.auth_on_media = []
        self.quota = {'limit': str(15 * 1024 ** 3), 'usage': '1000'}
        self.n = 0
        g = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, status, payload=None, headers=None, raw=None):
                body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else b'')
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def body(self):
                return self.rfile.read(int(self.headers.get('Content-Length') or 0))

            def ok(self):
                return (self.headers.get('Authorization') or '').startswith('Bearer at-')

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                if u.path == '/o/oauth2/v2/auth':
                    g.challenge = q.get('code_challenge')
                    g.last_auth = q
                    return self.send(302, headers={'Location': q['redirect_uri'] + '?' + urllib.parse.urlencode({'code': 'codigo-ficticio', 'state': q['state']})})
                if not self.ok():
                    return self.send(401, {'error': {'code': 401, 'status': 'UNAUTHENTICATED'}})
                if u.path == '/drive/v3/about':
                    return self.send(200, {'user': {'emailAddress': 'respaldos@example.invalid', 'displayName': 'Cuenta Ficticia'}, 'storageQuota': g.quota})
                if u.path == '/drive/v3/files':
                    expr = q.get('q', '')
                    parent = expr.split("'")[-2] if "in parents" in expr else None
                    out = [f for f in g.files.values() if f['id'] != 'root' and not f['trashed'] and parent in f['parents']]
                    if 'name=' in expr:
                        name = expr.split("name='")[1].split("' and")[0].replace("\\'", "'")
                        out = [f for f in out if f['name'] == name and f['mimeType'] == gd.FOLDER_MIME]
                    return self.send(200, {'files': [{k: f[k] for k in ('id', 'name') if k in f} | ({'size': str(f['size'])} if 'size' in f else {}) for f in out]})
                if u.path.startswith('/drive/v3/files/'):
                    fid = u.path.split('/')[4]
                    f = g.files.get(fid)
                    if not f:
                        return self.send(404, {'error': {'code': 404, 'status': 'NOT_FOUND'}})
                    if q.get('alt') == 'media':
                        g.auth_on_media.append(self.headers.get('Authorization', '')[:9])
                        return self.send(200, raw=g.blobs[fid])
                    return self.send(200, {'id': fid, 'name': f['name'], 'size': str(f.get('size', 0)), 'sha256Checksum': hashlib.sha256(g.blobs.get(fid, b'')).hexdigest(), 'trashed': f['trashed']})
                return self.send(404, {})

            def do_POST(self):
                u = urllib.parse.urlsplit(self.path)
                data = self.body()
                if u.path == '/token':
                    form = dict(urllib.parse.parse_qsl(data.decode()))
                    if form.get('client_id') != CLIENT or form.get('client_secret') != SECRET:
                        return self.send(401, {'error': 'invalid_client'})
                    if form['grant_type'] == 'authorization_code':
                        good = form.get('code') == 'codigo-ficticio' and base64.urlsafe_b64encode(hashlib.sha256(form.get('code_verifier', '').encode()).digest()).decode().rstrip('=') == g.challenge
                        return self.send(200, {'access_token': 'at-0', 'refresh_token': 'rt-1', 'scope': gd.SCOPE, 'expires_in': 3599}) if good else self.send(400, {'error': 'invalid_grant'})
                    if g.revoked or form.get('refresh_token') not in g.refresh_valid:
                        return self.send(400, {'error': 'invalid_grant', 'error_description': 'Token has been expired or revoked.'})
                    g.n += 1
                    return self.send(200, {'access_token': 'at-%d' % g.n, 'expires_in': 3599, 'scope': gd.SCOPE})
                if not self.ok():
                    return self.send(401, {'error': {'code': 401}})
                if u.path == '/drive/v3/files':
                    meta = json.loads(data)
                    fid = 'f%d' % len(g.files)
                    g.files[fid] = {'id': fid, 'name': meta['name'], 'mimeType': meta['mimeType'], 'parents': meta['parents'], 'trashed': False}
                    return self.send(200, {'id': fid, 'name': meta['name']})
                if u.path == '/upload/drive/v3/files':
                    meta = json.loads(data)
                    if not any(f['id'] == meta['parents'][0] and not f['trashed'] for f in g.files.values()):
                        return self.send(404, {'error': {'code': 404, 'status': 'NOT_FOUND'}})
                    sid = secrets.token_hex(4)
                    g.sessions[sid] = {'meta': meta, 'data': b'', 'total': int(self.headers['X-Upload-Content-Length'])}
                    return self.send(200, headers={'Location': 'http://127.0.0.1:%d/subida/%s' % (g.port, sid)})
                return self.send(404, {})

            def do_PUT(self):
                u = urllib.parse.urlsplit(self.path)
                s = g.sessions[u.path.split('/')[2]]
                s['data'] += self.body()
                if len(s['data']) < s['total']:
                    return self.send(308, headers={'Range': 'bytes=0-%d' % (len(s['data']) - 1)})
                fid = 'f%d' % len(g.files)
                blob = s['data'][:-1] + bytes([s['data'][-1] ^ 1]) if g.tamper else s['data']
                g.files[fid] = {'id': fid, 'name': s['meta']['name'], 'mimeType': 'application/octet-stream', 'parents': s['meta']['parents'], 'trashed': False, 'size': len(blob)}
                g.blobs[fid] = blob
                return self.send(200, {'id': fid, 'name': s['meta']['name'], 'size': str(len(blob)), 'sha256Checksum': hashlib.sha256(blob).hexdigest()})

            def do_PATCH(self):
                if not self.ok():
                    return self.send(401, {})
                fid = urllib.parse.urlsplit(self.path).path.split('/')[4]
                g.files[fid]['trashed'] = json.loads(self.body()).get('trashed', False)
                return self.send(200, {'id': fid})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def folder(self):
        parent = 'root'
        node = None
        for name in gd.FOLDER.split('/'):
            node = next((f for f in self.files.values() if not f['trashed'] and parent in f['parents'] and f['name'] == name), None)
            if not node:
                return None
            parent = node['id']
        return node

    def in_folder(self):
        folder = self.folder()
        return sorted(f['name'] for f in self.files.values() if folder and folder['id'] in f['parents'] and not f['trashed'])

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class GoogleDriveBackupTests(unittest.TestCase):
    Base = test_app.SecurityTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    request, login = Base.request, Base.login

    def setUp(self):
        self.Base.setUp(self)
        self.g = FakeGoogle()
        base = 'http://127.0.0.1:%d' % self.g.port
        self.env2 = patch.dict(os.environ, {'BACKUP_TOKEN_KEY': base64.b64encode(secrets.token_bytes(32)).decode(), 'BACKUP_ENCRYPTION_KEY': base64.b64encode(secrets.token_bytes(32)).decode(),
                                            'GOOGLE_ACCOUNTS_BASE': base, 'GOOGLE_OAUTH_BASE': base, 'GOOGLE_API_BASE': base, 'CRON_SECRET': 'cron-ficticio'})
        self.env2.start()
        for key in ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'VERCEL', 'ONEDRIVE_TOKEN_KEY'):
            os.environ.pop(key, None)
        self.nosleep = patch('time.sleep', lambda *_: None)
        self.nosleep.start()

    def tearDown(self):
        self.nosleep.stop()
        self.env2.stop()
        self.g.stop()
        self.Base.tearDown(self)

    # ---- ayudas ----
    def configure(self, cookie=None, csrf=None, **extra):
        if not cookie:
            cookie, csrf = self.login()
        return cookie, csrf, self.request('/api/backups/google/app', dict({'client_id': CLIENT, 'client_secret': SECRET}, **extra), cookie=cookie, csrf=csrf)

    def connect(self):
        cookie, csrf, r = self.configure()
        self.assertEqual(r['status'], 200, r['body'])
        r = self.request('/api/backups/google/connect', {}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200, r['body'])
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r['body']['url']).query))
        self.g.challenge = query['code_challenge']
        back = self.request('/api/backups/google/callback?' + urllib.parse.urlencode({'state': query['state'], 'code': 'codigo-ficticio'}))
        self.assertEqual(back['status'], 200, back['body'])
        return cookie, csrf, query

    def backup(self, cookie, csrf):
        return self.request('/api/backups/run', {'kind': 'respaldo'}, cookie=cookie, csrf=csrf)

    def state(self, key):
        with app.connect() as c:
            return bk.get_state(c, key)

    def runs(self):
        with app.connect() as c:
            return bk.runs(c)

    def titles(self, moment=None):
        with app.connect() as c:
            return [a['title'] for a in gd.alerts(c, moment)]

    def cron(self, path='/api/cron/backup', secret='cron-ficticio'):
        import io
        h = object.__new__(app.Handler)
        h.path = path
        h.client_address = ('127.0.0.1', 1)
        h.headers = Message()
        h.headers['Authorization'] = 'Bearer ' + secret
        h.rfile = io.BytesIO(b'')
        out = {}
        h.reply = lambda status, body, *a, **k: out.update(status=status, body=body)
        h.do_GET()
        return out

    # ---- asistente y conexión ----
    def test_wizard_stores_the_client_secret_encrypted_and_never_returns_it(self):
        cookie, csrf, r = self.configure(client_id='no-es-un-id', client_secret='x')
        self.assertEqual(r['status'], 400)
        self.assertEqual(set(r['body']['fields']), {'client_id', 'client_secret'})
        cookie, csrf, r = self.configure(cookie, csrf)
        self.assertEqual(r['status'], 200, r['body'])
        with app.connect() as c:
            raw = c.execute("SELECT value FROM system_state WHERE key='gdrive_app'").fetchone()[0]
            self.assertNotIn(SECRET, raw)
            self.assertEqual(gd.app_config(c)['secret'], SECRET)
        panel = self.request('/api/backups', cookie=cookie)['body']
        self.assertNotIn(SECRET, json.dumps(panel))
        self.assertIn('Conecta Google Drive', panel['ready'])
        self.assertFalse(panel['protected'])

    def test_connect_uses_minimal_scope_pkce_offline_access_and_creates_the_folder(self):
        cookie, csrf, query = self.connect()
        self.assertEqual(query['scope'], 'https://www.googleapis.com/auth/drive.file')
        self.assertEqual((query['access_type'], query['prompt'], query['code_challenge_method']), ('offline', 'consent', 'S256'))
        self.assertTrue(query['redirect_uri'].endswith('/api/backups/google/callback'))
        link = self.state('gdrive_link')
        self.assertEqual((link['status'], link['account']), ('vinculado', 'respaldos@example.invalid'))
        self.assertTrue(link['refresh'].startswith('gd1:'))
        self.assertIsNotNone(self.g.folder(), 'crea PC-DOCTOR S.A./Órdenes Pro/Respaldos Base de Datos')
        with app.connect() as c:
            self.assertNotIn('rt-1', c.execute("SELECT value FROM system_state WHERE key='gdrive_link'").fetchone()[0])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action IN ('gdrive_link_started','gdrive_linked')").fetchone()[0], 2)
        again = self.request('/api/backups/google/callback?' + urllib.parse.urlencode({'state': query['state'], 'code': 'codigo-ficticio'}))
        self.assertEqual(again['status'], 400, 'el «state» es de un solo uso')
        panel = self.request('/api/backups', cookie=cookie)['body']
        self.assertNotIn('rt-1', json.dumps(panel))
        self.assertFalse(panel['protected'], 'conectado no es protegido: falta un respaldo verificado')

    def test_google_errors_are_explained_without_saving_anything(self):
        for code, expected in (('access_denied', 'Permitir'), ('redirect_uri_mismatch', 'URI de redirección')):
            page = self.request('/api/backups/google/callback?' + urllib.parse.urlencode({'error': code}))
            self.assertEqual(page['status'], 400)
            self.assertIn(expected, page['body'])
        self.assertIsNone(self.state('gdrive_link'))

    def test_check_connection_and_create_folder_from_the_panel(self):
        cookie, csrf, _ = self.connect()
        self.g.quota = {'limit': str(15 * 1024 ** 3), 'usage': str(2 * 1024 ** 3)}
        r = self.request('/api/backups/google/check', {}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200, r['body'])
        self.assertEqual(r['body']['backups']['link']['quota']['usage'], str(2 * 1024 ** 3))
        folder = self.g.folder()
        self.g.files[folder['id']]['trashed'] = True
        r = self.request('/api/backups/google/folder', {}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200, r['body'])
        self.assertIsNotNone(self.g.folder(), 'vuelve a crear la carpeta')

    def test_only_admins_with_csrf(self):
        cookie, csrf = self.login()
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico1','tec@example.invalid','Técnico ficticio',?,'tecnico',1)", (self.hash,))
            c.commit()
        tc = self.request('/api/login', {'login': 'tecnico1', 'password': 'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        tcsrf = self.request('/api/me', cookie=tc)['body']['user']['csrf']
        self.assertEqual(self.request('/api/backups', cookie=tc)['status'], 403)
        for path in ('/api/backups/google/app', '/api/backups/google/connect', '/api/backups/google/check', '/api/backups/google/folder', '/api/backups/run'):
            self.assertEqual(self.request(path, {}, cookie=tc, csrf=tcsrf)['status'], 403, path)
            self.assertEqual(self.request(path, {}, cookie=cookie, csrf='malo')['status'], 403, path)

    # ---- respaldo real ----
    def test_backup_is_blocked_with_a_clear_reason_until_connected(self):
        cookie, csrf = self.login()
        r = self.backup(cookie, csrf)
        self.assertEqual(r['status'], 409)
        self.assertIn('paso 1', r['body']['error'])
        self.assertEqual(self.runs(), [], 'no registra respaldos que no se hicieron')

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_backup_is_encrypted_uploaded_checked_by_google_sha256_downloaded_and_restored(self):
        cookie, csrf, _ = self.connect()
        r = self.backup(cookie, csrf)
        self.assertEqual(r['status'], 200, r['body'])
        run = r['body']['run']
        self.assertEqual((run['status'], run['verified'], run['destination']), ('correcto', True, 'gdrive'))
        self.assertEqual(run['google_sha256'], run['sha256'], 'Google confirma el mismo SHA-256')
        self.assertIn(run['file'], self.g.in_folder())
        blob = next(self.g.blobs[f['id']] for f in self.g.files.values() if f['name'] == run['file'])
        self.assertTrue(blob.startswith(b'OPRB\x01'))
        self.assertNotIn(b'SQLite format 3', blob)
        self.assertTrue(r['body']['backups']['protected'])
        self.assertEqual(self.state('cloud_backup')['destination'], 'gdrive')
        with app.connect() as c:
            self.assertEqual(gd.alerts(c), [])
            self.assertIsNone(bk.get_state(c, 'backup_lock'))

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_integrity_check_and_test_restore_and_tampered_file(self):
        cookie, csrf, _ = self.connect()
        run = self.backup(cookie, csrf)['body']['run']
        r = self.request('/api/backups/run', {'kind': 'verificacion', 'file': run['file']}, cookie=cookie, csrf=csrf)
        self.assertEqual((r['status'], r['body']['run']['status']), (200, 'correcto'), r['body'])
        self.assertEqual(self.request('/api/backups/run', {'kind': 'restauracion', 'file': run['file']}, cookie=cookie, csrf=csrf)['status'], 400)
        r = self.request('/api/backups/run', {'kind': 'restauracion', 'file': run['file'], 'confirm': 'RESTAURAR'}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['body']['run']['status'], 'correcto')
        fid = next(f['id'] for f in self.g.files.values() if f['name'] == run['file'])
        self.g.blobs[fid] = self.g.blobs[fid][:-1] + b'\x00'
        r = self.request('/api/backups/run', {'kind': 'verificacion', 'file': run['file']}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 502)
        self.assertIn('SHA-256', r['body']['error'])

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_corrupted_upload_detected_by_google_checksum_is_trashed_and_reported(self):
        cookie, csrf, _ = self.connect()
        self.g.tamper = True
        r = self.backup(cookie, csrf)
        self.assertEqual(r['status'], 502)
        self.assertIn('SHA-256', r['body']['error'])
        self.assertEqual(self.g.in_folder(), [], 'el archivo dañado va a la papelera')
        self.assertIn('Falló el último respaldo en Google Drive', self.titles())
        self.assertFalse(r['body']['backups']['protected'])
        self.g.tamper = False
        self.assertEqual(self.backup(cookie, csrf)['status'], 200)
        self.assertNotIn('Falló el último respaldo en Google Drive', self.titles())

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_retention_trashes_extra_backups_and_never_other_files(self):
        cookie, csrf, _ = self.connect()
        folder = self.g.folder()
        start = bk.now() - timedelta(days=500)
        for d in range(500):
            fid = 'v%d' % d
            self.g.files[fid] = {'id': fid, 'name': bk.file_name(start + timedelta(days=d)), 'mimeType': 'application/octet-stream', 'parents': [folder['id']], 'trashed': False, 'size': 1}
            self.g.blobs[fid] = b'x'
        self.g.files['otro'] = {'id': 'otro', 'name': 'notas-personales.docx', 'mimeType': 'x', 'parents': [folder['id']], 'trashed': False, 'size': 1}
        run = self.backup(cookie, csrf)['body']['run']
        names = self.g.in_folder()
        self.assertIn('notas-personales.docx', names)
        self.assertIn(run['file'], names)
        self.assertLessEqual(len([n for n in names if n.endswith(bk.SUFFIX)]), 30 + 12 + 12)
        self.assertTrue(any(f['trashed'] for f in self.g.files.values()), 'lo que sobra queda en la papelera, recuperable')

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_lock_prevents_two_backups_at_once(self):
        cookie, csrf, _ = self.connect()
        with app.connect() as c:
            self.assertTrue(bk.acquire_lock(c, 'otro-proceso'))
        self.assertEqual(self.backup(cookie, csrf)['status'], 409)
        self.assertEqual(self.g.sessions, {})

    # ---- tarea programada, reintentos y alertas ----
    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_schedule_needs_cron_secret_retries_only_when_needed_and_never_claims_without_drive(self):
        self.assertEqual(self.cron(secret='malo')['status'], 404)
        self.assertEqual(self.cron()['status'], 200)
        self.assertEqual(self.state('backup_cron')['status'], 'omitido')
        self.assertEqual(self.runs(), [])
        self.assertIn('Respaldos sin copia en Google Drive', self.titles())
        self.connect()
        self.cron()
        self.assertEqual(self.state('backup_cron')['status'], 'correcto', self.state('backup_cron'))
        self.cron('/api/cron/backup-reintento-1')
        self.assertEqual(self.state('backup_cron')['status'], 'innecesario', 'el reintento no repite si ya está verificado')
        self.assertEqual(len([r for r in self.runs() if r['kind'] == 'respaldo']), 1)
        self.assertEqual(self.titles(), [])

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_revoked_access_marks_connection_expired_with_explanation(self):
        cookie, csrf, _ = self.connect()
        self.assertEqual(self.backup(cookie, csrf)['status'], 200)
        self.g.revoked = True
        r = self.backup(cookie, csrf)
        self.assertEqual(r['status'], 409)
        self.assertEqual(self.state('gdrive_link')['status'], 'vencida')
        self.assertIn('7 días', self.state('gdrive_link')['error'])
        self.assertIn('Conexión con Google Drive vencida', self.titles())

    def test_pending_indicator_ignores_retired_providers_without_changing_records(self):
        with app.connect() as c:
            old = bk.new_run('respaldo', 'programado', 'mega', None, 'ordenes-pro-20261121-220733-diario.sqlite.gz.enc')
            old.update(status='pendiente', error='Sin conexión con MEGA')
            bk.save_run(c, old)
        cookie, csrf = self.login()
        panel = self.request('/api/backups', cookie=cookie)['body']
        shown = next(r for r in panel['runs'] if r['destination'] == 'mega')
        self.assertEqual(shown['status'], 'retirado')
        self.assertIn('copia cifrada sigue en el equipo', shown['error'])
        self.assertEqual(self.runs()[0]['status'], 'pendiente', 'el registro original no se modifica')
        self.assertNotIn('pendientes', ' '.join(self.titles()).lower())

    def test_office_local_copy_is_independent_imports_its_real_log_and_keeps_the_previous_copy(self):
        import tempfile
        from pathlib import Path
        import backup_runner
        with app.connect() as c:
            bk.set_state(c, 'cloud_backup', {'ok': True, 'at': '2026-11-21T16:37:42-05:00', 'bytes': 39665664, 'sha256': '61cf' + '0' * 60, 'clients': 202, 'orders': 23})
            c.commit()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'copias'
            folder.mkdir()
            (folder / 'respaldos.log').write_text('2026-11-19T02:31:35-05:00 OK ordenes-pro-nube-20261119-023135.sqlite3 35131392 bytes clientes=201 ordenes=20 sha256=' + '3e' * 32 + '\n'
                                                  '2026-11-19T02:40:00-05:00 ERROR RuntimeError: fallo ficticio\n', encoding='utf-8')
            with patch.object(backup_runner, '_central', return_value=True):
                result = backup_runner.backup(folder)
            self.assertTrue((folder / result['file']).exists())
            runs = self.runs()
            self.assertIn(result['file'], [r['file'] for r in runs])
            self.assertIn('ordenes-pro-nube-20261119-023135.sqlite3', [r['file'] for r in runs])
            self.assertEqual(len([r for r in runs if r.get('legacy')]), 1, 'la copia anterior de 37,8 MB se conserva')
            self.assertEqual(len([r for r in runs if r.get('file') and r['destination'] == 'equipo']), 2, 'la línea de error no se convierte en respaldo')
            with app.connect() as c:
                self.assertEqual(backup_runner.import_office_log(c, folder / 'respaldos.log'), 0, 'no duplica')
        cookie, csrf = self.login()
        panel = self.request('/api/backups', cookie=cookie)['body']
        self.assertEqual(panel['last_local']['destination'], 'equipo')
        self.assertFalse(panel['protected'], 'una copia local no es «protegido en la nube»')

    # ---- respaldo COMPLETO (1.5.313) ----
    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_full_backup_contains_database_files_code_configuration_and_instructions(self):
        import backup_runner
        cookie, csrf, _ = self.connect()
        with patch.dict(os.environ, {'SMTP_PASSWORD': 'clave-smtp-ficticia', 'MFA_ENCRYPTION_KEY': 'clave-mfa-ficticia'}):
            r = self.backup(cookie, csrf)
        self.assertEqual(r['status'], 200, r['body'])
        run = r['body']['run']
        self.assertEqual(run['status'], 'correcto')
        self.assertTrue(run['complete'] and run['full'])
        self.assertTrue(run['file'].endswith('-completo.tar.gz.enc'))
        self.assertGreater(run['verify']['files_checked'], 1000, 'cada archivo de código se comprueba tras descargarlo')
        blob = next(self.g.blobs[f['id']] for f in self.g.files.values() if f['name'] == run['file'])
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            sha, info = backup_runner.inspect_archive(blob, run['sha256'], extract_to=tmp)
            root = Path(tmp)
            self.assertTrue(info['completo'], info['faltantes'])
            manifest = json.loads((root / 'manifiesto.json').read_text())
            for rel in ('codigo/local/app.py', 'codigo/local/static/app.js', 'codigo/local/static/logo-original.png', 'codigo/vercel.json', 'codigo/requirements.txt',
                        'codigo/maintenance/backup-cloud.py', 'codigo/docs/RESPALDOS-GOOGLE-DRIVE.md', 'codigo/local/data/releases.json', 'base/ordenes-pro.sqlite3', 'LEEME-RESTAURAR.md'):
                self.assertTrue((root / rel).exists(), rel)
            self.assertFalse(any(p.name.endswith('.sqlite3') for p in (root / 'codigo').rglob('*')), 'no mete bases de datos locales en el código')
            env = json.loads((root / 'configuracion' / 'variables-entorno.json').read_text())
            self.assertEqual(env['SMTP_PASSWORD'], 'clave-smtp-ficticia', 'las credenciales viajan, cifradas dentro del archivo')
            self.assertIn('MFA_ENCRYPTION_KEY', env)
            self.assertNotIn('BACKUP_ENCRYPTION_KEY', env, 'la clave de descifrado nunca va dentro de lo que protege')
            self.assertEqual(manifest['clave_huella'], hashlib.sha256(base64.b64decode(os.environ['BACKUP_ENCRYPTION_KEY'])).hexdigest()[:16])
            self.assertEqual(manifest['version'], manifest['version'] and manifest['version'])
            self.assertTrue(manifest['tareas_programadas'], 'incluye las tareas programadas de vercel.json')
            self.assertIn('turso db create', (root / 'LEEME-RESTAURAR.md').read_text())
        self.assertNotIn(b'clave-smtp-ficticia', blob, 'nada de la configuración se lee sin la clave')
        panel = r['body']['backups']
        self.assertTrue(panel['complete'])
        self.assertEqual(panel['last_full']['file'], run['file'])

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_backup_missing_a_part_is_never_called_complete(self):
        import backup_runner
        cookie, csrf, _ = self.connect()
        with patch.object(backup_runner, 'REQUIRED_CODE', backup_runner.REQUIRED_CODE + ('local/archivo-que-falta.py',)):
            r = self.backup(cookie, csrf)
        run = r['body']['run']
        self.assertEqual(run['status'], 'incompleto')
        self.assertIn('archivo-que-falta', run['error'])
        self.assertFalse(r['body']['backups']['complete'])
        self.assertIn('El último respaldo no es completo', self.titles())
        self.assertNotIn('Respaldo de la base central atrasado', self.titles(), 'la base sí quedó respaldada y verificada')

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_isolated_test_restore_starts_the_restored_system_and_checks_main_functions(self):
        cookie, csrf, _ = self.connect()
        run = self.backup(cookie, csrf)['body']['run']
        r = self.request('/api/backups/run', {'kind': 'restauracion', 'file': run['file'], 'confirm': 'RESTAURAR'}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200, r['body'])
        functional = r['body']['run']['verify']['functional']
        self.assertTrue(functional['correcto'], functional)
        for path in ('/api/me', '/api/orders', '/api/clients', '/api/catalog', '/api/system', '/'):
            self.assertEqual(functional['pruebas'][path]['status'], 200, path)
        self.assertEqual(r['body']['backups']['last_restore']['id'], r['body']['run']['id'])
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM sessions WHERE user_agent='restauracion-de-prueba'").fetchone()[0] if 'user_agent' in [x[1] for x in c.execute('PRAGMA table_info(sessions)')] else 0, 0, 'producción no se toca')

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography')
    def test_manual_recovery_extracts_the_full_backup_into_a_new_folder(self):
        import importlib.util
        import tempfile
        from pathlib import Path
        cookie, csrf, _ = self.connect()
        run = self.backup(cookie, csrf)['body']['run']
        blob = next(self.g.blobs[f['id']] for f in self.g.files.values() if f['name'] == run['file'])
        spec = importlib.util.spec_from_file_location('backup_cloud', Path(__file__).resolve().parents[2] / 'maintenance' / 'backup-cloud.py')
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as tmp:
            enc = Path(tmp) / run['file']
            enc.write_bytes(blob)
            out = Path(tmp) / 'restaurado'
            with patch('sys.argv', ['backup-cloud.py', '--descifrar-completo', str(enc), '--salida', str(out)]):
                worker.main()
            self.assertTrue((out / 'base' / 'ordenes-pro.sqlite3').exists())
            self.assertTrue((out / 'codigo' / 'local' / 'app.py').exists())
            with patch('sys.argv', ['backup-cloud.py', '--descifrar-completo', str(enc), '--salida', str(out)]), self.assertRaises(SystemExit):
                worker.main()

    def test_late_alert_clears_only_with_a_verified_backup(self):
        self.assertIn('Respaldo de la base central atrasado', self.titles())
        with app.connect() as c:
            fresh = bk.new_run('respaldo', 'programado', 'equipo')
            fresh.update(status='correcto', verified=True, finished_at=bk.stamp())
            bk.save_run(c, fresh)
        self.assertNotIn('Respaldo de la base central atrasado', self.titles())


if __name__ == '__main__':
    unittest.main()
