"""1.5.296 · Cobertura Empresarial de Repuestos — PC-DOCTOR. Datos ficticios en una base temporal (sin correo, impresión ni despliegue).

Ejemplo de la especificación: pantalla a $150,00 para el cliente, costo real $95,00, cobertura 100 % → PC-DOCTOR paga $95,00 al proveedor
(egreso real de caja, una sola vez) y el cliente sigue viendo y pagando $150,00. Autorizar no mueve dinero; el técnico nunca recibe
costos, proveedor, pagos ni margen; los documentos del cliente no cambian."""
import json
import unittest

import test_fase2
import app
import cash_sessions

INTERNAL = ('cost_cents', 'covered_cents', 'paid_cents', 'pending_cents', 'margin_cents', 'supplier', 'supplier_id', 'supplier_document', 'notes', 'payments', 'suppliers')
SUPPLIER = 'Distribuidora Ficticia Omega'


def leaks(value):
    if isinstance(value, dict):
        return any(k in INTERNAL or leaks(v) for k, v in value.items())
    if isinstance(value, list):
        return any(leaks(v) for v in value)
    return False


class PartCoverageTests(unittest.TestCase):
    Base = test_fase2.Fase2Tests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, counts, tech, account = Base.form, Base.prepare, Base.counts, Base.tech, Base.account

    # ---- ayudas ----
    def setup_quote(self, decide=True, key='0001'):
        """Orden con presupuesto: pantalla ficticia (repuesto, $150,00 sin IVA, en inventario) y un servicio de $20,00."""
        cookie, csrf = (self.cookie, self.csrf) if getattr(self, 'post', None) else self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        order = post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'request_key': 'coverage-order-request-' + key}))['body']
        made = post('/api/catalog', name='Pantalla ficticia 15,6" ' + key, category='repuesto', price='150', taxed=False)
        self.assertIn('id', made['body'], made['body'])
        cat = made['body']['id']
        with app.connect() as c:
            found = c.execute('SELECT id FROM suppliers WHERE name=?', (SUPPLIER,)).fetchone()
            sup = found[0] if found else c.execute("INSERT INTO suppliers(name,created_at,updated_at) VALUES (?,'x','x')", (SUPPLIER,)).lastrowid
            item = c.execute("INSERT INTO inventory_items(catalog_id,kind,created_at,updated_at) VALUES (?,'repuesto','x','x')", (cat,)).lastrowid
            c.commit()
        quote = post('/api/orders/%d/quote' % order['id'])['body']['id']
        items = [{'description': 'Diagnóstico y mano de obra', 'category': 'servicio', 'quantity': 1, 'unit_cents': 2000, 'taxed': False},
                 {'catalog_id': cat, 'description': 'Pantalla ficticia 15,6"', 'category': 'repuesto', 'quantity': 1, 'unit_cents': 15000, 'taxed': False}]
        self.assertEqual(post('/api/quotes/%d' % quote, action='save', items=items)['status'], 200)
        if decide:
            post('/api/quotes/%d' % quote, action='send')
            ids = [i['id'] for i in self.request('/api/quotes/%d' % quote, cookie=cookie)['body']['quote']['items']]
            self.assertEqual(post('/api/quotes/%d' % quote, action='decide', approved=','.join(map(str, ids)), note='Aprobó por teléfono (ficticio)')['status'], 200)
        self.cookie, self.csrf, self.post = cookie, csrf, post
        return order, quote, sup, item

    def open_cash(self, cookie=None, csrf=None):
        cookie, csrf = cookie or self.cookie, csrf or self.csrf
        reg = self.request('/api/caja/state', cookie=cookie)['body']['registers'][0]['id']
        self.opened = getattr(self, 'opened', 0) + 1
        opened = self.request('/api/caja/open', {'register_id': str(reg), 'shift': 'Mañana', 'counts': self.counts(cookie, {('billete', 2000): 10}),
                                                 'request_key': 'apertura-cobertura-%04d' % self.opened}, cookie=cookie, csrf=csrf)
        self.assertEqual(opened['status'], 200, opened['body'])
        return opened['body']['session_id']

    def authorized(self, quote, sup, cost='95,00', mode='total', percent=''):
        made = self.post('/api/quotes/%d/coverage' % quote, position='1', cost=cost, mode=mode, percent=percent, supplier_id=str(sup), notes='Nota interna ficticia')
        self.assertEqual(made['status'], 201, made['body'])
        cid = made['body']['id']
        ok = self.post('/api/coverage/%d' % cid, action='authorize', revision=str(made['body']['coverage']['revision']), authorized_name='Gerencia ficticia')
        self.assertEqual(ok['status'], 200, ok['body'])
        return cid, ok['body']['coverage']

    def cash_out(self):
        with app.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM cash_movements WHERE kind='cobertura_repuesto' ORDER BY id")]

    # ---- pruebas ----
    def test_full_coverage_95_of_150_creates_exactly_one_supplier_payment(self):
        order, quote, sup, _ = self.setup_quote()
        before = self.request('/api/quotes/%d' % quote, cookie=self.cookie)['body']['quote']['totals']
        cid, cov = self.authorized(quote, sup)
        self.assertEqual((cov['sale_cents'], cov['cost_cents'], cov['percent'], cov['covered_cents'], cov['margin_cents']), (15000, 9500, 100, 9500, 5500))
        self.assertEqual((cov['status'], cov['payment_status'], cov['purchase_status']), ('autorizada', 'pendiente', 'pendiente'))
        self.assertEqual(self.cash_out(), [])   # autorizar no registra ninguna salida de caja
        # Sin caja abierta no hay pago.
        closed = self.post('/api/coverage/%d' % cid, action='pay', amount='95', method='efectivo', supplier_document='001-001-000000123', request_key='pago-cobertura-000000001')
        self.assertEqual((closed['status'], closed['body']['error']), (409, cash_sessions.CLOSED_MESSAGE))
        sid = self.open_cash()
        paid = self.post('/api/coverage/%d' % cid, action='pay', amount='95,00', method='efectivo', supplier_document='001-001-000000123', request_key='pago-cobertura-000000001')
        self.assertEqual(paid['status'], 200, paid['body'])
        self.assertEqual((paid['body']['payment_status'], paid['body']['coverage']['paid_cents'], paid['body']['coverage']['pending_cents']), ('pagado', 9500, 0))
        again = self.post('/api/coverage/%d' % cid, action='pay', amount='95,00', method='efectivo', supplier_document='001-001-000000123', request_key='pago-cobertura-000000001')
        self.assertTrue(again['body']['duplicate'])   # doble clic o reintento: el mismo pago
        other = self.post('/api/coverage/%d' % cid, action='pay', amount='1', method='efectivo', supplier_document='001-001-000000124', request_key='pago-cobertura-000000002')
        self.assertEqual(other['status'], 409)        # ya pagada: no se paga dos veces
        out = self.cash_out()
        self.assertEqual(len(out), 1)
        m = out[0]
        self.assertEqual((m['direction'], m['amount_cents'], m['session_id'], m['beneficiary'], m['document']), ('egreso', 9500, sid, SUPPLIER, '001-001-000000123'))
        self.assertIn(order['code'], m['concept'])
        self.assertIn('Pantalla ficticia', m['concept'])
        view = self.request('/api/caja/sessions/%d' % sid, cookie=self.cookie)['body']
        self.assertTrue(any(r.get('kind_label') == 'Compra de repuestos — Cobertura PC-DOCTOR' or 'Cobertura PC-DOCTOR' in json.dumps(r, ensure_ascii=False) for r in view['summary']['rows']))
        # El presupuesto del cliente no cambió: sigue en $150,00 por la pantalla.
        after = self.request('/api/quotes/%d' % quote, cookie=self.cookie)['body']['quote']
        self.assertEqual(after['totals'], before)
        self.assertEqual(next(i for i in after['items'] if i['category'] == 'repuesto')['unit_cents'], 15000)
        with app.connect() as c:
            with self.assertRaises(Exception):
                c.execute('DELETE FROM part_coverage_payments')
            with self.assertRaises(Exception):
                c.execute('DELETE FROM part_coverages')
            with self.assertRaises(Exception):
                c.execute('UPDATE part_coverage_payments SET amount_cents=1')
            self.assertGreaterEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action IN ('coverage_requested','coverage_authorize','coverage_pay')").fetchone()[0], 3)

    def test_partial_coverage_and_partial_payments(self):
        _, quote, sup, _ = self.setup_quote()
        cid, cov = self.authorized(quote, sup, cost='95', mode='parcial', percent='50')
        self.assertEqual((cov['percent'], cov['covered_cents']), (50, 4750))
        self.open_cash()
        first = self.post('/api/coverage/%d' % cid, action='pay', amount='20', method='efectivo', supplier_document='FAC-1', request_key='pago-parcial-0000000001')
        self.assertEqual((first['status'], first['body'].get('payment_status')), (200, 'parcial'), first['body'])
        over = self.post('/api/coverage/%d' % cid, action='pay', amount='30', method='efectivo', supplier_document='FAC-1', request_key='pago-parcial-0000000002')
        self.assertEqual(over['status'], 409)
        self.assertIn('supera lo pendiente', over['body']['error'])
        rest = self.post('/api/coverage/%d' % cid, action='pay', amount='27,50', method='efectivo', supplier_document='FAC-1', request_key='pago-parcial-0000000003')
        self.assertEqual(rest['body']['payment_status'], 'pagado')
        self.assertEqual(sum(m['amount_cents'] for m in self.cash_out()), 4750)
        # El importe cubierto no baja de lo ya pagado.
        low = self.post('/api/coverage/%d' % cid, action='update', revision=str(rest['body']['coverage']['revision']), cost='95', mode='parcial', percent='10')
        self.assertEqual(low['status'], 409)
        bad = self.post('/api/coverage/%d' % cid, action='update', revision='0', cost='95', mode='parcial', percent='60')
        self.assertEqual(bad['status'], 409)   # revisión vieja: no pisa cambios de otra persona

    def test_technician_requests_but_never_sees_costs_or_pays(self):
        _, quote, sup, _ = self.setup_quote()
        tcookie, tcsrf = self.tech()
        tpost = lambda path, **body: self.request(path, body, cookie=tcookie, csrf=tcsrf)
        made = tpost('/api/quotes/%d/coverage' % quote, position='1', cost='95', mode='total', supplier_id=str(sup), authorize=True)
        self.assertEqual(made['status'], 201, made['body'])
        cid = made['body']['id']
        self.assertEqual(made['body']['coverage']['status'], 'solicitada')   # el técnico solicita; no autoriza aunque lo pida
        # 1.5.299: el seguimiento indica quién la solicitó (dato no financiero, visible también para el técnico).
        with app.connect() as c:
            asker = c.execute('SELECT u.name FROM part_coverages p JOIN users u ON u.id=p.requested_by WHERE p.id=?', (cid,)).fetchone()[0]
        self.assertEqual(made['body']['coverage']['requested_name'], asker)
        self.assertEqual(self.request('/api/coverage/%d' % cid, cookie=self.cookie)['body']['coverage']['requested_name'], asker)
        self.assertFalse(leaks(made['body']))
        self.assertFalse(leaks(self.request('/api/quotes/%d/coverage' % quote, cookie=tcookie)['body']))
        self.assertFalse(leaks(self.request('/api/coverage/%d' % cid, cookie=tcookie)['body']))
        self.assertEqual(tpost('/api/coverage/%d' % cid, action='authorize', revision='0')['status'], 403)
        for path in ('/api/coverage/dashboard', '/api/coverage/dashboard.csv', '/api/coverage/%d/pdf' % cid, '/api/coverage/%d/ticket' % cid):
            self.assertEqual(self.request(path, cookie=tcookie)['status'], 403, path)
        cid2, _ = cid, self.post('/api/coverage/%d' % cid, action='authorize', revision='0', authorized_name='Gerencia ficticia')
        self.assertEqual(tpost('/api/coverage/%d' % cid, action='pay', amount='95', method='efectivo', supplier_document='X-1', request_key='pago-tecnico-00000001')['status'], 403)
        # Con su propia caja abierta, el personal de caja sí registra el pago (y sigue sin ver costos).
        self.open_cash(tcookie, tcsrf)
        paid = tpost('/api/coverage/%d' % cid, action='pay', amount='95', method='efectivo', supplier_document='X-1', request_key='pago-tecnico-00000001')
        self.assertEqual(paid['status'], 200, paid['body'])
        self.assertFalse(leaks(paid['body']))
        self.assertEqual(tpost('/api/coverage/%d' % cid, action='reverse', payment_id='1', reason='Intento de reverso del técnico')['status'], 403)
        # El tipo de egreso de cobertura no se registra a mano desde la caja.
        sid = self.cash_out()[0]['session_id']
        manual = tpost('/api/caja/movement', session_id=str(sid), direction='egreso', kind='cobertura_repuesto', method='efectivo', amount='5', concept='Manual', beneficiary='Proveedor')
        self.assertEqual(manual['status'], 400)
        self.assertNotIn('cobertura_repuesto', self.request('/api/caja/state', cookie=tcookie)['body']['out_kinds'])

    def test_client_documents_never_show_cost_supplier_or_margin(self):
        order, quote, sup, _ = self.setup_quote(decide=False)
        cid, _ = self.authorized(quote, sup)
        sent = self.post('/api/quotes/%d' % quote, action='send')['body']
        self.open_cash()
        self.post('/api/coverage/%d' % cid, action='pay', amount='95', method='efectivo', supplier_document='FAC-77', request_key='pago-documentos-0000001')
        token = sent['link'].rsplit('/', 1)[1]
        page = self.request('/presupuesto/' + token)
        self.assertEqual(page['status'], 200)
        quote_json = json.dumps(self.request('/api/quotes/%d' % quote, cookie=self.cookie)['body'], ensure_ascii=False)
        portal = self.request('/api/orders/%d' % order['id'], cookie=self.cookie)
        for text in (page['body'], quote_json, json.dumps(portal['body'], ensure_ascii=False)):
            for secret in (SUPPLIER, '95,00', 'Nota interna ficticia', 'Cobertura PC-DOCTOR', 'FAC-77'):
                self.assertNotIn(secret, text if isinstance(text, str) else text.decode('utf-8', 'replace'))
        import quote_pdf
        import quotes
        with app.connect() as c:
            found = quotes.get(c, quote)
            detail = quotes.detail(c, found)
            pdf = quote_pdf.render(detail, app.order_document(c, found['order_id']), None)
        self.assertFalse(leaks({k: v for k, v in detail.items() if k not in ('events', 'notes')}), [k for k, v in detail.items() if leaks({k: v})])
        self.assertNotIn(SUPPLIER.encode('cp1252'), pdf)
        # El cliente paga su presupuesto y el recibo solo refleja el dinero recibido: $170,00 (servicio + pantalla), no la cobertura.
        self.post('/api/quotes/%d' % quote, action='decide', approved=','.join(str(i['id']) for i in detail['items']), note='Aprobó por teléfono (ficticio)')
        pay = self.post('/api/orders/%d/payments' % order['id'], amount='170,00', method='efectivo')
        self.assertEqual(pay['status'], 201, pay['body'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM order_payments WHERE order_id=?', (order['id'],)).fetchone()[0], 17000)
            moves = {r[0]: r[1] for r in c.execute("SELECT direction,SUM(amount_cents) FROM cash_movements WHERE voided_at='' GROUP BY direction")}
        self.assertEqual(moves.get('egreso'), 9500)   # el egreso del proveedor no se mezcla con el cobro al cliente

    def test_cancelled_quote_and_review(self):
        _, quote, sup, _ = self.setup_quote(decide=False)
        cid, _ = self.authorized(quote, sup)
        self.post('/api/quotes/%d' % quote, action='send')
        self.assertEqual(self.post('/api/quotes/%d' % quote, action='cancel', reason='El cliente desistió')['status'], 200)
        cov = self.request('/api/coverage/%d' % cid, cookie=self.cookie)['body']['coverage']
        self.assertEqual(cov['status'], 'cancelada')   # sin compra ni pagos: se cancela con el presupuesto
        # Con la compra registrada: queda para revisión, no se cancela sola.
        _, quote2, sup2, _ = self.setup_quote(decide=False, key='0002')
        cid2, cov2 = self.authorized(quote2, sup2)
        self.assertEqual(self.post('/api/coverage/%d' % cid2, action='purchase', supplier_document='PED-55')['status'], 200)
        self.post('/api/quotes/%d' % quote2, action='send')
        self.post('/api/quotes/%d' % quote2, action='cancel', reason='El cliente desistió')
        cov2 = self.request('/api/coverage/%d' % cid2, cookie=self.cookie)['body']['coverage']
        self.assertEqual(cov2['status'], 'autorizada')
        self.assertIn('revisa', cov2['review'])
        self.assertEqual(self.post('/api/coverage/%d' % cid2, action='cancel', reason='Se intenta cancelar con compra')['status'], 409)

    def test_draft_edits_keep_the_link(self):
        _, quote, sup, _ = self.setup_quote(decide=False)
        cid, _ = self.authorized(quote, sup)
        items = self.request('/api/quotes/%d' % quote, cookie=self.cookie)['body']['quote']['items']
        lines = [{k: i[k] for k in ('description', 'category', 'quantity', 'unit_cents', 'catalog_id')} for i in items]
        lines.insert(0, {'description': 'Limpieza ficticia', 'category': 'servicio', 'quantity': 1, 'unit_cents': 1000, 'catalog_id': None})
        self.assertEqual(self.post('/api/quotes/%d' % quote, action='save', items=lines)['status'], 200)
        cov = self.request('/api/coverage/%d' % cid, cookie=self.cookie)['body']['coverage']
        new_item = next(i for i in self.request('/api/quotes/%d' % quote, cookie=self.cookie)['body']['quote']['items'] if i['category'] == 'repuesto')
        self.assertEqual((cov['line_position'], cov['linked'], cov['review']), (new_item['position'], True, ''))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT quote_item_id FROM part_coverages WHERE id=?', (cid,)).fetchone()[0], new_item['id'])
        self.post('/api/quotes/%d' % quote, action='save', items=[l for l in lines if l['category'] != 'repuesto'])
        cov = self.request('/api/coverage/%d' % cid, cookie=self.cookie)['body']['coverage']
        self.assertEqual((cov['linked'], cov['status']), (False, 'autorizada'))
        self.assertTrue(cov['review'])

    def test_reception_creates_one_inventory_entry_and_states_stay_separate(self):
        _, quote, sup, item = self.setup_quote()
        cid, _ = self.authorized(quote, sup)
        self.assertEqual(self.post('/api/coverage/%d' % cid, action='receive')['status'], 409)   # sin compra registrada
        self.post('/api/coverage/%d' % cid, action='purchase', supplier_document='FAC-900')
        first = self.post('/api/coverage/%d' % cid, action='receive')
        self.assertEqual(first['status'], 200, first['body'])
        again = self.post('/api/coverage/%d' % cid, action='receive')
        self.assertEqual(again['body']['inventory_movement_id'], first['body']['inventory_movement_id'])
        with app.connect() as c:
            moves = c.execute("SELECT direction,reason,quantity,unit_cost_cents,reference_kind,reference_id FROM inventory_movements WHERE item_id=?", (item,)).fetchall()
        self.assertEqual([tuple(m) for m in moves], [(1, 'compra', 1, 9500, 'cobertura', cid)])
        cov = first['body']['coverage']
        self.assertEqual((cov['purchase_status'], cov['payment_status']), ('recibido', 'pendiente'))   # recibido no es pagado
        self.assertEqual(self.cash_out(), [])

    def test_reversal_is_admin_only_traceable_and_compensates_closed_sessions(self):
        _, quote, sup, _ = self.setup_quote()
        cid, _ = self.authorized(quote, sup)
        sid = self.open_cash()
        paid = self.post('/api/coverage/%d' % cid, action='pay', amount='95', method='efectivo', supplier_document='FAC-1', request_key='pago-reverso-000000001')
        pid = paid['body']['payment_id']
        self.assertEqual(self.post('/api/coverage/%d' % cid, action='reverse', payment_id=str(pid), reason='corto')['status'], 400)
        done = self.post('/api/coverage/%d' % cid, action='reverse', payment_id=str(pid), reason='Factura del proveedor anulada')
        self.assertEqual(done['status'], 200, done['body'])
        self.assertEqual(done['body']['coverage']['payment_status'], 'pendiente')
        with app.connect() as c:
            self.assertTrue(c.execute('SELECT voided_at FROM cash_movements WHERE id=?', (paid['body']['cash_movement_id'],)).fetchone()[0])
            self.assertEqual(c.execute('SELECT status FROM part_coverage_payments WHERE id=?', (pid,)).fetchone()[0], 'revertido')
        self.assertEqual(self.post('/api/coverage/%d' % cid, action='reverse', payment_id=str(pid), reason='Factura del proveedor anulada')['status'], 409)
        # Pago en una sesión ya cerrada: ingreso compensatorio en la caja abierta (nada se borra).
        second = self.post('/api/coverage/%d' % cid, action='pay', amount='95', method='efectivo', supplier_document='FAC-2', request_key='pago-reverso-000000002')
        with app.connect() as c:
            c.execute("UPDATE cash_sessions SET status='cerrada' WHERE id=?", (sid,))
            c.commit()
        no_cash = self.post('/api/coverage/%d' % cid, action='reverse', payment_id=str(second['body']['payment_id']), reason='Devolución del proveedor')
        self.assertEqual(no_cash['status'], 409)
        sid2 = self.open_cash()
        comp = self.post('/api/coverage/%d' % cid, action='reverse', payment_id=str(second['body']['payment_id']), reason='Devolución del proveedor')
        self.assertEqual(comp['status'], 200, comp['body'])
        with app.connect() as c:
            m = c.execute('SELECT session_id,direction,amount_cents,voided_at FROM cash_movements WHERE id=?', (comp['body']['compensating_movement_id'],)).fetchone()
            self.assertEqual(tuple(m), (sid2, 'ingreso', 9500, ''))
            self.assertEqual(c.execute('SELECT voided_at FROM cash_movements WHERE id=?', (second['body']['cash_movement_id'],)).fetchone()[0], '')
        events = [e['event'] for e in self.request('/api/coverage/%d' % cid, cookie=self.cookie)['body']['coverage']['events']]
        self.assertEqual(events.count('pago_revertido'), 2)

    def test_dashboard_csv_and_internal_report(self):
        _, quote, sup, _ = self.setup_quote()
        cid, _ = self.authorized(quote, sup)
        self.open_cash()
        self.post('/api/coverage/%d' % cid, action='pay', amount='40', method='efectivo', supplier_document='=FAC-1', request_key='pago-panel-0000000001')
        board = self.request('/api/coverage/dashboard', cookie=self.cookie)['body']
        t = board['totals']
        self.assertEqual((t['covered'], t['paid'], t['pending'], t['authorized_unpaid'], t['margin'], t['monthly_paid']), (9500, 4000, 5500, 1, 5500, 4000))
        self.assertEqual(len(self.request('/api/coverage/dashboard?supplier=%d' % sup, cookie=self.cookie)['body']['rows']), 1)
        self.assertEqual(len(self.request('/api/coverage/dashboard?status=cancelada', cookie=self.cookie)['body']['rows']), 0)
        self.assertEqual(self.request('/api/coverage/dashboard?from=2026-12-01&to=2026-01-01', cookie=self.cookie)['status'], 400)
        csv_text = self.request('/api/coverage/dashboard.csv', cookie=self.cookie)['body']
        csv_text = csv_text.decode('utf-8') if isinstance(csv_text, bytes) else csv_text
        self.assertIn('Margen bruto estimado', csv_text)
        self.assertIn('95.00', csv_text)
        for path in ('/api/coverage/%d/pdf' % cid, '/api/coverage/%d/ticket' % cid):
            pdf = self.request(path, cookie=self.cookie)
            self.assertEqual(pdf['status'], 200, path)
            self.assertTrue(pdf['body'][:4] == b'%PDF')
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action IN ('coverage_exported','coverage_report_viewed')").fetchone()[0], 3)

    def test_only_spare_part_lines_and_one_live_coverage_per_line(self):
        _, quote, sup, _ = self.setup_quote()
        self.assertEqual(self.post('/api/quotes/%d/coverage' % quote, position='0', cost='10', mode='total')['status'], 409)   # servicio
        self.assertEqual(self.post('/api/quotes/%d/coverage' % quote, position='9', cost='10', mode='total')['status'], 404)
        self.assertEqual(self.post('/api/quotes/%d/coverage' % quote, position='1', cost='0', mode='total')['status'], 400)
        self.assertEqual(self.post('/api/quotes/%d/coverage' % quote, position='1', cost='95', mode='parcial', percent='150')['status'], 400)
        self.authorized(quote, sup)
        self.assertEqual(self.post('/api/quotes/%d/coverage' % quote, position='1', cost='95', mode='total')['status'], 409)
        self.assertEqual(self.request('/api/quotes/%d/coverage' % quote)['status'], 401)


if __name__ == '__main__':
    unittest.main()
