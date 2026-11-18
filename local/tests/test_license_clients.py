"""1.5.293 · Licencias Digitales Enterprise 3.0 (inventario por cliente): indicadores del encabezado, documento del cliente identificado,
filtro por fabricante y renovaciones sin duplicados ni pisadas. Datos ficticios en una base temporal."""
import unittest
from datetime import timedelta

import test_app
import app
import test_license_control


class LicenseClientsTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login
    _B = test_license_control.LicenseControlTests
    admin, today, new_product, order_data, delivered = _B.admin, _B.today, _B.new_product, _B.order_data, _B.delivered
    del _B

    def test_header_indicators_follow_real_data(self):
        self.admin()
        self.delivered(10)                       # activa y próxima a vencer
        self.delivered(200)                      # activa
        self.delivered(-5)                       # vencida
        self.delivered(60, activated=False)      # entregada sin activar
        ind = self.get('/api/licenses')['body']['indicators']
        self.assertEqual((ind['total'], ind['activas'], ind['por_vencer'], ind['vencidas'], ind['soon_days']), (4, 2, 1, 1, 30))
        self.assertEqual(ind['renovaciones_pendientes'], 2)   # la que vence en 10 días y la vencida (dentro del margen de seguimiento)
        unit, _ = self.delivered(20)
        self.post('/api/licenses/units/%d' % unit, action='followup', status='rechazado', note='Cambia de proveedor')
        self.assertEqual(self.get('/api/licenses')['body']['indicators']['renovaciones_pendientes'], 2)   # el rechazo no cuenta como pendiente

    def test_client_document_and_maker_filter(self):
        self.admin()
        unit, cid = self.delivered(30)
        with app.connect() as c:
            c.execute("UPDATE clients SET identification='1790011223001',document_type='ruc' WHERE id=?", (cid,))
        row = next(r for r in self.get('/api/licenses/units')['body']['rows'] if r['id'] == unit)
        self.assertEqual((row['client_identification'], row['client_document_type']), ('1790011223001', 'ruc'))
        self.assertEqual(len(self.get('/api/licenses/units?fabricante=eset')['body']['rows']), 1)
        self.assertEqual(len(self.get('/api/licenses/units?fabricante=microsoft')['body']['rows']), 0)

    def test_renewal_is_never_duplicated_or_overwritten(self):
        self.admin()
        unit, _ = self.delivered(12)
        url = '/api/licenses/units/%d' % unit
        with app.connect() as c:
            expires = c.execute('SELECT expires_at FROM license_units WHERE id=?', (unit,)).fetchone()[0]
        first = self.post(url, action='renew', duration='anual', starts_at=expires)
        self.assertEqual(first['status'], 200, first['body'])
        again = self.post(url, action='renew', duration='anual', starts_at=expires)   # doble clic o reintento: misma vigencia
        self.assertEqual(again['status'], 409)
        self.assertIn('ya está registrada', again['body']['error'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM license_renewals WHERE unit_id=?', (unit,)).fetchone()[0], 1)
            new_expiry = c.execute('SELECT expires_at FROM license_units WHERE id=?', (unit,)).fetchone()[0]
        self.assertEqual(new_expiry, first['body']['expires_at'])
        # Otra persona renovó entre la lectura y la escritura: no se pisa (control de concurrencia en el UPDATE).
        import licenses
        real = licenses.unit_row

        def stale(c, unit_id):
            row = dict(real(c, unit_id))
            row['expires_at'] = expires   # vencimiento leído antes de la otra renovación
            return row
        from unittest.mock import patch
        with patch.object(licenses, 'unit_row', side_effect=stale):
            later = self.post(url, action='renew', duration='anual', starts_at=(self.today() + timedelta(days=400)).isoformat())
        self.assertEqual(later['status'], 409, later['body'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT expires_at FROM license_units WHERE id=?', (unit,)).fetchone()[0], new_expiry)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM license_renewals WHERE unit_id=?', (unit,)).fetchone()[0], 1)
