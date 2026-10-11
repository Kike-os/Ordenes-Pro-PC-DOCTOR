"""Adaptadores oficiales de fabricantes para identificar un equipo por su número de serie.

Cada adaptador solo se activa con credenciales propias entregadas por el fabricante (variables de entorno); sin ellas
no se realiza ninguna consulta externa. Un fallo del servicio nunca impide registrar la orden: se informa y se sigue
con el ingreso manual. Las credenciales no se registran ni se envían al navegador.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT=8
_tokens={}


class ProviderError(Exception):
    def __init__(self,kind,message):
        super().__init__(message);self.kind=kind


def _request(url,data=None,headers=None):
    request=urllib.request.Request(url,data=data,headers=dict({'Accept':'application/json','User-Agent':'OrdenesPro-PCDOCTOR'},**(headers or {})))
    try:
        with urllib.request.urlopen(request,timeout=TIMEOUT) as response:return json.loads(response.read(2_000_000).decode('utf-8'))
    except urllib.error.HTTPError as error:
        raise ProviderError('credenciales' if error.code in (400,401,403) else 'limite' if error.code==429 else 'servicio','El fabricante respondió con el código %d.'%error.code) from None
    except (urllib.error.URLError,TimeoutError,OSError):
        raise ProviderError('conexion','No se pudo conectar con el servicio del fabricante.') from None
    except ValueError:
        raise ProviderError('servicio','El fabricante devolvió una respuesta que no se pudo leer.') from None


# Dell TechDirect (API de garantía). Requiere clave aprobada por Dell: DELL_API_CLIENT_ID y DELL_API_CLIENT_SECRET.
# El host depende de la cuenta; se puede ajustar con DELL_API_HOST. Integración aún no probada contra el servicio real.
def dell_configured():
    return bool(os.getenv('DELL_API_CLIENT_ID') and os.getenv('DELL_API_CLIENT_SECRET'))


def dell_lookup(serial):
    if not re.fullmatch(r'[A-Z0-9]{5,7}',serial):return None  # Un Service Tag tiene de 5 a 7 letras y números.
    host=os.getenv('DELL_API_HOST','apigtwb2c.us.dell.com').strip()
    if not re.fullmatch(r'[a-z0-9.-]+\.dell\.com',host):raise ProviderError('configuracion','DELL_API_HOST debe ser un servidor de dell.com.')
    cached=_tokens.get('dell')
    if not cached or cached[1]<=time.time():
        body=urllib.parse.urlencode({'grant_type':'client_credentials','client_id':os.environ['DELL_API_CLIENT_ID'],'client_secret':os.environ['DELL_API_CLIENT_SECRET']}).encode()
        token=_request('https://'+host+'/auth/oauth/v2/token',body,{'Content-Type':'application/x-www-form-urlencoded'})
        if not isinstance(token,dict) or not token.get('access_token'):raise ProviderError('credenciales','Dell no entregó un token de acceso.')
        cached=_tokens['dell']=(str(token['access_token']),time.time()+max(60,int(token.get('expires_in',3600))-120))
    data=_request('https://'+host+'/PROD/sbil/eapi/v5/asset-entitlements?servicetags='+urllib.parse.quote(serial),headers={'Authorization':'Bearer '+cached[0]})
    item=next((row for row in data if isinstance(row,dict)),None) if isinstance(data,list) else None
    if not item or item.get('invalid') or not str(item.get('productLineDescription') or '').strip():return None
    return {'brand':'Dell','model':str(item['productLineDescription']).strip()[:150],'type':''}


ADAPTERS={'dell':(dell_configured,dell_lookup)}


def configured():
    return tuple(slug for slug,(ready,_) in ADAPTERS.items() if ready())


def lookup(slug,serial):
    """Resultado verificable del fabricante, None si no lo reconoce. Lanza ProviderError si el servicio falla."""
    adapter=ADAPTERS.get(slug)
    if not adapter or not adapter[0]():return None
    return adapter[1](serial)
