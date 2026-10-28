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
    for match in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', raw, re.S):
        try:
            out.append(zlib.decompress(match.group(1)).decode('cp1252', 'replace'))
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
        self.assertIn('No. ' + inv['number'], ride)
        self.assertNotIn('PC-DOCTOR S.A.', ride.replace(inv.get('legal_name', '') or '\x00', ''))
        t = inv['total_cents']
        self.assertIn('$' + format(t // 100, ',d').replace(',', '.') + ',%02d' % (t % 100), ride)


if __name__ == '__main__':
    unittest.main()
