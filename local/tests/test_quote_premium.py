"""Página pública del presupuesto · Premium compacto (1.5.282). Base temporal y datos ficticios, sin correo real.
Cubre: un servicio y varios; aprobación total, parcial y rechazo total; pendientes; importes, bases e IVA por partida que suma el navegador
(iguales a los del servidor); el total cotizado no cambia; presupuesto vencido (ya no se aprueba ni se rechaza, sí se pide una versión);
doble confirmación; enlace inválido; fotografía del catálogo solo de partidas de este presupuesto y con la comprobación de identidad;
persistencia en la orden; sin estilos en línea y sin importes antes de comprobar la identidad."""
import re
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_quotes  # primero: prepara la ruta de importación y la base temporal
import app
import quotes
from test_quotes import SIGN

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


class QuotePremiumTests(unittest.TestCase):
    Base = test_quotes.QuoteFlowTests  # solo sus ayudantes: sus pruebas no se repiten aquí
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data, form = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data, Base.form

    def build(self, lines, valid_days=10, key='0001'):
        """Presupuesto enviado con las partidas dadas: [(nombre, categoría, precio, con_iva, cantidad), …]. Devuelve (ruta, id, orden, post, ids de catálogo)."""
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        order = self.request('/api/orders', self.order_data({'email': 'cliente@example.invalid', 'brand': 'Lenovo', 'model': 'Ficticio', 'request_key': 'premium-quote-request-' + key}), cookie=cookie, csrf=csrf)['body']
        lines = [('%s %s' % (name, key), category, price, taxed, qty) for name, category, price, taxed, qty in lines]  # el catálogo no admite nombres repetidos
        catalog = [post('/api/catalog', name=name, category=category, price=price, taxed=taxed)['body']['id'] for name, category, price, taxed, qty in lines]
        quote = post('/api/orders/%d/quote' % order['id'])['body']['id']
        items = [{'catalog_id': cid, 'description': name, 'category': category, 'quantity': qty, 'unit_cents': quotes.cents(price), 'taxed': taxed} for cid, (name, category, price, taxed, qty) in zip(catalog, lines)]
        post('/api/quotes/%d' % quote, action='save', items=items, valid_until=(app.reception_now().date() + timedelta(days=valid_days)).isoformat())
        with patch.object(app.mail_pro, 'configured', return_value=False):
            sent = post('/api/quotes/%d' % quote, action='send')['body']
        self.cookie = cookie
        return '/presupuesto/' + sent['link'].rsplit('/', 1)[1], quote, order, post, catalog

    def open(self, path):
        page = self.form(path, {'last4': '0017'})['body']
        passkey = re.search(r'name="passkey" value="([^"]+)"', page)[1]
        ids = [int(v) for v in dict.fromkeys(re.findall(r'name="decision_(\d+)"', page))]
        return page, passkey, ids

    def decide(self, path, passkey, ids, choices, **extra):
        fields = dict({'passkey': passkey, 'action': 'decide', 'name': 'Cliente Ficticio', 'accept': 'on', 'signature': SIGN}, **{'decision_%d' % i: v for i, v in zip(ids, choices)})
        fields.update(extra)
        return self.form(path, fields)['body']

    def detail(self, quote):
        return self.request('/api/quotes/%d' % quote, cookie=self.cookie)['body']['quote']

    def test_single_service_and_identity_before_amounts(self):
        path, quote, order, post, _ = self.build([('Mantenimiento preventivo', 'servicio', '35', True, 1)])
        first = self.request(path)['body']
        for text in ('Comprueba tu identidad', 'últimos cuatro dígitos', 'Orden vinculada', order['code'], 'Lenovo Ficticio', 'Válido hasta', 'Vigente · quedan 10 días', 'logo-original.png', 'Servicio Técnico Especializado'):
            self.assertIn(text, first)
        self.assertNotIn('$35,00', first)  # sin importes antes de comprobar la identidad
        page, passkey, ids = self.open(path)
        self.assertEqual(len(ids), 1)
        for text in ('Aprobar', 'No lo apruebo', 'Lo decidiré después', 'Total cotizado', '$35,00', 'Total seleccionado para aprobación', 'Revisar selección', 'Confirmar decisiones',
                     'Solicitar una modificación', 'data-qp-copy="%s"' % self.detail(quote)['code'], '/documento.pdf?k=' + passkey):
            self.assertIn(text, page)
        for page_text in (first, page):
            self.assertNotIn('style=', page_text)
            self.assertNotIn('<script>', page_text)
        done = self.decide(path, passkey, ids, ['aprobado'])
        self.assertIn('Aprobado', done)
        self.assertIn('Decisión registrada el', done)
        self.assertEqual(self.detail(quote)['status'], 'aprobado')

    def test_multiple_items_amounts_come_from_the_server_and_quoted_total_is_fixed(self):
        path, quote, order, post, _ = self.build([('Mantenimiento preventivo', 'servicio', '35', True, 1), ('Licencia ficticia', 'licencia', '12,50', False, 2), ('Disco SSD ficticio', 'repuesto', '80', True, 1)])
        page, passkey, ids = self.open(path)
        cards = re.findall(r'class="qp-item" id="qp-item-(\d+)" data-choice="[^"]*" data-net="(\d+)" data-base="(\d+)" data-tax="(\d+)" data-taxed="([01])"', page)
        self.assertEqual([int(c[0]) for c in cards], ids)  # mismo orden que fijó el taller
        totals = quotes.totals(quotes.items_of(app.connect(), quote), 1500)
        self.assertEqual(sum(int(c[1]) for c in cards), totals['quoted'])
        self.assertEqual(sum(int(c[2]) for c in cards if c[4] == '1'), totals['base_taxed'])
        self.assertEqual(sum(int(c[2]) for c in cards if c[4] == '0'), totals['base_zero'])
        self.assertEqual(sum(int(c[3]) for c in cards), totals['tax'])
        self.assertEqual([int(c[3]) for c in cards if c[4] == '0'], [0])  # tarifa 0 %: sin IVA
        self.assertEqual(page.count('name="decision_'), 9)
        # Error de validación: el servidor conserva la selección y su total (sumado con los mismos valores), y el total cotizado sigue igual.
        again = self.form(path, {'passkey': passkey, 'action': 'decide', 'accept': 'on', 'signature': SIGN, 'decision_%d' % ids[0]: 'aprobado', 'decision_%d' % ids[1]: 'aprobado', 'decision_%d' % ids[2]: 'rechazado'})['body']
        self.assertIn('Escribe tu nombre completo.', again)
        self.assertIn('data-qp-sum="total">$60,00<', again)  # 35,00 + 2 × 12,50
        self.assertIn('data-qp-sum="tax">$4,57<', again)  # solo el IVA de la partida gravada aprobada
        self.assertIn('$140,00', again)  # total cotizado original
        self.assertEqual(len(re.findall(r'name="decision_\d+" value="\w+" checked', again)), 3)

    def test_total_partial_reject_and_pending_decisions(self):
        lines = [('Mantenimiento preventivo', 'servicio', '35', True, 1), ('Disco SSD ficticio', 'repuesto', '80', True, 1)]
        cases = ((['aprobado', 'aprobado'], 'aprobado', 'Aprobado'), (['aprobado', 'rechazado'], 'parcial', 'Aprobado parcialmente'), (['rechazado', 'rechazado'], 'rechazado', 'Rechazado'),
                 (['aprobado', 'pendiente'], 'parcial', 'Por decidir'))
        for number, (choices, status, text) in enumerate(cases):
            path, quote, order, post, _ = self.build(lines, key='%04d' % (10 + number))
            page, passkey, ids = self.open(path)
            extra = {'signature': ''} if 'aprobado' not in choices else {}
            done = self.decide(path, passkey, ids, choices, **extra)
            self.assertIn(text, done)
            detail = self.detail(quote)
            self.assertEqual((detail['status'], [i['status'] for i in detail['items']]), (status, choices))
            approved = sum(i['net_cents'] for i in detail['items'] if i['status'] == 'aprobado')
            self.assertEqual(detail['totals']['approved'], approved)
            order_now = self.request('/api/orders/%d' % order['id'], cookie=self.cookie)['body']
            order_now = order_now.get('order', order_now)
            self.assertEqual(order_now['budget']['total_cents'], approved)  # la orden recibe solo lo aprobado
        # Todo pendiente: no se registra nada.
        path, quote, order, post, _ = self.build(lines, key='0099')
        page, passkey, ids = self.open(path)
        self.assertIn('Decide al menos un servicio', self.decide(path, passkey, ids, ['pendiente', 'pendiente']))
        self.assertEqual(self.detail(quote)['status'], 'enviado')

    def test_expired_quote_cannot_be_approved_but_can_request_an_update(self):
        path, quote, order, post, _ = self.build([('Mantenimiento preventivo', 'servicio', '35', True, 1)], key='0201')
        page, passkey, ids = self.open(path)
        with app.connect() as c:
            c.execute('UPDATE quotes SET valid_until=? WHERE id=?', ((app.reception_now().date() - timedelta(days=1)).isoformat(), quote))
            c.commit()
        self.assertIn('Vencido el', self.request(path)['body'])
        view, passkey, _ = self.open(path)
        self.assertIn('ya no admite aprobaciones', view)
        self.assertNotIn('name="decision_', view)
        blocked = self.decide(path, passkey, ids, ['aprobado'])
        self.assertIn('ya no se puede aprobar ni rechazar', blocked)
        self.assertEqual(self.detail(quote)['status'], 'enviado')
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM quote_acceptances WHERE quote_id=?', (quote,)).fetchone()[0], 0)
        done = self.form(path, {'passkey': passkey, 'action': 'change', 'comment': 'Envíenme el presupuesto actualizado'})['body']
        self.assertIn('solicitud de modificación', done)
        self.assertEqual(self.detail(quote)['status'], 'modificacion')

    def test_duplicate_confirmation_and_invalid_link(self):
        path, quote, order, post, _ = self.build([('Mantenimiento preventivo', 'servicio', '35', True, 1)], key='0301')
        page, passkey, ids = self.open(path)
        self.assertIn('Aprobado', self.decide(path, passkey, ids, ['aprobado']))
        again = self.decide(path, passkey, ids, ['rechazado'])  # segundo envío: muestra lo registrado, no decide otra vez
        self.assertIn('Aprobado', again)
        self.assertNotIn('name="decision_', again)
        self.assertEqual(self.detail(quote)['status'], 'aprobado')
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM quote_acceptances WHERE quote_id=?', (quote,)).fetchone()[0], 1)
        reopened = self.request(path)['body']
        for text in ('Autorizados', 'Total aprobado', 'Ver PDF', 'Decisión registrada el'):
            self.assertIn(text, reopened)
        missing = self.request('/presupuesto/' + 'x' * 43)
        self.assertEqual(missing['status'], 404)
        self.assertIn('Enlace no disponible', missing['body'])
        self.assertNotIn('style=', missing['body'])

    def test_catalog_photo_only_for_items_of_this_quote_after_identity(self):
        path, quote, order, post, catalog = self.build([('Disco SSD ficticio', 'repuesto', '80', True, 1)], key='0401')
        other = post('/api/catalog', name='Producto ajeno ficticio', category='repuesto', price='10', taxed=True)['body']['id']
        with app.connect() as c:
            for item in (catalog[0], other):
                c.execute('INSERT INTO catalog_images(item_id,mime,data,updated_at) VALUES (?,?,?,?)', (item, 'image/png', PNG, '2026-11-12T10:00:00'))
            c.commit()
        page, passkey, ids = self.open(path)
        self.assertIn('/imagen/%d?k=%s' % (catalog[0], passkey), page)
        self.assertEqual(self.request('%s/imagen/%d' % (path, catalog[0]))['status'], 404)  # sin comprobar la identidad
        shown = self.request('%s/imagen/%d?k=%s' % (path, catalog[0], passkey))
        self.assertEqual((shown['status'], bytes(shown['body'])), (200, PNG))
        self.assertEqual(self.request('%s/imagen/%d?k=%s' % (path, other, passkey))['status'], 404)  # no pertenece a este presupuesto


if __name__ == '__main__':
    unittest.main()
