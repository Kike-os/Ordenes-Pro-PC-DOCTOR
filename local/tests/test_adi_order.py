"""ADI Premium 4.0 (1.5.265, datos ficticios, base temporal): recomendaciones según el estado REAL de la orden, presupuesto pendiente,
saldos con pagos parciales y órdenes pagadas, recordatorio de pago sin inventar vencimientos ni duplicar, revisión contextual de mensajes,
repuestos sin afirmar llegadas ni aduana no registradas, informe de situación, descartar sin cambiar datos, auditoría y permisos.
Nombres descriptivos de evidencias (seguimientos y repuestos) con el nombre original como metadato."""
import base64
import json
import unittest
from datetime import datetime

import adi_order
import app
import test_order_followups as base

JPEG = b'\xff\xd8\xff\xe0' + bytes(range(256)) * 2 + b'\xff\xd9'


class AdiOrderTests(unittest.TestCase):
    Base = base.OrderFollowupTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order = Base.form, Base.prepare, Base.paid_order

    def adi(self, cookie, oid):
        return self.request('/api/orders/%d/adi' % oid, cookie=cookie)

    def keys(self, panel):
        return [r['key'] for r in panel['recommendations']]

    def sent_quote(self, cents=15000, key='0001'):
        """Orden con un presupuesto ENVIADO y todavía sin decisión del cliente."""
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        order = post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'request_key': 'adi-order-request-' + key}))['body']
        quote = post('/api/orders/%d/quote' % order['id'])['body']['id']
        post('/api/quotes/%d' % quote, action='save', items=[{'description': 'Cambio de pantalla (ficticio)', 'category': 'servicio', 'quantity': 1, 'unit_cents': cents, 'taxed': True}])
        self.assertEqual(post('/api/quotes/%d' % quote, action='send')['status'], 200)
        return cookie, csrf, post, order

    def test_pending_quote_is_not_a_finished_repair(self):
        cookie, csrf, post, order = self.sent_quote()
        panel = self.adi(cookie, order['id'])
        self.assertEqual(panel['status'], 200, panel['body'])
        recs = {r['key']: r for r in panel['body']['recommendations']}
        self.assertIn('presupuesto_aprobacion', recs)
        rec = recs['presupuesto_aprobacion']
        self.assertEqual((rec['priority'], rec['target'], rec['dismissible']), ('alta', 'quote', False))
        self.assertIn('$150,00', rec['reason']);self.assertIn('no corresponde informar que la reparación está terminada', rec['action'])
        self.assertEqual(panel['body']['recommendations'][0]['priority'], 'alta')  # agrupadas por prioridad
        check = lambda text, channel='whatsapp': post('/api/orders/%d/adi' % order['id'], action='check', text=text, channel=channel)['body']
        got = check('Estimado cliente, su equipo está listo para retirar. El valor es $999,00.')
        self.assertTrue(any('listo' in w for w in got['warnings']), got)
        self.assertTrue(any('$999,00' in w for w in got['warnings']), got)
        self.assertTrue(any('presupuesto pendiente' in s for s in got['suggestions']), got)
        ok = check('Le enviamos el presupuesto del cambio de pantalla por $150,00 para su aprobación.')
        self.assertEqual((ok['warnings'], ok['suggestions']), ([], []))
        other = check('Su orden PCD-20200101-0099 está en revisión. Presupuesto enviado.')
        self.assertTrue(any('PCD-20200101-0099' in w for w in other['warnings']))
        long = check('presupuesto ' + 'palabra ' * 200)
        self.assertTrue(any('WhatsApp' in s for s in long['suggestions']))
        self.assertFalse(any('WhatsApp' in s for s in check('presupuesto ' + 'palabra ' * 200, 'correo')['suggestions']))
        with app.connect() as c:  # revisar un texto no modifica la orden ni deja nada en la auditoría
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action LIKE 'adi_%'").fetchone()[0], 0)

    def test_balances_partial_paid_and_reminder_without_inventing(self):
        cookie, csrf, post, order = self.paid_order(15000, pay=False)
        oid = order['id']
        self.assertEqual(post('/api/orders/%d/payments' % oid, amount='50,00', method='efectivo')['status'], 201)
        panel = self.adi(cookie, oid)['body']
        pay = panel['payments']
        self.assertEqual((pay['total'], pay['paid'], pay['balance'], pay['state']), ('$150,00', '$50,00', '$100,00', 'parcial'))
        self.assertEqual(pay['due_date'], '')  # no hay vencimiento registrado
        saldo = next(r for r in panel['recommendations'] if r['key'] == 'saldo')
        self.assertIn('saldo $100,00', saldo['reason'])
        msg = post('/api/orders/%d/adi' % oid, action='payment_message')
        self.assertEqual(msg['status'], 200, msg['body'])
        body = msg['body']['body']
        for line in ('Total de la orden: $150,00.', 'Abonado: $50,00.', 'Saldo pendiente: $100,00.'):
            self.assertIn(line, body)
        self.assertNotIn('vencid', body.lower());self.assertEqual(msg['body']['template'], 'pago')
        self.assertFalse(any('Ya se envió' in w for w in msg['body']['warnings']))
        with app.connect() as c:  # un recordatorio preparado y enviado hace poco se informa para no duplicarlo
            c.execute("INSERT INTO order_messages(order_id,channel,template,recipient,body,status,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (oid, 'whatsapp_manual', 'pago', '0991234567', 'Recordatorio (ficticio)', 'preparado', self.uid, datetime.now().isoformat(timespec='seconds'), datetime.now().isoformat(timespec='seconds')))
            c.commit()
        again = post('/api/orders/%d/adi' % oid, action='payment_message')['body']
        self.assertTrue(any('Ya se envió o preparó un recordatorio' in w for w in again['warnings']), again['warnings'])
        check = post('/api/orders/%d/adi' % oid, action='check', text='Su saldo está vencido. La orden no registra saldo.')['body']
        self.assertTrue(any('vencimiento' in w for w in check['warnings']));self.assertTrue(any('saldo pendiente de $100,00' in w for w in check['warnings']))
        self.assertEqual(post('/api/orders/%d/adi' % oid, action='check', text='Saldo pendiente: $100,00. Abonado $50,00 de $150,00.')['body']['warnings'], [])
        with app.connect() as c:  # ADI no registró pagos ni cambió saldos
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_payments WHERE order_id=?', (oid,)).fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='adi_payment_message_prepared' AND entity_id=?", (oid,)).fetchone()[0], 2)
        # Pagada por completo: sin recomendación de saldo y sin recordatorio
        self.assertEqual(post('/api/orders/%d/payments' % oid, amount='100,00', method='efectivo')['status'], 201)
        paid = self.adi(cookie, oid)['body']
        self.assertNotIn('saldo', self.keys(paid));self.assertEqual(paid['payments']['state'], 'pagado')
        self.assertEqual(post('/api/orders/%d/adi' % oid, action='payment_message')['status'], 409)

    def test_parts_never_claim_unregistered_arrival_or_customs(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        made = post('/api/orders/%d/part-requests' % oid, name='Pantalla 15,6" FHD (ficticia)', quantity='1', request_key='adi-part-000000000001', shipping='internacional')
        self.assertEqual(made['status'], 200, made['body'])
        panel = self.adi(cookie, oid)['body']
        rid = made['body']['id']
        self.assertIn('repuesto_%d' % rid, self.keys(panel))
        rec = next(r for r in panel['recommendations'] if r['key'] == 'repuesto_%d' % rid)
        self.assertIn('Pantalla 15,6', rec['reason']);self.assertEqual(rec['target'], 'parts')
        got = post('/api/orders/%d/adi' % oid, action='check', text='Su repuesto ya llegó y fue liberado por la aduana. Ya llegó a Ecuador.')['body']
        joined = ' '.join(got['warnings'])
        self.assertIn('ningún repuesto de la orden figura como recibido', joined);self.assertIn('aduana', joined)
        self.assertIn('Ecuador', joined)

    def test_diagnosis_pending_dismiss_restore_report_and_audit(self):
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        order = post('/api/orders', **self.order_data({'request_key': 'adi-order-request-0009'}))['body']
        oid = order['id']
        panel = self.adi(cookie, oid)['body']
        keys = self.keys(panel)
        self.assertIn('diagnostico', keys);self.assertIn('fotos_recepcion', keys)
        info = next(r for r in panel['recommendations'] if r['key'] == 'fotos_recepcion')
        diag = next(r for r in panel['recommendations'] if r['key'] == 'diagnostico')
        self.assertEqual(post('/api/orders/%d/adi' % oid, action='dismiss', key=diag['key'], fingerprint=diag['fingerprint'])['status'], 400)  # una acción pendiente no se descarta
        self.assertEqual(post('/api/orders/%d/adi' % oid, action='dismiss', key=info['key'], fingerprint='0000000000000000')['status'], 409)
        done = post('/api/orders/%d/adi' % oid, action='dismiss', key=info['key'], fingerprint=info['fingerprint'])
        self.assertEqual(done['status'], 200);self.assertNotIn('fotos_recepcion', self.keys(done['body']));self.assertEqual(done['body']['dismissed'], 1)
        self.assertNotIn('fotos_recepcion', self.keys(self.adi(cookie, oid)['body']))  # no se repite
        # Si cambian los datos (otra huella), vuelve a aparecer: se agrega y se retira una foto de diagnóstico, no de recepción → misma huella
        with app.connect() as c:
            before = c.execute('SELECT status,findings,updated_at FROM orders WHERE id=?', (oid,)).fetchone()
        restored = post('/api/orders/%d/adi' % oid, action='restore')['body']
        self.assertIn('fotos_recepcion', self.keys(restored))
        rep = post('/api/orders/%d/adi' % oid, action='report')['body']['report']
        self.assertIn('Diagnóstico técnico: pendiente (no registrado)', rep);self.assertIn('Pendientes:', rep);self.assertIn('Diagnóstico técnico pendiente', rep)
        self.assertNotIn('Cliente ficticio', rep)
        with app.connect() as c:
            self.assertEqual(tuple(c.execute('SELECT status,findings,updated_at FROM orders WHERE id=?', (oid,)).fetchone()), tuple(before))  # nada cambió
            actions = [r[0] for r in c.execute("SELECT action FROM audit WHERE entity_id=? AND action LIKE 'adi_%' ORDER BY id", (oid,))]
        self.assertEqual(actions, ['adi_recommendation_dismissed', 'adi_recommendations_restored', 'adi_report_prepared'])

    def test_permissions_and_unknown_orders(self):
        cookie, csrf = self.login()
        order = self.request('/api/orders', self.order_data({'request_key': 'adi-order-request-0010'}), cookie=cookie, csrf=csrf)['body']
        self.assertEqual(self.request('/api/orders/%d/adi' % order['id'])['status'], 401)
        self.assertEqual(self.request('/api/orders/%d/adi' % order['id'], {'action': 'report'}, cookie=cookie)['status'], 403)  # sin CSRF
        self.assertEqual(self.adi(cookie, 99999)['status'], 404)
        self.assertEqual(self.request('/api/orders/99999/adi', {'action': 'report'}, cookie=cookie, csrf=csrf)['status'], 404)
        self.assertEqual(self.request('/api/orders/%d/adi' % order['id'], {'action': 'borrar'}, cookie=cookie, csrf=csrf)['status'], 400)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.adi(cookie, order['id'])['status'], 200)  # el técnico de la orden también la usa

    def test_evidence_names_for_followups_and_parts(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        code = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']['code']
        data = 'data:image/jpeg;base64,' + base64.b64encode(JPEG).decode()
        made = post('/api/orders/%d/followups' % oid, kind='diagnostico', internal_note='Prueba de evidencias (ficticia)', request_key='adi-evidence-000000000001',
                    files=json.dumps([{'data': data, 'name': 'IMG_0001.JPG', 'visible': '0'}, {'data': data, 'name': 'otra.jpg', 'visible': '0', 'filename': 'Bisagra izquierda.png'}]))
        self.assertEqual(made['status'], 201, made['body'])
        bad = post('/api/orders/%d/followups' % oid, kind='novedad', internal_note='Nombre con datos (ficticio)', request_key='adi-evidence-000000000002',
                   files=json.dumps([{'data': data, 'name': 'x.jpg', 'visible': '0', 'filename': 'Cliente ficticio pantalla'}]))
        self.assertEqual(bad['status'], 400);self.assertIn('nombre del cliente', bad['body']['error'])
        part = post('/api/orders/%d/part-requests' % oid, name='Bisagra (ficticia)', quantity='1', request_key='adi-part-000000000002')['body']['id']
        self.assertEqual(post('/api/orders/%d/followups' % oid, kind='novedad', internal_note='Repuesto (ficticio)', part_request_id=str(part), request_key='adi-evidence-000000000003',
                              files=json.dumps([{'data': data, 'name': 'WhatsApp Image 2026.jpeg', 'visible': '0'}]))['status'], 201)
        with app.connect() as c:
            rows = [tuple(r) for r in c.execute('SELECT name,original_name FROM order_followup_files WHERE order_id=? ORDER BY id', (oid,))]
        self.assertEqual(rows[0], (code + '_HP-240-G7_Diagnostico-Tecnico_01.jpg', 'IMG_0001.JPG') if 'HP' in rows[0][0] else (rows[0][0], 'IMG_0001.JPG'))
        self.assertTrue(rows[0][0].startswith(code + '_') and rows[0][0].endswith('_Diagnostico-Tecnico_01.jpg'), rows[0])
        self.assertEqual(rows[1], ('Bisagra-izquierda.jpg', 'otra.jpg'))  # el nombre escrito, con la extensión REAL (es un JPEG)
        self.assertIn('_Repuesto-%02d-Bisagra-Ficticia_Pedido-Solicitado_' % part, rows[2][0]);self.assertTrue(rows[2][0].endswith('_03.jpg'), rows[2]);self.assertEqual(rows[2][1], 'WhatsApp Image 2026.jpeg')
        listing = self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']
        files = [f for row in listing['followups'] for f in row.get('files', [])]
        self.assertIn('IMG_0001.JPG', [f.get('original_name') for f in files])


class AdiRules(unittest.TestCase):
    def ctx(self, **extra):
        base = {'id': 1, 'code': 'PCD-20261109-0001', 'status': 'reparacion', 'status_label': 'Reparación en proceso', 'status_since': '2026-11-05T10:00:00',
                'client': 'Cliente Ficticio', 'device': 'HP 240 G7', 'findings': 'Pantalla dañada', 'diagnosis_followups': 1, 'problem': 'Pantalla rota', 'estimated': '',
                'terms_accepted': True, 'received_at': '2026-11-01T09:00:00', 'quote': None, 'money': {'budget_cents': 0, 'paid_cents': 0, 'balance_cents': 0, 'credit_cents': 0, 'state': 'sin_cargos', 'state_label': ''},
                'order_money': None, 'multiple': False, 'payments': [], 'pending_transfers': {'count': 0, 'cents': 0}, 'parts': [], 'last_message': None,
                'last_payment_message': None, 'photos': {'recepcion': 2}}
        base.update(extra)
        return base

    def test_ready_with_balance_and_late_part(self):
        money = {'budget_cents': 15000, 'paid_cents': 5000, 'balance_cents': 10000, 'credit_cents': 0, 'state': 'parcial', 'state_label': 'Pago parcial registrado'}
        recs = adi_order.recommendations(self.ctx(status='listo', status_label='Listo para entregar', money=money), datetime(2026, 11, 9))
        keys = [r['key'] for r in recs]
        self.assertEqual(keys[0], 'saldo');self.assertIn('entrega', keys)
        self.assertIn('la entrega requiere registrar el pago', recs[0]['reason'])
        part = {'id': 7, 'name': 'Teclado', 'stage': 'transito', 'step': 'transito_internacional', 'step_label': 'En tránsito internacional', 'situation': 'normal',
                'situation_label': 'Sin novedad', 'eta': '2026-11-01', 'shipping': 'internacional', 'changed_at': '2026-11-02T10:00:00', 'notified': True}
        late = adi_order.recommendations(self.ctx(parts=[part]), datetime(2026, 11, 9))
        rec = next(r for r in late if r['key'] == 'repuesto_7')
        self.assertEqual(rec['priority'], 'alta');self.assertIn('ya pasó', rec['reason']);self.assertIn('En tránsito internacional', rec['reason'])
        on_time = next(r for r in adi_order.recommendations(self.ctx(parts=[part]), datetime(2026, 10, 30)) if r['key'] == 'repuesto_7')
        self.assertEqual(on_time['priority'], 'media')
        self.assertNotEqual(rec['fingerprint'], on_time['fingerprint'])  # el dato cambió: una recomendación descartada vuelve a aparecer
        cancelled = adi_order.recommendations(self.ctx(parts=[dict(part, situation='cancelado')]), datetime(2026, 11, 9))
        self.assertNotIn('repuesto_7', [r['key'] for r in cancelled])

    def test_check_message_customs_only_when_registered(self):
        part = {'id': 1, 'name': 'Pantalla', 'stage': 'transito', 'step': 'aduana_revision', 'step_label': 'En revisión aduanera', 'situation': 'normal', 'situation_label': '',
                'eta': '', 'shipping': 'internacional', 'changed_at': '', 'notified': True}
        ok = adi_order.check_message(self.ctx(parts=[part]), 'Su repuesto está en revisión en la aduana.')
        self.assertEqual(ok['warnings'], [])
        self.assertTrue(adi_order.check_message(self.ctx(), 'Su repuesto está en la aduana.')['warnings'])
        many = adi_order.check_message(self.ctx(status='pendiente', status_label='En espera de diagnóstico'),
                                       'Ya está listo!! El repuesto llegó. Su saldo está vencido. Pasó aduana. Orden OP-00099. $5,00')
        self.assertLessEqual(len(many['warnings']) + len(many['suggestions']), 5)  # sin llenar el editor de advertencias


if __name__ == '__main__':
    unittest.main()
