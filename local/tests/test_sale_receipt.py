"""Comprobante de venta no tributario (80 mm y A4), datos ficticios y base temporal: importes con IVA incluido iguales a la factura, pagos
mixtos y pendientes, licencias sin claves, venta del inventario con serie, factura autorizada mencionada sin sustituir al RIDE, reimpresión
que no crea nada y permisos. Con SALE_RECEIPT_OUT=<carpeta> guarda los PDF para revisarlos."""
import json
import os
import re
import unittest

import test_cash_rules
import test_inventory_erp
import test_license_sales
import app
import sale_receipt

OUT = os.environ.get('SALE_RECEIPT_OUT', '')


def counts(c):
    return tuple(c.execute(sql).fetchone()[0] for sql in ('SELECT COUNT(*) FROM proformas', 'SELECT COUNT(*) FROM advances', 'SELECT COUNT(*) FROM inventory_movements',
                                                          'SELECT COUNT(*) FROM license_sale_payments', 'SELECT COUNT(*) FROM invoices', 'SELECT COUNT(*) FROM payment_events'))


def helpers(base):
    """Auxiliares de otra clase de pruebas sin heredar sus pruebas (si no, se ejecutarían dos veces)."""
    return {k: v for k, v in vars(base).items() if not k.startswith('test_') and not k.startswith('__')}


class ReceiptChecks:
    def pdfs(self, cookie, kind, sid, name):
        """Ticket (cliente, establecimiento y ambas) y A4: una página por copia en el ticket, 72 mm útiles; nada se crea al imprimir."""
        with app.connect() as c:
            before = counts(c)
        out = {}
        for fmt, copy in (('termico', 'cliente'), ('termico', 'establecimiento'), ('termico', 'ambas'), ('a4', 'cliente')):
            r = self.request('/api/sales/receipt/%s/%d.pdf?formato=%s&copia=%s' % (kind, sid, fmt, copy), cookie=cookie)
            self.assertEqual(r['status'], 200, r['body'])
            self.assertTrue(r['body'].startswith(b'%PDF'))
            out[(fmt, copy)] = r['body']
            if OUT:
                with open(os.path.join(OUT, '%s-%s-%s.pdf' % (name, fmt, copy)), 'wb') as handle:
                    handle.write(r['body'])
        ticket = out[('termico', 'cliente')]
        width = float(re.search(rb'/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]', ticket).group(1))
        self.assertAlmostEqual(width * 25.4 / 72, 72, places=1)
        self.assertEqual(len(re.findall(rb'/Type /Page\b', ticket)), 1)
        self.assertEqual(len(re.findall(rb'/Type /Page\b', out[('termico', 'ambas')])), 2)
        with app.connect() as c:
            self.assertEqual(counts(c), before)  # reimprimir no crea ventas, cobros, movimientos, facturas ni eventos
        self.assertEqual(self.request('/api/sales/receipt/%s/%d.pdf?formato=otro' % (kind, sid), cookie=cookie)['status'], 400)
        return out


class DirectSaleReceiptTests(ReceiptChecks, unittest.TestCase):
    locals().update(helpers(test_cash_rules.CashRulesTests))

    def test_direct_sale_mixed_payments_discount_vat_and_authorized_invoice(self):
        cookie, csrf, post, order = self.paid_order(1000, pay=False)
        acc = self.account(post, bank='Banco Pichincha', number='2211992424')
        items = json.dumps([{'kind': 'producto', 'description': 'Mouse inalámbrico ficticio', 'quantity': '2', 'unit_price': '15,00', 'discount': '2,00'},
                            {'kind': 'servicio', 'description': 'Mantenimiento preventivo ficticio', 'quantity': '1', 'unit_price': '40,00'},
                            {'kind': 'servicio', 'description': 'Servicio exento ficticio', 'quantity': '1', 'unit_price': '10,00', 'taxed': '0'}])
        draft = post('/api/proformas', origin='directa', items=items, client_name='Cliente Ficticio de Prueba', client_identification='0100000017', request_key='recibo-venta-0001')
        self.assertEqual(draft['status'], 200, draft['body'])
        pid = draft['body']['id']
        pays = [{'method': 'efectivo', 'amount': '30,00'}, {'method': 'transferencia', 'amount': '28,00', 'bank_account_id': str(acc), 'reference': 'TRX-RECIBO-01'},
                {'method': 'debito', 'amount': '20,00'}]
        sold = post('/api/proformas/%d' % pid, action='checkout', payments=json.dumps(pays), request_key='recibo-venta-cobro-01')
        self.assertEqual(sold['status'], 200, sold['body'])
        with app.connect() as c:
            d = sale_receipt.collect(c, 'directa', pid)
        t = d['totals']
        self.assertEqual((t['total_cents'], t['discount_cents'], d['paid_cents'], d['balance_cents'], d['state']), (7800, 200, 7800, 0, 'pagada'))
        self.assertEqual(t['base_taxed_cents'] + t['tax_cents'] + t['base_zero_cents'], 7800)
        self.assertEqual((t['base_zero_cents'], t['tax_cents']), (1000, 887))  # 68,00 con IVA del 15 % = 59,13 + 8,87
        self.assertEqual([p['method'] for p in d['payments']], ['Efectivo', 'Transferencia', 'Tarjeta de débito'])
        self.assertEqual(d['payments'][1]['account'], 'Banco Pichincha · ahorros •••• 2424')  # cuenta enmascarada
        # La factura (borrador) tiene los mismos importes que el comprobante.
        with app.connect() as c:
            inv = c.execute('SELECT * FROM invoices WHERE id=(SELECT invoice_id FROM proformas WHERE id=?)', (pid,)).fetchone()
        self.assertEqual((inv['total_cents'], inv['tax_cents']), (7800, 887))
        self.assertIsNone(d['invoice'] if inv['status'] == 'descartado' else None)
        summary = self.request('/api/sales/receipt/directa/%d' % pid, cookie=cookie)['body']
        self.assertEqual((summary['code'], summary['total_cents'], summary['invoice']['authorized']), (d['code'], 7800, False))
        self.pdfs(cookie, 'directa', pid, 'directa-mixta')
        # Factura autorizada (simulada en la base temporal, ambiente de pruebas): el comprobante la menciona y la ventana ofrece el RIDE.
        with app.connect() as c:
            c.execute("UPDATE invoices SET status='autorizado',sequential=123,access_key='0311202601179001167400110010020000001231234567813',"
                      "authorization_number='0311202601179001167400110010020000001231234567813',authorized_at='2026-11-03T10:00:00-05:00' WHERE id=?", (inv['id'],))
            c.commit()
        summary = self.request('/api/sales/receipt/directa/%d' % pid, cookie=cookie)['body']
        self.assertEqual((summary['invoice']['authorized'], summary['invoice']['test']), (True, True))
        self.assertTrue(summary['invoice']['number'].endswith('000000123'))
        self.pdfs(cookie, 'directa', pid, 'directa-autorizada')
        # Venta pendiente de pago: abona 20 de 50.
        items = json.dumps([{'kind': 'servicio', 'description': 'Instalación de software ficticia', 'quantity': '1', 'unit_price': '50,00'}])
        pending = post('/api/proformas', origin='directa', items=items, client_name='Consumidor Ficticio', client_identification='', request_key='recibo-venta-0002')['body']['id']
        self.assertEqual(post('/api/proformas/%d' % pending, action='checkout', payments=json.dumps([{'method': 'efectivo', 'amount': '20,00'}]), request_key='recibo-venta-cobro-02')['status'], 200)
        with app.connect() as c:
            d = sale_receipt.collect(c, 'directa', pending)
        self.assertEqual((d['paid_cents'], d['balance_cents'], d['state_label']), (2000, 3000, 'Saldo pendiente'))
        self.pdfs(cookie, 'directa', pending, 'directa-pendiente')
        # Un técnico no accede a las ventas; una venta inexistente responde 404.
        tcookie, tcsrf = self.tech()
        self.assertEqual(self.request('/api/sales/receipt/directa/%d.pdf' % pid, cookie=tcookie)['status'], 403)
        self.assertEqual(self.request('/api/sales/receipt/directa/999999', cookie=cookie)['status'], 404)


class LicenseSaleReceiptTests(ReceiptChecks, unittest.TestCase):
    locals().update(helpers(test_license_sales.LicenseSalesTests))

    def test_license_sale_without_keys_and_partial_payment(self):
        av, ms, client = self.catalog()
        made = self.sale(client, [{'product_id': av, 'quantity': 2, 'discount': '5'}, {'product_id': ms, 'quantity': 1}], payment={'amount': '30', 'method': 'efectivo', 'confirmed': True})
        self.assertEqual(made['status'], 201, made['body'])
        sid = made['body']['sale']
        with app.connect() as c:
            d = sale_receipt.collect(c, 'licencia', sid)
        self.assertEqual((d['totals']['total_cents'], d['paid_cents'], d['balance_cents'], d['state']), (2 * 3000 + 9990 - 500, 3000, 2 * 3000 + 9990 - 500 - 3000, 'por_cobrar'))
        t = d['totals']  # el descuento de la partida no se cuenta otra vez como descuento general; el IVA se desglosa
        self.assertEqual((t['general_discount_cents'], t['discount_cents'], t['base_taxed_cents'] + t['tax_cents'] + t['base_zero_cents']), (0, 500, 15490))
        out = self.pdfs(self.cookie, 'licencia', sid, 'licencias')
        for pdf in out.values():
            self.assertNotIn(b'BITD-FICT', pdf)
            self.assertNotIn(b'M365-FICT', pdf)
        self.assertNotIn('FICT-X', json.dumps(d))


class InventorySaleReceiptTests(ReceiptChecks, unittest.TestCase):
    locals().update(helpers(test_inventory_erp.InventoryErpTests))

    def test_inventory_sale_with_serial_and_unregistered_payment(self):
        self.admin()
        ssd, unit = self.ssd()
        self.assertEqual(self.post('/api/inventory/products', action='pricing', id=str(ssd), price='34,50', min_price='30,00', max_discount='5')['status'], 200)
        client = self.client()
        sale = self.post('/api/inventory/exit', item_id=str(ssd), reason='venta', unit_ids=json.dumps([unit]), client_id=str(client), discount='2', document='Venta ficticia')
        self.assertEqual(sale['status'], 200, sale['body'])
        with app.connect() as c:
            mid = c.execute("SELECT id FROM inventory_movements WHERE reason='venta' ORDER BY id DESC LIMIT 1").fetchone()[0]
            d = sale_receipt.collect(c, 'inventario', mid)
        self.assertEqual((d['code'], d['state'], d['totals']['total_cents'], d['lines'][0]['discount_cents']), ('INV-%d' % mid, 'sin_cobro', 3381, 69))  # 2 % de descuento sobre $34,50
        self.assertIn('Serie: S-1', d['lines'][0]['description'])
        self.pdfs(self.cookie, 'inventario', mid, 'inventario')


if __name__ == '__main__':
    unittest.main()
