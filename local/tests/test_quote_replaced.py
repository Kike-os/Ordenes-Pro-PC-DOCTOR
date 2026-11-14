"""Presupuestos reemplazados por una versión nueva (caso real PCD-20261031-0010: P3 sustituido por P4, aprobado por el cliente).
Una versión que el taller reemplaza queda «cancelada» con el evento «Sustituido por la versión Pn»: es correcto y no se toca. Lo que se
corrige (1.5.285) es lo que ve quien abre el enlace antiguo: antes decía «cancelado por el taller» y mostraba las partidas «Pendiente»;
ahora indica que fue reemplazado, por qué versión y en qué estado está esa versión, y las partidas «Sin efecto».
También: una aprobación válida nunca pasa a cancelada (ni por cancelar ni por crear otra versión), el enlace antiguo no permite decidir,
la cancelación manual sigue diciendo «cancelado por el taller» y el avance de ejecución no cambia el estado del presupuesto."""
import re
import unittest
from unittest.mock import patch

import test_quote_premium  # primero: prepara la ruta de importación y la base temporal
import app
from test_quotes import SIGN


class QuoteReplacedTests(unittest.TestCase):
    Base = test_quote_premium.QuotePremiumTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data, form = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data, Base.form
    build, open, decide, detail = Base.build, Base.open, Base.decide, Base.detail
    LINES = [('Actualización de BIOS ficticia', 'servicio', '16', True, 1), ('Windows 11 Pro ficticio', 'licencia', '146,95', True, 1), ('Pasta térmica ficticia', 'servicio', '65', True, 1)]

    def new_version(self, post, quote):
        created = post('/api/quotes/%d' % quote, action='version')
        self.assertEqual(created['status'], 201, created['body'])
        new = created['body']['id']
        with patch.object(app.mail_pro, 'configured', return_value=False):
            sent = post('/api/quotes/%d' % new, action='send')['body']
        return new, '/presupuesto/' + sent['link'].rsplit('/', 1)[1]

    def test_replaced_version_points_to_the_approved_one(self):
        old_path, old, order, post, _ = self.build(self.LINES, key='R001')
        page, old_key, old_ids = self.open(old_path)  # el cliente comprobó su identidad en la versión antigua y no decidió
        new, new_path = self.new_version(post, old)
        self.assertEqual(self.detail(old)['status'], 'cancelado')
        events = [e['detail'] for e in self.detail(old)['events']]
        self.assertTrue(any(text.startswith('Sustituido por la versión P2') for text in events))
        # La llave de la versión antigua ya no sirve para decidir: no se registra nada en ella.
        late = self.decide(old_path, old_key, old_ids, ['aprobado'] * 3)
        self.assertNotIn('name="decision_', late)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM quote_acceptances WHERE quote_id=?', (old,)).fetchone()[0], 0)
        page, key, ids = self.open(new_path)
        self.assertIn('Aprobado', self.decide(new_path, key, ids, ['aprobado'] * 3))
        new_code, approved = self.detail(new)['code'], self.detail(new)['totals']['approved']
        # Enlace antiguo: dice que fue reemplazado y por cuál, con su estado real; nada de «cancelado por el taller» ni partidas pendientes.
        shown = self.request(old_path)['body']
        for text in ('Versión reemplazada', 'Reemplazado', new_code, 'Aprobado', 'Sin efecto', app.quotes.usd(approved)):
            self.assertIn(text, shown)
        for text in ('cancelado por el taller', '<em>Pendiente</em>', 'name="decision_'):
            self.assertNotIn(text, shown)
        self.assertNotIn('style=', shown)
        # Abrir el enlace antiguo no cambia nada: la versión aprobada sigue aprobada y la antigua sigue cancelada con su historial.
        self.assertEqual((self.detail(old)['status'], self.detail(new)['status']), ('cancelado', 'aprobado'))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM quote_acceptances WHERE quote_id=?', (new,)).fetchone()[0], 1)

    def test_replacement_still_pending_and_manual_cancel(self):
        old_path, old, order, post, _ = self.build(self.LINES, key='R002')
        new, new_path = self.new_version(post, old)
        shown = self.request(old_path)['body']
        self.assertIn('Versión reemplazada', shown)
        self.assertIn('Esperando tu aprobación', shown)  # la versión vigente todavía no se decidió
        self.assertNotIn('cancelado por el taller', shown)
        # Cancelación manual (sin versión nueva): mantiene su mensaje y las partidas quedan «Sin efecto».
        path, quote, order2, post2, _ = self.build(self.LINES, key='R003')
        self.assertEqual(post2('/api/quotes/%d' % quote, action='cancel', reason='Prueba ficticia')['status'], 200)
        manual = self.request(path)['body']
        self.assertIn('cancelado por el taller', manual)
        self.assertIn('Sin efecto', manual)
        self.assertNotIn('Versión reemplazada', manual)

    def test_approval_is_never_turned_into_cancelled(self):
        path, quote, order, post, _ = self.build(self.LINES, key='R004')
        page, key, ids = self.open(path)
        self.decide(path, key, ids, ['aprobado', 'aprobado', 'pendiente'])
        self.assertEqual(self.detail(quote)['status'], 'parcial')
        self.assertEqual(post('/api/quotes/%d' % quote, action='cancel', reason='No debe poder')['status'], 409)
        follow = post('/api/quotes/%d' % quote, action='pending_version')  # continuación con lo pendiente
        self.assertEqual(follow['status'], 201, follow['body'])
        self.assertEqual(self.detail(quote)['status'], 'parcial')  # la versión aprobada no se toca
        approved = [i for i in self.detail(quote)['items'] if i['status'] == 'aprobado']
        self.assertEqual(post('/api/quotes/%d' % quote, action='execution', item=str(approved[0]['id']), value='realizado')['status'], 200)
        after = self.detail(quote)
        self.assertEqual((after['status'], [i['execution'] for i in after['items'] if i['id'] == approved[0]['id']]), ('parcial', ['realizado']))
        self.assertIn('Aprobado parcialmente', self.request(path)['body'])
        self.assertNotIn('Hay una versión más reciente', self.request(path)['body'])  # una continuación con lo pendiente no reemplaza nada

    def test_approved_version_followed_by_a_newer_one(self):
        # Caso real PCD-20261102-0012: P1 aprobado y después P2 (copia ampliada) también aprobado; el total de la orden es solo el de P2.
        path, quote, order, post, _ = self.build(self.LINES, key='R005')
        page, key, ids = self.open(path)
        self.decide(path, key, ids, ['aprobado'] * 3)
        new, new_path = self.new_version(post, quote)
        page, key2, ids2 = self.open(new_path)
        self.decide(new_path, key2, ids2, ['aprobado', 'aprobado', 'rechazado'])
        self.assertEqual((self.detail(quote)['status'], self.detail(new)['status']), ('aprobado', 'parcial'))  # la aprobación antigua no se toca
        shown = self.request(path)['body']
        for text in ('Hay una versión más reciente', self.detail(new)['code'], 'Aprobado parcialmente', app.quotes.usd(self.detail(new)['totals']['approved'])):
            self.assertIn(text, shown)
        self.assertNotIn('Hay una versión más reciente', self.request(new_path)['body'])
        order_now = self.request('/api/orders/%d' % order['id'], cookie=self.cookie)['body']
        order_now = order_now.get('order', order_now)
        self.assertEqual(order_now['budget']['total_cents'], self.detail(new)['totals']['approved'])  # sin sumar las dos versiones


if __name__ == '__main__':
    unittest.main()
