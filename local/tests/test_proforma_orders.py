"""Proformas y órdenes de servicio: vincular al crear o después (sin otra proforma ni perder aprobación, firma, importes ni historial),
decisión del cliente registrada en la orden sin cambiar su estado técnico, consulta en ambos sentidos, búsqueda de órdenes y conceptos
repetidos con el presupuesto técnico sin cobrarlos dos veces. Base temporal y datos ficticios; nada se emite al SRI."""
import json
import re
import unittest

import test_invoicing
import test_cash
import app
import equipment

SIGN = json.dumps([[[10, 10], [100, 60], [200, 120], [300, 80], [400, 60], [500, 140], [600, 200], [700, 150], [800, 90], [900, 40]]])
CLIENT = dict(client_name='Cliente ficticio', client_identification='0100000017', client_email='cliente@example.invalid')
ITEMS = [{'kind': 'servicio', 'description': 'Instalación de software ficticia', 'quantity': '1', 'unit_price': '40,00'},
         {'kind': 'producto', 'description': 'Memoria RAM ficticia', 'quantity': '1', 'unit_price': '60,00'}]


class ProformaOrderTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, paid_order = Base.form, Base.paid_order

    def history(self, oid):
        with app.connect() as c:
            return [r['comment'] for r in c.execute("SELECT comment FROM order_history WHERE order_id=? AND event='proforma' ORDER BY id", (oid,))]

    def state(self, oid):
        with app.connect() as c:
            return c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()[0], equipment.money(c, oid)['balance_cents']

    def client_decides(self, cookie, post, pid, decisions):
        token = post('/api/proformas/%d' % pid, action='send')['body']['link'].rsplit('/', 1)[1]
        key = re.search(r'name="passkey" value="([0-9a-f]+)"', self.form('/proforma/' + token, {'last4': '0017'})['body'])[1]
        ids = [i['id'] for i in self.request('/api/proformas/%d' % pid, cookie=cookie)['body']['items']]
        fields = {'passkey': key, 'name': 'Cliente Ficticio', 'accept': 'on', 'signature': SIGN, 'action': 'decide'}
        fields.update({'decision_%d' % i: d for i, d in zip(ids, decisions)})
        return self.form('/proforma/' + token, fields)

    def test_link_existing_approved_proforma_keeps_evidence_and_shows_in_order(self):
        cookie, csrf, post, order = self.paid_order(1000)
        oid = order['id']
        pid = post('/api/proformas', items=json.dumps(ITEMS), request_key='proforma-orden-000001', **CLIENT)['body']['id']
        self.client_decides(cookie, post, pid, ['aprobado', 'rechazado'])  # aprobación parcial con firma, antes de vincular
        before = self.request('/api/proformas/%d' % pid, cookie=cookie)['body']
        self.assertEqual((before['proforma']['status'], before['proforma']['order']), ('parcial', None))
        order_before = self.state(oid)
        with app.connect() as c:
            count = c.execute('SELECT COUNT(*) FROM proformas').fetchone()[0]
        linked = post('/api/proformas/%d' % pid, action='link', order_id=str(oid))
        self.assertEqual(linked['status'], 200, linked['body'])
        after = linked['body']
        self.assertEqual(after['proforma']['order']['code'], order['code'])
        # Sin otra proforma ni cambios en la aprobación, la firma, los importes, las partidas o el historial anterior.
        self.assertEqual((after['proforma']['status'], after['acceptance'], after['approved_totals'], after['totals']),
                         (before['proforma']['status'], before['acceptance'], before['approved_totals'], before['totals']))
        self.assertEqual([(i['description'], i['status']) for i in after['items']], [(i['description'], i['status']) for i in before['items']])
        self.assertEqual(after['events'][1:], before['events'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM proformas').fetchone()[0], count)
            self.assertNotEqual(c.execute('SELECT signature FROM proforma_acceptances WHERE proforma_id=?', (pid,)).fetchone()[0], '[]')
        self.assertEqual(self.state(oid), order_before)  # el saldo y el estado técnico de la orden no cambian (no se duplican cobros)
        self.assertIn('Proforma %s vinculada (aprobada parcialmente' % after['proforma']['code'], self.history(oid)[-1])
        view = self.request('/api/proformas/order/%d' % oid, cookie=cookie)['body']
        self.assertEqual([(r['code'], r['status'], [a['description'] for a in r['authorized']]) for r in view['rows']], [(after['proforma']['code'], 'parcial', ['Instalación de software ficticia'])])
        self.assertEqual(view['rows'][0]['acceptance']['decision'], 'parcial')
        listed = self.request('/api/proformas?order=con', cookie=cookie)['body']['rows']
        self.assertEqual([r['order_code'] for r in listed], [order['code']])
        # Repetir no cambia nada; otra orden exige desvincular primero; desvincular pide motivo y queda en ambos historiales.
        self.assertEqual(post('/api/proformas/%d' % pid, action='link', order_id=str(oid))['status'], 200)
        other = post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'request_key': 'invoice-order-request-0002'}))['body']['id']
        self.assertEqual(post('/api/proformas/%d' % pid, action='link', order_id=str(other))['status'], 409)
        self.assertEqual(post('/api/proformas/%d' % pid, action='unlink')['status'], 400)
        self.assertEqual(post('/api/proformas/%d' % pid, action='unlink', reason='Orden equivocada (ficticio)')['status'], 200)
        self.assertIn('desvinculada', self.history(oid)[-1])
        self.assertEqual(post('/api/proformas/%d' % pid, action='link', order_id=str(other))['status'], 200)
        self.assertEqual(len(self.history(oid)), 2)

    def test_other_client_needs_confirmation_and_technicians_cannot_link(self):
        cookie, csrf, post, order = self.paid_order(1000)
        pid = post('/api/proformas', items=json.dumps(ITEMS), client_name='Otra Persona Ficticia', client_identification='0912345678', request_key='proforma-orden-000002')['body']['id']
        refused = post('/api/proformas/%d' % pid, action='link', order_id=str(order['id']))
        self.assertEqual((refused['status'], sorted(refused['body']['fields'])), (409, ['confirm_client', 'note']))
        ok = post('/api/proformas/%d' % pid, action='link', order_id=str(order['id']), confirm_client='1', note='El cliente paga la reparación de un familiar')
        self.assertEqual(ok['status'], 200, ok['body'])
        self.assertIn('Cliente distinto confirmado', self.history(order['id'])[-1])
        tech_cookie, tech_csrf = test_cash.CashTests.technician(self)
        self.assertEqual(self.request('/api/proformas/%d' % pid, {'action': 'unlink', 'reason': 'Prueba ficticia'}, cookie=tech_cookie, csrf=tech_csrf)['status'], 403)
        self.assertEqual(post('/api/proformas/%d' % pid, action='link', order_id='999999')['status'], 404)  # orden inexistente
        self.assertEqual(post('/api/proformas', items=json.dumps(ITEMS), origin='orden', request_key='proforma-orden-000003', **CLIENT)['status'], 400)  # desde una orden: la orden es obligatoria

    def test_created_from_order_decision_sync_overlap_and_search(self):
        cookie, csrf, post, order = self.paid_order(1000)  # presupuesto técnico aprobado: «Servicio ficticio»
        oid = order['id']
        found = self.request('/api/proformas/orders?q=' + order['code'][-6:], cookie=cookie)['body']['rows']
        self.assertEqual([r['id'] for r in found], [oid])
        self.assertIn(oid, [r['id'] for r in self.request('/api/proformas/orders?q=0100000017', cookie=cookie)['body']['rows']])
        self.assertIn(oid, [r['id'] for r in self.request('/api/proformas/orders?q=cliente%20fict', cookie=cookie)['body']['rows']])
        items = [{'kind': 'servicio', 'description': 'Servicio ficticio', 'quantity': '1', 'unit_price': '10,00'}, ITEMS[1]]
        made = post('/api/proformas', items=json.dumps(items), origin='orden', order_id=str(oid), request_key='proforma-orden-000004', **CLIENT)
        self.assertEqual(made['status'], 200, made['body'])
        pid = made['body']['id']
        self.assertEqual((made['body']['proforma']['order']['id'], made['body']['overlaps']), (oid, ['Servicio ficticio']))
        self.assertIn('creada desde la orden', self.history(oid)[-1])
        status_before = self.state(oid)
        post('/api/proformas/%d' % pid, action='send')
        decided = post('/api/proformas/%d' % pid, action='decide', decision='aprobada', note='Aprobó por teléfono con el técnico (ficticio)')
        self.assertEqual(decided['status'], 200, decided['body'])
        last = self.history(oid)[-1]
        self.assertIn('aprobada por Persona de prueba (registrada por el personal)', last)
        self.assertIn('1 × Memoria RAM ficticia', last)
        self.assertIn('El estado técnico de la orden no cambia', last)
        self.assertEqual(self.state(oid), status_before)
        notices = self.request('/api/notifications', cookie=cookie)['body']['items']
        self.assertTrue(any(n['title'].startswith('Proforma aprobada (registrada por el personal)') and n['href'] == '#orders?id=%d' % oid for n in notices))
        # Conceptos ya autorizados en el presupuesto de la orden: no se facturan sin confirmación expresa.
        blocked = post('/api/proformas/%d' % pid, action='convert')
        self.assertEqual((blocked['status'], blocked['body']['overlaps']), (409, ['Servicio ficticio']))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM invoices WHERE source_kind=?', ('proforma',)).fetchone()[0], 0)
        done = post('/api/proformas/%d' % pid, action='convert', accept_overlap='1')
        self.assertEqual(done['status'], 200, done['body'])
        self.assertIn('convertida en borrador de factura', self.history(oid)[-1])
        self.assertEqual(self.request('/api/proformas/order/%d' % oid, cookie=cookie)['body']['rows'][0]['invoice']['id'], done['body']['invoice_id'])
        self.assertEqual(self.state(oid), status_before)  # la factura de la proforma no toca el saldo de la orden


if __name__ == '__main__':
    unittest.main()
