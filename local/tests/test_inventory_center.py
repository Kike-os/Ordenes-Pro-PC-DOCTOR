"""Centro de Inventario: códigos por categoría, series, inventario inicial, Kardex valorizado, ventas, consumo en órdenes sin doble descuento,
reservas, traslados, garantías, licencias clasificadas, importación, etiquetas y exportaciones. Base temporal y datos ficticios."""
import base64
import io
import json
import sqlite3
import unittest
import zipfile
from datetime import date, timedelta

import test_app
import test_invoicing
import app
import inventory_center

SECRET = 'KASP-FICT-0000-AAAA-1111'


class InventoryCenterTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data
    technician = __import__('test_cash').CashTests.technician

    def admin(self):
        self.cookie, self.csrf = self.login()
        self.post = lambda path, **body: self.request(path, body, cookie=self.cookie, csrf=self.csrf)
        self.get = lambda path: self.request(path, cookie=self.cookie)

    def category(self, name, parent=None):
        with app.connect() as c:
            if parent:
                return c.execute("SELECT k.id FROM inventory_categories k JOIN inventory_categories p ON p.id=k.parent_id WHERE k.name=? AND p.name=?", (name, parent)).fetchone()[0]
            return c.execute('SELECT id FROM inventory_categories WHERE name=? AND parent_id IS NULL', (name,)).fetchone()[0]

    def new(self, category, brand, model, units=None, quantity=None, cost='18,50', **product):
        fields = dict(category_id=str(category), brand=brand, model=model, price='35,00', min_stock='1', **product)
        body = dict(product=json.dumps(fields), reason='inicial', cost=cost, location='Bodega A')
        if units is not None:
            body['units'] = json.dumps([{'serial': s} for s in units])
        if quantity is not None:
            body['quantity'] = str(quantity)
        return self.post('/api/inventory/register', **body)

    def more(self, item_id, units=None, quantity=None, cost='18,50', reason='inicial', key=''):
        body = dict(item_id=str(item_id), reason=reason, cost=cost)
        if units is not None:
            body['units'] = json.dumps([{'serial': s} for s in units])
        if quantity is not None:
            body['quantity'] = str(quantity)
        if key:
            body['request_key'] = key
        return self.post('/api/inventory/register', **body)

    def ssd(self, **warranty):
        made = self.new(self.category('SSD SATA 2.5"', 'Almacenamiento'), 'Kingston', 'A400 256 GB', units=['691918TM'], cost='20,00', **warranty)
        self.assertEqual(made['status'], 200, made['body'])
        return made['body']['item']['id'], made['body']['units'][0]['id']

    def client(self):
        with app.connect() as c:
            row = c.execute("SELECT id FROM clients WHERE identification='0100000017'").fetchone()
        if row:
            return row[0]
        self.request('/api/orders', self.order_data({'email': 'cliente@example.invalid', 'request_key': 'center-client-000001'}), cookie=self.cookie, csrf=self.csrf)
        return self.client()

    def order(self, key):
        return self.request('/api/orders', self.order_data({'email': 'cliente@example.invalid', 'request_key': 'center-order-' + key}), cookie=self.cookie, csrf=self.csrf)['body']

    def test_codes_by_category_serials_duplicates_and_initial_inventory(self):
        self.admin()
        first = self.new(self.category('SSD SATA 2.5"', 'Almacenamiento'), 'Kingston', 'A400 256 GB', units=['691918TM'])
        self.assertEqual(first['status'], 200, first['body'])
        ssd = first['body']['item']['id']
        self.assertEqual([(u['internal_code'], u['serial']) for u in first['body']['units']], [('PCD-SSD-000001', '691918TM')])
        second = self.more(ssd, units=['691919TM'])
        self.assertEqual([(u['internal_code'], u['serial']) for u in second['body']['units']], [('PCD-SSD-000002', '691919TM')])  # misma ficha, otra unidad
        detail = self.get('/api/inventory/products/%d' % ssd)['body']
        self.assertEqual((detail['product']['stock'], detail['product']['tracking'], len(detail['units'])), (2, 'serie', 2))
        # Duplicados: la misma serie (aunque cambien espacios o mayúsculas), dentro del mismo ingreso, o la misma ficha otra vez.
        dup = self.more(ssd, units=[' 691918tm '])
        self.assertEqual(dup['status'], 409)
        self.assertIn('PCD-SSD-000001', dup['body']['error'])
        self.assertEqual(self.more(ssd, units=['AAA111', 'aaa111'])['status'], 409)
        self.assertTrue(self.get('/api/inventory/serial-check?serial=691919tm')['body']['exists'])
        self.assertFalse(self.get('/api/inventory/serial-check?serial=NUEVA-0001')['body']['exists'])
        again = self.new(self.category('SSD SATA 2.5"', 'Almacenamiento'), 'KINGSTON', 'a400 256 gb', units=['X1'])
        self.assertEqual((again['status'], list(again['body']['fields'])), (400, ['model']))
        # Sin serie del fabricante: solo código interno; la serie se agrega después (y corregirla exige motivo).
        bare = self.more(ssd, units=[''])['body']['units'][0]
        self.assertEqual((bare['internal_code'], bare['serial']), ('PCD-SSD-000003', ''))
        self.assertEqual(self.post('/api/inventory/units/%d' % bare['id'], action='serial', serial='691920TM')['status'], 200)
        self.assertEqual(self.post('/api/inventory/units/%d' % bare['id'], action='serial', serial='691921TM')['status'], 400)
        self.assertEqual(self.post('/api/inventory/units/%d' % bare['id'], action='serial', serial='691918TM', reason='Etiqueta mal leída')['status'], 409)
        # Códigos por categoría (prefijo propio o heredado de la categoría principal).
        codes = {}
        for name, parent, brand, model in (('SSD M.2 NVMe', 'Almacenamiento', 'Samsung', '980 1 TB'), ('DDR4', 'Memorias RAM', 'Kingston', 'Fury 8 GB'), ('Portátiles', 'Computadoras', 'Lenovo', 'IdeaPad 3'),
                                           ('Fuentes ATX', 'Fuentes de alimentación', 'Corsair', 'CV550'), ('Intel', 'Placas madre', 'ASUS', 'Prime H610M'), ('Epson', 'Impresoras', 'Epson', 'L3250')):
            made = self.new(self.category(name, parent), brand, model, units=[model.replace(' ', '') + '-S1'])
            self.assertEqual(made['status'], 200, made['body'])
            codes[name] = made['body']['units'][0]['internal_code']
        self.assertEqual(codes, {'SSD M.2 NVMe': 'PCD-NVME-000001', 'DDR4': 'PCD-RAM-000001', 'Portátiles': 'PCD-LAP-000001', 'Fuentes ATX': 'PCD-FUE-000001',
                                 'Intel': 'PCD-PLM-000001', 'Epson': 'PCD-IMP-000001'})
        # A granel: cantidad sin serializar.
        paste = self.new(self.category('Pasta térmica', 'Consumibles de servicio técnico'), 'Arctic', 'MX-4 4 g', quantity=10, cost='4,20')
        self.assertEqual((paste['status'], paste['body']['item']['tracking'], paste['body']['item']['stock'], paste['body']['units']), (200, 'granel', 10, []))
        # Prefijos: únicos y no reutilizables; cambiar y volver no reinicia la numeración.
        nvme = self.category('SSD M.2 NVMe', 'Almacenamiento')
        self.assertEqual(self.post('/api/inventory/categories', action='save', name='Discos nuevos', parent_id=str(self.category('Almacenamiento')), prefix='SSD')['status'], 409)
        self.assertEqual(self.post('/api/inventory/categories', action='save', id=str(nvme), name='SSD M.2 NVMe', prefix='NVM2')['status'], 200)
        self.assertEqual(self.post('/api/inventory/categories', action='save', id=str(nvme), name='SSD M.2 NVMe', prefix='NVME')['status'], 200)
        nvme_item = self.get('/api/inventory/products?q=980')['body']['rows'][0]['id']
        self.assertEqual(self.more(nvme_item, units=['S2-980'])['body']['units'][0]['internal_code'], 'PCD-NVME-000002')
        with app.connect() as c:
            for sql in ("UPDATE inventory_prefixes SET category_id=1 WHERE prefix='SSD'", "DELETE FROM inventory_prefixes WHERE prefix='SSD'", "UPDATE inventory_units SET internal_code='X' WHERE id=1",
                        'DELETE FROM inventory_units', 'DELETE FROM inventory_movement_units', 'DELETE FROM inventory_categories'):
                with self.assertRaises(sqlite3.DatabaseError):
                    c.execute(sql)
        # Kardex: el inventario inicial es el movimiento de apertura de cada producto.
        rows = self.get('/api/inventory/kardex?item_id=%d' % ssd)['body']['rows']
        self.assertEqual([(r['reason'], r['entry'], r['balance']) for r in rows], [('inicial', 1, 1), ('inicial', 1, 2), ('inicial', 1, 3)])
        self.assertEqual(self.get('/api/inventory/kardex?serial=691920tm')['body']['rows'][0]['units'][0]['internal_code'], 'PCD-SSD-000003')
        # Búsqueda por código interno, serie, marca, nombre y categoría.
        for q in ('PCD-SSD-000002', '691919', 'kingston a400', 'Almacenamiento'):
            self.assertIn(ssd, [p['id'] for p in self.get('/api/inventory/search?q=' + q.replace(' ', '+'))['body']['products']], q)
        # Persistencia: lo registrado está en la base (al reabrirla sigue ahí).
        with sqlite3.connect(app.DB) as raw:
            self.assertEqual(raw.execute('SELECT COUNT(*) FROM inventory_units').fetchone()[0], 10)

    def test_kardex_weighted_average_sale_order_consumption_reservations_and_no_double_discount(self):
        self.admin()
        ssd, u1 = self.ssd(warranty_store_qty='1', warranty_store_unit='anios', warranty_maker_qty='3', warranty_maker_unit='anios')
        units = [u['id'] for u in self.more(ssd, units=['S-2', 'S-3'], cost='20,00')['body']['units']]
        u2, u3 = units
        client = self.client()
        today = app.reception_now().date()
        sale = dict(item_id=str(ssd), reason='venta', unit_ids=json.dumps([u1]), client_id=str(client), document='Nota de venta 001 (ficticia)', request_key='venta-ficticia-000000001')
        self.assertEqual(self.post('/api/inventory/exit', **dict(sale, unit_ids='[]'))['status'], 400)  # una salida con serie exige las unidades
        first = self.post('/api/inventory/exit', **sale)
        self.assertEqual(first['status'], 200, first['body'])
        self.assertEqual(self.post('/api/inventory/exit', **sale)['body']['movement_id'], first['body']['movement_id'])  # reintento: una sola salida
        unit = self.get('/api/inventory/units/%d' % u1)['body']
        self.assertEqual((unit['status'], unit['client_id'], unit['store_warranty_from'], unit['store_warranty_to'], unit['maker_warranty_to']),
                         ('vendida', client, today.isoformat(), today.replace(year=today.year + 1).isoformat(), today.replace(year=today.year + 3).isoformat()))
        # Compra posterior: costo promedio ponderado móvil (3×20 − 1×20 + 2×30) / 4 = 25.
        self.assertEqual(self.more(ssd, units=['S-4', 'S-5'], cost='30,00', reason='compra')['status'], 200)
        product = self.get('/api/inventory/products/%d' % ssd)['body']['product']
        self.assertEqual((product['stock'], product['average_cost_cents'], product['value_cents']), (4, 2500, 10000))
        # Consumo en una orden técnica: una sola salida por orden y producto.
        order = self.order('000001')
        used = self.post('/api/inventory/exit', item_id=str(ssd), reason='uso_orden', order_code=order['code'], unit_ids=json.dumps([u2]))
        self.assertEqual(used['status'], 200, used['body'])
        twice = self.post('/api/inventory/exit', item_id=str(ssd), reason='uso_orden', order_code=order['code'], unit_ids=json.dumps([u3]))
        self.assertEqual(twice['status'], 409)
        self.assertIn('no se descuenta dos veces', twice['body']['error'])
        self.assertEqual(self.get('/api/inventory/products/%d' % ssd)['body']['product']['stock'], 3)
        # Reserva: no descuenta; nadie más puede sacar la unidad reservada; liberarla la devuelve.
        reserved = self.post('/api/inventory/reservations', action='reserve', item_id=str(ssd), unit_ids=json.dumps([u3]), reference='Presupuesto ficticio 15')
        self.assertEqual(reserved['status'], 200, reserved['body'])
        product = self.get('/api/inventory/products/%d' % ssd)['body']['product']
        self.assertEqual((product['stock'], product['reserved'], product['available']), (3, 1, 2))
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(ssd), reason='venta', unit_ids=json.dumps([u3]))['status'], 409)
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(ssd), reason='venta', unit_ids=json.dumps([u3]), reservation_id=str(reserved['body']['id']))['status'], 200)  # la venta consume la reserva
        self.assertEqual(self.get('/api/inventory/reservations')['body']['rows'], [])
        # A granel: reservado 8 de 10, solo 2 libres.
        paste = self.new(self.category('Pasta térmica', 'Consumibles de servicio técnico'), 'Arctic', 'MX-4 4 g', quantity=10, cost='4,20')['body']['item']['id']
        hold = self.post('/api/inventory/reservations', action='reserve', item_id=str(paste), quantity='8', reference='Mantenimiento ficticio')['body']['id']
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(paste), reason='uso_orden', order_code=order['code'], quantity='5')['status'], 409)
        self.assertEqual(self.post('/api/inventory/reservations', action='release', id=str(hold))['status'], 200)
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(paste), reason='uso_orden', order_code=order['code'], quantity='5')['status'], 200)
        # Traslado: cambia la ubicación, no las existencias.
        free = [u['id'] for u in self.get('/api/inventory/units?item=%d&status=disponible' % ssd)['body']['rows']]
        self.assertEqual(self.post('/api/inventory/transfer', item_id=str(ssd), unit_ids=json.dumps(free[:1]), to_location='Vitrina')['status'], 200)
        self.assertEqual(self.get('/api/inventory/units/%d' % free[0])['body']['location'], 'Vitrina')
        kardex = self.get('/api/inventory/kardex?item_id=%d' % ssd)['body']
        self.assertEqual([r['type'] for r in kardex['rows']], ['entrada', 'entrada', 'salida', 'entrada', 'salida', 'reserva', 'salida', 'traslado'])
        self.assertEqual([r['balance'] for r in kardex['rows']], [1, 3, 2, 4, 3, 3, 2, 2])
        self.assertEqual(kardex['rows'][2]['unit_cost_cents'], 2000)  # la venta salió al promedio vigente
        self.assertEqual([r['reason'] for r in self.get('/api/inventory/kardex?type=m:venta')['body']['rows']], ['venta', 'venta'])
        self.assertEqual(self.get('/api/inventory/kardex?from=2000-01-01&to=2000-12-31')['body']['rows'], [])
        # Exportaciones: Excel real, CSV y PDF.
        book = zipfile.ZipFile(io.BytesIO(self.get('/api/inventory/kardex.xlsx?item_id=%d' % ssd)['body']))
        self.assertIn('Kingston', book.read('xl/worksheets/sheet1.xml').decode())
        self.assertTrue(self.get('/api/inventory/kardex.csv')['body'].decode('utf-8-sig').startswith('Fecha;Producto;SKU'))
        self.assertEqual(self.get('/api/inventory/kardex.pdf')['body'][:5], b'%PDF-')
        self.assertEqual(self.get('/api/inventory/stock.xlsx')['body'][:2], b'PK')

    def test_invoice_after_order_consumption_does_not_discount_again(self):
        self.admin()
        ssd, _ = self.ssd()
        paste = self.new(self.category('Pasta térmica', 'Consumibles de servicio técnico'), 'Arctic', 'MX-4 4 g', quantity=10, cost='4,20')['body']['item']['id']
        with app.connect() as c:
            catalog = {r['id']: r['catalog_id'] for r in c.execute('SELECT id,catalog_id FROM inventory_items')}
        order = self.order('000002')
        quote = self.post('/api/orders/%d/quote' % order['id'])['body']['id']
        items = [{'catalog_id': catalog[ssd], 'description': 'SSD ficticio', 'category': 'repuesto', 'quantity': 1, 'unit_cents': 3500, 'taxed': True},
                 {'catalog_id': catalog[paste], 'description': 'Pasta ficticia', 'category': 'repuesto', 'quantity': 1, 'unit_cents': 900, 'taxed': True}]
        self.assertEqual(self.post('/api/quotes/%d' % quote, action='save', items=items)['status'], 200)
        self.post('/api/quotes/%d' % quote, action='send')
        with app.connect() as c:
            ids = [str(r[0]) for r in c.execute('SELECT id FROM quote_items WHERE quote_id=?', (quote,))]
        self.assertEqual(self.post('/api/quotes/%d' % quote, action='decide', approved=','.join(ids), note='Aprobó por teléfono (ficticio)')['status'], 200)
        self.assertEqual(self.post('/api/orders/%d/payments' % order['id'], amount='44,00', method='efectivo')['status'], 201)
        # El técnico consumió el SSD en la orden; la pasta todavía no.
        unit = self.get('/api/inventory/units?item=%d' % ssd)['body']['rows'][0]['id']
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(ssd), reason='uso_orden', order_code=order['code'], unit_ids=json.dumps([unit]))['status'], 200)
        draft = self.post('/api/invoicing/draft', kind='orden', id=str(order['id']))
        self.assertEqual(draft['status'], 200, draft['body'])
        invoice = draft['body']['invoice']['id']
        user = {'id': self.uid, 'name': 'Prueba'} if hasattr(self, 'uid') else {'id': 1, 'name': 'Prueba'}
        with app.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            result = inventory_center.invoice_exit(c, invoice, user, app.reception_now())
            again = inventory_center.invoice_exit(c, invoice, user, app.reception_now())
            c.commit()
            stock = {r[0]: r[1] for r in c.execute('SELECT item_id,SUM(direction*quantity) FROM inventory_movements GROUP BY item_id')}
        self.assertEqual(([m['item_id'] for m in result['moved']], [s['item_id'] for s in result['skipped']]), ([paste], [ssd]))  # el SSD ya salió por la orden
        self.assertEqual((again['moved'], len(again['skipped'])), ([], 2))  # la factura tampoco descuenta dos veces
        self.assertEqual((stock[ssd], stock[paste]), (0, 9))

    def test_warranties_start_progress_and_expiry(self):
        self.admin()
        made = self.new(self.category('SSD M.2 NVMe', 'Almacenamiento'), 'Samsung', '980 Pro 1 TB', units=['W1', 'W2', 'W3', 'W4'], warranty_store_qty='1', warranty_store_unit='anios',
                        warranty_store_from='entrega', warranty_maker_qty='5', warranty_maker_unit='anios')
        item = made['body']['item']['id']
        u = [x['id'] for x in made['body']['units']]
        today = app.reception_now().date()
        client = self.client()
        # Vendida sin entregar: la garantía de PC-DOCTOR (desde la entrega) espera; la del fabricante (desde la venta) ya corre.
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(item), reason='venta', unit_ids=json.dumps([u[0]]), client_id=str(client), delivered='0')['status'], 200)
        row = next(r for r in self.get('/api/inventory/warranties')['body']['rows'] if r['unit_id'] == u[0])
        self.assertEqual((row['store']['state'], row['maker']['state'], row['maker']['to']), ('pendiente_entrega', 'vigente', today.replace(year=today.year + 5).isoformat()))
        self.assertEqual(self.post('/api/inventory/delivery', unit_ids=json.dumps([u[0]]), delivered_at=today.isoformat())['status'], 200)
        row = next(r for r in self.get('/api/inventory/warranties')['body']['rows'] if r['unit_id'] == u[0])
        self.assertEqual((row['store']['state'], row['store']['tone'], row['store']['days_left']), ('vigente', 'verde', (today.replace(year=today.year + 1) - today).days))
        # Vendida hace 350 días: próxima a vencer (panel y tarjeta); hace 400 días: vencida, con su historial intacto.
        old = (today - timedelta(days=350)).isoformat()
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(item), reason='venta', unit_ids=json.dumps([u[1]]), sold_at=old, delivered_at=old)['status'], 200)
        older = (today - timedelta(days=400)).isoformat()
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(item), reason='venta', unit_ids=json.dumps([u[2]]), sold_at=older, delivered_at=older)['status'], 200)
        states = {r['unit_id']: (r['store']['state'], r['store']['tone']) for r in self.get('/api/inventory/warranties')['body']['rows']}
        self.assertEqual((states[u[1]][0], states[u[1]][1], states[u[2]][0]), ('por_vencer', 'rojo', 'vencida'))
        self.assertEqual(self.get('/api/inventory/center')['body']['cards']['warranties_soon'], 1)
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(item), reason='venta', unit_ids=json.dumps([u[3]]), sold_at=(today + timedelta(days=2)).isoformat())['status'], 400)  # fecha futura
        expired = self.get('/api/inventory/units/%d' % u[2])['body']
        self.assertEqual((expired['store_warranty_from'], expired['status']), (older, 'vendida'))

    def test_licenses_classified_by_category_brand_family_and_edition(self):
        self.admin()
        made = {}
        for name, brand, line, key in (('Kaspersky Plus ficticio', 'Kaspersky', 'antivirus', SECRET), ('Norton 360 Deluxe ficticio', 'Norton', 'antivirus', 'NORT-FICT-0000-0001'),
                                       ('McAfee Total Protection ficticio', 'McAfee', 'antivirus', 'MCAF-FICT-0000-0001'), ('Microsoft 365 Personal ficticio', 'Microsoft', 'microsoft', 'M365-FICT-0000-0001')):
            answer = self.post('/api/licenses/new', name=name, brand=brand, line=line, model='suscripcion', edition='2026', description='Licencia de prueba', devices='1', duration='anual',
                               validity_mode='activacion', price='30', purchase_price='18,50', supplier='Mayorista ficticio', key=key)
            self.assertEqual(answer['status'], 201, answer['body'])
            made[brand] = answer['body']['product_id']
        tax = self.get('/api/inventory/taxonomy')['body']
        family = {(f['brand'], f['name']): f['id'] for f in tax['families']}
        antivirus = self.category('Antivirus')
        m365 = next(ch['id'] for cat in tax['categories'] if cat['name'] == 'Microsoft' for ch in cat['children'] if ch['name'] == 'Microsoft 365')
        for brand, fam, edition, category in (('Kaspersky', 'Kaspersky', 'Plus', antivirus), ('Norton', 'Norton 360', 'Deluxe', antivirus), ('McAfee', 'McAfee', 'Total Protection', antivirus),
                                              ('Microsoft', 'Microsoft 365', 'Personal', m365)):
            answer = self.post('/api/inventory/licenses/classify', item_id=str(made[brand]), category_id=str(category), brand=brand, family_id=str(family[(brand, fam)]), edition=edition,
                               sku='SKU-' + brand.upper()[:4])
            self.assertEqual(answer['status'], 200, answer['body'])
        tree = self.get('/api/inventory/licenses')['body']
        self.assertNotIn(SECRET, json.dumps(tree))  # las claves nunca salen de su módulo
        av = next(n for n in tree['categories'] if n['name'] == 'Antivirus')
        found = {(b['name'], f['name'], p['edition']): p['stock']['disponible'] for b in av['brands'] for f in b['families'] for p in f['products']}
        self.assertEqual(found, {('Kaspersky', 'Kaspersky', 'Plus'): 1, ('McAfee', 'McAfee', 'Total Protection'): 1, ('Norton', 'Norton 360', 'Deluxe'): 1})
        ms = next(n for n in tree['categories'] if n['name'] == 'Microsoft 365')
        self.assertEqual([p['edition'] for b in ms['brands'] for f in b['families'] for p in f['products']], ['Personal'])
        self.assertEqual(tree['totals']['disponible'], 4)  # una sola existencia: la de las unidades del módulo Licencias
        # Licencias nuevas de productos clasificados: código de su categoría. La clave repetida se advierte.
        unit = self.post('/api/licenses/units', product_id=str(made['Kaspersky']), key='KASP-FICT-0000-AAAA-2222')
        self.assertIn(unit['status'], (200, 201), unit['body'])
        m = self.post('/api/licenses/units', product_id=str(made['Microsoft']), key='M365-FICT-0000-0002')
        with app.connect() as c:
            codes = sorted(r[0] for r in c.execute('SELECT code FROM license_units'))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM inventory_items').fetchone()[0], 0)  # no se duplica en el inventario físico
        self.assertIn('PCD-AV-000001', codes)
        self.assertIn('PCD-M365-000001', codes)
        self.assertNotEqual(self.post('/api/licenses/units', product_id=str(made['Kaspersky']), key=SECRET)['status'], 200)  # duplicada
        self.assertEqual(self.post('/api/inventory/licenses/classify', item_id=str(made['Norton']), category_id=str(antivirus), brand='Norton', sku='SKU-KASP')['status'], 400)  # SKU repetido

    def test_import_preview_duplicates_and_commit(self):
        self.admin()
        self.ssd()
        template = self.get('/api/inventory/import/template.csv')['body'].decode('utf-8-sig')
        self.assertTrue(template.startswith('categoria;subcategoria;marca'))
        csv_text = ('categoria;subcategoria;marca;modelo;producto;sku;control;serie;cantidad;costo;precio;ubicacion;minimo;garantia_pcdoctor;garantia_fabricante\n'
                    'Almacenamiento;SSD SATA 2.5";Crucial;BX500 480 GB;SSD Crucial BX500 480 GB;CT480BX500;serie;CRU-0001;1;22,00;39,00;Bodega B;1;1 año;3 años\n'
                    'Almacenamiento;SSD SATA 2.5";Crucial;BX500 480 GB;SSD Crucial BX500 480 GB;CT480BX500;serie;691918TM;1;22,00;39,00;Bodega B;1;1 año;3 años\n'
                    'Consumibles de servicio técnico;Alcohol isopropílico;Genérico;1 litro;Alcohol isopropílico 1 L;;granel;;6;5,50;0;Taller;2;;\n')
        raw = base64.b64encode(csv_text.encode('utf-8')).decode()
        preview = self.post('/api/inventory/import/preview', file=raw, name='inventario.csv')['body']
        self.assertEqual((preview['valid'], preview['errors']), (2, 1))
        self.assertIn('Serie ya registrada', ' '.join(preview['rows'][1]['problems']))
        self.assertEqual(self.post('/api/inventory/import/commit', file=raw, name='inventario.csv', sha=preview['sha'])['status'], 409)  # todo o nada
        fixed = base64.b64encode(csv_text.replace('691918TM', 'CRU-0002').encode('utf-8')).decode()
        preview = self.post('/api/inventory/import/preview', file=fixed, name='inventario.csv')['body']
        self.assertEqual(preview['errors'], 0)
        self.assertEqual(self.post('/api/inventory/import/commit', file=fixed, name='inventario.csv', sha='otra')['status'], 409)
        done = self.post('/api/inventory/import/commit', file=fixed, name='inventario.csv', sha=preview['sha'])
        self.assertEqual((done['status'], done['body']['products_created'], done['body']['units']), (200, 2, 8))
        crucial = self.get('/api/inventory/products?q=crucial')['body']['rows'][0]
        self.assertEqual((crucial['stock'], crucial['warranty_store']['label'], crucial['warranty_maker']['label'], crucial['sku']), (2, '1 año', '3 años', 'CT480BX500'))
        self.assertEqual([u['internal_code'] for u in self.get('/api/inventory/units?item=%d' % crucial['id'])['body']['rows']], ['PCD-SSD-000003', 'PCD-SSD-000002'])

    def test_purchase_of_serial_product_creates_units_and_void_returns_them(self):
        self.admin()
        ssd, _ = self.ssd()
        supplier = self.post('/api/inventory/suppliers', action='save', name='Distribuidora Ficticia S.A.')['body']['id']
        lines = json.dumps([{'item_id': ssd, 'quantity': '2', 'unit_cost': '24,00', 'taxed': '1'}])
        purchase = self.post('/api/inventory/purchases', action='save', supplier_id=str(supplier), document_number='001-001-000000555', issue_date='2026-10-20', items=lines)['body']['id']
        self.assertEqual(self.post('/api/inventory/purchases/%d' % purchase, action='receive')['status'], 200)
        units = [u for u in self.get('/api/inventory/units?item=%d' % ssd)['body']['rows'] if u['serial'] == '']
        self.assertEqual(sorted(u['internal_code'] for u in units), ['PCD-SSD-000002', 'PCD-SSD-000003'])  # recibidas solo con código interno
        self.assertEqual(self.post('/api/inventory/units/%d' % units[0]['id'], action='serial', serial='COMPRA-0001')['status'], 200)
        self.assertEqual(self.post('/api/inventory/exit', item_id=str(ssd), reason='venta', unit_ids=json.dumps([units[0]['id']]))['status'], 200)
        blocked = self.post('/api/inventory/purchases/%d' % purchase, action='void', reason='Documento del proveedor errado')
        self.assertEqual(blocked['status'], 409)  # ya salió una unidad de esa compra
        self.assertEqual(self.get('/api/inventory/products/%d' % ssd)['body']['product']['stock'], 2)

    def test_labels_exports_and_permissions(self):
        self.admin()
        ssd, unit = self.ssd()
        self.assertEqual(self.get('/api/inventory/labels.pdf?units=%d' % unit)['body'][:5], b'%PDF-')
        package = json.loads(self.get('/api/inventory/export.json')['body'])
        self.assertEqual((package['format'], package['counts']['inventory_units']), ('ordenes-pro-inventario/1', 1))
        self.assertNotIn('secret', json.dumps(package))
        center = self.get('/api/inventory/center')['body']
        self.assertEqual((center['cards']['products'], center['cards']['available']), (1, 1))
        tcookie, tcsrf = self.technician()
        for path in ('/api/inventory/center', '/api/inventory/kardex', '/api/inventory/licenses'):
            self.assertEqual(self.request(path, cookie=tcookie)['status'], 403)
        self.assertEqual(self.request('/api/inventory/register', {'item_id': str(ssd), 'units': '[{"serial":"T1"}]'}, cookie=tcookie, csrf=tcsrf)['status'], 403)


if __name__ == '__main__':
    unittest.main()
