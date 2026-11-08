"""Etapa «En camino al punto de embarque» (1.5.261, datos ficticios, base temporal): tramo dentro del país de origen (p. ej., USPS hacia el
casillero) entre «Despachado en el país de origen» y «En tránsito internacional». Aparece en el orden correcto, se ve en el seguimiento del
cliente con su mensaje y el avión todavía en tierra, y no envía aviso por correo (es un paso logístico menor)."""
import re
import unittest

import order_part_requests as opr
import test_part_requests as parts
import app


class EmbarqueTests(unittest.TestCase):
    Base = parts.PartRequestTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link

    def test_new_step_in_order_visible_to_client_without_mail(self):
        flow = opr.FLOWS['internacional']
        self.assertEqual(flow[flow.index('despachado') + 1:flow.index('despachado') + 3], ('transito_origen', 'transito_internacional'))
        self.assertEqual(opr.step_label('transito_origen', 'internacional'), 'En camino al punto de embarque')
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        token = self.link(oid)
        rid = self.part(post, oid, name='Cámara ficticia', shipping='internacional', origin_country='Estados Unidos', carrier='USPS')['body']['id']
        for step in ('confirmado', 'preparacion', 'despachado'):
            self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage=step)['status'], 200, step)
        got = post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage='transito_origen', public_note=opr.MESSAGES['transito_origen'], publish='1')
        self.assertEqual(got['status'], 200, got['body'])
        with app.connect() as c:
            row = c.execute('SELECT stage,logistics FROM order_part_requests WHERE id=?', (rid,)).fetchone()
            self.assertEqual(tuple(row), ('transito', 'transito_origen'))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM order_part_notices WHERE request_id=? AND event='transito_origen'", (rid,)).fetchone()[0], 0)
        page = self.request('/s/' + token)['body']
        self.assertIn('punto de embarque', page)
        # El siguiente paso normal es el tránsito internacional (sin saltos ni retrocesos).
        self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage='transito_internacional')['status'], 200)
        notes = self.request('/api/orders/%d/part-requests' % oid, cookie=cookie)['body']['rows']
        self.assertEqual(next(r for r in notes if r['id'] == rid)['fine'], 'transito_internacional')


if __name__ == '__main__':
    unittest.main()
