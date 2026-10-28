"""PDF de la proforma y de la factura (RIDE) con la identidad de PC-DOCTOR: nombre comercial sin «S.A.» en el encabezado y el pie, leyenda de
proforma no tributaria, advertencia de prueba en el RIDE, código único de la proforma, clave de acceso real, importes iguales a los registrados,
paginación y nombres de archivo automáticos. Base temporal y datos ficticios."""
import json
import re
import unittest
import zlib

import test_app
import test_invoicing
import document_style


def pdf_text(raw):
    """Texto de todos los flujos (comprimidos) del PDF."""
    out = []
    for match in re.finditer(rb'/Length (\d+)[^>]*>>\s*stream\r?\n', raw):  # cada flujo con su longitud declarada
        data = raw[match.end():match.end() + int(match.group(1))]
        try:
            out.append(zlib.decompress(data).decode('cp1252', 'replace'))
        except zlib.error:
            pass
    return '\n'.join(re.findall(r'\((.*?)\) ?Tj', '\n'.join(out)))


class DocumentStyleTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure

    def test_filenames(self):
        self.assertEqual(document_style.filename('PROFORMA', 'PF-000001'), 'PC-DOCTOR_PROFORMA_PF-000001.pdf')
        self.assertEqual(document_style.filename('FACTURA', '001-001-000000001'), 'PC-DOCTOR_FACTURA_001-001-000000001.pdf')

    def test_proforma_and_ride_share_identity_and_keep_legal_differences(self):
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        items = [{'kind': 'servicio', 'code': 'SRV-%02d' % n, 'description': 'Servicio ficticio %d con una descripción larga para comprobar el ajuste automático del texto' % n,
                  'quantity': '1', 'unit_price': '%d,00' % (10 + n)} for n in range(40)]
        pf = post('/api/proformas', origin='cliente', items=json.dumps(items), client_name='Cliente Ficticio', client_identification='0100000017', request_key='estilo-proforma-000001')
        self.assertEqual(pf['status'], 200, pf['body'])
        raw = self.request('/api/proformas/%d.pdf' % pf['body']['id'], cookie=cookie)['body']
        text = pdf_text(raw)
        self.assertIn('PC-DOCTOR', text)
        self.assertNotIn('PC-DOCTOR S.A.', text)
        self.assertIn('PROFORMA COMERCIAL', text)
        self.assertIn(pf['body']['proforma']['code'], text)  # identificador impreso bajo el Code 128
        self.assertIn('Página 2 de', text)
        pages = int(re.search(r'Página 1 de (\d+)', text).group(1))
        self.assertGreaterEqual(pages, 2)
        self.assertGreaterEqual(text.count('Descripción'), 2)  # encabezado de la tabla repetido en cada página que la contiene
        total = pf['body']['totals']['total_cents']
        self.assertIn('$' + format(total // 100, ',d').replace(',', '.') + ',%02d' % (total % 100), text)
        self.assertNotIn('clave de acceso', text.lower())  # la proforma no usa datos tributarios del SRI
        # Factura directa emitida en pruebas.
        self.configure(post)
        d = post('/api/proformas', origin='directa', items=json.dumps(items[:3]), client_name='Cliente Ficticio', client_identification='0100000017', request_key='estilo-directa-0000001')
        made = post('/api/proformas/%d' % d['body']['id'], action='checkout', payments='[]', emit='1', request_key='estilo-cobro-00000001')
        self.assertEqual(made['status'], 200, made['body'])
        self.assertEqual(made['body']['emit_error'], '', made['body']['emit_error'])
        inv = made['body']['invoice']
        got = self.request('/api/invoicing/%d/ride.pdf' % inv['id'], cookie=cookie)
        self.assertEqual(got['status'], 200, got['body'] if not isinstance(got['body'], bytes) else got['body'][:200])
        self.assertTrue(got['body'].startswith(b'%PDF'), got['body'][:200])
        ride = pdf_text(got['body'])
        self.assertTrue(ride, 'Sin texto legible en el RIDE (%d bytes)' % len(got['body']))
        self.assertIn('DOCUMENTO DE PRUEBA', ride)  # nunca se presenta como autorizada
        self.assertIn('Ambiente de pruebas: no autorizada', ride)
        self.assertIn(inv['access_key'], ride)
        self.assertIn('No.\n' + inv['number'], ride)  # etiqueta y número del comprobante
        self.assertNotIn('PC-DOCTOR S.A.', ride.replace(inv.get('legal_name', '') or '\x00', ''))
        t = inv['total_cents']
        self.assertIn('$' + format(t // 100, ',d').replace(',', '.') + ',%02d' % (t % 100), ride)


    def test_ride_warning_depends_only_on_real_authorization(self):
        """Base temporal ficticia: solo una factura autorizada en ambiente 2 deja de mostrar la advertencia; en pruebas, siempre se muestra."""
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        self.configure(post)
        items = json.dumps([{'kind': 'servicio', 'description': 'Servicio ficticio', 'quantity': '1', 'unit_price': '11,50'}])
        d = post('/api/proformas', origin='directa', items=items, client_name='Cliente Ficticio', client_identification='0100000017', request_key='ride-estado-00000001')
        made = post('/api/proformas/%d' % d['body']['id'], action='checkout', payments='[]', emit='1', request_key='ride-estado-cobro-001')
        iid = made['body']['invoice_id']
        test_pdf = pdf_text(self.request('/api/invoicing/%d/ride.pdf' % iid, cookie=cookie)['body'])
        self.assertIn('DOCUMENTO DE PRUEBA', test_pdf)
        self.assertIn('PRUEBAS', test_pdf)
        import app
        with app.connect() as c:  # solo en la base temporal: simula la respuesta de autorización del SRI para revisar la presentación
            c.execute("UPDATE invoices SET environment='2',status='autorizado',authorization_number=access_key,authorized_at='2026-10-28T09:00:00-05:00' WHERE id=?", (iid,))
            c.commit()
        real = pdf_text(self.request('/api/invoicing/%d/ride.pdf' % iid, cookie=cookie)['body'])
        self.assertNotIn('SIN VALIDEZ TRIBUTARIA', real)
        self.assertIn('PRODUCCIÓN', real)
        self.assertIn('2026-10-28 09:00:00', real)


    def test_proforma_phones_status_invoice_and_advances(self):
        import proformas
        self.assertEqual(proformas.phones('0991234567 / 022345678'), ['0991234567', '022345678'])
        self.assertEqual(proformas.phones('0223456780987654321'), ['022345678', '0987654321'])  # una sola división válida
        self.assertEqual(proformas.phones('022345678098765432'), ['022345678098765432'])  # dudoso: se muestra tal como está registrado
        self.assertEqual(proformas.phones(''), [])
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        self.configure(post)
        items = json.dumps([{'kind': 'servicio', 'description': 'Servicio ficticio', 'quantity': '1', 'unit_price': '20,00'}])
        pf = post('/api/proformas', origin='cliente', items=items, client_name='Cliente Ficticio', client_identification='0100000017', client_phone='0991234567 / 022345678',
                  request_key='pdf-anticipo-proforma-1')
        self.assertEqual(post('/api/proformas/%d' % pf['body']['id'], action='advance', method='efectivo', amount='5', request_key='pdf-anticipo-cobro-001')['status'], 200)
        text = pdf_text(self.request('/api/proformas/%d.pdf' % pf['body']['id'], cookie=cookie)['body'])
        for expected in ('0991234567 · 022345678', 'Anticipos confirmados', '$5,00', 'Saldo pendiente', '$15,00', 'Suma de partidas', 'IVA incluido', 'Base imponible 15 %'):
            self.assertIn(expected, text)
        d = post('/api/proformas', origin='directa', items=items, client_name='Cliente Ficticio', client_identification='0100000017', request_key='pdf-convertida-000001')
        made = post('/api/proformas/%d' % d['body']['id'], action='checkout', payments=json.dumps([{'method': 'efectivo', 'amount': '20,00'}]), emit='1', request_key='pdf-convertida-cobro1')
        self.assertEqual(made['status'], 200, made['body'])
        text = pdf_text(self.request('/api/proformas/%d.pdf' % d['body']['id'], cookie=cookie)['body'])
        self.assertIn('Convertida a factura', text)
        self.assertIn(made['body']['invoice']['number'], text)  # referencia a la factura vinculada
        self.assertIn('ya fue convertida en la factura', text)
        self.assertIn('Saldo pendiente', text)


if __name__ == '__main__':
    unittest.main()
