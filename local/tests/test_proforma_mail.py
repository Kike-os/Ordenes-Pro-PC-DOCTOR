"""Mail Pro from the proforma UI contract, with temporary data and simulated SMTP."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import unittest
from unittest.mock import patch

import adi_exec
import app
import mail_pro
import mail_tracking
import test_invoicing
from test_proforma_orders import CLIENT, ITEMS

CONFIG = {'MAIL_IMAP_HOST':'imap.example.invalid','MAIL_SMTP_HOST':'smtp.example.invalid',
          'MAIL_USERNAME':'empresa@example.invalid','MAIL_PASSWORD':'ficticia',
          'PUBLIC_APP_URL':'https://example.invalid'}


class ProformaMailTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    request, login = Base.request, Base.login

    def setUp(self):
        self.Base.setUp(self)
        self.addCleanup(self.Base.tearDown,self)
        self.enterContext(patch.dict('os.environ', CONFIG))
        self.smtp = self.enterContext(patch.object(mail_pro,'deliver',return_value={'trace':[], 'dsn':False}))
        self.cookie,self.csrf = self.login()
        client = {**CLIENT,'client_email':'cliente@example.invalid'}
        result = self.post('/api/proformas',items=json.dumps(ITEMS),request_key='proforma-mail-test-0001',**client)
        self.assertEqual(result['status'],200,result['body'])
        self.path = '/api/proformas/%d' % result['body']['id']
        created = self.post(self.path,action='send')
        self.assertEqual(created['status'],200,created['body'])
        self.token = created['body']['link_token']

    def post(self,path,**body):
        return self.request(path,body,cookie=self.cookie,csrf=self.csrf)

    def send(self, **updates):
        return self.post(self.path,**{'action':'mail_send','link_token':self.token,'recipient':'cliente@example.invalid',
                                    'body':'Mensaje ficticio al cliente.',**updates})

    def test_mail_preview_mime_and_duplicate(self):
        preview = self.post(self.path,action='mail_preview',link_token=self.token)['body']
        self.assertEqual((preview['recipient'],preview['sender']),('cliente@example.invalid','empresa@example.invalid'))
        self.assertTrue(preview['filename'].endswith('.pdf'))
        self.assertIn(self.token,preview['link'])
        self.assertNotIn('ficticia',str(preview))
        self.assertEqual(self.smtp.call_count,0)
        result = self.send()
        self.assertEqual(result['status'],200,result['body'])
        self.assertEqual(result['body']['status'],'accepted')
        message, recipients = self.smtp.call_args.args[1:]
        self.assertEqual(recipients,['cliente@example.invalid'])
        self.assertIn('empresa@example.invalid',message['From'])
        self.assertIn(preview['link'],message.get_body(('plain',)).get_content())
        attachment = next(message.iter_attachments())
        self.assertEqual(attachment.get_content_type(),'application/pdf')
        self.assertTrue(attachment.get_payload(decode=True).startswith(b'%PDF'))
        self.assertEqual(attachment.get_filename(),preview['filename'])
        repeated = self.send(body='Otro texto')
        self.assertTrue(repeated['body']['duplicate'])
        self.assertEqual(self.smtp.call_count,1)
        with app.connect() as c:
            row=c.execute("SELECT body_text FROM mail_archive WHERE kind='proforma'").fetchone()
            self.assertNotIn(self.token,row['body_text'])
            delivery=c.execute("SELECT * FROM mail_deliveries WHERE kind='proforma'").fetchone()
            self.assertEqual(delivery['status'],'enviado')
            now=app.reception_now()
            mail_tracking.record(c,delivery['id'],'entregado','confirmed','dsn','2.0.0','Entrega ficticia',mail_tracking.stamp(now),'proforma-test-dsn',now)
        history=self.request(self.path,cookie=self.cookie)['body']['mail_history']
        self.assertEqual(history[0]['status'],'entregado')
        self.assertEqual(history[0]['sender'],'empresa@example.invalid')
        self.assertEqual(history[0]['message_id'],result['body']['message_id'])

    def test_recipient_override_rejection_and_safe_retry(self):
        self.assertEqual(self.send(recipient='otro@example.invalid')['status'],400)
        self.assertEqual(self.send(recipient='a@example.invalid, b@example.invalid',confirm_recipient=True)['status'],400)
        self.assertEqual(self.send(recipient='a@example.invalid\nBcc: b@example.invalid',confirm_recipient=True)['status'],400)
        self.assertEqual(self.send(link_token='token-inválido')['status'],409)
        self.assertFalse(self.smtp.called)
        self.smtp.side_effect=mail_pro.MailError('servidor','SMTP ficticio rechazó el mensaje.')
        failed=self.send(recipient='otro@example.invalid',confirm_recipient=True)
        self.assertEqual(failed['status'],502)
        preview=self.post(self.path,action='mail_preview',link_token=self.token)['body']
        self.assertEqual(preview['status'],'failed')
        with app.connect() as c:
            alerts=adi_exec.mail_delivery_health(c,app.reception_now())
        self.assertEqual(alerts['incidencias_24h'],{'fallido':1})
        self.smtp.side_effect=None
        self.assertEqual(self.send(recipient='otro@example.invalid',confirm_recipient=True)['status'],200)
        self.assertEqual(self.smtp.call_count,2)

    def test_ambiguous_result_blocks_retry_including_link_replacement(self):
        self.smtp.side_effect=mail_pro.MailError('sin_confirmacion','SMTP ficticio sin confirmación.')
        self.assertEqual(self.send()['body']['kind'],'sin_confirmacion')
        self.assertEqual(self.send()['status'],409)
        self.assertEqual(self.post(self.path,action='send')['status'],409)
        self.assertEqual(self.smtp.call_count,1)
        history=self.request(self.path,cookie=self.cookie)['body']['mail_history']
        self.assertEqual(history[0]['status'],'desconocido')
        self.assertEqual(history[0]['reason'],'Servidor SMTP no devolvió confirmación (se cortó durante la transmisión).')
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
        with patch.dict('os.environ', {'MAIL_ALLOW_TECHNICIANS':'0'}):
            self.assertEqual(self.send()['status'],403)

    def test_concurrent_submission_claims_one_smtp_attempt(self):
        started, finish = Event(), Event()
        def deliver(*args, **kwargs):
            started.set()
            if not finish.wait(10):
                raise RuntimeError('El intento de prueba quedó abierto.')
            return {'trace': [], 'dsn': False}
        self.smtp.side_effect = deliver
        with ThreadPoolExecutor(max_workers=1) as worker:
            first = worker.submit(self.send)
            try:
                self.assertTrue(started.wait(10))
                concurrent = self.send()
                self.assertEqual(concurrent['status'],409,concurrent['body'])
            finally:
                finish.set()
            self.assertEqual(first.result(timeout=10)['status'],200)
        self.assertEqual(self.smtp.call_count,1)
