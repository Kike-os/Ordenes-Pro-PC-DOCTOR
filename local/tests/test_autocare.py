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

        def flaky(c, deep=False, now=None):
            items = real(c, deep, now)
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

        def checks(c, deep=False, now=None):
            def unstable():
                if state['fail']:
                    raise RuntimeError('Servicio no disponible')
                return 'Correcto'
            return [('svc', 'Servicio vigilado', 'alta', unstable)] + real(c, deep, now)[:1]
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
        for required in ('Conectividad con la base de datos', 'Autenticación y sesiones', 'Registro de clientes', 'Órdenes de reparación', 'Presupuestos', 'Licencias e inventario', 'Ventas y pagos', 'Agenda y citas', 'Envío de correos', 'Notificaciones', 'Integraciones configuradas', 'Inteligencia artificial de ADI', 'Servicios internos y tareas programadas', 'Copias de seguridad', 'Registros de errores'):
            self.assertIn(required, names)
        documents = next(s for s in ran['body']['services'] if s['name'] == 'Órdenes de reparación')
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
        wanted = {'critical': False, 'unavailable': False, 'recurrent': False, 'connection': True, 'scheduled': False, 'updates': True, 'min_severity': 'crítica'}
        saved = self.request('/api/autocare/settings', {'settings': json.dumps(wanted)}, cookie=cookie, csrf=csrf)
        self.assertEqual(saved['body']['settings'], wanted)
        notes = [i for i in self.request('/api/notifications', cookie=cookie)['body']['items'] if i['key'].startswith('autocare:errors')]
        self.assertEqual(notes, [])
        reviewed = self.request('/api/autocare/review', {}, cookie=cookie, csrf=csrf)['body']
        self.assertEqual(len([item for item in reviewed['incidents'] if item['source'] == 'ejecución']), 1)
        with app.connect() as c:
            self.assertEqual(len(autocare._load(c, 'autocare_errors', [])), 1)


class AutoCareProTests(AutoCareTests):
    def test_four_result_states_and_no_all_clear_with_unchecked(self):
        with app.connect() as c:
            entry = stability.run(c, app.reception_now())  # automática: el buzón no se comprueba
        statuses = {r['code']: r['status'] for r in entry['results']}
        self.assertEqual(len(statuses), 15)
        self.assertEqual(statuses['mail'], 'error')  # sin correo configurado
        with patch.dict(app.os.environ, {'MAIL_IMAP_HOST': 'i.example.invalid', 'MAIL_SMTP_HOST': 's.example.invalid', 'MAIL_USERNAME': 'b@example.invalid', 'MAIL_PASSWORD': 'x'}), app.connect() as c:
            entry = stability.run(c, app.reception_now())
        mail = next(r for r in entry['results'] if r['code'] == 'mail')
        self.assertEqual((mail['status'], mail['ok']), ('not_checked', True))
        self.assertEqual(entry['counts']['not_checked'], 2);self.assertIn('Envío de correos', entry['unchecked']);self.assertIn('Copias de seguridad', entry['unchecked'])  # sin registro de respaldo central
        self.assertEqual(sum(entry['counts'].values()), 15)

    def test_stepwise_diagnosis_runs_each_check_on_the_server_and_records_once(self):
        cookie, csrf = self.login()
        started = self.request('/api/autocare/diagnose/start', {}, cookie=cookie, csrf=csrf)['body']
        self.assertEqual(len(started['plan']), 15)
        self.assertEqual(self.request('/api/autocare/diagnose/start', {}, cookie=cookie, csrf=csrf)['status'], 409)  # ya hay uno en curso
        self.assertEqual(self.request('/api/autocare/diagnose/step', {'id': started['id'], 'code': started['plan'][1]['code']}, cookie=cookie, csrf=csrf)['status'], 409)  # fuera de orden
        with patch.object(app.mail_pro, 'configured', return_value=True), patch.object(app.mail_pro, 'test_imap', return_value=None):
            for index, item in enumerate(started['plan']):
                out = self.request('/api/autocare/diagnose/step', {'id': started['id'], 'code': item['code']}, cookie=cookie, csrf=csrf)['body']
                self.assertIn(out['result']['status'], ('ok', 'warning', 'error', 'not_checked', 'unavailable'))
                self.assertEqual(out['done'], index == 14)
        self.assertEqual(out['entry']['total'], 15)
        with app.connect() as c:
            runs = stability._load(c, 'stability_runs', [])
        self.assertEqual((len(runs), runs[-1]['source'], runs[-1]['by']), (1, 'manual', 'Persona de prueba'))
        panel = self.request('/api/autocare', cookie=cookie)['body']
        self.assertEqual(panel['last_by'], 'Persona de prueba');self.assertEqual(sum(panel['runs'][0]['counts'].values()), 15)
        self.assertTrue(panel['explanation']);self.assertIsNotNone(panel['post_deploy'])

    def test_incident_lifecycle_with_code_cause_action_and_manual_resolution(self):
        cookie, csrf = self.login()
        real = stability.checks
        state = {'fail': True}

        def checks(c, deep=False, now=None):
            def unstable():
                if state['fail']:
                    raise RuntimeError('No hay servicios de cita')
                return 'Correcto'
            return [('agenda', 'Agenda y citas', 'crítica', unstable)] + real(c, deep, now)[:1]
        now = app.reception_now()
        with patch.object(stability, 'checks', checks), app.connect() as c:
            stability.run(c, now - timedelta(minutes=30), 'programada')
            stability.run(c, now - timedelta(minutes=20), 'programada')
            items = [i for i in autocare.incidents(c) if i['key'] == 'check:agenda']
            self.assertEqual(len(items), 1);item = items[0]
            self.assertRegex(item['code'], r'^INC-\d{8}-\d{3}$');self.assertEqual((item['count'], item['status'], item['severity']), (2, 'activa', 'crítica'))
            self.assertIn('Agenda', item['action']);self.assertTrue(item['cause'])
            state['fail'] = False
            stability.run(c, now, 'programada')
            item = next(i for i in autocare.incidents(c) if i['key'] == 'check:agenda')
            self.assertEqual(item['status'], 'resuelta');self.assertTrue(item['resolved_by'].startswith('Verificación'))
        try:
            raise KeyError('x')
        except Exception as error:
            for _ in range(3):app.note_runtime_error('POST', '/api/orders/5', error)
        panel = self.request('/api/autocare', cookie=cookie)['body']
        runtime = next(i for i in panel['incidents'] if i['source'] == 'ejecución')
        self.assertEqual(runtime['count'], 3)
        self.assertEqual(self.request('/api/autocare/incident', {'code': runtime['code'], 'status': 'resuelta', 'note': 'x'}, cookie=cookie, csrf=csrf)['status'], 400)
        done = self.request('/api/autocare/incident', {'code': runtime['code'], 'status': 'resuelta', 'note': 'Corregido en la rama de pruebas'}, cookie=cookie, csrf=csrf)['body']['incident']
        self.assertEqual((done['status'], done['resolved_by'], done['history'][-1]['note']), ('resuelta', 'Persona de prueba', 'Corregido en la rama de pruebas'))
        notes = [i for i in self.request('/api/notifications', cookie=cookie)['body']['items'] if i['key'].startswith('autocare:recurrent')]
        self.assertEqual(notes, [])  # resuelta: sin aviso de recurrente

    def test_license_and_sales_checks_warn_without_changing_data(self):
        cookie, csrf = self.login()
        import licenses as lic
        with app.connect() as c:
            user = {'id': self.uid, 'role': 'administrador', 'name': 'Persona de prueba'}
            made = lic.register_new(c, {'name': 'Antivirus ficticio', 'line': 'antivirus', 'duration': 'anual', 'price': '10', 'key': 'AUTOCARE-KEY-0001'}, user, app.reception_now())
            c.execute("UPDATE license_units SET activated=1,activated_at='2026-01-01' WHERE id=?", (made['unit_id'],))
            entry = stability.run(c, app.reception_now())
            before = dict(c.execute('SELECT * FROM license_units WHERE id=?', (made['unit_id'],)).fetchone())
        result = next(r for r in entry['results'] if r['code'] == 'licenses')
        self.assertEqual(result['status'], 'warning');self.assertIn('inconsistentes', result['detail'])
        with app.connect() as c:
            self.assertEqual(dict(c.execute('SELECT * FROM license_units WHERE id=?', (made['unit_id'],)).fetchone()), before)
            self.assertEqual(next(i for i in autocare.incidents(c) if i['key'] == 'check:licenses')['severity'], 'baja')

    def test_pending_changes_are_counted_from_the_registry(self):
        cookie, csrf = self.login()
        fake = dict(app.versioning.load());fake['unreleased'] = {'features': ['a'], 'fixes': ['b', 'c']}
        with patch.object(app.versioning, 'load', return_value=fake):
            panel = self.request('/api/autocare', cookie=cookie)['body']
        self.assertEqual(panel['pending_changes'], 3)


class AutoCareFixTests(AutoCareTests):
    MAIL = {'MAIL_IMAP_HOST': 'i.example.invalid', 'MAIL_SMTP_HOST': 's.example.invalid', 'MAIL_USERNAME': 'b@example.invalid', 'MAIL_PASSWORD': 'x'}

    def mail_result(self, entry):
        return next(r for r in entry['results'] if r['code'] == 'mail')

    def test_mail_distinguishes_real_failure_omitted_and_pending(self):
        now = app.reception_now()
        with patch.dict(app.os.environ, self.MAIL), app.connect() as c:
            pending = self.mail_result(stability.run(c, now))
            self.assertEqual(pending['status'], 'not_checked');self.assertIn('pendiente', pending['detail'])
            with patch.object(app.mail_pro, 'test_imap', return_value=None):
                deep = self.mail_result(stability.run(c, now, 'manual'))
            self.assertEqual(deep['status'], 'ok');self.assertIn('IMAP', deep['detail'])
            omitted = self.mail_result(stability.run(c, now + timedelta(hours=1)))
            self.assertEqual(omitted['status'], 'ok');self.assertIn('prueba omitida', omitted['detail'])
            with patch.object(app.mail_pro, 'test_imap', side_effect=app.mail_pro.MailError('autenticacion', 'Usuario o contraseña rechazados')):
                failed = self.mail_result(stability.run(c, now + timedelta(hours=2), 'programada'))
            self.assertEqual(failed['status'], 'error')
            real = self.mail_result(stability.run(c, now + timedelta(hours=3)))
            self.assertEqual(real['status'], 'error');self.assertIn('Fallo real', real['detail'])
            stale = self.mail_result(stability.run(c, now + timedelta(hours=30)))
            self.assertEqual(stale['status'], 'not_checked')

    def test_ticket_only_in_deep_runs_and_step_timings_are_reported(self):
        cookie, csrf = self.login()
        self.request('/api/orders', self.order_data({'request_key': 'autocare-fix-order-0001'}), cookie=cookie, csrf=csrf)
        with app.connect() as c:
            auto = next(r for r in stability.run(c, app.reception_now())['results'] if r['code'] == 'orders')
            deep = next(r for r in stability.run(c, app.reception_now(), 'manual')['results'] if r['code'] == 'orders')
            agenda = next(r for r in stability.run(c, app.reception_now())['results'] if r['code'] == 'agenda')
        self.assertIn('no generado en verificaciones automáticas', auto['detail']);self.assertRegex(deep['detail'], r'ticket PDF generado en \d+ ms')
        self.assertRegex(auto['detail'], r'seguimiento \(\d+ ms\)');self.assertRegex(agenda['detail'], r'horarios \(\d+ ms\)')

    def test_slow_threshold_uses_real_measurements_and_never_changes_status(self):
        history = [{'results': [{'code': 'agenda', 'ms': ms}]} for ms in (200, 210, 190, 205, 220, 198)]
        info = autocare.timing(history, 'agenda', 900)
        self.assertEqual((info['samples'], info['median'], info['threshold'], info['slow']), (6, 205, 1500, False))
        self.assertTrue(autocare.timing(history, 'agenda', 1600)['slow'])
        slow_history = [{'results': [{'code': 'orders', 'ms': ms}]} for ms in (3000, 3200, 3100, 3300, 2900)]
        self.assertEqual(autocare.timing(slow_history, 'orders', 3323)['slow'], False)  # 3,3 s es su normal: no es lento

    def test_service_detail_for_licenses_shows_affected_stock_and_duplicates(self):
        cookie, csrf = self.login()
        import licenses as lic
        with app.connect() as c:
            user = {'id': self.uid, 'role': 'administrador', 'name': 'Persona de prueba'}
            made = lic.register_new(c, {'name': 'Antivirus ficticio', 'line': 'antivirus', 'duration': 'anual', 'price': '10', 'key': 'AAAA-1111-ZZ123456'}, user, app.reception_now())
            lic.register(c, {'product_id': str(made['product_id']), 'key': 'BBBB-2222-ZZ123456'}, user, app.reception_now())
            c.execute("UPDATE license_units SET activated=1,activated_at='2026-01-01' WHERE id=?", (made['unit_id'],))
            stability.run(c, app.reception_now())
            before = [tuple(r) for r in c.execute('SELECT * FROM license_units ORDER BY id')]
        info = self.request('/api/autocare/service/licenses', cookie=cookie)['body']['licenses']
        self.assertEqual([a['code'] for a in info['affected']], ['LIC-000001'])
        self.assertEqual(info['products'][0]['registros'], 2);self.assertIn('registros individuales', info['stock_note'])
        self.assertEqual(info['duplicates'][0]['codes'], ['LIC-000001', 'LIC-000002']);self.assertEqual(info['duplicates'][0]['hint'], '•••• 3456')
        self.assertNotIn('AAAA-1111', str(info));self.assertTrue(info['recommendations'])
        with app.connect() as c:self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM license_units ORDER BY id')], before)
        mail = self.request('/api/autocare/service/mail', cookie=cookie)['body']['mail']
        self.assertEqual(mail['state'], 'Sin configurar');self.assertNotIn('password', {k for k, v in mail.items() if isinstance(v, str) and v == 'x'})
        self.assertEqual(self.request('/api/autocare/service/inventado', cookie=cookie)['status'], 404)
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
        self.assertEqual(self.request('/api/autocare/service/licenses', cookie=cookie)['status'], 403)


if __name__ == '__main__':
    unittest.main()
