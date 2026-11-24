"""Premium Billing Center · reportes y exportaciones de facturación. Base temporal, datos ficticios y SOLO el ambiente de pruebas:
no se envía nada al SRI ni a clientes. Cubre: facturado frente a cobrado (con un pago anulado después de facturar), filtro por forma de
pago, separación por ambiente, indicadores anuales, notas de crédito sin inventar valores, exportaciones Excel/CSV/PDF con los mismos
filtros y auditoría, que nada cambia en los comprobantes, y acceso solo de administración."""
import unittest

import test_invoicing as base
import app


class InvoiceReportTests(unittest.TestCase):
    B = base.InvoiceFlowTests
    setUpClass = classmethod(B.setUpClass.__func__)
    setUp, tearDown, request, login = B.setUp, B.tearDown, B.request, B.login
    order_data, form, prepare, paid_order, configure = B.order_data, B.form, B.prepare, B.paid_order, B.configure

    def build(self):
        """A: 10,00 pagada y emitida. B: 25,00 sin pagar (crédito) y emitida. C: 40,00 pagada, borrador."""
        cookie, csrf, post, a = self.paid_order(1000, key='rep-a')
        self.configure(post)
        ids = {}
        for name, cents, pay, emit in (('a', 1000, True, True), ('b', 2500, False, True), ('c', 4000, True, False)):
            if name != 'a':
                cookie, csrf, post, a = self.paid_order(cents, pay=pay, key='rep-' + name)
            inv = post('/api/invoicing/draft', kind='orden', id=str(a['id']))['body']['invoice']
            if emit:
                self.assertEqual(post('/api/invoicing/%d' % inv['id'], action='emit', confirm='1')['status'], 200)
            ids[name] = (inv['id'], a['id'])
        self.cookie = cookie
        return ids

    def report(self, q=''):
        got = self.request('/api/invoicing/report?' + q, cookie=self.cookie)
        self.assertEqual(got['status'], 200, got['body'])
        return got['body']

    def snapshot(self):
        with app.connect() as c:
            return tuple(c.execute('SELECT COUNT(*),COALESCE(SUM(total_cents),0),(SELECT COUNT(*) FROM invoice_events),(SELECT COUNT(*) FROM invoice_payments),'
                                   "(SELECT group_concat(status||COALESCE(sequential,''),',') FROM invoices) FROM invoices").fetchone())

    def test_billed_versus_collected_and_payment_filter(self):
        ids = self.build()
        before = self.snapshot()
        r = self.report()
        self.assertEqual(r['environment'], '1')                                                     # ambiente vigente en pruebas
        self.assertEqual((r['documents'], r['billed_documents'], r['billed_cents'], r['collected_cents'], r['outstanding_cents']), (3, 2, 3500, 1000, 2500))
        self.assertEqual(r['by_status'], {'pendiente': 2, 'borrador': 1})
        self.assertEqual({m['method']: m['amount_cents'] for m in r['by_method']}, {'efectivo': 1000, 'credito': 2500})
        self.assertEqual(self.report('method=credito')['billed_cents'], 2500)
        cash = self.report('method=efectivo')
        self.assertEqual((cash['documents'], cash['billed_cents']), (2, 1000))                        # el borrador entra en la lista pero no suma
        listed = self.request('/api/invoicing?method=credito', cookie=self.cookie)['body']
        self.assertEqual([row['id'] for row in listed['rows']], [ids['b'][0]])
        self.assertIn('credito', listed['payment_filters'])
        self.assertEqual(self.report('status=borrador')['billed_cents'], 0)
        self.assertEqual(self.report('method=x%27%20OR%201=1')['documents'], 3)                          # valor no válido: se ignora, sin inyección
        self.assertEqual(self.report('method=cheque')['documents'], 0)
        self.assertEqual(self.report('from=2001-01-01&to=2001-12-31')['documents'], 0)
        # Un cobro anulado DESPUÉS de facturar deja saldo: lo cobrado baja aunque la factura conserve su forma de pago.
        with app.connect() as c:
            c.execute("UPDATE order_payments SET voided_at=? WHERE order_id=?", (app.reception_now().isoformat(), ids['a'][1]));c.commit()
        after = self.report()
        self.assertEqual((after['billed_cents'], after['collected_cents'], after['outstanding_cents']), (3500, 0, 3500))
        self.assertEqual(self.snapshot()[:4], before[:4])                                             # los reportes no cambian comprobantes ni pagos

    def test_environments_are_never_mixed_and_annual_and_credit_notes(self):
        self.build()
        test = self.report()
        self.assertEqual(test['annual']['year_cents'], 3500)
        self.assertEqual(test['annual']['prev_year_cents'], 0)
        self.assertEqual(sum(m['billed_cents'] for m in test['annual']['months']), 3500)
        self.assertEqual(test['credit_notes'], {'count': 0, 'total_cents': 0})                    # registrado: ninguna (no se inventa)
        prod = self.report('env=2')
        self.assertEqual((prod['environment_label'], prod['documents'], prod['billed_cents'], prod['annual']['year_cents']), ('Producción', 0, 0, 0))

    def test_exports_use_the_same_filters_are_audited_and_admin_only(self):
        self.build()
        before = self.snapshot()
        with app.connect() as c:
            audits = c.execute("SELECT COUNT(*) FROM audit WHERE action LIKE 'invoice_report_%'").fetchone()[0]
        got = {}
        for fmt in ('xlsx', 'csv', 'pdf'):
            got[fmt] = self.request('/api/invoicing/report.%s?method=credito' % fmt, cookie=self.cookie)
            self.assertEqual(got[fmt]['status'], 200, fmt)
        self.assertTrue(got['xlsx']['body'].startswith(b'PK'))
        self.assertTrue(got['pdf']['body'].startswith(b'%PDF'))
        text = got['csv']['body'].decode('utf-8-sig')
        lines = [line for line in text.splitlines() if line.strip()]
        self.assertTrue(lines[0].startswith('Comprobante;Ambiente;Emisión;Cliente'))
        self.assertEqual(len(lines), 2)                                                              # solo la factura a crédito
        self.assertIn('Crédito (tarjeta de crédito o saldo a crédito)', lines[1])
        self.assertIn('25,00', lines[1])
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action LIKE 'invoice_report_%'").fetchone()[0], audits + 3)
        self.assertEqual(self.snapshot(), before)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        for path in ('/api/invoicing/report', '/api/invoicing/report.csv', '/api/invoicing/report.pdf'):
            self.assertEqual(self.request(path, cookie=self.cookie)['status'], 403)
        self.assertEqual(self.request('/api/invoicing/report.csv')['status'], 401)


if __name__ == '__main__':
    unittest.main()
