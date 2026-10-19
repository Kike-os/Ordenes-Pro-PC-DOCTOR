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


def _province(value):
    return 1 <= int(value[:2]) <= 24 or value[:2] == '30'


def document_check(value, kind=''):
    """Valida una cédula o un RUC ecuatorianos con las reglas de cada tipo. Devuelve (error, aviso).
    Cédula: 10 dígitos, provincia, tercer dígito 0-5 y dígito verificador (módulo 10).
    RUC de persona natural (tercer dígito 0-5): su cédula válida más el establecimiento. RUC de entidad pública (6) o de sociedad (9):
    provincia y establecimiento; su dígito verificador (módulo 11) se comprueba, pero si no coincide solo se avisa, porque el SRI
    emite RUC de sociedades que no lo cumplen y rechazarlos dejaría fuera a contribuyentes reales.
    `kind` ('cedula' o 'ruc') exige la longitud de ese tipo; vacío acepta cualquiera de los dos."""
    size = {'cedula': 10, 'ruc': 13}.get(kind)
    if not re.fullmatch(r'[0-9]+', value) or (len(value) != size if size else len(value) not in (10, 13)):
        return ({10: 'La cédula debe contener exactamente 10 dígitos.', 13: 'El RUC debe contener exactamente 13 dígitos.'}.get(size, 'Ingresa 10 dígitos para cédula o 13 para RUC, sin letras ni símbolos.'), '')
    third = int(value[2])
    if len(value) == 10:
        if not _province(value):
            return 'Los dos primeros dígitos de la cédula no corresponden a una provincia.', ''
        if third > 5:
            return 'El tercer dígito no corresponde a una cédula ecuatoriana.', ''
        return ('' if valid_cedula(value) else 'El número de cédula no es válido. Revisa los dígitos ingresados.'), ''
    if not _province(value):
        return 'Los dos primeros dígitos del RUC no corresponden a una provincia.', ''
    if third in (7, 8):
        return 'El tercer dígito no corresponde a ningún tipo de RUC.', ''
    if third < 6:
        if not valid_cedula(value[:10]):
            return 'Los diez primeros dígitos del RUC no forman una cédula válida. Revisa los dígitos ingresados.', ''
        return ('' if int(value[10:]) > 0 else 'El RUC debe terminar en su número de establecimiento (por ejemplo, 001).'), ''
    weights = [3,2,7,6,5,4,3,2] if third == 6 else [4,3,2,7,6,5,4,3,2]
    position = 8 if third == 6 else 9
    if int(value[position+1:]) == 0:
        return 'El RUC debe terminar en su número de establecimiento (por ejemplo, 001).', ''
    check = (11-sum(int(n)*w for n,w in zip(value,weights)) % 11) % 11
    return '', ('' if check < 10 and check == int(value[position]) else 'No pudimos comprobar el dígito verificador de este RUC. Confirma que esté escrito correctamente.')


def document_error(value, kind='', strict=False):
    """Error de una cédula o RUC (vacío si es aceptable). Con `strict`, un RUC cuyo dígito verificador no se puede comprobar también es error."""
    error, notice = document_check(value, kind)
    return error or (notice if strict else '')


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
    if fields['document_type']!='pasaporte' and fields['identification'] and (error := document_error(fields['identification'], fields['document_type'] if fields['document_type'] in ('cedula','ruc') else '')):
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
    qr = segno.make_qr(payload, error='m')
    qr.save(stream, kind=kind, scale=8, border=4, dark='#102744', light='#ffffff')
    data = stream.getvalue()
    if kind == 'svg' and b'viewBox' not in data:
        # Mismo tamaño propio, pero escalable: sin viewBox, un SVG mostrado más pequeño se recorta en lugar de reducirse.
        side = (qr.symbol_size(scale=8, border=4)[0])
        data = data.replace(b'<svg ', b'<svg viewBox="0 0 %d %d" ' % (side, side), 1)
    return data


def production_enabled():
    return (os.getenv('APP_ENV') == 'production' and os.getenv('PRODUCTION_ENABLED','').lower() == 'true'
            and os.getenv('APP_URL','').startswith('https://') and os.getenv('SESSION_SECURE','').lower() == 'true')
