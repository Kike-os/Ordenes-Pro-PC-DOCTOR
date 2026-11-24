"""Atención humana real desde WhatsApp (docs/WHATSAPP-ATENCION.md). Base temporal, datos ficticios y API de Meta SIMULADA: ningún mensaje
real sale ni llega a clientes.

Cubre: «ASESOR» crea una solicitud real con código y deja la conversación con el personal; ADI deja de responder y los mensajes del
cliente se guardan; urgencia (viaje, queja, espera) sube la prioridad o crea la solicitud; mensajes repetidos no duplican la solicitud;
la respuesta del asesor sale por WhatsApp y un fallo de Meta se registra y se informa; aceptar, transferir y cerrar actualizan la
solicitud y avisan al cliente; al cerrar, ADI vuelve a atender; un fallo de la base no produce una confirmación falsa; orden sin
diagnóstico publicado y «SOLICITAR»; la solicitud y la verificación sobreviven a un reinicio; sin la migración 116 nunca se promete
una transferencia; el chat web también registra su solicitud."""
import json
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_whatsapp_identity as ident
import app
import live_support
import whatsapp_adi
import whatsapp_handoff as handoff

TITULAR = ident.TITULAR
STRANGER = ident.STRANGER


class WhatsAppHandoffTests(ident.WhatsAppIdentityTests):
    # Reutiliza la preparación de las pruebas de verificación (Meta simulado, plantilla del código, orden ficticia) sin repetir sus pruebas.
    def run(self, result=None):
        if not self._testMethodName.startswith('test_h'):
            return result
        return super().run(result)

    def conv_id(self, sender=TITULAR):
        with app.connect() as c:
            return c.execute('SELECT conversation_id FROM whatsapp_conversations WHERE wa_number=?', (sender,)).fetchone()[0]

    def case(self, conv):
        with app.connect() as c:
            return c.execute('SELECT * FROM adi_handoffs WHERE conversation_id=? ORDER BY id DESC LIMIT 1', (conv,)).fetchone()

    def live(self, conv, **body):
        return self.request('/api/adi/live/%d' % conv, body, cookie=self.cookie, csrf=self.csrf)

    def texts_to(self, number):
        return [s[3]['text']['body'] for s in self.meta.sends() if s[3].get('type') == 'text' and s[3]['to'] == number]

    # 3 · solicitud real
    def test_h01_asesor_creates_real_request_and_staff_sees_it(self):
        answer = self.say('Quiero hablar con un ASESOR')
        conv = self.conv_id()
        case = self.case(conv)
        self.assertIsNotNone(case)
        self.assertRegex(case['code'], r'^ATN-\d{8}-\d{4}$')
        self.assertEqual(case['status'], 'pendiente')
        self.assertIn(case['code'], answer)                       # se confirma con el código real guardado
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT mode FROM adi_conversations WHERE id=?', (conv,)).fetchone()['mode'], 'human')
            self.assertGreaterEqual(live_support.summary(c)['waiting'], 1)   # aparece en las notificaciones del personal
        rows = self.request('/api/adi/live', cookie=self.cookie)['body']['rows']
        row = next(r for r in rows if r['id'] == conv)
        self.assertEqual((row['channel'], row['case_code']), ('whatsapp', case['code']))

    # 4 · ADI deja de responder con el asesor; 10 · repetidos sin duplicar
    def test_h02_adi_silent_with_advisor_and_messages_kept_without_duplicates(self):
        self.say('ASESOR')
        conv = self.conv_id()
        with patch.object(whatsapp_adi.adi, 'reply') as reply:
            before = len(self.meta.sends())
            self.assertEqual(self.say('¿Me pueden ayudar?'), '')
            self.assertEqual(self.say('ASESOR'), '')
            reply.assert_not_called()
            self.assertEqual(len(self.meta.sends()), before)      # ADI no envía nada mientras atiende el personal
        with app.connect() as c:
            msgs = [r['content'] for r in c.execute("SELECT content FROM adi_messages WHERE conversation_id=? AND author='client'", (conv,))]
            self.assertIn('¿Me pueden ayudar?', msgs)             # el mensaje no se pierde: lo ve el asesor
            self.assertEqual(c.execute("SELECT COUNT(*) FROM adi_handoffs WHERE conversation_id=? AND status IN ('pendiente','asignada')", (conv,)).fetchone()[0], 1)

    # 5 · urgencia por viaje; queja crea la solicitud sola
    def test_h03_urgency_raises_priority_and_complaint_escalates(self):
        self.say('Necesito hablar con una persona')
        conv = self.conv_id()
        self.assertEqual(self.case(conv)['priority'], 'normal')
        self.say('Por favor, tengo que viajar mañana y necesito mi laptop')
        case = self.case(conv)
        self.assertEqual(case['priority'], 'urgente')
        self.assertIn('Viaje', case['signals'])
        # Sin pedir asesor: una queja crea la solicitud urgente.
        answer = self.say('Quiero presentar una queja, pésimo servicio', STRANGER)
        other = self.case(self.conv_id(STRANGER))
        self.assertEqual((other['priority'], other['status']), ('urgente', 'pendiente'))
        self.assertIn('URGENTE', answer)

    # aceptar, responder por WhatsApp, transferir y cerrar; 14 · ADI se reactiva
    def test_h04_advisor_accepts_replies_transfers_closes_and_adi_resumes(self):
        self.say('ASESOR')
        conv = self.conv_id()
        self.assertEqual(self.live(conv, action='takeover')['status'], 200)
        self.assertEqual(self.case(conv)['status'], 'asignada')
        self.assertTrue(any('te atiende' in t for t in self.texts_to(TITULAR)))
        got = self.live(conv, action='reply', message='Hola, revisamos tu caso ahora mismo.')
        self.assertEqual(got['status'], 200, got['body'])
        self.assertEqual(got['body']['whatsapp'], {'sent': True, 'detail': ''})
        self.assertIn('Hola, revisamos tu caso ahora mismo.', self.texts_to(TITULAR))
        with app.connect() as c:
            other = c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('otro','otro@example.invalid','Otra Asesora','x','tecnico',0)").lastrowid
            c.commit()
        self.assertEqual(self.live(conv, action='transfer', user_id=str(other))['status'], 200)
        self.assertEqual(self.case(conv)['accepted_by'], other)
        detail = self.request('/api/adi/live/%d' % conv, cookie=self.cookie)['body']
        self.assertEqual(detail['attention']['channel'], 'whatsapp')
        self.assertEqual(detail['attention']['case']['accepted_by'], 'Otra Asesora')
        self.assertEqual(self.live(conv, action='close')['status'], 200)
        self.assertEqual(self.case(conv)['status'], 'cerrada')
        self.assertTrue(any('terminó' in t for t in self.texts_to(TITULAR)))
        # El siguiente mensaje lo atiende ADI otra vez.
        self.assertEqual(self.say('¿Qué horario tienen?'), 'Respuesta general de ADI.')

    # 9 · fallo de Meta al responder el asesor
    def test_h05_meta_failure_on_advisor_reply_is_recorded_and_reported(self):
        self.say('ASESOR')
        conv = self.conv_id()
        self.meta.replies.append((400, {'error': {'message': 'Re-engagement message', 'code': 131047}}))
        got = self.live(conv, action='reply', message='Mensaje que no llegará')
        self.assertEqual(got['status'], 200)
        self.assertFalse(got['body']['whatsapp']['sent'])
        detail = self.request('/api/adi/live/%d' % conv, cookie=self.cookie)['body']
        failed = [m for m in detail['messages'] if m.get('whatsapp_failed')]
        self.assertEqual([m['content'] for m in failed], ['Mensaje que no llegará'])   # guardado y marcado, no perdido
        self.assertEqual(detail['attention']['failed_sends'], 1)

    # 8 · fallo de la base: nunca una confirmación falsa
    def test_h06_database_failure_never_claims_a_transfer(self):
        with patch.object(handoff, 'request', side_effect=app.sqlite3.OperationalError('database is locked')):
            answer = self.say('ASESOR')
        self.assertIn('No pude registrar', answer)
        self.assertNotIn('ATN-', answer)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM adi_handoffs').fetchone()[0], 0)

    # 6 · orden sin diagnóstico publicado + SOLICITAR
    def test_h07_order_without_published_update_and_update_request(self):
        self.request_code()
        code, _ = self.otp()
        done = self.say(code)
        self.assertIn('Todavía no hay una actualización técnica publicada', done)
        answer = self.say('SOLICITAR', minutes=1)
        self.assertIn('Pedí al técnico una actualización', answer)
        case = self.case(self.conv_id())
        self.assertEqual((case['order_id'], case['reason']), (self.oid, 'Solicitud de actualización técnica'))

    # 13 · reinicio: el estado vive en la base, no en memoria
    def test_h08_state_survives_restart(self):
        self.say('Hola, quiero saber cómo va mi laptop')
        self.say(self.code)
        self.say('Sí')
        code, _ = self.otp()
        import importlib, whatsapp_identity
        importlib.reload(whatsapp_identity); importlib.reload(handoff); importlib.reload(whatsapp_adi)   # «reinicio» del proceso
        whatsapp_adi.adi.reply = lambda *a, **k: 'Respuesta general de ADI.'
        self.assertIn('Identidad verificada', self.say(code))

    # sin la migración 116: nunca se promete una transferencia
    def test_h09_without_migration_never_promises_transfer(self):
        with patch.object(handoff, 'installed', return_value=False), patch.object(whatsapp_adi.adi, 'reply', return_value='Te conecto con un asesor ahora mismo.') as reply:
            answer = self.say('ASESOR')
            reply.assert_not_called()
        self.assertIn('no puedo transferirte', answer)

    def test_h10_web_chat_request_is_registered(self):
        with app.connect() as c:
            conv = c.execute("INSERT INTO adi_conversations(token_hash,mode,created_at,updated_at) VALUES (?,?,?,?)", (app.digest('token-web-ficticio'), 'adi', 'x', 'x')).lastrowid
            c.commit()
        got = self.request('/api/public/adi/human', {}, cookie='pcdoctor_adi=token-web-ficticio')
        self.assertEqual(got['status'], 200, got['body'])
        case = self.case(conv)
        self.assertEqual((case['channel'], case['status']), ('web', 'pendiente'))


    # Límite mensual: ADI no responde, pero el mensaje NO se pierde: queda en la conversación y pasa al personal con prioridad alta.
    def test_h20_monthly_limit_keeps_message_for_staff_without_sending(self):
        with patch.object(whatsapp_adi.wa, 'MAX_MONTHLY_ADI_REPLIES', 0), patch.object(whatsapp_adi.adi, 'reply') as reply:
            before = len(self.meta.sends())
            self.assertEqual(self.say('Hola, ¿mi equipo ya está listo?'), '')
            reply.assert_not_called()
            self.assertEqual(len(self.meta.sends()), before)                          # nada sale a Meta
        conv = self.conv_id()
        case = self.case(conv)
        self.assertEqual((case['status'], case['priority']), ('pendiente', 'alta'))
        self.assertIn('Límite mensual', case['reason'])
        with app.connect() as c:
            self.assertIn('Hola, ¿mi equipo ya está listo?', [r[0] for r in c.execute("SELECT content FROM adi_messages WHERE conversation_id=? AND author='client'", (conv,))])
            inbound = c.execute('SELECT status,conversation_id,detail FROM whatsapp_adi_inbound ORDER BY rowid DESC LIMIT 1').fetchone()
            self.assertEqual((inbound['status'], inbound['conversation_id']), ('omitido', conv))
        rows = self.request('/api/adi/live', cookie=self.cookie)['body']['rows']
        self.assertIn(conv, [r['id'] for r in rows])                                       # el personal lo ve en el panel


if __name__ == '__main__':
    unittest.main()
