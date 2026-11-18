"""1.5.295 · Licencias: el inventario incluye la entrega vinculada (para «Gestionar entrega») sin exponer costos ni credenciales."""
import unittest

import test_app
import test_license_control
import test_license_enterprise


class LicenseMenusTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login
    _B = test_license_control.LicenseControlTests
    admin, today, new_product, order_data, delivered = _B.admin, _B.today, _B.new_product, _B.order_data, _B.delivered
    del _B

    def test_units_include_delivery_link_without_secrets_or_costs(self):
        self.admin()
        unit, _ = self.delivered(40)
        rows = self.get('/api/licenses/units')['body']['rows']
        row = next(r for r in rows if r['id'] == unit)
        self.assertIn('delivery_id', row)
        self.assertIn('sale_id', row)
        self.assertFalse(test_license_enterprise.contains_cost(rows))
        self.assertNotIn(test_license_control.test_licenses.SERIAL, str(rows))
