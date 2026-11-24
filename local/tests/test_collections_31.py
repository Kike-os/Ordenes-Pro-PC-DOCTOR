"""ADI Smart Collections 3.1: estados financieros verificables, pago al retirar frente a cartera vencida, conciliación precisa, reclamos,
varias órdenes por cliente, límites de 89/90/91 días, indicadores sin duplicidades y mensajes coherentes con el estado real.
Base temporal y datos ficticios: nada se envía, no se registran pagos reales y no cambia ningún saldo."""
import time
import unittest
from datetime import timedelta

import test_collections as base  # prepara la ruta de importación y la base temporal
import app
import collections_center as cc


class SmartCollections31Tests(unittest.TestCase):
    Base = base.CollectionsTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link
    order, fresh, pay, set_status, comms, check, commit, move_due, rates, add = (Base.order, Base.fresh, Base.pay, Base.set_status, Base.comms, Base.check, Base.commit,
                                                                                Base.move_due, Base.rates, Base.add)
    get, setup_order, deliver = Base.get, Base.setup_order, Base.deliver

    def new_order(self, cents, key):
        cookie, csrf, post, order = self.paid_order(cents, pay=False, key=key)
        self.post, self.cookie = post, cookie
        return order['id']

    def item(self, oid):
        return next(i for i in self.get('/api/collections')['items'] if i['order_id'] == oid)

    def account(self):
        with app.connect() as c:
            return c.execute("INSERT INTO bank_accounts(bank,account_type,number,holder,holder_id,created_at,updated_at) VALUES ('Banco Ficticio','ahorros','5555000077','TITULAR FICTICIO','0100000017','x','x')").lastrowid

    def test_pay_at_pickup_is_never_overdue_and_counters_are_separate(self):
        oid, _ = self.setup_order(10500)
        it = self.item(oid)
        self.assertEqual((it['state'], it['days_overdue'], it['due_date']), ('pago_al_retirar', None, ''))
        self.set_status(oid, 'listo')
        with app.connect() as c:
            base.insert(c, 'order_status_log', order_id=oid, from_status='reparacion', to_status='listo', created_at=app.reception_now().isoformat());c.commit()
        it = self.item(oid)
        self.assertEqual((it['state'], it['days_overdue'], it['pickup_days']), ('pago_al_retirar', None, 0))   # retiro y mora: contadores distintos
        k = self.get('/api/collections')['kpis']
        self.assertEqual((k['at_pickup_cents'], k['overdue_cents'], k['consistent']), (10500, 0, True))
        purposes = {p['key']: p for p in self.comms(oid, 'analysis')['purposes']}
        self.assertFalse(purposes['regularizacion_saldo']['available'])                                    # no se trata como moroso

    def test_89_90_91_days_after_delivery(self):
        oid, _ = self.setup_order(10500)
        for days, state in ((89, 'pago_vencido'), (90, 'pago_vencido'), (91, 'mora_90')):
            self.deliver(oid, days)
            it = self.item(oid)
            self.assertEqual((it['state'], it['days_overdue']), (state, days))
        self.assertEqual(self.get('/api/collections')['kpis']['over90_cents'], 10500)

    def test_transfer_covering_balance_stays_visible_as_pending_reconciliation(self):
        oid, _ = self.setup_order(10500)
        acc = self.account()
        self.pay(oid, '105,00', method='transferencia', note='Comprobante ficticio', bank_account_id=str(acc), reference='TRX-SC31-0001')
        it = self.item(oid)                                                                                   # antes desaparecía de la cartera
        self.assertEqual((it['state'], it['reconciliation'], it['pending_cents']), ('pendiente_conciliacion', 'transferencia_pendiente', 10500))
        self.assertEqual(self.get('/api/collections')['kpis']['pending_reconciliation_cents'], 10500)

    def test_partial_confirmed_rejected_transfer_and_no_payments(self):
        oid, _ = self.setup_order(10500)
        self.assertEqual(self.item(oid)['reconciliation'], 'no_aplica')
        self.pay(oid, '40,00', method='efectivo')
        it = self.item(oid)
        self.assertEqual((it['reconciliation'], it['confirmed_paid_cents']), ('pago_parcial_confirmado', 4000))
        acc = self.account()
        self.pay(oid, '10,00', method='transferencia', note='Comprobante ficticio', bank_account_id=str(acc), reference='TRX-SC31-0002')
        with app.connect() as c:
            c.execute("UPDATE bank_transfers SET status='rechazado' WHERE reference='TRX-SC31-0002'");c.commit()
        it = self.item(oid)
        self.assertEqual((it['state'], it['reconciliation']), ('en_revision', 'diferencia'))

    def test_claim_puts_case_in_review_and_blocks_collection(self):
        oid, client = self.setup_order(10500)
        self.deliver(oid, 20)
        with app.connect() as c:
            base.insert(c, 'pqrs_cases', code='PQRS-FICT-1', category='reclamo', status='recibida', client_id=client, order_id=oid, name='Cliente ficticio',
                        email='cliente@example.invalid', subject='Reclamo ficticio', description='Texto ficticio de prueba.', privacy_consent=1);c.commit()
        it = self.item(oid)
        self.assertEqual((it['state'], it['claims']), ('en_revision', ['PQRS-FICT-1']))
        self.assertEqual(self.check(oid, 'pago_pendiente')['consentimiento']['level'], 'block')
        props = [p for p in self.get('/api/collections/proposals')['items'] if p['order_id'] == oid]
        self.assertTrue(props and not props[0]['ready'])

    def test_several_orders_of_one_client_are_separate_and_devices_not_repeated(self):
        a = self.new_order(5000, 'sc31-a')
        b = self.new_order(7000, 'sc31-b')
        self.assertNotEqual(a, b)
        items = {i['order_id']: i for i in self.get('/api/collections')['items']}
        self.assertEqual((items[a]['balance_cents'], items[b]['balance_cents']), (5000, 7000))
        self.assertEqual(cc.device_label([{'brand': 'HP', 'model': 'HP 240 G7'}, {'brand': 'HP', 'model': 'HP 240 G7'}]), 'HP 240 G7')
        self.assertEqual(cc.device_label([{'brand': 'Dell', 'model': 'Latitude 5420'}]), 'Dell Latitude 5420')

    def test_statement_says_not_applicable_for_unknown_overdue(self):
        import account_statement as st
        oid, client = self.setup_order(10500)
        with app.connect() as c:
            data = st.data_for(c, client, app.reception_now())
        self.assertIsNone(data['rows'][0]['days'])
        self.assertEqual(data['rows'][0]['state'], 'Pago al retirar')

    def test_requires_review_when_delivery_date_is_missing(self):
        oid, _ = self.setup_order(10500)
        self.set_status(oid, 'entregado', delivered_at='')
        it = self.item(oid)
        self.assertEqual(it['state'], 'requiere_revision')
        self.assertTrue(it['requires_review'])

    def test_many_records_stay_fast(self):
        for n in range(25):
            self.new_order(1000 + n, 'sc31-many-%02d' % n)
        started = time.monotonic()
        got = self.get('/api/collections')
        self.assertGreaterEqual(got['total'], 25)
        self.assertTrue(got['kpis']['consistent'])
        self.assertLess(time.monotonic() - started, 5)


if __name__ == '__main__':
    unittest.main()
