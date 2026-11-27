"""ADI Release Monitor 2.0: comprobaciones nuevas de solo lectura, la verificación manual no suma al período de seguimiento (no permite
eludir los requisitos), detalle técnico solo para administración, informe copiable sin secretos y avisos sin duplicados.
Base temporal y datos ficticios; no se envía nada."""
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_app
import app
import stability
import release_monitor

MAIL = {'MAIL_IMAP_HOST': 'i.example.invalid', 'MAIL_SMTP_HOST': 's.example.invalid', 'MAIL_USERNAME': 'b@example.invalid', 'MAIL_PASSWORD': 'x'}


class ReleaseMonitorTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data

    def counts(self, c):
        return {t: c.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in ('orders', 'clients', 'invoices', 'whatsapp_outbox', 'users', 'audit')}

    def test_new_checks_are_read_only_and_part_of_every_run(self):
        now = app.reception_now()
        with patch.dict(app.os.environ, MAIL), app.connect() as c:
            before = self.counts(c)
            entry = stability.run(c, now)
            self.assertEqual(self.counts(c), before)                                                  # no escriben datos de negocio
        codes = [r['code'] for r in entry['results']]
        for code in ('migrations', 'frontend', 'invoicing', 'whatsapp'):
            self.assertIn(code, codes)
        self.assertEqual(entry['total'], 19)
        whatsapp = next(r for r in entry['results'] if r['code'] == 'whatsapp')
        self.assertEqual(whatsapp['status'], 'not_checked')                                          # sin credenciales: no se comprueba ni se envía
        self.assertEqual(next(r for r in entry['results'] if r['code'] == 'frontend')['status'], 'ok')

    def test_manual_checks_never_add_passes_to_the_follow_up(self):
        now = app.reception_now()
        with patch.dict(app.os.environ, MAIL), app.connect() as c:
            for hours in (30, 20, 10):
                stability.run(c, now - timedelta(hours=hours), 'manual', 'Persona de prueba')
            info = stability.status(c, now)
            self.assertEqual((info['window_passes'], info['checks_passed']), (0, 3))
            self.assertNotEqual(info['state'], 'stable')                                             # tres manuales en 24 h no bastan
            for hours in (30, 20, 10):
                stability.run(c, now - timedelta(hours=hours))
            info = stability.status(c, now)
            self.assertEqual((info['window_passes'], info['window_start'][:13]), (3, (now - timedelta(hours=30)).isoformat()[:13]))   # cuentan las automáticas

    def test_details_are_admin_only_and_the_report_has_no_secrets(self):
        cookie, csrf = self.login()
        self.assertEqual(self.request('/api/system/release-monitor')['status'], 401)
        with patch.dict(app.os.environ, dict(MAIL, WHATSAPP_TOKEN='token-ficticio-secreto', WHATSAPP_PHONE_NUMBER_ID='123')), app.connect() as c:
            stability.run(c, app.reception_now())
        out = self.request('/api/system/release-monitor', cookie=cookie)
        self.assertEqual(out['status'], 200, out['body'])
        body = out['body']
        self.assertEqual(len(body['detail_tests']), 19)
        self.assertTrue(all('detail' in t and 'ms' in t for t in body['detail_tests']))
        self.assertIn('ADI Release Monitor 2.0', body['report'])
        self.assertNotIn('token-ficticio-secreto', str(body))
        self.assertNotIn('MAIL_PASSWORD', str(body))
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico'");c.commit()
        self.assertEqual(self.request('/api/system/release-monitor', cookie=cookie)['status'], 403)

    def test_laboratory_status_and_probe(self):
        cookie, _ = self.login()
        path = '/api/system/release-monitor'
        probe = path + '?lab_probe=1'
        self.assertEqual(self.request(probe)['status'], 401)
        status = self.request(path, cookie=cookie)['body']['lab']
        self.assertEqual([(r['number'], r['applied'], r['storage']) for r in status],
                         [('131', True, True), ('132', True, True)])
        for _ in range(3):
            result = self.request(probe, cookie=cookie)
            self.assertEqual(result['status'], 200)
            self.assertEqual(set(result['body']), {'search_ms', 'matches', 'database'})
            self.assertEqual(result['body']['database'], 'SQLite')
        self.assertEqual(self.request(probe, cookie=cookie)['status'], 429)
        with app.connect() as c:
            c.execute('DROP TABLE adi_lab_diagnoses')
        self.assertFalse(self.request(path, cookie=cookie)['body']['lab'][1]['storage'])
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico'")
        self.assertEqual(self.request(probe, cookie=cookie)['status'], 403)

    def test_notifications_have_stable_keys_and_report_missing_scheduled_tasks(self):
        now = app.reception_now()
        with patch.dict(app.os.environ, MAIL), app.connect() as c:
            stability.run(c, now - timedelta(hours=2), 'programada')
            first = release_monitor.notifications(c, now)
            self.assertEqual([i['key'] for i in first], ['release:observing:' + stability.status(c, now)['version']])
            self.assertEqual(first, release_monitor.notifications(c, now))                            # misma clave: no se duplica
            stability.cron_heartbeat(c, now - timedelta(hours=40), 'stability')
            c.execute("DELETE FROM system_state WHERE key='stability_runs'");c.execute("DELETE FROM system_state WHERE key='stability_versions'");c.commit()
            later = release_monitor.notifications(c, now)
        self.assertTrue(any(i['key'].startswith('release:cron-missed:') for i in later))


class RunComparisonTests(unittest.TestCase):
    def test_comparison_uses_two_runs_of_the_installed_version(self):
        import release_monitor
        def run(version, at, status):
            return {'version':version,'at':at,'results':[{'code':'db','name':'Base','status':status,'ok':status=='ok'}]}
        runs = [run('1.0.0','one','ok'),run('2.0.0','two','error'),run('1.0.0','three','warning')]
        self.assertFalse(release_monitor.compare_runs(runs,'2.0.0')['available'])
        comparison = release_monitor.compare_runs(runs,'1.0.0')
        self.assertEqual((comparison['from_at'],comparison['to_at']), ('one','three'))
        self.assertEqual(comparison['changes'],[{'code':'db','name':'Base','before':'ok','after':'warning'}])


if __name__ == '__main__':
    unittest.main()
