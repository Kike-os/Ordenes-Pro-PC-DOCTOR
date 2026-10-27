"""Facturación electrónica (solo ambiente de pruebas): cálculo exacto del IVA incluido, regla de consumidor final en el servidor,
una factura por operación, secuenciales sin repetición, clave de acceso con módulo 11 y XML. Base temporal y datos ficticios."""
import re
import unittest
import xml.etree.ElementTree as ET

import test_app
import test_quote_order_sync
import app
import invoicing
import sri_xml


def fake_ruc():
    """RUC ficticio de persona natural: una cédula válida generada aquí más «001»."""
    import reception
    for check in range(10):
        if reception.valid_cedula('170000000%d' % check):
            return '170000000%d001' % check


SETTINGS = {'ruc': fake_ruc(), 'legal_name': 'EMPRESA FICTICIA DE PRUEBAS S.A.', 'trade_name': 'FICTICIA', 'head_office_address': 'Dirección ficticia 123',
            'branch_address': 'Dirección ficticia 123', 'establishment': '001', 'emission_point': '001', 'keeps_accounts': 'SI', 'regime': 'general'}


class InvoiceMathTests(unittest.TestCase):
    def test_access_key_check_digit_matches_the_official_example(self):
        self.assertEqual(sri_xml.mod11('41261533'), 6)  # ficha técnica SRI v2.34, ejemplo del módulo 11
        from datetime import date
        key = sri_xml.access_key(date(2026, 10, 26), '01', SETTINGS['ruc'], '1', '001', '001', 7, '12345678')
        self.assertEqual(len(key), 49)
        self.assertEqual(key[:8], '26102026');self.assertEqual(key[8:10], '01');self.assertEqual(key[10:23], SETTINGS['ruc']);self.assertEqual(key[23], '1')
        self.assertEqual(key[24:30], '001001');self.assertEqual(key[30:39], '000000007');self.assertEqual(key[39:47], '12345678');self.assertEqual(key[47], '1')
        self.assertEqual(int(key[48]), sri_xml.mod11(key[:48]))

    def test_tax_split_is_exact_and_flags_the_few_unreachable_amounts(self):
        adjusted = 0
        for amount in range(1, 30001):
            base, tax, flag = invoicing.split_inclusive(amount, 1500)
            self.assertEqual(base + tax, amount)
            if flag:
                adjusted += 1
                self.assertLessEqual(abs(tax - (2 * base * 1500 + 10000) // 20000), 1)  # el ajuste nunca pasa de un centavo
            else:
                self.assertEqual(tax, (2 * base * 1500 + 10000) // 20000)  # IVA = base × 15 % redondeado al centavo
        self.assertLess(adjusted / 30000, 0.15)  # importes con IVA incluido sin base exacta (≈13 %): se marcan para revisar
        self.assertEqual(invoicing.split_inclusive(14535, 1500)[:2], (12639, 1896))  # orden real PCD-20261019-0005
        self.assertEqual(invoicing.split_inclusive(2500, 0), (2500, 0, False))

    def test_consumer_final_limit_is_fifty_dollars_inclusive(self):
        for cents, allowed in ((2000, True), (4999, True), (5000, True), (5001, False), (7500, False), (10000, False), (0, False)):
            self.assertEqual(invoicing.consumer_final_allowed(cents), allowed, cents)


class InvoiceFlowTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data
    form = test_quote_order_sync.QuoteOrderSyncTests.form
    prepare = test_quote_order_sync.QuoteOrderSyncTests.prepare

    def paid_order(self, cents, pay=True, key='0001'):
        """Orden con un presupuesto aprobado por el personal de `cents` (IVA incluido) y, si `pay`, totalmente pagada."""
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        order = post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'request_key': 'invoice-order-request-' + key}))['body']
        quote = post('/api/orders/%d/quote' % order['id'])['body']['id']
        post('/api/quotes/%d' % quote, action='save', items=[{'description': 'Servicio ficticio', 'category': 'servicio', 'quantity': 1, 'unit_cents': cents, 'taxed': True}])
        post('/api/quotes/%d' % quote, action='send')
        items = [i['id'] for i in self.request('/api/quotes/%d' % quote, cookie=cookie)['body']['quote']['items']]
        self.assertEqual(post('/api/quotes/%d' % quote, action='decide', approved=','.join(map(str, items)), note='Aprobó por teléfono (ficticio)')['status'], 200)
        if pay:
            self.assertEqual(post('/api/orders/%d/payments' % order['id'], amount='%d,%02d' % divmod(cents, 100), method='efectivo')['status'], 201)
        return cookie, csrf, post, order

    def configure(self, post):
        self.assertEqual(post('/api/invoicing/settings', **SETTINGS)['status'], 200)

    def test_permissions_and_blockers(self):
        cookie, csrf, post, order = self.paid_order(3000, pay=False)
        self.assertEqual(self.request('/api/invoicing')['status'], 401)
        eligible = self.request('/api/invoicing/eligibility?kind=orden&id=%d' % order['id'], cookie=cookie)['body']
        self.assertFalse(eligible['can_generate']);self.assertIn('no está totalmente pagada', ' '.join(eligible['blockers']))
        self.assertEqual(post('/api/invoicing/draft', kind='orden', id=str(order['id']))['status'], 409)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.request('/api/invoicing', cookie=cookie)['status'], 403)
        self.assertEqual(post('/api/invoicing/settings', **SETTINGS)['status'], 403)

    def test_full_flow_once_per_order_with_sequential_access_key_and_xml(self):
        cookie, csrf, post, order = self.paid_order(14535)
        draft = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']
        again = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']
        self.assertEqual(draft['invoice']['id'], again['invoice']['id'])  # idempotente: una sola factura por operación
        inv = draft['invoice']
        self.assertEqual((inv['status'], inv['subtotal_cents'], inv['tax_cents'], inv['total_cents']), ('borrador', 12639, 1896, 14535))
        self.assertEqual((inv['buyer_id_type'], inv['buyer_id'], inv['consumer_final']), ('05', '0100000017', 0))  # datos del cliente de la orden
        self.assertFalse(inv['consumer_final_allowed'])
        self.assertEqual([(p['sri_code'], p['amount_cents']) for p in draft['payments']], [('01', 14535)])
        path = '/api/invoicing/%d' % inv['id']
        self.assertEqual(post(path, action='emit')['status'], 400)  # sin confirmación
        missing = post(path, action='emit', confirm='1')
        self.assertEqual(missing['status'], 409);self.assertIn('Faltan datos fiscales', missing['body']['error'])
        self.configure(post)
        done = post(path, action='emit', confirm='1')['body']['invoice']
        self.assertEqual((done['status'], done['sequential'], done['number']), ('pendiente', 1, '001-001-000000001'))
        self.assertTrue(re.fullmatch(r'\d{49}', done['access_key']));self.assertEqual(int(done['access_key'][48]), sri_xml.mod11(done['access_key'][:48]))
        self.assertEqual(done['access_key'][23], '1')  # ambiente de pruebas
        self.assertEqual(post(path, action='emit', confirm='1')['status'], 409)  # no se emite dos veces
        with app.connect() as c:
            xml = c.execute('SELECT xml_unsigned FROM invoices WHERE id=?', (inv['id'],)).fetchone()[0]
            root = ET.fromstring(xml.split('\n', 1)[1])
            self.assertEqual((root.tag, root.get('version'), root.findtext('infoTributaria/ambiente'), root.findtext('infoTributaria/secuencial')), ('factura', '1.1.0', '1', '000000001'))
            self.assertEqual((root.findtext('infoFactura/importeTotal'), root.findtext('infoFactura/totalSinImpuestos'), root.findtext('infoFactura/totalConImpuestos/totalImpuesto/valor')),
                             ('145.35', '126.39', '18.96'))
            self.assertEqual(root.findtext('infoFactura/tipoIdentificacionComprador'), '05')
            self.assertEqual(root.findtext('detalles/detalle/impuestos/impuesto/codigoPorcentaje'), '4')
            # Un comprobante autorizado no se modifica ni se elimina; el historial es inmutable.
            c.execute("UPDATE invoices SET status='autorizado' WHERE id=?", (inv['id'],));c.commit()
            for sql in ("UPDATE invoices SET total_cents=1 WHERE id=%d" % inv['id'], 'DELETE FROM invoices WHERE id=%d' % inv['id'], 'UPDATE invoice_events SET detail=1', 'DELETE FROM invoice_events'):
                with self.assertRaises(Exception):
                    c.execute(sql)
        second_cookie = cookie
        _, _, post2, order2 = self.paid_order(2000, key='0002')
        draft2 = post2('/api/invoicing/draft', kind='orden', id=str(order2['id']))['body']['invoice']
        post2('/api/invoicing/%d' % draft2['id'], action='buyer', consumer_final='1')
        self.assertEqual(post2('/api/invoicing/%d' % draft2['id'], action='emit', confirm='1')['body']['invoice']['number'], '001-001-000000002')  # consecutivo
        listing = self.request('/api/invoicing', cookie=second_cookie)['body']
        self.assertEqual((listing['counts']['pendiente'], listing['counts']['autorizado']), (1, 1))
        # Indicadores del panel: solo lo registrado; las dos órdenes están pagadas, así que no hay saldos pendientes.
        s = listing['summary']
        self.assertEqual((s['emitted'], s['pending'], s['drafts'], s['to_send'], s['authorized'], s['rejected'], s['billed_cents'], s['unpaid_count'], s['unpaid_cents']),
                         (2, 1, 0, 1, 1, 0, 16535, 0, 0))
        self.assertEqual({r['number']: r['has_xml'] for r in listing['rows']}, {'001-001-000000001': True, '001-001-000000002': True})
        with app.connect() as c:  # un pago anulado después de facturar deja saldo en la orden ya facturada
            c.execute("UPDATE order_payments SET voided_at='2026-01-01 00:00:00',void_reason='prueba' WHERE order_id=?", (order2['id'],));c.commit()
        s = self.request('/api/invoicing', cookie=second_cookie)['body']['summary']
        self.assertEqual((s['unpaid_count'], s['unpaid_cents']), (1, 2000))

    def test_consumer_final_boundaries_are_enforced_by_the_server(self):
        results = {}
        for n, cents in enumerate((4999, 5000, 5001)):
            cookie, csrf, post, order = self.paid_order(cents, key='cf%02d' % n)
            draft = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
            answer = post('/api/invoicing/%d' % draft['id'], action='buyer', consumer_final='1')
            results[cents] = (answer['status'], draft['consumer_final_allowed'])
            if cents == 5001:
                self.assertIn('supera USD 50,00', answer['body']['error'])
                # Aunque alguien fuerce la base o la petición, la emisión vuelve a comprobarlo.
                with app.connect() as c:
                    c.execute("UPDATE invoices SET consumer_final=1,buyer_id_type='07',buyer_id='9999999999999',buyer_name='CONSUMIDOR FINAL' WHERE id=?", (draft['id'],));c.commit()
                self.configure(post)
                blocked = post('/api/invoicing/%d' % draft['id'], action='emit', confirm='1')
                self.assertEqual(blocked['status'], 409);self.assertIn('supera USD 50,00', blocked['body']['error'])
        self.assertEqual(results, {4999: (200, True), 5000: (200, True), 5001: (409, False)})

    def test_only_the_test_environment_and_discard_frees_the_operation(self):
        cookie, csrf, post, order = self.paid_order(2000)
        draft = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
        with app.connect() as c:
            with self.assertRaises(invoicing.InvoiceError):
                invoicing.emit(c, draft['id'], {'id': self.uid, 'name': 'Persona de prueba'}, app.reception_now(), environment='2')
        self.assertEqual(post('/api/invoicing/%d' % draft['id'], action='discard', reason='Prueba')['body']['invoice']['status'], 'descartado')
        fresh = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
        self.assertNotEqual(fresh['id'], draft['id'])
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM invoices WHERE source_kind='orden' AND source_id=? AND status!='descartado'", (order['id'],)).fetchone()[0], 1)
            with self.assertRaises(Exception):  # la base impide una segunda factura vigente para la misma operación
                c.execute("INSERT INTO invoices(source_kind,source_id,environment,created_at,updated_at) VALUES ('orden',?,'1','x','x')", (order['id'],))


if __name__ == '__main__':
    unittest.main()
