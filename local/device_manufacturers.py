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
    # Datos de fábrica: solo los que la respuesta traiga; describen el equipo al salir de fábrica, no su estado actual.
    factory={label:str(item[key]).strip()[:80] for key,label in (('productFamily','Familia'),('productCode','Código de producto'),('systemDescription','Descripción')) if str(item.get(key) or '').strip()}
    if str(item.get('shipDate') or '')[:10]:factory['Fecha de envío']=str(item['shipDate'])[:10]
    return {'brand':'Dell','model':str(item['productLineDescription']).strip()[:150],'type':'','factory':factory}


class Provider:
    """Interfaz común de un servicio de identificación por fabricante.

    mode: 'api' (adaptador oficial escrito; solo consulta con credenciales propias), 'pendiente' (existe un programa oficial pero el
    fabricante no ha concedido acceso ni publicado su documentación: no hay adaptador ni consultas) o 'manual' (sin API: consulta
    asistida en el portal oficial). Ningún modo simula respuestas ni lee páginas web del fabricante."""
    def __init__(self,slug,name,mode,credentials=(),access='',ready=None,query=None):
        self.slug,self.name,self.mode,self.credentials,self.access=slug,name,mode,tuple(credentials),access
        self._ready,self._query=ready,query

    def configured(self):
        return self.mode=='api' and bool(self._ready and self._ready())

    def lookup(self,serial):
        if not self.configured():return None
        return self._query(serial)

    def status(self):
        """Estado real para la interfaz (sin valores de credenciales: solo sus nombres)."""
        return {'slug':self.slug,'mode':self.mode,'automatic':self.configured(),'credentials':list(self.credentials),'access':self.access}


PROVIDERS={p.slug:p for p in (
 Provider('dell','Dell','api',('DELL_API_CLIENT_ID','DELL_API_CLIENT_SECRET'),
          'Cuenta empresarial en Dell TechDirect (techdirect.dell.com) → Servicios → API: solicitar la API de garantía (Warranty API, OAuth 2.0). Dell revisa la solicitud, entrega un ID y un secreto de cliente para pruebas y después los promueve a producción.',
          dell_configured,dell_lookup),
 Provider('hp','HP','pendiente',('HP_API_KEY','HP_API_SECRET'),
          'Cuenta en el portal de desarrolladores de HP (developers.hp.com) y solicitud de la HP Warranty API; según integradores, la tramita el gestor de cuenta de HP de la empresa (warrantyapi.customers@hp.com). HP aprueba a mano; con el acceso se obtiene la documentación para escribir el adaptador.'),
 Provider('lenovo','Lenovo','pendiente',('LENOVO_CLIENT_ID',),
          'ClientID de la API de garantía de Lenovo: se solicita al representante comercial o de soporte empresarial de Lenovo (requiere un Lenovo ID de empresa o socio). Con el ClientID y su documentación se escribe el adaptador.'),
 Provider('asus','ASUS','manual',(),'No hay API pública. Para un acceso empresarial, consultar al canal de socios o servicio técnico regional de ASUS.'),
 Provider('acer','Acer','manual',(),'No hay API pública. Para consultas masivas, Acer remite a su portal de servicio y a su canal de empresas o revendedores.'),
 Provider('msi','MSI','manual',(),'No hay API pública y MSI prohíbe las consultas automatizadas a su verificador; solo consulta manual o acuerdo con su canal de empresas.'),
)}
# Compatibilidad: (configurado, consulta) por fabricante con adaptador oficial.
ADAPTERS={slug:(p.configured,p.lookup) for slug,p in PROVIDERS.items() if p.mode=='api'}


def configured():
    return tuple(slug for slug,p in PROVIDERS.items() if p.configured())


def statuses():
    return {slug:p.status() for slug,p in PROVIDERS.items()}


def lookup(slug,serial):
    """Resultado verificable del fabricante, None si no lo reconoce. Lanza ProviderError si el servicio falla."""
    provider=PROVIDERS.get(slug)
    if not provider:return None
    return provider.lookup(serial)
