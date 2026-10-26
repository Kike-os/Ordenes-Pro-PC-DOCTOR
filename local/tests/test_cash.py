"""Cuentas bancarias (catálogo central), cierre de caja diario por usuario y depósitos con comprobante. Base temporal y datos
ficticios; no se mueve dinero ni se conecta con ningún banco."""
import base64
import re
import unittest
from unittest.mock import patch

import test_app
import test_invoicing
import app
import invoicing
import quotes

ACCOUNT = {'bank': 'Banco Ficticio del Austro', 'account_type': 'corriente', 'number': '1234567890', 'holder': 'EMPRESA FICTICIA DE PRUEBAS S.A.', 'holder_id': test_invoicing.fake_ruc()}
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 3_000_000  # comprobante ficticio de ~3 MB: viaja en varias partes


class CashTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data

    def technician(self):
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico1','t1@example.invalid','Técnico Ficticio',?, 'tecnico',0)", (self.hash,));c.commit()
        result = self.request('/api/login', {'login': 'tecnico1', 'password': 'contraseña-segura-de-prueba'})
        cookie = result['cookie'].split(';')[0]
        return cookie, self.request('/api/me', cookie=cookie)['body']['user']['csrf']

    def charged_order(self, post, cookie, key, cents):
        order = post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'request_key': 'cash-order-request-' + key}))['body']
        quote = post('/api/orders/%d/quote' % order['id'])['body']['id']
        post('/api/quotes/%d' % quote, action='save', items=[{'description': 'Servicio ficticio', 'category': 'servicio', 'quantity': 1, 'unit_cents': cents, 'taxed': True}])
        post('/api/quotes/%d' % quote, action='send')
        items = [i['id'] for i in self.request('/api/quotes/%d' % quote, cookie=cookie)['body']['quote']['items']]
        self.assertEqual(post('/api/quotes/%d' % quote, action='decide', approved=','.join(map(str, items)), note='Aprobó por teléfono (ficticio)')['status'], 200)
        return order

    def upload(self, post, raw, size=1_400_000):
        data = base64.b64encode(raw).decode()
        parts = [data[i:i + size] for i in range(0, len(data), size)]
        upload_id = ''
        for n, part in enumerate(parts):
            answer = post('/api/cash/upload', upload_id=upload_id, part=str(n), total=str(len(parts)), data=part)
            self.assertEqual(answer['status'], 200, answer['body'])
            upload_id = answer['body']['upload_id']
        return upload_id, len(parts)

    def test_bank_accounts_catalog(self):
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        bad = post('/api/bank-accounts', action='save', bank='B', account_type='plazo', number='12', holder='', holder_id='x')
        self.assertEqual(bad['status'], 400);self.assertEqual(set(bad['body']['fields']), {'bank', 'account_type', 'number', 'holder', 'holder_id'})
        rows = post('/api/bank-accounts', action='save', **ACCOUNT)['body']['rows']
        self.assertEqual((rows[0]['label'], rows[0]['is_default'], rows[0]['active']), ('Banco Ficticio del Austro · Corriente · 1234567890', 1, 1))
        self.assertIn('Número de cuenta: 1234567890', rows[0]['copy_text'])
        self.assertEqual(post('/api/bank-accounts', action='save', **dict(ACCOUNT, number='12-3456-7890'))['status'], 409)  # misma cuenta, aunque se escriba con guiones
        second = post('/api/bank-accounts', action='save', **dict(ACCOUNT, number='9876543210', account_type='ahorros'))['body']['rows']
        other = next(r for r in second if r['number'] == '9876543210')
        self.assertEqual(other['is_default'], 0)
        post('/api/bank-accounts', action='default', id=str(other['id']))
        rows = self.request('/api/bank-accounts', cookie=cookie)['body']['rows']
        self.assertEqual([r['number'] for r in rows if r['is_default']], ['9876543210'])  # una sola predeterminada
        post('/api/bank-accounts', action='deactivate', id=str(rows[0]['id']))
        with app.connect() as c:
            with self.assertRaises(Exception):
                c.execute('DELETE FROM bank_accounts')
        tcookie, tcsrf = self.technician()
        listed = self.request('/api/bank-accounts', cookie=tcookie)['body']
        self.assertEqual(([r['number'] for r in listed['rows']], listed['can_manage']), (['1234567890'], False))  # solo activas
        self.assertEqual(self.request('/api/bank-accounts', dict(ACCOUNT, action='save', number='5555555555'), cookie=tcookie, csrf=tcsrf)['status'], 403)

    @patch.object(invoicing, 'TEST_MODE', False)  # comportamiento previsto al activar la facturación
    def test_daily_closing_per_user_deposits_and_reconciliation(self):
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        account = post('/api/bank-accounts', action='save', **ACCOUNT)['body']['rows'][0]
        order = self.charged_order(post, cookie, '000001', 10000)
        self.assertEqual(post('/api/orders/%d/payments' % order['id'], amount='80,00', method='efectivo')['status'], 201)
        post('/api/orders/%d/payments' % order['id'], amount='20,00', method='transferencia')
        day = self.request('/api/cash/day', cookie=cookie)['body']
        self.assertEqual((day['live']['cash_cents'], day['live']['total_cents'], day['live']['count'], day['closing']), (8000, 10000, 2, None))
        # Si el contado no coincide, hay que explicarlo; el cierre es único por persona y día.
        self.assertEqual(post('/api/cash/close', counted_cash='75,00')['status'], 400)
        closed = post('/api/cash/close', counted_cash='75,00', notes='Faltan $5 por un vuelto (ficticio)')['body']['closing']
        self.assertEqual((closed['expected_cash_cents'], closed['counted_cash_cents'], closed['difference_cents'], closed['to_deposit_cents']), (8000, 7500, -500, 7500))
        self.assertEqual(post('/api/cash/close', counted_cash='75,00', notes='Otra vez')['status'], 409)
        with app.connect() as c:
            with self.assertRaises(Exception):
                c.execute('UPDATE cash_closings SET counted_cash_cents=1')
        # Depósito pendiente: no supera lo contado y un reintento con la misma clave no lo duplica.
        self.assertEqual(post('/api/cash/deposits', closing_id=str(closed['id']), bank_account_id=str(account['id']), amount='80,00')['status'], 409)
        made = post('/api/cash/deposits', closing_id=str(closed['id']), bank_account_id=str(account['id']), amount='75,00', request_key='deposit-key-0000001')['body']
        post('/api/cash/deposits', closing_id=str(closed['id']), bank_account_id=str(account['id']), amount='75,00', request_key='deposit-key-0000001')
        deposit = made['deposits'][0]
        self.assertEqual((len(self.request('/api/cash/day', cookie=cookie)['body']['deposits']), deposit['status']), (1, 'pendiente'))
        # Confirmar exige fecha, comprobante y archivo; el archivo (~3 MB) llega por partes y se verifica.
        path = '/api/cash/deposits/%d' % deposit['id']
        self.assertEqual(set(post(path, action='confirm')['body']['fields']), {'deposit_date', 'voucher_number', 'file'})
        bad_id, _ = self.upload(post, b'MZ' + b'0' * 1000)
        self.assertIn('JPG, PNG o PDF', post(path, action='confirm', deposit_date=app.reception_now().date().isoformat(), voucher_number='A-1001', upload_id=bad_id)['body']['error'])
        upload_id, parts = self.upload(post, PNG)
        self.assertGreater(parts, 2)
        done = post(path, action='confirm', deposit_date=app.reception_now().date().isoformat(), voucher_number='A-1001', upload_id=upload_id, file_name='comprobante.png')['body']['deposits'][0]
        self.assertEqual((done['status'], done['voucher_number'], done['file']['mime'], done['file']['size']), ('depositado', 'A-1001', 'image/png', len(PNG)))
        got = self.request(path + '/file', cookie=cookie)
        self.assertEqual(got['status'], 200)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM cash_upload_parts').fetchone()[0], 1)  # solo queda la subida rechazada (de otra prueba)
        # Conciliar es solo de administración; un técnico no ve ni confirma la caja de otra persona.
        tcookie, tcsrf = self.technician()
        self.assertEqual(self.request(path, {'action': 'reconcile'}, cookie=tcookie, csrf=tcsrf)['status'], 403)
        self.assertEqual(self.request('/api/cash/day?user=%d' % self.uid, cookie=tcookie)['body']['user']['name'], 'Técnico Ficticio')  # el parámetro se ignora: ve su caja
        self.assertEqual(post(path, action='reconcile')['body']['deposits'][0]['status'], 'conciliado')
        self.assertEqual(post(path, action='void', reason='Prueba de anulación')['status'], 409)  # conciliado: no se anula
        history = self.request('/api/cash/history', cookie=cookie)['body']
        self.assertEqual((len(history['rows']), history['rows'][0]['deposit_summary']['conciliado']), (1, 7500))

    def test_duplicate_voucher_size_limit_and_late_movements(self):
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        account = post('/api/bank-accounts', action='save', **ACCOUNT)['body']['rows'][0]
        order = self.charged_order(post, cookie, '000002', 10000)
        self.assertEqual(post('/api/orders/%d/payments' % order['id'], amount='60,00', method='efectivo')['status'], 201)
        closed = post('/api/cash/close', counted_cash='60,00')['body']['closing']
        one = post('/api/cash/deposits', closing_id=str(closed['id']), bank_account_id=str(account['id']), amount='30,00')['body']['deposits'][0]
        two = post('/api/cash/deposits', closing_id=str(closed['id']), bank_account_id=str(account['id']), amount='30,00')['body']['deposits'][1]
        today = app.reception_now().date().isoformat()
        up, _ = self.upload(post, b'%PDF-1.4 ficticio')
        self.assertEqual(post('/api/cash/deposits/%d' % one['id'], action='confirm', deposit_date=today, voucher_number='B-77', upload_id=up)['status'], 200)
        up2, _ = self.upload(post, b'%PDF-1.4 otro ficticio')
        dup = post('/api/cash/deposits/%d' % two['id'], action='confirm', deposit_date=today, voucher_number='B-77', upload_id=up2)
        self.assertEqual(dup['status'], 409);self.assertIn('ya está registrado', dup['body']['error'])
        big, _ = self.upload(post, b'%PDF-' + b'0' * (5 * 1024 * 1024))
        self.assertIn('hasta 5 MB', post('/api/cash/deposits/%d' % two['id'], action='confirm', deposit_date=today, voucher_number='B-78', upload_id=big)['body']['error'])
        self.assertEqual(post('/api/cash/deposits/%d' % two['id'], action='void')['status'], 400)  # motivo obligatorio
        self.assertEqual(post('/api/cash/deposits/%d' % two['id'], action='void', reason='Se depositó todo junto')['body']['deposits'][1]['status'], 'anulado')
        # Un cobro posterior al cierre no cambia el cierre: se avisa.
        post('/api/orders/%d/payments' % order['id'], amount='5,00', method='efectivo')
        view = self.request('/api/cash/day', cookie=cookie)['body']
        self.assertEqual((view['closing']['expected_cash_cents'], len(view['closing']['late_movements'])), (6000, 1))

    @patch.object(invoicing, 'TEST_MODE', False)  # comportamiento previsto al activar la facturación
    def test_bank_account_in_quotes_and_invoices(self):
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        account = post('/api/bank-accounts', action='save', **ACCOUNT)['body']['rows'][0]
        order = post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'request_key': 'cash-order-request-000003'}))['body']
        quote = post('/api/orders/%d/quote' % order['id'])['body']['id']
        post('/api/quotes/%d' % quote, action='save', items=[{'description': 'Servicio ficticio', 'category': 'servicio', 'quantity': 1, 'unit_cents': 3000, 'taxed': True}])
        detail = self.request('/api/quotes/%d' % quote, cookie=cookie)['body']['quote']
        self.assertEqual(detail['bank_account']['number'], '1234567890')  # predeterminada mientras no se elija otra
        self.assertEqual(post('/api/quotes/%d' % quote, action='bank', bank_account_id='999')['status'], 404)
        self.assertEqual(post('/api/quotes/%d' % quote, action='bank', bank_account_id=str(account['id']))['body']['quote']['bank_account']['id'], account['id'])
        link = post('/api/quotes/%d' % quote, action='send')['body']['link']
        page = self.request('/presupuesto/' + link.rsplit('/', 1)[1])
        form = test_invoicing.InvoiceFlowTests.form(self, '/presupuesto/' + link.rsplit('/', 1)[1], {'last4': '0017'})['body']
        self.assertIn('Datos para depósito o transferencia', form);self.assertIn('1234567890', form);self.assertIn('data-copy-bank', form)
        self.assertEqual(self.request('/api/quotes/%d/pdf' % quote, cookie=cookie)['body'][:4], b'%PDF')
        # Factura: la cuenta elegida aparece en la vista y en la información adicional del XML.
        items = [i['id'] for i in self.request('/api/quotes/%d' % quote, cookie=cookie)['body']['quote']['items']]
        post('/api/quotes/%d' % quote, action='decide', approved=','.join(map(str, items)), note='Aprobó por teléfono (ficticio)')
        post('/api/orders/%d/payments' % order['id'], amount='30,00', method='transferencia')
        draft = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
        chosen = post('/api/invoicing/%d' % draft['id'], action='bank', bank_account_id=str(account['id']))['body']
        self.assertEqual(chosen['bank_account']['number'], '1234567890')
        post('/api/invoicing/settings', **test_invoicing.SETTINGS)
        post('/api/invoicing/%d' % draft['id'], action='emit', confirm='1')
        with app.connect() as c:
            xml = c.execute('SELECT xml_unsigned FROM invoices WHERE id=?', (draft['id'],)).fetchone()[0]
        self.assertIn('<campoAdicional nombre="Cuenta para depósito">Banco Ficticio del Austro · Corriente · 1234567890', xml)


    def test_test_mode_keeps_real_records_and_client_documents_unchanged(self):
        """MODO DE PRUEBAS (producción hasta la activación): presupuestos y páginas del cliente sin cambios; caja solo para administración."""
        self.assertTrue(invoicing.TEST_MODE)
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        account = post('/api/bank-accounts', action='save', **ACCOUNT)['body']['rows'][0]
        order = post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'request_key': 'cash-order-request-000004'}))['body']
        quote = post('/api/orders/%d/quote' % order['id'])['body']['id']
        post('/api/quotes/%d' % quote, action='save', items=[{'description': 'Servicio ficticio', 'category': 'servicio', 'quantity': 1, 'unit_cents': 3000, 'taxed': True}])
        detail = self.request('/api/quotes/%d' % quote, cookie=cookie)['body']['quote']
        self.assertEqual((detail['bank_account'], detail['bank_enabled']), (None, False))
        self.assertEqual(post('/api/quotes/%d' % quote, action='bank', bank_account_id=str(account['id']))['status'], 409)
        with app.connect() as c:
            self.assertIsNone(c.execute('SELECT bank_account_id FROM quotes WHERE id=?', (quote,)).fetchone()[0])  # el presupuesto no cambió
        link = post('/api/quotes/%d' % quote, action='send')['body']['link']
        form = test_invoicing.InvoiceFlowTests.form(self, '/presupuesto/' + link.rsplit('/', 1)[1], {'last4': '0017'})['body']
        self.assertNotIn('Datos para depósito o transferencia', form);self.assertNotIn('1234567890', form)
        pdf = self.request('/api/quotes/%d/pdf' % quote, cookie=cookie)['body']
        self.assertEqual(pdf[:4], b'%PDF');self.assertNotIn(b'1234567890', pdf)
        self.assertEqual(self.request('/api/cash/day', cookie=cookie)['status'], 200)  # administración prueba la caja
        tcookie, tcsrf = self.technician()
        self.assertEqual(self.request('/api/cash/day', cookie=tcookie)['status'], 403)
        self.assertEqual(self.request('/api/cash/close', {'day': '', 'counted_cash': '0,00'}, cookie=tcookie, csrf=tcsrf)['status'], 403)
        self.assertTrue(self.request('/api/invoicing/settings', cookie=cookie)['body']['settings']['test_mode'])


if __name__ == '__main__':
    unittest.main()
