"""Cobertura Empresarial PC-DOCTOR universal (1.5.301): cualquier partida y dos modalidades.

Casos del encargo con datos ficticios:
 A · servicio BIOS/UEFI $45,00 con costo interno $20,00 cubierto al 100 %: el cliente sigue pagando $45,00.
 B · el mismo servicio con cobertura comercial del 100 %: el cliente paga $0,00 por esa partida, a la vista y como descuento de la línea.
 C · pantalla $150,00 con costo $95,00 cubierto internamente (lo cubre test_part_coverage, que sigue en verde).
 D · cobertura comercial del 50 %: beneficio $22,50 y saldo de la partida $22,50, con el IVA sobre el importe final.
"""
import unittest

import test_part_coverage   # antes que app: prepara la ruta y la base temporal de pruebas
import app
import quotes
import quote_page

BIOS = 'Actualización de BIOS/UEFI ficticia'


class UniversalCoverageTests(unittest.TestCase):
    Base = test_part_coverage.PartCoverageTests   # atributo de la clase: así unittest no vuelve a ejecutar sus pruebas aquí
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, counts, tech, account = Base.form, Base.prepare, Base.counts, Base.tech, Base.account
    setup_quote, open_cash, cash_out = Base.setup_quote, Base.open_cash, Base.cash_out

    def draft(self, key='0101'):
        """Borrador con el servicio BIOS/UEFI ($45,00 con IVA, posición 0) y la pantalla ($150,00 tarifa 0 %, posición 1)."""
        order, quote, sup, item = self.setup_quote(decide=False, key=key)
        items = [{'description': BIOS, 'category': 'servicio', 'quantity': 1, 'unit_cents': 4500, 'taxed': True},
                 {'description': 'Pantalla ficticia 15,6"', 'category': 'repuesto', 'quantity': 1, 'unit_cents': 15000, 'taxed': False}]
        self.assertEqual(self.post('/api/quotes/%d' % quote, action='save', items=items)['status'], 200)
        return order, quote, sup

    def cover(self, quote, position, **body):
        made = self.post('/api/quotes/%d/coverage' % quote, position=str(position), **body)
        self.assertEqual(made['status'], 201, made['body'])
        return made['body']['id'], made['body']['coverage']

    def quote(self, quote):
        return self.request('/api/quotes/%d' % quote, cookie=self.cookie)['body']['quote']

    def approve_all(self, quote):
        self.assertEqual(self.post('/api/quotes/%d' % quote, action='send')['status'], 200)
        ids = [i['id'] for i in self.quote(quote)['items']]
        self.assertEqual(self.post('/api/quotes/%d' % quote, action='decide', approved=','.join(map(str, ids)), note='Aprobó por teléfono (ficticio)')['status'], 200)

    def test_case_a_internal_service_cost_keeps_client_price_and_moves_no_money(self):
        order, quote, _ = self.draft()
        cid, cov = self.cover(quote, 0, modality='interna', cost='20', mode='total', reason_code='cortesia', authorize=True)
        self.assertEqual((cov['status'], cov['modality'], cov['covered_cents'], cov['cost_cents'], cov['goods']), ('autorizada', 'interna', 2000, 2000, False))
        q = self.quote(quote)
        self.assertEqual(q['totals']['quoted'], 19500)        # $45,00 + $150,00: el precio del cliente no cambia
        self.assertEqual(q['totals']['benefit'], 0)
        self.assertEqual(q['items'][0]['net_cents'], 4500)
        self.assertEqual(self.cash_out(), [])                  # autorizar no registra egresos
        # Un servicio no tiene compra ni recepción de inventario; el pago de un costo asociado necesita a quién se le paga.
        self.assertEqual(self.post('/api/coverage/%d' % cid, action='purchase', supplier_document='X-1')['status'], 409)
        self.assertEqual(self.post('/api/coverage/%d' % cid, action='receive')['status'], 409)
        self.open_cash()
        paid = self.post('/api/coverage/%d' % cid, action='pay', amount='20', method='efectivo', supplier_document='X-2', request_key='pago-servicio-000000001')
        self.assertEqual(paid['status'], 409, paid['body'])
        self.assertIn('proveedor', paid['body']['error'])
        self.assertEqual(self.cash_out(), [])

    def test_case_b_commercial_full_service_is_free_for_the_client_and_invoiced_as_line_discount(self):
        order, quote, _ = self.draft('0102')
        cid, cov = self.cover(quote, 0, modality='comercial', mode='total', reason_code='garantia', authorize=True)
        self.assertEqual((cov['status'], cov['modality'], cov['benefit_cents'], cov['client_cents']), ('autorizada', 'comercial', 4500, 0))
        q = self.quote(quote)
        bios = q['items'][0]
        self.assertEqual((bios['line_cents'], bios['benefit_cents'], bios['net_cents']), (4500, 4500, 0))
        t = q['totals']
        self.assertEqual((t['gross'], t['benefit'], t['quoted'], t['base_taxed'], t['tax'], t['base_zero']), (19500, 4500, 15000, 0, 0, 15000))
        self.assertEqual(self.cash_out(), [])                  # ni ingresos ni egresos ficticios
        # Documento del cliente: precio, beneficio e importe final, a la vista.
        with app.connect() as c:
            rows = quote_page.lines(quotes.get(c, quote), quotes.items_of(c, quote))
            self.assertEqual((rows[0]['before'], rows[0]['benefit'], rows[0]['net']), (4500, 4500, 0))
            self.assertIn('Beneficio PC-DOCTOR', quote_page._price(rows[0], quotes.get(c, quote)))
            self.assertIn('Beneficio PC-DOCTOR aplicado', quote_page._quoted_block(quotes.get(c, quote), quotes.items_of(c, quote)))
            self.assertTrue(any(e['event'] == 'cobertura' for e in c.execute('SELECT event FROM quote_events WHERE quote_id=?', (quote,))))
        pdf = self.request('/api/quotes/%d/pdf' % quote, cookie=self.cookie)
        self.assertEqual((pdf['status'], pdf['body'][:4]), (200, b'%PDF'))
        # Aprobado: lo autorizado y la factura llevan el beneficio como descuento de la línea (IVA sobre $0,00).
        self.approve_all(quote)
        with app.connect() as c:
            found = quotes.authorized(c, order['id'])
            self.assertEqual(sum(i['net_cents'] for i in found['items']), 15000)
            import invoicing
            line = invoicing._order_source(c, order['id'])['lines'][0]
            self.assertEqual((line['total_cents'], line['tax_cents'], line['discount_cents']), (0, 0, 3913))
        # Con el presupuesto ya aprobado, la cobertura comercial no se retira ni se modifica: lo aprobado no cambia por detrás.
        self.assertEqual(self.post('/api/coverage/%d' % cid, action='cancel', reason='Intento de retirar el beneficio')['status'], 409)
        self.assertEqual(self.post('/api/coverage/%d' % cid, action='update', mode='parcial', percent='50', revision=str(cov['revision']))['status'], 409)
        self.assertEqual(self.post('/api/coverage/%d' % cid, action='pay', amount='1', method='efectivo', supplier_document='X', request_key='pago-comercial-0000001')['status'], 409)

    def test_case_d_partial_commercial_half_price_with_tax_on_final_amount(self):
        _, quote, _ = self.draft('0103')
        _, cov = self.cover(quote, 0, modality='comercial', mode='parcial', percent='50', reason_code='atencion_comercial', authorize=True)
        self.assertEqual((cov['benefit_cents'], cov['client_cents'], cov['percent']), (2250, 2250, 50))
        q = self.quote(quote)
        self.assertEqual(q['items'][0]['net_cents'], 2250)
        base, tax = quotes.split(2250, True, q['tax_rate_bp'])
        self.assertEqual((q['totals']['base_taxed'], q['totals']['tax'], q['totals']['quoted']), (base, tax, 17250))

    def test_commercial_follows_draft_edits_and_cancel_restores_the_price(self):
        _, quote, _ = self.draft('0104')
        cid, cov = self.cover(quote, 0, modality='comercial', mode='parcial', percent='50', reason_code='garantia', authorize=True)
        items = [{'description': BIOS, 'category': 'servicio', 'quantity': 1, 'unit_cents': 6000, 'taxed': True},
                 {'description': 'Pantalla ficticia 15,6"', 'category': 'repuesto', 'quantity': 1, 'unit_cents': 15000, 'taxed': False}]
        self.assertEqual(self.post('/api/quotes/%d' % quote, action='save', items=items)['status'], 200)
        self.assertEqual(self.quote(quote)['items'][0]['net_cents'], 3000)    # 50 % del nuevo precio
        detail = self.request('/api/coverage/%d' % cid, cookie=self.cookie)['body']['coverage']
        self.assertEqual((detail['benefit_cents'], detail['base_cents']), (3000, 6000))
        done = self.post('/api/coverage/%d' % cid, action='cancel', reason='El cliente prefiere pagar el servicio completo', )
        self.assertEqual(done['status'], 200, done['body'])
        self.assertEqual(self.quote(quote)['totals']['quoted'], 21000)        # vuelve el precio completo; el registro se conserva
        # Ambas modalidades en la misma partida: el repuesto puede tener el precio exonerado y, además, su costo asumido.
        self.cover(quote, 1, modality='comercial', mode='total', reason_code='garantia')
        self.cover(quote, 1, modality='interna', cost='95', mode='total', reason_code='garantia')
        self.assertEqual(self.post('/api/quotes/%d/coverage' % quote, position='1', modality='interna', cost='95', mode='total', reason_code='garantia')['status'], 409)

    def test_technician_requests_commercial_but_never_authorizes_or_sees_costs(self):
        _, quote, _ = self.draft('0105')
        tcookie, tcsrf = self.tech()
        tpost = lambda path, **body: self.request(path, body, cookie=tcookie, csrf=tcsrf)
        made = tpost('/api/quotes/%d/coverage' % quote, position='0', modality='comercial', mode='total', reason_code='garantia', authorize=True)
        self.assertEqual(made['status'], 201, made['body'])
        cov = made['body']['coverage']
        self.assertEqual((cov['status'], cov['benefit_cents']), ('solicitada', 4500))   # el beneficio figura en el documento del cliente
        self.assertFalse(test_part_coverage.leaks(made['body']))
        self.assertEqual(self.quote(quote)['totals']['quoted'], 19500)                   # solicitada: todavía no cambia el precio
        self.assertEqual(tpost('/api/coverage/%d' % cov['id'], action='authorize', revision=str(cov['revision']))['status'], 403)
        internal = tpost('/api/quotes/%d/coverage' % quote, position='1', modality='interna', cost='95', mode='total', reason_code='garantia')
        self.assertEqual(internal['status'], 201, internal['body'])
        self.assertFalse(test_part_coverage.leaks(self.request('/api/coverage/%d' % internal['body']['id'], cookie=tcookie)['body']))

    def test_reasons_catalog_is_configurable_and_required(self):
        _, quote, _ = self.draft('0106')
        listed = self.request('/api/coverage/reasons', cookie=self.cookie)['body']
        self.assertTrue(listed['ready'])
        self.assertEqual([r['code'] for r in listed['reasons']][:3], ['garantia', 'compensacion', 'error_interno'])
        # «Otro motivo justificado» exige una descripción interna.
        self.assertEqual(self.post('/api/quotes/%d/coverage' % quote, position='0', modality='comercial', mode='total', reason_code='otro')['status'], 400)
        self.assertEqual(self.post('/api/quotes/%d/coverage' % quote, position='0', modality='comercial', mode='total', reason_code='inexistente')['status'], 400)
        tcookie, tcsrf = self.tech()
        self.assertEqual(self.request('/api/coverage/reasons', {'label': 'Motivo del técnico'}, cookie=tcookie, csrf=tcsrf)['status'], 403)
        made = self.post('/api/coverage/reasons', label='Promoción de temporada', requires_note=False)
        self.assertEqual(made['status'], 200, made['body'])
        code = made['body']['code']
        self.assertIn(code, [r['code'] for r in self.request('/api/coverage/reasons', cookie=tcookie)['body']['reasons']])
        self.assertEqual(self.post('/api/coverage/reasons', code=code, label='Promoción de temporada', active=False)['status'], 200)
        self.assertNotIn(code, [r['code'] for r in self.request('/api/coverage/reasons', cookie=tcookie)['body']['reasons']])
        self.assertEqual(self.post('/api/quotes/%d/coverage' % quote, position='0', modality='comercial', mode='total', reason_code=code)['status'], 400)
        with app.connect() as c:
            with self.assertRaises(Exception):
                c.execute('DELETE FROM coverage_reasons WHERE code=?', (code,))

    def test_existing_coverages_stay_internal(self):
        _, quote, sup, _ = self.setup_quote(key='0107')
        cid, cov = self.Base.authorized(self, quote, sup)
        self.assertEqual(cov['modality'], 'interna')
        self.assertEqual(self.quote(quote)['totals']['benefit'], 0)


if __name__ == '__main__':
    unittest.main()
