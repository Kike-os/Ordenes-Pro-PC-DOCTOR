"""Barra única de avisos (1.5.255, datos ficticios, base temporal): presupuesto con su estado real y color, estados especiales, repuestos con su
paso real (avión, aduana, camión, recibido, instalación, cancelado aparte) y varios repuestos agrupados con acceso a cada uno. El cliente solo ve
lo público y sin enlace al presupuesto interno. Nada avanza ni cambia por mostrar avisos."""
import re
import unittest

import repair_stages
import test_part_requests as parts
import app


class RepairNoticeTests(unittest.TestCase):
    Base = parts.PartRequestTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link

    def notes(self, oid, public=False):
        with app.connect() as c:
            return repair_stages.compute(c, oid, public=public)['notices']

    def go(self, post, oid, rid, *steps):
        for step in steps:
            self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage=step)['status'], 200, step)

    def test_quote_and_special_states(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)  # presupuesto aprobado por el personal
        oid = order['id']
        self.assertEqual(post('/api/order-status', id=str(oid), status='reparacion')['status'], 200)
        n = self.notes(oid)
        self.assertEqual([(x['kind'], x['tone'], x['label']) for x in n], [('quote', 'verde', 'Presupuesto aprobado')])
        self.assertEqual(n[0]['target']['type'], 'quote')
        self.assertIsNone(self.notes(oid, public=True)[0]['target'])  # el cliente no abre el presupuesto interno
        with app.connect() as c:
            c.execute("UPDATE orders SET status='esperando_cliente' WHERE id=?", (oid,));c.commit()
        self.assertIn(('status', 'ambar', 'Respuesta pendiente'), [(x['kind'], x['tone'], x['label']) for x in self.notes(oid)])
        with app.connect() as c:
            c.execute("UPDATE orders SET status='entregado' WHERE id=?", (oid,));c.commit()
        self.assertEqual(self.notes(oid), [])  # entregada: sin avisos (el historial no cambia)

    def test_parts_states_grouping_and_public_view(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        with app.connect() as c:  # sin presupuesto vigente para aislar los avisos de repuestos
            c.execute("UPDATE quotes SET deleted_at='x' WHERE order_id=?", (oid,));c.commit()
        self.assertEqual(self.notes(oid), [])  # sin avisos activos: la barra no aparece
        a = self.part(post, oid, name='Pantalla ficticia', shipping='internacional')['body']['id']
        self.go(post, oid, a, 'confirmado', 'preparacion', 'despachado', 'transito_internacional')
        n = self.notes(oid)
        self.assertEqual([(x['tone'], x['icon'], x['label'], x['target']) for x in n], [('celeste', 'plane', 'En tránsito internacional', {'type': 'part', 'id': a})])
        self.go(post, oid, a, 'llegada_pais', 'aduana_revision')
        self.assertEqual((self.notes(oid)[0]['tone'], self.notes(oid)[0]['label']), ('naranja', 'En aduana de Ecuador'))
        self.go(post, oid, a, 'aduana_liberado', 'distribucion_nacional')
        self.assertEqual((self.notes(oid)[0]['icon'], self.notes(oid)[0]['label']), ('truck', 'En camino a Otavalo'))
        b = self.part(post, oid, name='Teclado ficticio', shipping='nacional')['body']['id']
        self.go(post, oid, b, 'confirmado')
        hidden = self.part(post, oid, name='Placa interna', public_visible='0')['body']['id']
        n = self.notes(oid)
        self.assertEqual(len(n), 1);self.assertEqual(n[0]['label'], 'Repuestos (3)')  # varios repuestos: un solo aviso agrupado
        self.assertEqual([p['id'] for p in n[0]['items']], [a, b, hidden])
        self.assertEqual(n[0]['tone'], 'ambar')  # el de mayor prioridad (esperando despacho) da el color
        pub = self.notes(oid, public=True)
        self.assertEqual(pub[0]['label'], 'Repuestos (2)')  # el cliente no ve el repuesto interno
        self.assertNotIn('Placa interna', str(pub))
        # Recibido, instalación y cancelación (estado alternativo, en rojo).
        self.go(post, oid, a, 'ruta_otavalo', 'recibido')
        self.assertIn(('verde', 'Repuesto recibido'), [(p['tone'], p['label']) for p in self.notes(oid)[0]['items']])
        self.go(post, oid, a, 'instalacion')
        self.assertIn(('violeta', 'Instalación en proceso'), [(p['tone'], p['label']) for p in self.notes(oid)[0]['items']])
        self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, b), action='cancel_direct', reason_code='sin_disponibilidad',
                              note='El proveedor no tiene existencias (ficticio).', confirm_supplier='1')['status'], 200)
        n = self.notes(oid)
        self.assertEqual(n[0]['tone'], 'rojo');self.assertIn(('rojo', 'Pedido cancelado'), [(p['tone'], p['label']) for p in n[0]['items']])
        self.go(post, oid, a, 'instalado')
        self.assertNotIn(a, [p['id'] for p in self.notes(oid)[0]['items']])  # terminado: deja de avisarse

    def test_public_page_shows_one_compact_bar(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        self.assertEqual(post('/api/order-status', id=str(oid), status='reparacion')['status'], 200)
        a = self.part(post, oid, name='Pantalla ficticia', shipping='nacional')['body']['id']
        self.go(post, oid, a, 'confirmado', 'preparacion', 'despachado')
        page = self.request('/s/' + self.link(oid))['body'].split('<section class="pa4"')[0]
        self.assertEqual(page.count('class="rp-nt"'), 1);self.assertNotIn('class="rp-alert"', page)
        self.assertIn('<span>Avisos (2)</span>', page)
        self.assertIn('href="#tp-%d"' % a, page);self.assertIn('id="tp-%d"' % a, page)
        self.assertRegex(page, r'<span class="rp-nt-item" data-tone="verde" title="Aprobado">')


if __name__ == '__main__':
    unittest.main()
