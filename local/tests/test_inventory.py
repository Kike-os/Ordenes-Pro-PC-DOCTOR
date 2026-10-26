"""Inventario físico, proveedores y compras. Base temporal y datos ficticios: no se toca ningún inventario real."""
import json
import unittest

import test_app
import test_invoicing
import app


class InventoryTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    technician = __import__('test_cash').CashTests.technician

    def catalog(self, name, category='repuesto', cents=2500):
        with app.connect() as c:
            new_id = c.execute("INSERT INTO catalog_items(name,category,price_cents,taxed,available,created_at,updated_at) VALUES (?,?,?,1,1,'2026-10-26T09:00:00','2026-10-26T09:00:00')",
                               (name, category, cents)).lastrowid
            c.commit()
        return new_id

    def session(self):
        cookie, csrf = self.login()
        return cookie, lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)

    def item(self, post, name, **extra):
        answer = post('/api/inventory/items', action='save', catalog_id=str(self.catalog(name)), kind='repuesto', **extra)
        self.assertEqual(answer['status'], 200, answer['body'])
        return answer['body']['id']

    def stock(self, cookie, item_id):
        return next(r for r in self.request('/api/inventory', cookie=cookie)['body']['items'] if r['id'] == item_id)

    def test_items_movements_and_alerts(self):
        cookie, post = self.session()
        licence = self.catalog('Antivirus ficticio', 'licencia')
        bad = post('/api/inventory/items', action='save', catalog_id=str(licence), kind='repuesto')
        self.assertEqual((bad['status'], list(bad['body']['fields'])), (400, ['catalog_id']))  # las licencias tienen su propio inventario
        disk = self.item(post, 'Disco SSD ficticio 480 GB', sku='SSD-480', min_stock='2', initial_stock='3', initial_cost='18,50', location='Estante A')
        self.assertEqual(post('/api/inventory/items', action='save', catalog_id=str(self.catalog('Otro')), kind='accesorio', sku='SSD-480')['status'], 400)  # código repetido
        row = self.stock(cookie, disk)
        self.assertEqual((row['stock'], row['low'], row['average_cost_cents'], row['value_cents']), (3, False, 1850, 5550))
        out = post('/api/inventory/items', action='move', id=str(disk), direction='out', reason='uso_orden', quantity='2', request_key='mov-ficticio-000001')
        self.assertEqual(out['status'], 200)
        self.assertEqual(post('/api/inventory/items', action='move', id=str(disk), direction='out', reason='uso_orden', quantity='2', request_key='mov-ficticio-000001')['body']['movement'],
                         out['body']['movement'])  # reintento: no se duplica
        row = self.stock(cookie, disk)
        self.assertEqual((row['stock'], row['low']), (1, True))
        overview = self.request('/api/inventory', cookie=cookie)['body']
        self.assertEqual(([a['id'] for a in overview['alerts']], overview['totals']['alerts']), ([disk], 1))
        short = post('/api/inventory/items', action='move', id=str(disk), direction='out', reason='venta', quantity='2')
        self.assertEqual(short['status'], 409)
        self.assertIn('hay 1', short['body']['error'])  # nunca existencias negativas
        self.assertEqual(post('/api/inventory/items', action='move', id=str(disk), direction='out', reason='compra', quantity='1')['status'], 400)  # motivo de otro sentido
        self.assertEqual(post('/api/inventory/items', action='move', id=str(disk), direction='in', reason='inicial', quantity='1')['status'], 400)  # «inicial» no es manual
        self.assertEqual(post('/api/inventory/items', action='move', id=str(disk), direction='in', reason='ajuste_entrada', quantity='0')['status'], 400)
        post('/api/inventory/items', action='move', id=str(disk), direction='in', reason='ajuste_entrada', quantity='4', cost='20,50')
        history = self.request('/api/inventory/items/%d/movements' % disk, cookie=cookie)['body']
        self.assertEqual([m['balance'] for m in history['movements']], [5, 1, 3])
        self.assertEqual(self.stock(cookie, disk)['average_cost_cents'], 1964)  # (3×18,50 + 4×20,50) / 7
        with app.connect() as c:
            for sql in ('UPDATE inventory_movements SET quantity=99', 'DELETE FROM inventory_movements', 'DELETE FROM inventory_items', 'DELETE FROM inventory_events'):
                with self.assertRaises(Exception):
                    c.execute(sql)
        self.assertIsInstance(self.request('/api/inventory', cookie=cookie)['body']['licenses'], list)  # licencias: solo lectura desde su módulo
        tcookie, tcsrf = self.technician()
        self.assertEqual(self.request('/api/inventory', cookie=tcookie)['status'], 403)
        self.assertEqual(self.request('/api/inventory/items', {'action': 'move', 'id': str(disk), 'direction': 'in', 'reason': 'ajuste_entrada', 'quantity': '5'}, cookie=tcookie, csrf=tcsrf)['status'], 403)
        self.assertEqual(self.stock(cookie, disk)['stock'], 5)

    def test_suppliers_and_purchases(self):
        cookie, post = self.session()
        bad = post('/api/inventory/suppliers', action='save', name='X', identification='1234567890', email='no-es-correo')
        self.assertEqual((bad['status'], set(bad['body']['fields'])), (400, {'name', 'identification', 'email'}))
        ruc = test_invoicing.fake_ruc()
        supplier = post('/api/inventory/suppliers', action='save', name='Distribuidora Ficticia S.A.', identification=ruc, email='ventas@example.invalid')['body']['id']
        self.assertEqual(post('/api/inventory/suppliers', action='save', name='Duplicado', identification=ruc)['status'], 400)
        ram = self.item(post, 'Memoria RAM ficticia 8 GB')
        fan = self.item(post, 'Ventilador ficticio')
        lines = json.dumps([{'item_id': ram, 'quantity': '4', 'unit_cost': '22,40', 'taxed': '1'}, {'item_id': fan, 'quantity': '2', 'unit_cost': '5', 'taxed': '0'}])
        self.assertEqual(post('/api/inventory/purchases', action='save', supplier_id=str(supplier), document_number='001-001-000000123', issue_date='2099-01-01', items=lines)['status'], 400)
        purchase = post('/api/inventory/purchases', action='save', supplier_id=str(supplier), document_number='001-001-000000123', issue_date='2026-10-20', items=lines)
        self.assertEqual(purchase['status'], 200, purchase['body'])
        pid = purchase['body']['id']
        detail = self.request('/api/inventory/purchases/%d' % pid, cookie=cookie)['body']
        self.assertEqual((detail['subtotal_cents'], detail['tax_cents'], detail['total_cents'], detail['status']), (9960, 1344, 11304, 'borrador'))
        self.assertEqual(self.stock(cookie, ram)['stock'], 0)  # el borrador no mueve inventario
        dup = post('/api/inventory/purchases', action='save', supplier_id=str(supplier), document_number='001-001-000000123', issue_date='2026-10-20', items=lines)
        self.assertEqual((dup['status'], list(dup['body']['fields'])), (400, ['document_number']))
        self.assertEqual(post('/api/inventory/purchases/%d' % pid, action='receive')['status'], 200)
        self.assertEqual(post('/api/inventory/purchases/%d' % pid, action='receive')['status'], 409)  # no entra dos veces
        self.assertEqual((self.stock(cookie, ram)['stock'], self.stock(cookie, fan)['stock'], self.stock(cookie, ram)['average_cost_cents']), (4, 2, 2240))
        self.assertEqual(post('/api/inventory/purchases', action='save', id=str(pid), supplier_id=str(supplier), document_number='001-001-000000123', issue_date='2026-10-20', items=lines)['status'], 409)
        with app.connect() as c:
            with self.assertRaises(Exception):
                c.execute('UPDATE purchase_items SET quantity=40')
            with self.assertRaises(Exception):  # el mismo documento no mueve dos veces el mismo artículo
                c.execute("INSERT INTO inventory_movements(item_id,direction,reason,quantity,reference_kind,reference_id,created_at) VALUES (?,1,'compra',4,'compra',?,'2026-10-26T10:00:00')", (ram, pid))
        post('/api/inventory/items', action='move', id=str(fan), direction='out', reason='uso_orden', quantity='1')
        self.assertEqual(post('/api/inventory/purchases/%d' % pid, action='void', reason='x')['status'], 400)  # motivo obligatorio
        blocked = post('/api/inventory/purchases/%d' % pid, action='void', reason='Factura del proveedor errada')
        self.assertEqual(blocked['status'], 409)  # ya se usó un ventilador: no se puede revertir sin dejar negativo
        self.assertEqual((self.stock(cookie, ram)['stock'], self.stock(cookie, fan)['stock']), (4, 1))  # la anulación fallida no dejó nada a medias
        post('/api/inventory/items', action='move', id=str(fan), direction='in', reason='devolucion_cliente', quantity='1')
        self.assertEqual(post('/api/inventory/purchases/%d' % pid, action='void', reason='Factura del proveedor errada')['status'], 200)
        self.assertEqual((self.stock(cookie, ram)['stock'], self.stock(cookie, fan)['stock']), (0, 0))
        again = post('/api/inventory/purchases', action='save', supplier_id=str(supplier), document_number='001-001-000000123', issue_date='2026-10-20', items=lines)
        self.assertEqual(again['status'], 200)  # anulada, el documento puede registrarse de nuevo
        listed = self.request('/api/inventory/purchases', cookie=cookie)['body']['rows']
        self.assertEqual([r['status'] for r in listed], ['borrador', 'anulada'])
        post('/api/inventory/suppliers', action='deactivate', id=str(supplier))
        self.assertEqual(post('/api/inventory/purchases', action='save', supplier_id=str(supplier), document_number='X-2', issue_date='2026-10-20', items=lines)['status'], 400)


if __name__ == '__main__':
    unittest.main()
