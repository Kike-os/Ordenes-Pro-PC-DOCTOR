from datetime import datetime,timezone
import io
import json
import unittest
from unittest.mock import patch
import weather


class WeatherTests(unittest.TestCase):
    def setUp(self):weather._CACHE.update(key=None,expires=0,data=None)

    def test_dynamic_icons(self):
        for symbol,wind,icon in [('clearsky_day',0,'sun'),('clearsky_night',0,'moon'),('partlycloudy_day',0,'cloud-sun'),('partlycloudy_night',0,'cloud-moon'),('cloudy',0,'cloud'),('rain',0,'cloud-rain'),('rainandthunder',0,'cloud-lightning'),('fog',0,'cloud-fog'),('cloudy',12,'wind')]:
            self.assertEqual(weather.describe(symbol,wind)[1],icon)

    def test_real_response_shape_cache_and_failure(self):
        now=datetime.now(timezone.utc).isoformat()
        payload={'properties':{'meta':{'updated_at':now},'timeseries':[{'time':now,'data':{'instant':{'details':{'air_temperature':17.4,'wind_speed':2}},'next_1_hours':{'summary':{'symbol_code':'rain'}}}}]}}
        with patch.object(weather,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as fetch:
            first=weather.current_weather();second=weather.current_weather()
            self.assertTrue(first['available']);self.assertEqual(first['icon'],'cloud-rain')
            self.assertEqual(first,second);self.assertEqual(fetch.call_count,1)
            self.assertIn('OrdenesPro',fetch.call_args.args[0].headers['User-agent'])
        weather._CACHE.update(key=None,expires=0,data=None)
        with patch.object(weather,'urlopen',side_effect=OSError('Sin conexión')):
            result=weather.current_weather()
            self.assertFalse(result['available']);self.assertEqual(result['label'],'Clima no disponible')
