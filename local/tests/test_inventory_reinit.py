"""Inventario: reinicialización controlada (vista previa, autorización expresa, salida de ajuste trazable, series liberadas para el nuevo
ingreso, idempotencia), correcciones de costo y cambios de precio sin efecto en las existencias, saldo anterior y posterior en el Kardex,
código de barras único y existencia máxima. Base temporal y datos ficticios."""
import json
import unittest

import test_app
import test_inventory_center as base
import app


class InventoryReinitTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data
    admin, category, new, more = (getattr(base.InventoryCenterTests, n) for n in ('admin', 'category', 'new', 'more'))

    def products(self):
        self.admin()
        ssd = self.new(self.category('SSD SATA 2.5"', 'Almacenamiento'), 'Kingston', 'A400 480 GB', units=['RS-1', 'RS-2'], cost='0,00', barcode='7501234567890')
        self.assertEqual(ssd['status'], 200, ssd['body'])
        mouse = self.new(self.category('Pasta térmica', 'Consumibles de servicio técnico'), 'Arctic', 'MX-4 4 g', quantity=3, cost='4,00')
        self.assertEqual(mouse['status'], 200, mouse['body'])
        return ssd['body']['item']['id'], mouse['body']['item']['id']

    def test_cost_corrections_and_price_changes_do_not_move_stock(self):
        ssd, mouse = self.products()
        entry = [r for r in self.get('/api/inventory/kardex?item_id=%d' % ssd)['body']['rows'] if r['type'] == 'entrada'][0]
        self.assertEqual(self.post('/api/inventory/cost-correction', movement_id=str(entry['movement_id']), cost='22,00', reason='Costo real según factura ficticia')['status'], 200)
        with app.connect() as c:
            catalog = c.execute('SELECT catalog_id FROM inventory_items WHERE id=?', (ssd,)).fetchone()[0]
            c.execute("INSERT INTO catalog_price_history(item_id,old_cents,new_cents,user_id,created_at) VALUES (?,3500,3900,?,'2099-01-01T00:00:00-05:00')", (catalog, self.uid))
            c.commit()
        product = self.get('/api/inventory/products/%d' % ssd)['body']['product']
        self.assertEqual((product['stock'], product['average_cost_cents']), (2, 2200))  # el costo cambia; las existencias no
        rows = self.get('/api/inventory/kardex?item_id=%d' % ssd)['body']['rows']
        fix = next(r for r in rows if r['type'] == 'correccion')
        price = next(r for r in rows if r['type'] == 'precio')
        for r in (fix, price):
            self.assertEqual((r['entry'], r['exit'], r['balance_before'], r['balance'], r['stock_effect']), (0, 0, 2, 2, False))
            self.assertIn('sin movimiento de existencias', r['label'])
        moves = [r for r in rows if r['type'] == 'entrada']
        self.assertEqual([(r['balance_before'], r['balance'], r['stock_effect']) for r in moves], [(0, 2, True)])
        self.assertEqual([r['type'] for r in self.get('/api/inventory/kardex?item_id=%d&type=precio' % ssd)['body']['rows']], ['precio'])
        self.assertIn('Saldo anterior', self.request('/api/inventory/kardex.csv?item_id=%d' % ssd, cookie=self.cookie)['body'].decode('utf-8-sig').splitlines()[0])

    def test_reinitialization_is_previewed_authorized_traceable_and_frees_serials(self):
        ssd, mouse = self.products()
        unit = self.get('/api/inventory/products/%d' % ssd)['body']
        held = self.post('/api/inventory/reservations', action='reserve', item_id=str(mouse), quantity='1', reference='Reserva ficticia')
        self.assertEqual(held['status'], 200, held['body'])
        preview = self.get('/api/inventory/reinitialize?ids=%d,%d' % (ssd, mouse))['body']
        self.assertTrue(preview['blocked'])
        self.assertEqual([(r['id'], r['stock'], r['movements']) for r in preview['rows']], [(ssd, 2, 1), (mouse, 3, 1)])
        self.assertEqual(self.post('/api/inventory/reinitialize', item_ids='%d,%d' % (ssd, mouse), reason='Reingreso del inventario (ficticio)', confirm='REINICIALIZAR')['status'], 409)  # reserva activa
        self.assertEqual(self.post('/api/inventory/reservations', action='release', id=str(held['body']['id']))['status'], 200)
        body = dict(item_ids='%d,%d' % (ssd, mouse), reason='Reingreso del inventario (ficticio)', request_key='reinicio-prueba-000001')
        self.assertEqual(self.post('/api/inventory/reinitialize', **body, confirm='SI')['status'], 400)  # sin la palabra de confirmación
        self.assertEqual(self.post('/api/inventory/reinitialize', **{**body, 'reason': 'corto'}, confirm='REINICIALIZAR')['status'], 400)
        with app.connect() as c:
            before = [tuple(r) for r in c.execute('SELECT * FROM inventory_movements ORDER BY id')]
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.post('/api/inventory/reinitialize', **body, confirm='REINICIALIZAR')['status'], 403)
        with app.connect() as c:
            c.execute("UPDATE users SET role='administrador' WHERE id=?", (self.uid,));c.commit()
        done = self.post('/api/inventory/reinitialize', **body, confirm='REINICIALIZAR')
        self.assertEqual(done['status'], 200, done['body'])
        self.assertEqual([(r['before'], r['after']) for r in done['body']['rows']], [(2, 0), (3, 0)])
        self.assertEqual(self.post('/api/inventory/reinitialize', **body, confirm='REINICIALIZAR')['body']['duplicate'], True)  # sin repetir
        with app.connect() as c:
            after = [tuple(r) for r in c.execute('SELECT * FROM inventory_movements ORDER BY id')]
            self.assertEqual(after[:len(before)], before)  # los movimientos anteriores no cambian
            self.assertEqual([(r[2], r[3], r[4]) for r in after[len(before):]], [(-1, 'ajuste_salida', 2), (-1, 'ajuste_salida', 3)])
            units = [tuple(r) for r in c.execute('SELECT status,serial,serial_key,released_serial FROM inventory_units WHERE item_id=? ORDER BY id', (ssd,))]
            self.assertEqual(units, [('baja', 'RS-1', '', 'RS-1'), ('baja', 'RS-2', '', 'RS-2')])
            with self.assertRaises(Exception):
                c.execute('DELETE FROM inventory_reinit_batches')
        for item in (ssd, mouse):
            self.assertEqual(self.get('/api/inventory/products/%d' % item)['body']['product']['stock'], 0)
        # Las mismas series vuelven a ingresarse con códigos internos nuevos.
        again = self.more(ssd, units=['RS-1', 'RS-2'], cost='21,00')
        self.assertEqual(again['status'], 200, again['body'])
        self.assertEqual(self.get('/api/inventory/products/%d' % ssd)['body']['product']['stock'], 2)
        self.assertEqual(len(self.get('/api/inventory/reinit-batches')['body']['rows']), 1)

    def test_barcode_is_unique_and_max_stock_is_validated(self):
        ssd, mouse = self.products()
        self.assertEqual(self.get('/api/inventory/products/%d' % ssd)['body']['product']['barcode'], '7501234567890')
        other = self.new(self.category('SSD SATA 2.5"', 'Almacenamiento'), 'Kingston', 'A400 960 GB', units=['RS-9'], cost='30,00', barcode='7501234567890')
        self.assertEqual((other['status'], 'barcode' in other['body']['fields']), (409, True))
        import inventory_center
        with app.connect() as c:
            c.execute('UPDATE inventory_items SET min_stock=5 WHERE id=?', (mouse,))
            with self.assertRaises(inventory_center.InventoryError) as error:
                inventory_center._codes(c, mouse, {'max_stock': '2'})
            self.assertIn('max_stock', error.exception.fields)
            inventory_center._codes(c, mouse, {'max_stock': '20'})
            self.assertEqual(c.execute('SELECT max_stock FROM inventory_items WHERE id=?', (mouse,)).fetchone()[0], 20)


if __name__ == '__main__':
    unittest.main()
