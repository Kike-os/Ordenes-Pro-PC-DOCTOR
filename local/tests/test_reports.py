import unittest
from datetime import date, timedelta
import test_app
import app
import reports


class ReportsTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    login = test_app.SecurityTests.login
    request = test_app.SecurityTests.request
    order_data = test_app.SecurityTests.order_data

    def board(self, cookie, query=''):
        return self.request('/api/reports' + query, cookie=cookie)

    def test_board_counts_real_orders_and_updates(self):
        cookie, csrf = self.login()
        before = self.board(cookie)['body']['board']
        created = self.request('/api/orders', self.order_data({'request_key': 'reports-order-000000001'}), cookie=cookie, csrf=csrf)
        self.assertEqual(created['status'], 201, created['body'])
        after = self.board(cookie)['body']['board']
        self.assertEqual(after['kpis']['received'], before['kpis']['received'] + 1)
        self.assertEqual(after['kpis']['active'], before['kpis']['active'] + 1)
        self.assertEqual(sum(after['periods']['received']), after['kpis']['received'])
        self.assertEqual(sum(item['total'] for item in after['statuses']), after['kpis']['received'])
        self.assertEqual(len(after['periods']['labels']), 30)
        # Sin información económica en la respuesta.
        self.assertNotIn('cents', str(after))
        oid = created['body']['id']
        with app.connect() as c:
            status = c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()[0]
        rows = self.board(cookie, '?group=status&value=' + status)['body']
        self.assertIn(oid, [row['id'] for row in rows['rows']])
        self.assertEqual(rows['total'], next(item['total'] for item in after['statuses'] if item['code'] == status))

    def test_delivered_order_moves_between_indicators(self):
        cookie, csrf = self.login()
        oid = self.request('/api/orders', self.order_data({'request_key': 'reports-order-000000002'}), cookie=cookie, csrf=csrf)['body']['id']
        today = app.reception_now()
        with app.connect() as c:
            c.execute("UPDATE orders SET status='entregado',delivered_at=? WHERE id=?", (today.isoformat(), oid))
        board = self.board(cookie)['body']['board']
        self.assertGreaterEqual(board['kpis']['delivered'], 1)
        self.assertEqual(board['kpis']['average_days'], 0)
        self.assertIn(oid, [row['id'] for row in self.board(cookie, '?group=kpi&value=delivered')['body']['rows']])
        self.assertNotIn(oid, [row['id'] for row in self.board(cookie, '?group=kpi&value=active')['body']['rows']])
        self.assertEqual(board['periods']['open'][-1], board['kpis']['active'])

    def test_filters_are_validated(self):
        cookie, _ = self.login()
        for query in ('?period=hour', '?from=2026-13-01', '?from=2026-10-10&to=2026-10-01', '?status=x', '?type=x', '?technician=a', '?group=nada&value=1', '?group=kpi&value=ingresos'):
            self.assertEqual(self.board(cookie, query)['status'], 400, query)
        self.assertEqual(self.board('')['status'], 401)
        monthly = self.board(cookie, '?period=month')['body']['board']
        self.assertLessEqual(len(monthly['periods']['labels']), 13)
        self.assertEqual(self.board(cookie, '?technician=none&type=portatil&status=pendiente')['status'], 200)

    def test_buckets(self):
        self.assertEqual(reports._bucket(date(2026, 10, 14), 'week'), date(2026, 10, 12))
        self.assertEqual(reports._next(date(2026, 12, 1), 'month'), date(2027, 1, 1))
        self.assertEqual(reports._day('2026-10-09T23:30:00-05:00'), date(2026, 10, 9))
        self.assertIsNone(reports._day('no es fecha'))

if __name__ == '__main__':
    unittest.main()
