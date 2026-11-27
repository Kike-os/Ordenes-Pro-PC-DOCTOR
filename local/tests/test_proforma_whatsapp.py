"""Integración HTTP de Proformas con un transporte de Meta ficticio."""
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

import app
import proforma_whatsapp as pf
import test_invoicing
from test_proforma_orders import CLIENT, ITEMS
from test_whatsapp_business import FAKE
import whatsapp_business as wa

PHONE = '593980000000'
BASE = 'https://ordenes-pro.ecuadorpcdoctor.com'


class ProformaWhatsAppTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    request, login = Base.request, Base.login

    def setUp(self):
        self.Base.setUp(self)
        self.addCleanup(self.Base.tearDown, self)
        self.sent, self.responses = [], []
        self.template = dict(pf.template_definition(BASE), status='APPROVED', name='proforma_existente')
        self.enterContext(patch.dict('os.environ', {**FAKE, 'PUBLIC_APP_URL': BASE}))
        self.enterContext(patch.object(wa, 'TRANSPORT', self.meta))
        self.cookie, self.csrf = self.login()
        created = self.post('/api/proformas', items=json.dumps(ITEMS), request_key='proforma-whatsapp-0001',
                            client_phone='0980000000', **CLIENT)
        self.assertEqual(created['status'], 200, created['body'])
        self.path = '/api/proformas/%d' % created['body']['id']
        self.token = self.post(self.path, action='send')['body']['link_token']

    def meta(self, method, url, headers, body):
        if method == 'GET' and '/message_templates' in url:
            return 200, {'data': [self.template]}
        if method == 'POST' and url.endswith('/messages'):
            self.sent.append(body)
            return self.responses.pop(0) if self.responses else (200, {'messages': [{'id': 'wamid.ficticio'}]})
        self.fail('Llamada inesperada al transporte ficticio: ' + url)

    def post(self, path, **body):
        return self.request(path, body, cookie=self.cookie, csrf=self.csrf)

    def consent(self):
        with app.connect() as c:
            wa.record_consent(c, PHONE, 'aceptado', 'presencial', app.reception_now())

    def send(self, **overrides):
        data = {'recipient': '+' + PHONE, 'template': 'proforma_existente', 'language': 'es', **overrides}
        return self.post(self.path, action='whatsapp_send', link_token=self.token, **data)

    def webhook(self, status):
        update = {'id': 'wamid.ficticio', 'status': status, 'recipient_id': PHONE,
                  'biz_opaque_callback_data': self.sent[-1]['biz_opaque_callback_data']}
        raw = json.dumps({'entry': [{'changes': [{'value': {'statuses': [update]}}]}]}).encode()
        signature = 'sha256=' + hmac.new(FAKE['WHATSAPP_APP_SECRET'].encode(), raw, hashlib.sha256).hexdigest()
        with app.connect() as c:
            wa.webhook(c, raw, signature, app.reception_now(), FAKE)

    def history(self):
        return self.request(self.path, cookie=self.cookie)['body']['whatsapp_history']

    def test_send_once_and_apply_monotonic_webhook(self):
        self.consent()
        preview = self.post(self.path, action='whatsapp_preview', link_token=self.token)['body']
        self.assertEqual(preview['template_state'], 'aprobada')
        self.assertIn(CLIENT['client_name'], preview['preview']['body'])
        self.assertEqual(self.send()['body']['delivery']['status'], 'enviado')
        self.assertEqual(self.send()['body']['delivery']['status'], 'enviado')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['to'], PHONE)
        self.assertEqual(self.sent[0]['template']['components'][1]['parameters'][0]['text'], self.token)
        self.webhook('delivered')
        self.webhook('read')
        self.webhook('sent')
        log = self.history()[0]
        self.assertEqual((log['status'], log['provider_id']), ('leido', 'wamid.ficticio'))
        self.assertTrue(log['actor'])
        with app.connect() as c:
            row = c.execute('SELECT * FROM whatsapp_outbox WHERE event=?', (pf.EVENT,)).fetchone()
            self.assertNotIn(self.token, str(dict(row)))

    def test_refuses_unverified_recipient_and_unapproved_template(self):
        self.assertEqual(self.send()['status'], 409)
        self.consent()
        self.assertEqual(self.send(recipient='+593990000000')['status'], 409)
        self.template['status'] = 'PENDING'
        self.assertEqual(self.send()['status'], 409)
        self.assertFalse(self.sent)

    def test_retry_rejection_and_reconcile_ambiguous_result(self):
        self.consent()
        self.responses = [(429, {}), (0, {})]
        self.assertTrue(self.send()['body']['delivery']['retry'])
        self.assertFalse(self.send()['body']['delivery']['retry'])
        self.assertEqual(self.send()['body']['delivery']['status'], 'fallido')
        self.assertEqual(len(self.sent), 2)
        self.webhook('delivered')
        self.assertEqual(self.history()[0]['status'], 'entregado')


class TemplateAuditTests(unittest.TestCase):
    def test_follows_pagination_before_considering_submission(self):
        existing = dict(pf.template_definition(BASE), name='otra_proforma', status='APPROVED')
        results = [(200, {'data': [], 'paging': {'next': 'https://graph.facebook.com/next', 'cursors': {'after': 'cursor'}}}),
                   (200, {'data': [existing]})]
        with patch.object(wa, 'call', side_effect=results) as transport:
            self.assertEqual(pf.audit_template(BASE, FAKE, submit=True)[1], existing)
        self.assertEqual([call.args[0] for call in transport.call_args_list], ['GET', 'GET'])

    def test_submits_only_when_no_equivalent_exists(self):
        with patch.object(wa, 'call', side_effect=[(200, {'data': []}), (200, {'id': '123', 'status': 'PENDING'})]) as transport:
            self.assertEqual(pf.audit_template(BASE, FAKE, submit=True)[0], 'presentada')
        payload = transport.call_args.args[3]
        self.assertEqual((payload['name'], payload['category']), (pf.NAME, 'UTILITY'))
        self.assertTrue(pf.compatible(payload, BASE))
        self.assertFalse(pf.compatible(payload, 'https://otro.example'))
