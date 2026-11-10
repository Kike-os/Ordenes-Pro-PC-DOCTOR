"""Firma empresarial visual (1.5.271). Imagen FICTICIA (un QR de prueba con fondo transparente); base temporal; nada se imprime.

Cubre: carga y conservación exacta del original, versiones, permisos, configuración por documento, ticket de 80 mm en blanco y negro sin
deformar y con el QR nítido, inclusión en ticket, comprobante, hoja de servicio y presupuesto solo cuando se activa, vistas previas,
JPEG, y que la imagen nunca se presente como firma electrónica (leyenda y ausencia de /ByteRange)."""
import base64
import io
import struct
import sys
import unittest
import zlib

import test_app  # primero: prepara la ruta de importación y la base temporal
import app
import business_signature as bs
import pdf_signature

sys.path.insert(0, str(__import__('pathlib').Path(app.__file__).resolve().parent / 'vendor'))
import segno  # noqa: E402

app.os.environ.setdefault('LOGIN_CAPTCHA', 'off')


def signature_png(variant=0):
    """PNG RGBA 600×200: QR ficticio a la izquierda y el resto transparente (como una firma con su código)."""
    buf = io.BytesIO()
    segno.make_qr('https://example.invalid/firma-ficticia', error='m').save(buf, kind='png', scale=6, border=2)
    qw, qh, qrgb, _ = bs._png(buf.getvalue())
    w, h = 600, 200
    rows = []
    for y in range(h):
        row = bytearray(b'\x00')
        for x in range(w):
            if x < qw and y < qh:
                v = qrgb[3 * (y * qw + x)]
                row += bytes((v, v, v, 255))
            elif 300 <= x < 560 and 80 <= y < 100:
                row += bytes((10, 40 + variant, 90, 255))  # «nombre» en azul
            else:
                row += bytes((0, 0, 0, 0))
        rows.append(bytes(row))

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b'')


class BusinessSignatureTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login, test_app.SecurityTests.order_data

    def post(self, **body):
        return self.request('/api/business-signature', body, cookie=self.cookie, csrf=self.csrf)

    def upload(self, data, name='firma.png'):
        return self.post(action='upload', filename=name, content=base64.b64encode(data).decode())

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        bs._image.cache_clear()
        bs._thermal.cache_clear()
        self.cookie, self.csrf = self.login()

    def test_original_is_kept_exactly_with_versions_and_audit(self):
        png = signature_png()
        up = self.upload(png)
        self.assertEqual(up['status'], 201, up['body'])
        ov = up['body']['overview']
        self.assertFalse(ov['settings']['enabled'])  # cargar no activa la firma
        self.assertEqual((ov['current']['width'], ov['current']['height'], ov['current']['mime']), (600, 200, 'image/png'))
        got = self.request('/api/business-signature/%d/original' % up['body']['id'], cookie=self.cookie)
        self.assertEqual(got['status'], 200)
        with app.connect() as c:
            self.assertEqual(bytes(c.execute('SELECT data FROM business_signature_versions WHERE id=?', (up['body']['id'],)).fetchone()[0]), png)
            with self.assertRaises(Exception):
                c.execute('DELETE FROM business_signature_versions')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='business_signature_uploaded'").fetchone()[0], 1)
        self.assertTrue(self.upload(png)['body']['duplicate'])
        second = self.upload(signature_png(variant=1), 'firma-2.png')
        self.assertEqual(second['status'], 201)
        self.assertEqual(len(second['body']['overview']['versions']), 2)
        self.assertEqual(second['body']['overview']['settings']['version_id'], up['body']['id'])  # la nueva no reemplaza sola a la elegida

    def test_permissions_and_validation(self):
        self.assertEqual(self.post(action='settings', enabled=True)['status'], 400)  # sin imagen no se activa
        self.assertEqual(self.upload(b'no es una imagen')['status'], 400)
        self.upload(signature_png())
        self.assertEqual(self.post(action='settings', docs='{"factura": true}')['status'], 400)
        self.assertEqual(self.post(action='settings', a4_width_mm='200')['status'], 400)
        self.assertEqual(self.post(action='settings', ticket_width_mm='80')['status'], 400)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=1");c.commit()
        try:
            self.assertEqual(self.request('/api/business-signature', cookie=self.cookie)['status'], 403)
            self.assertEqual(self.upload(signature_png())['status'], 403)
            self.assertEqual(self.post(action='settings', enabled=False)['status'], 403)
        finally:
            with app.connect() as c:c.execute("UPDATE users SET role='administrador' WHERE id=1");c.commit()

    def test_thermal_variant_keeps_proportions_and_a_sharp_qr(self):
        self.upload(signature_png())
        with app.connect() as c:
            vid = bs.settings(c)['version_id']
            sha = c.execute('SELECT sha256 FROM business_signature_versions WHERE id=?', (vid,)).fetchone()[0]
        tw, th, gray = bs._thermal(vid, sha, 48 * bs.DOTS_PER_MM)
        self.assertEqual(tw, 384);self.assertAlmostEqual(th / tw, 200 / 600, delta=.01)
        self.assertEqual(set(gray), {0, 255})  # solo blanco y negro
        # QR: módulos de 6 px → 3,84 puntos de impresora; filas con alternancias nítidas (no un gris borroso).
        row = gray[tw * 40:tw * 41][:140]
        self.assertGreater(sum(1 for a, b in zip(row, row[1:]) if a != b), 10)
        # La transparencia se imprime en blanco.
        self.assertEqual(gray[tw * (th - 1) + tw - 1], 255)
        png = self.request('/api/business-signature/%d/ticket.png?w=48' % vid, cookie=self.cookie)
        self.assertEqual(png['status'], 200)

    def test_documents_include_it_only_when_enabled_and_never_as_a_digital_signature(self):
        order = self.request('/api/orders', self.order_data({'request_key': 'business-signature-0001'}), cookie=self.cookie, csrf=self.csrf)['body']
        get = lambda path: self.request(path, cookie=self.cookie)
        texts = lambda pdf: pdf_signature.page_text(pdf)
        self.upload(signature_png())
        ticket = get('/api/orders/%d/thermal.pdf' % order['id'])['body']
        self.assertNotIn(b'FirmaVisual', ticket)  # cargada pero desactivada
        self.assertEqual(self.post(action='settings', enabled=True, docs='{"ticket": true, "comprobante": true}', ticket_width_mm='48', a4_width_mm='50')['status'], 200)
        ticket = get('/api/orders/%d/thermal.pdf' % order['id'])['body']
        receipt = get('/api/orders/%d/receipt.pdf' % order['id'])['body']
        service = get('/api/orders/%d/service.pdf' % order['id'])['body']
        self.assertIn(b'/FirmaVisualT', ticket);self.assertIn(b'/FirmaVisual', receipt);self.assertNotIn(b'FirmaVisual', service)
        for pdf in (ticket, receipt):
            self.assertIn('Firma visual de identificación de PC-DOCTOR S.A. · No constituye'.encode('cp1252'), texts(pdf))
            self.assertNotIn(b'/ByteRange', pdf);self.assertNotIn(b'/Sig', pdf)
        # Ticket sin firma visual cuando no es legible: opción «omitir».
        self.post(action='settings', ticket_mode='omitir')
        self.assertNotIn(b'FirmaVisual', get('/api/orders/%d/thermal.pdf' % order['id'])['body'])
        # Desactivar la firma la quita de todos los documentos nuevos.
        self.post(action='settings', enabled=False)
        self.assertNotIn(b'FirmaVisual', get('/api/orders/%d/receipt.pdf' % order['id'])['body'])
        with app.connect() as c:
            self.assertGreaterEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='business_signature_settings'").fetchone()[0], 3)

    def test_quote_and_payment_receipt_follow_their_own_switch(self):
        post = lambda path, **body: self.request(path, body, cookie=self.cookie, csrf=self.csrf)
        order = post('/api/orders', **self.order_data({'request_key': 'business-signature-0002'}))['body']
        quote = post('/api/orders/%d/quote' % order['id'])['body']['id']
        post('/api/quotes/%d' % quote, action='save', items=[{'description': 'Servicio ficticio', 'category': 'servicio', 'quantity': 1, 'unit_cents': 2000, 'taxed': True}])
        with app.connect() as c:
            c.execute('INSERT INTO order_budget(order_id,labor_cents) VALUES (?,2000)', (order['id'],));c.commit()
        paid = post('/api/orders/%d/payments' % order['id'], amount='20', method='efectivo')
        self.assertEqual(paid['status'], 201, paid['body'])
        with app.connect() as c:
            pid = c.execute('SELECT id FROM order_payments WHERE order_id=?', (order['id'],)).fetchone()[0]
        quote_pdf = lambda: self.request('/api/quotes/%d/pdf' % quote, cookie=self.cookie)['body']
        receipt = lambda: self.request('/api/orders/%d/payments/%d/receipt.pdf' % (order['id'], pid), cookie=self.cookie)['body']
        self.upload(signature_png())
        self.post(action='settings', enabled=True, docs='{"presupuesto": true}')
        self.assertIn(b'/FirmaVisual', quote_pdf());self.assertNotIn(b'FirmaVisual', receipt())
        self.post(action='settings', docs='{"presupuesto": false, "pago": true}')
        self.assertNotIn(b'FirmaVisual', quote_pdf());self.assertIn(b'/FirmaVisual', receipt())

    def test_previews_and_jpeg(self):
        self.upload(signature_png())
        for doc in ('a4', 'ticket'):
            got = self.request('/api/business-signature/preview.pdf?doc=' + doc, cookie=self.cookie)
            self.assertEqual(got['status'], 200);self.assertIn(b'FirmaVisual', got['body'])
        jpeg = b'\xff\xd8\xff\xc0\x00\x11\x08\x00\x40\x00\xc8\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xd9'
        up = self.upload(jpeg, 'firma.jpg')
        self.assertEqual(up['status'], 201, up['body'])
        self.assertEqual(self.request('/api/business-signature/%d/ticket.png?w=48' % up['body']['id'], cookie=self.cookie)['status'], 409)


if __name__ == '__main__':
    unittest.main()
