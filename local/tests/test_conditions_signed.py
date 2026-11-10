"""Original firmado de las condiciones (1.5.271). Base temporal; el PDF de prueba se firma con un certificado FICTICIO autofirmado
generado aquí con openssl (si no está disponible, las pruebas de firma se omiten). Ningún documento real se modifica."""
import base64
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid

import test_app  # primero: prepara la ruta de importación y la base temporal
import app
import conditions_pdf
import pdf_signature

app.os.environ.setdefault('LOGIN_CAPTCHA', 'off')
TEXT = '1. Diagnóstico\nTexto ficticio de prueba.\n\n2. Garantía\nOtro texto ficticio.'


def sign_pdf(pdf, workdir):
    """Añade una firma PAdES (adbe.pkcs7.detached) firmada con un certificado ficticio. Devuelve el PDF firmado."""
    key, cert = os.path.join(workdir, 'k.pem'), os.path.join(workdir, 'c.pem')
    if not os.path.exists(cert):
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', cert, '-days', '30',
                        '-subj', '/C=EC/O=Prueba Ficticia/CN=FIRMANTE DE PRUEBA'], check=True, capture_output=True)
    placeholder = b'0' * 8192
    tail = (b"\n1000 0 obj\n<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached /M (D:20261110100000-05'00') "
            b"/ByteRange [0 0000000000 0000000000 0000000000] /Contents <" + placeholder + b"> >>\nendobj\n%%EOF\n")
    data = bytearray(pdf + tail)
    b = data.index(b'/Contents <', len(pdf)) + len(b'/Contents ')
    c = b + len(placeholder) + 2
    d = len(data) - c
    brange = b'[0 %010d %010d %010d]' % (b, c, d)
    at = data.index(b'[0 0000000000', len(pdf))
    data[at:at + len(brange)] = brange
    signed = os.path.join(workdir, 'datos.bin')
    with open(signed, 'wb') as out:
        out.write(bytes(data[:b]) + bytes(data[c:]))
    der = subprocess.run(['openssl', 'cms', '-sign', '-binary', '-md', 'sha256', '-outform', 'DER', '-signer', cert, '-inkey', key, '-in', signed],
                         check=True, capture_output=True).stdout
    hexed = der.hex().encode().ljust(len(placeholder), b'0')
    data[b + 1:b + 1 + len(placeholder)] = hexed
    return bytes(data)


@unittest.skipUnless(shutil.which('openssl'), 'openssl no disponible')
class ConditionsSignedTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login

    def version(self, number):
        tid = uuid.uuid4().hex
        with app.connect() as c:
            c.execute('INSERT INTO service_terms(id,version,effective_date,title,full_text,compact_text,content_hash,published_at,published_by) VALUES (?,?,?,?,?,?,?,?,1)',
                      (tid, number, '2026-11-01', 'Condiciones de Recepción y Servicios', TEXT, '1. Resumen ficticio.', hashlib.sha256(TEXT.encode()).hexdigest(), '2026-11-01T10:00:00-05:00'))
            c.commit()
            row = dict(c.execute('SELECT * FROM service_terms WHERE id=?', (tid,)).fetchone())
        return tid, row

    def test_signed_original_is_verified_stored_intact_and_downloadable(self):
        cookie, csrf = self.login()
        tid, row = self.version('2026.11.9')
        work = tempfile.mkdtemp()
        try:
            signed = sign_pdf(conditions_pdf.render_conditions(row), work)
            check = pdf_signature.verify(signed)
            self.assertEqual((check['verified'], check['signer'], check['covers_all']), ('valida', 'FIRMANTE DE PRUEBA', True))
            up = self.request('/api/conditions/%s/signed' % tid, {'filename': 'firmado.pdf', 'content': base64.b64encode(signed).decode()}, cookie=cookie, csrf=csrf)
            self.assertEqual(up['status'], 201, up['body'])
            self.assertEqual((up['body']['verified'], up['body']['sha256']), ('valida', hashlib.sha256(signed).hexdigest()))
            # Se guarda tal cual (byte a byte) y se descarga igual, también desde el enlace público.
            got = self.request('/api/conditions/signed/%d.pdf' % up['body']['id'], cookie=cookie)
            self.assertEqual(got['status'], 200)
            with app.connect() as c:
                self.assertEqual(bytes(c.execute('SELECT data FROM service_terms_signed WHERE id=?', (up['body']['id'],)).fetchone()[0]), signed)
                with self.assertRaises(Exception):
                    c.execute("UPDATE service_terms_signed SET verified='invalida'")
                self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='conditions_signed_uploaded'").fetchone()[0], 1)
            self.assertEqual(self.request('/conditions/%s/firmado.pdf' % tid)['status'], 200)
            page = self.request('/conditions/%s' % tid)['body']
            page = page.decode() if isinstance(page, bytes) else str(page)
            self.assertIn('/conditions/%s/firmado.pdf' % tid, page);self.assertIn('FIRMANTE DE PRUEBA', page)
            # Reverificación del archivo guardado y estado documental en el historial.
            again = self.request('/api/conditions/%s/signed' % tid, {'action': 'verify', 'id': str(up['body']['id'])}, cookie=cookie, csrf=csrf)['body']
            self.assertEqual((again['verified'], again['file_intact']), ('valida', True))
            rows = {r['id']: r for r in self.request('/api/conditions', cookie=cookie)['body']['rows']}
            self.assertTrue(rows[tid]['signed']);self.assertEqual(rows[tid]['signature']['signer'], 'FIRMANTE DE PRUEBA')
            # Subirlo otra vez no duplica el registro.
            self.assertTrue(self.request('/api/conditions/%s/signed' % tid, {'filename': 'firmado.pdf', 'content': base64.b64encode(signed).decode()}, cookie=cookie, csrf=csrf)['body']['duplicate'])
        finally:
            shutil.rmtree(work)

    def test_tampered_or_other_version_or_unsigned_is_rejected(self):
        cookie, csrf = self.login()
        tid, row = self.version('2026.11.10')
        other_id, other = self.version('2026.11.11')
        work = tempfile.mkdtemp()
        try:
            signed = sign_pdf(conditions_pdf.render_conditions(row), work)
            post = lambda pdf, target=tid: self.request('/api/conditions/%s/signed' % target, {'filename': 'x.pdf', 'content': base64.b64encode(pdf).decode()}, cookie=cookie, csrf=csrf)
            tampered = bytearray(signed)
            tampered[200] = (tampered[200] + 1) % 256
            self.assertEqual(pdf_signature.verify(bytes(tampered))['verified'], 'invalida')
            self.assertEqual(post(bytes(tampered))['status'], 409)
            wrong = post(signed, other_id)
            self.assertEqual(wrong['status'], 409);self.assertIn('no corresponde a la versión 2026.11.11', wrong['body']['error'])
            self.assertEqual(post(conditions_pdf.render_conditions(row))['status'], 400)  # sin firma
            self.assertEqual(post(b'no es un pdf')['status'], 400)
            with app.connect() as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM service_terms_signed').fetchone()[0], 0)
                c.execute("UPDATE users SET role='tecnico' WHERE id=1");c.commit()
            try:
                self.assertEqual(post(signed)['status'], 403)
            finally:
                with app.connect() as c:c.execute("UPDATE users SET role='administrador' WHERE id=1");c.commit()
        finally:
            shutil.rmtree(work)


if __name__ == '__main__':
    unittest.main()
