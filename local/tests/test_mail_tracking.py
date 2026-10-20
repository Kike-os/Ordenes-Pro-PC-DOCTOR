"""Seguimiento de entregas de Mail Pro: estados reales por destinatario, informes de entrega, duplicados, orden de llegada,
reenvío corregido y alertas. Datos ficticios, base temporal y ningún correo real (el servidor SMTP está simulado)."""
import email
import json
import smtplib
import unittest
from datetime import timedelta
from email import policy
from unittest.mock import patch

import test_app
import app
import mail_pro
import mail_tracking
import notifications

ENV = {'MAIL_IMAP_HOST': 'mail.example.invalid', 'MAIL_IMAP_PORT': '993', 'MAIL_SMTP_HOST': 'mail.example.invalid', 'MAIL_SMTP_PORT': '465',
       'MAIL_USERNAME': 'buzon@example.invalid', 'MAIL_PASSWORD': 'secreto-ficticio-123'}


def dsn(action, status, recipient, original, date=None, diagnostic='smtp; 550 5.1.1 User unknown'):
    if date is None:
        from email.utils import format_datetime
        date = format_datetime(app.reception_now() + timedelta(minutes=2))
    raw = ('From: Mail Delivery System <MAILER-DAEMON@example.invalid>\r\nTo: buzon@example.invalid\r\nDate: ' + date + '\r\nSubject: Aviso\r\nMIME-Version: 1.0\r\n'
           'Content-Type: multipart/report; report-type=delivery-status; boundary="b1"\r\n\r\n--b1\r\nContent-Type: text/plain\r\n\r\nInforme.\r\n'
           '--b1\r\nContent-Type: message/delivery-status\r\n\r\nReporting-MTA: dns; mx.example.invalid\r\n\r\nFinal-Recipient: rfc822; ' + recipient + '\r\nAction: ' + action +
           '\r\nStatus: ' + status + '\r\nDiagnostic-Code: ' + diagnostic + '\r\n\r\n--b1\r\nContent-Type: text/rfc822-headers\r\n\r\nMessage-ID: ' + original + '\r\nSubject: Presupuesto\r\n\r\n--b1--\r\n')
    return mail_pro.parse_bounce(email.message_from_string(raw, policy=policy.default))


class FakeSMTP:
    """Servidor SMTP simulado: sin DSN, acepta todo salvo las direcciones de `refuse` (código, texto)."""
    sent = []
    refuse = {}

    def __init__(self, *a, **k):
        pass

    def login(self, *a):
        pass

    def has_extn(self, name):
        return False

    def send_message(self, message, from_addr=None, to_addrs=None, **options):
        bad = {address: FakeSMTP.refuse[address] for address in to_addrs if address in FakeSMTP.refuse}
        if bad and len(bad) == len(to_addrs):
            raise smtplib.SMTPRecipientsRefused(bad)
        FakeSMTP.sent.append((message, [address for address in to_addrs if address not in bad], options))
        return bad

    def quit(self):
        pass


class TrackingTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        FakeSMTP.sent, FakeSMTP.refuse = [], {}
        self.smtp = patch.object(mail_pro, 'smtp_client', side_effect=lambda config: FakeSMTP())
        self.smtp.start()
        self.envs = patch.dict(app.os.environ, ENV)
        self.envs.start()
        self.now = app.reception_now()

    def tearDown(self):
        self.envs.stop()
        self.smtp.stop()
        test_app.SecurityTests.tearDown(self)

    def institutional(self, recipient, kind='quote', actor=None):
        with app.connect() as c:
            try:
                return app.send_institutional(c, kind, 'Presupuesto', recipient, 'Presupuesto de prueba', 'Hola:\n\nTexto ficticio de prueba.', None, actor, review=False)
            except mail_pro.MailError as error:
                return error

    def row(self, recipient):
        with app.connect() as c:
            return dict(c.execute('SELECT * FROM mail_deliveries WHERE recipient=? ORDER BY id DESC LIMIT 1', (recipient,)).fetchone())

    def events(self, delivery):
        with app.connect() as c:
            return [dict(e) for e in c.execute('SELECT * FROM mail_delivery_events WHERE delivery_id=? ORDER BY occurred_at,id', (delivery,))]

    def report(self, item, base):
        with app.connect() as c:
            return mail_tracking.from_report(c, item, base, app.reception_now())

    def test_01_accepted_mail_is_sent_never_delivered_without_a_report(self):
        sent = self.institutional('cliente1@example.invalid')
        row = self.row('cliente1@example.invalid')
        self.assertEqual((row['status'], row['message_id'], row['kind'], row['archive_id']), ('enviado', sent['message_id'], 'quote', sent['archive_id']))
        self.assertEqual([e['event'] for e in self.events(row['id'])], ['creado', 'cola', 'conectando', 'autenticado', 'transmitiendo', 'aceptado', 'resultado'])  # Creado → En cola → Conectando SMTP → Autenticado → Aceptado → Resultado final
        self.assertIn('no emite confirmaciones de entrega final', self.events(row['id'])[-1]['detail'])
        # Sin DSN anunciado no se piden informes al servidor.
        self.assertEqual(FakeSMTP.sent[0][2], {})

    def test_02_delivery_only_from_a_real_report_and_dsn_is_requested_when_offered(self):
        sent = self.institutional('cliente2@example.invalid')
        self.report(dsn('delivered', '2.0.0', 'cliente2@example.invalid', sent['message_id'], diagnostic='smtp; 250 OK'), 'dsn:1:10')
        self.assertEqual(self.row('cliente2@example.invalid')['status'], 'entregado')
        with patch.object(FakeSMTP, 'has_extn', lambda self, name: name == 'dsn'):
            self.institutional('cliente2b@example.invalid')
        self.assertEqual(FakeSMTP.sent[-1][2], {'mail_options': ['RET=HDRS'], 'rcpt_options': ['NOTIFY=SUCCESS,FAILURE,DELAY']})

    def test_03_badly_formatted_address_is_rejected_before_sending(self):
        with self.assertRaises(mail_pro.MailError):
            mail_pro.clean_addresses('cliente@ejemplo')
        cookie, csrf = self.login()
        sent = self.institutional('valida@example.invalid')
        bad = self.request('/api/mail/deliveries/resend', {'id': str(self.row('valida@example.invalid')['id']), 'recipient': 'no es correo', 'confirm': True}, cookie=cookie, csrf=csrf)
        self.assertEqual(bad['status'], 400)
        self.assertTrue(sent)

    def test_04_unknown_address_bounces_and_automatic_sends_stop_there(self):
        FakeSMTP.refuse = {'nadie@example.invalid': (550, b'5.1.1 <nadie@example.invalid>: Recipient address rejected: User unknown')}
        error = self.institutional('nadie@example.invalid')
        self.assertIsInstance(error, mail_pro.MailError)
        row = self.row('nadie@example.invalid')
        self.assertEqual((row['status'], row['code'], row['permanent'], row['reason']), ('rebotado', '5.1.1', 1, 'La dirección no existe en el servidor de destino.'))
        FakeSMTP.refuse = {}
        sent_before = len(FakeSMTP.sent)
        again = self.institutional('nadie@example.invalid')
        self.assertIsInstance(again, mail_pro.MailError)
        self.assertIn('rechazada de forma permanente', str(again))
        self.assertEqual(len(FakeSMTP.sent), sent_before)
        # Un envío hecho por una persona sí se permite (decisión consciente).
        self.assertNotIsInstance(self.institutional('nadie@example.invalid', actor=self.uid), mail_pro.MailError)

    def test_05_full_mailbox_bounces_but_does_not_invalidate_the_address(self):
        sent = self.institutional('lleno@example.invalid')
        self.report(dsn('failed', '5.2.2', 'lleno@example.invalid', sent['message_id'], diagnostic='smtp; 552 5.2.2 Mailbox full'), 'dsn:1:20')
        row = self.row('lleno@example.invalid')
        self.assertEqual((row['status'], row['permanent'], row['reason']), ('rebotado', 0, 'El buzón del destinatario está lleno.'))
        with app.connect() as c:
            self.assertEqual(mail_tracking.blocked(c, 'lleno@example.invalid'), '')

    def test_06_missing_domain_is_a_permanent_bounce(self):
        sent = self.institutional('alguien@dominio-inexistente.invalid')
        self.report(dsn('failed', '5.1.2', 'alguien@dominio-inexistente.invalid', sent['message_id'], diagnostic='smtp; 550 5.1.2 Host unknown'), 'dsn:1:30')
        row = self.row('alguien@dominio-inexistente.invalid')
        self.assertEqual((row['status'], row['permanent'], row['reason']), ('rebotado', 1, 'El dominio del destinatario no existe.'))

    def test_07_temporary_delay_then_final_bounce(self):
        sent = self.institutional('lento@example.invalid')
        from email.utils import format_datetime
        self.report(dsn('delayed', '4.4.1', 'lento@example.invalid', sent['message_id'], date=format_datetime(app.reception_now() + timedelta(hours=1)), diagnostic='smtp; 451 timeout'), 'dsn:1:40')
        self.assertEqual(self.row('lento@example.invalid')['status'], 'demorado')
        self.report(dsn('failed', '4.4.7', 'lento@example.invalid', sent['message_id'], date=format_datetime(app.reception_now() + timedelta(days=2)), diagnostic='smtp; retry timeout exceeded'), 'dsn:1:41')
        row = self.row('lento@example.invalid')
        self.assertEqual((row['status'], row['reason']), ('rebotado', 'La entrega se retrasó demasiado.'))

    def test_08_provider_failure_is_failed_with_its_reason(self):
        with patch.object(FakeSMTP, 'login', side_effect=smtplib.SMTPAuthenticationError(535, b'bad')):
            error = self.institutional('cliente8@example.invalid')
        row = self.row('cliente8@example.invalid')
        self.assertEqual((row['status'], row['code']), ('fallido', 'credenciales'))
        self.assertIn('usuario o la contraseña', row['reason'])
        self.assertNotIn('secreto', json.dumps(row))
        self.assertIsInstance(error, mail_pro.MailError)

    def test_09_each_recipient_keeps_its_own_state(self):
        FakeSMTP.refuse = {'mala@example.invalid': (550, b'5.1.1 User unknown')}
        cookie, csrf = self.login()
        with patch.object(mail_pro, 'open_imap', side_effect=mail_pro.MailError('red', 'sin red')):
            reply = self.request('/api/mail/send', {'to': 'buena@example.invalid, mala@example.invalid', 'cc': '', 'subject': 'Asunto ficticio', 'body': 'Texto', 'attachments': '[]', 'request_key': 'tracking-multi-000001'}, cookie=cookie, csrf=csrf)
        self.assertEqual(reply['status'], 201)
        self.assertEqual(reply['body']['refused'], ['mala@example.invalid'])
        self.assertEqual((self.row('buena@example.invalid')['status'], self.row('mala@example.invalid')['status']), ('enviado', 'rebotado'))
        listed = self.request('/api/mail/deliveries?status=rebotados', cookie=cookie)['body']
        self.assertEqual([r['recipient'] for r in listed['rows']], ['mala@example.invalid'])
        self.assertEqual(listed['counts']['enviados'], 1)

    def test_10_duplicate_report_is_ignored(self):
        sent = self.institutional('dup@example.invalid')
        item = dsn('failed', '5.1.1', 'dup@example.invalid', sent['message_id'])
        self.report(item, 'dsn:1:50')
        self.report(item, 'dsn:1:50')
        self.assertEqual([e['event'] for e in self.events(self.row('dup@example.invalid')['id'])], ['creado', 'cola', 'conectando', 'autenticado', 'transmitiendo', 'aceptado', 'resultado', 'rebote'])

    def test_11_out_of_order_report_never_moves_the_state_back(self):
        sent = self.institutional('orden@example.invalid')
        from email.utils import format_datetime
        later, earlier = format_datetime(app.reception_now() + timedelta(days=2)), format_datetime(app.reception_now() + timedelta(days=1))
        self.report(dsn('failed', '5.1.1', 'orden@example.invalid', sent['message_id'], date=later), 'dsn:1:61')
        self.report(dsn('delayed', '4.4.1', 'orden@example.invalid', sent['message_id'], date=earlier, diagnostic='smtp; 451 later'), 'dsn:1:60')
        row = self.row('orden@example.invalid')
        self.assertEqual(row['status'], 'rebotado')
        self.assertEqual([e['event'] for e in self.events(row['id'])], ['creado', 'cola', 'conectando', 'autenticado', 'transmitiendo', 'aceptado', 'resultado', 'demora', 'rebote'])

    def test_12_correct_and_resend_creates_a_linked_attempt_and_keeps_the_original(self):
        FakeSMTP.refuse = {'error@example.invalid': (550, b'5.1.1 User unknown')}
        self.institutional('error@example.invalid')
        original = self.row('error@example.invalid')
        cookie, csrf = self.login()
        self.assertEqual(self.request('/api/mail/deliveries/resend', {'id': str(original['id']), 'recipient': 'correcta@example.invalid'}, cookie=cookie, csrf=csrf)['status'], 400)
        reply = self.request('/api/mail/deliveries/resend', {'id': str(original['id']), 'recipient': 'correcta@example.invalid', 'confirm': True}, cookie=cookie, csrf=csrf)
        self.assertEqual((reply['status'], reply['body']['ok'], reply['body']['status']), (200, True, 'enviado'))
        fresh = self.row('correcta@example.invalid')
        self.assertEqual((fresh['retry_of'], fresh['kind'], fresh['actor_id']), (original['id'], 'quote', self.uid))
        self.assertEqual(FakeSMTP.sent[-1][1], ['correcta@example.invalid'])
        self.assertIn('Texto ficticio de prueba.', FakeSMTP.sent[-1][0].get_body(('plain',)).get_content())
        kept = self.row('error@example.invalid')
        self.assertEqual((kept['status'], kept['code'], kept['reason']), ('rebotado', '5.1.1', original['reason']))
        self.assertTrue(kept['resolved_at'])
        detail = self.request('/api/mail/deliveries/' + str(original['id']), cookie=cookie)['body']['delivery']
        self.assertEqual([a['recipient'] for a in detail['attempts']], ['error@example.invalid', 'correcta@example.invalid'])
        self.assertEqual(detail['events'][-1]['event'], 'reenvio')
        # Las direcciones declaradas inválidas no se aceptan como corrección; el historial no se edita ni se borra.
        again = self.request('/api/mail/deliveries/resend', {'id': str(fresh['id']), 'recipient': 'error@example.invalid', 'confirm': True}, cookie=cookie, csrf=csrf)
        self.assertEqual(again['status'], 409)
        with app.connect() as c:
            with self.assertRaises(Exception):
                c.execute('DELETE FROM mail_delivery_events WHERE delivery_id=?', (original['id'],))
        with app.connect() as c:
            with self.assertRaises(Exception):
                c.execute("UPDATE mail_deliveries SET recipient='otra@example.invalid' WHERE id=?", (original['id'],))

    def test_13_without_any_response_the_state_is_unknown(self):
        with app.connect() as c:
            ids = mail_tracking.start(c, ['silencio@example.invalid'], kind='quote', subject='Sin respuesta', now=self.now - timedelta(hours=1))
            mail_tracking.sweep(c, self.now)
        row = self.row('silencio@example.invalid')
        self.assertEqual((row['status'], row['reason']), ('desconocido', 'Servidor SMTP no devolvió confirmación registrada (el envío se interrumpió).'))
        self.assertTrue(ids)

    def test_15_appointment_and_order_mails_are_tracked_and_access_is_restricted(self):
        self.assertEqual(self.request('/api/mail/deliveries')['status'], 401)
        cookie, csrf = self.login()
        order = self.request('/api/orders', self.order_data({'email': 'orden@example.invalid', 'request_key': 'tracking-order-request-01'}), cookie=cookie, csrf=csrf)['body']
        with app.connect() as c:
            app.send_institutional(c, 'receipt', 'Comprobante', 'orden@example.invalid', 'Comprobante ' + order['code'], 'Hola:\n\nTexto.', order['id'], self.uid, review=False)
            self.assertEqual(c.execute("SELECT order_id FROM mail_deliveries WHERE kind='receipt'").fetchone()[0], order['id'])
        listed = self.request('/api/mail/deliveries?q=orden@', cookie=cookie)['body']
        self.assertEqual({r['kind'] for r in listed['rows']}, {'receipt'})
        self.assertEqual(listed['rows'][0]['order_code'], order['code'])
        self.assertEqual(listed['provider']['delivery_confirmations'], False)
        import appointment_mail
        self.assertIn("mail_tracking.start(c,[email],kind='appointment'", __import__('pathlib').Path(appointment_mail.__file__).read_text())

    def test_16_alerts_are_deduplicated_configurable_and_summarised(self):
        FakeSMTP.refuse = {'presu@example.invalid': (550, b'5.1.1 User unknown')}
        self.institutional('presu@example.invalid', kind='quote')
        with app.connect() as c:
            items = mail_tracking.alerts(c, app.reception_now())
            keys = [i['key'] for i in items]
            self.assertEqual(len(keys), len(set(keys)))
            first = next(i for i in items if i['key'].endswith(':rebotado'))
            self.assertTrue(first['title'].startswith('Presupuesto no entregado'))
            self.assertIn('No se pudo entregar el correo. Revisa la dirección del destinatario.', first['detail'])
            self.assertTrue(any(i['key'].startswith('maildelivery:summary:') for i in items))
            mail_tracking.save_settings(c, {'quote': False, 'appointment': True, 'ready': True, 'permanent': True, 'provider': True})
            self.assertFalse([i for i in mail_tracking.alerts(c, app.reception_now()) if 'presu@' in i['title']])
        # Fallos repetidos del proveedor: un solo aviso por hora.
        with patch.object(FakeSMTP, 'login', side_effect=OSError('sin red')):
            for n in range(3):
                self.institutional('p%d@example.invalid' % n, kind='receipt')
        with app.connect() as c:
            provider = [i for i in mail_tracking.alerts(c, app.reception_now()) if i['key'].startswith('maildelivery:provider:')]
        self.assertEqual(len(provider), 1)

    def test_17_resend_is_refused_when_content_cannot_be_rebuilt(self):
        with app.connect() as c:
            archive = c.execute("INSERT INTO mail_archive(kind,recipient,subject,body_text,body_html,attachments,created_at) VALUES ('receipt','x@example.invalid','Asunto','Texto','<p>Texto</p>','comprobante.pdf',?)", (self.now.isoformat(),)).lastrowid
            ids = mail_tracking.start(c, ['x@example.invalid'], kind='receipt', subject='Asunto', now=self.now, archive_id=archive)
            mail_tracking.failed(c, ids, mail_pro.MailError('red', 'sin red'), self.now)
            row = c.execute('SELECT * FROM mail_deliveries WHERE id=?', (ids['x@example.invalid'],)).fetchone()
            check = mail_tracking.resend_check(c, row)
        self.assertFalse(check['allowed'])
        self.assertIn('adjuntos', check['reason'])


class DeliveryCenterTests(TrackingTests):
    """Centro de Entrega: etapas exactas, reintento seguro, «sin confirmación» como Incidencia, barrido sin estados eternos y contadores."""
    locals().update({name: None for name in dir(TrackingTests) if name.startswith('test_')})

    def test_connection_retry_is_safe_and_traced(self):
        calls = []
        def client(config):
            calls.append(1)
            if len(calls) == 1:
                raise ConnectionResetError('red cortada')
            return FakeSMTP()
        with patch.object(mail_pro, 'smtp_client', side_effect=client), patch.object(mail_pro, 'RETRY_WAIT', 0):
            self.institutional('reintento@example.invalid')
        row = self.row('reintento@example.invalid')
        self.assertEqual((row['status'], len(calls), len(FakeSMTP.sent)), ('enviado', 2, 1))
        details = ' '.join(e['detail'] for e in self.events(row['id']))
        self.assertIn('reintento 1 de 1', details);self.assertIn('Falló en la etapa «Conectando con el servidor SMTP»', details)

    def test_authentication_failure_is_not_retried_and_names_the_stage(self):
        calls = []
        def client(config):
            calls.append(1);fake = FakeSMTP();fake.login = lambda *a: (_ for _ in ()).throw(smtplib.SMTPAuthenticationError(535, b'bad'));return fake
        with patch.object(mail_pro, 'smtp_client', side_effect=client):
            self.institutional('clave@example.invalid')
        row = self.row('clave@example.invalid')
        self.assertEqual((row['status'], row['code'], len(calls)), ('fallido', 'credenciales', 1))
        self.assertIn('Falló en la etapa «Autenticando la cuenta del remitente» (respuesta SMTP 535)', row['reason'])
        self.assertEqual([e['event'] for e in self.events(row['id'])][:3], ['creado', 'cola', 'conectando'])

    def test_cut_during_transmission_is_an_incident_without_confirmation_and_never_resent_automatically(self):
        def cut(*a, **k):
            raise smtplib.SMTPServerDisconnected('Connection unexpectedly closed')
        with patch.object(FakeSMTP, 'send_message', side_effect=cut):
            error = self.institutional('corte@example.invalid')
        row = self.row('corte@example.invalid')
        self.assertEqual((row['status'], error.kind), ('desconocido', 'sin_confirmacion'))
        self.assertEqual(row['reason'], 'Servidor SMTP no devolvió confirmación (se cortó durante la transmisión).')
        self.assertEqual(mail_tracking.LABELS[row['status']], 'Incidencia')
        with app.connect() as c:
            listing = mail_tracking.listing(c, {})
        self.assertEqual((listing['counts']['pendientes'], listing['counts']['incidencias']), (0, 1))

    def test_nothing_stays_sending_sweep_recovers_the_real_result(self):
        import mailing
        with app.connect() as c:
            old = self.now - timedelta(minutes=10)
            message = email.message.EmailMessage();message['Subject'] = 'x';message.set_content('x')
            sent_id = mailing.archive(c, 'quote', None, 'a@example.invalid', 'x', message, 'plantilla', None, old)
            mailing.mark(c, sent_id, 'enviado', 'El servidor de correo aceptó el mensaje.', '<id@x>', old)
            lost_id = mailing.archive(c, 'quote', None, 'b@example.invalid', 'x', message, 'plantilla', None, old)
            a = mail_tracking.start(c, ['a@example.invalid'], kind='quote', subject='x', now=old, archive_id=sent_id)
            b = mail_tracking.start(c, ['b@example.invalid'], kind='quote', subject='x', now=old, archive_id=lost_id)
            fresh = mail_tracking.start(c, ['c@example.invalid'], kind='quote', subject='x', now=self.now)
            mail_tracking.sweep(c, self.now);c.commit()
        self.assertEqual(self.row('a@example.invalid')['status'], 'enviado')
        self.assertIn('Recuperado del registro del mensaje', self.events(self.row('a@example.invalid')['id'])[-1]['detail'])
        lost = self.row('b@example.invalid');self.assertEqual(lost['status'], 'desconocido');self.assertIn('Servidor SMTP no devolvió confirmación registrada', lost['reason'])
        self.assertEqual(self.row('c@example.invalid')['status'], 'enviando')  # en curso, todavía dentro del plazo

    def test_accepted_means_sent_not_delivered_and_counters_are_exact(self):
        self.institutional('uno@example.invalid');self.institutional('dos@example.invalid')
        FakeSMTP.refuse = {'mala@example.invalid': (550, b'5.1.1 User unknown')};self.institutional('mala@example.invalid')
        with app.connect() as c:
            listing = mail_tracking.listing(c, {})
        self.assertEqual({k: listing['counts'][k] for k in ('enviados', 'entregados', 'pendientes', 'rebotados', 'fallidos', 'incidencias')},
                         {'enviados': 2, 'entregados': 0, 'pendientes': 0, 'rebotados': 1, 'fallidos': 0, 'incidencias': 1})
        row = next(r for r in listing['rows'] if r['recipient'] == 'uno@example.invalid')
        self.assertEqual(row['label'], 'Enviado');self.assertIn('La entrega final al destinatario no está confirmada', row['meaning'])

    def test_bookkeeping_after_acceptance_survives_a_database_hiccup(self):
        real = mail_tracking.accepted
        calls = []
        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                import sqlite3
                raise sqlite3.OperationalError('No se pudo contactar la base de datos remota.')
            return real(*a, **k)
        with patch.object(mail_tracking, 'accepted', side_effect=flaky):
            result = self.institutional('hipo@example.invalid')
        self.assertNotIsInstance(result, Exception)
        self.assertEqual((self.row('hipo@example.invalid')['status'], len(FakeSMTP.sent), len(calls)), ('enviado', 1, 2))
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT status FROM mail_archive ORDER BY id DESC LIMIT 1").fetchone()[0], 'enviado')


if __name__ == '__main__':
    unittest.main()
