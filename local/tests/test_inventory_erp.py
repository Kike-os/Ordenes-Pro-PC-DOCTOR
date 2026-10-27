"""Centro de Inventario (auditoría y rediseño): estados de existencias y alertas, costo obligatorio y correcciones auditadas, precios y ventas con
autorización, historial de ventas, reservas con cliente y vencimiento, licencias por revisar, revisión de datos, Kardex por período y reportes.
Base temporal y datos ficticios."""
import io
import json
import sqlite3
import unittest
import zipfile
from datetime import timedelta

import test_app
import test_inventory_center as base
import app


class InventoryErpTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data
    admin, category, new, more, client, order = (getattr(base.InventoryCenterTests, n) for n in ('admin', 'category', 'new', 'more', 'client', 'order'))

    def ssd(self, cost='20,00', **extra):
        made = self.new(self.category('SSD SATA 2.5"', 'Almacenamiento'), 'Kingston', 'A400 480 GB', units=['S-1'], cost=cost, **extra)
        self.assertEqual(made['status'], 200, made['body'])
        return made['body']['item']['id'], made['body']['units'][0]['id']

    def test_stock_states_alerts_and_required_cost(self):
        self.admin()
        cat = self.category('Pasta térmica', 'Consumibles de servicio técnico')
        rows = {}
        for model, qty, minimum in (('Cero', None, '1'), ('Critico', 1, '3'), ('Minimo', 2, '2'), ('Normal', 5, '2')):
            body = dict(product=json.dumps({'category_id': str(cat), 'brand': 'Arctic', 'model': model, 'price': '9,00', 'min_stock': minimum}), reason='inicial', cost='4,00', quantity=str(qty or 1))
            made = self.post('/api/inventory/register', **body)['body']
            rows[model] = made['item']['id']
        out = self.post('/api/inventory/exit', item_id=str(rows['Cero']), reason='baja', quantity='1')
        self.assertEqual(out['status'], 200, out['body'])
        states = {p['model']: (p['stock_state'], p['urgent']) for p in self.get('/api/inventory/products')['body']['rows']}
        self.assertEqual(states, {'Cero': ('agotado', True), 'Critico': ('critico', True), 'Minimo': ('minimo', False), 'Normal': ('normal', False)})
        cards = self.get('/api/inventory/center')['body']['cards']
        self.assertEqual((cards['out'], cards['critical'], cards['at_min'], cards['low']), (1, 1, 1, 2))
        self.assertEqual(self.post('/api/inventory/products', action='alerts_off', id=str(rows['Critico']))['status'], 200)  # sin reposición automática
        cards = self.get('/api/inventory/center')['body']['cards']
        self.assertEqual(cards['low'], 1)
        self.assertEqual([p['model'] for p in self.get('/api/inventory/products?state=sin_alertas')['body']['rows']], ['Critico'])
        # Costo obligatorio: vacío ya no se guarda como 0; un 0 escrito expresamente sí se acepta.
        missing = self.post('/api/inventory/register', item_id=str(rows['Normal']), reason='compra', quantity='1')
        self.assertEqual((missing['status'], list(missing['body']['fields'])), (400, ['cost']))
        self.assertEqual(self.post('/api/inventory/register', item_id=str(rows['Normal']), reason='compra', quantity='1', cost='0')['status'], 200)

    def test_cost_correction_is_audited_and_feeds_the_weighted_average(self):
        self.admin()
        ssd, _ = self.ssd(cost='0')
        self.assertEqual(self.more(ssd, units=['S-2'], cost='30,00')['status'], 200)
        sheet = self.get('/api/inventory/products/%d/sheet' % ssd)['body']
        self.assertEqual(sheet['product']['average_cost_cents'], 1500)  # (0 + 30) / 2: la entrada sin costo arrastra el promedio
        self.assertIn('cost', [a['field'] for a in sheet['alerts']])
        zero = next(e for e in sheet['entries'] if e['cost_cents'] == 0)
        self.assertEqual(self.post('/api/inventory/cost-correction', movement_id=str(zero['id']), cost='20,00', reason='x')['status'], 400)  # motivo obligatorio
        fixed = self.post('/api/inventory/cost-correction', movement_id=str(zero['id']), cost='20,00', reason='Costo real según factura del proveedor', document='FAC-001')
        self.assertEqual(fixed['status'], 200, fixed['body'])
        self.assertEqual(fixed['body']['product']['average_cost_cents'], 2500)  # (20 + 30) / 2
        with app.connect() as c:
            original = c.execute('SELECT unit_cost_cents FROM inventory_movements WHERE id=?', (zero['id'],)).fetchone()[0]
            self.assertEqual(original, 0)  # el movimiento original no cambia
            for sql in ('UPDATE inventory_cost_corrections SET new_cost_cents=1', 'DELETE FROM inventory_cost_corrections'):
                with self.assertRaises(sqlite3.DatabaseError):
                    c.execute(sql)
        kardex = self.get('/api/inventory/kardex?item_id=%d' % ssd)['body']
        types = [(r['type'], r.get('corrected', False), r.get('cost_pending', False)) for r in kardex['rows']]
        self.assertEqual(types, [('entrada', True, False), ('entrada', False, False), ('correccion', False, False)])
        self.assertIn('FAC-001', kardex['rows'][2]['document'])
        report = self.get('/api/inventory/report.xlsx?kind=sin_costo')['body']
        self.assertNotIn('A400', zipfile.ZipFile(io.BytesIO(report)).read('xl/worksheets/sheet1.xml').decode())  # ya no figura sin costo

    def test_pricing_sales_authorization_history_and_reservations(self):
        self.admin()
        ssd, u1 = self.ssd(warranty_store_qty='1', warranty_store_unit='anios', warranty_store_from='entrega', warranty_maker_qty='3', warranty_maker_unit='anios')
        units = [u['id'] for u in self.more(ssd, units=['S-2', 'S-3'], cost='20,00')['body']['units']]
        priced = self.post('/api/inventory/products', action='pricing', id=str(ssd), price='34,50', min_price='30,00', max_discount='5')
        self.assertEqual(priced['status'], 200, priced['body'])
        sheet = self.get('/api/inventory/products/%d/sheet' % ssd)['body']
        p = sheet['pricing']
        self.assertEqual((p['price_cents'], p['net_cents'], p['tax_cents'], p['cost_cents'], p['margin_cents']), (3450, 3000, 450, 2000, 1000))
        self.assertEqual(self.post('/api/inventory/products', action='pricing', id=str(ssd), price='34,50', min_price='40,00', max_discount='5')['status'], 400)  # mínimo > precio
        client = self.client()
        # Descuento mayor al autorizado o precio $0: exige autorización administrativa expresa con motivo.
        over = self.post('/api/inventory/exit', item_id=str(ssd), reason='venta', unit_ids=json.dumps([u1]), client_id=str(client), discount='10')
        self.assertEqual((over['status'], list(over['body']['fields'])), (409, ['authorization']))
        free = self.post('/api/inventory/exit', item_id=str(ssd), reason='venta', unit_ids=json.dumps([u1]), unit_price='0')
        self.assertEqual(free['status'], 409)
        self.assertIn('$0,00', free['body']['error'])
        sale = self.post('/api/inventory/exit', item_id=str(ssd), reason='venta', unit_ids=json.dumps([u1]), client_id=str(client), discount='5', document='Nota de venta 9 (ficticia)', delivered='0')
        self.assertEqual(sale['status'], 200, sale['body'])
        authorized = self.post('/api/inventory/exit', item_id=str(ssd), reason='venta', unit_ids=json.dumps([units[0]]), unit_price='25,00', authorize='1',
                               authorization='Liquidación de equipo de exhibición (ficticio)')
        self.assertEqual(authorized['status'], 200, authorized['body'])
        history = self.get('/api/inventory/products/%d/sheet' % ssd)['body']['sales']
        self.assertEqual([(h['price_cents'], h['discount_cents'], bool(h['authorization'])) for h in history], [(2500, 0, True), (3277, 173, False)])  # 5 % de 34,50 = 1,725 → 1,73 (redondeo comercial)
        self.assertEqual(history[1]['units'][0]['internal_code'], 'PCD-SSD-000001')
        unit = self.get('/api/inventory/units/%d' % u1)['body']
        self.assertEqual((unit['store_warranty_from'], unit['warranty']['store']['state'], unit['maker_warranty_from'] != ''), ('', 'pendiente_entrega', True))  # no se activa antes de la entrega
        # Reserva con cliente y vencimiento: reduce lo disponible, no las existencias.
        today = app.reception_now().date()
        self.assertEqual(self.post('/api/inventory/reservations', action='reserve', item_id=str(ssd), unit_ids=json.dumps([units[1]]), reference='Cliente ficticio', client_id=str(client),
                                   expires_at=(today - timedelta(days=1)).isoformat())['status'], 400)
        res = self.post('/api/inventory/reservations', action='reserve', item_id=str(ssd), unit_ids=json.dumps([units[1]]), reference='Separado por el cliente', client_id=str(client),
                        expires_at=(today + timedelta(days=3)).isoformat())
        self.assertEqual(res['status'], 200, res['body'])
        sheet = self.get('/api/inventory/products/%d/sheet' % ssd)['body']
        self.assertEqual((sheet['product']['stock'], sheet['product']['available'], sheet['reservations'][0]['client'] != '', sheet['reservations'][0]['expired']), (1, 0, True, False))
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(ssd), reason='venta', unit_ids=json.dumps([units[1]]))['status'], 409)  # reservada para otra operación

    def test_kardex_period_totals_reports_licenses_and_review(self):
        self.admin()
        ssd, u1 = self.ssd(cost='20,00')
        self.assertEqual(self.new(self.category('DDR4', 'Memorias RAM'), 'Kingston', 'Fury 8 GB', units=['R-1'], cost='')['status'], 400)
        self.post('/api/inventory/exit', item_id=str(ssd), reason='uso_orden', order_code=self.order('000077')['code'], unit_ids=json.dumps([u1]))
        today = app.reception_now().date().isoformat()
        data = self.get('/api/inventory/kardex?from=%s&to=%s' % (today, today))['body']
        t = data['totals']
        self.assertEqual((t['rows'], t['entries'], t['exits'], t['opening'], t['closing'], t['stock_units']), (2, 1, 1, 0, 0, 0))
        self.assertEqual(data['previous']['rows'], 0)
        self.assertEqual([r['kind'] for r in data['rows']], ['inicial', 'salida'])
        self.assertEqual(self.get('/api/inventory/kardex?document=orden')['body']['totals']['rows'], 1)
        for kind in ('general', 'categoria', 'producto', 'periodo', 'valorizado', 'sin_costo', 'ajustes', 'responsable'):
            extra = '&category_id=%d' % self.category('Almacenamiento') if kind == 'categoria' else '&item_id=%d' % ssd if kind == 'producto' else ''
            pdf = self.get('/api/inventory/report.pdf?kind=%s%s' % (kind, extra))
            self.assertEqual((pdf['status'], pdf['body'][:5]), (200, b'%PDF-'), kind)
            book = self.get('/api/inventory/report.xlsx?kind=%s%s' % (kind, extra))['body']
            self.assertEqual(book[:2], b'PK', kind)
        sheet = zipfile.ZipFile(io.BytesIO(self.get('/api/inventory/report.xlsx?kind=valorizado')['body'])).read('xl/worksheets/sheet1.xml').decode()
        self.assertIn('<v>20.00</v>', sheet)  # números utilizables, no texto con «$»
        self.assertEqual(self.get('/api/inventory/report.pdf?kind=producto')['status'], 400)
        # Licencias: la duración que no coincide con el nombre se señala sin cambiarla.
        answer = self.post('/api/licenses/new', name='Antivirus ficticio de Duración Ilimitada', brand='Kaspersky', line='antivirus', model='suscripcion', edition='2026', description='Prueba',
                           devices='1', duration='anual', validity_mode='activacion', price='30', purchase_price='18,50', supplier='Mayorista ficticio', key='KASP-FICT-ILIM-0001')
        self.assertEqual(answer['status'], 201, answer['body'])
        table = self.get('/api/inventory/licenses/table')['body']
        row = next(r for r in table['rows'] if r['id'] == answer['body']['product_id'])
        self.assertEqual((row['state'], row['duration'], row['stock']['disponible']), ('revisar', 'Anual', 1))
        self.assertNotIn('KASP-FICT-ILIM-0001', json.dumps(table))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT duration FROM license_products WHERE item_id=?', (answer['body']['product_id'],)).fetchone()[0], 'anual')  # no se modificó
            c.execute("INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('WD GREEN','2026-10-26','2026-10-26')")
            c.commit()
        review = self.get('/api/inventory/review')['body']
        kinds = {f['kind'] for f in review['findings']}
        self.assertTrue({'marca', 'licencia'} <= kinds, kinds)
        self.assertEqual(review['counts']['error'], 0)


if __name__ == '__main__':
    unittest.main()
