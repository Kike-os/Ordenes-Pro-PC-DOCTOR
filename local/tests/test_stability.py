"""Indicador de estabilidad de versiones: estados reales a partir de verificaciones registradas, de solo lectura."""
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_app
import app
import stability


class StabilityTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data

    def counts(self, c):
        return {t: c.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in ('orders', 'clients', 'devices', 'order_history', 'appointments', 'users', 'audit')}

    def test_without_checks_the_version_is_not_verified(self):
        with app.connect() as c:
            info = stability.status(c, app.reception_now())
        self.assertEqual((info['state'], info['label'], info['last_check'], info['passed']), ('unverified', 'No verificada', '', 0))

    def test_checks_are_read_only_recorded_and_lead_to_observation_then_stable(self):
        cookie, csrf = self.login()
        self.request('/api/orders', self.order_data({'request_key': 'stability-order-000001'}), cookie=cookie, csrf=csrf)
        now = app.reception_now()
        with patch.dict(app.os.environ, {'MAIL_IMAP_HOST': 'i.example.invalid', 'MAIL_SMTP_HOST': 's.example.invalid', 'MAIL_USERNAME': 'b@example.invalid', 'MAIL_PASSWORD': 'x'}), app.connect() as c:
            before = self.counts(c)
            entry = stability.run(c, now - timedelta(hours=30))
            self.assertEqual(self.counts(c), before)
            self.assertEqual((entry['passed'], entry['total'], entry['critical_failures'], entry['warnings']), (8, 8, [], []))
            self.assertEqual(entry['version'], app.versioning.load()['releases'][0]['version'])
            self.assertEqual(stability.status(c, now)['state'], 'observing')
            stability.run(c, now - timedelta(hours=10))
            info = stability.status(c, now)
            self.assertEqual((info['state'], info['checks_passed']), ('observing', 2))
            stability.run(c, now)
            info = stability.status(c, now)
            self.assertEqual((info['state'], info['label'], info['short'], info['passed'], info['remaining_hours'], info['missing_passes']), ('stable', 'Versión estable', 'Estable', 8, 0.0, 0))

    def test_a_critical_failure_requires_attention_and_blocks_stable(self):
        now = app.reception_now()
        with app.connect() as c:
            for hours in (40, 30):
                stability.run(c, now - timedelta(hours=hours))
            # Una migración pendiente (simulada con una carpeta temporal) es un fallo crítico de la base de datos.
            import shutil,tempfile
            from pathlib import Path
            with tempfile.TemporaryDirectory() as root:
                shutil.copytree(stability.ROOT / 'migrations', Path(root) / 'migrations')
                (Path(root) / 'migrations' / '999_pendiente.sql').write_text('SELECT 1;')
                shutil.copytree(stability.ROOT / 'static', Path(root) / 'static');shutil.copytree(stability.ROOT / 'templates', Path(root) / 'templates')
                with patch.object(stability, 'ROOT', Path(root)):
                    failed = stability.run(c, now - timedelta(hours=2))
            self.assertEqual(failed['critical_failures'], ['Base de datos y migraciones'])
            self.assertEqual(stability.status(c, now)['state'], 'attention')
            stability.run(c, now - timedelta(hours=1))
            # Tras un fallo crítico el seguimiento empieza de nuevo: no basta con las verificaciones correctas anteriores.
            info = stability.status(c, now)
            self.assertEqual((info['state'], info['window_passes'], info['missing_passes'], info['checks_passed']), ('observing', 1, 2, 3))
            self.assertTrue(any(item['critical'] for item in info['incidents']))
            stability.run(c, now + timedelta(hours=12))
            stability.run(c, now + timedelta(hours=22))
            # El nuevo período empezó a las now-1h: con 3 verificaciones correctas, es estable al cumplir 24 h, no antes.
            self.assertEqual(stability.status(c, now + timedelta(hours=22, minutes=59))['state'], 'observing')
            self.assertEqual(stability.status(c, now + timedelta(hours=23))['state'], 'stable')

    def test_missing_mail_is_a_warning_not_a_critical_failure(self):
        with app.connect() as c:
            entry = stability.run(c, app.reception_now())
        self.assertEqual((entry['critical_failures'], entry['warnings']), ([], ['Servicio de correo']))

    def test_a_new_version_starts_a_new_follow_up_and_keeps_the_previous_history(self):
        now = app.reception_now()
        real = stability.versioning.load()
        with app.connect() as c:
            for hours in (30, 20, 2):
                stability.run(c, now - timedelta(hours=hours))
            old = real['releases'][0]['version']
            self.assertEqual(stability.status(c, now)['state'], 'stable')
            newer = dict(real, releases=[dict(real['releases'][0], version='99.0.0')] + real['releases'])
            with patch.object(stability.versioning, 'load', return_value=newer):
                info = stability.status(c, now)
                self.assertEqual((info['version'], info['state'], info['checks_run']), ('99.0.0', 'unverified', 0))
                self.assertEqual(info['previous'][0]['version'], old)
                self.assertTrue(info['previous'][0]['stable'])
                self.assertEqual(info['previous'][0]['runs'], 3)
                stability.run(c, now)
                self.assertEqual(stability.status(c, now)['state'], 'observing')
            self.assertEqual(stability._load(c, 'stability_versions', {})[old]['runs'], 3)

    def test_summary_is_rebuilt_from_runs_recorded_before_this_version_of_the_module(self):
        now = app.reception_now()
        with app.connect() as c:
            stability.run(c, now - timedelta(hours=25))
            c.execute("DELETE FROM system_state WHERE key='stability_versions'")
            info = stability.status(c, now)
            self.assertEqual((info['checks_run'], info['window_passes'], info['missing_passes']), (1, 1, 2))
            # Al publicarse otra versión, la anterior figura en el historial y su resumen queda guardado en la primera verificación.
            real = stability.versioning.load()
            old = real['releases'][0]['version']
            newer = dict(real, releases=[dict(real['releases'][0], version='99.1.0')] + real['releases'])
            with patch.object(stability.versioning, 'load', return_value=newer):
                self.assertEqual([item['version'] for item in stability.status(c, now)['previous']], [old])
                stability.run(c, now)
            self.assertEqual(stability._load(c, 'stability_versions', {})[old]['runs'], 1)

    def test_scheduled_task_is_protected_and_matches_vercel(self):
        import json
        from pathlib import Path
        crons = json.loads((Path(app.ROOT).parent / 'vercel.json').read_text())['crons']
        hours = sorted(int(item['schedule'].split()[1]) for item in crons if item['path'] in ('/api/cron/stability', '/api/cron/stability-night', '/api/cron/reminders'))
        self.assertEqual(tuple(hours), stability.SCHEDULE_UTC)
        self.assertTrue(all(item['schedule'].split()[2:] == ['*', '*', '*'] for item in crons))
        def cron(path, token=''):
            # La plataforma llama con la cabecera Authorization: Bearer <CRON_SECRET>.
            base = test_app.Message
            def headers():
                message = base()
                if token:
                    message['Authorization'] = 'Bearer ' + token
                return message
            with patch.object(test_app, 'Message', headers):
                return self.request(path)
        # Sin CRON_SECRET configurado la tarea no responde (no queda una ruta abierta).
        self.assertEqual(cron('/api/cron/stability')['status'], 404)
        with patch.dict(app.os.environ, {'CRON_SECRET': 'secreto-de-prueba-cron'}):
            self.assertEqual(cron('/api/cron/stability')['status'], 404)
            self.assertEqual(cron('/api/cron/stability', 'otro')['status'], 404)
            ok = cron('/api/cron/stability-night', 'secreto-de-prueba-cron')
            self.assertEqual(ok['status'], 200)
            self.assertEqual(ok['body'], {'ok': True})
        with app.connect() as c:
            runs = stability._load(c, 'stability_runs', [])
            self.assertEqual([entry['source'] for entry in runs], ['programada'])
        self.assertTrue(stability.next_scheduled(app.reception_now()))

    def test_public_endpoint_runs_at_most_every_thirty_minutes(self):
        first = self.request('/api/public/stability')
        self.assertEqual(first['status'], 200)
        self.assertEqual(first['body']['state'], 'observing')
        self.request('/api/public/stability')
        with app.connect() as c:
            runs = stability._load(c, 'stability_runs', [])
            self.assertEqual(len(runs), 1)
            stability._save(c, 'stability_running', {'version': runs[0]['version'], 'since': app.reception_now().isoformat(timespec='seconds')})
            self.assertEqual(stability.status(c, app.reception_now())['state'], 'verifying')
        self.assertNotIn('detail', str(first['body']['tests']))


if __name__ == '__main__':
    unittest.main()
