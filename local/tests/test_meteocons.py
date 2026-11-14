"""1.5.284 · Iconos animados Meteocons «fill» del clima del encabezado.
Cada symbol_code oficial de MET Norway tiene su icono (día y noche) y su archivo existe animado (SMIL) y quieto; los SVG no traen guiones
ni recursos externos; /api/weather devuelve el icono del código real; la ruta sirve solo nombres válidos; se conserva la licencia MIT."""
from datetime import datetime, timezone
import io
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import test_app  # primero: ruta de importación y base temporal
import app
import weather

STATIC = Path(app.ROOT) / 'static' / 'meteocons'
# Lista oficial de symbol_code de MET Norway (sin sufijo de día/noche).
MET_CODES = ('clearsky fair partlycloudy cloudy fog lightrain rain heavyrain lightrainshowers rainshowers heavyrainshowers lightrainandthunder rainandthunder '
             'heavyrainandthunder lightrainshowersandthunder rainshowersandthunder heavyrainshowersandthunder lightsleet sleet heavysleet lightsleetshowers sleetshowers '
             'heavysleetshowers lightsleetandthunder sleetandthunder heavysleetandthunder lightssleetshowersandthunder sleetshowersandthunder heavysleetshowersandthunder '
             'lightsnow snow heavysnow lightsnowshowers snowshowers heavysnowshowers lightsnowandthunder snowandthunder heavysnowandthunder lightssnowshowersandthunder '
             'snowshowersandthunder heavysnowshowersandthunder').split()


class MeteoconsTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request

    def test_every_met_code_has_an_animated_and_a_still_icon(self):
        self.assertEqual(set(weather.METEOCONS), set(MET_CODES))
        names = {name for pair in weather.METEOCONS.values() for name in pair} | {'wind', 'not-available'}
        for name in names:
            animated = (STATIC / 'fill' / (name + '.svg')).read_text(encoding='utf-8')
            still = (STATIC / 'estatico' / (name + '.svg')).read_text(encoding='utf-8')
            if name != 'not-available':
                self.assertIn('<animate', animated, name)  # animación propia del SVG, no un efecto simulado
            self.assertNotIn('<animate', still, name)
            for text in (animated, still):
                self.assertFalse(re.search(r'<script|<style|style="|<image|<foreignObject|https?://(?!www\.w3\.org)', text), name)
        self.assertEqual({p.stem for p in (STATIC / 'fill').glob('*.svg')}, names)
        app_js = (Path(app.ROOT) / 'static' / 'app.js').read_text(encoding='utf-8')
        listed = set(re.search(r"const METEOCONS=new Set\(\[([^\]]+)\]\)", app_js)[1].replace("'", '').split(','))
        self.assertEqual(listed, names)  # la interfaz conoce exactamente los iconos publicados
        notice = (STATIC / 'meteocons-MIT.txt').read_text(encoding='utf-8')
        for text in ('MIT License', 'Bas Milius', 'meteocons'):
            self.assertIn(text, notice)

    def test_mapping_day_night_wind_and_unknown(self):
        cases = {('clearsky_day', 1): 'clear-day', ('clearsky_night', 1): 'clear-night', ('clearsky_polartwilight', 1): 'clear-day',
                 ('fair_night', 2): 'partly-cloudy-night', ('partlycloudy_day', 2): 'partly-cloudy-day', ('cloudy', 2): 'overcast',
                 ('lightrain', 1): 'drizzle', ('rain', 1): 'rain', ('heavyrain', 1): 'extreme-rain', ('rainshowers_night', 1): 'partly-cloudy-night-rain',
                 ('rainshowersandthunder_day', 1): 'thunderstorms-day-rain', ('rainandthunder', 1): 'thunderstorms-rain', ('fog', 1): 'fog',
                 ('snowshowers_day', 1): 'partly-cloudy-day-snow', ('sleet', 1): 'sleet', ('partlycloudy_day', 12): 'wind', ('rain', 12): 'rain',
                 ('', 1): 'not-available', ('inventado_day', 1): 'not-available'}
        for (symbol, wind), expected in cases.items():
            self.assertEqual(weather.meteocon(symbol, wind), expected, symbol)

    def test_api_returns_the_icon_of_the_real_code(self):
        now = datetime.now(timezone.utc).isoformat()
        payload = {'properties': {'meta': {'updated_at': now}, 'timeseries': [{'time': now, 'data': {'instant': {'details': {'air_temperature': 14.6, 'wind_speed': 1.5}},
                                                                                                          'next_1_hours': {'summary': {'symbol_code': 'lightrainshowers_night'}}}}]}}
        weather._CACHE.update(key=None, expires=0, data=None, good=None)
        with patch.object(weather, 'urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
            data = weather.current_weather()
        self.assertEqual((data['available'], data['symbol'], data['meteocon'], data['temperature']), (True, 'lightrainshowers_night', 'partly-cloudy-night-drizzle', 15))
        weather._CACHE.update(key=None, expires=0, data=None, good=None)
        with patch.object(weather, 'urlopen', side_effect=OSError('sin conexión')):
            down = weather.current_weather()
        self.assertEqual((down['available'], down['meteocon']), (False, 'not-available'))
        weather._CACHE.update(key=None, expires=0, data=None, good=None)

    def test_route_serves_only_valid_icon_names(self):
        ok = self.request('/static/meteocons/fill/clear-day.svg')
        self.assertEqual(ok['status'], 200)
        self.assertIn(b'<animateTransform', bytes(ok['body']))
        self.assertEqual(self.request('/static/meteocons/estatico/clear-day.svg')['status'], 200)
        for bad in ('/static/meteocons/fill/../app.py', '/static/meteocons/fill/Clear-Day.svg', '/static/meteocons/otra/clear-day.svg',
                    '/static/meteocons/fill/no-existe.svg', '/static/meteocons/meteocons-MIT.txt'):
            self.assertIn(self.request(bad)['status'], (401, 404), bad)  # nunca se sirve: 404 o, si cae en otra ruta, 401 sin sesión


if __name__ == '__main__':
    unittest.main()
