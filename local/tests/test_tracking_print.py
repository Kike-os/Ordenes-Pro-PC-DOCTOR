"""Seguimiento de reparación en hoja A4 (1.5.248, datos ficticios, base temporal): la versión pública sale del mismo modelo seguro que la
página de seguimiento (sin cliente, serie, proveedor, transportista, guía, referencia ni notas internas); la interna exige sesión de
administración o técnico y no cambia nada de la orden; la cabecera muestra el estado del presupuesto sin importes."""
import re
import unittest

import test_part_requests as parts
import app


class TrackingPrintTests(unittest.TestCase):
    Base = parts.PartRequestTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link, rows = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link, Base.rows

    def order_with_part(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        rid = self.part(post, oid, shipping='internacional', origin_country='Estados Unidos', carrier='DHL Express', tracking_number='DHL-445566',
                        supplier_order='PED-778899')['body']['id']
        for stage in ('confirmado', 'preparacion', 'despachado', 'transito_internacional'):
            self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage=stage, note='Nota interna de etapa (interno)')['status'], 200)
        return cookie, post, order, rid

    @staticmethod
    def a4(page):
        found = re.search(r'<section class="pa4".*</section>', page, re.S)
        return found.group(0) if found else ''

    def snapshot(self, oid):
        with app.connect() as c:
            return [tuple(r) for r in c.execute("SELECT o.status,o.updated_at,(SELECT COUNT(*) FROM order_history WHERE order_id=o.id),(SELECT COUNT(*) FROM order_part_events e "
                                                "JOIN order_part_requests r ON r.id=e.request_id WHERE r.order_id=o.id),(SELECT group_concat(stage||situation) FROM order_part_requests WHERE order_id=o.id) "
                                                "FROM orders o WHERE o.id=?", (oid,))]

    def test_public_print_has_all_sections_and_no_private_data(self):
        cookie, post, order, rid = self.order_with_part()
        with app.connect() as c:
            client, serial = c.execute('SELECT cl.name,d.serial FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?', (order['id'],)).fetchone()
        before = self.snapshot(order['id'])
        page = self.request('/s/' + self.link(order['id']))['body']
        doc = self.a4(page)
        self.assertTrue(doc)
        self.assertIn('/static/seguimiento-a4.css', page)
        for text in ('Seguimiento de Reparación', 'Información del equipo', 'Progreso de reparación', 'Seguimiento de repuestos', 'Observaciones y avisos',
                     'Historial de seguimiento', 'Información de transporte', order['code'], 'Pantalla 15,6', 'Estado del presupuesto', 'Aprobado', 'data-audience="public"',
                     'logo-original.png', 'Próxima etapa:'):
            self.assertIn(text, doc, text)
        for secret in (client, serial, 'DHL', 'PED-778899', 'Costo 85', 'PANT-156-30P', 'NV156FHM', 'Nota interna de etapa', 'Estados Unidos', 'uso interno'):
            if secret:
                self.assertNotIn(secret, doc, secret)
        # Cabecera de pantalla: presupuesto sin importes y botón de impresión A4.
        self.assertIn('Imprimir seguimiento A4', page)
        self.assertRegex(page, r'class="tw-budget" data-budget="aprobado"><small>Presupuesto:</small> Aprobado')
        self.assertNotRegex(re.search(r'<header class="tw-head">.*?</header>', page, re.S).group(0), r'\$|USD|105')
        self.assertEqual(self.snapshot(order['id']), before)  # ver o imprimir no cambia nada

    def test_staff_print_requires_session_and_role_and_shows_internal_data(self):
        cookie, post, order, rid = self.order_with_part()
        url = '/tarjeta/%d/a4' % order['id']
        before = self.snapshot(order['id'])
        anon = self.request(url)
        self.assertNotIn('pa4', anon['body'] if isinstance(anon['body'], str) else '')
        page = self.request(url, cookie=cookie)
        self.assertEqual(page['status'], 200)
        doc = self.a4(page['body'])
        for text in ('data-audience="admin"', 'uso interno', 'DHL Express', 'DHL-445566', 'Estados Unidos', 'PANT-156-30P', 'Costo 85', 'Nota interna de etapa',
                     'Historial de modificaciones de la orden', 'Técnico responsable', 'Imprimir seguimiento A4'):
            self.assertIn(text, page['body'], text)
        self.assertTrue(doc)
        self.assertEqual(self.request('/tarjeta/999999/a4', cookie=cookie)['status'], 404)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.request(url, cookie=cookie)['status'], 200)
        with app.connect() as c:
            # Solo existen administrador y técnico; un rol distinto (creado aquí, en la base temporal) no accede a la versión interna.
            c.execute("INSERT OR IGNORE INTO roles(name) VALUES ('consulta')");c.execute("UPDATE users SET role='consulta' WHERE id=?", (self.uid,));c.commit()
        other = self.request(url, cookie=cookie)
        self.assertNotEqual(other['status'], 200)
        self.assertNotIn('DHL-445566', str(other['body']))
        with app.connect() as c:
            c.execute("UPDATE users SET role='administrador' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.snapshot(order['id']), before)

    def test_tracking_card_offers_a4_and_stylesheet_is_served(self):
        cookie, post, order, rid = self.order_with_part()
        card = self.request('/api/orders/%d/tracking-card' % order['id'], cookie=cookie)['body']
        self.assertEqual(card['print_a4_url'], '/tarjeta/%d/a4' % order['id'])
        css = self.request('/static/seguimiento-a4.css')
        self.assertEqual(css['status'], 200)
        self.assertIn('size:A4 portrait', css['body'] if isinstance(css['body'], str) else css['body'].decode())

    def test_order_without_parts_and_lookup_keeps_existing_keys(self):
        cookie, csrf, post, order = self.paid_order(3000, pay=False, key='0009')
        token = self.link(order['id'])
        with app.connect() as c:
            import order_tracking
            data = order_tracking.lookup(c, token)
        for key in ('id', 'code', 'status', 'status_label', 'received', 'updated', 'device', 'updates', 'files', 'parts'):
            self.assertIn(key, data)
        self.assertEqual((data['budget_code'], data['budget']), ('aprobado', 'Aprobado'))
        doc = self.a4(self.request('/s/' + token)['body'])
        self.assertNotIn('Seguimiento de repuestos', doc)
        self.assertIn('Sin avisos', doc)


if __name__ == '__main__':
    unittest.main()
