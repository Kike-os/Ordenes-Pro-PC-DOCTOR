"""ADI 3.0 · fase 3: motor de intereses SOLO EN SIMULACIÓN y registro de tasas. Base temporal y tasas FICTICIAS de prueba (los porcentajes de
las pruebas no son tasas oficiales registradas en el sistema). Nada se guarda como interés, no cambia saldos ni se comunica al cliente."""
import unittest
from datetime import date, timedelta
from decimal import Decimal

import test_payment_commitments as commitments  # prepara la ruta de importación y la base temporal
import app
import interest_engine as ie

AS_OF = date(2026, 11, 24)
RATE = [(date(2026, 1, 1), None, 688)]          # 6,88 % anual (valor de referencia de la orden, aquí solo como dato de prueba)


class InterestSimulatorTests(unittest.TestCase):
    def sim(self, late, capital=15000, payments=(), table=RATE, grace=90):
        return ie.simulate(capital, AS_OF - timedelta(days=late), AS_OF, payments, table, grace)

    def test_reference_example_150_dollars_120_days(self):
        got = self.sim(120)
        self.assertEqual((got['interest_days'], got['interest'], got['total']), (30, '0.85', '150.85'))
        self.assertEqual(got['mode'], 'simulacion')

    def test_grace_boundaries_89_90_91(self):
        self.assertEqual(self.sim(89)['interest'], '0.00')
        self.assertEqual(self.sim(90)['interest'], '0.00')
        got = self.sim(91)
        self.assertEqual((got['interest_days'], got['interest']), (1, '0.03'))
        self.assertEqual(got['interest_start'], (AS_OF - timedelta(days=91) + timedelta(days=91)).isoformat())

    def test_no_retroactive_grace_interest_and_no_compounding(self):
        a, b = Decimal(self.sim(150)['interest']), Decimal(self.sim(210)['interest'])
        self.assertAlmostEqual(float(b), float(a) * 2, delta=.011)         # lineal: interés simple, sin capitalizar

    def test_rate_change_is_applied_per_period(self):
        change = AS_OF - timedelta(days=10)
        got = self.sim(120, table=[(date(2026, 1, 1), None, 688), (change, None, 774)])
        self.assertEqual([p['rate'] for p in got['periods']], ['6,88 %', '7,74 %'])
        self.assertEqual(sum(p['days'] for p in got['periods']), 30)

    def test_partial_payment_during_arrears_reduces_capital(self):
        due = AS_OF - timedelta(days=120)
        pay_day = due + timedelta(days=100)
        got = self.sim(120, payments=[(pay_day, 5000)])
        self.assertEqual([p['capital'] for p in got['periods']], ['150.00', '100.00'])
        self.assertEqual(got['capital'], '100.00')
        self.assertLess(Decimal(got['interest']), Decimal('0.85'))

    def test_full_payment_stops_interest(self):
        due = AS_OF - timedelta(days=120)
        got = self.sim(120, payments=[(due + timedelta(days=95), 15000)])
        self.assertEqual((got['capital'], got['interest_days']), ('0.00', 4))

    def test_missing_validated_rate_suspends_simulation(self):
        with self.assertRaises(ie.InterestError) as raised:
            self.sim(120, table=[])
        self.assertEqual(raised.exception.status, 409)
        self.assertIn('no la reemplaza', str(raised.exception))

    def test_only_simulation_mode_can_be_active(self):
        for value in ('revision', 'aplicacion'):
            with self.assertRaises(ie.InterestError) as raised:
                ie.set_mode(None, value)
            self.assertEqual(raised.exception.status, 403)
        self.assertEqual(ie.mode(None), 'simulacion')


class InterestRouteTests(unittest.TestCase):
    Base = commitments.PaymentCommitmentTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link
    order, fresh, pay, set_status, comms, check, commit, move_due = (Base.order, Base.fresh, Base.pay, Base.set_status, Base.comms, Base.check, Base.commit,
                                                                     Base.move_due)

    def rates(self, expect=200, **body):
        got = self.post('/api/finance/rates', **body)
        self.assertEqual(got['status'], expect, got['body'])
        return got['body']

    def add(self, **extra):
        body = dict(action='add', kind='legal', rate='6,88', effective_from='2026-01-01', consulted_at='2026-11-20',
                    source_url=ie.BCE_SOURCE, evidence='Tabla de tasas de interés del BCE, dato de PRUEBA ficticio.', **extra)
        return self.rates(**body)

    def test_rate_registry_requires_official_source_and_validation(self):
        self.order(0)
        self.rates(400, action='add', kind='legal', rate='6,88', effective_from='2026-01-01', consulted_at='2026-11-20',
                   source_url='https://blog.example.com/tasas', evidence='Fuente no oficial de prueba.')
        got = self.add()
        rid = got['rates'][0]['id']
        self.assertEqual(got['rates'][0]['status'], 'sin_validar')
        with app.connect() as c:
            self.assertEqual(ie._rate_table(c, 'legal'), [])                     # sin validar no se usa
        self.rates(400, action='validate', id=str(rid), note='')
        got = self.rates(action='validate', id=str(rid), note='Validada contra la tabla oficial (prueba ficticia).')
        self.assertEqual(got['rates'][0]['status'], 'validada')
        self.rates(403, action='mode', mode='aplicacion')

    def test_order_simulation_from_broken_commitment_has_no_effects(self):
        oid, _ = self.order(10500)
        cid = self.commit(oid, amount='105,00')['current']['id']
        self.post('/api/orders/%d/interest-sim' % oid)                         # sin compromiso vencido: no exigible
        rid = self.add()['rates'][0]['id']
        self.rates(action='validate', id=str(rid), note='Validada contra la tabla oficial (prueba ficticia).')
        with app.connect() as c:
            c.execute('UPDATE payment_commitments SET due_date=?,committed_at=? WHERE id=?',
                      ((app.reception_now() - timedelta(days=120)).date().isoformat(), (app.reception_now() - timedelta(days=130)).isoformat(timespec='seconds'), cid));c.commit()
            before = tuple(c.execute('SELECT (SELECT COUNT(*) FROM order_payments),(SELECT COUNT(*) FROM order_messages),(SELECT COUNT(*) FROM payment_commitments)').fetchone())
        got = self.post('/api/orders/%d/interest-sim' % oid)
        self.assertEqual(got['status'], 200, got['body'])
        self.assertEqual((got['body']['interest_days'], got['body']['mode']), (30, 'simulacion'))
        self.assertEqual(got['body']['interest'], str((Decimal('105') * Decimal('0.0688') * 30 / 365).quantize(Decimal('0.01'))))
        with app.connect() as c:
            self.assertEqual(tuple(c.execute('SELECT (SELECT COUNT(*) FROM order_payments),(SELECT COUNT(*) FROM order_messages),(SELECT COUNT(*) FROM payment_commitments)').fetchone()), before)

    def test_provider_delay_blocks_interest(self):
        oid, _ = self.order(10500)
        self.set_status(oid, 'reparacion', estimated_delivery=(app.reception_now() - timedelta(days=5)).date().isoformat(), estimated_confirmed=1)
        got = self.post('/api/orders/%d/interest-sim' % oid, capital='105,00', due_date='2026-01-01')
        self.assertEqual(got['status'], 409)
        self.assertIn('No exigible', got['body']['error'])

    def test_cash_payment_choice_alone_never_generates_interest(self):
        oid, _ = self.order(10500)
        self.pay(oid, '40,00', method='efectivo')
        got = self.post('/api/orders/%d/interest-sim' % oid)
        self.assertEqual(got['status'], 409)                                    # sin obligación vencida registrada no hay simulación


if __name__ == '__main__':
    unittest.main()
