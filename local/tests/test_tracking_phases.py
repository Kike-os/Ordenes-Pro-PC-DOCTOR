"""Seguimiento por fases (1.5.224): Activas por omisión en el Inicio, Entregadas y Todas; una orden entregada sale de Activas sin
borrarse y vuelve si se reabre; «Entregado» no es «pagado»: el saldo sigue en cuentas por cobrar y en la alerta del seguimiento.
Base temporal y datos ficticios."""
import unittest

import test_app
import test_cash
import app
import cash_sessions
import equipment

app.os.environ.setdefault('LOGIN_CAPTCHA', 'off')


class TrackingPhaseTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data
    charged_order = test_cash.CashTests.charged_order

    def board(self, cookie, query=''):
        result = self.request('/api/tracking?size=50' + query, cookie=cookie)
        self.assertEqual(result['status'], 200, result)
        return result['body']

    def test_phases_reopen_and_receivables(self):
        cookie, csrf = self.login()
        post = lambda path, **data: self.request(path, data, cookie=cookie, csrf=csrf)
        status = lambda oid, value, **extra: post('/api/order-status', id=str(oid), status=value, **extra)
        active = [post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'model': 'Activa %d' % n, 'request_key': 'phase-active-%04d' % n}))['body']['id'] for n in range(3)]
        status(active[1], 'listo')
        done = post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'model': 'Entregada', 'request_key': 'phase-done-000001'}))['body']['id']
        self.assertEqual(status(done, 'entregado')['status'], 200)
        owed = self.charged_order(post, cookie, 'phase-owed', 4500)['id']  # presupuesto aprobado de $45,00 sin pagar
        self.assertEqual(status(owed, 'entregado')['status'], 409)  # entregar con saldo exige autorización expresa
        self.assertEqual(status(owed, 'entregado', authorize_balance='1', balance_reason='El cliente pagará el viernes (ficticio)')['status'], 200)
        with app.connect() as c:
            statuses = dict(c.execute('SELECT id,status FROM orders').fetchall())
            history = c.execute('SELECT COUNT(*) FROM order_history').fetchone()[0]
        ids = lambda data: {row['id'] for row in data['rows']}
        # Activas: sin las entregadas. Entregadas y Todas las siguen mostrando. Sin «phase», como antes: todas.
        self.assertEqual(ids(self.board(cookie, '&phase=activas')), set(active))
        self.assertEqual(ids(self.board(cookie, '&phase=entregadas')), {done, owed})
        self.assertEqual(ids(self.board(cookie, '&phase=todas')), set(active) | {done, owed})
        self.assertEqual(ids(self.board(cookie)), set(active) | {done, owed})
        self.assertEqual(ids(self.board(cookie, '&phase=listas')), {active[1]})
        self.assertEqual(self.request('/api/tracking?phase=otra', cookie=cookie)['status'], 400)
        # Combinables con la búsqueda y el estado; consultar no cambia ninguna orden ni el historial.
        self.assertEqual(ids(self.board(cookie, '&phase=activas&q=Activa%202')), {active[2]})
        self.assertEqual(ids(self.board(cookie, '&phase=activas&status=entregado')), set())
        data = self.board(cookie, '&phase=activas')
        self.assertEqual({k: data['phases'][k] for k in ('activas', 'entregadas', 'todas', 'listas', 'entregadas_hoy', 'entregadas_saldo', 'saldo_cents')},
                         {'activas': 3, 'entregadas': 2, 'todas': 5, 'listas': 1, 'entregadas_hoy': 2, 'entregadas_saldo': 1, 'saldo_cents': 4500})
        # La entregada con saldo sigue en la alerta de cobro, en el reporte de saldos y en el «por cobrar» de Caja.
        self.assertEqual(ids(self.board(cookie, '&phase=entregadas&balance=1')), {owed})
        report = self.request('/api/reports/finance?from=2026-01-01&to=2030-12-31', cookie=cookie)['body']
        self.assertIn(owed, [row['id'] for row in report['rows']])
        with app.connect() as c:
            self.assertEqual(cash_sessions.indicators(c, app.reception_now())['receivable_cents'], 4500)
            self.assertEqual(equipment.money(c, owed)['balance_cents'], 4500)
            self.assertEqual(dict(c.execute('SELECT id,status FROM orders').fetchall()), statuses)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_history').fetchone()[0], history)
        # Reabierta por garantía (revertir la entrega, solo administración): vuelve a Activas con todo su historial.
        self.assertEqual(status(done, 'reparacion', comment='Reingreso por garantía (ficticio)')['status'], 200)
        self.assertIn(done, ids(self.board(cookie, '&phase=activas')))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_history WHERE order_id=?', (done,)).fetchone()[0] >= 3, True)
            self.assertTrue(c.execute("SELECT 1 FROM audit WHERE action='delivery_reverted' AND entity_id=?", (done,)).fetchone())
        # Pagar el saldo lo retira de la alerta de cobro (la orden sigue entregada).
        self.assertEqual(post('/api/orders/%d/payments' % owed, amount='45,00', method='efectivo')['status'], 201)
        data = self.board(cookie, '&phase=entregadas&balance=1')
        self.assertEqual((ids(data), data['phases']['entregadas_saldo']), (set(), 0))
        self.assertEqual(ids(self.board(cookie, '&phase=entregadas')), {owed})


if __name__ == '__main__':
    unittest.main()
