"""Teléfonos internacionales (1.5.251, datos ficticios, base temporal): validación por país, guardado en E.164 sin duplicar el prefijo,
WhatsApp solo con números aptos (sin afirmar que tengan WhatsApp), búsqueda por formato antiguo o internacional, números antiguos intactos
hasta que alguien edita la ficha, y archivos del selector servidos (biblioteca y banderas)."""
import unittest

import phones
import test_operations as base
import app

CASES = {  # país: (escrito por la persona, E.164 esperado, apto para WhatsApp)
    'EC': ('099 123 4567', '+593991234567', True), 'CO': ('+57 300 123 4567', '+573001234567', True), 'PE': ('+51 912 345 678', '+51912345678', True),
    'US': ('+1 202 555 0143', '+12025550143', True), 'ES': ('+34 612 34 56 78', '+34612345678', True), 'MX': ('+52 55 1234 5678', '+525512345678', True),
    'AR': ('+54 9 11 2345 6789', '+5491123456789', True), 'DE': ('+49 1512 3456789', '+4915123456789', True)}


class PhoneRulesTests(unittest.TestCase):
    def test_each_country_is_validated_and_stored_in_e164(self):
        for country, (typed, expected, wa) in CASES.items():
            self.assertEqual(phones.normalize(typed), (expected, ''), country)
            self.assertEqual(bool(phones.whatsapp(typed)), wa, country)
            self.assertEqual(phones.whatsapp(typed), expected[1:], country)
        # Pegado con «00», con el código sin «+» o ya en E.164: nunca se duplica el prefijo.
        for typed in ('00593991234567', '593991234567', '+593 99 123 4567', '0991234567', '991234567', '+593991234567'):
            self.assertEqual(phones.normalize(typed)[0], '+593991234567', typed)
        self.assertEqual(phones.normalize('573001234567')[0], '+573001234567')

    def test_clear_errors_and_no_fixed_length(self):
        self.assertIn('incompleto', phones.normalize('+57 300')[1])
        self.assertIn('Ecuador', phones.normalize('09912345')[1])
        self.assertIn('solo números', phones.normalize('099-ABC')[1])
        self.assertEqual(phones.normalize(''), ('', ''))
        self.assertEqual(len(phones.normalize('+51 912 345 678')[0]) - 1, 11)  # no se exige un largo fijo de 10 cifras
        self.assertEqual(len(phones.normalize('+5491123456789')[0]) - 1, 13)
        self.assertEqual(phones.whatsapp('062920000'), '')  # un fijo de Ecuador no sirve para WhatsApp
        self.assertEqual(phones.display('+593991234567'), '+593 99 123 4567')
        self.assertEqual(phones.tidy('0991234567 / 062920000'), '0991234567 / 062920000')  # en documentos, un texto no interpretable se conserva

    def test_search_finds_old_and_international_formats(self):
        for typed in ('0991234567', '099 123 4567', '+593 99 123 4567', '593991234567'):
            self.assertEqual(phones.as_query(typed), '991234567', typed)
        self.assertIsNone(phones.as_query('PCD-20261107-0001'))
        self.assertIsNone(phones.as_query('Juan'))
        self.assertTrue(phones.same('0991234567', '+593991234567'))
        self.assertFalse(phones.same('+573001234567', '+593991234567'))


class PhoneIntegrationTests(unittest.TestCase):
    Base = base.OperationsTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, create, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.create, Base.order_data

    def test_international_client_saved_found_and_old_numbers_untouched(self):
        cookie, csrf, data, order = self.create()
        oid = order['id']
        detail = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']
        self.assertEqual(detail['phone'], phones.normalize(data['phone'])[0])
        # Un número antiguo guardado antes de 1.5.251 no se reescribe al leerlo; la búsqueda lo encuentra en cualquier formato.
        with app.connect() as c:
            client_id = c.execute('SELECT d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?', (oid,)).fetchone()[0]
            c.execute("UPDATE clients SET phone='0987001122' WHERE id=?", (client_id,));c.commit()
        for term in ('0987001122', '+593 98 700 1122', '098 700 1122'):
            rows = self.request('/api/clients?q=' + __import__('urllib.parse').parse.quote(term), cookie=cookie)['body']['rows']
            self.assertEqual([r['id'] for r in rows], [client_id], term)
            self.assertEqual(len(self.request('/api/search?q=' + __import__('urllib.parse').parse.quote(term), cookie=cookie)['body']['rows']), 1, term)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT phone FROM clients WHERE id=?', (client_id,)).fetchone()[0], '0987001122')
        # Alta rápida con un número de Colombia: se guarda en E.164; un número inválido se rechaza con un mensaje claro.
        made = self.request('/api/clients', {'name': 'Cliente de Colombia', 'phone': '+57 300 123 4567', 'email': ''}, cookie=cookie, csrf=csrf)
        self.assertIn(made['status'], (200, 201), made['body'])
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT phone FROM clients WHERE name='Cliente de Colombia'").fetchone()[0], '+573001234567')
        bad = self.request('/api/clients', {'name': 'Cliente con error', 'phone': '+57 300', 'email': ''}, cookie=cookie, csrf=csrf)
        self.assertEqual(bad['status'], 400);self.assertIn('incompleto', bad['body']['fields']['phone'])

    def test_whatsapp_number_never_duplicates_the_prefix(self):
        import order_followups
        for raw, expected in (('0991234567', '593991234567'), ('+593 99 123 4567', '593991234567'), ('00593991234567', '593991234567'),
                              ('+57 300 123 4567', '573001234567'), ('+1 202 555 0143', '12025550143'), ('062920000', '')):
            self.assertEqual(order_followups.ecuador_number(raw), expected, raw)

    def test_selector_files_are_served(self):
        for path, kind in (('/static/phone-input.js', 'javascript'), ('/static/phone-input.css', 'css'), ('/static/libphonenumber-max.js', 'javascript'),
                           ('/static/flags/EC.svg', 'svg'), ('/static/flags/CO.svg', 'svg')):
            got = self.request(path)
            self.assertEqual(got['status'], 200, path)
        for bad in ('/static/flags/../app.py', '/static/flags/ec.svg', '/static/flags/ECU.svg'):
            got = self.request(bad)
            self.assertNotEqual(got['status'], 200, bad);self.assertNotIn('import ', str(got['body'])[:400])
        page = self.request('/citas')['body']
        self.assertIn('data-phone-intl', page);self.assertIn('/static/phone-input.js', page)


if __name__ == '__main__':
    unittest.main()
