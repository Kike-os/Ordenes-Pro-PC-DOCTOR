"""Logistics Pro (datos ficticios, base temporal): pedidos internacionales (14 etapas) y nacionales (10), cada paso solo con un evento
registrado, aduana sin liberación automática, incidencias que no avanzan, vehículo/avión según el paso real, pedidos anteriores sin
cambios y seguimiento público con sus 6 etapas y sin datos logísticos internos."""
import unittest
from datetime import datetime

import test_part_requests as base
import app
import order_part_requests as parts

INTL = ['confirmado', 'preparacion', 'despachado', 'transito_internacional', 'llegada_pais', 'aduana_revision', 'aduana_liberado', 'distribucion_nacional', 'ruta_otavalo', 'recibido']


class PartLogisticsTests(unittest.TestCase):
    Base = base.PartRequestTests
    setUpClass = classmethod(Base.Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure
    part, rows, link = Base.part, Base.rows, Base.link

    def row(self, cookie, oid, rid):
        return next(r for r in self.rows(cookie, oid) if r['id'] == rid)

    def test_international_flow_plane_customs_and_truck_by_real_events(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        rid = self.part(post, oid, shipping='internacional', origin_country='Estados Unidos', carrier='DHL Express', tracking_number='DHL-123')['body']['id']
        url = '/api/orders/%d/part-requests/%d' % (oid, rid)
        r = self.row(cookie, oid, rid)
        self.assertEqual((len(r['detail']), r['shipping_label'], [p['code'] for p in r['route']]), (15, 'Internacional', ['pedido', 'aereo', 'aduana', 'terrestre', 'recepcion', 'servicio']))  # 1.5.261: + «En camino al punto de embarque» (opcional)
        self.assertEqual(post(url, action='advance', stage='transito_internacional')['status'], 400)  # sin saltos (el administrador necesita motivo)
        seen = {}
        for step in INTL:
            res = post(url, action='advance', stage=step)
            self.assertEqual(res['status'], 200, (step, res['body']))
            r = self.row(cookie, oid, rid)
            seen[step] = (r['stage'], r['vehicle_mode'], r['customs'])
        self.assertEqual(seen['despachado'], ('transito', 'plane-parked', ''))
        self.assertEqual(seen['transito_internacional'], ('transito', 'plane', ''))
        self.assertEqual(seen['llegada_pais'], ('transito', 'plane-landed', 'Llegada al país · pendiente de revisión'))
        self.assertEqual(seen['aduana_revision'], ('transito', '', 'En proceso aduanero'))
        self.assertEqual(seen['aduana_liberado'][2], 'Liberado por aduana')
        self.assertEqual(seen['distribucion_nacional'][:2], ('transito', 'truck'))
        self.assertEqual(seen['recibido'][:2], ('recibido', 'truck-arrived'))
        r = self.row(cookie, oid, rid)
        self.assertEqual([d['state'] for d in r['detail']][:11], ['done'] * 10 + ['current'])
        self.assertTrue(all(d['at'] for d in r['detail'][:11]))
        self.assertEqual(r['dispatch_date'], app.reception_now().date().isoformat())
        # Seguimiento público (1.5.246): el envío internacional tiene su propia ruta (vuelo, aduana y traslado a Otavalo), pero nunca el país,
        # el transportista, la guía ni el proveedor.
        page = self.request('/s/' + self.link(oid))['body']
        for secret in ('Estados Unidos', 'DHL'):
            self.assertNotIn(secret, page, secret)
        self.assertIn('Proceso de aduana', page)
        with app.connect() as c:
            p = parts.public(c, oid)[0]
            self.assertEqual(([s['code'] for s in p['steps']], p['vehicle'], p['map']['mode']),
                             (['solicitud', 'confirmado', 'aereo', 'aduana', 'nacional', 'recibido', 'instalacion', 'finalizado'], '', 'internacional'))
            self.assertEqual([n['sub'] for n in p['map']['nodes']][0], 'Envío internacional')  # sin el país de origen
            self.assertEqual(sum(1 for h in p['history'] if h['label'] == 'Llegada a Ecuador'), 1)  # cada paso real, una sola vez

    def test_customs_is_never_released_without_its_event_and_incidents_do_not_advance(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        rid = self.part(post, oid, shipping='internacional')['body']['id']
        url = '/api/orders/%d/part-requests/%d' % (oid, rid)
        for step in INTL[:6]:  # hasta «En revisión aduanera»
            self.assertEqual(post(url, action='advance', stage=step)['status'], 200)
        self.assertEqual(post(url, action='advance', stage='distribucion_nacional', note='')['status'], 400)  # no se salta la liberación
        for incident, customs, situation in (('documentacion_pendiente', 'Documentación requerida', 'espera_confirmacion'), ('retencion_aduanera', 'Retención aduanera', 'incidencia_transporte')):
            self.assertEqual(post(url, action='situation', situation=incident, note='Novedad ficticia de aduana')['status'], 200)
            r = self.row(cookie, oid, rid)
            self.assertEqual((r['fine'], r['customs'], r['situation'], r['incident']), ('aduana_revision', customs, situation, incident))
        # Corrección de administración que salta la liberación: queda «Sin registro de liberación» y la etapa no se pinta como completada.
        self.assertEqual(post(url, action='advance', stage='distribucion_nacional', note='Corrección: el courier entregó sin aviso (ficticio)')['status'], 200)
        r = self.row(cookie, oid, rid)
        self.assertEqual(r['customs'], 'Sin registro de liberación aduanera')
        self.assertEqual(next(d['state'] for d in r['detail'] if d['code'] == 'aduana_liberado'), 'skipped')
        self.assertEqual((r['situation'], r['incident']), ('normal', ''))  # avanzar resuelve la novedad
        # Vuelo reprogramado en un pedido en el aire: el avión se detiene, la etapa no avanza.
        other = self.part(post, oid, shipping='internacional', name='Ventilador importado')['body']['id']
        ourl = '/api/orders/%d/part-requests/%d' % (oid, other)
        for step in INTL[:4]:
            post(ourl, action='advance', stage=step)
        self.assertEqual(post(ourl, action='situation', situation='vuelo_reprogramado', note='Vuelo reprogramado (ficticio)')['status'], 200)
        o = self.row(cookie, oid, other)
        self.assertEqual((o['fine'], o['vehicle_mode'], o['incident_label']), ('transito_internacional', 'plane-stopped', 'Vuelo retrasado o reprogramado'))
        for code in ('extraviado', 'devuelto', 'cambio_transportista', 'problema_entrega', 'retraso_transporte'):
            self.assertEqual(post(ourl, action='situation', situation=code, note='Novedad ficticia')['status'], 200, code)
            self.assertEqual(self.row(cookie, oid, other)['fine'], 'transito_internacional')
        self.assertTrue(len(self.row(cookie, oid, other)['events']) >= 10)  # todo queda en el historial

    def test_national_flow_and_previous_orders_keep_working(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        nat = self.part(post, oid, shipping='nacional', name='Teclado nacional')['body']['id']
        url = '/api/orders/%d/part-requests/%d' % (oid, nat)
        r = self.row(cookie, oid, nat)
        self.assertEqual((len(r['detail']), [p['code'] for p in r['route']]), (10, ['pedido', 'terrestre', 'recepcion', 'servicio']))
        self.assertEqual(post(url, action='advance', stage='transito_internacional')['status'], 400)  # sin avión ni aduana en un nacional
        for step in ('confirmado', 'preparacion', 'despachado', 'transito_nacional'):
            self.assertEqual(post(url, action='advance', stage=step)['status'], 200)
        self.assertEqual(self.row(cookie, oid, nat)['vehicle_mode'], 'truck')
        # Pedido anterior (sin tipo de envío): sus 8 etapas de siempre; puede definirse el tipo después y sigue en su paso.
        old = self.part(post, oid, name='Pedido anterior')['body']['id']
        ourl = '/api/orders/%d/part-requests/%d' % (oid, old)
        for step in ('confirmado', 'preparacion', 'transito'):
            self.assertEqual(post(ourl, action='advance', stage=step)['status'], 200)
        o = self.row(cookie, oid, old)
        self.assertEqual((len(o['detail']), o['route'], o['shipping_label'], o['fine']), (8, [], 'Sin definir', 'transito'))
        self.assertEqual(post(ourl, action='update', shipping='nacional')['status'], 200)
        o = self.row(cookie, oid, old)
        self.assertEqual((o['fine'], o['vehicle_mode']), ('despachado', 'truck-parked'))
        self.assertEqual(post(ourl, action='advance', stage='transito_nacional')['status'], 200)
        # Un técnico no cambia el tipo de un envío que ya está en traslado.
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(post(url, action='update', shipping='internacional')['status'], 403)


if __name__ == '__main__':
    unittest.main()
