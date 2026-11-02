"""Centro de Ventas: la venta confirmada descuenta el inventario (Kardex «Venta», serie elegida, cliente), no descuenta dos veces, no factura
sin existencias y devuelve lo vendido si el borrador se descarta. Base temporal y datos ficticios; nada se emite al SRI."""
import json
import threading
import unittest

import test_invoicing
import test_inventory_center as base
import test_license_sales
import test_cash
import app


class SalesCenterTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    configure = Base.configure
    admin, category, new, more = (getattr(base.InventoryCenterTests, n) for n in ('admin', 'category', 'new', 'more'))

    def product(self, serials):
        made = self.new(self.category('SSD SATA 2.5"', 'Almacenamiento'), 'Kingston', 'A400 960 GB', units=serials, cost='20,00')
        self.assertEqual(made['status'], 200, made['body'])
        return made['body']['item']['id']

    def units(self, item):
        with app.connect() as c:
            return {r['serial']: (r['id'], r['status'], r['client_id']) for r in c.execute('SELECT id,serial,status,client_id FROM inventory_units WHERE item_id=?', (item,))}

    def sale(self, item, quantity, lines=1, key='venta-directa-000001'):
        items = [{'inventory_item_id': str(item), 'description': 'SSD ficticio', 'quantity': str(quantity), 'unit_price': '40,00'} for _ in range(lines)]
        with app.connect() as c:
            client = c.execute("SELECT id FROM clients WHERE identification='0100000017'").fetchone()
            client = client[0] if client else c.execute("INSERT INTO clients(name,phone,identification) VALUES ('Cliente Ficticio','0990000000','0100000017')").lastrowid
        made = self.post('/api/proformas', origin='directa', items=json.dumps(items), client_id=str(client), request_key=key)
        self.assertEqual(made['status'], 200, made['body'])
        return made['body']['id']

    def test_confirmed_sale_moves_inventory_once_with_chosen_serials(self):
        self.admin()
        item = self.product(['VS-1', 'VS-2', 'VS-3'])
        units = self.units(item)
        pid = self.sale(item, 2)
        wrong = self.post('/api/proformas/%d' % pid, action='checkout', payments='[]', units=json.dumps({str(item): [units['VS-1'][0]]}))
        self.assertEqual(wrong['status'], 409)  # dos vendidas, una serie elegida: no se factura nada
        with app.connect() as c:
            self.assertIsNone(c.execute('SELECT invoice_id FROM proformas WHERE id=?', (pid,)).fetchone()[0])
        chosen = {str(item): [units['VS-3'][0], units['VS-1'][0]]}
        done = self.post('/api/proformas/%d' % pid, action='checkout', payments='[]', units=json.dumps(chosen))
        self.assertEqual(done['status'], 200, done['body'])
        invoice = done['body']['invoice_id']
        after = self.units(item)
        self.assertEqual((after['VS-1'][1], after['VS-2'][1], after['VS-3'][1]), ('vendida', 'disponible', 'vendida'))
        self.assertIsNotNone(after['VS-1'][2])  # la unidad queda a nombre del cliente
        again = self.post('/api/proformas/%d' % pid, action='checkout', payments='[]', units=json.dumps(chosen))
        self.assertEqual(again['body']['invoice_id'], invoice)
        with app.connect() as c:
            rows = c.execute("SELECT direction,quantity,reason,sale_price_cents FROM inventory_movements WHERE reference_kind='factura' AND reference_id=?", (invoice,)).fetchall()
            self.assertEqual([tuple(r) for r in rows], [(-1, 2, 'venta', 4000)])  # una sola salida, con el precio cobrado
        # Descartar el borrador devuelve las mismas unidades (una sola vez).
        self.assertEqual(self.post('/api/invoicing/%d' % invoice, action='discard', reason='Venta ficticia anulada')['status'], 200)
        back = self.units(item)
        self.assertEqual((back['VS-1'][1], back['VS-3'][1]), ('disponible', 'disponible'))
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM inventory_movements WHERE reference_kind='factura' AND reference_id=? AND direction=1", (invoice,)).fetchone()[0], 1)

    def test_sale_without_stock_creates_no_invoice_and_repeated_lines_are_summed(self):
        self.admin()
        item = self.product(['VQ-1', 'VQ-2'])
        pid = self.sale(item, 2, lines=2, key='venta-directa-000002')  # dos líneas del mismo producto: 4 unidades y solo hay 2
        short = self.post('/api/proformas/%d' % pid, action='checkout', payments='[]')
        self.assertEqual(short['status'], 409, short['body'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM invoices').fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT status FROM proformas WHERE id=?", (pid,)).fetchone()[0], 'borrador')
        self.assertEqual({s for _, s, _ in self.units(item).values()}, {'disponible'})
        ok = self.post('/api/proformas/%d' % self.sale(item, 1, lines=2, key='venta-directa-000003'), action='checkout', payments='[]')
        self.assertEqual(ok['status'], 200, ok['body'])  # sin elegir series: salen las más antiguas
        self.assertEqual(sorted(s for _, s, _ in self.units(item).values()), ['vendida', 'vendida'])

    def test_center_panel_history_reports_and_requests(self):
        self.admin()
        item = self.product(['VP-1', 'VP-2'])
        paid = self.post('/api/proformas/%d' % self.sale(item, 1, key='venta-directa-000004'), action='checkout', payments=json.dumps([{'method': 'efectivo', 'amount': '40'}]))
        self.assertEqual(paid['status'], 200, paid['body'])
        self.sale(item, 1, key='venta-directa-000005')  # borrador: venta sin confirmar, no cuenta como venta
        d = self.get('/api/sales/dashboard')['body']
        self.assertEqual((d['today']['count'], d['today']['total_cents'], d['month']['count'], d['pending']['drafts'], d['pending']['to_emit']), (1, 4000, 1, 1, 1))
        self.assertEqual((d['collections']['count'], d['top'][0]['name'], d['top'][0]['quantity']), (0, 'SSD ficticio', 1))
        history = self.get('/api/sales/history')['body']['rows']
        self.assertEqual([(r['kind'], r['state'], r['paid_cents'], r['invoice_status']) for r in history], [('directa', 'pagada', 4000, 'borrador')])
        self.assertEqual(self.get('/api/sales/history?kind=licencia')['body']['rows'], [])
        self.assertEqual(self.get('/api/sales/history?from=2026-13-01')['status'], 400)
        report = self.get('/api/sales/report?group=producto')['body']
        self.assertEqual([(g['label'], g['count'], g['total_cents']) for g in report['rows']], [('SSD ficticio', 1, 4000)])
        self.assertEqual(self.get('/api/sales/report?group=usuario')['body']['totals'], {'count': 1, 'total_cents': 4000})
        self.assertEqual(self.get('/api/sales/report?group=otro')['status'], 400)
        self.assertEqual(self.get('/api/sales/report?from=2026-11-05&to=2026-11-01')['status'], 400)
        # Anular la venta (descartar el borrador de factura): sigue en el historial como anulada y deja de sumar.
        self.assertEqual(self.post('/api/invoicing/%d' % paid['body']['invoice_id'], action='discard', reason='Venta ficticia anulada')['status'], 200)
        self.assertEqual(self.get('/api/sales/history')['body']['rows'][0]['state'], 'anulada')
        self.assertEqual(self.get('/api/sales/dashboard')['body']['today']['count'], 0)
        # Pedidos comerciales: sin duplicados por reenvío, estados válidos, cancelación con motivo y sin borrado.
        with app.connect() as c:
            client = c.execute("SELECT id FROM clients WHERE identification='0100000017'").fetchone()[0]
        body = dict(client_id=str(client), kind='producto', description='Disco SSD 2 TB ficticio', quantity='2', estimate='180,00', request_key='pedido-comercial-0000001')
        made = self.post('/api/sales/requests', **body)
        self.assertEqual(made['status'], 200, made['body'])
        self.assertEqual(made['body']['request']['code'], 'PED-000001')
        self.assertEqual(self.post('/api/sales/requests', **body)['body']['id'], made['body']['id'])
        self.assertEqual(self.post('/api/sales/requests', description='Sin cliente')['status'], 400)
        rid = made['body']['id']
        path = '/api/sales/requests/%d' % rid
        self.assertEqual(self.post(path, action='status', status='entregado', sale_code='PF-999999')['status'], 404)  # venta inexistente: no se cierra
        self.assertEqual(self.post(path, action='status', status='recibido')['status'], 200)
        self.assertEqual(self.post(path, action='status', status='pedido_proveedor')['status'], 409)
        self.assertEqual(self.post(path, action='status', status='cancelado', note='no')['status'], 400)
        self.assertEqual(self.post(path, action='status', status='cancelado', note='El cliente ya no lo necesita')['status'], 200)
        detail = self.get(path)['body']
        self.assertEqual((detail['request']['status'], detail['request']['next'], len(detail['events'])), ('cancelado', [], 3))
        self.assertEqual(self.get('/api/sales/requests')['body']['rows'], [])  # «Abiertos» por omisión
        self.assertEqual(len(self.get('/api/sales/requests?status=todos')['body']['rows']), 1)
        with app.connect() as c:
            for sql in ('DELETE FROM sales_requests', 'DELETE FROM sales_request_events', "UPDATE sales_request_events SET detail='x'"):
                with self.assertRaises(app.sqlite3.DatabaseError):
                    c.execute(sql)
        self.assertEqual(self.post('/api/sales/from-order', order_code='PCD-00000000-0000')['status'], 404)

    def test_sales_center_is_admin_only(self):
        self.admin()
        cookie, csrf = test_cash.CashTests.technician(self)
        self.assertEqual(self.request('/api/sales/dashboard', cookie=cookie)['status'], 403)
        self.assertEqual(self.request('/api/sales/history', cookie=cookie)['status'], 403)
        self.assertEqual(self.request('/api/sales/requests', {'description': 'Pedido ficticio'}, cookie=cookie, csrf=csrf)['status'], 403)

    def test_concurrent_sales_never_take_the_same_last_unit(self):
        self.admin()
        item = self.product(['CC-1'])
        first, second = self.sale(item, 1, key='venta-concurrente-0001'), self.sale(item, 1, key='venta-concurrente-0002')
        gate, results = threading.Barrier(2), []

        def buy(pid):
            gate.wait()
            results.append(self.post('/api/proformas/%d' % pid, action='checkout', payments='[]')['status'])
        threads = [threading.Thread(target=buy, args=(pid,)) for pid in (first, second)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(sorted(results), [200, 409])  # una sola venta se lleva la última unidad; la otra no factura nada
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM inventory_movements WHERE item_id=? AND reason='venta'", (item,)).fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM invoices').fetchone()[0], 1)

    def test_credit_note_returns_sold_units_once(self):
        self.admin()
        item = self.product(['NC-1', 'NC-2'])
        made = self.post('/api/proformas/%d' % self.sale(item, 2, key='venta-directa-000006'), action='checkout', payments='[]')
        invoice = made['body']['invoice_id']
        self.configure(self.post)
        self.assertEqual(self.post('/api/invoicing/%d' % invoice, action='emit', confirm='1')['body']['invoice']['status'], 'pendiente')
        detail = self.get('/api/invoicing/%d' % invoice)['body']
        self.assertTrue(detail['invoice']['stock_out'])
        line = detail['items'][0]['id']
        part = self.post('/api/credit-notes', invoice_id=str(invoice), reason='Devolución ficticia de una unidad', scope='parcial', lines=json.dumps([{'item_id': line, 'quantity': 1}]), return_stock='1')
        self.assertEqual(part['status'], 200, part['body'])
        self.assertEqual(sorted(s for _, s, _ in self.units(item).values()), ['disponible', 'vendida'])
        rest = self.post('/api/credit-notes', invoice_id=str(invoice), reason='Devolución ficticia del resto', scope='total', return_stock='1')
        self.assertEqual(rest['status'], 200, rest['body'])
        self.assertEqual({s for _, s, _ in self.units(item).values()}, {'disponible'})
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT SUM(quantity) FROM inventory_movements WHERE item_id=? AND reference_kind='nota_credito' AND direction=1", (item,)).fetchone()[0], 2)
        self.assertEqual(self.post('/api/credit-notes', invoice_id=str(invoice), reason='Otra nota ficticia', scope='total', return_stock='1')['status'], 409)


class LicenseAssignTests(unittest.TestCase):
    """«Asignar o entregar licencia» entrega sin venta ni cobro; las ventas de licencias aparecen en el Centro de Ventas."""
    Base = test_license_sales.LicenseSalesTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    admin, new_product, client_id, stock, catalog, sale = Base.admin, Base.new_product, Base.client_id, Base.stock, Base.catalog, Base.sale

    def test_assignment_records_no_price_and_sales_show_in_center(self):
        av, ms, client = self.catalog()
        given = self.post('/api/licenses/deliver', assign=True, client_id=str(client), product_id=str(av), send_mail=False)
        self.assertEqual(given['status'], 200, given['body'])
        with app.connect() as c:
            row = c.execute('SELECT price_cents,discount_cents,payment_status FROM license_deliveries ORDER BY id DESC LIMIT 1').fetchone()
            self.assertEqual(tuple(row), (None, 0, ''))  # sin precio ni estado de pago
            self.assertEqual(c.execute('SELECT COUNT(*) FROM license_sales').fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM license_units WHERE status='entregada' AND client_id=?", (client,)).fetchone()[0], 1)
        self.assertEqual(self.get('/api/sales/history')['body']['rows'], [])  # una asignación no es una venta
        made = self.sale(client, [{'product_id': ms, 'quantity': 1}])
        self.assertEqual(made['status'], 201, made['body'])
        rows = self.get('/api/sales/history')['body']['rows']
        self.assertEqual([(r['kind'], r['code'], r['state'], r['delivery'], r['balance_cents']) for r in rows], [('licencia', made['body']['code'], 'por_cobrar', 'pendiente', 9990)])
        self.assertEqual(self.get('/api/sales/dashboard')['body']['pending']['to_deliver'], 1)


if __name__ == '__main__':
    unittest.main()
