"""Registrar pago (1.5.225): las cuentas activas del Centro de Cuentas Bancarias llegan a la orden; transferencia o depósito con
comprobante adjunto en el archivo central (enlazado a la transferencia por conciliar); pagos parciales, completos y mixtos; sin
duplicados por doble clic ni pagos por encima del saldo. Base temporal y datos ficticios; no se mueve dinero."""
import base64
import unittest

import test_app
import test_cash
import app

app.os.environ.setdefault('LOGIN_CAPTCHA', 'off')
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 2048  # comprobante ficticio


class PaymentProofTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data
    charged_order = test_cash.CashTests.charged_order
    technician = test_cash.CashTests.technician

    def upload(self, post):
        answer = post('/api/files/upload', upload_id='', part='0', total='1', data=base64.b64encode(PNG).decode())
        self.assertEqual(answer['status'], 200, answer['body'])
        return answer['body']['upload_id']

    def test_transfer_with_proof_partial_full_mixed_and_no_duplicates(self):
        cookie, csrf = self.login()
        post = lambda path, **data: self.request(path, data, cookie=cookie, csrf=csrf)
        order = self.charged_order(post, cookie, 'proof-1', 10000)  # $100,00 por cobrar
        oid = order['id']
        self.assertEqual(self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']['bank_accounts'], [])  # sin cuentas: la ventana lo avisa
        account = post('/api/bank-accounts', action='save', **test_cash.ACCOUNT)['body']['rows'][0]
        accounts = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']['bank_accounts']
        self.assertEqual([(a['bank'], a['number'], a['type_label']) for a in accounts], [(account['bank'], account['number'], 'Corriente')])
        pay = lambda key, **data: post('/api/orders/%d/payments' % oid, request_key=key, **data)
        # El comprobante solo acompaña a una transferencia o un depósito.
        self.assertEqual(pay('pago-prueba-efectivo-000001', amount='10,00', method='efectivo', proof_upload_id=self.upload(post), proof_name='x.png')['status'], 400)
        # Abono por transferencia con comprobante: queda en el archivo central y enlazado a la transferencia por conciliar.
        first = pay('pago-prueba-transfer-000001', amount='40,00', method='transferencia', bank_account_id=str(account['id']), reference='TRX-123456',
                    proof_upload_id=self.upload(post), proof_name='comprobante.png')
        self.assertEqual(first['status'], 201, first['body'])
        self.assertEqual(first['body']['balance_cents'], 6000)
        again = pay('pago-prueba-transfer-000001', amount='40,00', method='transferencia', bank_account_id=str(account['id']), reference='TRX-123456')
        self.assertEqual((again['status'], again['body'].get('duplicate')), (200, True), again['body'])  # doble clic: no se registra dos veces
        rows = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']['payments']
        self.assertEqual(len([r for r in rows if r['kind'] == 'pago']), 1)
        row = rows[-1]
        self.assertTrue(row['proof'] and row['transfer_id'])
        self.assertEqual((row['bank'], row['reference']), (account['bank'] + ' · ' + account['number'], 'TRX-123456'))
        file = self.request('/api/bank/transfers/%d/file' % row['transfer_id'], cookie=cookie)
        self.assertEqual((file['status'], file['body'][:8]), (200, PNG[:8]))
        with app.connect() as c:
            stored = c.execute('SELECT t.status,t.file_id,f.kind,f.size FROM bank_transfers t JOIN payment_files f ON f.id=t.file_id WHERE t.payment_id=?', (row['id'],)).fetchone()
        self.assertEqual(tuple(stored)[2:], ('transferencia', len(PNG)))
        self.assertEqual(stored['status'], 'pendiente')  # un comprobante no es dinero verificado
        # Más que el saldo: se rechaza. El resto, en un pago mixto (efectivo + depósito con comprobante).
        self.assertEqual(pay('pago-prueba-excede-0000001', amount='70,00', method='efectivo')['status'], 400)
        import json
        mixed = pay('pago-prueba-mixto-00000001', amount='60,00', lines=json.dumps([{'method': 'efectivo', 'amount': '20,00'},
                    {'method': 'deposito', 'amount': '40,00', 'bank_account_id': str(account['id']), 'reference': 'DEP-998877'}]), proof_upload_id=self.upload(post), proof_name='deposito.png')
        self.assertEqual(mixed['status'], 201, mixed['body'])
        self.assertEqual(mixed['body']['balance_cents'], 0)
        rows = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']['payments']
        self.assertEqual(sorted((r['method'], r['amount_cents'], r['proof']) for r in rows if r['kind'] == 'pago'),
                         [('deposito', 4000, True), ('efectivo', 2000, False), ('transferencia', 4000, True)])
        # Un técnico que no registró el pago no descarga el comprobante.
        tech_cookie, tech_csrf = self.technician()
        self.assertIn(self.request('/api/bank/transfers/%d/file' % row['transfer_id'], cookie=tech_cookie)['status'], (403, 404))


if __name__ == '__main__':
    unittest.main()
