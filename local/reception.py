"""Validación y catálogos de recepción, compartidos por las rutas autenticadas."""
import io
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, quote

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
import segno
from geography import validate_location

DEVICE_TYPES = {'portatil':'Portátil (Laptop)','notebook':'Notebook','gaming':'Portátil Gaming',
    'impresora':'Impresora','escritorio':'PC de escritorio','mini_pc':'Mini PC','aio':'All-in-One','aio_hp':'All-in-One HP',
    'aio_lenovo':'All-in-One Lenovo','aio_dell':'All-in-One Dell','consola':'Consolas',
    'tablet':'Tablet','celular':'Celular','router':'Router / equipo de red','servidor':'Servidor','otro':'Otro equipo'}
# La columna devices.category tiene una lista cerrada (CHECK) anterior a estos tipos: los nuevos se guardan en
# devices.kind y en category queda su equivalente admitido. El tipo real se lee con COALESCE(NULLIF(d.kind,''),d.category).
STORED_CATEGORY = {'notebook':'portatil','consola':'otro','aio':'escritorio','mini_pc':'escritorio','tablet':'otro','celular':'otro','router':'otro','servidor':'escritorio'}
LIMITS = {'document_type':10,'trade_name':150,'province_code':2,'canton':100,'canton_code':4,'parish':150,'parish_code':6,'locality_code':6,'main_street':250,'secondary_street':250,'building_number':30,'geo_version':10,'client':150,'identification':30,'phone':30,'email':254,'province':80,'city':100,
    'address':500,'location_reference':500,'type':30,'brand':150,'model':150,'serial':150,
    'color':100,'accessories':2000,'physical_condition':2000,'problem':2000,'technician_notes':2000}
REQUIRED = {'client','identification','phone','province_code','canton_code','parish_code','city','main_street','document_type','type','physical_condition','problem'}


def valid_cedula(value):
    if not re.fullmatch(r'[0-9]{10}', value):
        return False
    if not (1 <= int(value[:2]) <= 24 or value[:2] == '30') or int(value[2]) > 5:
        return False
    products = [int(n) * (2 if i % 2 == 0 else 1) for i,n in enumerate(value[:9])]
    return (-sum(n-9 if n>9 else n for n in products)) % 10 == int(value[9])


def document_error(value):
    if not re.fullmatch(r'[0-9]{10}|[0-9]{13}', value):
        return 'Ingresa 10 dígitos para cédula o 13 para RUC, sin letras ni símbolos.'
    if len(value) == 10:
        return '' if valid_cedula(value) else 'La cédula no supera la validación del dígito verificador.'
    if not (1 <= int(value[:2]) <= 24 or value[:2] == '30'):
        return 'El código de provincia del RUC no es válido.'
    third = int(value[2])
    if third < 6:
        valid = valid_cedula(value[:10]) and int(value[10:]) > 0
    elif third in (6,9):
        weights = [3,2,7,6,5,4,3,2] if third == 6 else [4,3,2,7,6,5,4,3,2]
        check = (11-sum(int(n)*w for n,w in zip(value,weights)) % 11) % 11
        position = 8 if third == 6 else 9
        valid = check < 10 and check == int(value[position]) and int(value[position+1:]) > 0
    else:
        valid = False
    return '' if valid else 'El RUC no supera la validación tradicional de su tipo y establecimiento.'


def valid_ecuador_phone(value):
    if not re.fullmatch(r'[+0-9 ()-]+',value):return False
    normalized=re.sub(r'[ ()-]','',value)
    return bool(re.fullmatch(r'(?:09[0-9]{8}|0[2-7][0-9]{7}|\+?593(?:9[0-9]{8}|[2-7][0-9]{7}))',normalized))


def validate_order(data):
    fields = {key:str(data.get(key,'')).strip() for key in LIMITS}
    errors = {}
    for key,limit in LIMITS.items():
        if len(fields[key]) > limit:
            errors[key] = f'Admite hasta {limit} caracteres.'
        elif key in REQUIRED and not fields[key]:
            errors[key] = 'Completa este campo.'
    if fields['document_type']!='pasaporte' and fields['identification'] and (error := document_error(fields['identification'])):
        errors['identification'] = error
    if fields['email'] and not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+', fields['email']):
        errors['email'] = 'Ingresa un correo electrónico válido.'
    if fields['phone'] and not valid_ecuador_phone(fields['phone']):
        errors['phone'] = 'Ingresa un móvil 09…, fijo con código de área o +593….'
    if fields['serial'] and not re.fullmatch(r'[A-Za-z0-9-]+', fields['serial']):
        errors['serial'] = 'Utiliza letras, números y guiones.'
    if fields['document_type']=='pasaporte':
        if not re.fullmatch(r'[A-Za-z0-9-]{3,30}',fields['identification']):errors['identification']='Ingresa un pasaporte de 3 a 30 letras, números o guiones.'
        fields['identification']=fields['identification'].upper()
    elif fields['document_type'] not in ('cedula','ruc'):
        errors['document_type']='Selecciona cédula ecuatoriana o RUC ecuatoriano.'
    elif len(fields['identification']) != (10 if fields['document_type']=='cedula' else 13):
        errors['identification']='Usa 10 dígitos para cédula o 13 para RUC, según el tipo seleccionado.'
    if fields['document_type']!='ruc':
        fields['trade_name']=''
    validate_location(fields,errors)
    if fields['type'] not in DEVICE_TYPES:
        errors['type'] = 'Selecciona un tipo de equipo válido.'
    key = str(data.get('request_key',''))
    if key and not re.fullmatch(r'[A-Za-z0-9-]{16,80}', key):
        errors['request_key'] = 'Recarga el formulario e intenta de nuevo.'
    return fields, errors


ECUADOR_TZ = ZoneInfo('America/Guayaquil')


def reception_now():
    return datetime.now(ECUADOR_TZ)


def order_code(date, number):
    return f'PCD-{date}-{number:04d}'


def public_base_url():
    base = os.getenv('PUBLIC_APP_URL', '').rstrip('/') or 'https://ordenes-pro.ecuadorpcdoctor.com'
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('PUBLIC_APP_URL debe ser una URL HTTPS sin ruta ni credenciales.')
    return base


def order_url(code):
    return public_base_url() + '/orders/' + quote(code, safe='')


def stored_category(kind):
    return STORED_CATEGORY.get(kind, kind)


def legacy_type(category):
    return 'portatil' if category in ('portatil','gaming','notebook') else 'escritorio'


def remember_brand(c, name, category):
    if name:
        group = 'printer' if category == 'impresora' else 'other' if category in ('otro','consola') else 'computer'
        c.execute('INSERT OR IGNORE INTO brands(name,category) VALUES (?,?)', (name,group))


def qr_image(payload, kind='svg'):
    stream = io.BytesIO()
    segno.make_qr(payload, error='m').save(stream, kind=kind, scale=8, border=4, dark='#102744', light='#ffffff')
    return stream.getvalue()


def production_enabled():
    return (os.getenv('APP_ENV') == 'production' and os.getenv('PRODUCTION_ENABLED','').lower() == 'true'
            and os.getenv('APP_URL','').startswith('https://') and os.getenv('SESSION_SECURE','').lower() == 'true')
