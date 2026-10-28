"""Integración con AZUR contra un AZUR SIMULADO (sin red, sin emisión real, datos ficticios, base temporal): configuración y bloqueo de
producción, envío sin duplicados (doble clic, corte de conexión, secuencial ya usado), estados del SRI (pendiente, autorizado, rechazado y
reproceso), documentos guardados, correo de prueba nunca al cliente, anulación con confirmación y que ninguna credencial aparezca."""
import base64
import json
import unittest
from unittest.mock import patch

import test_invoicing
import app
import azur_client

EMISSION, CREDENTIAL = 'API_clave_ficticia_de_prueba', 'sk_test_credencial_ficticia_de_prueba'
ENV = {'AZUR_API_KEY_EMISION': EMISSION, 'AZUR_CREDENCIAL': CREDENTIAL, 'AZUR_PUNTO_EMISION': '001-001', 'AZUR_PRODUCCION_AUTORIZADA': ''}


class FakeAzur:
    """AZUR simulado: recuerda las claves de idempotencia y los secuenciales, y responde como su API v2."""

    def __init__(self, ruc):
        self.ruc, self.docs, self.by_key, self.calls, self.state, self.fail_next, self.env_digit, self.annul_error = ruc, {}, {}, [], 3, None, '1', None

    def key_for(self, seq):
        body = '27102026' + '01' + self.ruc + self.env_digit + '001001' + seq + '12345678' + '1'
        return body + '7'

    def __call__(self, method, url, headers, body):
        path = url.split('/api/v2', 1)[1]
        self.calls.append((method, path.split('?')[0], dict(headers)))
        if self.fail_next:
            error, self.fail_next = self.fail_next, None
            raise error
        if path == '/factura/emision':
            assert headers['X-Api-Key'] == EMISSION and headers.get('Idempotency-Key')
            idem = headers['Idempotency-Key']
            if idem in self.by_key:
                return 200, {'creado': True, 'claveacceso': self.docs[self.by_key[idem]]['claveacceso']}
            seq = body['emisor']['secuencial']
            if any(d['seq'] == seq for d in self.docs.values()):
                return 200, {'creado': False, 'claveacceso': '', 'errors': {'error': 'El secuencial ya existe para este punto de emisión'}}
            doc_id = 900 + len(self.docs)
            self.docs[doc_id] = {'seq': seq, 'claveacceso': self.key_for(seq), 'body': body}
            self.by_key[idem] = doc_id
            return 200, {'creado': True, 'claveacceso': self.docs[doc_id]['claveacceso']}
        assert headers['X-Api-Key'] == CREDENTIAL
        if path.startswith('/facturas'):
            term = path.split('buscar=')[1].split('&')[0]
            rows = [{'id': i, 'claveacceso': d['claveacceso'], 'secuencial': '001-001-' + d['seq']} for i, d in self.docs.items() if term in (d['claveacceso'], '001-001-' + d['seq'])]
            return 200, {'ok': True, 'datos': rows}
        doc_id = int(path.split('/')[2])
        if path.endswith('/estado') or '/estado?' in path:
            st = {'codigo': self.state, 'claveacceso': self.docs[doc_id]['claveacceso'], 'reprocesable': self.state in (5, 6)}
            if self.state == 4:
                st.update(fecha_autorizacion='2026-10-27T23:50:00-05:00', autorizado=True)
            if self.state == 5:
                st['errores'] = ['ERROR 65: fecha de emisión extemporánea (ficticio)']
            return 200, {'ok': True, 'datos': st}
        if '/pdf' in path or '/xml' in path:
            content = b'%PDF-1.4 ficticio' if '/pdf' in path else b'<factura id="comprobante">ficticia</factura>'
            return 200, {'ok': True, 'datos': {'contenido': base64.b64encode(content).decode()}}
        if path.endswith('/anular'):
            if self.annul_error:
                return 409, {'ok': False, 'error': {'codigo': self.annul_error, 'mensaje': 'No consta la solicitud', 'reintentable': False}}
            return 200, {'ok': True, 'datos': {'id': doc_id, 'estado': 9}}
        if path.endswith('/reprocesar'):
            self.state = 3
            return 200, {'ok': True, 'datos': {'id': doc_id}}
        return 404, {'ok': False, 'error': {'codigo': 'no_encontrado', 'mensaje': 'No encontrado'}}


class AzurTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    request, login, order_data, form, prepare, paid_order, configure = Base.request, Base.login, Base.order_data, Base.form, Base.prepare, Base.paid_order, Base.configure

    def setUp(self):
        self.Base.setUp(self)
        self.fake = FakeAzur(test_invoicing.SETTINGS['ruc'])
        self.transport = patch.object(azur_client, 'TRANSPORT', self.fake)
        self.transport.start()

    def tearDown(self):
        self.transport.stop()
        self.Base.tearDown(self)

    def emitted(self, key='0001'):
        cookie, csrf, post, order = self.paid_order(11500, key=key)
        self.configure(post)
        inv = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
        self.assertEqual(post('/api/invoicing/%d' % inv['id'], action='emit', confirm='1')['status'], 200)
        return cookie, post, inv['id']

    def emissions(self):
        return len(self.fake.docs)  # comprobantes creados en AZUR (un intento cortado no crea nada)

    def test_configuration_and_production_guard(self):
        cookie, post, iid = self.emitted()
        with patch.dict(app.os.environ, {k: '' for k in ENV}):
            st = self.request('/api/invoicing/azur', cookie=cookie)['body']
            self.assertFalse(st['ready'])
            self.assertTrue(any('AZUR_API_KEY_EMISION' in p for p in st['problems']))
            self.assertEqual(post('/api/invoicing/%d' % iid, action='azur_send')['status'], 409)
        with patch.dict(app.os.environ, dict(ENV, AZUR_CREDENCIAL='sk_live_credencial_ficticia')):
            st = self.request('/api/invoicing/azur', cookie=cookie)['body']
            self.assertTrue(any('PRODUCCIÓN' in p for p in st['problems']))
            self.assertEqual(post('/api/invoicing/%d' % iid, action='azur_send')['status'], 409)
        with patch.dict(app.os.environ, dict(ENV, AZUR_PUNTO_EMISION='001-002')):
            st = self.request('/api/invoicing/azur', cookie=cookie)['body']
            self.assertTrue(any('no coincide' in p for p in st['problems']))  # evita choques de numeración con Mi Negocio
        self.assertEqual(self.emissions(), 0)

    def test_send_without_duplicates_authorize_files_and_test_mail_only(self):
        cookie, post, iid = self.emitted()
        with patch.dict(app.os.environ, ENV):
            self.assertTrue(self.request('/api/invoicing/azur', cookie=cookie)['body']['ready'])
            # Corte de conexión: no se crea nada y se puede reintentar con la misma clave.
            self.fake.fail_next = azur_client.AzurError('sin conexión', 'sin_conexion', 0, True)
            cut = post('/api/invoicing/%d' % iid, action='azur_send')
            self.assertEqual(cut['status'], 502)
            sent = post('/api/invoicing/%d' % iid, action='azur_send')
            self.assertEqual(sent['status'], 200, sent['body'])
            inv = sent['body']['invoice']
            self.assertEqual((inv['status'], inv['provider_id'], inv['access_key'][23]), ('enviado', 900, '1'))
            again = post('/api/invoicing/%d' % iid, action='azur_send')  # doble clic: consulta, no emite
            self.assertEqual(again['status'], 200)
            self.assertEqual(self.emissions(), 1)
            keys = {h['Idempotency-Key'] for m, p, h in self.fake.calls if p == '/factura/emision'}
            self.assertEqual(len(keys), 1)
            body = self.fake.docs[900]['body']
            self.assertNotIn('correo', body['comprador'])  # AZUR nunca escribe al cliente
            self.assertEqual(body['emisor']['secuencial'], '%09d' % 1)
            self.assertEqual(round(sum(i['cantidad'] * i['precio_unitario'] - i['descuento'] for i in body['items']), 2), 100.0)  # sin IVA: $115,00 con IVA
            self.assertEqual([i['tipo_iva'] for i in body['items']], [4])
            # Autorizada: número y fecha reales del SRI, PDF y XML guardados, y el correo solo a la dirección de prueba.
            self.fake.state = 4
            done = post('/api/invoicing/%d' % iid, action='azur_sync')
            self.assertEqual(done['status'], 200, done['body'])
            inv = done['body']['invoice']
            self.assertEqual((inv['status'], inv['authorization_number'], inv['authorized_at']), ('autorizado', self.fake.docs[900]['claveacceso'], '2026-10-27T23:50:00-05:00'))
            self.assertTrue(done['body']['azur']['newly_authorized'])
            self.assertEqual(done['body']['azur']['mail']['sent'], False)  # sin correo configurado en la prueba: queda registrado
            self.assertEqual(self.request('/api/invoicing/%d/azur/pdf' % iid, cookie=cookie)['body'][:5], b'%PDF-')
            with app.connect() as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM invoice_provider_files WHERE invoice_id=?', (iid,)).fetchone()[0], 3)
                self.assertTrue(c.execute("SELECT 1 FROM invoice_events WHERE invoice_id=? AND event='correo_pendiente'", (iid,)).fetchone())
                self.assertFalse(c.execute("SELECT 1 FROM mail_archive WHERE recipient LIKE '%cliente%'").fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE name='mail_archive'").fetchone() else False)
                logs = json.dumps([tuple(r) for r in c.execute('SELECT * FROM azur_operations')], ensure_ascii=False)
            self.assertNotIn(EMISSION, logs)
            self.assertNotIn(CREDENTIAL, logs)
            self.assertNotIn(CREDENTIAL, json.dumps(self.request('/api/invoicing/azur', cookie=cookie)['body'], ensure_ascii=False))

    def test_rejected_reprocess_sequential_recovery_and_production_key(self):
        cookie, post, iid = self.emitted()
        with patch.dict(app.os.environ, ENV):
            self.fake.state = 5
            sent = post('/api/invoicing/%d' % iid, action='azur_send')
            self.assertEqual(sent['body']['invoice']['status'], 'rechazado')
            self.assertIn('extemporánea', json.dumps(sent['body']['invoice']['sri_messages'], ensure_ascii=False))
            redo = post('/api/invoicing/%d' % iid, action='azur_send')  # reprocesa el mismo comprobante
            self.assertEqual((redo['status'], redo['body']['invoice']['status']), (200, 'enviado'))
            self.assertEqual(self.emissions(), 1)
            self.assertTrue(any(p.endswith('/reprocesar') for m, p, h in self.fake.calls))
        # Secuencial ya registrado en AZUR (respuesta perdida): se recupera el documento existente sin emitir otro.
        cookie2, post2, iid2 = self.emitted('0002')
        with patch.dict(app.os.environ, ENV):
            self.fake.docs[950] = {'seq': '%09d' % 2, 'claveacceso': self.fake.key_for('%09d' % 2), 'body': {}}
            rec = post2('/api/invoicing/%d' % iid2, action='azur_send')
            self.assertEqual((rec['status'], rec['body']['invoice']['provider_id']), (200, 950), rec['body'])
        # Si AZUR devolviera una clave de PRODUCCIÓN, todo se detiene con una alerta.
        cookie3, post3, iid3 = self.emitted('0003')
        with patch.dict(app.os.environ, ENV):
            self.fake.env_digit = '2'
            bad = post3('/api/invoicing/%d' % iid3, action='azur_send')
            self.assertEqual(bad['status'], 409)
            self.assertIn('PRODUCCIÓN', bad['body']['error'])

    def test_annulment_needs_confirmation_and_sri_request(self):
        cookie, post, iid = self.emitted()
        with patch.dict(app.os.environ, ENV):
            self.fake.state = 4
            post('/api/invoicing/%d' % iid, action='azur_send')
            self.assertEqual(post('/api/invoicing/%d' % iid, action='azur_annul', confirm='SI', reason='Error en el comprador (ficticio)')['status'], 400)
            self.fake.annul_error = 'anulacion_no_solicitada'
            no = post('/api/invoicing/%d' % iid, action='azur_annul', confirm='ANULAR', reason='Error en el comprador (ficticio)')
            self.assertEqual(no['status'], 409)
            self.assertIn('SRI en línea', no['body']['error'])
            self.fake.annul_error = None
            ok = post('/api/invoicing/%d' % iid, action='azur_annul', confirm='ANULAR', reason='Error en el comprador (ficticio)')
            self.assertEqual(ok['status'], 200, ok['body'])
            self.assertEqual(ok['body']['invoice']['annulment']['source'], 'usuario')
            self.assertEqual(ok['body']['invoice']['status'], 'autorizado')  # el comprobante autorizado no se modifica
            with app.connect() as c:
                c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
                c.commit()
            self.assertEqual(post('/api/invoicing/%d' % iid, action='azur_send')['status'], 403)


if __name__ == '__main__':
    unittest.main()
