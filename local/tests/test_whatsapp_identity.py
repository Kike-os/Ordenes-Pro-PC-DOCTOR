"""Verificación de identidad por WhatsApp antes de que ADI informe sobre una orden (docs/WHATSAPP-IDENTIDAD.md).

Base temporal, datos ficticios y API de Meta SIMULADA: ninguna llamada sale a internet ni llega a clientes. Cubre los 13 escenarios
obligatorios (cliente legítimo, código incorrecto, caducado, reutilizado, fuerza bruta, orden ajena, número no autorizado, cambio de
teléfono, sesión vencida, otra orden con sesión válida, reenvío excesivo, fallo de mensajería y revocación con sesión abierta), que nunca
se guarda el código en texto plano ni llega al historial de la IA, y los permisos del panel de administración.
Criterio de aceptación: ninguna consulta sin autorización revela información privada ni da acceso a una orden distinta de la verificada."""
import hashlib
import hmac
import json
import re
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_whatsapp_business as base
import app
import whatsapp_business as wa
import whatsapp_adi
import whatsapp_identity as identity

FAKE = base.FAKE
ENV = dict(FAKE, WHATSAPP_ADI_AUTO_REPLY='true')
TITULAR = '593991234567'      # 0991234567 del cliente ficticio de las pruebas
STRANGER = '593987650000'     # número que nadie autorizó
PRIVATE = ('Cliente ficticio', '0100000017', '0991234567', 'No enciende', 'cliente@example.invalid')


class WhatsAppIdentityTests(unittest.TestCase):
    Base = base.WhatsAppBusinessTests.Base          # misma base de datos temporal y datos ficticios que las pruebas de WhatsApp
    setUpClass = classmethod(Base.setUpClass.__func__)
    request, login, order_data = Base.request, Base.login, Base.order_data
    session, order = base.WhatsAppBusinessTests.session, base.WhatsAppBusinessTests.order

    def setUp(self):
        base.WhatsAppBusinessTests.setUp(self)
        self.env = patch.dict(app.os.environ, ENV)
        self.env.start()
        self.adi = patch.object(whatsapp_adi.adi, 'reply', return_value='Respuesta general de ADI.')
        self.adi.start()
        self.cookie, self.csrf, self.post = self.session()
        got = self.post('/api/whatsapp/settings', otp_template='pcdoctor_codigo', otp_lang='es')
        self.assertEqual(got['status'], 200, got['body'])
        self.oid = self.order(self.post, 'identidad-%d' % id(self))
        with app.connect() as c:
            self.code = c.execute('SELECT code FROM orders WHERE id=?', (self.oid,)).fetchone()['code']
        self.now = app.reception_now()
        self.seq = 0

    def tearDown(self):
        self.adi.stop()
        self.env.stop()
        base.WhatsAppBusinessTests.tearDown(self)

    # ---- ayudantes ----
    def say(self, text, sender=TITULAR, minutes=0):
        """Mensaje entrante firmado; devuelve la respuesta que ADI envió por WhatsApp (o '' si no envió texto)."""
        self.seq += 1
        payload = {'entry': [{'changes': [{'value': {'messages': [{'id': 'wamid.ID-%d-%d' % (id(self), self.seq), 'from': sender, 'type': 'text', 'text': {'body': text}}]}}]}]}
        raw = json.dumps(payload).encode()
        sign = 'sha256=' + hmac.new(FAKE['WHATSAPP_APP_SECRET'].encode(), raw, hashlib.sha256).hexdigest()
        before = len(self.meta.sends())
        with app.connect() as c:
            whatsapp_adi.handle(c, raw, sign, self.now + timedelta(minutes=minutes), ENV)
        texts = [s[3]['text']['body'] for s in self.meta.sends()[before:] if s[3].get('type') == 'text']
        return texts[-1] if texts else ''

    def otp(self):
        """Último código enviado por la plantilla de autenticación (lo que recibiría el teléfono autorizado) y su destinatario."""
        sent = [s[3] for s in self.meta.sends() if s[3].get('type') == 'template' and s[3]['template']['name'] == 'pcdoctor_codigo']
        self.assertTrue(sent, 'no se envió ningún código')
        return sent[-1]['template']['components'][0]['parameters'][0]['text'], sent[-1]['to']

    def request_code(self, sender=TITULAR, minutes=0):
        self.say('Hola, quiero saber cómo va mi laptop', sender, minutes)
        offer = self.say(self.code, sender, minutes)
        self.assertIn('••67', offer)
        sent = self.say('Sí', sender, minutes)
        self.assertIn('código de seguridad de 6 dígitos', sent)
        return sent

    def assertPrivate(self, text):
        for item in PRIVATE + ('Portátil', 'Estado:', 'Equipo:', 'Observaciones', 'Entrega estimada'):
            self.assertNotIn(item, text, 'se reveló «%s»' % item)

    # ---- 1. cliente legítimo ----
    def test_01_legitimate_client_with_correct_code(self):
        first = self.say('Hola, quiero saber cómo va mi laptop')
        self.assertIn('número de orden', first)
        self.assertPrivate(first)
        offer = self.say(self.code)
        self.assertIn('termina en ••67', offer)
        self.assertPrivate(offer)
        self.request_code()
        code, to = self.otp()
        self.assertTrue(re.fullmatch(r'\d{6}', code))
        self.assertEqual(to, TITULAR)
        done = self.say(code)
        self.assertIn('Identidad verificada correctamente', done)
        self.assertIn('Estado:', done)
        self.assertIn(self.code, done)
        self.assertNotIn('0100000017', done)   # ni siquiera verificado se envía la cédula
        # Seguir preguntando por la orden dentro de la sesión responde sin pedir otro código.
        again = self.say('¿Ya está lista mi laptop?', minutes=5)
        self.assertIn('Estado:', again)

    def test_02_code_never_stored_in_plain_text_or_sent_to_ai_history(self):
        self.request_code()
        code, _ = self.otp()
        self.say(code)
        with app.connect() as c:
            stored = [r['code_hash'] for r in c.execute('SELECT code_hash FROM wa_identity_challenges')]
            history = ' '.join(r['content'] for r in c.execute('SELECT content FROM adi_messages'))
            events = ' '.join(r['detail'] for r in c.execute('SELECT detail FROM wa_identity_events'))
        self.assertTrue(stored and all(len(h) == 64 and h != code for h in stored))
        self.assertNotIn(code, history)
        self.assertNotIn(code, events)
        self.assertIn('[código de verificación]', history)
        self.assertNotIn('Estado:', history)   # los datos de la orden no quedan en el historial que viaja a la IA

    # ---- 2. código incorrecto · 5. fuerza bruta ----
    def test_03_wrong_code_and_brute_force_lock(self):
        self.request_code()
        code, _ = self.otp()
        wrong = '%06d' % ((int(code) + 1) % 1000000)
        self.assertIn('Te quedan 2 intentos', self.say(wrong))
        self.assertIn('Te queda 1 intento', self.say(wrong))
        locked = self.say(wrong)
        self.assertIn('Superaste el número de intentos', locked)
        self.assertPrivate(locked)
        # Ni el código correcto sirve ya.
        after = self.say(code)
        self.assertNotIn('Identidad verificada', after)
        self.assertPrivate(after)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM wa_identity_challenges ORDER BY id DESC LIMIT 1').fetchone()['status'], 'bloqueado')
        data = self.request('/api/orders/%d/identity' % self.oid, cookie=self.cookie)['body']
        self.assertTrue(any(a['kind'] == 'codigo_bloqueado' for a in data['alerts']))

    # ---- 3. código caducado ----
    def test_04_expired_code(self):
        self.request_code()
        code, _ = self.otp()
        late = self.say(code, minutes=identity.CODE_MINUTES + 1)
        self.assertIn('ya no es válido', late)
        self.assertPrivate(late)

    # ---- 4. reutilización ----
    def test_05_consumed_code_cannot_be_reused(self):
        self.request_code()
        code, _ = self.otp()
        self.assertIn('Identidad verificada', self.say(code))
        self.say('CANCELAR')   # cierra la sesión
        # Nueva verificación: el código anterior no sirve.
        self.request_code(minutes=2)
        reused = self.say(code, minutes=2)
        new_code, _ = self.otp()
        if new_code != code:
            self.assertNotIn('Identidad verificada', reused)
            self.assertPrivate(reused)

    # ---- 6. orden ajena · 7. número no autorizado ----
    def test_06_foreign_order_from_unauthorized_number_reveals_nothing(self):
        first = self.say('Hola, quiero saber cómo va mi laptop ' + self.code, STRANGER)
        self.assertPrivate(first)
        self.assertIn('••67', first)                 # solo los dos últimos dígitos del teléfono autorizado
        self.assertNotIn('0991234567', first)
        sent = self.say('Sí', STRANGER)
        self.assertIn('no a este chat', sent)        # el código va al teléfono autorizado, no al que pregunta
        _, to = self.otp()
        self.assertEqual(to, TITULAR)
        self.assertNotIn(STRANGER, [s[3]['to'] for s in self.meta.sends() if s[3].get('type') == 'template'])
        # Adivinar no funciona y no revela nada.
        for guess in ('000000', '111111', '222222'):
            self.assertPrivate(self.say(guess, STRANGER))
        # Un número de orden inexistente da la misma respuesta genérica que una orden sin teléfono autorizado.
        missing = self.say('PCD-20990101-9999', STRANGER)
        self.assertIn('no puedo verificar esa orden', missing)

    # ---- 8. cambio de teléfono registrado ----
    def test_07_phone_change_invalidates_session_and_pending_code(self):
        self.request_code()
        code, _ = self.otp()
        self.assertIn('Identidad verificada', self.say(code))
        with app.connect() as c:
            c.execute("UPDATE clients SET phone='0981112233' WHERE id=(SELECT d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?)", (self.oid,))
            c.commit()
        after = self.say('¿Cómo va mi laptop?', minutes=1)
        self.assertNotIn('Estado:', after)
        self.assertNotIn('Identidad verificada', after)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT end_reason FROM wa_identity_sessions ORDER BY id DESC LIMIT 1').fetchone()['end_reason'], 'contactos_modificados')
        # ADI nunca cambia el teléfono: solo registra la solicitud para revisión humana.
        recovery = self.say('Cambié de número, ¿pueden actualizarlo?', STRANGER)
        self.assertIn('no puedo cambiar el teléfono', recovery)
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT phone FROM clients WHERE identification='0100000017'").fetchone()['phone'], '0981112233')

    # ---- 9. sesión vencida ----
    def test_08_expired_session(self):
        self.request_code()
        code, _ = self.otp()
        self.say(code)
        late = self.say('¿Cómo va mi laptop?', minutes=identity.IDLE_MINUTES + 1)
        self.assertNotIn('Estado:', late)
        self.assertIn('número de orden', late)

    # ---- 10. otra orden durante una sesión válida ----
    def test_09_other_order_during_valid_session(self):
        other = self.order(self.post, 'identidad-otra-%d' % id(self))
        with app.connect() as c:
            other_code = c.execute('SELECT code FROM orders WHERE id=?', (other,)).fetchone()['code']
        self.request_code()
        code, _ = self.otp()
        self.assertIn('Identidad verificada', self.say(code))
        answer = self.say('¿Y la orden ' + other_code + '?', minutes=1)
        self.assertNotIn('Estado:', answer)
        self.assertNotIn(other_code + '\nEstado', answer)
        self.assertIn('Podemos enviar un código', answer)   # exige verificar esa otra orden por separado

    # ---- 11. reenvío excesivo ----
    def test_10_excessive_resend(self):
        self.request_code()
        self.say('REENVIAR')
        self.say('REENVIAR')
        limited = self.say('REENVIAR')
        self.assertIn('Espera un momento', limited)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM wa_identity_challenges').fetchone()[0], identity.CODES_PER_HOUR_CONVERSATION)
        # Recorrer números de orden también tiene límite.
        for n in range(identity.LOOKUPS_PER_HOUR + 1):
            last = self.say('PCD-20990101-%04d' % n, STRANGER)
        self.assertIn('límite de consultas', last)

    # ---- 12. fallo del servicio de mensajería ----
    def test_11_messaging_failure(self):
        self.say('Hola, quiero saber cómo va mi laptop')
        self.say(self.code)
        self.meta.replies.append((503, {'error': {'message': 'Servicio no disponible', 'code': 2}}))
        failed = self.say('Sí')
        self.assertIn('No pudimos enviar el código', failed)
        self.assertPrivate(failed)
        with app.connect() as c:
            row = c.execute('SELECT status FROM wa_identity_challenges ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual(row['status'], 'envio_fallido')
        # Sin plantilla configurada tampoco se envía nada (y tampoco se revela nada).
        self.post('/api/whatsapp/settings', otp_template='')
        self.say(self.code, minutes=1)
        self.assertIn('No pudimos enviar el código', self.say('Sí', minutes=1))

    # ---- 13. revocación con sesión abierta ----
    def test_12_revocation_with_open_session(self):
        self.request_code()
        code, _ = self.otp()
        self.say(code)
        got = self.post('/api/orders/%d/identity/revoke' % self.oid)
        self.assertEqual(got['status'], 200, got['body'])
        self.assertFalse(any(s['active'] for s in got['body']['sessions']))
        after = self.say('¿Cómo va mi laptop?', minutes=1)
        self.assertNotIn('Estado:', after)

    # ---- contactos autorizados y permisos del panel ----
    def test_13_authorized_contact_flow_and_admin_permissions(self):
        bad = self.post('/api/orders/%d/identity/contacts' % self.oid, name='Persona Autorizada', phone='0987650000', relation='Hija', evidence='')
        self.assertEqual(bad['status'], 400)
        self.assertIn('evidence', bad['body']['fields'])
        self.assertIn('confirm', bad['body']['fields'])
        ok = self.post('/api/orders/%d/identity/contacts' % self.oid, name='Persona Autorizada', phone='0987650000', relation='Hija',
                       evidence='Carta firmada por el titular y cédula presentadas en el local', confirm=True)
        self.assertEqual(ok['status'], 200, ok['body'])
        contact = ok['body']['contacts'][0]
        self.assertEqual(contact['tail'], '00')
        self.assertNotIn('0987650000', json.dumps(ok['body']))   # el panel muestra solo los dos últimos dígitos
        # El contacto autorizado recibe el código en su propio número.
        self.say('Hola, quiero saber cómo va mi laptop', STRANGER)
        self.assertIn('••00', self.say(self.code, STRANGER))
        self.say('Sí', STRANGER)
        code, to = self.otp()
        self.assertEqual(to, STRANGER)
        self.assertIn('Identidad verificada', self.say(code, STRANGER))
        # Revocarlo cierra su sesión.
        rev = self.post('/api/orders/%d/identity/contacts/%d/revoke' % (self.oid, contact['id']), reason='El titular retiró la autorización')
        self.assertEqual(rev['status'], 200, rev['body'])
        self.assertNotIn('Estado:', self.say('¿Cómo va mi laptop?', STRANGER, minutes=1))
        kinds = [e['kind'] for e in rev['body']['audit']]
        self.assertIn('contacto_agregado', kinds)
        self.assertIn('contacto_revocado', kinds)
        # Un técnico no puede ver ni cambiar la verificación.
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico'")
            c.commit()
        cookie, csrf = self.login()
        self.assertEqual(self.request('/api/orders/%d/identity' % self.oid, cookie=cookie)['status'], 403)
        self.assertEqual(self.request('/api/orders/%d/identity/revoke' % self.oid, {}, cookie=cookie, csrf=csrf)['status'], 403)

    def test_14_unrelated_questions_still_go_to_adi_and_no_real_messages(self):
        self.assertEqual(self.say('¿Qué horario tienen?'), 'Respuesta general de ADI.')
        self.assertEqual(self.say('¿Cuánto cuesta reparar mi equipo?'), 'Respuesta general de ADI.')   # «mi equipo» solo no activa la verificación
        for call in self.meta.calls:
            self.assertTrue(call[1].startswith('https://graph.facebook.com/'))   # solo la API simulada

    def test_15_missing_migration_keeps_whatsapp_working_and_reveals_nothing(self):
        # Producción: Vercel no ejecuta migraciones. Sin las tablas de la 115 los envíos de WhatsApp siguen funcionando, ADI responde lo
        # demás con normalidad y las consultas de órdenes no revelan nada. Las tablas se eliminan dentro de una transacción que se deshace.
        user = {'id': 1, 'role': 'administrador'}
        with app.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            for table in ('wa_identity_state', 'wa_identity_sessions', 'wa_identity_challenges', 'wa_identity_events', 'order_authorized_contacts'):
                c.execute('DROP TABLE ' + table)
            try:
                self.assertFalse(identity.installed(c))
                self.assertIsInstance(wa.monthly_outbound_count(c, self.now), int)
                self.assertIsNone(identity.respond(c, 'conv-sin-migracion', TITULAR, '¿Qué horario tienen?', self.now, ENV))
                for text in ('¿Cómo va mi laptop?', self.code):
                    turn = identity.respond(c, 'conv-sin-migracion', TITULAR, text, self.now, ENV)
                    self.assertEqual(turn['answer'], identity.DENIED)
                    self.assertPrivate(turn['answer'])
                with self.assertRaises(identity.IdentityError) as caught:
                    identity.overview(c, self.oid, user, self.now, ENV)
                self.assertEqual(caught.exception.status, 503)
            finally:
                c.rollback()
        with app.connect() as c:
            self.assertTrue(identity.installed(c))


if __name__ == '__main__':
    unittest.main()
