"""Smart Cancellation & Closure Management: solicitar (con verificación de identidad y evidencia), confirmar (solo administración), bloqueo de
cambios de estado, presupuestos pendientes cancelados, liquidación sin cobros automáticos, cierre solo con el equipo devuelto y sin saldos,
reapertura, acta PDF, estadísticas, permisos y que nada se borre. Base temporal y datos ficticios; WhatsApp no configurado (no sale nada)."""
import base64
import re
import unittest
import zlib

import test_invoicing
import app


def pdf_text(pdf):
    out = []
    for m in re.finditer(rb'/Length (\d+)[^>]*>>\s*stream\r?\n', pdf):
        try:
            data = zlib.decompress(pdf[m.end():m.end() + int(m[1])])
        except zlib.error:
            continue
        out += [re.sub(rb'\\(.)', rb'\1', t).decode('cp1252') for t in re.findall(rb'\(((?:\\.|[^\\)])*)\)\s*Tj', data)]
    return ' '.join(out)


class OrderCancellationTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure

    def counts(self, oid):
        with app.connect() as c:
            return tuple(c.execute('SELECT (SELECT COUNT(*) FROM order_payments WHERE order_id=?),(SELECT COUNT(*) FROM quotes WHERE order_id=?),'
                                   '(SELECT COUNT(*) FROM order_photos WHERE order_id=?),(SELECT COUNT(*) FROM invoices WHERE order_id=?)', (oid, oid, oid, oid)).fetchone())

    def status(self, oid):
        with app.connect() as c:
            return c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()[0]

    def test_full_flow_request_confirm_settle_close(self):
        cookie, csrf, post, order = self.paid_order(3000, key='cancel-1')
        oid = order['id']
        path = '/api/orders/%d/cancellation' % oid
        before = self.counts(oid)
        self.assertEqual(post(path, action='request', reason='costo', detail='corto', id_last4='0017')['status'], 400)            # observaciones obligatorias
        self.assertEqual(post(path, action='request', reason='costo', detail='El cliente no desea continuar con la reparación.', id_last4='9999')['status'], 400)  # identidad
        evidence = base64.b64encode(b'%PDF-1.4 evidencia ficticia').decode()
        req = post(path, action='request', reason='costo', detail='El cliente no desea continuar con la reparación.', id_last4='0017',
                   file_name='solicitud.pdf', file_mime='application/pdf', file_data=evidence)
        self.assertEqual(req['status'], 200, req['body'])
        self.assertEqual(req['body']['cancellation']['state'], 'solicitada')
        self.assertEqual(len(req['body']['cancellation']['files']), 1)
        self.assertEqual(self.status(oid), order.get('status') or self.status(oid))                                              # solicitar no cambia el estado
        self.assertEqual(post(path, action='request', reason='costo', detail='Segunda solicitud de prueba.', id_last4='0017')['status'], 409)
        self.assertEqual(post(path, action='confirm', confirm='no')['status'], 400)
        done = post(path, action='confirm', confirm='CANCELAR')
        self.assertEqual(done['status'], 200, done['body'])
        self.assertEqual(self.status(oid), 'espera_entrega')
        self.assertEqual(done['body']['cancellation']['state'], 'pendiente_retiro')                                               # pagado: solo falta devolver
        # Mientras está cancelada, nadie cambia el estado por otras vías.
        moved = post('/api/order-status', id=str(oid), status='reparacion', comment='intento')
        self.assertEqual(moved['status'], 409)
        import repair_status
        with app.connect() as c:
            self.assertIsNone(repair_status.auto(c, oid, 'part_received', app.reception_now(), self.uid))
        self.assertEqual(post(path, action='close')['status'], 400)                                                              # quién retiró
        with app.connect() as c:
            maint = c.execute('SELECT COUNT(*) FROM maintenance_schedules').fetchone()[0] if c.execute("SELECT 1 FROM sqlite_master WHERE name='maintenance_schedules'").fetchone() else 0
        closed = post(path, action='close', receiver='Cliente ficticio, C.I. 0100000017')
        self.assertEqual(closed['status'], 200, closed['body'])
        self.assertEqual((self.status(oid), closed['body']['cancellation']['state']), ('entregado', 'cerrada'))
        with app.connect() as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='maintenance_schedules'").fetchone():
                self.assertEqual(c.execute('SELECT COUNT(*) FROM maintenance_schedules').fetchone()[0], maint)                 # sin mantenimiento por una cancelación
        self.assertEqual(self.counts(oid)[0], before[0])                                                                          # pagos intactos
        self.assertEqual(self.counts(oid)[2:], before[2:])                                                                        # fotos y facturas intactas
        acta = self.request(path + '/acta.pdf', cookie=cookie)
        self.assertEqual(acta['status'], 200)
        text = pdf_text(acta['body'])
        for expected in ('ACTA DE CANCELACIÓN Y DEVOLUCIÓN', 'El costo de la reparación no le conviene', 'Constancia de aceptación'.upper(), 'No es una factura'):
            self.assertIn(expected, text)
        fid = closed['body']['cancellation']['files'][0]['id']
        self.assertEqual(self.request(path + '/files/%d' % fid, cookie=cookie)['body'], b'%PDF-1.4 evidencia ficticia')
        self.assertEqual(post(path, action='reopen', reason='El cliente cambió de opinión.')['status'], 409)                    # cerrada: no se reabre
        stats = self.request('/api/cancellations/stats', cookie=cookie)['body']
        self.assertEqual((stats['total'], stats['states']['cerrada'], stats['reasons'][0]['code'], stats['recovered_cents']), (1, 1, 'costo', 3000))

    def test_balance_blocks_close_pending_quotes_cancelled_and_reopen_restores(self):
        cookie, csrf, post, order = self.paid_order(2500, pay=False, key='cancel-2')
        oid = order['id']
        path = '/api/orders/%d/cancellation' % oid
        with app.connect() as c:
            previous = c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()[0]
        q = post('/api/orders/%d/quote' % oid)['body']['id']                                                                     # presupuesto nuevo sin aprobar
        post('/api/quotes/%d' % q, action='save', items='[{"description":"Trabajo ficticio adicional","category":"servicio","quantity":1,"unit_cents":4000,"taxed":true}]')
        post('/api/quotes/%d' % q, action='send')
        post(path, action='request', reason='tiempo', detail='El cliente necesita el equipo de inmediato.', id_last4='0017')
        done = post(path, action='confirm', confirm='CANCELAR')['body']
        self.assertEqual(done['cancellation']['state'], 'pendiente_liquidacion')                                                 # saldo de lo AUTORIZADO
        self.assertEqual(done['cancellation']['money']['balance_cents'], 2500)                                                   # el trabajo no aprobado no se cobra
        with app.connect() as c:
            statuses = [r[0] for r in c.execute('SELECT status FROM quotes WHERE order_id=? ORDER BY id', (oid,))]
        self.assertIn('cancelado', statuses)
        blocked = post(path, action='close', receiver='Cliente ficticio')
        self.assertEqual(blocked['status'], 409);self.assertIn('saldo pendiente', blocked['body']['error'])
        self.assertEqual(post(path, action='reopen', reason='corto')['status'], 400)
        back = post(path, action='reopen', reason='El cliente decidió continuar con la reparación.')
        self.assertEqual(back['status'], 200, back['body'])
        self.assertEqual(self.status(oid), 'diagnostico')                                                                       # el presupuesto se canceló: vuelve a diagnóstico
        self.assertIsNone(back['body']['cancellation'])
        self.assertEqual(back['body']['history'][0]['state'], 'anulada')

    def test_permissions_technician_requests_admin_confirms(self):
        cookie, csrf, post, order = self.paid_order(1500, key='cancel-3')
        oid = order['id']
        path = '/api/orders/%d/cancellation' % oid
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(post(path, action='request', reason='otro', detail='Solicitud registrada por el técnico.', id_last4='0017')['status'], 200)
        self.assertEqual(post(path, action='confirm', confirm='CANCELAR')['status'], 403)
        self.assertEqual(post(path, action='reopen', reason='Intento del técnico de reabrir.')['status'], 403)
        self.assertEqual(self.request('/api/cancellations/stats', cookie=cookie)['status'], 403)
        self.assertEqual(self.request(path)['status'], 401)


if __name__ == '__main__':
    unittest.main()
