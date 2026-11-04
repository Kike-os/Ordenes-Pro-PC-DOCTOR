"""Factores DATAFAST: estado real de cada factor (confirmado, verificado sin confirmar, pendiente, sin configurar, inactivo), confirmación
administrativa individual y por lotes con quién y cuándo, corrección con validación que no borra la versión anterior, bloqueo de pendientes
e inactivos en los cobros y proformas ya emitidas intactas. Base temporal y datos ficticios."""
import json
import unittest

import test_cash_rules
import app

ITEMS = json.dumps([{'kind': 'servicio', 'description': 'Servicio ficticio', 'quantity': '1', 'unit_price': '140,00'}])
CARD = {'card_bank': 'Banco Pichincha', 'card_brand': 'Visa', 'card_category': 'Corporativa', 'card_months': '3'}  # grupo B: 1,28 % a 3 meses
PICH = {'bank': 'Banco Pichincha', 'brand': 'Visa', 'category': 'Corporativa'}
NOTE = 'Cotejado con la tabla DATAFAST 6.2 (ficticio)'


def helpers(cls):
    return {k: v for k, v in vars(cls).items() if not k.startswith('test_') and not k.startswith('__')}


class CardFactorConfirmTests(unittest.TestCase):
    locals().update(helpers(test_cash_rules.CashRulesTests))

    def table(self, cookie):
        return self.request('/api/payments/cards', cookie=cookie)['body']['table']

    def cell(self, cookie, group, months):
        return next(r for r in self.table(cookie)['rows'] if r['months'] == months)['factors'][group]

    def sim(self, cookie, months=3, **card):
        from urllib.parse import urlencode
        return self.request('/api/payments/simulate?' + urlencode({'amount': '140', 'method': 'diferido_con_intereses', 'months': months, **(card or PICH)}), cookie=cookie)

    def confirmations(self):
        with app.connect() as c:
            return c.execute('SELECT COUNT(*) FROM card_factor_confirmations').fetchone()[0]

    def test_loaded_factors_are_verified_and_usable_until_confirmed(self):
        cookie, csrf, post, _ = self.paid_order(1000, pay=False)
        t = self.table(cookie)
        self.assertEqual(t['summary']['states'], {'confirmado': 0, 'verificado': 110, 'pendiente': 0, 'sin_configurar': 0, 'inactivo': 0})
        b3 = self.cell(cookie, 'B', 3)
        self.assertEqual((b3['state'], b3['usable'], b3['factor_bp'], b3['confirmed_by']), ('verificado', True, 128, ''))
        self.assertEqual(self.sim(cookie)['body']['factor_bp'], 128)  # verificado sin confirmar: sigue sirviendo para cobrar
        # Pendiente (sin valor) e inactivo (fuera de vigencia): visibles con su estado y bloqueados para cobrar.
        with app.connect() as c:
            c.execute("UPDATE card_factors SET status='pendiente',factor_bp=NULL WHERE group_code='B' AND months=4 AND status='vigente'")
            c.execute("UPDATE card_factors SET valid_to='2026-01-31' WHERE group_code='B' AND months=5 AND status='vigente'")
            c.commit()
        s = self.table(cookie)['summary']
        self.assertEqual((s['states']['pendiente'], s['states']['inactivo'], s['usable'], s['pending']), (1, 1, 108, 1))
        self.assertEqual(self.cell(cookie, 'B', 4)['state'], 'pendiente')
        self.assertEqual(self.cell(cookie, 'B', 5)['state'], 'inactivo')
        self.assertEqual(self.sim(cookie, months=4)['status'], 409)
        self.assertEqual(self.sim(cookie, months=5)['status'], 409)

    def test_confirm_one_and_many_records_who_and_when(self):
        cookie, csrf, post, _ = self.paid_order(1000, pay=False)
        b3 = self.cell(cookie, 'B', 3)
        # Sin marcar el cotejo o sin documento: no se confirma nada.
        no = post('/api/payments/factors/confirm', items='%d:%d' % (b3['id'], 128), note=NOTE)
        self.assertEqual((no['status'], list(no['body']['fields'])), (400, ['checked']))
        self.assertEqual(post('/api/payments/factors/confirm', items='%d:128' % b3['id'], checked='1', note='')['status'], 400)
        one = post('/api/payments/factors/confirm', items='%d:128' % b3['id'], checked='1', note=NOTE)
        self.assertEqual((one['status'], one['body']['confirmed'], one['body']['skipped']), (200, 1, 0))
        b3 = self.cell(cookie, 'B', 3)
        self.assertEqual(b3['state'], 'confirmado')
        self.assertTrue(b3['confirmed_by'] and b3['confirmed_at'].startswith('20'))
        # Confirmar de nuevo no duplica.
        self.assertEqual(post('/api/payments/factors/confirm', items='%d:128' % b3['id'], checked='1', note=NOTE)['body']['skipped'], 1)
        # Lote: los 11 plazos del grupo J. Si un porcentaje no coincide con lo guardado, no se confirma ninguno.
        j = [next(r for r in self.table(cookie)['rows'] if r['months'] == m)['factors']['J'] for m in (3, 4, 5, 6, 9, 10, 12, 15, 18, 24, 36)]
        before = self.confirmations()
        stale = ','.join('%d:%d' % (f['id'], f['factor_bp'] + (1 if i == 5 else 0)) for i, f in enumerate(j))
        self.assertEqual(post('/api/payments/factors/confirm', items=stale, checked='1', note=NOTE)['status'], 409)
        self.assertEqual(self.confirmations(), before)
        ok = post('/api/payments/factors/confirm', items=','.join('%d:%d' % (f['id'], f['factor_bp']) for f in j), checked='1', note=NOTE)
        self.assertEqual((ok['status'], ok['body']['confirmed']), (200, 11))
        self.assertEqual(self.table(cookie)['summary']['states']['confirmado'], 12)
        # Las confirmaciones no se modifican ni se borran.
        with app.connect() as c:
            for sql in ('UPDATE card_factor_confirmations SET factor_bp=1', 'DELETE FROM card_factor_confirmations'):
                with self.assertRaises(Exception):
                    c.execute(sql)

    def test_pending_is_completed_and_cannot_be_confirmed_without_value(self):
        cookie, csrf, post, _ = self.paid_order(1000, pay=False)
        with app.connect() as c:
            c.execute("UPDATE card_factors SET status='pendiente',factor_bp=NULL WHERE group_code='B' AND months=3 AND status='vigente'")
            c.commit()
        b3 = self.cell(cookie, 'B', 3)
        self.assertEqual(post('/api/payments/factors/confirm', items='%d:0' % b3['id'], checked='1', note=NOTE)['status'], 409)
        self.assertEqual(self.sim(cookie)['status'], 409)
        done = post('/api/payments/factors/edit', group='B', months='3', percent='1,28', expected_id=str(b3['id']), checked='1', note=NOTE)
        self.assertEqual((done['status'], done['body']['action']), (200, 'completado'), done['body'])
        b3 = self.cell(cookie, 'B', 3)
        self.assertEqual((b3['state'], b3['factor_bp'], b3['version']), ('confirmado', 128, '6.2'))
        self.assertEqual(self.sim(cookie)['body']['factor_bp'], 128)

    def test_correction_keeps_previous_version_and_issued_quotes(self):
        cookie, csrf, post, _ = self.paid_order(1000, pay=False)
        self.configure(post)
        made = post('/api/proformas', origin='cliente', items=ITEMS, client_name='Cliente Ficticio', client_identification='0100000017',
                    payment_method='diferido_con_intereses', request_key='factor-correccion-01', **CARD)
        self.assertEqual(made['status'], 200, made['body'])
        before = self.request('/api/proformas/%d' % made['body']['id'], cookie=cookie)['body']['proforma']['financing']
        self.assertEqual(before['factor_bp'], 128)
        b3 = self.cell(cookie, 'B', 3)
        self.assertEqual(post('/api/payments/factors/edit', group='B', months='3', percent='1,28', expected_id=str(b3['id']), checked='1', note=NOTE)['status'], 400)  # mismo valor
        self.assertEqual(post('/api/payments/factors/edit', group='B', months='3', percent='1,30', expected_id='999999', checked='1', note=NOTE)['status'], 409)  # cambió
        self.assertEqual(post('/api/payments/factors/edit', group='B', months='3', percent='abc', expected_id=str(b3['id']), checked='1', note=NOTE)['status'], 400)
        fixed = post('/api/payments/factors/edit', group='B', months='3', percent='1,30', expected_id=str(b3['id']), checked='1', note=NOTE)
        self.assertEqual((fixed['status'], fixed['body']['action']), (200, 'corregido'), fixed['body'])
        new = self.cell(cookie, 'B', 3)
        self.assertEqual((new['state'], new['factor_bp'], new['version']), ('confirmado', 130, '6.2 · corr. 1'))
        self.assertEqual(self.sim(cookie)['body']['factor_bp'], 130)
        self.assertEqual(self.table(cookie)['source']['version'], '6.2')  # una corrección suelta no cambia la versión de la tabla
        h = self.request('/api/payments/factors/history?group=B&months=3', cookie=cookie)['body']
        self.assertEqual([(v['status'], v['factor_bp']) for v in h['versions']], [('vigente', 130), ('reemplazado', 128)])
        self.assertEqual((h['confirmations'][0]['action'], h['confirmations'][0]['previous_bp']), ('corregido', 128))
        # La proforma ya emitida conserva su cálculo.
        self.assertEqual(self.request('/api/proformas/%d' % made['body']['id'], cookie=cookie)['body']['proforma']['financing'], before)
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM card_factors WHERE group_code='B' AND months=3").fetchone()[0], 2)

    def test_only_administration_confirms_or_edits(self):
        self.assertEqual(self.request('/api/payments/factors/history?group=B&months=3')['status'], 401)
        cookie, csrf, post, _ = self.paid_order(1000, pay=False)
        b3 = self.cell(cookie, 'B', 3)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(post('/api/payments/factors/confirm', items='%d:128' % b3['id'], checked='1', note=NOTE)['status'], 403)
        self.assertEqual(post('/api/payments/factors/edit', group='B', months='3', percent='2', expected_id=str(b3['id']), checked='1', note=NOTE)['status'], 403)
        self.assertEqual(self.request('/api/payments/factors/history?group=B&months=3', cookie=cookie)['status'], 403)
        self.assertEqual(self.request('/api/payments/factors/confirm', {'items': '%d:128' % b3['id'], 'checked': '1', 'note': NOTE}, cookie=cookie)['status'], 403)  # sin CSRF
        self.assertEqual(self.confirmations(), 0)


if __name__ == '__main__':
    unittest.main()
