"""Políticas comerciales con versiones, RIDE, garantías de la factura y envío de documentos. Base temporal y datos ficticios; el correo se
sustituye por uno simulado: no se envía ningún mensaje real ni se contacta al SRI."""
import json
import sqlite3
import unittest
from unittest.mock import patch

import test_app
import test_invoicing
import app
import invoicing
import invoice_documents
import mail_pro

BODY = '# Políticas de prueba\n1. Ventas\nTexto ficticio de prueba para la vista previa del documento, sin valor comercial ni legal. ' * 4 + '\n- Viñeta ficticia\n- Otra viñeta ficticia'


class InvoiceDocumentsTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data
    paid_order = test_invoicing.InvoiceFlowTests.paid_order
    configure = test_invoicing.InvoiceFlowTests.configure

    def admin(self):
        self.cookie, self.csrf = self.login()
        self.post = lambda path, **body: self.request(path, body, cookie=self.cookie, csrf=self.csrf)
        self.get = lambda path: self.request(path, cookie=self.cookie)

    def policy(self, version='2026.10.1', scope='fisico', publish=True, body=BODY):
        made = self.post('/api/invoicing/policies', action='save', scope=scope, code='PCD-POL-VTA', version=version, title=invoice_documents.DEFAULT_TITLE, body=body)
        self.assertEqual(made['status'], 200, made['body'])
        if publish:
            done = self.post('/api/invoicing/policies', action='publish', id=str(made['body']['id']), validated_by='Asesoría legal ficticia', confirm='1')
            self.assertEqual(done['status'], 200, done['body'])
        return made['body']['id']

    def emitted(self, cents=4000, key='0001'):
        _, _, post, order = self.paid_order(cents, key=key)
        draft = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
        post('/api/invoicing/%d' % draft['id'], action='buyer', consumer_final='1') if cents <= 5000 else None
        done = post('/api/invoicing/%d' % draft['id'], action='emit', confirm='1')
        self.assertEqual(done['status'], 200, done['body'])
        return done['body']['invoice']['id'], order

    def test_policies_are_versioned_validated_and_frozen(self):
        self.admin()
        draft = self.post('/api/invoicing/policies', action='save', scope='fisico', code='PCD-POL-VTA', version='2026.10.1', title=invoice_documents.DEFAULT_TITLE, body='Texto corto')['body']['id']
        blocked = self.post('/api/invoicing/policies', action='publish', id=str(draft))
        self.assertEqual((blocked['status'], set(blocked['body']['fields'])), (400, {'body', 'validated_by', 'confirm'}))  # texto completo y validación legal
        self.assertEqual(self.post('/api/invoicing/policies', action='save', scope='fisico', code='X', version='2', title='Otro', body='')['status'], 409)  # un borrador por alcance
        self.assertEqual(self.post('/api/invoicing/policies', action='save', id=str(draft), scope='fisico', code='PCD-POL-VTA', version='2026.10.1', title=invoice_documents.DEFAULT_TITLE, body=BODY)['status'], 200)
        self.assertEqual(self.get('/api/invoicing/policies/%d.pdf' % draft)['body'][:5], b'%PDF-')  # vista previa del borrador
        self.assertEqual(self.post('/api/invoicing/policies', action='publish', id=str(draft), validated_by='Asesoría legal ficticia', confirm='1')['status'], 200)
        data = self.get('/api/invoicing/policies')['body']['scopes']['fisico']
        self.assertEqual((data['current']['version'], data['current']['legal_validated_by'], data['draft']), ('2026.10.1', 'Asesoría legal ficticia', None))
        self.assertEqual(self.post('/api/invoicing/policies', action='save', id=str(draft), scope='fisico', code='PCD-POL-VTA', version='2026.10.1', title='Cambio', body=BODY)['status'], 409)
        with app.connect() as c:
            for sql in ("UPDATE sales_policies SET body='otro' WHERE id=%d" % draft, 'DELETE FROM sales_policies WHERE id=%d' % draft):
                with self.assertRaises(sqlite3.DatabaseError):
                    c.execute(sql)
        second = self.policy('2026.11.1')
        data = self.get('/api/invoicing/policies')['body']['scopes']['fisico']
        self.assertEqual((data['current']['id'], [(h['version'], h['status']) for h in data['history']]), (second, [('2026.11.1', 'vigente'), ('2026.10.1', 'archivada')]))
        self.assertEqual(self.post('/api/invoicing/policies', action='save', scope='fisico', code='PCD-POL-VTA', version='2026.10.1', title='Repetida', body=BODY)['status'], 400)  # versión repetida
        self.assertEqual(self.post('/api/invoicing/policies', action='settings', auto='1', test_recipient='no-es-correo')['status'], 400)

    def test_invoice_keeps_the_policy_version_in_force_when_emitted(self):
        self.admin()
        self.configure(self.post)
        before, _ = self.emitted(key='0001')  # sin política vigente: no se asocia ninguna (no se reescribe la historia)
        first = self.policy('2026.10.1')
        after, _ = self.emitted(key='0002')
        self.policy('2026.11.1')
        with app.connect() as c:
            linked = {r[0]: r[1] for r in c.execute('SELECT invoice_id,policy_id FROM invoice_policies')}
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute('UPDATE invoice_policies SET policy_id=99')
        self.assertEqual(linked, {after: first})  # la factura conserva la 2026.10.1 aunque ya rija la 2026.11.1
        self.assertEqual(self.get('/api/invoicing/%d/politicas.pdf' % after)['body'][:5], b'%PDF-')
        self.assertEqual(self.get('/api/invoicing/%d/politicas.pdf' % before)['status'], 404)
        docs = self.get('/api/invoicing/%d/documents' % after)['body']
        self.assertEqual(([p['version'] for p in docs['policies']], docs['emitted'], docs['authorized']), (['2026.10.1'], True, False))
        self.assertEqual(self.get('/api/invoicing/%d/ride.pdf' % after)['body'][:5], b'%PDF-')
        _, _, post, order = self.paid_order(3000, key='0003')
        draft = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']['id']
        self.assertEqual(self.get('/api/invoicing/%d/ride.pdf' % draft)['status'], 409)  # sin emitir no hay RIDE

    def test_warranties_of_physical_products_follow_the_invoice(self):
        self.admin()
        self.configure(self.post)
        with app.connect() as c:
            category = c.execute("SELECT k.id FROM inventory_categories k JOIN inventory_categories p ON p.id=k.parent_id WHERE k.name='SSD M.2 NVMe'").fetchone()[0]
        made = self.post('/api/inventory/register', reason='inicial', cost='40,00', units=json.dumps([{'serial': 'NVME-FICT-1'}]),
                         product=json.dumps({'category_id': str(category), 'brand': 'Samsung', 'model': '980 1 TB', 'sku': 'MZ-V8V1T0', 'price': '80,00', 'warranty_store_qty': '1',
                                             'warranty_store_unit': 'anios', 'warranty_maker_qty': '5', 'warranty_maker_unit': 'anios'}))['body']
        catalog = made['item']['catalog_id']
        order = self.request('/api/orders', self.order_data({'email': 'cliente@example.invalid', 'request_key': 'docs-order-000001'}), cookie=self.cookie, csrf=self.csrf)['body']
        quote = self.post('/api/orders/%d/quote' % order['id'])['body']['id']
        self.post('/api/quotes/%d' % quote, action='save', items=[{'catalog_id': catalog, 'description': 'SSD ficticio', 'category': 'repuesto', 'quantity': 1, 'unit_cents': 8000, 'taxed': True}])
        self.post('/api/quotes/%d' % quote, action='send')
        with app.connect() as c:
            ids = [str(r[0]) for r in c.execute('SELECT id FROM quote_items WHERE quote_id=?', (quote,))]
        self.post('/api/quotes/%d' % quote, action='decide', approved=','.join(ids), note='Aprobó por teléfono (ficticio)')
        self.assertEqual(self.post('/api/orders/%d/payments' % order['id'], amount='80,00', method='efectivo')['status'], 201)
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(made['item']['id']), reason='uso_orden', order_code=order['code'], unit_ids=json.dumps([made['units'][0]['id']]))['status'], 200)
        draft = self.post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']['id']
        self.post('/api/invoicing/%d' % draft, action='emit', confirm='1')
        rows = self.get('/api/invoicing/%d/documents' % draft)['body']['warranties']
        unit = rows['units'][0]
        self.assertEqual((unit['internal_code'], unit['serial'], unit['brand'], unit['sku'], unit['store']['state'], unit['maker']['state']), ('PCD-NVME-000001', 'NVME-FICT-1', 'Samsung', 'MZ-V8V1T0', 'vigente', 'vigente'))
        self.assertGreater(unit['maker']['days_left'], unit['store']['days_left'])  # dos coberturas separadas
        self.assertEqual((rows['products'][0]['store_label'], rows['products'][0]['maker_label']), ('1 año · desde la venta', '5 años · desde la venta'))
        self.assertEqual(self.get('/api/invoicing/%d/garantias.pdf' % draft)['body'][:5], b'%PDF-')
        plain, _ = self.emitted(key='0009')
        self.assertEqual(self.get('/api/invoicing/%d/garantias.pdf' % plain)['status'], 404)

    def test_sending_only_authorized_invoices_once_with_controlled_retries(self):
        self.admin()
        self.configure(self.post)
        self.policy()
        invoice, _ = self.emitted(key='0001')
        sent = []
        fake = lambda c, kind, title, to, subject, body, order_id=None, actor=None, attachments=None, review=True, **k: sent.append((to, subject, [a['name'] for a in attachments], body))
        with patch.object(app, 'send_institutional', side_effect=fake):
            refused = self.post('/api/invoicing/%d/send' % invoice, kind='cliente')
            self.assertEqual(refused['status'], 409)  # una factura de prueba nunca se envía como comprobante autorizado
            self.assertIn('Solo se envían al cliente facturas autorizadas', refused['body']['error'])
            self.assertEqual(self.post('/api/invoicing/%d/send' % invoice, kind='prueba')['status'], 409)  # falta la dirección de prueba
            self.assertEqual(self.post('/api/invoicing/policies', action='settings', auto='1', test_recipient='pruebas@example.invalid')['status'], 200)
            test = self.post('/api/invoicing/%d/send' % invoice, kind='prueba')
            self.assertEqual(test['status'], 200, test['body'])
        to, subject, files, body = sent[-1]
        self.assertEqual(to, 'pruebas@example.invalid')
        self.assertTrue(subject.startswith('[PRUEBA — SIN VALIDEZ TRIBUTARIA]'))
        self.assertIn('no fue autorizada por el SRI', body)
        self.assertEqual([f.split('-')[0] for f in files], ['FACTURA', 'POLITICAS'])
        self.assertEqual(test['body']['mail'][0]['status'], 'enviado')
        # Factura autorizada en producción (simulada en la base temporal): una sola vez, con reintentos controlados.
        with app.connect() as c:
            c.execute("UPDATE invoices SET status='autorizado',environment='2',authorization_number='0'||access_key,authorized_at='2026-10-26T10:00:00',xml_authorized='<factura/>',buyer_email='cliente@example.invalid' WHERE id=?", (invoice,))
            c.commit()
        calls = {'n': 0}

        def flaky(c, kind, title, to, subject, body, order_id=None, actor=None, attachments=None, review=True, **k):
            calls['n'] += 1
            if calls['n'] == 1:
                raise mail_pro.MailError('red', 'Sin conexión (simulada).')
            sent.append((to, subject, [a['name'] for a in attachments], body))
        with patch.object(app, 'send_institutional', side_effect=flaky), patch.object(invoicing, 'TEST_MODE', False):
            first = self.post('/api/invoicing/%d/send' % invoice, kind='cliente')
            self.assertEqual(first['status'], 502)
            second = self.post('/api/invoicing/%d/send' % invoice, kind='cliente')
            self.assertEqual(second['status'], 200, second['body'])
            again = self.post('/api/invoicing/%d/send' % invoice, kind='cliente')
            self.assertTrue(again['body']['skipped'])  # una sola vez por factura
            self.assertEqual(self.post('/api/invoicing/%d/send' % invoice, kind='reenvio')['status'], 200)  # reenvío manual registrado
        self.assertEqual(calls['n'], 3)
        to, subject, files, body = sent[-1]
        self.assertEqual((to, subject.startswith('PC-DOCTOR S.A. | Factura'), [f.rsplit('.', 1)[1] for f in files]), ('cliente@example.invalid', True, ['pdf', 'xml', 'pdf']))
        log = self.get('/api/invoicing/%d/documents' % invoice)['body']['mail']
        client = next(m for m in log if m['kind'] == 'cliente')
        self.assertEqual((client['status'], client['attempts'], len([m for m in log if m['kind'] == 'reenvio'])), ('enviado', 2, 1))
        # Reintentos agotados: tras MAX_TRIES fallos no se insiste solo.
        other, _ = self.emitted(key='0002')
        with app.connect() as c:
            c.execute("UPDATE invoices SET status='autorizado',environment='2',buyer_email='cliente@example.invalid' WHERE id=?", (other,))
            c.commit()
        with patch.object(app, 'send_institutional', side_effect=mail_pro.MailError('red', 'Sin conexión (simulada).')), patch.object(invoicing, 'TEST_MODE', False):
            for _ in range(invoice_documents.MAX_TRIES):
                self.assertEqual(self.post('/api/invoicing/%d/send' % other, kind='cliente')['status'], 502)
            self.assertEqual(self.post('/api/invoicing/%d/send' % other, kind='cliente')['status'], 409)
        with app.connect() as c:
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute('DELETE FROM invoice_mail')
        tcookie, tcsrf = __import__('test_cash').CashTests.technician(self)
        self.assertEqual(self.request('/api/invoicing/policies', cookie=tcookie)['status'], 403)


if __name__ == '__main__':
    unittest.main()
