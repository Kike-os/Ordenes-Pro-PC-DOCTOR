"""ADI AutoCare Pro: registro de errores clasificados, recuperación segura, historial, avisos y panel. Base temporal, datos ficticios."""
import io
import json
import unittest
from datetime import timedelta
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

import test_app
import app
import autocare
import stability


class AutoCareTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data

    def counts(self, c):
        return {t: c.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in ('orders', 'clients', 'devices', 'quotes', 'appointments', 'order_history', 'equipment_payments' if c.execute("SELECT 1 FROM sqlite_master WHERE name='equipment_payments'").fetchone() else 'users')}

    def test_runtime_errors_are_classified_without_personal_data(self):
        try:
            raise app.sqlite3.OperationalError('database is locked: INSERT INTO clients VALUES ("Cliente Ficticio")')
        except Exception as error:
            app.note_runtime_error('POST', '/api/clients/123', error)
        try:
            raise KeyError('dato')
        except Exception as error:
            app.note_runtime_error('POST', '/api/quotes/9', error)
        with app.connect() as c:
            errors = autocare.recent_errors(c)
        self.assertEqual([(e['severity'], e['module'], e['path'], e['type']) for e in errors],
                         [('crítica', 'Clientes', '/api/clients/:id', 'OperationalError'), ('alta', 'Presupuestos', '/api/quotes/:id', 'KeyError')])
        self.assertNotIn('Cliente Ficticio', json.dumps(errors))
        self.assertTrue(errors[0]['where'])

    def test_production_layer_records_unexpected_errors(self):
        import wsgi_app
        env = {}
        setup_testing_defaults(env)
        env.update(PATH_INFO='/api/public/version', REQUEST_METHOD='GET', **{'wsgi.input': io.BytesIO(b'')})
        with patch.object(app.Handler, 'do_GET', side_effect=RuntimeError('fallo de prueba')):
            status = {}
            body = b''.join(wsgi_app.app(env, lambda s, h, e=None: status.update(s=s)))
        self.assertTrue(status['s'].startswith('500'))
        self.assertNotIn(b'fallo de prueba', body)
        with app.connect() as c:
            self.assertEqual([(e['method'], e['path'], e['module']) for e in autocare.recent_errors(c)], [('GET', '/api/public/version', 'Servicios públicos')])

    def test_transient_failures_are_retried_once_and_recorded_as_recovery(self):
        real = stability.checks
        calls = {'n': 0}

        def flaky(c, deep=False):
            items = real(c, deep)
            def once():
                calls['n'] += 1
                if calls['n'] == 1:
                    raise ConnectionError('conexión interrumpida')
                return 'Respondió en el reintento'
            return [('net', 'Servicio de prueba', 'media', once)] + items[:2]
        with patch.object(stability.time, 'sleep'), patch.object(stability, 'checks', flaky), app.connect() as c:
            entry = stability.run(c, app.reception_now(), 'manual')
            result = entry['results'][0]
            self.assertEqual((result['ok'], result['recovered'], result['detail']), (True, True, 'Respondió en el reintento'))
            kinds = [event['kind'] for event in autocare._load(c, 'autocare_events', [])]
            self.assertIn('recovery', kinds)
            self.assertIn('version', kinds)

    def test_incident_is_logged_once_and_resolution_is_recorded(self):
        real = stability.checks
        state = {'fail': True}

        def checks(c, deep=False):
            def unstable():
                if state['fail']:
                    raise RuntimeError('Servicio no disponible')
                return 'Correcto'
            return [('svc', 'Servicio vigilado', 'alta', unstable)] + real(c, deep)[:1]
        now = app.reception_now()
        with patch.object(stability, 'checks', checks), app.connect() as c:
            stability.run(c, now - timedelta(hours=2), 'programada')
            stability.run(c, now - timedelta(hours=1), 'programada')
            state['fail'] = False
            stability.run(c, now, 'programada')
            events = [(e['kind'], e['module']) for e in autocare._load(c, 'autocare_events', []) if e['module'] == 'Servicio vigilado']
            self.assertEqual(events, [('incident', 'Servicio vigilado'), ('resolved', 'Servicio vigilado')])

    def test_panel_and_diagnosis_are_admin_only_and_never_modify_business_data(self):
        self.assertEqual(self.request('/api/autocare')['status'], 401)
        cookie, csrf = self.login()
        self.request('/api/orders', self.order_data({'request_key': 'autocare-order-request-01'}), cookie=cookie, csrf=csrf)
        with app.connect() as c:
            before = self.counts(c)
        ran = self.request('/api/autocare/diagnose', {}, cookie=cookie, csrf=csrf)
        self.assertEqual(ran['status'], 200)
        self.assertEqual(ran['body']['ran']['total'], len(ran['body']['services']))
        names = {s['name'] for s in ran['body']['services']}
        for required in ('Inicio de sesión y autenticación', 'Registro de clientes', 'Seguimiento de órdenes', 'Tickets y presupuestos PDF', 'Servicio de correo', 'Agenda de citas', 'ADI con inteligencia artificial', 'Base de datos y migraciones', 'Errores de ejecución'):
            self.assertIn(required, names)
        documents = next(s for s in ran['body']['services'] if s['name'] == 'Tickets y presupuestos PDF')
        self.assertTrue(documents['ok'])
        self.assertIn('ticket', documents['detail'])
        with app.connect() as c:
            self.assertEqual(self.counts(c), before)
            runs = stability._load(c, 'stability_runs', [])
            self.assertEqual(runs[-1]['source'], 'manual')
        panel = self.request('/api/autocare', cookie=cookie)['body']
        self.assertIn(panel['general'], ('ok', 'degraded', 'critical'))
        self.assertTrue(panel['last_check'])
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
        self.assertEqual(self.request('/api/autocare', cookie=cookie)['status'], 403)
        self.assertEqual(self.request('/api/autocare/diagnose', {}, cookie=cookie, csrf=csrf)['status'], 403)

    def test_settings_review_and_notifications(self):
        cookie, csrf = self.login()
        try:
            raise KeyError('x')
        except Exception as error:
            app.note_runtime_error('POST', '/api/orders/5', error)
        notes = [i for i in self.request('/api/notifications', cookie=cookie)['body']['items'] if i['key'].startswith('autocare:')]
        self.assertTrue(any('error de ejecución' in i['title'] for i in notes))
        saved = self.request('/api/autocare/settings', {'settings': json.dumps({'incidents': False, 'recoveries': True, 'versions': True, 'min_severity': 'crítica'})}, cookie=cookie, csrf=csrf)
        self.assertEqual(saved['body']['settings'], {'incidents': False, 'recoveries': True, 'versions': True, 'min_severity': 'crítica'})
        notes = [i for i in self.request('/api/notifications', cookie=cookie)['body']['items'] if i['key'].startswith('autocare:errors')]
        self.assertEqual(notes, [])
        reviewed = self.request('/api/autocare/review', {}, cookie=cookie, csrf=csrf)['body']
        self.assertFalse([item for item in reviewed['active'] if item['source'] == 'ejecución'])
        with app.connect() as c:
            self.assertEqual(len(autocare._load(c, 'autocare_errors', [])), 1)


if __name__ == '__main__':
    unittest.main()
