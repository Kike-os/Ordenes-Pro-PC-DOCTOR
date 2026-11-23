"""Paso a PRODUCCIÓN (AZUR SIMULADO, base temporal, datos ficticios; ninguna llamada real): el ambiente solo cambia con las dos variables
del servidor; sin el último secuencial del sistema anterior no se emite; continúa en el siguiente número; la clave de AZUR debe ser del
mismo ambiente; credencial y ambiente deben coincidir; el secuencial inicial solo lo fija administración y no se cambia tras emitir."""
import unittest
from unittest.mock import patch

import test_azur
import test_invoicing
import app
import invoicing

PROD_ENV = dict(test_azur.ENV, AZUR_CREDENCIAL='sk_live_credencial_ficticia', AZUR_PRODUCCION_AUTORIZADA='SI', FACTURACION_AMBIENTE='produccion')
POINT = '%s-%s' % (test_invoicing.SETTINGS['establishment'], test_invoicing.SETTINGS['emission_point'])


class ProductionTests(unittest.TestCase):
    A = test_azur.AzurTests
    Base = A.Base
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, emissions = A.setUp, A.tearDown, A.emissions
    request, login, order_data, form, prepare, paid_order, configure = A.request, A.login, A.order_data, A.form, A.prepare, A.paid_order, A.configure

    def test_switch_needs_both_server_variables(self):
        self.assertFalse(invoicing.production_requested({}))
        self.assertFalse(invoicing.production_requested({'FACTURACION_AMBIENTE': 'produccion'}))
        self.assertFalse(invoicing.production_requested({'AZUR_PRODUCCION_AUTORIZADA': 'SI'}))
        self.assertTrue(invoicing.production_requested({'FACTURACION_AMBIENTE': 'produccion', 'AZUR_PRODUCCION_AUTORIZADA': 'SI'}))
        self.assertTrue(invoicing.TEST_MODE)  # el servidor de pruebas sigue en pruebas
        self.assertEqual(invoicing.active_environment(), '1')

    def draft(self, post, order):
        self.configure(post)
        return post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']

    def test_production_continues_after_previous_system(self):
        cookie, csrf, post, order = self.paid_order(11500)
        with patch.object(invoicing, 'TEST_MODE', False), patch.dict(app.os.environ, PROD_ENV), patch.object(test_azur, 'CREDENTIAL', PROD_ENV['AZUR_CREDENCIAL']):
            self.fake.env_digit = '2'
            inv = self.draft(post, order)
            self.assertEqual(inv['environment'], '2')
            blocked = post('/api/invoicing/%d' % inv['id'], action='emit', confirm='1')
            self.assertEqual(blocked['status'], 409)  # sin el último secuencial del sistema anterior no se emite
            self.assertIn('último secuencial', blocked['body']['error'])
            self.assertEqual(post('/api/invoicing/sequence-start', point=POINT, last_number='275')['status'], 400)  # falta confirmar
            self.assertEqual(post('/api/invoicing/sequence-start', point='001-999', last_number='275', confirm='FIJAR SECUENCIAL')['status'], 409)
            done = post('/api/invoicing/sequence-start', point=POINT, last_number='275', confirm='FIJAR SECUENCIAL')
            self.assertEqual((done['status'], done['body']['next_number']), (200, 276), done['body'])
            self.assertEqual(post('/api/invoicing/%d' % inv['id'], action='emit', confirm='1')['status'], 200)
            with app.connect() as c:
                row = c.execute('SELECT environment,sequential,access_key FROM invoices WHERE id=?', (inv['id'],)).fetchone()
                self.assertEqual((row['environment'], row['sequential'], row['access_key'][23]), ('2', 276, '2'))
                self.assertTrue(c.execute("SELECT 1 FROM audit WHERE action LIKE 'invoice_sequence_start%'").fetchone())
            # Ya hay una factura de producción: el secuencial inicial no se vuelve a cambiar.
            self.assertEqual(post('/api/invoicing/sequence-start', point=POINT, last_number='10', confirm='FIJAR SECUENCIAL')['status'], 409)
            sent = post('/api/invoicing/%d' % inv['id'], action='azur_send')
            self.assertEqual(sent['status'], 200, sent['body'])
            st = self.request('/api/invoicing/azur', cookie=cookie)['body']
            self.assertTrue(st['ready'], st['problems'])
        self.assertEqual(self.emissions(), 1)

    def test_key_from_other_environment_stops(self):
        cookie, csrf, post, order = self.paid_order(11500)
        with patch.object(invoicing, 'TEST_MODE', False), patch.dict(app.os.environ, PROD_ENV), patch.object(test_azur, 'CREDENTIAL', PROD_ENV['AZUR_CREDENCIAL']):
            inv = self.draft(post, order)
            post('/api/invoicing/sequence-start', point=POINT, last_number='275', confirm='FIJAR SECUENCIAL')
            self.assertEqual(post('/api/invoicing/%d' % inv['id'], action='emit', confirm='1')['status'], 200)
            self.fake.env_digit = '1'  # AZUR responde con una clave de pruebas a un comprobante de producción
            sent = post('/api/invoicing/%d' % inv['id'], action='azur_send')
            self.assertEqual(sent['status'], 409)
            self.assertIn('ambiente distinto', sent['body']['error'])

    def test_credential_must_match_environment(self):
        cookie, csrf, post, order = self.paid_order(11500)
        self.configure(post)
        with patch.object(invoicing, 'TEST_MODE', False), patch.dict(app.os.environ, dict(PROD_ENV, AZUR_CREDENCIAL=test_azur.CREDENTIAL)):
            st = self.request('/api/invoicing/azur', cookie=cookie)['body']
            self.assertFalse(st['ready'])
            self.assertTrue(any('deben coincidir' in p for p in st['problems']), st['problems'])

    def test_only_admin_sets_sequence(self):
        cookie, csrf, post, order = self.paid_order(11500)
        self.configure(post)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
        self.assertIn(post('/api/invoicing/sequence-start', point=POINT, last_number='275', confirm='FIJAR SECUENCIAL')['status'], (401, 403))


if __name__ == '__main__':
    unittest.main()
