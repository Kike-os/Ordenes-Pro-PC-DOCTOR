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
            self.assertEqual((info['state'], info['label'], info['passed']), ('stable', 'Estable', 8))

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
            stability.run(c, now)
            # Tras un fallo crítico la versión vuelve a observación, no a estable.
            self.assertEqual(stability.status(c, now)['state'], 'observing')
            self.assertTrue(any(item['critical'] for item in stability.status(c, now)['incidents']))

    def test_missing_mail_is_a_warning_not_a_critical_failure(self):
        with app.connect() as c:
            entry = stability.run(c, app.reception_now())
        self.assertEqual((entry['critical_failures'], entry['warnings']), ([], ['Servicio de correo']))

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
