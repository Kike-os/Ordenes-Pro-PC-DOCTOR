"""1.5.311 · Respaldos en MEGA Cloud con el agente del equipo de la oficina. Datos FICTICIOS en una base temporal y un MEGAcmd SIMULADO
(local/tests/fake_megacmd.py): no se contacta con MEGA ni se usa ninguna cuenta real.

Cubre: respaldo completo (copia local + cifrado + subida + descarga de comprobación + SHA-256 + restauración aislada), MEGA sin red o sin
sesión (queda PENDIENTE en disco y se reintenta; nunca se declara respaldado), archivo dañado en la nube, falta de espacio, conservación
30/12/12 sin tocar archivos ajenos, bloqueo, órdenes del panel (respaldo, verificar, restaurar aislado, descargar, espacio, carpeta,
reintentar) con permisos, CSRF y auditoría, enlaces de descarga que caducan, alertas reales que se retiran solas, historial unificado y
recuperación con --descifrar."""
import base64
import json
import os
import secrets
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import test_app
import app
import backups as od

try:
    import cryptography  # noqa: F401
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

ROOT = Path(__file__).resolve().parents[2]
FAKE = Path(__file__).resolve().parent / 'fake_megacmd.py'


class MegaBackupTests(unittest.TestCase):
    Base = test_app.SecurityTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    request, login = Base.request, Base.login

    def setUp(self):
        self.Base.setUp(self)
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.cloud_dir = base / 'mega'
        self.local = base / 'copias'
        self.env2 = patch.dict(os.environ, {'BACKUP_ENCRYPTION_KEY': base64.b64encode(secrets.token_bytes(32)).decode(), 'FAKE_MEGA_DIR': str(self.cloud_dir),
                                            'MEGA_CMD': sys.executable + ' ' + str(FAKE), 'MEGA_EXCHANGE_DIR': str(base / 'intercambio')})
        self.env2.start()
        self.nosleep = patch('time.sleep', lambda *_: None)
        self.nosleep.start()
        import backup_runner
        self.runner = backup_runner
        # La copia exige base central: en las pruebas el control inicial la da por configurada y la copia usa la base temporal.
        self.remote = patch.object(backup_runner, '_central', return_value=True)
        self.remote.start()

    def tearDown(self):
        self.remote.stop()
        self.nosleep.stop()
        self.env2.stop()
        self.tmp.cleanup()
        self.Base.tearDown(self)

    # ---- ayudas ----
    def mode(self, name, on=True):
        self.cloud_dir.mkdir(parents=True, exist_ok=True)
        path = self.cloud_dir / name
        path.write_text('1') if on else path.unlink(missing_ok=True)

    def daily(self):
        return self.runner.daily(self.local)

    def runs(self):
        with app.connect() as c:
            return od.runs(c)

    def state(self, key):
        with app.connect() as c:
            return od.get_state(c, key)

    def remote_files(self):
        folder = self.cloud_dir / 'nube' / od.FOLDER
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []

    def titles(self, moment=None):
        with app.connect() as c:
            return [a['title'] for a in od.alerts(c, moment)]

    # ---- respaldo completo ----
    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del agente)')
    def test_daily_backup_keeps_local_copy_uploads_encrypted_and_verifies_by_download_and_restore(self):
        run = self.daily()
        self.assertEqual((run['status'], run['verified'], run['destination']), ('correcto', True, 'mega'), run.get('error'))
        self.assertEqual(run['verify']['integrity'], 'ok')
        self.assertRegex(run['file'], r'^ordenes-pro-\d{8}-\d{6}-(diario|semanal|mensual)\.sqlite\.gz\.enc$')
        self.assertIn(run['file'], self.remote_files(), 'subido a PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos')
        blob = (self.cloud_dir / 'nube' / od.FOLDER / run['file']).read_bytes()
        self.assertTrue(blob.startswith(b'OPRB\x01'))
        self.assertNotIn(b'SQLite format 3', blob)
        self.assertTrue(list(self.local.glob('ordenes-pro-nube-*.sqlite3')), 'la copia local independiente se conserva')
        self.assertEqual(list((Path(self.tmp.name) / 'intercambio' / 'pendientes').iterdir()), [], 'sin pendientes tras verificar')
        self.assertEqual(self.state('cloud_backup')['destination'], 'mega')
        kinds = {(r['destination'], r['status']) for r in self.runs()}
        self.assertIn(('equipo', 'correcto'), kinds)
        self.assertEqual(self.titles(), [])
        cookie, csrf = self.login()
        panel = self.request('/api/backups', cookie=cookie)['body']
        self.assertEqual(panel['last_mega']['file'], run['file'])
        self.assertEqual(panel['last_local']['destination'], 'equipo')

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del agente)')
    def test_offline_mega_keeps_the_encrypted_backup_pending_and_retries_until_verified(self):
        self.mode('sin-red')
        run = self.daily()
        self.assertEqual(run['status'], 'pendiente')
        self.assertFalse(run['verified'])
        self.assertIn('Sin conexión con MEGA', run['error'])
        self.assertIn('network', run['error'], 'se informa la causa real, no «sin sesión»')
        pending = Path(self.tmp.name) / 'intercambio' / 'pendientes' / run['file']
        self.assertTrue(pending.exists(), 'la copia cifrada queda en disco')
        self.assertTrue(pending.read_bytes().startswith(b'OPRB\x01'))
        cookie, csrf = self.login()
        panel = self.request('/api/backups', cookie=cookie)['body']
        self.assertIsNone(panel['last_mega'], 'nunca se declara respaldado en MEGA sin subir y verificar')
        self.runner.heartbeat()
        later = od.now() + timedelta(hours=3)
        self.assertIn('Respaldos pendientes de subir a MEGA', self.titles(later))
        # Vuelve la conexión: el reintento sube, verifica y retira la alerta.
        self.mode('sin-red', False)
        done = self.runner.upload_pending()
        self.assertEqual(done['uploaded'], 1)
        self.assertFalse(pending.exists())
        self.assertEqual(next(r for r in self.runs() if r['id'] == run['id'])['status'], 'correcto')
        self.runner.heartbeat()
        self.assertNotIn('Respaldos pendientes de subir a MEGA', self.titles(later))

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del agente)')
    def test_without_mega_session_the_backup_waits_and_raises_a_real_alert(self):
        self.mode('sin-sesion')
        run = self.daily()
        self.assertEqual(run['status'], 'pendiente')
        self.assertIn('MEGA desconectado', run['error'])
        state = self.runner.heartbeat()
        self.assertFalse(state['connected'])
        self.assertIn('MEGA desconectado', self.titles())

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del agente)')
    def test_corrupted_upload_is_detected_trashed_and_retried(self):
        self.mode('dañar')
        run = self.daily()
        self.assertEqual(run['status'], 'error')
        self.assertIn('no coincide', run['error'])
        self.assertNotIn(run['file'], self.remote_files(), 'el archivo dañado va a la papelera de MEGA')
        self.assertIn('Falló el último respaldo en MEGA', self.titles())
        self.mode('dañar', False)
        self.assertEqual(self.runner.upload_pending()['uploaded'], 1)
        self.assertIn(run['file'], self.remote_files())
        self.assertNotIn('Falló el último respaldo en MEGA', self.titles())

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del agente)')
    def test_not_enough_space_keeps_it_pending_with_the_reason(self):
        self.mode('lleno')
        run = self.daily()
        self.assertEqual(run['status'], 'pendiente')
        self.assertIn('Espacio insuficiente', run['error'])

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del agente)')
    def test_retention_moves_extra_backups_to_trash_and_never_touches_other_files(self):
        folder = self.cloud_dir / 'nube' / od.FOLDER
        folder.mkdir(parents=True)
        start = od.now() - timedelta(days=500)
        for d in range(500):
            (folder / od.file_name(start + timedelta(days=d))).write_bytes(b'x')
        (folder / 'notas-personales.docx').write_bytes(b'x')
        run = self.daily()
        names = self.remote_files()
        self.assertIn('notas-personales.docx', names)
        self.assertIn(run['file'], names)
        self.assertLessEqual(len([n for n in names if n.endswith(od.SUFFIX)]), 30 + 12 + 12)
        self.assertTrue(list((self.cloud_dir / 'nube' / '_papelera').iterdir()), 'lo que sobra queda en la papelera, recuperable')

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del agente)')
    def test_lock_prevents_two_uploads_at_once(self):
        self.mode('sin-red')
        self.daily()
        self.mode('sin-red', False)
        with app.connect() as c:
            self.assertTrue(od.acquire_lock(c, 'otro-proceso'))
        self.assertTrue(self.runner.upload_pending().get('busy'))
        self.assertEqual(self.remote_files(), [])
        with app.connect() as c:
            od.release_lock(c, 'otro-proceso')

    # ---- panel y órdenes al agente ----
    def test_panel_requests_need_admin_csrf_an_installed_agent_and_are_audited(self):
        cookie, csrf = self.login()
        r = self.request('/api/backups/request', {'action': 'respaldo'}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 409)
        self.assertIn('no está instalado', r['body']['error'])
        self.assertEqual(self.request('/api/backups/request', {'action': 'respaldo'}, cookie=cookie, csrf='malo')['status'], 403)
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico1','tec@example.invalid','Técnico ficticio',?,'tecnico',1)", (self.hash,))
            c.commit()
        tc = self.request('/api/login', {'login': 'tecnico1', 'password': 'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        tcsrf = self.request('/api/me', cookie=tc)['body']['user']['csrf']
        self.assertEqual(self.request('/api/backups', cookie=tc)['status'], 403)
        self.assertEqual(self.request('/api/backups/request', {'action': 'respaldo'}, cookie=tc, csrf=tcsrf)['status'], 403)
        self.runner.heartbeat()
        r = self.request('/api/backups/request', {'action': 'espacio'}, cookie=cookie, csrf=csrf)
        self.assertEqual(r['status'], 202, r['body'])
        self.assertEqual(self.request('/api/backups/request', {'action': 'espacio'}, cookie=cookie, csrf=csrf)['status'], 409, 'sin duplicar órdenes')
        self.assertEqual(self.request('/api/backups/request', {'action': 'restaurar', 'file': 'x'}, cookie=cookie, csrf=csrf)['status'], 400)
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='backup_request_espacio'").fetchone()[0], 1)
        self.assertNotIn('password', json.dumps(self.request('/api/backups', cookie=cookie)['body']).lower())

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del agente)')
    def test_agent_executes_panel_orders_backup_verify_isolated_restore_download_folder_and_space(self):
        cookie, csrf = self.login()
        self.runner.heartbeat()
        for action in ('carpeta', 'espacio'):
            self.assertEqual(self.request('/api/backups/request', {'action': action}, cookie=cookie, csrf=csrf)['status'], 202)
        self.request('/api/backups/request', {'action': 'respaldo'}, cookie=cookie, csrf=csrf)
        self.runner.handle_requests(self.local)
        done = {q['action']: q for q in self.state('backup_requests')}
        self.assertEqual(done['carpeta']['status'], 'hecho')
        self.assertIn('Conectado como respaldos@example.invalid', done['espacio']['result'])
        self.assertEqual(done['respaldo']['status'], 'hecho', done['respaldo'])
        self.assertIn('subido a MEGA y verificado', done['respaldo']['result'])
        file = next(r['file'] for r in self.runs() if r['destination'] == 'mega' and r['status'] == 'correcto')
        for action in ('verificar', 'descargar'):
            self.assertEqual(self.request('/api/backups/request', {'action': action, 'file': file}, cookie=cookie, csrf=csrf)['status'], 202)
        self.assertEqual(self.request('/api/backups/request', {'action': 'restaurar', 'file': file, 'confirm': 'RESTAURAR'}, cookie=cookie, csrf=csrf)['status'], 202)
        self.runner.handle_requests(self.local)
        done = {q['action']: q for q in self.state('backup_requests')}
        self.assertEqual((done['verificar']['status'], done['restaurar']['status'], done['descargar']['status']), ('hecho', 'hecho', 'hecho'), done)
        self.assertIn('restauró aislada', done['restaurar']['result'])
        panel = self.request('/api/backups', cookie=cookie)['body']
        self.assertEqual(panel['downloads'][0]['file'], file)
        self.assertTrue(panel['downloads'][0]['link'].startswith('https://mega.nz/'))
        self.assertTrue((self.cloud_dir / 'enlaces' / file).exists())
        # El enlace caduca a las 24 h: el agente lo retira de MEGA y del panel.
        with app.connect() as c:
            items = od.get_state(c, 'mega_downloads')
            items[0]['expires_at'] = (od.now() - timedelta(minutes=1)).isoformat(timespec='seconds')
            od.set_state(c, 'mega_downloads', items)
            c.commit()
        self.runner.expire_downloads()
        self.assertFalse((self.cloud_dir / 'enlaces' / file).exists())
        self.assertEqual(self.request('/api/backups', cookie=cookie)['body']['downloads'], [])

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del agente)')
    def test_service_cycle_attends_orders_and_reports_state(self):
        cookie, csrf = self.login()
        self.runner.heartbeat()
        self.request('/api/backups/request', {'action': 'espacio'}, cookie=cookie, csrf=csrf)
        self.runner.serve(self.local, cycles=1)
        self.assertEqual(self.state('backup_requests')[0]['status'], 'hecho')
        agent = self.request('/api/backups', cookie=cookie)['body']['agent']
        self.assertTrue(agent['online'])
        self.assertTrue(agent['connected'])
        self.assertEqual(agent['account'], 'respaldos@example.invalid')
        self.assertGreater(agent['space']['total'], 0)

    def test_alerts_for_silent_agent_and_nearly_full_space(self):
        with app.connect() as c:
            od.set_state(c, 'mega_agent', {'seen_at': (od.now() - timedelta(hours=3)).isoformat(timespec='seconds'), 'connected': True, 'space': {'used': 95, 'total': 100}, 'pending': []})
            c.commit()
        titles = self.titles()
        self.assertIn('Agente de respaldos sin señal', titles)
        self.assertIn('Espacio en MEGA casi lleno', titles)

    def test_late_alert_clears_only_with_a_verified_backup(self):
        self.assertIn('Respaldo de la base central atrasado', self.titles())
        with app.connect() as c:
            pending = od.new_run('respaldo', 'programado', 'mega')
            pending.update(status='pendiente', finished_at=od.stamp())
            od.save_run(c, pending)
            self.assertIn('Respaldo de la base central atrasado', [a['title'] for a in od.alerts(c)], 'un pendiente no cuenta')
            fresh = od.new_run('respaldo', 'programado', 'equipo')
            fresh.update(status='correcto', verified=True, finished_at=od.stamp())
            od.save_run(c, fresh)
        self.assertNotIn('Respaldo de la base central atrasado', self.titles())

    def test_history_keeps_the_previous_office_copy_without_inventing(self):
        with app.connect() as c:
            od.set_state(c, 'cloud_backup', {'ok': True, 'at': '2026-11-21T16:37:42-05:00', 'bytes': 39665664, 'sha256': '61cf' + '0' * 60, 'clients': 202, 'orders': 23})
            c.commit()
        cookie, csrf = self.login()
        panel = self.request('/api/backups', cookie=cookie)['body']
        self.assertEqual(panel['runs'][0]['bytes'], 39665664)
        self.assertTrue(panel['runs'][0]['legacy'])
        self.assertEqual(panel['last_local']['bytes'], 39665664)
        self.assertIsNone(panel['last_mega'])
        with app.connect() as c:
            od.keep_legacy(c)
            od.keep_legacy(c)
            self.assertEqual(len([r for r in od.runs(c) if r.get('legacy')]), 1)

    @unittest.skipUnless(HAS_CRYPTO, 'necesita cryptography (entorno del agente)')
    def test_manual_recovery_decrypts_to_a_new_file_and_never_overwrites(self):
        run = self.daily()
        blob = (self.cloud_dir / 'nube' / od.FOLDER / run['file']).read_bytes()
        import importlib.util
        spec = importlib.util.spec_from_file_location('backup_cloud', ROOT / 'maintenance' / 'backup-cloud.py')
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        enc = Path(self.tmp.name) / run['file']
        enc.write_bytes(blob)
        out = Path(self.tmp.name) / 'recuperada.sqlite3'
        with patch('sys.argv', ['backup-cloud.py', '--descifrar', str(enc), '--salida', str(out)]):
            worker.main()
        self.assertTrue(out.exists())
        with patch('sys.argv', ['backup-cloud.py', '--descifrar', str(enc), '--salida', str(out)]), self.assertRaises(SystemExit):
            worker.main()

    def test_schedule_and_retention_rules(self):
        moment = od.now().replace(year=2026, month=11, day=22, hour=1, minute=0)
        self.assertEqual(od.next_run(moment).strftime('%Y-%m-%d %H:%M'), '2026-11-22 02:00')
        self.assertEqual(od.next_run(moment.replace(hour=3)).strftime('%Y-%m-%d %H:%M'), '2026-11-23 02:00')
        self.assertEqual(od.retention(['otro.txt', 'ordenes-pro-mal.sqlite.gz.enc']), [])


if __name__ == '__main__':
    unittest.main()
