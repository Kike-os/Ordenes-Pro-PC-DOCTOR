"""Libreta de direcciones y comunicados a clientes: contactos del registro, envíos individuales, cola, duplicados, bajas y permisos.
Base temporal, datos ficticios y servidor SMTP simulado: no sale ningún correo."""
import json
import smtplib
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_app
import app
import campaigns
import mail_pro

ENV = {'MAIL_IMAP_HOST': 'mail.example.invalid', 'MAIL_SMTP_HOST': 'mail.example.invalid', 'MAIL_SMTP_PORT': '465', 'MAIL_USERNAME': 'buzon@example.invalid', 'MAIL_PASSWORD': 'secreto-ficticio-123'}


class FakeSMTP:
    sent = []
    refuse = set()

    def __init__(self, *a, **k):
        pass

    def login(self, *a):
        pass

    def has_extn(self, name):
        return False

    def send_message(self, message, from_addr=None, to_addrs=None, **options):
        if set(to_addrs) & FakeSMTP.refuse:
            raise smtplib.SMTPRecipientsRefused({address: (550, b'5.1.1 User unknown') for address in to_addrs})
        FakeSMTP.sent.append((message, list(to_addrs)))
        return {}

    def quit(self):
        pass


class CampaignTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        FakeSMTP.sent, FakeSMTP.refuse = [], set()
        self.patches = [patch.object(mail_pro, 'smtp_client', side_effect=lambda config: FakeSMTP()), patch.dict(app.os.environ, ENV), patch.object(campaigns, 'PAUSE_SECONDS', 0)]
        for item in self.patches:
            item.start()
        with app.connect() as c:
            for name, email in (('Ana Ficticia', 'ana@example.invalid'), ('Bruno Ficticio', 'bruno@example.invalid'), ('Ana Duplicada', 'ANA@example.invalid'),
                                ('Sin Correo', ''), ('Correo Malo', 'no-es-correo'), ('Carla Ficticia', 'carla@example.invalid')):
                c.execute("INSERT INTO clients(name,email,phone,identification) VALUES (?,?,'0990000000','')", (name, email))

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        test_app.SecurityTests.tearDown(self)

    def ids(self, c, *names):
        return [c.execute('SELECT id FROM clients WHERE name=?', (name,)).fetchone()[0] for name in names]

    def test_contacts_come_from_the_client_registry_deduplicated_and_up_to_date(self):
        cookie, csrf = self.login()
        data = self.request('/api/mail/contacts?all=1', cookie=cookie)['body']
        self.assertEqual([row['email'] for row in data['rows']], ['ana@example.invalid', 'bruno@example.invalid', 'carla@example.invalid'])
        self.assertEqual(data['rows'][0]['duplicates'], 1)
        self.assertEqual((data['stats']['duplicates'], data['stats']['invalid'], data['stats']['clients'] - data['stats']['with_email']), (1, 1, 1))
        with app.connect() as c:
            c.execute("UPDATE clients SET email='bruno.nuevo@example.invalid' WHERE name='Bruno Ficticio'")
            c.execute("INSERT INTO clients(name,email,phone,identification) VALUES ('Dario Nuevo','dario@example.invalid','0990000001','')")
        emails = [row['email'] for row in self.request('/api/mail/contacts?all=1', cookie=cookie)['body']['rows']]
        self.assertIn('bruno.nuevo@example.invalid', emails);self.assertIn('dario@example.invalid', emails);self.assertNotIn('bruno@example.invalid', emails)

    def test_campaign_requires_admin_and_explicit_confirmation(self):
        cookie, csrf = self.login()
        with app.connect() as c:
            chosen = self.ids(c, 'Ana Ficticia', 'Ana Duplicada', 'Carla Ficticia')
        draft = self.request('/api/mail/campaigns', {'subject': 'Nueva agenda en línea', 'body': 'Estimado/a {nombre}:\n\nYa puede agendar en {enlace_citas}.', 'audience': 'selected', 'client_ids': json.dumps(chosen)}, cookie=cookie, csrf=csrf)
        self.assertEqual(draft['status'], 201)
        campaign = draft['body']['campaign']
        self.assertEqual(campaign['total'], 2)
        self.assertEqual(self.request('/api/mail/campaigns/%d/process' % campaign['id'], {}, cookie=cookie, csrf=csrf)['body']['campaign']['counts']['sent'], 0)
        self.assertEqual(FakeSMTP.sent, [])
        self.assertEqual(self.request('/api/mail/campaigns/%d/confirm' % campaign['id'], {'confirm': True, 'count': '5'}, cookie=cookie, csrf=csrf)['status'], 400)
        self.assertEqual(self.request('/api/mail/campaigns/%d/confirm' % campaign['id'], {'confirm': True, 'count': '2'}, cookie=cookie, csrf=csrf)['status'], 200)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
        self.assertEqual(self.request('/api/mail/campaigns', cookie=cookie)['status'], 403)
        self.assertEqual(self.request('/api/mail/campaigns/%d/process' % campaign['id'], {}, cookie=cookie, csrf=csrf)['status'], 403)

    def test_individual_messages_once_each_with_personal_unsubscribe_link(self):
        cookie, csrf = self.login()
        draft = self.request('/api/mail/campaigns', {'subject': 'Comunicado de prueba', 'body': 'Estimado/a {nombre}:\n\nTexto ficticio del comunicado.', 'audience': 'all'}, cookie=cookie, csrf=csrf)['body']['campaign']
        self.assertEqual(draft['total'], 3)
        self.request('/api/mail/campaigns/%d/confirm' % draft['id'], {'confirm': True, 'count': '3'}, cookie=cookie, csrf=csrf)
        FakeSMTP.refuse = {'carla@example.invalid'}
        done = self.request('/api/mail/campaigns/%d/process' % draft['id'], {}, cookie=cookie, csrf=csrf)['body']['campaign']
        self.assertEqual((done['status'], done['counts']['sent'], done['counts']['failed']), ('done', 2, 1))
        self.assertEqual(sorted(to for _, recipients in FakeSMTP.sent for to in recipients), ['ana@example.invalid', 'bruno@example.invalid'])
        self.assertTrue(all(len(recipients) == 1 and 'Bcc' not in message and ',' not in str(message['To']) for message, recipients in FakeSMTP.sent))
        text = next(m for m, r in FakeSMTP.sent if r == ['ana@example.invalid']).get_body(('plain',)).get_content()
        self.assertIn('Estimado/a Ana Ficticia:', text);self.assertIn('/baja/', text)
        # La copia archivada no guarda el enlace personal de baja.
        with app.connect() as c:
            archived = [row['body_text'] for row in c.execute("SELECT body_text FROM mail_archive WHERE kind='campaign'")]
            self.assertTrue(archived and not any('/baja/' in body for body in archived))
            states = {row['status'] for row in c.execute("SELECT d.status FROM mail_campaign_recipients r JOIN mail_deliveries d ON d.id=r.delivery_id")}
            self.assertEqual(states, {'enviado', 'rebotado'})
        # Procesar otra vez no reenvía a nadie.
        self.request('/api/mail/campaigns/%d/process' % draft['id'], {}, cookie=cookie, csrf=csrf)
        self.assertEqual(len(FakeSMTP.sent), 2)
        detail = self.request('/api/mail/campaigns/%d' % draft['id'], cookie=cookie)['body']['campaign']
        self.assertEqual({r['email']: r['delivery'] for r in detail['recipients']}['carla@example.invalid'], 'rebotado')

    def test_stuck_sends_are_not_repeated_and_unsubscribe_excludes_future_campaigns_only(self):
        cookie, csrf = self.login()
        draft = self.request('/api/mail/campaigns', {'subject': 'Comunicado de prueba', 'body': 'Estimado/a {nombre}:\n\nTexto ficticio del comunicado.', 'audience': 'all'}, cookie=cookie, csrf=csrf)['body']['campaign']
        self.request('/api/mail/campaigns/%d/confirm' % draft['id'], {'confirm': True, 'count': '3'}, cookie=cookie, csrf=csrf)
        old = (app.reception_now() - timedelta(minutes=30)).isoformat(timespec='seconds')
        with app.connect() as c:
            c.execute("UPDATE mail_campaign_recipients SET status='sending',updated_at=? WHERE email='bruno@example.invalid'", (old,))
        self.request('/api/mail/campaigns/%d/process' % draft['id'], {}, cookie=cookie, csrf=csrf)
        self.assertNotIn(['bruno@example.invalid'], [r for _, r in FakeSMTP.sent])
        link = next(m for m, r in FakeSMTP.sent if r == ['ana@example.invalid']).get_body(('plain',)).get_content().split('/baja/')[1].split()[0]
        page = self.request('/baja/' + link)
        self.assertEqual(page['status'], 200);self.assertIn('an•', page['body']);self.assertNotIn('ana@example.invalid', page['body'])
        handler_status = self.request('/baja/' + link, {})
        self.assertEqual(handler_status['status'], 200)
        with app.connect() as c:
            self.assertTrue(c.execute("SELECT 1 FROM mail_optouts WHERE email='ana@example.invalid'").fetchone())
        again = self.request('/api/mail/campaigns', {'subject': 'Otro comunicado', 'body': 'Estimado/a {nombre}:\n\nOtro texto ficticio.', 'audience': 'all'}, cookie=cookie, csrf=csrf)['body']
        self.assertEqual((again['campaign']['total'], again['excluded']['opted_out']), (2, 1))
        # Los correos de servicio siguen llegando a quien se dio de baja de los comunicados.
        with app.connect() as c:
            app.send_institutional(c, 'receipt', 'Comprobante', 'ana@example.invalid', 'Comprobante ficticio', 'Hola:\n\nTexto.', None, self.uid, review=False)
        self.assertEqual(FakeSMTP.sent[-1][1], ['ana@example.invalid'])
        self.assertEqual(self.request('/baja/token-que-no-existe-123')['status'], 404)

    def test_preview_is_isolated_and_uses_the_first_recipient(self):
        cookie, csrf = self.login()
        draft = self.request('/api/mail/campaigns', {'subject': 'Comunicado de prueba', 'body': 'Estimado/a {nombre}:\n\nTexto ficticio del comunicado.', 'audience': 'all'}, cookie=cookie, csrf=csrf)['body']['campaign']
        page = self.request('/api/mail/campaigns/%d/preview' % draft['id'], cookie=cookie)
        self.assertEqual(page['status'], 200)
        self.assertIn('Estimado/a Ana Ficticia:', page['body'])
        templates = self.request('/api/mail/campaigns', cookie=cookie)['body']['templates']
        self.assertIn('{nombre}', templates['agenda']['body']);self.assertIn('{enlace_citas}', templates['agenda']['body'])


if __name__ == '__main__':
    unittest.main()
