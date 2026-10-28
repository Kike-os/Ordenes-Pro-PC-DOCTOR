"""Caja obligatoria y configuración (datos ficticios, base temporal): con la caja cerrada no se registran cobros ni se confirman ventas
presenciales (borradores y proformas sí); apertura con $0,00 y con conteo; cuadre del efectivo y cobros por medio y por cuenta en el cierre;
cierre cuadrado, con sobrante, con faltante y con diferencia dentro del límite; configuración (fondo, regla, límite, denominaciones, cajas)."""
import json
import unittest

import test_fase2
import app
import cash_sessions

CLOSED = cash_sessions.CLOSED_MESSAGE


class CashRulesTests(unittest.TestCase):
    Base = test_fase2.Fase2Tests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure
    counts, tech, account = Base.counts, Base.tech, Base.account

    def require(self, on=True):
        with app.connect() as c:
            c.execute('UPDATE cash_settings SET require_open=? WHERE id=1', (1 if on else 0,))
            c.commit()

    def test_closed_cash_blocks_payments_and_sales_but_not_drafts(self):
        cookie, csrf, post, order = self.paid_order(10000, pay=False)
        card = post('/api/orders/%d/payments' % order['id'], amount='20', method='credito')  # antes de exigir la caja (como un cobro anterior)
        self.assertEqual(card['status'], 201, card['body'])
        self.require()
        status = self.request('/api/caja/status', cookie=cookie)['body']
        self.assertEqual((status['require_open'], status['open'], status['can_open'], status['message']), (True, False, True, CLOSED))
        # Cobro de una orden: bloqueado en el servidor con el mensaje acordado.
        r = post('/api/orders/%d/payments' % order['id'], amount='10,00', method='efectivo')
        self.assertEqual((r['status'], r['body']['error']), (409, CLOSED))
        # Factura directa: el borrador se guarda; confirmarla (con o sin cobro) exige la caja abierta.
        items = json.dumps([{'kind': 'servicio', 'description': 'Servicio ficticio', 'quantity': '1', 'unit_price': '20,00'}])
        draft = post('/api/proformas', origin='directa', items=items, client_name='Cliente Ficticio', client_identification='0100000017', request_key='caja-cerrada-borrador-01')
        self.assertEqual(draft['status'], 200, draft['body'])
        sale = post('/api/proformas/%d' % draft['body']['id'], action='checkout', payments='[]')
        self.assertEqual((sale['status'], sale['body']['error']), (409, CLOSED))
        # Proforma de cliente: se crea sin caja; su anticipo, no.
        pf = post('/api/proformas', origin='cliente', items=items, client_name='Cliente Ficticio', client_identification='0100000017', request_key='caja-cerrada-proforma-1')
        self.assertEqual(pf['status'], 200, pf['body'])
        adv = post('/api/proformas/%d' % pf['body']['id'], action='advance', method='efectivo', amount='5')
        self.assertEqual((adv['status'], adv['body']['error']), (409, CLOSED))
        # Voucher de tarjeta: bloqueado.
        # Un voucher suelto es un cobro nuevo: bloqueado. (El de un pago ya registrado solo lo documenta y queda en la caja de ese pago.)
        v = post('/api/vouchers', amount='10', issuer_bank='Banco Guayaquil', brand='Visa', category=test_fase2.ONE, tx_type='diferido_con_intereses', months='3', lot='000123',
                 reference='456789', approval_code='A1B2C3', last4='4242')
        self.assertEqual((v['status'], v['body'].get('error')), (409, CLOSED))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_payments').fetchone()[0], 1)  # solo el anterior
            self.assertEqual(c.execute('SELECT COUNT(*) FROM advances').fetchone()[0], 0)
            self.assertIsNone(c.execute('SELECT invoice_id FROM proformas WHERE id=?', (draft['body']['id'],)).fetchone()[0])
        # Con la caja abierta (fondo $0,00) los cobros se registran y quedan en esa caja.
        reg = self.request('/api/caja/state', cookie=cookie)['body']['registers'][0]['id']
        opened = post('/api/caja/open', register_id=str(reg), shift='Mañana', counts='[]', request_key='apertura-cero-00000001')
        self.assertEqual(opened['status'], 200, opened['body'])
        sid = opened['body']['session_id']
        self.assertEqual(self.request('/api/caja/sessions/%d' % sid, cookie=cookie)['body']['session']['opening_cents'], 0)
        self.assertEqual(post('/api/orders/%d/payments' % order['id'], amount='10,00', method='efectivo')['status'], 201)
        sold = post('/api/proformas/%d' % draft['body']['id'], action='checkout', payments=json.dumps([{'method': 'efectivo', 'amount': '20,00'}]), request_key='caja-abierta-cobro-0001')
        self.assertEqual(sold['status'], 200, sold['body'])
        with app.connect() as c:
            self.assertEqual({r[0] for r in c.execute('SELECT cash_session_id FROM order_payments WHERE id!=?', (card['body']['id'],))} | {r[0] for r in c.execute('SELECT cash_session_id FROM advances')}, {sid})
        # Sin la regla (desactivada por administración) se vuelve al comportamiento anterior: cobro como incidencia.
        self.require(False)
        self.assertFalse(self.request('/api/caja/status', cookie=cookie)['body']['require_open'])

    def test_close_breakdown_by_concept_method_and_account_with_limits(self):
        cookie, csrf, post, order = self.paid_order(50000, pay=False)
        self.require()
        state = self.request('/api/caja/state', cookie=cookie)['body']
        self.assertEqual((state['require_open'], state['default_fund_cents'], state['next_code'][:3]), (True, 0, 'CJ-'))
        reg = state['registers'][0]['id']
        # Apertura con varias denominaciones: 2 × $20 + 3 × $1 (billete) + 4 × $0,25 = $44,00.
        opened = post('/api/caja/open', register_id=str(reg), shift='Tarde', counts=self.counts(cookie, {('billete', 2000): 2, ('billete', 100): 3, ('moneda', 25): 4}))
        self.assertEqual(opened['status'], 200, opened['body'])
        sid = opened['body']['session_id']
        acc = self.account(post)
        # Cobro mixto: efectivo $30 + transferencia $20 a la cuenta + tarjeta $15.
        mixed = post('/api/orders/%d/payments' % order['id'], amount='65,00', lines=json.dumps([
            {'method': 'efectivo', 'amount': '30,00'}, {'method': 'transferencia', 'amount': '20,00', 'bank_account_id': str(acc), 'reference': 'TRX-CAJA-0001'},
            {'method': 'debito', 'amount': '15,00'}]), request_key='cobro-mixto-caja-0001')
        self.assertEqual(mixed['status'], 201, mixed['body'])
        self.assertEqual(post('/api/caja/movement', session_id=str(sid), direction='ingreso', kind='otro_ingreso', method='efectivo', amount='5', concept='Ingreso ficticio')['status'], 200)
        self.assertEqual(post('/api/caja/movement', session_id=str(sid), direction='egreso', kind='gasto_menor', method='efectivo', amount='4', concept='Gasto ficticio', beneficiary='Papelería ficticia')['status'], 200)
        s = self.request('/api/caja/sessions/%d' % sid, cookie=cookie)['body']['summary']
        b = s['cash_breakdown']
        self.assertEqual((b['opening_cents'], b['sales_cents'], b['other_in_cents'], b['out_cents'], b['refunds_cents'], b['expected_cents']), (4400, 3000, 500, 400, 0, 7500))
        self.assertEqual(b['expected_cents'], s['expected_cash_cents'])  # Fondo + entradas − salidas de efectivo
        col = s['collections']
        self.assertEqual((col['cash_cents'], col['transfer_cents'], col['card_cents'], col['total_cents']), (3500, 2000, 1500, 7000))  # sin mezclar efectivo y electrónicos
        self.assertEqual([(a['transfer_cents'], a['count']) for a in s['by_account']], [(2000, 1)])
        # Sobrante sin explicación: no se cierra; con explicación queda en revisión (límite 0).
        over = self.counts(cookie, {('billete', 5000): 1, ('billete', 2000): 1, ('billete', 500): 1, ('billete', 100): 1})  # $76,00 (sobra $1,00)
        base = dict(session_id=str(sid), counts=over, confirm='1', confirmed_name='Persona de prueba', reserved='0', delivered_to='Administración ficticia')
        self.assertEqual(post('/api/caja/close', **base)['status'], 400)
        # Límite de diferencia sin revisión: $1,00 → «Cerrada con diferencia» con la explicación y el responsable.
        cfg = post('/api/caja/config', default_fund='0', difference_limit='1,00', require_open='1')
        self.assertEqual((cfg['status'], cfg['body']['settings']['difference_limit_cents']), (200, 100))
        done = post('/api/caja/close', **base, difference_reason='Sobrante de un dólar en monedas (ficticio)')
        self.assertEqual((done['status'], done['body']['status'], done['body']['difference_cents']), (200, 'cerrada_diferencia', 100))
        # Siguiente turno con faltante mayor que el límite: queda en revisión. Y uno cuadrado: «cerrada».
        nxt = post('/api/caja/open', register_id=str(reg), shift='Noche', counts='[]')['body']['session_id']
        self.assertEqual(post('/api/caja/movement', session_id=str(nxt), direction='ingreso', kind='otro_ingreso', method='efectivo', amount='10', concept='Ingreso ficticio')['status'], 200)
        short = post('/api/caja/close', session_id=str(nxt), counts=self.counts(cookie, {('billete', 500): 1}), confirm='1', confirmed_name='Persona de prueba', reserved='0',
                     delivered_to='Administración ficticia', difference_reason='Faltante de cinco dólares (ficticio)')
        self.assertEqual((short['body']['status'], short['body']['difference_cents']), ('revision', -500))
        third = post('/api/caja/open', register_id=str(reg), shift='Mañana', counts='[]')['body']['session_id']
        square = post('/api/caja/close', session_id=str(third), counts='[]', confirm='1', confirmed_name='Persona de prueba', reserved='0')
        self.assertEqual((square['body']['status'], square['body']['difference_cents']), ('cerrada', 0))
        hist = self.request('/api/caja/history', cookie=cookie)['body']['rows']
        self.assertEqual(sorted(h['status'] for h in hist if h['id'] in (sid, nxt, third)), ['cerrada', 'cerrada_diferencia', 'revision'])

    def test_configuration_cards_denominations_and_permissions(self):
        cookie, csrf, post, order = self.paid_order(1000, pay=False)
        cfg = self.request('/api/caja/config', cookie=cookie)['body']
        self.assertEqual([r['name'] for r in cfg['registers']], ['Caja principal'])
        self.assertEqual(len(cfg['denominations']), 13)
        reg = cfg['registers'][0]['id']
        self.assertEqual(post('/api/caja/open', register_id=str(reg), shift='Mañana', counts='[]')['status'], 200)
        card = self.request('/api/caja/config', cookie=cookie)['body']['registers'][0]
        self.assertEqual((card['session']['cashier'], card['session']['shift'], card['session']['status']), ('Persona de prueba', 'Mañana', 'abierta'))
        self.assertTrue(card['last_opened'])
        self.assertEqual(post('/api/caja/registers', id=str(reg), name='Caja principal', active='0')['status'], 409)  # turno abierto: no se desactiva
        # Denominaciones en lote: se desactivan los billetes de $1 y $2; nunca se queda sin ninguna.
        ids = {(d['kind'], d['value_cents']): d['id'] for d in cfg['denominations']}
        keep = [i for k, i in ids.items() if k not in (('billete', 100), ('billete', 200))]
        self.assertEqual(post('/api/caja/denominations', action='batch', active_ids=','.join(map(str, keep)))['body']['changed'], 2)
        active = {(d['kind'], d['value_cents']) for d in self.request('/api/caja/state', cookie=cookie)['body']['denominations']}
        self.assertNotIn(('billete', 100), active)  # Abrir y Cerrar Caja muestran solo las activas
        self.assertEqual(post('/api/caja/denominations', action='batch', active_ids='')['status'], 400)
        self.assertEqual(post('/api/caja/config', default_fund='-1', difference_limit='0', require_open='1')['status'], 400)
        self.assertEqual(post('/api/caja/config', default_fund='50,00', difference_limit='0', require_open='1')['body']['settings']['default_fund_cents'], 5000)
        # Un técnico no cambia la configuración ni la ve.
        tcookie, tcsrf = self.tech()
        self.assertEqual(self.request('/api/caja/config', cookie=tcookie)['status'], 403)
        self.assertEqual(self.request('/api/caja/config', {'default_fund': '0', 'require_open': '0'}, cookie=tcookie, csrf=tcsrf)['status'], 403)
        with app.connect() as c:  # cada cambio de configuración queda auditado
            self.assertEqual(c.execute("SELECT COUNT(*) FROM payment_events WHERE event IN ('configuracion','denominacion')").fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
