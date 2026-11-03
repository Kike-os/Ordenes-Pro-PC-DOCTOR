"""Recargo por pago con tarjeta de crédito trasladado al cliente (datos ficticios, base temporal): partida propia con IVA que el servidor
añade según la configuración del recargo comercial, sin duplicarse; en la venta directa, sobre lo pagado con tarjeta de crédito y sumado a
esa línea de cobro, de modo que factura y cobros coinciden. Débito, efectivo o recargo a cargo de la empresa: no se suma nada."""
import json
import unittest

import test_cash_rules
import app
import proformas


def helpers(cls):
    return {k: v for k, v in vars(cls).items() if not k.startswith('test_') and not k.startswith('__')}


ITEMS = json.dumps([{'kind': 'producto', 'description': 'Teclado ficticio', 'quantity': '2', 'unit_price': '25,00'},
                    {'kind': 'servicio', 'description': 'Instalación ficticia', 'quantity': '1', 'unit_price': '50,00'}])  # 100,00 con IVA incluido
CARD = {'card_bank': 'Banco Pichincha', 'card_brand': 'Visa', 'card_category': 'Personal', 'card_months': '3'}


class CardSurchargeTests(unittest.TestCase):
    locals().update(helpers(test_cash_rules.CashRulesTests))

    def setup_surcharge(self, payer='cliente'):
        with app.connect() as c:
            c.execute("UPDATE card_surcharge_settings SET percent_bp=900,fixed_cents=0,payer=?,active=1,valid_from='',valid_to='',"
                      "methods='[\"credito_corriente\",\"diferido_con_intereses\",\"diferido_sin_intereses\"]' WHERE id=1", (payer,))
            c.commit()

    def items(self, pid):
        with app.connect() as c:
            return [dict(r) for r in c.execute('SELECT code,description,unit_cents,taxed,status FROM proforma_items WHERE proforma_id=? ORDER BY position', (pid,))]

    def test_quote_with_credit_card_adds_surcharge_when_invoiced(self):
        cookie, csrf, post, order = self.paid_order(1000, pay=False)
        self.setup_surcharge()
        self.configure(post)
        acc = self.account(post)
        made = post('/api/proformas', origin='cliente', items=ITEMS, client_name='Cliente Ficticio', client_identification='0100000017',
                    payment_method='diferido_con_intereses', request_key='recargo-cotizacion-01', **CARD)
        self.assertEqual(made['status'], 200, made['body'])
        pid = made['body']['id']
        # Al guardar, el recargo es informativo (el cliente aprueba sus partidas; el recargo no es una de ellas).
        self.assertEqual([r for r in self.items(pid) if r['code'] == proformas.SURCHARGE_CODE], [])
        d = self.request('/api/proformas/%d' % pid, cookie=cookie)['body']
        f = d['proforma']['financing']
        self.assertEqual((d['totals']['total_cents'], f['base_cents'], f['surcharge_cents'], f['financeable_cents']), (10000, 10000, 900, 10900))
        # Una partida de recargo recibida al editar se descarta.
        again = json.loads(ITEMS) + [{'kind': 'servicio', 'description': 'Recargo', 'quantity': '1', 'unit_price': '9,00', 'code': proformas.SURCHARGE_CODE}]
        self.assertEqual(post('/api/proformas/%d' % pid, action='save', origin='cliente', items=json.dumps(again), client_name='Cliente Ficticio',
                              client_identification='0100000017', payment_method='diferido_con_intereses', **CARD)['status'], 200)
        self.assertEqual([r for r in self.items(pid) if r['code'] == proformas.SURCHARGE_CODE], [])
        # Aprobada, con un anticipo de 40,00 por transferencia: al facturar, el 9 % de los 60,00 que se pagan con la tarjeta.
        self.assertEqual(post('/api/proformas/%d' % pid, action='decide', decision='aprobada', note='Aprobada por el cliente por teléfono (ficticio)')['status'], 200)
        self.assertEqual(post('/api/proformas/%d' % pid, action='advance', method='transferencia', amount='40', bank_account_id=str(acc), reference='TR-RECARGO-1', request_key='recargo-anticipo-0001')['status'], 200)
        inv = post('/api/proformas/%d' % pid, action='convert')
        self.assertEqual(inv['status'], 200, inv['body'])
        self.assertEqual([(r['unit_cents'], r['status']) for r in self.items(pid) if r['code'] == proformas.SURCHARGE_CODE], [(540, 'aprobado')])
        self.assertEqual(inv['body']['invoice']['total_cents'], 10540)
        self.assertEqual(post('/api/proformas/%d' % pid, action='convert')['body']['invoice_id'], inv['body']['invoice_id'])  # sin duplicar
        self.assertEqual(len([r for r in self.items(pid) if r['code'] == proformas.SURCHARGE_CODE]), 1)
        # En efectivo, o si el recargo lo asume la empresa, no se suma.
        cash = post('/api/proformas', origin='cliente', items=ITEMS, client_name='Cliente Ficticio', client_identification='0100000017', payment_method='efectivo', request_key='recargo-cotizacion-02')['body']['id']
        post('/api/proformas/%d' % cash, action='decide', decision='aprobada', note='Aprobada por el cliente por teléfono (ficticio)')
        self.assertEqual(post('/api/proformas/%d' % cash, action='convert')['body']['invoice']['total_cents'], 10000)
        self.setup_surcharge('empresa')
        other = post('/api/proformas', origin='cliente', items=ITEMS, client_name='Cliente Ficticio', client_identification='0100000017',
                     payment_method='credito_corriente', request_key='recargo-cotizacion-03', **CARD)['body']['id']
        post('/api/proformas/%d' % other, action='decide', decision='aprobada', note='Aprobada por el cliente por teléfono (ficticio)')
        self.assertEqual(post('/api/proformas/%d' % other, action='convert')['body']['invoice']['total_cents'], 10000)

    def test_direct_sale_surcharge_only_on_the_credit_card_part(self):
        cookie, csrf, post, order = self.paid_order(1000, pay=False)
        self.setup_surcharge()
        pid = post('/api/proformas', origin='directa', items=ITEMS, client_name='Cliente Ficticio', client_identification='0100000017', request_key='recargo-directa-0001')['body']['id']
        pays = json.dumps([{'method': 'efectivo', 'amount': '40,00'}, {'method': 'credito', 'amount': '60,00'}])
        sold = post('/api/proformas/%d' % pid, action='checkout', payments=pays, request_key='recargo-directa-cobro-01')
        self.assertEqual(sold['status'], 200, sold['body'])
        extra = [r for r in self.items(pid) if r['code'] == proformas.SURCHARGE_CODE]
        self.assertEqual([r['unit_cents'] for r in extra], [540])  # 9 % de los 60,00 con tarjeta
        with app.connect() as c:
            adv = [(r['method'], r['amount_cents']) for r in c.execute("SELECT method,amount_cents FROM advances WHERE proforma_id=? AND voided_at='' ORDER BY id", (pid,))]
            inv = c.execute('SELECT * FROM invoices WHERE id=(SELECT invoice_id FROM proformas WHERE id=?)', (pid,)).fetchone()
            line = c.execute("SELECT description,total_cents,tax_cents FROM invoice_items WHERE invoice_id=? AND description LIKE 'Recargo por pago con tarjeta%'", (inv['id'],)).fetchone()
        self.assertEqual(adv, [('efectivo', 4000), ('credito', 6540)])  # la línea de la tarjeta lleva su recargo
        self.assertEqual(inv['total_cents'], 10540)  # lo facturado = lo cobrado
        self.assertEqual((line['total_cents'], line['tax_cents'] > 0), (540, True))  # la partida del recargo lleva IVA
        # Repetir la confirmación no suma otro recargo.
        self.assertEqual(post('/api/proformas/%d' % pid, action='checkout', payments=pays, request_key='recargo-directa-cobro-01')['status'], 200)
        self.assertEqual(len([r for r in self.items(pid) if r['code'] == proformas.SURCHARGE_CODE]), 1)
        # Tarjeta de débito: sin recargo.
        other = post('/api/proformas', origin='directa', items=ITEMS, client_name='Cliente Ficticio', client_identification='0100000017', request_key='recargo-directa-0002')['body']['id']
        self.assertEqual(post('/api/proformas/%d' % other, action='checkout', payments=json.dumps([{'method': 'debito', 'amount': '100,00'}]), request_key='recargo-directa-cobro-02')['status'], 200)
        self.assertEqual([r for r in self.items(other) if r['code'] == proformas.SURCHARGE_CODE], [])

    def test_order_payment_with_credit_card_adds_its_surcharge(self):
        import invoicing
        cookie, csrf, post, order = self.paid_order(50000, pay=False)
        self.setup_surcharge()
        oid = order['id']
        money = lambda: self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']['money']
        before = money()['balance_cents']
        pay = post('/api/orders/%d/payments' % oid, amount='100,00', method='credito', request_key='recargo-orden-000001')
        self.assertEqual(pay['status'], 201, pay['body'])
        self.assertEqual((pay['body']['amount_cents'], pay['body']['surcharge_cents']), (10900, 900))
        m = money()
        self.assertEqual((m['balance_cents'], m['surcharge_cents']), (before - 10000, 900))  # el saldo baja como un pago de 100,00
        # Reintento: el mismo pago, sin otro recargo.
        again = post('/api/orders/%d/payments' % oid, amount='100,00', method='credito', request_key='recargo-orden-000001')
        self.assertEqual((again['status'], again['body'].get('duplicate')), (200, True))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_card_surcharges WHERE order_id=?', (oid,)).fetchone()[0], 1)
        # Pago mixto: solo la parte con tarjeta de crédito; débito sin recargo.
        mixed = post('/api/orders/%d/payments' % oid, amount='80,00', lines=json.dumps([{'method': 'efectivo', 'amount': '30,00'}, {'method': 'credito', 'amount': '50,00'}]), request_key='recargo-orden-mixto-01')
        self.assertEqual((mixed['status'], mixed['body']['surcharge_cents']), (201, 450))
        debit = post('/api/orders/%d/payments' % oid, amount='20,00', method='debito', request_key='recargo-orden-debito-1')
        self.assertEqual((debit['status'], debit['body']['surcharge_cents']), (201, 0))
        self.assertEqual(money()['surcharge_cents'], 1350)
        # La factura incluye los recargos como partidas con IVA y no se bloquea por «cargos manuales».
        with app.connect() as c:
            source = invoicing.source(c, 'orden', oid)
        extra = [l for l in source['lines'] if l['code'] == 'RECARGO-TARJETA']
        self.assertEqual(([l['total_cents'] for l in extra], all(l['tax_cents'] > 0 for l in extra)), ([900, 450], True))
        self.assertFalse(any('cargos manuales' in b for b in source['blockers']), source['blockers'])
        # Anular el pago con tarjeta anula su recargo y el saldo vuelve a ser el de antes de ese pago.
        bal = money()['balance_cents']
        void = post('/api/orders/%d/payments/void' % oid, payment_id=str(pay['body']['id']), reason='Prueba ficticia de anulación')
        self.assertEqual(void['status'], 200, void['body'])
        m = money()
        self.assertEqual((m['surcharge_cents'], m['balance_cents']), (450, bal + 10000))


import test_license_sales


class LicenseSurchargeTests(unittest.TestCase):
    locals().update(helpers(test_license_sales.LicenseSalesTests))

    def test_license_credit_card_payment_adds_surcharge_and_void_reverts_it(self):
        import invoicing
        av, ms, client = self.catalog()
        with app.connect() as c:
            c.execute("UPDATE card_surcharge_settings SET percent_bp=900,fixed_cents=0,payer='cliente',active=1,valid_from='',valid_to='',"
                      "methods='[\"credito_corriente\",\"diferido_con_intereses\",\"diferido_sin_intereses\"]' WHERE id=1")
            c.commit()
        made = self.sale(client, [{'product_id': ms, 'quantity': 1}], payment={'amount': '50', 'method': 'tarjeta', 'card_kind': 'credito', 'confirmed': True})
        self.assertEqual(made['status'], 201, made['body'])
        sid = made['body']['sale']
        d = self.detail(sid)
        self.assertEqual((d['total_cents'], d['paid_cents'], d['balance_cents']), (9990 + 450, 5450, 9990 - 5000))  # el saldo baja como un pago de 50,00
        # Débito: sin recargo. Con el resto pagado, la factura incluye el recargo como partida con IVA y no se bloquea.
        rest = self.post('/api/licenses/sales/%d' % sid, action='pay', amount='%d,%02d' % divmod(9990 - 5000, 100), method='tarjeta', card_kind='debito', confirmed=True)
        self.assertEqual(rest['status'], 200, rest['body'])
        d = self.detail(sid)
        self.assertEqual((d['total_cents'], d['payment_status']), (10440, 'pagado'))
        with app.connect() as c:
            source = invoicing.source(c, 'venta_licencia', sid)
        extra = [l for l in source['lines'] if l['code'] == 'RECARGO-TARJETA']
        self.assertEqual(([l['total_cents'] for l in extra], source['blockers']), ([450], []))
        self.assertEqual(sum(l['total_cents'] for l in source['lines']), 10440)
        # Anular el pago con crédito anula su recargo: el total vuelve al de los productos.
        credit = next(p for p in d['payments'] if p['amount_cents'] == 5450)
        void = self.post('/api/licenses/sales/%d' % sid, action='void_payment', payment_id=str(credit['id']), reason='Prueba ficticia de anulación')
        self.assertEqual(void['status'], 200, void['body'])
        self.assertEqual(self.detail(sid)['total_cents'], 9990)


if __name__ == '__main__':
    unittest.main()
