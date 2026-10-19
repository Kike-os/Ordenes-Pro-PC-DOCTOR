"""Servicio de cita «Servicio de Administración Remota» y texto del selector de servicios."""
import unittest

import test_app
import app


class RemoteServiceTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request

    def test_remote_administration_service_is_offered_publicly(self):
        services = {item['code']: item for item in self.request('/api/public/appointments/services')['body']['services']}
        self.assertEqual(services['remota']['label'], 'Servicio de Administración Remota')
        self.assertEqual(services['remota']['duration_minutes'], 60)
        self.assertIn('<legend>Selecciona el Servicio', (app.ROOT / 'templates' / 'appointments.html').read_text())
        self.assertIn("el('legend','Selecciona el Servicio *')", (app.ROOT / 'static' / 'app.js').read_text())


if __name__ == '__main__':
    unittest.main()
