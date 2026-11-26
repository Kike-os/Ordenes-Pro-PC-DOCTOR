"""Smart Catalog 3.0 en Inventario: la ficha creada desde Inventario (también desde «Crear producto» del ingreso de mercadería) devuelve su
artículo del catálogo para subir la fotografía, queda como PERMANENTE y su foto aparece en la lista del Inventario. Datos ficticios."""
import base64
import unittest

import test_app
import test_inventory_center
import app

JPEG = base64.b64decode('/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=') + b'\xff\xd9'


class SmartCatalogInventoryTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login, test_app.SecurityTests.order_data
    admin, category, new, more, technician = (getattr(test_inventory_center.InventoryCenterTests, n) for n in ('admin', 'category', 'new', 'more', 'technician'))

    def test_inventory_product_photo_and_permanent_profile(self):
        self.admin()
        made = self.post('/api/inventory/products', action='save', category_id=str(self.category('SSD SATA 2.5"', 'Almacenamiento')), brand='Ficticia', model='SSD-FICT-1', price='60,00', min_stock='0', tracking='granel', sku='')
        self.assertEqual(made['status'], 200, made['body'])
        catalog_id = made['body']['catalog_id']
        self.assertTrue(catalog_id)
        with app.connect() as c:
            profile = c.execute('SELECT mode,origin FROM catalog_profiles WHERE item_id=?', (catalog_id,)).fetchone()
        self.assertEqual(tuple(profile), ('permanente', 'inventario'))
        self.assertEqual(self.post('/api/catalog/%d/image' % catalog_id, data=base64.b64encode(JPEG).decode())['status'], 200)
        rows = self.request('/api/inventory/products', cookie=self.cookie)['body']
        rows = rows.get('rows', rows) if isinstance(rows, dict) else rows
        mine = next(r for r in rows if r['catalog_id'] == catalog_id)
        self.assertTrue(mine['photo'])


if __name__ == '__main__':
    unittest.main()
