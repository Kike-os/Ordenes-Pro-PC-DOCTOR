"""WhatsApp Business (1.5.275). Base temporal, datos ficticios y API de Meta SIMULADA: ninguna llamada sale a internet ni llega a clientes.

Cubre: requisitos sin exponer secretos; permisos de administración; comprobación de credenciales, plantillas y webhook; activación solo con
credenciales y plantilla; autorización del cliente (sin ella, «omitido»); gracia y verificación de que el aviso siga siendo cierto; errores
temporales con reintento automático y permanentes sin él; botón de reintento solo cuando procede; sin duplicados (clave única y reclamo);
webhook firmado (entregado, leído, sin retroceder), bajas «BAJA»; envío de prueba solo al número autorizado; recordatorios de entrega; y que
el correo sigue igual."""
import hashlib
import hmac
import json
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_part_requests as parts
import app
import whatsapp_business as wa

FAKE = {'WHATSAPP_TOKEN': 'token-ficticio-NO-REAL-9f8e7d6c', 'WHATSAPP_PHONE_NUMBER_ID': '100000000001234', 'WHATSAPP_BUSINESS_ACCOUNT_ID': '200000000005678',
        'WHATSAPP_APP_SECRET': 'secreto-ficticio-app', 'WHATSAPP_VERIFY_TOKEN': 'verificacion-ficticia-xyz'}
TEMPLATES = [{'name': 'pcdoctor_aviso', 'language': 'es', 'status': 'APPROVED', 'category': 'UTILITY',
              'components': [{'type': 'BODY', 'text': 'Hola {{1}}, sobre su orden {{2}}: {{3}}.'}]},
             {'name': 'aviso_rechazado', 'language': 'es', 'status': 'REJECTED', 'category': 'UTILITY', 'components': [{'type': 'BODY', 'text': 'Hola {{1}}'}]}]


class Meta:
    """API de Meta simulada: registra cada llamada y responde lo programado (por defecto, éxito)."""
    def __init__(self):
        self.calls, self.replies = [], []

    def __call__(self, method, url, headers, payload):
        self.calls.append((method, url, headers, payload))
        if url.endswith('/messages'):
            return self.replies.pop(0) if self.replies else (200, {'messages': [{'id': 'wamid.FICTICIO%d' % len(self.calls)}]})
        if 'message_templates' in url:
            return 200, {'data': TEMPLATES}
        if 'subscribed_apps' in url:
            return 200, {'data': [{'whatsapp_business_api_data': {'id': '1'}}]}
        if 'debug_token' in url:
            return 200, {'data': {'scopes': ['whatsapp_business_messaging', 'whatsapp_business_management'], 'expires_at': 0}}
        return 200, {'id': FAKE['WHATSAPP_PHONE_NUMBER_ID'], 'display_phone_number': '+593 98 000 0000', 'verified_name': 'PC-DOCTOR (ficticio)',
                     'quality_rating': 'GREEN', 'platform_type': 'CLOUD_API'}

    def sends(self):
        return [c for c in self.calls if c[1].endswith('/messages')]


class WhatsAppBusinessTests(unittest.TestCase):
    Base = parts.PartRequestTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    request, login, order_data = Base.request, Base.login, Base.order_data

    def setUp(self):
        self.Base.setUp(self)
        self.meta = Meta()
        self.transport = patch.object(wa, 'TRANSPORT', self.meta)
        self.transport.start()

    def tearDown(self):
        self.transport.stop()
        self.Base.tearDown(self)

    # ---- ayudantes ----
    def session(self):
        cookie, csrf = self.login()
        return cookie, csrf, (lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf))

    def order(self, post, key):
        got = post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'request_key': 'whatsapp-prueba-orden-' + key}))
        self.assertIn(got['status'], (200, 201), got['body'])
        return got['body']['id']

    def enable(self, post, **extra):
        got = post('/api/whatsapp/settings', general_template='pcdoctor_aviso', general_lang='es', auto=True, **extra)
        self.assertEqual(got['status'], 200, got['body'])

    def consent(self, post, oid):
        got = post('/api/orders/%d/whatsapp/consent' % oid, decision='aceptado', source='presencial', confirm=True)
        self.assertEqual((got['status'], got['body']['consent']['state']), (200, 'aceptado'), got['body'])

    def outbox(self, oid=None):
        with app.connect() as c:
            sql = 'SELECT * FROM whatsapp_outbox' + (' WHERE order_id=?' if oid else '') + ' ORDER BY id'
            return [dict(r) for r in c.execute(sql, (oid,) if oid else ())]

    def follow(self, post, oid, kind):
        got = post('/api/orders/%d/followups' % oid, kind=kind, internal_note='Registro técnico ficticio (%s).' % kind, client_message='', client_visible='')
        self.assertEqual(got['status'], 201, got['body'])

    def technician(self):
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnicowa','tecwa@example.invalid','Técnico ficticio',?,'tecnico',0)", (self.hash,))
            c.commit()
        got = self.request('/api/login', {'login': 'tecnicowa', 'password': 'contraseña-segura-de-prueba'})
        cookie = got['cookie'].split(';')[0]
        csrf = self.request('/api/me', cookie=cookie)['body']['user']['csrf']
        return lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf), cookie

    def later(self, minutes):
        return app.reception_now() + timedelta(minutes=minutes)

    # ---- pruebas ----
    def test_requirements_without_secrets_and_admin_only(self):
        cookie, csrf, post = self.session()
        data = self.request('/api/whatsapp', cookie=cookie)['body']
        self.assertEqual(data['state'], 'sin_configurar')
        self.assertEqual({r['key'] for r in data['requirements'] if r['required'] and not r['present']},
                         {'WHATSAPP_TOKEN', 'WHATSAPP_PHONE_NUMBER_ID', 'WHATSAPP_BUSINESS_ACCOUNT_ID', 'WHATSAPP_APP_SECRET', 'WHATSAPP_VERIFY_TOKEN'})
        self.assertEqual(data['version']['current'], 'v26.0')
        self.assertFalse(data['settings']['auto'])  # apagado por defecto
        oid = self.order(post, 'sin-config')
        self.follow(post, oid, 'diagnostico')
        self.assertEqual(self.outbox(), [])  # sin credenciales no se registra nada por WhatsApp
        with patch.dict(app.os.environ, FAKE):
            raw = json.dumps(self.request('/api/whatsapp', cookie=cookie)['body'], ensure_ascii=False)
            for secret in FAKE.values():
                self.assertNotIn(secret, raw)
            self.assertIn('…1234', raw)
            self.assertIn('/api/public/whatsapp/webhook', raw)
            tech, tcookie = self.technician()
            self.assertEqual(self.request('/api/whatsapp', cookie=tcookie)['status'], 403)
            self.assertEqual(self.request('/api/whatsapp/history', cookie=tcookie)['status'], 403)
            for path in ('/api/whatsapp/settings', '/api/whatsapp/check', '/api/whatsapp/test', '/api/whatsapp/process'):
                self.assertEqual(tech(path, auto=True, confirm=True)['status'], 403, path)
            self.assertEqual(self.request('/api/whatsapp/settings', {'auto': True}, cookie=cookie)['status'], 403)  # sin CSRF
            self.assertEqual(self.request('/api/whatsapp')['status'], 401)
        self.assertEqual(self.meta.calls, [])

    def test_activation_requires_credentials_and_template(self):
        cookie, csrf, post = self.session()
        got = post('/api/whatsapp/settings', auto=True)
        self.assertEqual(got['status'], 400)
        self.assertIn('auto', got['body']['fields'])
        with patch.dict(app.os.environ, FAKE):
            got = post('/api/whatsapp/settings', auto=True)
            self.assertEqual(got['status'], 400)
            self.assertIn('plantilla', got['body']['fields']['auto'])
            self.assertEqual(post('/api/whatsapp/settings', general_template='Plantilla Mala!')['status'], 400)
            self.assertEqual(post('/api/whatsapp/settings', test_number='12')['status'], 400)
            self.enable(post)
            self.assertTrue(self.request('/api/whatsapp', cookie=cookie)['body']['settings']['auto'])

    def test_server_check_reports_meta_state_and_template_issues(self):
        cookie, csrf, post = self.session()
        with patch.dict(app.os.environ, FAKE):
            self.enable(post, events={'listo': {'template': 'aviso_rechazado'}, 'entregado': {'template': 'no_existe'}})
            got = post('/api/whatsapp/check')
            self.assertEqual(got['status'], 200, got['body'])
            check = got['body']['check']
            states = {s['key']: s['state'] for s in check['steps']}
            self.assertEqual((states['variables'], states['token'], states['numero'], states['permisos'], states['plantillas'], states['suscripcion']),
                             ('ok', 'ok', 'ok', 'ok', 'ok', 'ok'))
            self.assertEqual(states['webhook'], 'warn')  # aún no llegó ningún aviso firmado
            self.assertEqual((states['plantilla:listo'], states['plantilla:entregado']), ('error', 'error'))
            self.assertFalse(check['ok'])
            self.assertNotIn(FAKE['WHATSAPP_TOKEN'], json.dumps(got['body']))
            # El token viaja solo en la cabecera hacia Meta, desde el servidor, y con la versión vigente.
            self.assertTrue(all(call[2]['Authorization'] == 'Bearer ' + FAKE['WHATSAPP_TOKEN'] and '/v26.0/' in call[1] for call in self.meta.calls))
            self.assertEqual(self.request('/api/whatsapp', cookie=cookie)['body']['check']['checked_at'], check['checked_at'])

    def test_consent_required_then_retry_sends_template(self):
        cookie, csrf, post = self.session()
        with patch.dict(app.os.environ, FAKE):
            self.enable(post)
            oid = self.order(post, 'consent')
            first = self.request('/api/orders/%d/whatsapp' % oid, cookie=cookie)['body']
            self.assertEqual(first['consent']['state'], 'sin_registro')
            item = first['items'][0]
            self.assertEqual((item['event'], item['status'], item['reason_kind'], item['can_retry']), ('orden_registrada', 'omitido', 'consentimiento', False))
            self.assertEqual(post('/api/orders/%d/whatsapp/consent' % oid, decision='aceptado', source='presencial')['status'], 400)  # sin confirmación expresa
            self.assertEqual(post('/api/orders/%d/whatsapp/consent' % oid, decision='aceptado', source='baja', confirm=True)['status'], 400)
            self.consent(post, oid)
            now = self.request('/api/orders/%d/whatsapp' % oid, cookie=cookie)['body']['items'][0]
            self.assertTrue(now['can_retry'])
            got = post('/api/whatsapp/outbox/%d/retry' % now['id'])
            self.assertEqual((got['status'], got['body']['item']['status'], got['body']['item']['attempts']), (200, 'enviado', 1), got['body'])
            payload = self.meta.sends()[0][3]
            self.assertEqual((payload['to'], payload['type'], payload['template']['name'], payload['template']['language']['code']),
                             ('593991234567', 'template', 'pcdoctor_aviso', 'es'))
            params = [p['text'] for p in payload['template']['components'][0]['parameters']]
            with app.connect() as c:
                code = c.execute('SELECT code FROM orders WHERE id=?', (oid,)).fetchone()[0]
                msg = c.execute("SELECT channel,status,provider_id FROM order_messages WHERE order_id=? AND request_key LIKE 'wa-outbox-%'", (oid,)).fetchone()
            self.assertEqual(params[:2], ['Cliente', code])
            self.assertIn('registramos su equipo', params[2])
            self.assertEqual(tuple(msg), ('whatsapp', 'enviado', 'wamid.FICTICIO%d' % len(self.meta.calls)))
            self.assertEqual(post('/api/whatsapp/outbox/%d/retry' % now['id'])['status'], 409)  # ya enviado: no se repite
            self.assertEqual(len(self.meta.sends()), 1)

    def test_status_notice_waits_and_is_dropped_when_no_longer_true(self):
        cookie, csrf, post = self.session()
        with patch.dict(app.os.environ, FAKE):
            self.enable(post)
            oid = self.order(post, 'gracia')
            self.consent(post, oid)
            self.follow(post, oid, 'diagnostico')
            with app.connect() as c:
                self.assertEqual(wa.process(c, app.reception_now()), [])  # aún dentro de la gracia de 3 minutos
            self.follow(post, oid, 'reparacion')  # el técnico avanza enseguida
            with app.connect() as c:
                done = {r['event']: r for r in wa.process(c, self.later(4))}
            self.assertEqual(done['diagnostico']['status'], 'omitido')
            self.assertIn('ya no era cierto', done['diagnostico']['detail'])
            self.assertEqual(done['reparacion_iniciada']['status'], 'enviado')
            self.assertEqual(len(self.meta.sends()), 1)
            with app.connect() as c:  # el correo no cambia: sus avisos siguen siendo solo de correo
                self.assertEqual({r[0] for r in c.execute('SELECT channel FROM order_status_notices')} - {'correo'}, set())

    def test_temporary_errors_retry_permanent_errors_do_not(self):
        cookie, csrf, post = self.session()
        with patch.dict(app.os.environ, FAKE):
            self.enable(post)
            oid = self.order(post, 'errores')
            self.consent(post, oid)
            self.meta.replies = [(503, {'error': {'code': 131016, 'message': 'Servicio no disponible (ficticio)'}})]
            got = post('/api/orders/%d/whatsapp/send' % oid, event='diagnostico_terminado')
            self.assertEqual(got['status'], 200, got['body'])
            item = next(i for i in got['body']['items'] if i['event'] == 'diagnostico_terminado')
            self.assertEqual((item['status'], item['permanent'], item['attempts'], item['can_retry']), ('fallido', False, 1, True))
            self.assertTrue(item['next_attempt_at'])
            self.assertEqual(post('/api/orders/%d/whatsapp/send' % oid, event='diagnostico_terminado')['status'], 409)  # mismo aviso, mismo día
            with app.connect() as c:
                self.assertEqual(wa.due_ids(c, app.reception_now()), [])
                self.assertEqual(wa.due_ids(c, self.later(3)), [item['id']])
                again = wa.process(c, self.later(3))
            self.assertEqual((again[0]['status'], again[0]['attempts']), ('enviado', 2))
            # Número sin WhatsApp: permanente, sin reintento automático ni botón.
            self.meta.replies = [(400, {'error': {'code': 131026, 'message': 'Message undeliverable (ficticio)'}})]
            got = post('/api/orders/%d/whatsapp/send' % oid, event='listo')
            bad = next(i for i in got['body']['items'] if i['event'] == 'listo')
            self.assertEqual((bad['status'], bad['permanent'], bad['reason_kind'], bad['can_retry'], bad['next_attempt_at']), ('fallido', True, 'telefono', False, ''))
            self.assertEqual(post('/api/whatsapp/outbox/%d/retry' % bad['id'])['status'], 409)
            # Plantilla inexistente: permanente, pero se puede reintentar a mano después de corregirla.
            self.meta.replies = [(400, {'error': {'code': 132001, 'message': 'Template name does not exist (ficticio)'}})]
            got = post('/api/orders/%d/whatsapp/send' % oid, event='entregado')
            tpl = next(i for i in got['body']['items'] if i['event'] == 'entregado')
            self.assertEqual((tpl['status'], tpl['reason_kind'], tpl['can_retry']), ('fallido', 'plantilla', True))
            with app.connect() as c:
                self.assertEqual(wa.due_ids(c, self.later(600)), [])
            self.assertEqual(len(self.meta.sends()), 4)

    def test_no_double_send_and_interrupted_send_is_not_resent(self):
        cookie, csrf, post = self.session()
        with patch.dict(app.os.environ, FAKE):
            self.enable(post)
            oid = self.order(post, 'duplicado')
            self.consent(post, oid)
            with app.connect() as c:
                now = app.reception_now()
                first = wa.enqueue(c, 'listo', 'prueba-unica', now, order_id=oid)
                self.assertIsNone(wa.enqueue(c, 'listo', 'prueba-unica', now, order_id=oid))  # misma clave: no se duplica
                self.assertTrue(wa._claim(c, first, now))
                self.assertFalse(wa._claim(c, first, now))  # otro proceso no puede tomarlo
                c.commit()
                self.assertEqual(wa.due_ids(c, now + timedelta(minutes=5)), [])
                row = c.execute('SELECT status,reason_kind,permanent FROM whatsapp_outbox WHERE id=?', (first,)).fetchone()
            self.assertEqual(tuple(row), ('fallido', 'incierto', 1))
            self.assertEqual(self.meta.sends(), [])

    def test_webhook_signed_states_never_go_back_and_opt_out(self):
        cookie, csrf, post = self.session()
        with patch.dict(app.os.environ, FAKE):
            self.enable(post)
            oid = self.order(post, 'webhook')
            self.consent(post, oid)
            sent = next(i for i in post('/api/orders/%d/whatsapp/send' % oid, event='listo')['body']['items'] if i['event'] == 'listo')
            with app.connect() as c:
                provider = c.execute('SELECT provider_id FROM whatsapp_outbox WHERE id=?', (sent['id'],)).fetchone()[0]

            def hook(status=None, text=None):
                value = {'statuses': [{'id': provider, 'status': status}]} if status else {'messages': [{'from': '593991234567', 'type': 'text', 'text': {'body': text}}]}
                raw = json.dumps({'entry': [{'changes': [{'field': 'messages', 'value': value}]}]}).encode()
                return raw, 'sha256=' + hmac.new(FAKE['WHATSAPP_APP_SECRET'].encode(), raw, hashlib.sha256).hexdigest()

            def deliver(raw, sign):
                from email.message import Message
                h = object.__new__(app.Handler)
                h.path = '/api/public/whatsapp/webhook'
                h.client_address = ('127.0.0.1', 1)
                h.headers = Message()
                h.headers['Content-Length'] = str(len(raw))
                h.headers['X-Hub-Signature-256'] = sign
                import io
                h.rfile = io.BytesIO(raw)
                out = {}
                h.reply = lambda status, body, *a, **k: out.update(status=status, body=body)
                h.do_POST()
                return out['status']

            def state():
                with app.connect() as c:
                    return c.execute('SELECT o.status,m.status FROM whatsapp_outbox o JOIN order_messages m ON m.id=o.message_id WHERE o.id=?', (sent['id'],)).fetchone()

            raw, sign = hook('delivered')
            self.assertEqual(deliver(raw, 'sha256=firma-falsa'), 403)
            self.assertEqual(tuple(state()), ('enviado', 'enviado'))
            self.assertEqual(deliver(raw, sign), 200)
            self.assertEqual(tuple(state()), ('entregado', 'entregado'))
            self.assertEqual(deliver(*hook('read')), 200)
            self.assertEqual(tuple(state()), ('leido', 'leido'))
            for back in ('delivered', 'sent', 'failed'):
                deliver(*hook(back))
            self.assertEqual(tuple(state()), ('leido', 'leido'))  # nunca retrocede
            self.assertEqual(deliver(*hook(text='BAJA')), 200)
            data = self.request('/api/orders/%d/whatsapp' % oid, cookie=cookie)['body']
            self.assertEqual((data['consent']['state'], data['consent']['source']), ('rechazado', 'baja'))
            self.follow(post, oid, 'diagnostico')
            last = self.outbox(oid)[-1]
            self.assertEqual((last['event'], last['status'], last['reason_kind']), ('diagnostico', 'omitido', 'consentimiento'))
            overview = self.request('/api/whatsapp', cookie=cookie)['body']['webhook']
            self.assertTrue(overview['last_event'])
            self.assertEqual(overview['rejected']['count'], 1)
            # Verificación del webhook (GET): solo con el token correcto.
            self.assertEqual(wa.verify({'hub.mode': 'subscribe', 'hub.verify_token': FAKE['WHATSAPP_VERIFY_TOKEN'], 'hub.challenge': '12345'}), '12345')
            self.assertIsNone(wa.verify({'hub.mode': 'subscribe', 'hub.verify_token': 'otro', 'hub.challenge': '12345'}))

    def test_test_send_goes_only_to_authorized_number(self):
        cookie, csrf, post = self.session()
        with patch.dict(app.os.environ, FAKE):
            self.assertEqual(post('/api/whatsapp/test', confirm=True)['status'], 400)  # sin número autorizado
            self.assertEqual(post('/api/whatsapp/settings', test_number='0987654321')['status'], 200)
            self.assertEqual(post('/api/whatsapp/test')['status'], 400)  # sin confirmación
            got = post('/api/whatsapp/test', confirm=True, recipient='0991234567')  # un número distinto se ignora
            self.assertEqual((got['status'], got['body']['item']['status']), (200, 'enviado'), got['body'])
            payload = self.meta.sends()[0][3]
            self.assertEqual((payload['to'], payload['template']['name'], payload['template']['language']['code']), ('593987654321', 'hello_world', 'en_US'))
            self.assertEqual(post('/api/whatsapp/test', confirm=True)['status'], 429)
            history = self.request('/api/whatsapp/history', cookie=cookie)['body']
            self.assertEqual((history['total'], history['rows'][0]['event'], history['counts']['enviado']), (1, 'prueba', 1))
            self.assertNotIn('593987654321', json.dumps(history))  # el número se muestra enmascarado

    def test_delivery_reminders_once_per_term(self):
        cookie, csrf, post = self.session()
        with patch.dict(app.os.environ, FAKE):
            self.enable(post)
            oid = self.order(post, 'recordatorio')
            self.consent(post, oid)
            now = app.reception_now()
            with app.connect() as c:
                c.execute("UPDATE orders SET status='listo' WHERE id=?", (oid,))
                c.execute("INSERT INTO order_status_log(order_id,from_status,to_status,actor_id,reason,source,detail,created_at) VALUES (?,'pruebas','listo',NULL,'','manual','',?)",
                          (oid, (now - timedelta(days=4)).isoformat()))
                c.commit()
                self.assertEqual(len(wa.reminders(c, now)), 1)
                self.assertEqual(wa.reminders(c, now), [])  # una sola vez por plazo
                self.assertEqual(len(wa.reminders(c, now + timedelta(days=4))), 1)  # plazo de 7 días
                c.execute("UPDATE orders SET status='entregado' WHERE id=?", (oid,))
                c.commit()
                sent = wa.process(c, now + timedelta(days=4, minutes=1))
            self.assertTrue(all(r['status'] == 'omitido' and 'retiro' in r['detail'] for r in sent))  # ya retirado: no se recuerda
            self.assertEqual(self.meta.sends(), [])

    def test_appointments_use_booking_consent_and_respect_opt_out(self):
        with patch.dict(app.os.environ, FAKE), app.connect() as c:
            settings = wa.settings(c)
            settings['general_template'] = 'pcdoctor_aviso'
            info = {'phone': '0991234567', 'name': 'Cliente ficticio', 'ref': 'CITA-0001', 'cuando': '12/11/2026 a las 10:00', 'appointment': {'communications_consent': 0}}
            self.assertEqual(wa.blockers(c, 'cita_confirmada', info, settings)[0], 'consentimiento')
            info['appointment']['communications_consent'] = 1
            self.assertEqual(wa.blockers(c, 'cita_confirmada', info, settings), ('', ''))
            wa.record_consent(c, '0991234567', 'rechazado', 'baja', app.reception_now())
            self.assertEqual(wa.blockers(c, 'cita_confirmada', info, settings)[0], 'consentimiento')
            msg = wa.compose('cita_confirmada', info, settings)
            self.assertEqual(msg['params'][:2], ['Cliente', 'CITA-0001'])
            self.assertIn('12/11/2026', msg['params'][2])


if __name__ == '__main__':
    unittest.main()
