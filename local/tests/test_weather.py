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
            # La actualización manual tampoco repite la consulta al proveedor dentro del mismo minuto.
            forced=weather.current_weather(force=True);self.assertIs(forced,first);self.assertTrue(first['checked_at']);self.assertEqual(fetch.call_count,1)
            weather._CACHE['asked_at']-=weather.FORCE_GAP+1;weather.urlopen.return_value=io.BytesIO(json.dumps(payload).encode());weather.current_weather(force=True);self.assertEqual(fetch.call_count,2)
            self.assertTrue(first['available']);self.assertEqual(first['icon'],'cloud-rain')
            self.assertEqual(first,second)
            self.assertIn('OrdenesPro',fetch.call_args.args[0].headers['User-agent'])
        weather._CACHE.update(key=None,expires=0,data=None)
        with patch.object(weather,'urlopen',side_effect=OSError('Sin conexión')):
            result=weather.current_weather()
            self.assertFalse(result['available']);self.assertEqual(result['label'],'Clima no disponible')

    def test_details_come_only_from_the_provider_and_stale_data_is_flagged(self):
        now=datetime.now(timezone.utc).isoformat()
        details={'air_temperature':16.2,'wind_speed':2.5,'relative_humidity':71.4}
        payload={'properties':{'meta':{'updated_at':now},'timeseries':[{'time':now,'data':{'instant':{'details':details},'next_1_hours':{'summary':{'symbol_code':'lightrain'},'details':{'precipitation_amount':0.4}}}}]}}
        with patch.object(weather,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
            full=weather.current_weather()
        self.assertEqual((full['icon'],full['label'],full['humidity'],full['wind_kmh'],full['precipitation_mm'],full['stale']),('cloud-drizzle','Llovizna',71,9,0.4,False))
        self.assertEqual(full['feels_like'],weather.feels_like(16.2,71.4,2.5))
        self.assertEqual(weather.describe('partlycloudy_day',0)[0],'Parcialmente nublado');self.assertEqual(weather.SHORT['Parcialmente nublado'],'Algo nublado')
        # Sin conexión, la última lectura válida se conserva marcada como desactualizada.
        weather._CACHE.update(expires=0)
        with patch.object(weather,'urlopen',side_effect=OSError('Sin conexión')):
            old=weather.current_weather()
        self.assertEqual((old['available'],old['stale'],old['temperature']),(True,True,16))
        # Si el proveedor no entrega humedad ni viento, no se inventan.
        weather._CACHE.update(key=None,expires=0,data=None,good=None)
        payload['properties']['timeseries'][0]['data']['instant']['details']={'air_temperature':16.2}
        with patch.object(weather,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
            bare=weather.current_weather()
        self.assertFalse({'humidity','feels_like','wind_kmh'}&set(bare))
