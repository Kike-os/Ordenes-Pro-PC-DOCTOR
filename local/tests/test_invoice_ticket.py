"""PC-DOCTOR — Tech Retail Invoice 4.0 (ticket térmico de factura). Base temporal, datos ficticios y emisión en el ambiente de PRUEBAS.

Cubre: 80 y 58 mm con una y varias partidas, descripciones y nombres extensos, descuentos y formas de pago; copias; importes idénticos a la
factura registrada; clave de acceso completa legible por el lector en Code 128 y QR a 203 dpi; que imprimir o descargar NO emite, no consume
secuenciales, no crea pagos ni eventos y no envía nada; que un borrador no se imprime; permisos y que nunca aparecen credenciales."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_invoicing as base
import app
import invoice_ticket

TOOLS = bool(shutil.which('pdftoppm') and shutil.which('zbarimg'))


class InvoiceTicketTests(unittest.TestCase):
    Base = base.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data, form, prepare, paid_order, configure = (Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data,
                                                                                       Base.form, Base.prepare, Base.paid_order, Base.configure)

    def emitted(self, cents=14535, key='ticket'):
        cookie, csrf, post, order = self.paid_order(cents, key=key)
        self.configure(post)
        inv = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
        done = post('/api/invoicing/%d' % inv['id'], action='emit', confirm='1')['body']['invoice']
        return cookie, csrf, post, done

    def snapshot(self):
        with app.connect() as c:
            return tuple(c.execute('SELECT (SELECT COUNT(*) FROM invoices),(SELECT COALESCE(SUM(total_cents),0) FROM invoices),(SELECT COUNT(*) FROM invoice_events),'
                                   '(SELECT COALESCE(SUM(last_number),0) FROM invoice_sequences),(SELECT COUNT(*) FROM invoice_mail),(SELECT COUNT(*) FROM order_payments)').fetchone())

    def text_of(self, pdf):
        # Texto visible del PDF (los flujos van comprimidos): se extrae con pdftotext si está, si no se omite la comprobación.
        if not shutil.which('pdftotext'):
            return None
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 't.pdf'
            path.write_bytes(pdf)
            return subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True).stdout

    def test_ticket_80_and_58_with_exact_amounts_and_no_side_effects(self):
        cookie, csrf, post, inv = self.emitted()
        before = self.snapshot()
        for fmt in ('80', '58'):
            got = self.request('/api/invoicing/%d/ticket.pdf?format=%s&copies=2' % (inv['id'], fmt), cookie=cookie)
            self.assertEqual(got['status'], 200, got['body'] if isinstance(got['body'], dict) else '')
            pdf = got['body']
            self.assertTrue(pdf.startswith(b'%PDF'))
            self.assertEqual(pdf.count(b'/Type /Page') - pdf.count(b'/Type /Pages'), 2)          # dos copias = dos páginas
            text = self.text_of(pdf)
            if text is not None:
                self.assertIn(inv['number'], text)
                self.assertIn('$145,35', text)                                                    # total exacto de la factura
                self.assertIn('DOCUMENTO DE PRUEBA', text)                                        # no autorizada en producción
                self.assertNotRegex(text, r'(?i)contrase(n|ñ)a|usuario:')                         # nunca credenciales
        self.assertEqual(self.snapshot(), before)                                                 # imprimir no emite ni cambia nada

    @unittest.skipUnless(TOOLS, 'pdftoppm y zbarimg no están instalados')
    def test_access_key_barcode_parts_and_qr_readable_at_203_dpi(self):
        """Epson Precision Print 4.2: la clave completa se lee en el QR y en el Code 128 dividido en partes (80 mm: 2; 58 mm: 3) con módulos de
        2 puntos, en 30 claves al azar más la de una factura emitida. Unidas en orden, las partes forman la clave."""
        import random
        cookie, csrf, post, inv = self.emitted(key='lector')
        with app.connect() as c:
            data = invoice_ticket.data_for(c, inv['id'])
        keys = [inv['access_key']]
        for n in range(29):
            rnd = random.Random(n)
            keys.append(''.join(rnd.choice('0123456789') for _ in range(49)))
        for fmt, count in (('80', 2), ('58', 3)):
            read = 0
            for key in keys:
                parts = invoice_ticket.key_parts(key, fmt)
                self.assertEqual((''.join(parts), len(parts)), (key, count))
                data['invoice']['access_key'] = key
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / 't.pdf'
                    path.write_bytes(invoice_ticket.render(data, fmt))
                    subprocess.run(['pdftoppm', '-r', '203', '-gray', '-png', str(path), str(Path(folder) / 'p')], check=True)
                    found = subprocess.run(['zbarimg', '-q'] + [str(p) for p in sorted(Path(folder).glob('p*.png'))], capture_output=True, text=True).stdout
                codes = sorted(line.split(':', 1)[1] for line in found.splitlines() if line.startswith('CODE-128:'))
                read += codes == sorted(parts) and ('QR-Code:' + key) in found
            self.assertEqual(read, len(keys), fmt)

    def test_epson_geometry_sizes_and_no_trailing_space(self):
        """Página del ancho del papel (80/58 mm) con contenido centrado de 68/44 mm, altura según el contenido y sin espacio al final."""
        import re as _re
        data = invoice_ticket.calibration_data()
        for fmt, page_mm, content_mm in (('80', 80, 68), ('58', 58, 44)):
            pdf = invoice_ticket.render(data, fmt)
            box = [float(v) for v in _re.search(rb'/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]', pdf).groups()]
            self.assertAlmostEqual(box[0], page_mm * 72 / 25.4, places=2)
            spec = invoice_ticket.FORMATS[fmt]
            self.assertAlmostEqual(spec['content'], content_mm * 72 / 25.4, places=2)
            one = invoice_ticket.render(dict(data, items=data['items'][:1]), fmt)
            short = float(_re.search(rb'/MediaBox \[0 0 [\d.]+ ([\d.]+)\]', one).group(1))
            self.assertLess(short, box[1])                                                     # la altura sigue al contenido
            if shutil.which('pdftoppm'):
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / 't.pdf'
                    path.write_bytes(pdf)
                    subprocess.run(['pdftoppm', '-r', '203', '-gray', '-singlefile', str(path), str(Path(folder) / 'p')], check=True)
                    raw = (Path(folder) / 'p.pgm').read_bytes()
                    head = raw.split(maxsplit=4)
                    width, height = int(head[1]), int(head[2])
                    pixels = head[4][-width * height:]
                    dark_rows = [r for r in range(height) if min(pixels[r * width:(r + 1) * width]) < 128]
                    self.assertLessEqual((height - 1 - dark_rows[-1]) * 25.4 / 203, 3.0, fmt)       # como mucho ~2 mm de avance bajo el pie
                    cols = [min(pixels[r * width + col] for r in dark_rows) < 128 for col in range(width)]
                    left, right = cols.index(True), width - 1 - cols[::-1].index(True)
                    margin = (page_mm - content_mm) / 2
                    self.assertGreaterEqual(left * 25.4 / 203, margin - .3, fmt)                   # tinta dentro del ancho seguro
                    self.assertLessEqual(right * 25.4 / 203, page_mm - margin + .3, fmt)
                    self.assertAlmostEqual((left + right) / 2 * 25.4 / 203, page_mm / 2, delta=1.0)  # centrado
            self.assertEqual(spec['sizes']['body'], 8 if fmt == '80' else 7)

    def test_long_descriptions_multiple_items_and_long_names(self):
        cookie, csrf, post, order = self.paid_order(100, key='largo')
        with app.connect() as c:
            data = {'invoice': {'id': 1, 'number': '001-001-000000099', 'status': 'autorizado', 'environment': '2', 'access_key': '1' * 49, 'issue_date': '2026-11-24',
                                'emitted_at': '2026-11-24T10:00:00-05:00', 'authorized_at': '2026-11-24T10:01:00-05:00', 'authorization_number': '1' * 49,
                                'buyer_name': 'COMERCIALIZADORA INTERNACIONAL DE TECNOLOGÍA Y MICROELECTRÓNICA DEL NORTE ANDINO CÍA. LTDA.', 'buyer_id': '1790000000001',
                                'buyer_address': 'Av. Ficticia 123 y Calle Inventada, edificio de prueba, piso 4, oficina 402', 'consumer_final': 0,
                                'subtotal_cents': 30000, 'discount_cents': 1000, 'tax_cents': 4350, 'total_cents': 33350, 'source_kind': 'orden'},
                    'fiscal': {'trade_name': 'PC-DOCTOR', 'legal_name': 'EMPRESA FICTICIA S.A.', 'ruc': '1790000000001', 'head_office_address': 'Dirección ficticia 1',
                               'branch_address': 'Dirección ficticia 2', 'keeps_accounts': 'NO', 'regime': 'general', 'regime_label': 'Régimen General'},
                    'items': [{'description': ('Servicio técnico de mantenimiento preventivo y correctivo con limpieza interna, cambio de pasta térmica y '
                                               'optimización del sistema operativo ') * 2, 'quantity': 1, 'unit_price_micros': 100_000_000, 'discount_cents': 1000,
                               'base_cents': 9000, 'tax_rate_bp': 1500, 'tax_cents': 1350, 'total_cents': 10350}] +
                             [{'description': 'Licencia Microsoft 365 Personal 1 año %d' % n, 'quantity': 2, 'unit_price_micros': 52_500_000, 'discount_cents': 0,
                               'base_cents': 10500, 'tax_rate_bp': 1500 if n else 0, 'tax_cents': 1500 if n else 0, 'total_cents': 12000} for n in range(2)],
                    'payments': [{'label': 'Transferencia', 'amount_cents': 20000}, {'label': 'Tarjeta de crédito', 'amount_cents': 13350}],
                    'groups': {1500: {'base': 19500, 'tax': 2850}, 0: {'base': 10500, 'tax': 0}}, 'reference': ('Orden de servicio', 'PCD-20261124-0001')}
        for fmt in ('80', '58'):
            pdf = invoice_ticket.render(data, fmt)
            self.assertEqual(pdf.count(b'/Type /Page') - pdf.count(b'/Type /Pages'), 1)          # una sola página de altura variable
            text = self.text_of(pdf)
            if text is not None:
                self.assertIn('$333,50', text)
                self.assertIn('Subtotal 0%', text)
                self.assertNotIn('SIN VALIDEZ', text)                                             # autorizada en producción

    def test_draft_cannot_be_printed_and_permissions(self):
        cookie, csrf, post, order = self.paid_order(2000, key='borrador')
        self.configure(post)
        draft = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
        got = self.request('/api/invoicing/%d/ticket.pdf?format=80' % draft['id'], cookie=cookie)
        self.assertEqual(got['status'], 409)
        self.assertEqual(self.request('/api/invoicing/%d/ticket.pdf?format=99' % draft['id'], cookie=cookie)['status'], 400)
        self.assertEqual(self.request('/api/invoicing/%d/ticket.pdf' % draft['id'])['status'], 401)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
            c.commit()
        self.assertEqual(self.request('/api/invoicing/%d/ticket.pdf' % draft['id'], cookie=cookie)['status'], 403)

    def test_print_center_formats_history_prefs_and_no_side_effects(self):
        cookie, csrf, post, inv = self.emitted(key='centro')
        center = self.request('/api/invoicing/%d/print-center' % inv['id'], cookie=cookie)['body']
        avail = {f['key']: f['available'] for f in center['formats']}
        self.assertEqual(avail, {'80': True, '58': True, 'a4': True, 'azur': False})               # sin envío por AZUR no hay su RIDE
        self.assertEqual(center['prefs'], {'format': '80', 'copies': 1})                           # 80 mm por defecto
        before = self.snapshot()
        first = post('/api/invoicing/%d/print-log' % inv['id'], format='80', copies='2', action='impresion', remember='1')
        self.assertEqual(first['status'], 200, first['body'])
        second = post('/api/invoicing/%d/print-log' % inv['id'], format='58', copies='1', action='impresion')
        post('/api/invoicing/%d/print-log' % inv['id'], format='a4', copies='1', action='descarga')
        rows = second['body']['history']['rows']
        self.assertEqual([r['action'] for r in rows], ['Solicitud de reimpresión', 'Solicitud de impresión'])
        self.assertTrue(all('no confirmada en papel' in r['result'] for r in rows))               # nunca se afirma «impreso»
        self.assertEqual(self.request('/api/invoicing/%d/print-center' % inv['id'], cookie=cookie)['body']['prefs'], {'format': '80', 'copies': 2})
        self.assertEqual(self.snapshot(), before)                                                 # sin facturas, pagos, secuenciales ni correos nuevos
        self.assertEqual(post('/api/invoicing/%d/print-log' % inv['id'], format='80', copies='9', action='impresion')['status'], 400)
        # Borrador: los formatos se muestran no disponibles con su motivo y no se registra nada.
        c2, s2, post2, order = self.paid_order(1500, key='centro-borrador')
        draft = post2('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
        fm = self.request('/api/invoicing/%d/print-center' % draft['id'], cookie=c2)['body']['formats']
        self.assertTrue(all(not f['available'] and f['reason'] for f in fm))
        self.assertEqual(post2('/api/invoicing/%d/print-log' % draft['id'], format='80', copies='1', action='impresion')['status'], 409)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
            c.commit()
        self.assertEqual(self.request('/api/invoicing/%d/print-center' % inv['id'], cookie=cookie)['status'], 403)

    def test_azur_ride_available_when_its_pdf_is_stored(self):
        import base64
        cookie, csrf, post, inv = self.emitted(key='azur-ride')
        fm = lambda: {f['key']: f['available'] for f in self.request('/api/invoicing/%d/print-center' % inv['id'], cookie=cookie)['body']['formats']}
        self.assertFalse(fm()['azur'])
        with app.connect() as c:
            cols = [r[1] for r in c.execute('PRAGMA table_info(invoice_provider_files)')]
            values = {'invoice_id': inv['id'], 'kind': 'pdf', 'content': base64.b64encode(b'%PDF-1.4 ficticio').decode(), 'sha256': '0' * 64}
            extra = {k: '2026-11-24T00:00:00-05:00' for k in cols if k not in values and k not in ('id',) and k.endswith('_at')}
            values.update(extra)
            c.execute('INSERT INTO invoice_provider_files(%s) VALUES (%s)' % (','.join(values), ','.join('?' * len(values))), tuple(values.values()))
            c.commit()
        self.assertTrue(fm()['azur'])                                                              # sin depender de provider_id

    def test_azur_ride_fetched_by_access_key_without_touching_the_invoice(self):
        """Autorizada sin id interno de AZUR: se busca por clave de acceso solo para leer el PDF; la factura no cambia. AZUR simulado."""
        import base64
        from unittest.mock import patch
        import azur_invoicing
        cookie, csrf, post, inv = self.emitted(key='azur-fetch')
        with app.connect() as c:
            c.execute("UPDATE invoices SET provider='azur',status='autorizado',provider_id=NULL WHERE id=?", (inv['id'],))
            c.commit()
            before = tuple(c.execute('SELECT * FROM invoices WHERE id=?', (inv['id'],)).fetchone())
        fmts = lambda: {f['key']: f for f in self.request('/api/invoicing/%d/print-center' % inv['id'], cookie=cookie)['body']['formats']}
        self.assertTrue(fmts()['azur']['fetchable'])
        pdf = base64.b64encode(b'%PDF-1.4 ficticio').decode()
        with patch.object(azur_invoicing.az, 'find_invoice', return_value=987) as find, \
             patch.object(azur_invoicing.az, 'document', side_effect=lambda cfg, doc, kind: pdf if kind == 'pdf' else '') as doc, \
             patch.object(azur_invoicing.az, 'config', return_value={}):
            with app.connect() as c:
                got = azur_invoicing.fetch_files(c, inv['id'], {}, app.reception_now())
                c.commit()
        find.assert_called_once_with({}, inv['access_key'])
        self.assertTrue(all(call.args[1] == 987 for call in doc.call_args_list))
        self.assertIn('pdf', got)
        with app.connect() as c:
            self.assertEqual(tuple(c.execute('SELECT * FROM invoices WHERE id=?', (inv['id'],)).fetchone()), before)
        f = fmts()['azur']
        self.assertTrue(f['available'])
        self.assertFalse(f['fetchable'])

    def test_print_log_without_migration_keeps_working(self):
        import print_center
        cookie, csrf, post, inv = self.emitted(key='sin-118')
        with app.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DROP TABLE invoice_print_log')
            try:
                self.assertIsNone(print_center.log(c, inv['id'], self.uid, {'format': '80', 'copies': '1', 'action': 'impresion'}, app.reception_now()))
                self.assertEqual(print_center.history(c, inv['id']), {'installed': False, 'rows': []})
                self.assertTrue(print_center.formats_for(c, inv['id'])[0]['available'])
            finally:
                c.rollback()


if __name__ == '__main__':
    unittest.main()
