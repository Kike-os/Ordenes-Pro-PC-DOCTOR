"""Fase 2 (datos ficticios, base temporal, sin SRI ni correo): caja por sesiones con arqueo por denominaciones, cierre inmutable y fondo
del siguiente turno; pagos y saldo (completo, abonos, mixto, transferencia con cuenta, duplicados, entrega con saldo); cuentas bancarias y
transferencias con verificación; vouchers; proformas con aprobación del cliente, anticipos, conversión a factura y notas de crédito."""
import json
import re
import unittest
from urllib.parse import urlencode

import test_app
import test_invoicing
import app

ONE = 'Única (la tabla no distingue categoría)'
# Conteo del ejemplo de la especificación: 15 × $20 + 8 × $10 + 12 × $0,25 + 5 × moneda de $1 = $388,00.
EXAMPLE = {('billete', 2000): 15, ('billete', 1000): 8, ('moneda', 25): 12, ('moneda', 100): 5}


class Fase2Tests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure

    # ---- ayudas ----
    def counts(self, cookie, spec):
        rows = self.request('/api/caja/state', cookie=cookie)['body']['denominations']
        ids = {(d['kind'], d['value_cents']): d['id'] for d in rows}
        return json.dumps([{'id': ids[k], 'qty': str(v)} for k, v in spec.items()])

    def tech(self):
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('cajero','caj@example.invalid','Cajero de prueba',?,'tecnico',1)", (self.hash,))
            c.commit()
        cookie = self.request('/api/login', {'login': 'cajero', 'password': 'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        return cookie, self.request('/api/me', cookie=cookie)['body']['user']['csrf']

    def account(self, post, bank='Banco Ficticio', number='0026533754', verified='1'):
        r = post('/api/bank-accounts', action='save', bank=bank, account_type='ahorros', number=number, holder='TITULAR FICTICIO', holder_id='0100000017', verified=verified)
        self.assertEqual(r['status'], 200, r['body'])
        return next(a['id'] for a in r['body']['rows'] if a['number'] == number)

    # ---- Caja ----
    def test_cash_cycle_open_movements_count_close_and_next_shift(self):
        cookie, csrf, post, order = self.paid_order(50000, pay=False)
        state = self.request('/api/caja/state', cookie=cookie)['body']
        self.assertEqual([d['value_cents'] for d in state['denominations']], [1, 5, 10, 25, 50, 100, 100, 200, 500, 1000, 2000, 5000, 10000])
        reg = state['registers'][0]['id']
        self.assertIsNone(state['registers'][0]['session'])  # caja cerrada: la interfaz muestra «Abrir Caja»
        bad = post('/api/caja/open', register_id=str(reg), shift='Mañana', counts=json.dumps([{'id': state['denominations'][0]['id'], 'qty': '-3'}]))
        self.assertEqual(bad['status'], 400)
        frac = post('/api/caja/open', register_id=str(reg), shift='Mañana', counts=json.dumps([{'id': state['denominations'][0]['id'], 'qty': '1.5'}]))
        self.assertEqual(frac['status'], 400)
        opened = post('/api/caja/open', register_id=str(reg), shift='Mañana', counts=self.counts(cookie, EXAMPLE), request_key='apertura-de-prueba-0001')
        self.assertEqual(opened['status'], 200, opened['body'])
        sid = opened['body']['session_id']
        self.assertEqual(post('/api/caja/open', register_id=str(reg), shift='Mañana', counts=self.counts(cookie, EXAMPLE), request_key='apertura-de-prueba-0001')['body']['session_id'], sid)  # doble clic
        again = post('/api/caja/open', register_id=str(reg), shift='Tarde', counts='[]')
        self.assertEqual((again['status'], again['body']['session_id']), (409, sid))  # no se abre dos veces la misma caja
        view = self.request('/api/caja/sessions/%d' % sid, cookie=cookie)['body']
        self.assertEqual((view['session']['status'], view['session']['opening_cents'], view['counts']['apertura']['total_cents'], view['session']['code']), ('abierta', 38800, 38800, 'CJ-%06d' % sid))
        # Cobros de la orden: efectivo y un pago mixto (efectivo + transferencia); se vinculan a la caja abierta.
        acc = self.account(post)
        self.assertEqual(post('/api/orders/%d/payments' % order['id'], amount='50,00', method='efectivo', request_key='pago-efectivo-000001')['status'], 201)
        mixed = post('/api/orders/%d/payments' % order['id'], amount='50,00', lines=json.dumps([{'method': 'efectivo', 'amount': '30,00'}, {'method': 'transferencia', 'amount': '20,00', 'bank_account_id': str(acc), 'reference': 'TRX-998877'}]), request_key='pago-mixto-0000001')
        self.assertEqual(mixed['status'], 201, mixed['body'])
        self.assertEqual(len(mixed['body']['ids']), 2);self.assertTrue(mixed['body']['operation_id'].startswith('OP-'))
        # Movimientos manuales con trazabilidad.
        self.assertEqual(post('/api/caja/movement', session_id=str(sid), direction='ingreso', kind='otro_ingreso', method='efectivo', amount='10', concept='Venta de un cable ficticio', request_key='ingreso-prueba-00001')['status'], 200)
        self.assertEqual(post('/api/caja/movement', session_id=str(sid), direction='egreso', kind='gasto_menor', method='efectivo', amount='5', concept='Gasto ficticio', beneficiary='')['status'], 400)  # sin beneficiario
        self.assertEqual(post('/api/caja/movement', session_id=str(sid), direction='egreso', kind='gasto_menor', method='efectivo', amount='5', concept='Gasto ficticio', beneficiary='Tienda ficticia')['status'], 200)
        self.assertEqual(post('/api/caja/movement', session_id=str(sid), direction='egreso', kind='gasto_menor', method='efectivo', amount='9999', concept='Gasto imposible', beneficiary='Tienda ficticia')['status'], 409)
        s = self.request('/api/caja/sessions/%d' % sid, cookie=cookie)['body']['summary']
        self.assertEqual(s['expected_cash_cents'], 38800 + 5000 + 3000 + 1000 - 500)  # efectivo esperado = fondo + entradas − salidas (solo efectivo)
        self.assertEqual((s['by_method']['transferencia']['in_cents'], [p['label'] for p in s['pending']]), (2000, ['Cobro de orden de servicio']))  # la transferencia no es efectivo y está por verificar
        # Arqueo: borrador y vuelta a la caja abierta; durante el arqueo no se registran movimientos.
        self.assertEqual(post('/api/caja/count', session_id=str(sid), counts=self.counts(cookie, {('billete', 2000): 20}))['status'], 200)
        self.assertEqual(self.request('/api/caja/sessions/%d' % sid, cookie=cookie)['body']['session']['status'], 'arqueo')
        self.assertEqual(post('/api/caja/movement', session_id=str(sid), direction='ingreso', kind='otro_ingreso', method='efectivo', amount='1', concept='Durante el arqueo')['status'], 409)
        post('/api/caja/count', session_id=str(sid), action='resume')
        self.assertEqual(self.request('/api/caja/sessions/%d' % sid, cookie=cookie)['body']['session']['status'], 'abierta')
        # Cierre con sobrante de $1,00: exige explicación y confirmación; reserva $100 para el siguiente turno.
        counted = self.counts(cookie, {('billete', 2000): 20, ('billete', 1000): 7, ('moneda', 100): 4})  # $400 + $70 + $4 = $474 → esperado $473
        base = dict(session_id=str(sid), counts=counted, confirm='1', confirmed_name='Persona de prueba', reserved='100,00', delivered_to='Administración ficticia')
        self.assertEqual(post('/api/caja/close', **{**base, 'difference_reason': ''})['status'], 400)
        self.assertEqual(post('/api/caja/close', **{**base, 'reserved': '500,00', 'difference_reason': 'Sobrante sin explicar aún'})['status'], 400)  # no reserva más de lo contado
        self.assertEqual(post('/api/caja/close', **{**base, 'confirm': '', 'difference_reason': 'Sobrante sin explicar aún'})['status'], 400)
        closed = post('/api/caja/close', **{**base, 'difference_reason': 'Un cliente dejó un dólar de más (ficticio)'})
        self.assertEqual((closed['status'], closed['body']['status'], closed['body']['difference_cents']), (200, 'revision', 100), closed['body'])
        self.assertEqual(post('/api/caja/close', **{**base, 'difference_reason': 'Segundo cierre'})['status'], 409)  # sin cierres duplicados
        self.assertEqual(post('/api/caja/movement', session_id=str(sid), direction='ingreso', kind='otro_ingreso', method='efectivo', amount='1', concept='Tras el cierre')['status'], 409)
        with app.connect() as c:
            for sql in ('UPDATE cash_session_closings SET counted_cash_cents=1', 'DELETE FROM cash_session_closings', 'DELETE FROM cash_movements', "UPDATE cash_movements SET amount_cents=1"):
                with self.assertRaises(Exception):
                    c.execute(sql)
        self.assertEqual(post('/api/caja/review', session_id=str(sid), review_note='Revisado con el cajero (ficticio)')['status'], 200)
        self.assertEqual(self.request('/api/caja/sessions/%d' % sid, cookie=cookie)['body']['session']['status'], 'cerrada_diferencia')
        self.assertEqual(post('/api/caja/adjust', session_id=str(sid), amount='1,00', sign='-', reason='Se devolvió el dólar al cliente (ficticio)')['status'], 200)
        # Siguiente turno: reconoce el fondo reservado y confirma su recepción.
        need = post('/api/caja/open', register_id=str(reg), shift='Tarde', counts=self.counts(cookie, {('billete', 2000): 5}))
        self.assertEqual((need['status'], 'fund_confirm' in need['body']['fields']), (400, True))
        nxt = post('/api/caja/open', register_id=str(reg), shift='Tarde', counts=self.counts(cookie, {('billete', 2000): 5}), fund_confirm='1', fund_received_by='Cajero de la tarde')
        self.assertEqual(nxt['status'], 200, nxt['body'])
        v2 = self.request('/api/caja/sessions/%d' % nxt['body']['session_id'], cookie=cookie)['body']
        self.assertEqual((v2['session']['fund_from_session_id'], v2['session']['fund_expected_cents'], v2['session']['opening_cents']), (sid, 10000, 10000))
        # Caja cuadrada en el segundo turno.
        done = post('/api/caja/close', session_id=str(nxt['body']['session_id']), counts=self.counts(cookie, {('billete', 2000): 5}), confirm='1', confirmed_name='Cajero de la tarde', delivered_to='Gerencia ficticia')
        self.assertEqual((done['body']['status'], done['body']['difference_cents']), ('cerrada', 0))
        # Reportes A4 y térmico, historial con filtros.
        for fmt in ('', '?formato=termico'):
            pdf = self.request('/api/caja/sessions/%d/report.pdf%s' % (sid, fmt), cookie=cookie)
            self.assertEqual(pdf['status'], 200);self.assertTrue(pdf['body'].startswith(b'%PDF'))
        hist = self.request('/api/caja/history?difference=sobrante', cookie=cookie)['body']['rows']
        self.assertEqual([r['id'] for r in hist], [sid])
        self.assertEqual([r['difference_type'] for r in self.request('/api/caja/history', cookie=cookie)['body']['rows']], ['cuadrado', 'sobrante'])

    def test_cash_permissions_shortage_void_and_incidents(self):
        cookie, csrf, post, order = self.paid_order(10000, pay=False)
        tcookie, tcsrf = self.tech()
        tpost = lambda path, **body: self.request(path, body, cookie=tcookie, csrf=tcsrf)
        reg = self.request('/api/caja/state', cookie=cookie)['body']['registers'][0]['id']
        # Una caja abierta sin operaciones se anula con motivo (y marca el inicio del uso de las sesiones).
        empty = post('/api/caja/open', register_id=str(reg), shift='Noche', counts='[]')['body']['session_id']
        self.assertEqual(post('/api/caja/void', session_id=str(empty), reason='Abierta por error (ficticio)')['status'], 200)
        self.assertEqual(self.request('/api/caja/sessions/%d' % empty, cookie=cookie)['body']['session']['status'], 'anulada')
        # Desde entonces, un cobro registrado sin caja abierta queda como incidencia para asignarlo.
        self.assertEqual(post('/api/orders/%d/payments' % order['id'], amount='10', method='efectivo')['status'], 201)
        opened = tpost('/api/caja/open', register_id=str(reg), shift='Jornada completa', counts=self.counts(tcookie, {('billete', 2000): 1}))
        self.assertEqual(opened['status'], 200, opened['body'])
        sid = opened['body']['session_id']
        incidents = self.request('/api/caja/state', cookie=cookie)['body']['incidents']
        self.assertEqual(len(incidents), 1)
        self.assertEqual(tpost('/api/caja/assign', payment_id=str(incidents[0]['id']), session_id=str(sid))['status'], 403)
        self.assertEqual(post('/api/caja/assign', payment_id=str(incidents[0]['id']), session_id=str(sid))['status'], 200)
        # El cajero no registra retiros (requieren administración) ni anula movimientos.
        self.assertEqual(tpost('/api/caja/movement', session_id=str(sid), direction='egreso', kind='retiro', method='efectivo', amount='1', concept='Retiro', beneficiary='Gerencia ficticia')['status'], 403)
        self.assertEqual(post('/api/caja/movement', session_id=str(sid), direction='egreso', kind='retiro', method='efectivo', amount='1', concept='Retiro autorizado', beneficiary='Gerencia ficticia')['status'], 200)
        mov = self.request('/api/caja/sessions/%d' % sid, cookie=cookie)['body']['summary']['rows'][-1]
        self.assertEqual(tpost('/api/caja/movement/void', movement_id=str(mov['source_id']), reason='Error de digitación ficticio')['status'], 403)
        self.assertEqual(post('/api/caja/void', session_id=str(sid), reason='Se intenta anular con movimientos')['status'], 409)
        # Faltante: contado $20 − esperado ($20 + $10 − $1 = $29) = −$9.
        closed = tpost('/api/caja/close', session_id=str(sid), counts=self.counts(tcookie, {('billete', 2000): 1}), confirm='1', confirmed_name='Cajero de prueba', difference_reason='Faltante en revisión (ficticio)', delivered_to='Gerencia ficticia')
        self.assertEqual((closed['body']['status'], closed['body']['difference_cents']), ('revision', -900), closed['body'])
        self.assertEqual(tpost('/api/caja/review', session_id=str(sid), review_note='Intento del cajero')['status'], 403)
        self.assertEqual([r['id'] for r in self.request('/api/caja/history?difference=faltante', cookie=tcookie)['body']['rows']], [sid])

    # ---- Pagos y saldo ----
    def test_payments_full_partial_mixed_duplicates_void_and_delivery(self):
        cookie, csrf, post, order = self.paid_order(14250, pay=False)
        oid = order['id']
        acc = self.account(post)
        r = post('/api/orders/%d/payments' % oid, amount='50,00', method='efectivo', request_key='abono-50-00000001')
        self.assertEqual((r['status'], r['body']['balance_cents'], r['body']['state']), (201, 9250, 'parcial'))
        dup = post('/api/orders/%d/payments' % oid, amount='50,00', method='efectivo', request_key='abono-50-00000001')
        self.assertTrue(dup['body'].get('duplicate'))  # doble clic: no se registra dos veces
        self.assertEqual(post('/api/orders/%d/payments' % oid, amount='0', method='efectivo')['status'], 400)
        self.assertEqual(post('/api/orders/%d/payments' % oid, amount='-5', method='efectivo')['status'], 400)
        self.assertEqual(post('/api/orders/%d/payments' % oid, amount='100,00', method='efectivo')['status'], 400)  # supera el saldo
        self.assertEqual(post('/api/orders/%d/payments' % oid, amount='10', method='transferencia')['status'], 400)  # sin cuenta ni referencia
        bad = post('/api/orders/%d/payments' % oid, amount='92,50', lines=json.dumps([{'method': 'efectivo', 'amount': '40'}, {'method': 'debito', 'amount': '40'}]))
        self.assertEqual((bad['status'], 'lines' in bad['body']['fields']), (400, True))  # la suma no coincide
        mixed = post('/api/orders/%d/payments' % oid, amount='92,50', lines=json.dumps([{'method': 'transferencia', 'amount': '42,50', 'bank_account_id': str(acc), 'reference': 'DEP-000123'},
                                                                                       {'method': 'debito', 'amount': '50,00'}]), request_key='mixto-final-000001', paid_at='2026-10-27T09:30')
        self.assertEqual((mixed['status'], mixed['body']['balance_cents'], mixed['body']['state']), (201, 0, 'pagado'), mixed['body'])
        detail = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']
        self.assertEqual((detail['statuses']['payment']['label'], detail['statuses']['payment']['percent'], detail['statuses']['billing']['code']), ('Pagada', 100, 'sin_factura'))
        rows = detail['payments']
        self.assertEqual([r['method_label'] for r in rows], ['Efectivo', 'Transferencia', 'Tarjeta de débito'])
        self.assertEqual((rows[1]['bank'], rows[1]['reference'], rows[1]['transfer_status']), ('Banco Ficticio · 0026533754', 'DEP-000123', 'pendiente'))
        self.assertEqual(post('/api/orders/%d/payments' % oid, amount='1', method='transferencia', bank_account_id=str(acc), reference='DEP-000123')['status'], 400)  # misma referencia
        # Anulación con motivo: el historial se conserva y vuelve el saldo.
        self.assertEqual(post('/api/orders/%d/payments/void' % oid, payment_id=str(rows[0]['id']), reason='Pago registrado por error (ficticio)')['status'], 200)
        self.assertEqual(self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']['money']['balance_cents'], 5000)
        # Una factura se genera aunque haya saldo pendiente (queda como venta a crédito).
        draft = post('/api/invoicing/draft', kind='orden', id=str(oid))
        self.assertEqual(draft['status'], 200, draft['body'])
        self.assertEqual([(p['method'], p['amount_cents']) for p in draft['body']['payments']], [('tarjeta', 5000), ('transferencia', 4250), ('credito', 5000)])
        self.assertEqual((draft['body']['balance_cents'], [x['reference'] for x in draft['body']['receipts']]), (5000, ['DEP-000123']))
        # Entrega con saldo: bloqueada salvo autorización administrativa expresa con motivo.
        # Entrega con saldo: bloqueada; solo administración la autoriza expresamente con motivo, y queda en el historial.
        blocked = post('/api/order-status', id=str(oid), status='entregado')
        self.assertEqual((blocked['status'], blocked['body']['balance'], blocked['body']['can_authorize']), (409, True, True))
        self.assertEqual(post('/api/order-status', id=str(oid), status='entregado', authorize_balance='1', balance_reason='corto')['status'], 409)
        self.assertEqual(post('/api/order-status', id=str(oid), status='entregado', authorize_balance='1', balance_reason='Cliente frecuente, paga el viernes (ficticio)')['status'], 200)
        with app.connect() as c:
            self.assertTrue(c.execute("SELECT 1 FROM audit WHERE action='delivery_balance_authorized' AND entity_id=?", (oid,)).fetchone())

    # ---- Cuentas bancarias y transferencias ----
    def test_bank_accounts_verification_transfers_and_invoice_account(self):
        cookie, csrf, post, order = self.paid_order(10000)
        accounts = [('Banco Guayaquil', '0026533754', 'ahorros'), ('Banco Guayaquil', '0045943119', 'corriente'), ('Banco Pichincha', '2211992424', 'ahorros'),
                    ('Banco del Pacífico', '8383944', 'corriente'), ('Produbanco', '12726007906', 'ahorros')]
        for bank, number, kind in accounts:
            r = post('/api/bank-accounts', action='save', bank=bank, account_type=kind, number=number, holder='TITULAR FICTICIO', holder_id='0100000017', holder_ruc='', email='pagos@example.invalid', verified='0')
            self.assertEqual(r['status'], 200, r['body'])
        rows = self.request('/api/bank-accounts', cookie=cookie)['body']['rows']
        self.assertEqual(sorted(a['number'] for a in rows), sorted(n for _, n, _ in accounts))  # ceros iniciales intactos
        self.assertTrue(all(not a['verified'] for a in rows))
        self.assertEqual(post('/api/bank-accounts', action='save', bank='Banco Guayaquil', account_type='ahorros', number='0026533754', holder='X Y Z', holder_id='0100000017')['status'], 409)
        first = next(a for a in rows if a['number'] == '0026533754')
        self.assertEqual(self.request('/api/bank/overview', cookie=cookie)['body']['indicators']['unverified_accounts'], 5)
        self.configure(post)
        draft = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
        self.assertEqual(post('/api/invoicing/%d' % draft['id'], action='bank', bank_account_id=str(first['id']))['status'], 409)  # sin verificar no va en documentos
        self.assertEqual(post('/api/bank-accounts', action='verify', id=str(first['id']))['status'], 200)
        self.assertEqual(post('/api/invoicing/%d' % draft['id'], action='bank', bank_account_id=str(first['id']))['status'], 200)
        t = post('/api/bank/transfers', method='deposito', bank_account_id=str(first['id']), reference='DEP-555', amount='25,00', source_kind='orden', source_id=str(order['id']), payer='Cliente ficticio')
        self.assertEqual(t['status'], 200, t['body'])
        self.assertEqual(post('/api/bank/transfers', method='deposito', bank_account_id=str(first['id']), reference='dep-555', amount='25,00')['status'], 409)
        tid = t['body']['id']
        self.assertEqual(post('/api/bank/transfers/%d' % tid, action='conciliar')['status'], 409)  # primero se confirma
        self.assertEqual(post('/api/bank/transfers/%d' % tid, action='confirmar')['status'], 200)
        self.assertEqual(post('/api/bank/transfers/%d' % tid, action='conciliar')['status'], 200)
        ov = self.request('/api/bank/overview?from=2000-01-01', cookie=cookie)['body']['indicators']
        self.assertEqual((ov['accounts'], ov['confirmed'], ov['by_bank'][0]['cents']), (5, 1, 2500))
        rows = self.request('/api/bank/transfers?q=DEP-555', cookie=cookie)['body']['rows']
        self.assertEqual((len(rows), rows[0]['status'], rows[0]['account']), (1, 'conciliado', 'Ahorros · •••• 3754'))
        for ext in ('xlsx', 'pdf'):
            self.assertEqual(self.request('/api/bank/transfers.' + ext, cookie=cookie)['status'], 200)

    # ---- Vouchers de tarjeta ----
    def test_card_vouchers_duplicates_corrections_and_settlement(self):
        cookie, csrf, post, order = self.paid_order(20000, pay=False)
        # Como en producción: el 9 % lo asume la empresa (es su costo, no se suma al cliente).
        self.assertEqual(post('/api/payments/surcharge', percent='9', payer='empresa', methods='credito_corriente,diferido_con_intereses,diferido_sin_intereses', active='1', valid_from='2026-01-01', note='Lo asume la empresa (ficticio)')['status'], 200)
        pay = post('/api/orders/%d/payments' % order['id'], amount='200', method='credito')
        pid = pay['body']['id']
        base = dict(payment_id=str(pid), issuer_bank='Banco Guayaquil', brand='Visa', category=ONE, tx_type='diferido_con_intereses', months='3', lot='000123', reference='456789', approval_code='A1B2C3', last4='4242')
        self.assertEqual(post('/api/vouchers', **{**base, 'last4': '4242424242424242'})['status'], 400)  # nunca el número completo
        v = post('/api/vouchers', **base)
        self.assertEqual(v['status'], 200, v['body'])
        self.assertEqual(post('/api/vouchers', **base)['status'], 409)  # el pago ya tiene voucher
        loose = dict(base, payment_id='', amount='50')
        dup = post('/api/vouchers', **loose)
        self.assertEqual((dup['status'], dup['body'].get('duplicate')), (409, 'VC-%06d' % v['body']['id']))
        self.assertEqual(post('/api/vouchers', **loose, confirm_duplicate='1')['status'], 200)
        vid = v['body']['id']
        self.assertEqual(post('/api/vouchers/%d' % vid, action='corregir', lot='000124', reason='Lote mal digitado (ficticio)')['status'], 200)
        events = self.request('/api/vouchers/%d/events' % vid, cookie=cookie)['body']['events']
        self.assertIn('lot «000123» → «000124»', events[0]['detail'])
        settle = post('/api/vouchers/%d' % vid, action='liquidar', commission='4,50', commission_tax='0,68', withholding='0')
        self.assertEqual(settle['status'], 200)
        row = next(r for r in self.request('/api/vouchers', cookie=cookie)['body']['rows'] if r['id'] == vid)
        self.assertEqual((row['status'], row['net_cents'], row['last4'], row['expected_commission_cents']), ('liquidada', 20000 - 450 - 68, '4242', 1800))  # 9 % que asume la empresa
        with app.connect() as c:
            self.assertFalse(any(re.search(r'\d{12,}', str(v)) for v in c.execute('SELECT * FROM card_vouchers').fetchone()))

    # ---- Proformas, aprobación del cliente, anticipos, factura y notas de crédito ----
    def test_proforma_approval_conversion_and_credit_notes(self):
        cookie, csrf, post, order = self.paid_order(1000)
        acc = self.account(post)
        items = [{'kind': 'servicio', 'description': 'Mantenimiento ficticio', 'quantity': '1', 'unit_price': '100,00'},
                 {'kind': 'producto', 'description': 'Memoria ficticia', 'quantity': '2', 'unit_price': '50,00', 'discount': '20,00'}]
        client = dict(client_name='Cliente Ficticio', client_identification='0100000017', client_email='cliente@example.invalid')
        need = post('/api/proformas', items=json.dumps(items), **client)
        self.assertEqual(need['status'], 400)  # 20 % de descuento exige autorización con motivo
        items[1]['authorization'] = 'Promoción ficticia aprobada'
        created = post('/api/proformas', items=json.dumps(items), payment_method='diferido_con_intereses', card_bank='Banco Guayaquil', card_brand='Visa', card_category=ONE, card_months='3',
                       request_key='proforma-prueba-0001', **client)
        self.assertEqual(created['status'], 200, created['body'])
        p = created['body']
        self.assertEqual((p['proforma']['status'], p['totals']['total_cents'], p['proforma']['code']), ('borrador', 18000, 'PF-%06d' % p['id']))
        # Recargo inicial (9 % a cargo del cliente en una base nueva): $180 + $16,20 = $196,20; interés 2,68 % = $5,26.
        self.assertEqual((p['proforma']['financing']['surcharge_cents'], p['proforma']['financing']['interest_cents'], p['proforma']['financing']['total_cents']), (1620, 526, 20146))
        sent = post('/api/proformas/%d' % p['id'], action='send')
        self.assertEqual(sent['status'], 200, sent['body'])
        token = sent['body']['link'].rsplit('/', 1)[1]
        page = self.request('/proforma/' + token)
        self.assertIn('Comprueba tu identidad', page['body'])
        wrong = self.form('/proforma/' + token, {'last4': '9999'})
        self.assertIn('no coinciden', wrong['body'])
        step = self.form('/proforma/' + token, {'last4': '0017'})['body']
        key = re.search(r'name="passkey" value="([0-9a-f]+)"', step)[1]
        ids = [i['id'] for i in self.request('/api/proformas/%d' % p['id'], cookie=cookie)['body']['items']]
        self.assertEqual(self.request('/api/proformas/%d' % p['id'], cookie=cookie)['body']['proforma']['status'], 'vista')
        sign = json.dumps([[[10, 10], [100, 60], [200, 120], [300, 80], [400, 60], [500, 140], [600, 200], [700, 150], [800, 90], [900, 40]]])
        decided = self.form('/proforma/' + token, {'passkey': key, 'decision_%d' % ids[0]: 'aprobado', 'decision_%d' % ids[1]: 'aprobado', 'name': 'Cliente Ficticio', 'accept': 'on', 'signature': sign, 'action': 'decide'})
        self.assertIn('aprobación', decided['body'])
        d = self.request('/api/proformas/%d' % p['id'], cookie=cookie)['body']
        self.assertEqual((d['proforma']['status'], d['acceptance']['decision'], len(d['acceptance']['evidence_hash'])), ('aprobada', 'aprobada', 64))
        self.assertEqual(self.form('/proforma/' + token, {'last4': '0017'})['status'], 200)  # el enlace ya no admite otra decisión
        # Anticipo por transferencia (pendiente de verificar) y conversión idempotente a factura con el anticipo aplicado.
        self.assertEqual(post('/api/proformas/%d' % p['id'], action='advance', method='transferencia', amount='500', bank_account_id=str(acc), reference='TR-1')['status'], 400)  # supera el saldo
        adv = post('/api/proformas/%d' % p['id'], action='advance', method='transferencia', amount='80', bank_account_id=str(acc), reference='TR-PROFORMA-1', request_key='anticipo-prueba-0001')
        self.assertEqual(adv['status'], 200, adv['body'])
        self.assertEqual((adv['body']['paid_cents'], adv['body']['balance_cents']), (8000, 10000))
        self.configure(post)
        inv = post('/api/proformas/%d' % p['id'], action='convert')
        self.assertEqual(inv['status'], 200, inv['body'])
        again = post('/api/proformas/%d' % p['id'], action='convert')
        self.assertEqual(again['body']['invoice_id'], inv['body']['invoice_id'])  # sin facturas duplicadas
        invoice = inv['body']['invoice']
        self.assertEqual((invoice['total_cents'], invoice['source_kind'], invoice['proforma_code'], invoice['financing']['months']), (18000, 'proforma', p['proforma']['code'], 3))
        self.assertEqual([(x['method'], x['amount_cents']) for x in inv['body']['payments']], [('transferencia', 8000), ('credito', 10000)])
        emitted = post('/api/invoicing/%d' % invoice['id'], action='emit', confirm='1')
        self.assertEqual(emitted['status'], 200, emitted['body'])
        # Nota de crédito parcial y total; nunca más de lo facturado.
        items_inv = self.request('/api/credit-notes/invoice/%d' % invoice['id'], cookie=cookie)['body']['items']
        part = post('/api/credit-notes', invoice_id=str(invoice['id']), scope='parcial', reason='Devolución de una memoria (ficticia)', lines=json.dumps([{'item_id': items_inv[1]['id'], 'quantity': 1}]))
        self.assertEqual(part['status'], 200, part['body'])
        self.assertEqual(part['body']['note']['total_cents'], 4000)
        self.assertEqual(post('/api/credit-notes', invoice_id=str(invoice['id']), scope='parcial', reason='Exceso', lines=json.dumps([{'item_id': items_inv[1]['id'], 'quantity': 2}]))['status'], 400)
        total = post('/api/credit-notes', invoice_id=str(invoice['id']), scope='total', reason='Anulación del resto (ficticia)')
        self.assertEqual((total['status'], total['body']['note']['total_cents']), (200, 14000))
        self.assertEqual(post('/api/credit-notes', invoice_id=str(invoice['id']), scope='total', reason='Otra vez')['status'], 409)
        xml = self.request('/api/credit-notes/%d/comprobante.xml' % total['body']['id'], cookie=cookie)['body'].decode()
        self.assertIn('<codDoc>04</codDoc>', xml);self.assertIn('<valorModificacion>140.00</valorModificacion>', xml);self.assertIn('<ambiente>1</ambiente>', xml)
        self.assertEqual(self.request('/api/proformas/%d.pdf' % p['id'], cookie=cookie)['body'][:4], b'%PDF')

    def test_direct_invoice_versions_and_cancel(self):
        cookie, csrf, post, order = self.paid_order(1000)
        direct = post('/api/proformas', origin='directa', finalize='1', items=json.dumps([{'kind': 'servicio', 'description': 'Instalación ficticia', 'quantity': '1', 'unit_price': '30'}]), client_name='Cliente Directo', client_identification='0100000017')
        self.assertEqual((direct['status'], direct['body']['proforma']['status']), (200, 'aprobada'))
        self.assertEqual(post('/api/proformas/%d' % direct['body']['id'], action='convert')['status'], 200)
        p = post('/api/proformas', items=json.dumps([{'kind': 'servicio', 'description': 'Servicio ficticio', 'quantity': '1', 'unit_price': '10'}]), client_name='Cliente Ficticio', client_identification='0100000017')['body']
        post('/api/proformas/%d' % p['id'], action='send')
        v2 = post('/api/proformas/%d' % p['id'], action='version')
        self.assertEqual((v2['status'], v2['body']['proforma']['code'], v2['body']['proforma']['version']), (200, p['proforma']['code'] + '-V2', 2))
        old = self.request('/api/proformas/%d' % p['id'], cookie=cookie)['body']['proforma']
        self.assertEqual(old['status'], 'reemplazada')
        self.assertEqual(post('/api/proformas/%d' % v2['body']['id'], action='decide', decision='aprobada', note='corto')['status'], 400)
        self.assertEqual(post('/api/proformas/%d' % v2['body']['id'], action='decide', decision='aprobada', note='Confirmó por teléfono (ficticio)')['status'], 200)
        third = post('/api/proformas', items=json.dumps([{'kind': 'servicio', 'description': 'Servicio ficticio', 'quantity': '1', 'unit_price': '10'}]), client_name='Cliente Ficticio')['body']
        self.assertEqual(post('/api/proformas/%d' % third['id'], action='cancel', reason='No interesa (ficticio)')['status'], 200)
        listing = self.request('/api/proformas', cookie=cookie)['body']
        self.assertEqual(listing['counts']['cancelada'], 1)


if __name__ == '__main__':
    unittest.main()
