"""Pronóstico MET Norway con caché compartida, timeout y fallos controlados."""
from datetime import datetime, timezone
import json
import math
import os
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_LOCK=threading.Lock()
_CACHE={'key':None,'expires':0,'data':None,'good':None,'good_at':0}
SHORT={'Parcialmente nublado':'Algo nublado','Nieve / aguanieve':'Nieve'}


def feels_like(temperature,humidity,wind):
    """Sensación térmica estimada (temperatura aparente de Steadman) a partir de temperatura, humedad y viento reales."""
    vapour=humidity/100*6.105*math.exp(17.27*temperature/(237.7+temperature))
    return round(temperature+0.33*vapour-0.70*wind-4.0)


def describe(symbol,wind):
    night=symbol.endswith('_night')
    if 'thunder' in symbol:return 'Tormenta','cloud-lightning'
    if 'snow' in symbol or 'sleet' in symbol:return 'Nieve / aguanieve','cloud-snow'
    if 'lightrain' in symbol:return 'Llovizna','cloud-drizzle'
    if 'rain' in symbol:return 'Lluvioso','cloud-rain'
    if 'fog' in symbol:return 'Niebla','cloud-fog'
    if wind>=10:return 'Viento','wind'
    if 'partlycloudy' in symbol or 'fair' in symbol:return 'Parcialmente nublado','cloud-moon' if night else 'cloud-sun'
    if 'cloudy' in symbol:return 'Nublado','cloud'
    if 'clearsky' in symbol:return ('Despejado','moon') if night else ('Soleado','sun')
    return 'Clima no disponible','cloud-off'


def current_weather():
    city=os.getenv('WEATHER_CITY','Otavalo, EC')[:80]
    try:
        lat=float(os.getenv('WEATHER_LATITUDE','0.2346'))
        lon=float(os.getenv('WEATHER_LONGITUDE','-78.2625'))
        if not (-90<=lat<=90 and -180<=lon<=180):raise ValueError()
    except ValueError:
        return {'available':False,'city':city,'label':'Clima no disponible','icon':'cloud-off'}
    key=(city,lat,lon)
    with _LOCK:
        if _CACHE['key']==key and _CACHE['expires']>time.monotonic():return _CACHE['data']
        result={'available':False,'city':city,'label':'Clima no disponible','icon':'cloud-off'}
        ttl=60
        try:
            query=urlencode({'lat':f'{lat:.4f}','lon':f'{lon:.4f}'})
            contact=os.getenv('WEATHER_CONTACT','https://ecuadorpcdoctor.com')
            request=Request('https://api.met.no/weatherapi/locationforecast/2.0/compact?'+query,
                headers={'User-Agent':'OrdenesPro/1.0 ('+contact+')','Accept':'application/json'})
            with urlopen(request,timeout=5) as response:
                raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:raise ValueError()
            payload=json.loads(raw)
            rows=payload['properties']['timeseries']
            now=datetime.now(timezone.utc)
            row=min(rows,key=lambda r:abs((datetime.fromisoformat(r['time'].replace('Z','+00:00'))-now).total_seconds()))
            valid_at=datetime.fromisoformat(row['time'].replace('Z','+00:00'))
            if abs((valid_at-now).total_seconds())>7200:raise ValueError()
            data=row['data'];instant=data['instant']['details']
            temperature=float(instant['air_temperature']);wind=float(instant.get('wind_speed',0))
            if not math.isfinite(temperature) or not -80<=temperature<=65:raise ValueError()
            period=data.get('next_1_hours',data.get('next_6_hours',{}))
            symbol=period.get('summary',{}).get('symbol_code','')
            label,icon=describe(symbol,wind)
            if icon=='cloud-off':raise ValueError()
            result.update(available=True,temperature=round(temperature),label=label,short=SHORT.get(label,label),icon=icon,
                source='MET Norway',source_url='https://api.met.no/',valid_at=row['time'],
                updated_at=payload['properties']['meta']['updated_at'],forecast=True,stale=False)
            # Datos adicionales solo cuando el proveedor los entrega; nunca se rellenan con valores supuestos.
            humidity=instant.get('relative_humidity');rain=period.get('details',{}).get('precipitation_amount') if 'next_1_hours' in data else None
            if isinstance(humidity,(int,float)) and 0<=humidity<=100:
                result.update(humidity=round(humidity))
                if 'wind_speed' in instant:result.update(feels_like=feels_like(temperature,humidity,wind))
            if 'wind_speed' in instant and 0<=wind<=120:result.update(wind_kmh=round(wind*3.6))
            if isinstance(rain,(int,float)) and 0<=rain<=500:result.update(precipitation_mm=round(rain,1))
            ttl=600
            _CACHE.update(good=result,good_at=time.monotonic())
        except (OSError,ValueError,TypeError,KeyError,IndexError):
            # Sin conexión con el proveedor: se conserva la última lectura válida hasta dos horas, marcada como desactualizada.
            if _CACHE['good'] and _CACHE['key']==key and time.monotonic()-_CACHE['good_at']<7200:result=dict(_CACHE['good'],stale=True)
        _CACHE.update(key=key,expires=time.monotonic()+ttl,data=result)
        return result
