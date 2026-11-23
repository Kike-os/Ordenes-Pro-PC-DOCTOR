"""Bloqueo de emisión y envío (1.5.319), contra un AZUR SIMULADO, base temporal y datos ficticios: con el bloqueo cerrado el SERVIDOR
rechaza emitir (no consume secuencial), enviar, anular, la consulta programada y los correos de factura; la variable de entorno bloquea
por sí sola incluso con la base abierta; solo administración abre, con confirmación escrita y motivo, y queda en un historial inmutable."""
import sqlite3
import unittest
from unittest.mock import patch

import test_azur
import app
import azur_client
import emission_lock

ENV = test_azur.ENV


class EmissionLockTests(unittest.TestCase):
    A = test_azur.AzurTests
    Base = A.Base
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, emitted, emissions = A.setUp, A.tearDown, A.emitted, A.emissions
    request, login, order_data, form, prepare, paid_order, configure = A.request, A.login, A.order_data, A.form, A.prepare, A.paid_order, A.configure

    def close(self):
        with app.connect() as c:
            c.execute('UPDATE invoicing_emission_lock SET locked=1 WHERE id=1')

    def sequence(self):
        with app.connect() as c:
            row = c.execute('SELECT COALESCE(MAX(last_number),0) FROM invoice_sequences').fetchone()
            return row[0]

    def test_default_after_migration_is_locked(self):
        with app.connect() as c:
            c.execute('DELETE FROM invoicing_emission_lock')  # recién migrada, sin fila: falla cerrado
            self.assertTrue(emission_lock.is_locked(c, {'FACTURACION_EMISION_BLOQUEADA': 'NO'}))
        mem = sqlite3.connect(':memory:')  # sin tabla (migración pendiente): falla cerrado
        self.assertTrue(emission_lock.is_locked(mem, {'FACTURACION_EMISION_BLOQUEADA': 'NO'}))
        self.assertTrue(emission_lock.env_locked({}))  # sin variable: bloqueado

    def test_locked_server_rejects_emit_send_annul_and_mail(self):
        cookie, csrf, post, order = self.paid_order(11500)
        self.configure(post)
        inv = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
        self.close()
        before = self.sequence()
        emit = post('/api/invoicing/%d' % inv['id'], action='emit', confirm='1')
        self.assertEqual(emit['status'], 423, emit['body'])
        self.assertIn(emission_lock.BANNER, emit['body']['error'])
        self.assertEqual(self.sequence(), before)  # no se consumió secuencial
        with patch.dict(app.os.environ, ENV):
            self.assertEqual(post('/api/invoicing/%d' % inv['id'], action='azur_send')['status'], 423)
            self.assertEqual(post('/api/invoicing/%d' % inv['id'], action='azur_annul', confirm='ANULAR', reason='Motivo ficticio de prueba')['status'], 423)
            self.assertEqual(post('/api/invoicing/%d/send' % inv['id'], kind='prueba')['status'], 423)
            st = self.request('/api/invoicing/azur', cookie=cookie)['body']
            self.assertTrue(st['emission_lock']['locked'])
            self.assertEqual(st['emission_lock']['banner'], emission_lock.BANNER)
        self.assertEqual(self.emissions(), 0)
        self.assertFalse([p for m, p, h in self.fake.calls if m == 'POST'])

    def test_env_variable_blocks_network_even_if_db_open(self):
        cookie, post, iid = self.emitted()
        with patch.dict(app.os.environ, dict(ENV, FACTURACION_EMISION_BLOQUEADA='')):
            self.assertEqual(post('/api/invoicing/%d' % iid, action='azur_send')['status'], 423)
            with self.assertRaises(azur_client.AzurError) as ctx:  # aunque alguien llame al cliente directamente
                azur_client.emit_invoice(azur_client.config(), {'x': 1}, 'clave-ficticia')
            self.assertEqual(ctx.exception.code, 'emision_bloqueada')
        self.assertEqual(self.emissions(), 0)

    def test_cron_and_autosend_do_nothing_while_locked(self):
        cookie, post, iid = self.emitted()
        with patch.dict(app.os.environ, ENV):
            self.assertEqual(post('/api/invoicing/%d' % iid, action='azur_send')['status'], 200)
            self.close()
            calls = len(self.fake.calls)
            self.fake.state = 4
            with app.connect() as c:
                self.assertEqual(app.invoice_autosend(c, iid, None, app.reception_now()), {'sent': False, 'error': emission_lock.BANNER})
                import invoice_documents
                with self.assertRaises(invoice_documents.DocumentError):
                    invoice_documents.send(c, iid, 'cliente', None, app.reception_now(), lambda *a: self.fail('no debe enviar'))
            self.assertEqual(len(self.fake.calls), calls)

    def test_only_admin_opens_with_confirmation_and_history(self):
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        self.close()
        self.assertEqual(post('/api/invoicing/emission-lock', locked='0', reason='Motivo suficiente')['status'], 400)
        self.assertEqual(post('/api/invoicing/emission-lock', locked='0', confirm='HABILITAR EMISION', reason='corto')['status'], 400)
        with patch.dict(app.os.environ, {'FACTURACION_EMISION_BLOQUEADA': ''}):
            opened = post('/api/invoicing/emission-lock', locked='0', confirm='HABILITAR EMISION', reason='Autorización ficticia de prueba')
            self.assertEqual(opened['status'], 200, opened['body'])
            self.assertFalse(opened['body']['db_locked'])
            self.assertTrue(opened['body']['locked'])  # la variable de entorno sigue bloqueando
            self.assertIn('warning', opened['body'])
        self.assertEqual(post('/api/invoicing/emission-lock', locked='1', reason='Cierre ficticio')['status'], 200)
        with app.connect() as c:
            self.assertEqual([r[0] for r in c.execute('SELECT locked FROM invoicing_emission_lock_events ORDER BY id')], [0, 1])
            self.assertTrue(c.execute("SELECT 1 FROM audit WHERE action='emission_lock_opened'").fetchone())
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
        self.assertIn(post('/api/invoicing/emission-lock', locked='1')['status'], (401, 403))


if __name__ == '__main__':
    unittest.main()
