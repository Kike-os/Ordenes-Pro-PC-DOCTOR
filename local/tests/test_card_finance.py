"""Centro de Métodos de Pago: factores DATAFAST 6.2 precargados, correspondencia banco · marca · categoría → grupo, recargo comercial
configurable, diferido sin intereses al 0 %, letras que suman exactamente el total, combinaciones bloqueadas y permisos.
Base temporal y datos ficticios; la tabla esperada se escribe aquí de nuevo, independiente de la migración."""
import unittest

import test_app
import app
import card_finance

MONTHS = (3, 4, 5, 6, 9, 10, 12, 15, 18, 24, 36)
EXPECTED = {
    'A': '2,63 3,30 3,97 4,65 6,69 7,38 8,76 10,85 12,97 17,29 26,23', 'B': '1,28 1,61 1,93 2,26 3,24 3,57 4,22 5,22 6,22 8,24 12,35',
    'C': '1,67 2,09 2,51 2,94 4,22 4,65 5,51 6,81 8,12 10,78 16,21', 'D': '1,60 2,01 2,42 2,82 4,05 4,47 5,29 6,54 7,80 10,35 15,56',
    'E': '4,26 5,34 6,44 7,54 10,89 12,02 14,31 17,79 21,34 28,64 44,01', 'F': '3,80 4,76 5,74 6,72 9,69 10,70 12,72 15,81 18,94 25,37 38,85',
    'G': '3,40 4,26 5,13 6,01 8,66 9,55 11,36 14,10 16,88 22,57 34,45', 'H': '2,62 3,28 3,95 4,62 6,65 7,33 8,70 10,78 12,89 17,17 26,05',
    'I': '2,61 3,27 3,93 4,59 6,61 7,28 8,65 10,71 12,80 17,05 25,85', 'J': '2,68 3,36 4,05 4,73 6,81 7,50 8,91 11,03 13,19 17,58 pendiente'}
ONE = 'Única (la tabla no distingue categoría)'
GROUPS = {('Banco Diners', 'Diners', 'Personal'): 'A', ('Banco Diners', 'Discover', 'Personal'): 'A', ('Banco Diners', 'Visa Titanium', 'Personal'): 'A',
          ('Banco Diners', 'Mastercard Titanium', 'Personal'): 'A', ('Banco Diners', 'Diners', 'Corporativa'): 'B', ('Banco Diners', 'Diners', 'Empresarial'): 'C',
          ('Banco Diners', 'Diners', 'PYMES'): 'D', ('Banco Diners', 'Diners', 'Minorista'): 'E', ('Banco Diners', 'Diners', 'Simple'): 'F', ('Banco Diners', 'Diners', 'Ampliado'): 'G',
          ('Banco de Manabí', 'Visa', ONE): 'A', ('Banco de Loja', 'Visa', ONE): 'A', ('Banco de Andalucía', 'Visa', ONE): 'H'}
for brand in ('Visa', 'Mastercard'):
    GROUPS.update({('Banco Pichincha', brand, 'Personal'): 'A', ('Banco Pichincha', brand, 'Corporativa'): 'B', ('Banco Pichincha', brand, 'Empresarial'): 'C', ('Banco Pichincha', brand, 'PYMES'): 'D'})
GROUPS.update({('Banco General Rumiñahui (BGR)', 'Visa', cat): g for cat, g in (('Personal', 'A'), ('Corporativa', 'B'), ('Empresarial', 'C'), ('PYMES', 'D'))})
GROUPS.update({('Banco del Pacífico', brand, ONE): 'I' for brand in ('Mastercard', 'Visa', 'Pacificard')})
GROUPS.update({('Banco Guayaquil', brand, ONE): 'J' for brand in ('American Express', 'Visa', 'Mastercard')})
GYE = {'bank': 'Banco Guayaquil', 'brand': 'Visa', 'category': ONE}


class CardFinanceTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login

    def sim(self, cookie, **q):
        from urllib.parse import urlencode
        return self.request('/api/payments/simulate?' + urlencode(q), cookie=cookie)

    def test_every_group_and_factor_is_loaded_in_the_database(self):
        with app.connect() as c:
            products = {(r['bank'], r['brand'], r['category']): r['group_code'] for r in c.execute('SELECT * FROM card_products')}
            self.assertEqual(products, GROUPS)
            for group, row in EXPECTED.items():
                for months, value in zip(MONTHS, row.split()):
                    f = c.execute("SELECT factor_bp,status,version,valid_from FROM card_factors WHERE group_code=? AND months=? AND status IN ('vigente','pendiente')", (group, months)).fetchone()
                    if value == 'pendiente':
                        self.assertEqual((f['factor_bp'], f['status']), (None, 'pendiente'))
                    else:
                        self.assertEqual((f['factor_bp'], f['status'], f['version'], f['valid_from']), (int(value.replace(',', '')), 'vigente', '6.2', '2026-10-01'), (group, months))
            with self.assertRaises(Exception):
                c.execute('DELETE FROM card_factors')

    def test_example_of_140_dollars_with_surcharge_and_deferred_interest(self):
        cookie, _ = self.login()
        r = self.sim(cookie, amount='140,00', method='diferido_con_intereses', months='3', **GYE)['body']
        self.assertEqual((r['base_cents'], r['surcharge_cents'], r['financeable_cents'], r['factor_bp'], r['interest_cents'], r['total_cents'], r['installment_cents']),
                         (14000, 1260, 15260, 268, 409, 15669, 5223))
        self.assertEqual([i['amount_cents'] for i in r['installments']], [5223, 5223, 5223])
        self.assertIn('6.2', r['factor_source']);self.assertTrue(r['warnings'])  # recargo pendiente de validación
        # American Express del mismo banco: el mismo grupo J (2,68 % a 3 meses).
        self.assertEqual(self.sim(cookie, amount='140', method='diferido_con_intereses', months='3', bank='Banco Guayaquil', brand='American Express', category=ONE)['body']['factor_bp'], 268)

    def test_each_combination_returns_its_own_factor_and_unknown_ones_are_blocked(self):
        cookie, _ = self.login()
        for (bank, brand, category), group in GROUPS.items():
            for months, value in zip(MONTHS, EXPECTED[group].split()):
                r = self.sim(cookie, amount='100', method='diferido_con_intereses', months=str(months), bank=bank, brand=brand, category=category)
                if value == 'pendiente':
                    self.assertEqual(r['status'], 409);self.assertIn('pendiente de confirmar', r['body']['error'])
                else:
                    self.assertEqual(r['body']['factor_bp'], int(value.replace(',', '')), (bank, brand, category, months))
        for bad in ({'bank': 'Banco de Loja', 'brand': 'Mastercard', 'category': ONE}, {'bank': 'Banco Diners', 'brand': 'Discover', 'category': 'Empresarial'},
                    {'bank': 'Banco Pichincha', 'brand': 'Visa', 'category': 'Minorista'}, {'bank': 'Banco Inventado', 'brand': 'Visa', 'category': 'Personal'}):
            r = self.sim(cookie, amount='100', method='diferido_con_intereses', months='3', **bad)
            self.assertEqual(r['status'], 409, bad);self.assertIn('category', r['body']['fields'])
        self.assertEqual(self.sim(cookie, amount='100', method='diferido_con_intereses', months='7', **GYE)['status'], 400)  # plazo inexistente
        for amount in ('0', '-5', '1,234', 'abc', ''):
            self.assertEqual(self.sim(cookie, amount=amount, method='diferido_con_intereses', months='3', **GYE)['status'], 400, amount)

    def test_no_interest_mode_uses_zero_factor_and_current_mode_one_payment(self):
        cookie, _ = self.login()
        r = self.sim(cookie, amount='140', method='diferido_sin_intereses', months='36', **GYE)['body']  # el factor con intereses de 36 meses está pendiente; sin intereses no lo usa
        self.assertEqual((r['factor_bp'], r['interest_cents'], r['surcharge_cents'], r['total_cents'], len(r['installments'])), (0, 0, 1260, 15260, 36))
        self.assertEqual(sum(i['amount_cents'] for i in r['installments']), 15260)
        r = self.sim(cookie, amount='140', method='credito_corriente', **GYE)['body']
        self.assertEqual((r['months'], r['factor_bp'], r['total_cents'], [i['amount_cents'] for i in r['installments']]), (1, 0, 15260, [15260]))
        r = self.sim(cookie, amount='140', method='efectivo')['body']
        self.assertEqual((r['surcharge_cents'], r['total_cents'], r['bank']), (0, 14000, None))

    def test_installments_always_add_up_to_the_total(self):
        for total in (1, 2, 100, 999, 10000, 15669, 123457):
            for months in MONTHS:
                rows = card_finance.installments(total, months)
                self.assertEqual((sum(rows), len(rows)), (total, months))
                self.assertLessEqual(max(rows) - min(rows), months)  # solo la última absorbe el ajuste de redondeo

    def test_surcharge_is_configurable_applied_once_and_audited(self):
        cookie, csrf = self.login()
        post = lambda **body: self.request('/api/payments/surcharge', body, cookie=cookie, csrf=csrf)
        self.assertEqual(post(percent='9', payer='cliente', methods='diferido_con_intereses', active='1')['status'], 400)  # sin motivo
        self.assertEqual(post(percent='9', payer='cliente', methods='diferido_con_intereses', active='1', note='Prueba ficticia', valid_from='2026-13-01')['status'], 400)
        ok = post(percent='9,00', fixed='0,50', payer='cliente', methods='diferido_con_intereses', active='1', validated='1', note='Prueba ficticia con recargo fijo')
        self.assertEqual(ok['status'], 200)
        r = self.sim(cookie, amount='140', method='diferido_con_intereses', months='3', **GYE)['body']
        self.assertEqual((r['surcharge_cents'], r['financeable_cents'], r['interest_cents'], r['total_cents'], r['warnings'][:1]), (1310, 15310, 410, 15720, ['Confirmar con el contador el tratamiento tributario del recargo y del interés antes de facturarlos.']))
        self.assertEqual(self.sim(cookie, amount='140', method='diferido_sin_intereses', months='3', **GYE)['body']['surcharge_cents'], 0)  # método fuera de la lista
        post(percent='9', payer='empresa', methods='diferido_con_intereses', active='1', note='Lo asume la empresa (ficticio)')
        r = self.sim(cookie, amount='140', method='diferido_con_intereses', months='3', **GYE)['body']
        self.assertEqual((r['surcharge_cents'], r['interest_cents'], r['total_cents']), (0, 375, 14375))  # 140,00 × 2,68 % = 3,752 → 3,75
        post(percent='9', payer='cliente', methods='diferido_con_intereses', active='0', note='Desactivado (ficticio)')
        self.assertEqual(self.sim(cookie, amount='140', method='diferido_con_intereses', months='3', **GYE)['body']['surcharge_cents'], 0)
        history = self.request('/api/payments/surcharge/history', cookie=cookie)['body']['rows']
        self.assertEqual([h['note'] for h in history], ['Desactivado (ficticio)', 'Lo asume la empresa (ficticio)', 'Prueba ficticia con recargo fijo', 'Carga inicial'])
        with app.connect() as c:
            for sql in ('UPDATE card_surcharge_history SET percent_bp=1', 'DELETE FROM card_surcharge_history'):
                with self.assertRaises(Exception):
                    c.execute(sql)

    def test_compare_permissions_and_catalog(self):
        self.assertEqual(self.request('/api/payments/cards')['status'], 401)
        cookie, csrf = self.login()
        cards = self.request('/api/payments/cards', cookie=cookie)['body']
        self.assertEqual(sorted(cards['banks']), sorted({k[0] for k in GROUPS}))
        self.assertEqual(sorted(cards['banks']['Banco Guayaquil']), ['American Express', 'Mastercard', 'Visa'])
        self.assertEqual([f['usable'] for f in cards['factors']['J']][-1], False)
        rows = self.request('/api/payments/compare?amount=140&bank=Banco+Guayaquil&brand=Visa&category=' + ONE.replace(' ', '+'), cookie=cookie)['body']['rows']
        self.assertEqual(len(rows), 11)
        self.assertEqual(rows[0]['diferido_con_intereses']['total_cents'], 15669);self.assertIn('unavailable', rows[-1]['diferido_con_intereses'])
        self.assertEqual(rows[-1]['diferido_sin_intereses']['total_cents'], 15260)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.request('/api/payments/surcharge', {'percent': '1', 'note': 'Intento sin permiso'}, cookie=cookie, csrf=csrf)['status'], 403)
        self.assertEqual(self.request('/api/payments/surcharge/history', cookie=cookie)['status'], 403)
        self.assertEqual(self.sim(cookie, amount='140', method='diferido_con_intereses', months='3', **GYE)['status'], 200)  # el simulador es para todo el personal


if __name__ == '__main__':
    unittest.main()
