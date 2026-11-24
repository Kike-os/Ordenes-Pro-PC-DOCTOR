"""Smart Fiscal Status 5.0: niveles reales, comprobación de solo lectura y límite de frecuencia. AZUR SIMULADO (ninguna llamada sale a
internet), base temporal y credenciales ficticias. Nunca se muestra verde sin una comprobación satisfactoria."""
import time
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_invoice_ticket as tickets  # prepara la ruta de importación y la base temporal
import app
import azur_client as az
import fiscal_status as fs

ENV = {'AZUR_API_KEY_EMISION': 'API_FICTICIA_DE_PRUEBA', 'AZUR_CREDENCIAL': 'sk_test_ficticia_de_prueba', 'AZUR_PUNTO_EMISION': '001-001'}


class FiscalStatusTests(unittest.TestCase):
    Base = tickets.InvoiceTicketTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, emitted = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.emitted

    def run_check(self, now=None, ping=None, env=ENV):
        now = now or app.reception_now()
        with patch.object(az, 'ping', ping or (lambda cfg: {'ok': True})) as fake, app.connect() as c:
            got = fs.check(c, now, env)
            c.commit()
        return got

    def status(self, now=None, env=ENV):
        with app.connect() as c:
            return fs.status(c, now or app.reception_now(), env)

    def age(self, seconds):
        with app.connect() as c:
            state = fs._get(c, fs.KEY_STATE, {})
            state['checked_epoch'] -= seconds
            state['checked_at'] = (app.reception_now() - timedelta(seconds=seconds)).isoformat(timespec='seconds')
            fs._set(c, fs.KEY_STATE, state)
            c.commit()

    def test_gray_without_any_check_and_never_green_by_default(self):
        got = self.status()
        self.assertEqual((got['level'], got['label']), ('gris', 'Sin verificar'))
        self.assertTrue(got['due'])

    def test_green_only_after_successful_read_only_check(self):
        calls = []
        got = self.run_check(ping=lambda cfg: calls.append('GET /secuenciales') or {})
        self.assertEqual((got['level'], got['auth']), ('verde', 'aceptada'))
        self.assertEqual(calls, ['GET /secuenciales'])
        self.assertTrue(got['last_ok'])

    def test_slow_answer_is_warning(self):
        with patch.object(fs, 'SLOW_MS', 0):
            got = self.run_check()
        self.assertEqual(got['level'], 'amarillo')
        self.assertIn('lenta', got['reason'])

    def test_rejected_credential_connection_and_outage_are_critical(self):
        cases = ((az.AzurError('No autorizado', 'http_401', 401), 'rechazó la credencial', 'rechazada'),
                 (az.AzurError('No hay conexión con AZUR', 'sin_conexion', 0, True), 'No hay conexión', 'desconocida'),
                 (az.AzurError('Error', 'http_503', 503), 'no está disponible', 'desconocida'))
        for error, text, auth in cases:
            self.age(3600) if self.status()['checked_at'] else None

            def boom(cfg, error=error):
                raise error
            got = self.run_check(ping=boom)
            self.assertEqual((got['level'], got['auth']), ('rojo', auth))
            self.assertIn(text, got['reason'])
        self.assertEqual(len(self.status()['history']), 3)

    def test_not_configured_is_critical_without_calling_azur(self):
        called = []
        got = self.run_check(ping=lambda cfg: called.append(1), env={})
        self.assertEqual(got['level'], 'rojo')
        self.assertEqual(called, [])

    def test_green_is_dropped_when_configuration_disappears(self):
        self.run_check()
        self.assertEqual(self.status()['level'], 'verde')
        got = self.status(env={})
        self.assertEqual((got['level'], got['auth']), ('rojo', 'sin_configurar'))

    def test_throttle_one_live_check_per_minute(self):
        self.run_check()
        calls = []
        got = self.run_check(ping=lambda cfg: calls.append(1))
        self.assertTrue(got['throttled'])
        self.assertEqual(calls, [])

    def test_stale_and_intermittent_become_warning_and_recovery_is_logged(self):
        def boom(cfg):
            raise az.AzurError('No hay conexión', 'sin_conexion', 0, True)
        self.run_check(ping=boom)
        self.age(120)
        got = self.run_check()
        self.assertEqual(got['level'], 'amarillo')                    # fallo en la última hora: intermitencia
        self.assertEqual(got['history'][0]['reason'], 'Conexión con AZUR restablecida.')
        with app.connect() as c:
            fs._set(c, fs.KEY_HISTORY, []);c.commit()
        self.assertEqual(self.status()['level'], 'verde')
        self.age(3 * 3600)
        got = self.status()
        self.assertEqual(got['level'], 'amarillo')                    # información desactualizada: nunca verde
        self.assertTrue(got['stale'])

    def test_sri_is_inferred_from_azur_answers_only(self):
        self.assertEqual(self.status()['sri']['level'], 'gris')
        now = app.reception_now()
        with app.connect() as c:
            c.execute("INSERT INTO azur_operations(invoice_id,action,result,code,detail,http_status,created_at) VALUES (NULL,'consultar','pendiente','11','SRI no disponible',200,?)",
                      (now.isoformat(timespec='seconds'),));c.commit()
        self.run_check()
        got = self.status()
        self.assertEqual((got['sri']['level'], got['level']), ('amarillo', 'amarillo'))

    def test_outage_never_changes_authorized_invoices_and_routes(self):
        cookie, csrf, post, inv = self.emitted(key='fiscal')
        with app.connect() as c:
            c.execute("UPDATE invoices SET status='autorizado' WHERE id=?", (inv['id'],));c.commit()
            before = tuple(c.execute('SELECT status,access_key,sequential FROM invoices WHERE id=?', (inv['id'],)).fetchone())
            seq = c.execute('SELECT COALESCE(SUM(last_number),0) FROM invoice_sequences').fetchone()[0]

        def boom(cfg):
            raise az.AzurError('Error', 'http_503', 503)
        with patch.object(az, 'ping', boom), patch.dict(app.os.environ, ENV):
            got = self.request('/api/invoicing/fiscal-status', {'action': 'check'}, cookie=cookie, csrf=csrf)
        self.assertEqual((got['status'], got['body']['level']), (200, 'rojo'))
        self.assertEqual(self.request('/api/invoicing/fiscal-status', cookie=cookie)['body']['level'], 'rojo')
        self.assertEqual(self.request('/api/invoicing/fiscal-status', {'action': 'interval', 'minutes': '7'}, cookie=cookie, csrf=csrf)['status'], 400)
        self.assertEqual(self.request('/api/invoicing/fiscal-status', {'action': 'interval', 'minutes': '15'}, cookie=cookie, csrf=csrf)['body']['interval'], 15)
        with app.connect() as c:
            self.assertEqual(tuple(c.execute('SELECT status,access_key,sequential FROM invoices WHERE id=?', (inv['id'],)).fetchone()), before)
            self.assertEqual(c.execute('SELECT COALESCE(SUM(last_number),0) FROM invoice_sequences').fetchone()[0], seq)


if __name__ == '__main__':
    unittest.main()
