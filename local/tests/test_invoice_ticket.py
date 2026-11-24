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
    def test_access_key_readable_in_barcode_and_qr_at_203_dpi(self):
        cookie, csrf, post, inv = self.emitted(key='lector')
        with app.connect() as c:
            data = invoice_ticket.data_for(c, inv['id'])
        for fmt in ('80', '58'):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 't.pdf'
                path.write_bytes(invoice_ticket.render(data, fmt))
                subprocess.run(['pdftoppm', '-r', '203', '-gray', '-png', str(path), str(Path(folder) / 'p')], check=True)
                found = subprocess.run(['zbarimg', '--raw', '-q'] + [str(p) for p in sorted(Path(folder).glob('p*.png'))], capture_output=True, text=True).stdout.split()
            self.assertEqual(found.count(inv['access_key']), 2, (fmt, found))                     # Code 128 y QR, ambos con la clave completa

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
