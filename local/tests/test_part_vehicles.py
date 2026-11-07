"""Vehículos 3D del seguimiento logístico (1.5.250, sin base de datos): cada estado real activa su dibujo y su animación, las animaciones
SMIL son válidas (keyTimes de 0 a 1), las ruedas giran según la distancia recorrida, el logo es el archivo original con su proporción real
y los id de los degradados no chocan entre dibujos."""
import math
import re
import unittest

import order_part_requests as parts
import part_route


def draw(shipping, step, situation='normal'):
    steps = parts.FLOWS[shipping]
    reached = set(steps[:steps.index(step) + 1])
    route = parts.route_map(shipping, step, reached, {}, False, situation)
    return route, part_route.render(route, 'u%s' % step[:6], 'Repuesto ficticio')


class PartVehicleTests(unittest.TestCase):
    def test_each_real_state_shows_its_vehicle_and_animation(self):
        cases = {('internacional', 'despachado'): ('plane', 'parked', 0), ('internacional', 'transito_internacional'): ('plane', 'moving', 1),
                 ('internacional', 'llegada_pais'): ('plane', 'landed', 1), ('internacional', 'distribucion_nacional'): ('truck', 'moving', 1),
                 ('nacional', 'despachado'): ('truck', 'parked', 0), ('nacional', 'transito_nacional'): ('truck', 'moving', 1),
                 ('nacional', 'recibido'): ('truck', 'arrived', 1)}
        for (shipping, step), (kind, motion, anim) in cases.items():
            route, html = draw(shipping, step)
            self.assertIn('data-kind="%s" data-motion="%s" data-anim="%d"' % (kind, motion, anim), html, (shipping, step))
            self.assertIn('lgx-plane-3d' if kind == 'plane' else 'lgx-van', html)
            self.assertEqual('lgx-clouds' in html, kind == 'plane' and motion == 'moving', (shipping, step))
        # Aduana: sin vehículo en movimiento; con una novedad, el vehículo se detiene con aviso y sin animación.
        self.assertIsNone(draw('internacional', 'aduana_revision')[0]['vehicle'])
        route, html = draw('internacional', 'transito_internacional', 'retrasado')
        self.assertIn('data-motion="stopped" data-anim="0"', html);self.assertIn('lgx-warn', html);self.assertNotIn('<animate', html)

    def test_animations_are_valid_and_follow_the_real_distance(self):
        for shipping, steps in parts.FLOWS.items():
            for step in steps:
                route, html = draw(shipping, step)
                for times in re.findall(r'keyTimes="([^"]+)"', html):
                    values = [float(x) for x in times.split(';')]
                    self.assertEqual((values[0], values[-1]), (0.0, 1.0), (shipping, step, times))  # si no, el navegador ignora la animación
                    self.assertEqual(values, sorted(values))
        route, html = draw('nacional', 'transito_nacional')
        spin = float(re.search(r'type="rotate" values="0;([0-9.]+)"', html).group(1))
        self.assertAlmostEqual(spin, route['vehicle']['distance'] / (2 * math.pi * part_route.WHEEL_R) * 360, delta=2)
        self.assertEqual(html.count('type="rotate"'), 2)  # dos ruedas visibles
        self.assertIn('repeatDur="%ss"' % part_route.DUR, html)  # suspensión solo durante el trayecto
        _, html = draw('internacional', 'transito_internacional')
        self.assertIn('values="1 1;1 1;1 0;1 0"', html)  # el tren se recoge al despegar
        _, html = draw('internacional', 'llegada_pais')
        self.assertIn('values="1 0;1 0;1 1;1 1"', html)  # y se despliega antes de aterrizar
        _, html = draw('nacional', 'recibido')
        self.assertRegex(html, r'<g transform="scale\(0\)"><g class="lgx-ok">.*?type="scale" values="0;1.18;1"')  # confirmación al llegar

    def test_original_logo_and_unique_ids(self):
        _, html = draw('internacional', 'transito_internacional')
        logos = re.findall(r'<svg class="lgx-logo" x="[^"]+" y="[^"]+" width="([^"]+)" height="([^"]+)" viewBox="([^"]+)"[^>]*><image href="([^"]+)" width="2826" height="2049"/>', html)
        self.assertTrue(logos)
        for w, h, box, href in logos:
            self.assertEqual((box, href), ('311 127 2102 1596', '/static/logo-original.png'))
            self.assertAlmostEqual(float(w) / float(h), 2102 / 1596, places=2)
        ids = re.findall(r'<(?:linear|radial)Gradient id="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.startswith('utransi') for i in ids))
        import order_tracking
        a, b = order_tracking._van(), order_tracking._van()
        self.assertNotEqual(set(re.findall(r'id="([^"]+)"', a)), set(re.findall(r'id="([^"]+)"', b)))


if __name__ == '__main__':
    unittest.main()
