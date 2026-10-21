"""Catálogo de fabricantes para la identificación de equipos: portal oficial, identificadores que admite y estado real.

Estados: `api` (integración oficial implementada; solo opera con credenciales propias), `pendiente` (existe un programa
oficial, falta autorización del fabricante), `manual` (solo consulta asistida en el portal) y `no_disponible`.
Los portales son para consulta manual del técnico: el sistema no los lee ni les envía series.
"""
import re
import unicodedata

MANUFACTURERS=(
 {'slug':'hp','name':'HP','aliases':('hewlett-packard','hp-inc','compaq'),'portal':'https://support.hp.com/ec-es/drivers/laptops','identifiers':'Número de serie y número de producto','status':'pendiente',
  'note':'HP ofrece una API de garantía en su portal de desarrolladores; exige solicitar credenciales y aprobación.'},
 {'slug':'dell','name':'Dell','aliases':('alienware',),'portal':'https://www.dell.com/support/home/en-ec?app=drivers','identifiers':'Service Tag (5 a 7 caracteres)','status':'api',
  'note':'API de TechDirect: requiere cuenta TechDirect y clave aprobada por Dell. Sin credenciales solo hay consulta manual.'},
 {'slug':'lenovo','name':'Lenovo','aliases':(),'portal':'https://pcsupport.lenovo.com/ec/es/warranty-lookup','identifiers':'Número de serie o tipo de máquina','status':'pendiente',
  'note':'La API de soporte exige un ClientID que Lenovo entrega mediante su representante comercial.'},
 {'slug':'acer','name':'Acer','aliases':(),'portal':'https://www.acer.com/ar-es/support/drivers-and-manuals','identifiers':'Número de serie (22 caracteres) o SNID','status':'manual','note':'No se encontró una API pública documentada.'},
 {'slug':'asus','name':'ASUS','aliases':('asustek',),'portal':'https://www.asus.com/support/warranty-status-inquiry/','identifiers':'Número de serie','status':'manual','note':'La consulta pública puede pedir verificación; no hay API documentada.'},
 {'slug':'apple','name':'Apple','aliases':('mac','macbook'),'portal':'https://checkcoverage.apple.com/','identifiers':'Número de serie','status':'manual','note':'La consulta pública usa CAPTCHA. La API existente es solo para proveedores de servicio autorizados.'},
 {'slug':'msi','name':'MSI','aliases':(),'portal':'https://www.msi.com/support/','identifiers':'Número de serie o modelo','status':'manual','note':'No se encontró una API pública documentada.'},
 {'slug':'samsung','name':'Samsung','aliases':(),'portal':'https://www.samsung.com/latin/support/','identifiers':'Modelo o número de serie','status':'manual','note':'No se encontró una API pública documentada.'},
 {'slug':'huawei','name':'Huawei','aliases':(),'portal':'https://consumer.huawei.com/latin/support/warranty-query/','identifiers':'Número de serie','status':'manual','note':'La consulta pública puede pedir verificación; no hay API documentada.'},
 {'slug':'dynabook','name':'Dynabook','aliases':('toshiba',),'portal':'https://support.dynabook.com/','identifiers':'Número de serie o número de modelo','status':'manual','note':'No se encontró una API pública documentada.'},
 {'slug':'epson','name':'Epson','aliases':(),'portal':'https://epson.com.ec/Soporte/Impresoras/sh/s1','identifiers':'Modelo de la impresora','status':'manual','note':'El portal busca por modelo, no por número de serie.'},
)


# Formato documentado del identificador de cada marca (solo para avisar de un posible error de escritura; nunca bloquea ni deduce).
FORMATS={'dell':(r'[A-Z0-9]{5,7}','El Service Tag de Dell tiene de 5 a 7 letras y números (normalmente 7). Está en la etiqueta del equipo o en la BIOS.'),
         'hp':(r'[A-Z0-9]{10}','La serie de HP suele tener 10 caracteres. El número de producto (p. ej. 6YX12LA#ABM) está en la misma etiqueta.'),
         'acer':(r'\d{11,12}|[A-Z0-9]{22}','Acer usa el SNID (11 o 12 dígitos) o la serie de 22 caracteres (con cero, nunca la letra O). Están en la etiqueta o en Acer Care Center.')}
HINTS={'dell':'Service Tag (5 a 7 caracteres)','hp':'Número de serie (10 caracteres)','lenovo':'Número de serie','asus':'Número de serie','acer':'SNID (11-12 dígitos) o serie de 22','msi':'Número de serie'}


def slug(name):
    text=unicodedata.normalize('NFD',str(name or ''))
    return re.sub(r'[^a-z0-9]+','-',''.join(ch for ch in text if not unicodedata.combining(ch)).lower()).strip('-')


def find(name):
    key=slug(name)
    return next((m for m in MANUFACTURERS if key and (key==m['slug'] or key in m['aliases'])),None)


def catalog(configured=(),providers=None):
    providers=providers or {}
    return [{'slug':m['slug'],'name':m['name'],'aliases':list(m['aliases']),'portal':m['portal'],'identifiers':m['identifiers'],'status':m['status'],'note':m['note'],'automatic':m['slug'] in configured,
             'hint':HINTS.get(m['slug'],''),'format':FORMATS.get(m['slug'],('',''))[0],'format_note':FORMATS.get(m['slug'],('',''))[1],'access':(providers.get(m['slug']) or {}).get('access','')} for m in MANUFACTURERS]
