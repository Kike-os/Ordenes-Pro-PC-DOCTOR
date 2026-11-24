"""Premium Billing Center · comprobantes no tributarios: recibo de pago (A5 con QR seguro y factura vinculada, y térmico 80 mm),
comprobante de anticipo (A5 y térmico) y comprobante de entrega (A4 y térmico). Base temporal y datos ficticios: imprimir no cambia
nada, cada documento dice que no es una factura y el QR solo aparece con un seguimiento activo."""
import json
import re
import unittest
import zlib

import test_invoicing
import app


def text(pdf):
    out = []
    for m in re.finditer(rb'/Length (\d+)[^>]*>>\s*stream\r?\n', pdf):
        raw = pdf[m.end():m.end() + int(m[1])]
        try:
            data = zlib.decompress(raw)
        except zlib.error:
            continue
        out += [re.sub(rb'\\(.)', rb'\1', t).decode('cp1252') for t in re.findall(rb'\(((?:\\.|[^\\)])*)\)\s*Tj', data)]
    return ' '.join(out)


def has_qr(pdf):
    return b'/s/' in pdf and 'Consulta segura' in text(pdf)   # QR = enlace de seguimiento con token (/s/...) y su leyenda


class VoucherTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure

    def snapshot(self):
        with app.connect() as c:
            return tuple(c.execute('SELECT (SELECT COUNT(*) FROM order_payments),(SELECT COALESCE(SUM(amount_cents),0) FROM order_payments),(SELECT COUNT(*) FROM advances),'
                                   '(SELECT COUNT(*) FROM invoices),(SELECT group_concat(status) FROM orders),(SELECT COUNT(*) FROM order_status_log)').fetchone())

    def test_payment_receipt_a5_and_thermal_with_secure_qr_only_when_tracking_is_active(self):
        cookie, csrf, post, order = self.paid_order(2500, key='vale-pago')
        with app.connect() as c:
            pid = c.execute('SELECT id FROM order_payments WHERE order_id=?', (order['id'],)).fetchone()[0]
        import order_tracking
        with app.connect() as c:                                                       # la recepción crea un seguimiento: se revoca para probar el caso sin él
            order_tracking.revoke(c, order['id'], self.uid, app.reception_now());c.commit()
        before = self.snapshot()
        path = '/api/orders/%d/payments/%d/receipt.pdf' % (order['id'], pid)
        a5 = self.request(path, cookie=cookie)
        self.assertEqual(a5['status'], 200)
        words = text(a5['body'])
        for expected in ('RECIBO DE PAGO', '$25,00', 'No es una factura', 'Registrado por', 'Saldo'):
            self.assertIn(expected, words)
        self.assertFalse(has_qr(a5['body']))                                          # sin seguimiento activo: no hay QR
        with app.connect() as c:
            link = order_tracking.create(c, order['id'], self.uid, app.reception_now());c.commit()
        with_qr = self.request(path, cookie=cookie)['body']
        self.assertTrue(has_qr(with_qr))
        self.assertIn(link.encode(), with_qr)                                          # el QR lleva el enlace seguro (con token)
        ticket = self.request(path + '?formato=termico', cookie=cookie)
        self.assertEqual(ticket['status'], 200)
        tw = text(ticket['body'])
        self.assertIn('RECIBO DE PAGO', tw);self.assertIn('Consulta segura', tw);self.assertIn('No es una factura', tw)
        self.assertIn(b'/MediaBox [0 0 226.77', ticket['body'])                       # rollo de 80 mm
        self.assertEqual(self.snapshot(), before)                                     # imprimir no cambia nada
        self.assertEqual(self.request(path)['status'], 401)

    def test_delivery_voucher_only_for_delivered_orders_and_honest_warranty(self):
        cookie, csrf, post, order = self.paid_order(4000, key='vale-entrega')
        path = '/api/orders/%d/delivery.pdf' % order['id']
        self.assertEqual(self.request(path, cookie=cookie)['status'], 409)            # aún no entregada
        with app.connect() as c:
            now = app.reception_now().isoformat(timespec='seconds')
            c.execute("UPDATE orders SET status='entregado',delivered_at=? WHERE id=?", (now, order['id']))
            c.execute("INSERT INTO order_status_log(order_id,from_status,to_status,actor_id,reason,source,created_at) VALUES (?,?,?,?,?,?,?)",
                      (order['id'], 'listo', 'entregado', self.uid, 'Retira el titular con su cédula', 'manual', now))
            c.commit()
        before = self.snapshot()
        a4 = self.request(path, cookie=cookie)
        self.assertEqual(a4['status'], 200)
        words = text(a4['body'])
        for expected in ('COMPROBANTE DE ENTREGA', 'Servicio ficticio', 'Saldo pendiente', 'Sin repuestos con garantía registrada', 'Retira el titular', 'Persona de prueba',
                         'CONSTANCIA DE RECEPCIÓN', 'Seguimiento seguro', 'No es una factura'):
            self.assertIn(expected, words)
        ticket = self.request(path + '?formato=termico', cookie=cookie)
        self.assertEqual(ticket['status'], 200)
        self.assertIn('Firma:', text(ticket['body']))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.request('/api/orders/999999/delivery.pdf', cookie=cookie)['status'], 404)

    def test_advance_voucher_a5_and_thermal_with_balance_and_void_notice(self):
        cookie, csrf, post, order = self.paid_order(1000, key='vale-anticipo')
        items = [{'kind': 'servicio', 'description': 'Instalación ficticia de software', 'quantity': '1', 'unit_price': '100,00'}]
        created = post('/api/proformas', items=json.dumps(items), client_name='Cliente Ficticio', client_identification='0100000017', request_key='proforma-vale-0001')
        self.assertEqual(created['status'], 200, created['body'])
        pid = created['body']['id']
        with app.connect() as c:
            now = app.reception_now().isoformat(timespec='seconds')
            aid = c.execute("INSERT INTO advances(code,proforma_id,method,reference,amount_cents,paid_at,created_by,created_at) VALUES ('ANT-000901',?,'transferencia','TR-FICTICIA-9',3000,?,?,?)",
                            (pid, now, self.uid, now)).lastrowid
            c.commit()
        before = self.snapshot()
        path = '/api/proformas/%d/advances/%d/receipt.pdf' % (pid, aid)
        a5 = self.request(path, cookie=cookie)
        self.assertEqual(a5['status'], 200, a5['body'])
        words = text(a5['body'])
        for expected in ('COMPROBANTE DE ANTICIPO', 'ANT-000901', 'Instalación ficticia de software', '$30,00', 'Transferencia', 'TR-FICTICIA-9', 'Saldo pendiente', '$70,00', 'No es una factura'):
            self.assertIn(expected, words)
        ticket = self.request(path + '?formato=termico', cookie=cookie)
        self.assertEqual(ticket['status'], 200)
        self.assertIn('$100,00', text(ticket['body']))
        with app.connect() as c:
            c.execute("UPDATE advances SET voided_at=?,void_reason='Error de registro ficticio',voided_by=? WHERE id=?", (now, self.uid, aid));c.commit()
        voided = text(self.request(path, cookie=cookie)['body'])
        self.assertIn('ANTICIPO ANULADO', voided);self.assertIn('$100,00', voided)     # anulado: el saldo vuelve al total
        self.assertEqual(self.request('/api/proformas/%d/advances/%d/receipt.pdf' % (pid + 50, aid), cookie=cookie)['status'], 404)   # otra proforma
        self.assertEqual(self.snapshot()[:4], before[:4])


if __name__ == '__main__':
    unittest.main()
