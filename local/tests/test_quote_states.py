"""Estados automáticos de presupuestos: esperando respuesta, aprobado, rechazado y aprobado parcialmente; correo fallido,
sincronización con la orden, avisos y protección contra respuestas duplicadas. Base temporal, sin correos reales."""
import re
import unittest
from unittest.mock import patch

import test_app
import app
import mail_pro
import quotes
import test_quotes
SIGN = test_quotes.SIGN

CONFIG = {'username': 'taller@example.invalid', 'password': 'x'}


class QuoteStateTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data
    form = test_quotes.QuoteFlowTests.form

    def quote(self, key, deliver=None, order_status=None):
        cookie, csrf = self.login()
        self.cookie, self.csrf = cookie, csrf
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        order = self.request('/api/orders', self.order_data({'email': 'cliente@example.invalid', 'request_key': 'quote-state-request-' + key}), cookie=cookie, csrf=csrf)['body']
        if order_status:
            post('/api/order-status', id=str(order['id']), status=order_status)
        quote = post('/api/orders/%d/quote' % order['id'])['body']['id']
        post('/api/quotes/%d' % quote, action='save', items=[{'description': 'Servicio ficticio', 'category': 'servicio', 'quantity': 1, 'unit_cents': 3000, 'taxed': True},
                                                             {'description': 'Repuesto ficticio', 'category': 'repuesto', 'quantity': 1, 'unit_cents': 5000, 'taxed': True}])
        with patch.object(mail_pro, 'configured', return_value=True), patch.object(mail_pro, 'settings', return_value=CONFIG), patch.object(mail_pro, 'deliver', side_effect=deliver or (lambda config, message, recipients: None)):
            result = post('/api/quotes/%d' % quote, action='send')['body']
        return order, quote, result

    def answer(self, link, choices, **extra):
        path = '/presupuesto/' + link.rsplit('/', 1)[1]
        page = self.form(path, {'last4': '0017'})['body']
        passkey = re.search(r'name="passkey" value="([^"]+)"', page)[1]
        ids = [int(v) for v in dict.fromkeys(re.findall(r'name="decision_(\d+)"', page))]
        return self.form(path, dict({'passkey': passkey, 'action': 'decide', 'name': 'Cliente Ficticio', 'accept': 'on', 'signature': SIGN}, **{'decision_%d' % i: v for i, v in zip(ids, choices)}, **extra))

    def notes(self):
        return [i for i in self.request('/api/notifications', cookie=self.cookie)['body']['items'] if i['key'].startswith('quote:')]

    def test_sent_quote_waits_for_the_answer_and_notifies(self):
        order, quote, result = self.quote('000001')
        self.assertEqual((result['mail'], result['quote']['status'], result['quote']['status_label'], result['quote']['mail_state']), ('sent', 'enviado', 'Esperando respuesta', 'sent'))
        data = self.request('/api/orders/%d/quote' % order['id'], cookie=self.cookie)['body']
        self.assertEqual((data['versions'][0]['mail_state'], data['current']['status_label']), ('sent', 'Esperando respuesta'))
        sent = [n for n in self.notes() if ':enviado:' in n['key']]
        self.assertEqual(len(sent), 1)
        self.assertIn('Esperando respuesta del cliente', sent[0]['detail'])
        # Estado técnico y comercial separados: la orden sigue en «En espera».
        self.assertEqual(self.request('/api/orders/%d' % order['id'], cookie=self.cookie)['body']['order']['status'], 'pendiente')

    def test_failed_mail_is_not_recorded_as_sent(self):
        def boom(config, message, recipients):
            raise mail_pro.MailError('red', 'sin conexión')
        order, quote, result = self.quote('000002', deliver=boom)
        self.assertEqual((result['mail'], result['quote']['mail_state']), ('failed', 'failed'))
        self.assertFalse([n for n in self.notes() if ':enviado:' in n['key']])
        with app.connect() as c:
            events = [r['detail'] for r in c.execute("SELECT detail FROM quote_events WHERE quote_id=? AND event='correo'", (quote,))]
            archived = c.execute("SELECT status FROM mail_archive WHERE kind='quote' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIn('no se pudo enviar', events[-1])
        self.assertEqual(archived['status'], 'error')

    def test_approval_moves_order_from_quote_approval_to_processing_and_notifies(self):
        order, quote, result = self.quote('000003', order_status='presupuesto')
        self.assertEqual(self.answer(result['link'], ['aprobado', 'aprobado'])['status'], 200)
        detail = self.request('/api/orders/%d' % order['id'], cookie=self.cookie)['body']['order']
        self.assertEqual(detail['status'], 'reparacion')
        self.assertTrue(any('aprobado por el cliente' in h['comment'] and 'Procesando' in h['comment'] for h in detail['history']))
        with app.connect() as c:
            row = quotes.get(c, quote)
            self.assertEqual((row['status'], row['decided_by']), ('aprobado', 'cliente'))
            self.assertTrue(row['decided_at'])
            self.assertTrue(c.execute('SELECT signature FROM quote_acceptances WHERE quote_id=?', (quote,)).fetchone()['signature'])
        self.assertTrue(any(n['title'].startswith('Presupuesto aprobado por el cliente') for n in self.notes()))
        # Una segunda respuesta con el mismo enlace no es posible: el enlace quedó revocado al decidir.
        path = '/presupuesto/' + result['link'].rsplit('/', 1)[1]
        self.assertNotIn('name="passkey"', self.form(path, {'last4': '0017'})['body'])

    def test_rejection_keeps_the_quote_records_the_reason_and_never_touches_a_ready_order(self):
        order, quote, result = self.quote('000004', order_status='listo')
        self.answer(result['link'], ['rechazado', 'rechazado'], comment='Prefiero no reparar por ahora.')
        detail = self.request('/api/orders/%d' % order['id'], cookie=self.cookie)['body']['order']
        self.assertEqual(detail['status'], 'listo')
        data = self.request('/api/orders/%d/quote' % order['id'], cookie=self.cookie)['body']
        self.assertEqual((data['current']['status'], data['current']['client_note']), ('rechazado', 'Prefiero no reparar por ahora.'))
        self.assertEqual(len(data['current']['items']), 2)
        rejected = [n for n in self.notes() if 'rechazado por el cliente' in n['title']]
        self.assertTrue(rejected and 'Prefiero no reparar' in rejected[0]['detail'] and 'No se autoriza ningún servicio' in rejected[0]['detail'])
        with app.connect() as c:
            self.assertIsNone(quotes.authorized(c, order['id']))

    def test_partial_approval_authorizes_only_the_approved_items(self):
        order, quote, result = self.quote('000005', order_status='presupuesto')
        self.answer(result['link'], ['aprobado', 'rechazado'])
        data = self.request('/api/orders/%d/quote' % order['id'], cookie=self.cookie)['body']
        self.assertEqual((data['current']['status'], data['current']['status_label']), ('parcial', 'Aprobado parcialmente'))
        self.assertEqual({i['description']: i['status'] for i in data['current']['items']}, {'Servicio ficticio': 'aprobado', 'Repuesto ficticio': 'rechazado'})
        with app.connect() as c:
            allowed = quotes.authorized(c, order['id'])
        self.assertEqual([i['description'] for i in allowed['items']], ['Servicio ficticio'])
        self.assertEqual(self.request('/api/orders/%d' % order['id'], cookie=self.cookie)['body']['order']['status'], 'reparacion')
        self.assertTrue(any(n['title'].startswith('Presupuesto aprobado parcialmente') for n in self.notes()))


if __name__ == '__main__':
    unittest.main()
