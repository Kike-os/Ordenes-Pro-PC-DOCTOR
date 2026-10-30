"""Centro de seguimiento de la orden (datos ficticios, base temporal, sin WhatsApp ni correo reales): seguimientos con lo interno separado de
lo visible para el cliente, evidencias validadas, inmutabilidad, enlace público sin datos internos, plantillas con datos reales, mensajes
preparados que nunca cuentan como enviados, WhatsApp Business simulado (envío, error, reintento sin duplicar) y avisos firmados."""
import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

import test_invoicing
import app
import order_followups

PNG = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'\x00' * 64).decode()
PDF = base64.b64encode(b'%PDF-1.4 informe ficticio').decode()
WA = {'WHATSAPP_TOKEN': 'token-ficticio', 'WHATSAPP_PHONE_NUMBER_ID': '123456', 'WHATSAPP_APP_SECRET': 'secreto-ficticio', 'WHATSAPP_VERIFY_TOKEN': 'verifica-ficticio'}


class OrderFollowupTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure

    def followup(self, post, oid, **extra):
        body = dict(kind='esperando_autorizacion', internal_note='Disco con sectores dañados (SMART 197=48). Solo taller.', client_message='Identificamos fallas en la unidad de almacenamiento; recomendamos reemplazarla.',
                    client_visible='1', priority='alta', next_action='Llamar al cliente', files=json.dumps([{'name': 'smart.png', 'data': PNG, 'visible': '1'}, {'name': 'informe.pdf', 'data': PDF, 'visible': ''}]))
        body.update(extra)
        return post('/api/orders/%d/followups' % oid, **body)

    def test_followups_keep_internal_private_and_are_immutable(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        made = self.followup(post, oid, request_key='seguimiento-prueba-0001')
        self.assertEqual(made['status'], 201, made['body'])
        self.assertEqual(self.followup(post, oid, request_key='seguimiento-prueba-0001')['body']['id'], made['body']['id'])  # doble clic: no duplica
        data = self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']
        fu = data['followups'][0]
        self.assertEqual((fu['kind_label'], fu['group'], fu['client_visible'], fu['priority'], len(fu['files'])), ('Esperando autorización', 'autorizacion', 1, 'alta', 2))
        self.assertEqual(len(data['followups']), 1)
        with app.connect() as c:
            self.assertTrue(c.execute("SELECT 1 FROM order_history WHERE id=? AND event='follow_up'", (fu['history_id'],)).fetchone())  # integrado al historial
            with self.assertRaises(Exception):
                c.execute("UPDATE order_followups SET internal_note='cambio' WHERE id=?", (fu['id'],))
            with self.assertRaises(Exception):
                c.execute('DELETE FROM order_followup_files')
            import order_tracking
            from datetime import datetime
            order_tracking.create(c, oid, self.uid, datetime.now().astimezone())
            row = c.execute("SELECT token FROM order_tracking_links WHERE order_id=? AND revoked_at=''", (oid,)).fetchone()
            c.commit()
        page = self.request('/s/' + row['token'])['body']
        page = page.decode() if isinstance(page, bytes) else page
        self.assertIn('Identificamos fallas en la unidad de almacenamiento', page)
        self.assertNotIn('SMART 197', page)  # la nota interna nunca se publica
        internal = next(f for f in fu['files'] if not f['visible_to_client'])
        self.assertEqual(self.request('/api/orders/%d/followups/files/%d' % (oid, internal['id']), cookie=cookie)['body'][:5], b'%PDF-')
        self.assertEqual(self.request('/api/orders/%d/followups/files/%d' % (oid, internal['id']))['status'], 401)  # sin sesión
        # Una corrección es otro seguimiento que referencia al anterior; el original no cambia.
        fix = post('/api/orders/%d/followups' % oid, kind='esperando_autorizacion', internal_note='Corrección: SMART 197=52.', corrects_id=str(fu['id']))
        self.assertEqual(fix['status'], 201, fix['body'])
        self.assertEqual(self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['followups'][0]['corrects_id'], fu['id'])

    def test_validation(self):
        cookie, csrf, post, order = self.paid_order(5000, pay=False)
        oid = order['id']
        self.assertEqual(self.followup(post, oid, kind='otro')['status'], 400)
        self.assertEqual(self.followup(post, oid, internal_note='', client_message='')['status'], 400)
        self.assertEqual(self.followup(post, oid, files=json.dumps([{'name': 'x.exe', 'data': base64.b64encode(b'MZ ejecutable').decode()}]))['status'], 400)
        big = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'\x00' * 950000).decode()
        self.assertEqual(self.followup(post, oid, files=json.dumps([{'name': 'grande.png', 'data': big}]))['status'], 400)
        self.assertEqual(self.followup(post, oid, files=json.dumps([{'name': 'a.png', 'data': PNG}] * 4))['status'], 400)
        self.assertEqual(self.followup(post, oid, next_date='2000-01-01')['status'], 400)
        self.assertEqual(self.followup(post, oid, quote_id='999999')['status'], 400)
        self.assertEqual(self.followup(post, oid, client_visible='1', client_message='', internal_note='Solo interno')['status'], 201)
        fu = self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['followups'][0]
        self.assertEqual(fu['client_visible'], 0)  # sin mensaje no hay nada visible para el cliente

    def test_messages_templates_whatsapp_and_signed_status(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        fid = self.followup(post, oid)['body']['id']
        text = post('/api/orders/%d/messages' % oid, action='compose', template='autorizacion', followup_id=str(fid))['body']['body']
        self.assertIn(order['code'], text)
        self.assertIn('unidad de almacenamiento', text)
        self.assertIn('necesitamos su autorización', text)
        self.assertNotIn('SMART', text)  # nunca la nota interna
        # Manual: queda «preparado» y jamás «enviado».
        prep = post('/api/orders/%d/messages' % oid, action='prepare', channel='whatsapp_manual', body=text, followup_id=str(fid), request_key='mensaje-manual-000001')
        self.assertEqual(prep['body']['message']['status'], 'preparado')
        self.assertEqual(post('/api/orders/%d/messages' % oid, action='whatsapp', body=text, request_key='mensaje-wa-sinconfig1')['status'], 409)  # sin configurar
        calls = []

        def fake(url, headers, payload):
            calls.append(payload)
            if len(calls) == 1:
                return 400, {'error': {'message': 'Fuera de la ventana de 24 horas (ficticio)'}}
            return 200, {'messages': [{'id': 'wamid.FICTICIO1'}]}
        with patch.dict(app.os.environ, WA), patch.object(order_followups, 'TRANSPORT', fake):
            self.assertTrue(self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['whatsapp']['configured'])
            fail = post('/api/orders/%d/messages' % oid, action='whatsapp', body=text, followup_id=str(fid), recipient='0991234567', request_key='mensaje-wa-prueba-0001')
            self.assertEqual((fail['status'], fail['body']['message']['status']), (502, 'error'))
            ok = post('/api/orders/%d/messages' % oid, action='whatsapp', body=text, followup_id=str(fid), recipient='0991234567', request_key='mensaje-wa-prueba-0001')  # reintento
            self.assertEqual((ok['status'], ok['body']['message']['status'], ok['body']['message']['attempts'], ok['body']['message']['provider_id']), (200, 'enviado', 2, 'wamid.FICTICIO1'))
            again = post('/api/orders/%d/messages' % oid, action='whatsapp', body=text, followup_id=str(fid), recipient='0991234567', request_key='mensaje-wa-prueba-0001')
            self.assertEqual((again['body']['duplicate'], len(calls)), (True, 2))  # no se envía dos veces
            self.assertEqual(calls[-1]['to'], '593991234567')
            # Avisos de Meta: solo con firma válida, y el estado nunca retrocede.
            event = lambda st: json.dumps({'entry': [{'changes': [{'value': {'statuses': [{'id': 'wamid.FICTICIO1', 'status': st}]}}]}]}).encode()
            sign = lambda raw: 'sha256=' + hmac.new(b'secreto-ficticio', raw, hashlib.sha256).hexdigest()
            with app.connect() as c:
                from datetime import datetime
                now = datetime.now().astimezone()
                self.assertEqual(order_followups.webhook_status(c, event('delivered'), 'sha256=falsa', now), 0)
                self.assertEqual(order_followups.webhook_status(c, event('delivered'), sign(event('delivered')), now), 1)
                self.assertEqual(order_followups.webhook_status(c, event('sent'), sign(event('sent')), now), 0)
                self.assertEqual(order_followups.webhook_status(c, event('read'), sign(event('read')), now), 1)
                self.assertEqual(c.execute("SELECT status FROM order_messages WHERE provider_id='wamid.FICTICIO1'").fetchone()[0], 'leido')
                self.assertEqual(order_followups.webhook_verify({'hub.mode': 'subscribe', 'hub.verify_token': 'verifica-ficticio', 'hub.challenge': '42'}), '42')
                self.assertIsNone(order_followups.webhook_verify({'hub.mode': 'subscribe', 'hub.verify_token': 'otra', 'hub.challenge': '42'}))
                with self.assertRaises(Exception):
                    c.execute("UPDATE order_messages SET body='otro texto' WHERE provider_id='wamid.FICTICIO1'")
        # Correo: sin Mail Pro configurado no se envía ni se registra como enviado.
        mail = post('/api/orders/%d/messages' % oid, action='email', body=text, recipient='cliente@example.invalid')
        self.assertEqual(mail['status'], 409)
        statuses = [m['status'] for m in self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['messages']]
        self.assertEqual(sorted(statuses), ['leido', 'preparado'])


if __name__ == '__main__':
    unittest.main()
