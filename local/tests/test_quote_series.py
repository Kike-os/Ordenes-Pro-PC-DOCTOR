"""Varios presupuestos independientes por orden: P1 aprobado y pagado, P2 pendiente, P3 aprobado sin pagar, cada uno con su propia
aprobación; versiones dentro de cada presupuesto; saldo y factura con todo lo aprobado una sola vez; Resumen de presupuestos con las
proformas ya vinculadas, sin duplicarlas. Base temporal y datos ficticios; nada se emite al SRI."""
import json
import unittest

import test_invoicing
import test_proforma_orders as po
import app
import equipment
import quotes


class QuoteSeriesTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, paid_order = Base.form, Base.paid_order
    client_decides = po.ProformaOrderTests.client_decides

    def independent(self, post, oid, description, cents):
        made = post('/api/orders/%d/quote' % oid, independent='1')
        self.assertEqual(made['status'], 201, made['body'])
        qid = made['body']['id']
        self.assertEqual(post('/api/quotes/%d' % qid, action='save', items=[{'description': description, 'category': 'servicio', 'quantity': 1, 'unit_cents': cents, 'taxed': True}])['status'], 200)
        self.assertEqual(post('/api/quotes/%d' % qid, action='send')['status'], 200)
        return qid

    def approve(self, cookie, post, qid, approved=True):
        items = [i['id'] for i in self.request('/api/quotes/%d' % qid, cookie=cookie)['body']['quote']['items']]
        body = dict(approved=','.join(map(str, items)) if approved else '', rejected='' if approved else ','.join(map(str, items)), note='Decidió por teléfono (ficticio)')
        result = post('/api/quotes/%d' % qid, action='decide', **body)
        self.assertEqual(result['status'], 200, result['body'])

    def statuses(self, oid):
        with app.connect() as c:
            return {r['code'].rsplit('-', 1)[1]: (r['status'], r['series']) for r in c.execute('SELECT code,status,series FROM quotes WHERE order_id=? ORDER BY version', (oid,))}

    def test_independent_budgets_keep_their_own_approval_and_payment(self):
        cookie, csrf, post, order = self.paid_order(1000)  # P1: aprobado y pagado ($10,00)
        oid = order['id']
        p2 = self.independent(post, oid, 'Cambio de pantalla ficticio', 5000)  # P2: queda pendiente de aprobación
        p3 = self.independent(post, oid, 'Limpieza interna ficticia', 2000)
        self.approve(cookie, post, p3)  # P3: aprobado, sin pagar
        self.assertEqual(self.statuses(oid), {'P1': ('aprobado', 1), 'P2': ('enviado', 2), 'P3': ('aprobado', 3)})
        with app.connect() as c:
            money = equipment.money(c, oid)
            found = quotes.authorized(c, oid)
        self.assertEqual((money['budget_cents'], money['paid_cents']), (3000, 1000))  # P1 + P3, una sola vez; P2 no suma
        self.assertEqual(sorted(i['description'] for i in found['items']), ['Limpieza interna ficticia', 'Servicio ficticio'])
        view = self.request('/api/orders/%d/quote' % oid, cookie=cookie)['body']['summary']
        rows = {r['code'].rsplit('-', 1)[1]: (r['status'], r['authorized_cents'], r['paid_cents'], r['payment']) for r in view['rows']}
        self.assertEqual(rows, {'P1': ('aprobado', 1000, 1000, 'pagado'), 'P2': ('enviado', 0, 0, 'no_aplica'), 'P3': ('aprobado', 2000, 0, 'pendiente')})
        self.assertEqual(view['totals']['quotes'], {'count': 3, 'authorized_cents': 3000, 'paid_cents': 1000, 'balance_cents': 2000})
        # Rechazar P2 no toca P1 ni P3; un abono parcial no marca nada como pagado de más.
        self.approve(cookie, post, p2, approved=False)
        self.assertEqual(self.statuses(oid), {'P1': ('aprobado', 1), 'P2': ('rechazado', 2), 'P3': ('aprobado', 3)})
        self.assertEqual(post('/api/orders/%d/payments' % oid, amount='5,00', method='efectivo')['status'], 201)
        view = self.request('/api/orders/%d/quote' % oid, cookie=cookie)['body']['summary']
        self.assertEqual({r['code'].rsplit('-', 1)[1]: r['payment'] for r in view['rows']}, {'P1': 'pagado', 'P2': 'no_aplica', 'P3': 'parcial'})
        # Una versión nueva de P3 queda en su misma serie y no reemplaza a P1 ni a P2.
        version = post('/api/quotes/%d' % p3, action='version')
        self.assertEqual(version['status'], 201, version['body'])
        self.assertEqual(self.statuses(oid)['P4'], ('borrador', 3))
        self.assertEqual(self.statuses(oid)['P1'], ('aprobado', 1))
        with app.connect() as c:
            self.assertEqual(equipment.money(c, oid)['budget_cents'], 3000)  # un borrador no cambia lo autorizado

    def test_old_single_budget_orders_behave_as_before(self):
        cookie, csrf, post, order = self.paid_order(1500)
        oid = order['id']
        quote = self.request('/api/orders/%d/quote' % oid, cookie=cookie)['body']['versions'][0]['id']
        version = post('/api/quotes/%d' % quote, action='version')['body']['id']  # revisión del mismo presupuesto: copia las partidas
        self.assertEqual(post('/api/quotes/%d' % version, action='send')['status'], 200)
        self.approve(cookie, post, version)
        self.assertEqual({k: v[1] for k, v in self.statuses(oid).items()}, {'P1': 1, 'P2': 1})
        with app.connect() as c:
            self.assertEqual(equipment.money(c, oid)['budget_cents'], 1500)  # la versión reemplaza, no suma
        summary = self.request('/api/orders/%d/quote' % oid, cookie=cookie)['body']['summary']
        self.assertEqual([(r['code'].rsplit('-', 1)[1], r['payment']) for r in summary['rows'] if r['kind'] == 'presupuesto'], [('P2', 'pagado')])

    def test_linked_proforma_appears_in_summary_without_duplicates(self):
        cookie, csrf, post, order = self.paid_order(1000)
        oid = order['id']
        pid = post('/api/proformas', items=json.dumps(po.ITEMS), request_key='proforma-resumen-00001', **po.CLIENT)['body']['id']
        self.client_decides(cookie, post, pid, ['aprobado', 'aprobado'])
        self.assertEqual(post('/api/proformas/%d' % pid, action='advance', method='efectivo', amount='30', request_key='anticipo-resumen-00001')['status'], 200)
        self.assertEqual(post('/api/proformas/%d' % pid, action='link', order_id=str(oid))['status'], 200)  # vinculada antes, como en producción
        with app.connect() as c:
            count = c.execute('SELECT COUNT(*) FROM proformas').fetchone()[0]
            budget = equipment.money(c, oid)['budget_cents']
        data = self.request('/api/orders/%d/quote' % oid, cookie=cookie)['body']['summary']
        mine = [r for r in data['rows'] if r['kind'] == 'proforma']
        self.assertEqual([(r['id'], r['status'], r['authorized_cents'], r['paid_cents'], r['payment']) for r in mine], [(pid, 'aprobada', 10000, 3000, 'parcial')])
        self.assertEqual(data['totals']['proformas'], {'count': 1, 'authorized_cents': 10000, 'paid_cents': 3000, 'balance_cents': 7000})
        unit = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']['group']['units'][0]
        self.assertEqual((unit['proformas']['count'], unit['proformas']['balance_cents']), (1, 7000))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM proformas').fetchone()[0], count)  # consultar no crea nada
            self.assertEqual(equipment.money(c, oid)['budget_cents'], budget)  # ni suma la proforma al saldo de la orden


if __name__ == '__main__':
    unittest.main()
