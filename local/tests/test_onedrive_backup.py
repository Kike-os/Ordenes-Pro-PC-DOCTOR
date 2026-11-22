"""1.5.309 · Respaldos automáticos en Microsoft OneDrive. Datos FICTICIOS en una base temporal y un servidor local que imita SOLO lo
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
                    if form.get('scope') != od.SCOPES or form.get('client_secret') != 'secreto-ficticio':
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
        self.env2 = patch.dict(os.environ, {'MS_CLIENT_ID': 'cliente-ficticio', 'MS_CLIENT_SECRET': 'secreto-ficticio', 'MS_TENANT_ID': 'inquilino-ficticio',
                                            'ONEDRIVE_TOKEN_KEY': base64.b64encode(secrets.token_bytes(32)).decode(), 'BACKUP_ENCRYPTION_KEY': base64.b64encode(secrets.token_bytes(32)).decode(),
                                            'GRAPH_BASE': base + '/v1.0', 'MS_LOGIN_BASE': base, 'GITHUB_API': base, 'GITHUB_BACKUP_TOKEN': 'gh-ficticio',
                                            'GITHUB_BACKUP_REPO': 'ficticio/ordenes', 'ORDENES_BACKUP_DIR': self.keydir.name})
        self.env2.start()
        self.nosleep = patch('time.sleep', lambda *_: None)
        self.nosleep.start()
        self.worker = load_worker()

    def tearDown(self):
        self.nosleep.stop()
        self.env2.stop()
        self.cloud.stop()
        self.keydir.cleanup()
        self.Base.tearDown(self)

    # ---- ayudas ----
    def link(self):
        cookie, csrf = self.login()
        r = self.request('/api/backups/onedrive/connect', {}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200, r['body'])
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r['body']['url']).query))
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

    # ---- vinculación ----
    def test_link_uses_pkce_single_use_state_and_stores_the_token_encrypted(self):
        cookie, csrf, query = self.link()
        self.assertEqual(query['code_challenge_method'], 'S256')
        self.assertEqual(query['scope'], 'offline_access User.Read Files.ReadWrite')
        self.assertTrue(query['redirect_uri'].endswith('/api/backups/onedrive/callback'))
        link = self.state('onedrive_link')
        self.assertEqual((link['status'], link['account'], link['folder']), ('vinculado', 'respaldos@example.invalid', od.FOLDER))
        self.assertTrue(link['refresh'].startswith('od1:'))
        with app.connect() as c:
            raw = c.execute("SELECT value FROM system_state WHERE key='onedrive_link'").fetchone()[0]
            self.assertNotIn('ref-1', raw)
            self.assertIsNone(od.get_state(c, 'onedrive_oauth'))
            self.assertEqual(od.unseal(link['refresh']), 'ref-1')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action IN ('onedrive_link_started','onedrive_linked')").fetchone()[0], 2)
        self.assertIsNotNone(self.cloud.find(od.FOLDER), 'debe crear PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos')
        # El «state» es de un solo uso y el panel nunca recibe el token.
        again = self.request('/api/backups/onedrive/callback?' + urllib.parse.urlencode({'state': query['state'], 'code': 'codigo-ficticio'}))
        self.assertEqual(again['status'], 400)
        panel = self.request('/api/backups', cookie=cookie)['body']
        self.assertNotIn('refresh', json.dumps(panel))
        self.assertEqual(panel['link']['status'], 'vinculado')

    def test_callback_rejects_forged_or_expired_state_and_escapes_the_message(self):
        cookie, csrf = self.login()
        self.request('/api/backups/onedrive/connect', {}, cookie=cookie, csrf=csrf)
        forged = self.request('/api/backups/onedrive/callback?state=falso&code=x')
        self.assertEqual(forged['status'], 400)
        self.assertIsNone(self.state('onedrive_link'))
        denied = self.request('/api/backups/onedrive/callback?error=%3Cscript%3E')
        self.assertEqual(denied['status'], 400)
        self.assertNotIn('<script>', denied['body'])
        r = self.request('/api/backups/onedrive/connect', {}, cookie=cookie, csrf=csrf)
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r['body']['url']).query))['state']
        with app.connect() as c:
            pending = od.get_state(c, 'onedrive_oauth')
            pending['expires'] = (od.now() - timedelta(minutes=1)).isoformat(timespec='seconds')
            od.set_state(c, 'onedrive_oauth', pending)
            c.commit()
        expired = self.request('/api/backups/onedrive/callback?' + urllib.parse.urlencode({'state': state, 'code': 'codigo-ficticio'}))
        self.assertEqual(expired['status'], 400)
        self.assertIn('10 minutos', expired['body'])

    def test_only_admins_with_csrf_manage_backups(self):
        cookie, csrf = self.login()
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico1','tec@example.invalid','Técnico ficticio',?,'tecnico',1)", (self.hash,))
            c.commit()
        tc = self.request('/api/login', {'login': 'tecnico1', 'password': 'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        tcsrf = self.request('/api/me', cookie=tc)['body']['user']['csrf']
        self.assertEqual(self.request('/api/backups', cookie=tc)['status'], 403)
        for path in ('/api/backups/onedrive/connect', '/api/backups/onedrive/disconnect', '/api/backups/run'):
            self.assertEqual(self.request(path, {}, cookie=tc, csrf=tcsrf)['status'], 403, path)
            self.assertEqual(self.request(path, {}, cookie=cookie, csrf='malo')['status'], 403, path)

    # ---- respaldo completo ----
    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del generador)')
    def test_scheduled_backup_is_encrypted_uploaded_downloaded_and_restored_before_counting_as_valid(self):
        self.link()
        run = self.worker.onedrive_backup()
        self.assertEqual(run['status'], 'correcto', run.get('error'))
        self.assertTrue(run['verified'])
        self.assertEqual(run['verify']['integrity'], 'ok')
        self.assertEqual(run['verify']['foreign_key_errors'], 0)
        self.assertRegex(run['file'], r'^ordenes-pro-\d{8}-\d{6}-(diario|semanal|mensual)\.sqlite\.gz\.enc$')
        stored = self.cloud.find(od.FOLDER + '/' + run['file'])
        blob = self.cloud.blobs[stored['id']]
        self.assertEqual(hashlib.sha256(blob).hexdigest(), run['sha256'])
        self.assertTrue(blob.startswith(b'OPRB\x01'))
        self.assertNotIn(b'SQLite format 3', blob)
        self.assertNotIn(b'\x1f\x8b', blob[:20])
        self.assertEqual(self.cloud.auth_on_download, [None], 'el token no debe viajar a la URL de descarga')
        # Token rotado y guardado cifrado; el estado de salud se actualiza solo con el respaldo verificado.
        self.assertEqual(od.unseal(self.state('onedrive_link')['refresh']), 'ref-2')
        self.assertTrue(self.state('cloud_backup')['ok'])
        with app.connect() as c:
            self.assertEqual(od.alerts(c), [])
            self.assertIsNone(od.get_state(c, 'backup_lock'))
        # Recuperación manual con la clave: nunca sobrescribe un archivo existente.
        with tempfile.TemporaryDirectory() as folder:
            enc = Path(folder) / run['file']
            enc.write_bytes(blob)
            out = Path(folder) / 'recuperada.sqlite3'
            with patch('sys.argv', ['backup-cloud.py', '--descifrar', str(enc), '--salida', str(out)]):
                self.worker.main()
            self.assertTrue(out.exists())
            with patch('sys.argv', ['backup-cloud.py', '--descifrar', str(enc), '--salida', str(out)]), self.assertRaises(SystemExit):
                self.worker.main()

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del generador)')
    def test_panel_requests_verify_and_isolated_restore_and_detects_a_tampered_file(self):
        cookie, csrf, _ = self.link()
        done = self.worker.onedrive_backup()
        # Respaldo pedido desde el panel → GitHub recibe la solicitud con su identificador.
        r = self.request('/api/backups/run', {'kind': 'verificacion', 'file': done['file']}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 202, r['body'])
        self.assertEqual(self.cloud.dispatches[-1]['inputs'], {'modo': 'verificar', 'archivo': done['file'], 'solicitud': r['body']['run']['id']})
        self.assertEqual(self.request('/api/backups/run', {'kind': 'respaldo'}, cookie=cookie, csrf=csrf)['status'], 409, 'no admite dos a la vez')
        checked = self.worker.onedrive_verify('verificacion', done['file'], r['body']['run']['id'])
        self.assertEqual((checked['status'], checked['verified']), ('correcto', True))
        # Restaurar exige escribir RESTAURAR y solo restaura en una base aislada.
        self.assertEqual(self.request('/api/backups/run', {'kind': 'restauracion', 'file': done['file']}, cookie=cookie, csrf=csrf)['status'], 400)
        r = self.request('/api/backups/run', {'kind': 'restauracion', 'file': done['file'], 'confirm': 'RESTAURAR'}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 202, r['body'])
        restored = self.worker.onedrive_verify('restauracion', done['file'], r['body']['run']['id'])
        self.assertEqual(restored['status'], 'correcto')
        # Archivo alterado en OneDrive: la verificación falla y lo dice.
        item = self.cloud.find(od.FOLDER + '/' + done['file'])
        self.cloud.blobs[item['id']] = self.cloud.blobs[item['id']][:-1] + b'\x00'
        with self.assertRaises(RuntimeError):
            self.worker.onedrive_verify('verificacion', done['file'])
        self.assertEqual(self.runs()[0]['status'], 'error')
        self.assertIn('SHA-256', self.runs()[0]['error'])
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action LIKE 'backup_requested_%'").fetchone()[0], 2)

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del generador)')
    def test_retention_keeps_30_daily_12_weekly_12_monthly_and_never_touches_other_files(self):
        self.link()
        token = 'acc-x'
        folder = self.cloud.find(od.FOLDER)
        start = od.now() - timedelta(days=500)
        names = [od.file_name(start + timedelta(days=d)) for d in range(500)]
        for name in names + ['notas-personales.docx', 'ordenes-pro-copia-manual.sqlite']:
            new = 'x%d' % len(self.cloud.items)
            self.cloud.items[new] = {'id': new, 'name': name, 'file': {}, 'parent': folder['id'], 'size': 1}
            self.cloud.blobs[new] = b'x'
        doomed = od.retention(names)
        kept = sorted(set(names) - set(doomed))
        self.assertLessEqual(len(kept), 30 + 12 + 12)
        self.assertGreaterEqual(len(kept), 30)
        self.assertIn(names[-1], kept)
        run = self.worker.onedrive_backup()
        left = {i['name'] for i in self.cloud.items.values() if i.get('parent') == folder['id']}
        self.assertIn('notas-personales.docx', left)
        self.assertIn('ordenes-pro-copia-manual.sqlite', left)
        self.assertIn(run['file'], left)
        self.assertLessEqual(len([n for n in left if n.endswith(od.SUFFIX)]), 30 + 12 + 12)
        del token

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del generador)')
    def test_lock_prevents_simultaneous_runs(self):
        self.link()
        with app.connect() as c:
            self.assertTrue(od.acquire_lock(c, 'otro-proceso'))
            self.assertFalse(od.acquire_lock(c, 'segundo'))
        with self.assertRaises(SystemExit):
            self.worker.onedrive_backup()
        self.assertEqual(self.runs()[0]['status'], 'error')
        self.assertEqual(self.cloud.sessions, {}, 'no debe subir nada')
        with app.connect() as c:
            od.release_lock(c, 'otro-proceso')
            self.assertTrue(od.acquire_lock(c, 'segundo'))

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del generador)')
    def test_revoked_access_marks_connection_expired_and_raises_separate_alerts(self):
        self.link()
        self.assertEqual(self.worker.onedrive_backup()['status'], 'correcto')
        self.cloud.revoked = True
        with self.assertRaises(od.BackupError):
            self.worker.onedrive_backup()
        self.assertEqual(self.state('onedrive_link')['status'], 'vencida')
        with app.connect() as c:
            titles = [a['title'] for a in od.alerts(c)]
        self.assertIn('Falló el último respaldo en OneDrive', titles)
        self.assertIn('Conexión con OneDrive vencida', titles)
        self.assertNotIn('Respaldo de la base central atrasado', titles, 'el último respaldo verificado sigue siendo reciente')
        with app.connect() as c:
            self.assertIsNone(od.get_state(c, 'backup_lock'), 'el bloqueo se libera aunque falle')

    def test_office_copy_still_works_and_is_recorded_as_independent_verified_copy(self):
        import remote_db
        answers = iter([True])  # solo el control inicial del guion ve la base central; la copia usa la base temporal
        with patch.object(remote_db, 'configured', side_effect=lambda: next(answers, False)):
            result = self.worker.backup(Path(self.keydir.name) / 'copias')
        self.assertTrue(result['ok'])
        self.assertTrue((Path(self.keydir.name) / 'copias' / result['file']).exists())
        last = self.runs()[0]
        self.assertEqual((last['destination'], last['status'], last['verified'], last['runner']), ('equipo', 'correcto', True, 'equipo-local'))
        with app.connect() as c:
            self.assertNotIn('Respaldo de la base central atrasado', [a['title'] for a in od.alerts(c)])

    # ---- alertas ----
    def test_late_alert_depends_on_a_verified_backup_and_clears_by_itself(self):
        with app.connect() as c:
            self.assertIn('Respaldo de la base central atrasado', [a['title'] for a in od.alerts(c)])
            old = od.new_run('respaldo', 'programado', 'equipo')
            old.update(status='correcto', verified=True, finished_at=(od.now() - timedelta(hours=40)).isoformat(timespec='seconds'))
            od.save_run(c, old)
            self.assertIn('Respaldo de la base central atrasado', [a['title'] for a in od.alerts(c)])
            unverified = od.new_run('respaldo', 'programado', 'onedrive')
            unverified.update(status='correcto', verified=False, finished_at=od.stamp())
            od.save_run(c, unverified)
            self.assertIn('Respaldo de la base central atrasado', [a['title'] for a in od.alerts(c)], 'un archivo sin verificar no cuenta')
            fresh = od.new_run('respaldo', 'programado', 'equipo')
            fresh.update(status='correcto', verified=True, finished_at=od.stamp())
            od.save_run(c, fresh)
            self.assertNotIn('Respaldo de la base central atrasado', [a['title'] for a in od.alerts(c)])
        cookie, csrf = self.login()
        feed = json.dumps(self.request('/api/notifications', cookie=cookie)['body'], ensure_ascii=False)
        self.assertNotIn('Respaldo de la base central atrasado', feed)

    def test_disconnect_removes_access_but_not_backups(self):
        cookie, csrf, _ = self.link()
        folder = self.cloud.find(od.FOLDER)
        r = self.request('/api/backups/onedrive/disconnect', {}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 200)
        self.assertIsNone(self.state('onedrive_link'))
        self.assertIsNotNone(self.cloud.find(od.FOLDER), 'la carpeta y sus respaldos se quedan en OneDrive')
        self.assertEqual(folder['id'], self.cloud.find(od.FOLDER)['id'])

    def test_schedule_names_and_retention_rules(self):
        moment = od.now().replace(year=2026, month=11, day=22, hour=1, minute=0)
        self.assertEqual(od.next_run(moment).strftime('%Y-%m-%d %H:%M'), '2026-11-22 02:00')
        self.assertEqual(od.next_run(moment.replace(hour=3)).strftime('%Y-%m-%d %H:%M'), '2026-11-23 02:00')
        self.assertEqual(od.tier(moment.replace(day=1)), 'mensual')
        self.assertEqual(od.tier(moment.replace(day=23)), 'semanal')  # lunes
        self.assertEqual(od.retention(['otro.txt', 'ordenes-pro-mal.sqlite.gz.enc']), [])


if __name__ == '__main__':
    unittest.main()
