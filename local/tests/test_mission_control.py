"""Technical Mission Control 5.1: comparación con el periodo anterior, indicadores con denominador válido y cohorte identificable, y resumen
financiero desde sus módulos (solo administración). Base temporal y datos ficticios; nada se modifica."""
import unittest
from datetime import timedelta

import test_collections as base  # prepara la ruta de importación y la base temporal
import app
import reports


class MissionControlTests(unittest.TestCase):
    Base = base.CollectionsTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link
    order, fresh, pay, set_status, deliver, setup_order, get = Base.order, Base.fresh, Base.pay, Base.set_status, Base.deliver, Base.setup_order, Base.get

    def board(self, **q):
        today = app.reception_now().date()
        with app.connect() as c:
            return reports.build(c, reports.parse_filters({k: [v] for k, v in q.items()}, today), today)

    def test_indicators_have_valid_denominators(self):
        b = self.board()
        for key in ('on_time', 'fast', 'progress'):
            ind = b['indicators'][key]
            self.assertTrue(ind['percent'] is None or ind['total'] > 0)
            self.assertTrue(ind['method'])
        self.assertIsNone(b['indicators']['capacity']['percent'])                      # sin capacidad definida no hay porcentaje

    def test_on_time_cohort_and_previous_period(self):
        oid, _ = self.setup_order(10500)
        today = app.reception_now().date()
        with app.connect() as c:
            c.execute("UPDATE orders SET status='entregado',delivered_at=?,estimated_delivery=?,estimated_confirmed=1 WHERE id=?",
                      (app.reception_now().isoformat(timespec='seconds'), (today + timedelta(days=1)).isoformat(), oid));c.commit()
        b = self.board(period='month')
        ind = b['indicators']['on_time']
        self.assertEqual((ind['value'], ind['total'], ind['percent']), (1, 1, 100))
        self.assertIn('previous', b)
        self.assertEqual(b['previous']['received'], 0)
        self.assertEqual(b['kpis']['delivered'], 1)

    def test_summary_sources_and_admin_only(self):
        oid, _ = self.setup_order(10500)
        self.pay(oid, '40,00')
        got = self.get('/api/reports/summary')
        self.assertEqual(got['income']['month'], 4000)
        self.assertEqual(len(got['income']['series']), 30)
        self.assertFalse(got['profitability']['available'])                            # no se inventa una rentabilidad
        self.assertIn('Cobros de órdenes', got['sources']['income'])
        self.assertEqual(got['portfolio']['capital_cents'], 6500)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.request('/api/reports/summary', cookie=self.cookie)['status'], 403)


if __name__ == '__main__':
    unittest.main()
