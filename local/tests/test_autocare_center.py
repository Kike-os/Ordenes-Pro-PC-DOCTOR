"""Centro de actualizaciones (ADI AutoCare): reintento por servicio, IA y respaldos, recuperación segura, historial exportable y
versiones con quién publicó. Base temporal, datos ficticios y sin red (OpenAI y el correo se simulan)."""
import io
import json
import unittest
import urllib.error
from datetime import timedelta
from unittest.mock import patch

import test_app
import app
import autocare
import stability
import versioning

MAIL = {'MAIL_IMAP_HOST': 'i.example.invalid', 'MAIL_SMTP_HOST': 's.example.invalid', 'MAIL_USERNAME': 'b@example.invalid', 'MAIL_PASSWORD': 'x'}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class AutoCareCenterTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login

    def ai(self, c, deep=True):
        return stability.execute(*next(item for item in stability.checks(c, deep, app.reception_now()) if item[0] == 'ai'))

    def test_ai_is_unavailable_without_key_and_checks_the_model_without_exposing_it(self):
        with app.connect() as c:
            self.assertEqual(self.ai(c)['status'], 'unavailable')
            with patch.dict(app.os.environ, {'OPENAI_API_KEY': 'sk-prueba-ficticia-123456'}):
                with patch('urllib.request.urlopen', return_value=FakeResponse(b'{}')) as opened:
                    ok = self.ai(c)
                self.assertEqual(ok['status'], 'ok');self.assertIn('/v1/models/', opened.call_args[0][0].full_url)
                with patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError('u', 401, 'x', {}, None)):
                    bad = self.ai(c)
                self.assertEqual(bad['status'], 'error');self.assertNotIn('sk-prueba', json.dumps(bad))
                with patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError('u', 429, 'x', {}, None)):
                    self.assertEqual(self.ai(c)['status'], 'warning')
                self.assertEqual(self.ai(c, deep=False)['status'], 'not_checked')  # la verificación automática no llama a OpenAI

    def test_backups_use_the_verified_backup_record(self):
        now = app.reception_now()
        with app.connect() as c:
            def backups():
                return stability.execute(*next(item for item in stability.checks(c, False, now) if item[0] == 'backups'))
            self.assertEqual(backups()['status'], 'not_checked')
            stability._save(c, 'cloud_backup', {'ok': True, 'at': (now - timedelta(days=1)).isoformat(timespec='seconds'), 'bytes': 2097152, 'clients': 3, 'orders': 4})
            self.assertEqual(backups()['status'], 'ok')
            stability._save(c, 'cloud_backup', {'ok': True, 'at': (now - timedelta(days=9)).isoformat(timespec='seconds'), 'bytes': 1, 'clients': 3, 'orders': 4})
            self.assertEqual(backups()['status'], 'warning')
            stability._save(c, 'cloud_backup', {'ok': False, 'at': now.isoformat(timespec='seconds')})
            self.assertEqual(backups()['status'], 'error')

    def test_recheck_closes_the_incident_only_with_a_correct_result_and_records_who(self):
        cookie, csrf = self.login()
        with app.connect() as c:
            stability.run(c, app.reception_now())  # sin correo: incidencia abierta
            self.assertTrue(any(i['key'] == 'check:mail' and i['status'] != 'resuelta' for i in autocare._load(c, 'autocare_incidents', [])))
        again = self.request('/api/autocare/check', {'code': 'mail'}, cookie=cookie, csrf=csrf)['body']
        self.assertEqual(again['result']['status'], 'error')  # sigue fallando: la incidencia no se cierra
        with app.connect() as c:
            self.assertTrue(any(i['key'] == 'check:mail' and i['status'] != 'resuelta' for i in autocare._load(c, 'autocare_incidents', [])))
        with patch.dict(app.os.environ, MAIL), patch.object(app.mail_pro, 'test_imap', return_value=None):
            fixed = self.request('/api/autocare/check', {'code': 'mail'}, cookie=cookie, csrf=csrf)['body']
        self.assertEqual(fixed['result']['status'], 'ok')
        mail = next(s for s in fixed['overview']['services'] if s['code'] == 'mail')
        self.assertEqual((mail['status'], mail['rechecked_by']), ('ok', 'Persona de prueba'))
        self.assertEqual(fixed['overview']['rechecks'][0]['code'], 'mail')
        with app.connect() as c:
            item = next(i for i in autocare._load(c, 'autocare_incidents', []) if i['key'] == 'check:mail')
            self.assertEqual((item['status'], item['resolved_by']), ('resuelta', 'Persona de prueba'))
            resolved = [e for e in autocare._load(c, 'autocare_events', []) if e['kind'] == 'resolved' and e['module'] == 'Envío de correos']
            self.assertEqual(resolved[-1]['by'], 'Persona de prueba');self.assertTrue(resolved[-1]['id'].startswith('EV-'))
        self.assertEqual(self.request('/api/autocare/check', {'code': 'inventado'}, cookie=cookie, csrf=csrf)['status'], 409)
        with app.connect() as c:
            stability._save(c, 'stability_running', {'version': '0', 'since': app.reception_now().isoformat(timespec='seconds')})
        self.assertEqual(self.request('/api/autocare/check', {'code': 'mail'}, cookie=cookie, csrf=csrf)['status'], 409)  # sin ejecuciones simultáneas

    def test_safe_actions_need_admin_confirmation_and_are_verified(self):
        cookie, csrf = self.login()
        import licenses as lic
        now = app.reception_now()
        with app.connect() as c:
            user = {'id': self.uid, 'role': 'administrador', 'name': 'Persona de prueba'}
            made = lic.register_new(c, {'name': 'Antivirus ficticio', 'line': 'antivirus', 'duration': 'anual', 'price': '10', 'key': 'AAAA-1111-ZZ123456'}, user, now)
            lic.register(c, {'product_id': str(made['product_id']), 'key': 'BBBB-2222-ZZ123456'}, user, now)
            c.execute("UPDATE license_units SET expires_at='2020-01-01' WHERE id=?", (made['unit_id'],))
            orders = c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        self.assertEqual(self.request('/api/autocare/action', {'action': 'license_expiry'}, cookie=cookie, csrf=csrf)['status'], 400)  # sin confirmar
        self.assertEqual(self.request('/api/autocare/action', {'action': 'borrar_todo', 'confirm': '1'}, cookie=cookie, csrf=csrf)['status'], 409)
        out = self.request('/api/autocare/action', {'action': 'license_expiry', 'confirm': '1'}, cookie=cookie, csrf=csrf)['body']
        self.assertIn('#' + str(made['unit_id']), out['done']);self.assertEqual(out['verification']['code'], 'licenses')
        with app.connect() as c:
            self.assertEqual([r[0] for r in c.execute('SELECT status FROM license_units ORDER BY id')], ['vencida', 'disponible'])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0], orders)
            self.assertTrue(any(e['kind'] == 'recovery' and e['by'] == 'Persona de prueba' for e in autocare._load(c, 'autocare_events', [])))
            stability._save(c, 'stability_running', {'version': '0', 'since': now.isoformat(timespec='seconds')})
        self.assertEqual(self.request('/api/autocare/action', {'action': 'unlock_diagnosis', 'confirm': '1'}, cookie=cookie, csrf=csrf)['status'], 409)  # sigue activo
        with app.connect() as c:
            stability._save(c, 'stability_running', {'version': '0', 'since': (now - timedelta(minutes=30)).isoformat(timespec='seconds')})
        freed = self.request('/api/autocare/action', {'action': 'unlock_diagnosis', 'confirm': '1'}, cookie=cookie, csrf=csrf)['body']
        self.assertEqual(freed['done'], 'Marca de diagnóstico liberada.')
        with app.connect() as c:
            self.assertIsNone(stability._load(c, 'stability_running', None))
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
        self.assertEqual(self.request('/api/autocare/action', {'action': 'license_expiry', 'confirm': '1'}, cookie=cookie, csrf=csrf)['status'], 403)
        self.assertEqual(self.request('/api/autocare/check', {'code': 'mail'}, cookie=cookie, csrf=csrf)['status'], 403)

    def test_history_has_ids_filters_and_exports_without_sensitive_data(self):
        cookie, csrf = self.login()
        with app.connect() as c:
            # Evento antiguo (sin identificador ni usuario) y uno con un correo y una clave en el detalle.
            events = [{'at': '2026-01-02T10:00:00', 'kind': 'incident', 'severity': 'alta', 'module': 'Agenda y citas', 'message': 'Antiguo', 'detail': '', 'version': '1.0.0'}]
            stability._save(c, 'autocare_events', events)
            autocare.log(c, 'review', 'baja', 'Envío de correos', 'Prueba', 'cliente@example.invalid sk-abcdefghijklmnop 0999999999', app.reception_now(), '1.5.0', 'Persona de prueba')
            rows = autocare.history_rows(c)
            self.assertEqual(rows[1]['id'], 'EV-H00000');self.assertTrue(rows[0]['id'].startswith('EV-'))
            self.assertEqual([r['message'] for r in autocare.history_rows(c, service='Agenda y citas')], ['Antiguo'])
            self.assertEqual([r['message'] for r in autocare.history_rows(c, who='persona')], ['Prueba'])
            self.assertEqual(autocare.history_rows(c, frm='2026-01-03', to='2026-01-01'), [])
        csv = self.request('/api/autocare/history.csv?version=1.5.0', cookie=cookie)
        self.assertEqual(csv['status'], 200)
        body = csv['body'].decode() if isinstance(csv['body'], bytes) else csv['body']
        self.assertIn('Identificador', body);self.assertIn('Prueba', body);self.assertNotIn('Antiguo', body)
        for secret in ('cliente@example.invalid', 'sk-abcdefghijklmnop', '0999999999'):
            self.assertNotIn(secret, body)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
        self.assertEqual(self.request('/api/autocare/history.csv', cookie=cookie)['status'], 403)

    def test_overview_reports_build_migrations_severity_and_publisher(self):
        cookie, csrf = self.login()
        with app.connect() as c:
            stability.run(c, app.reception_now())
        with patch.dict(app.os.environ, {'VERCEL_GIT_COMMIT_SHA': 'abcdef1234567', 'VERCEL_ENV': 'production'}):
            panel = self.request('/api/autocare', cookie=cookie)['body']
        self.assertEqual((panel['build']['commit'], panel['build']['environment']), ('abcdef1', 'production'))
        self.assertEqual(panel['migrations']['pending'], []);self.assertEqual(panel['migrations']['applied'], panel['migrations']['total'])
        self.assertEqual(set(panel['incidents_by_severity']), {'crítica', 'alta', 'media', 'baja'})
        self.assertGreaterEqual(panel['incidents_by_severity']['media'], 1)  # correo sin configurar
        mail = next(s for s in panel['services'] if s['code'] == 'mail')
        self.assertTrue(mail['cause'] and mail['action']);self.assertEqual(mail['limit_ms'], 20000)
        self.assertEqual({a['code'] for a in panel['actions']}, {'unlock_diagnosis', 'license_expiry'})
        self.assertIn('unavailable', panel['counts'])
        registry = {'unreleased': {'fixes': ['Arreglo ficticio']}, 'releases': [{'version': '1.0.0', 'date': '2026-01-01T00:00:00-05:00', 'type': 'initial', 'status': 'publicada', 'summary': '', 'changes': {}}]}
        made = versioning.publish(versioning.validate(registry), 'patch', 'Prueba', published_by='Kike', authorized_by='Administración')
        self.assertEqual((made['releases'][0]['published_by'], made['releases'][0]['authorized_by']), ('Kike', 'Administración'))
        self.assertNotIn('published_by', made['releases'][1])  # las anteriores no se rellenan


if __name__ == '__main__':
    unittest.main()
