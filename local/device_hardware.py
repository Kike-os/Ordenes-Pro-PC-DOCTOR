"""Lectura de la identidad de un equipo a partir de la salida de una herramienta del propio sistema.

El técnico ejecuta un comando estándar en el equipo recibido (PowerShell/WMIC/systeminfo en Windows, dmidecode en
Linux, system_profiler en macOS) y pega el resultado. Aquí solo se interpreta ese texto: no se ejecuta nada, no se
consulta ningún servicio y no se completa ningún dato que el texto no contenga.
"""
import re

import device_brands

LIMIT=8000
EMPTY={'','none','n/a','na','null','default string','not specified','not available','to be filled by o.e.m.','system product name','system manufacturer','system serial number','system version','no asset information','unknown','0','o.e.m.','oem'}
VENDORS=(('hewlett','HP'),('hp','HP'),('dell','Dell'),('alienware','Alienware'),('lenovo','Lenovo'),('asustek','ASUS'),('asus','ASUS'),('acer','Acer'),('apple','Apple'),('micro-star','MSI'),('msi','MSI'),('samsung','Samsung'),('huawei','Huawei'),('toshiba','Toshiba'),('dynabook','Dynabook'),('sony','Sony'),('lg','LG'),('microsoft','Microsoft'),('gigabyte','Gigabyte'),('razer','Razer'),('fujitsu','Fujitsu'),('panasonic','Panasonic'),('xiaomi','Xiaomi'),('honor','Honor'))
KEYS={
 'vendor':('vendor','manufacturer','system manufacturer','fabricante del sistema','fabricante','systemmanufacturer'),
 'name':('name','product name','system model','modelo el sistema','modelo del sistema','model','systemproductname','model name','nombre del modelo'),
 'version':('version','system version','systemversion','systemfamily','family'),
 'serial':('identifyingnumber','serial number','serialnumber','serial number (system)','número de serie','numero de serie','número de serie (sistema)'),
 'identifier':('model identifier','identificador del modelo'),
 'cpu':('processorname','cpu','model name (cpu)','chip','procesador','nombre del procesador','processor name'),
 'ram':('ram_gb','memory','memoria','total physical memory','cantidad total de memoria física','totalphysicalmemory'),
 'disk':('disk','disco','diskmodel'),
}


def _clean(value):
    value=re.sub(r'\s+',' ',str(value or '')).strip(' \t"\'')
    return '' if value.lower() in EMPTY else value[:150]


def vendor_name(value):
    text=_clean(value)
    if not text:return ''
    low=text.lower()
    for needle,name in VENDORS:
        if re.search(r'(?<![a-z])'+re.escape(needle)+r'(?![a-z])',low):return name
    return re.sub(r'[,.]?\s*\b(inc|corp|corporation|co|ltd|limited|computer|electronics|international)\b\.?','',text,flags=re.I).strip(' ,.')[:60]


def _pairs(text):
    """Pares clave/valor de líneas «Clave : valor» o «Clave=valor», y de la tabla de dos filas de WMIC."""
    pairs=[];lines=[line.rstrip() for line in text.replace('\r','').split('\n')]
    for line in lines:
        match=re.match(r'^\s*([^:=]{2,60}?)\s*[:=]\s*(.*)$',line)
        if match:pairs.append((match[1].strip().lower(),match[2]))
    table=[line for line in lines if line.strip()]
    for head,row in zip(table,table[1:]):
        if ':' in head or '=' in head:continue
        columns=[(m.start(),m.group()) for m in re.finditer(r'\S+',head)]
        if len(columns)>=2 and all(name.lower() in ('vendor','name','version','identifyingnumber','manufacturer','model','serialnumber') for _,name in columns):
            for index,(start,name) in enumerate(columns):
                end=columns[index+1][0] if index+1<len(columns) else None
                pairs.append((name.lower(),row[start:end]))
    return pairs


def parse(text):
    text=str(text or '')[:LIMIT];found={}
    for key,value in _pairs(text):
        value=_clean(value)
        if not value:continue
        for field,names in KEYS.items():
            if key in names and field not in found:found[field]=value
    # «Name» también es la clave del procesador en PowerShell: se reconoce por su contenido.
    for key,value in _pairs(text):
        value=_clean(value)
        if key in ('name','nombre') and re.search(r'\b(intel|amd|ryzen|core|celeron|pentium|xeon|athlon|apple m\d)\b',value,re.I):
            found['cpu']=value
            if found.get('name')==value:found.pop('name')
    for key,value in _pairs(text):
        value=_clean(value)
        if key in KEYS['name'] and 'name' not in found and value!=found.get('cpu'):found['name']=value
    brand=vendor_name(found.get('vendor'))
    # macOS no indica fabricante: solo se asume Apple si el propio informe trae un identificador de modelo Mac.
    if not brand and re.match(r'(MacBook|iMac|Macmini|MacPro|Mac)\w*\d+,\d+$',found.get('identifier','')):brand='Apple'
    name=found.get('name','');version=found.get('version','')
    # Lenovo guarda el nombre comercial en «Version» y el tipo de máquina en «Name».
    model=(version+(' ('+name+')' if name and name.lower() not in version.lower() else '')) if brand=='Lenovo' and version and not re.fullmatch(r'[\d.]+',version) else name
    # El nombre del producto suele repetir la marca («HP ProBook…»): se quita para no duplicarla.
    if brand and model.lower().startswith(brand.lower()+' '):model=model[len(brand)+1:].strip()
    serial=re.sub(r'\s+','',found.get('serial','')).upper()
    if not re.fullmatch(r'[A-Z0-9-]{4,150}',serial):serial=''
    ram=found.get('ram','');number=re.search(r'[\d.,]+',ram)
    if number:
        amount=float(number[0].replace('.','').replace(',','.') if re.search(r'\d\.\d{3}',number[0]) else number[0].replace(',','.'))
        unit=ram.lower()
        gigabytes=amount/1024 if 'mb' in unit else amount/1024**3 if amount>10**8 else amount
        ram='%d GB'%round(gigabytes) if 0<gigabytes<4096 else ''
    else:ram=''
    result={'brand':brand,'model':model[:150],'serial':serial,'cpu':found.get('cpu',''),'ram':ram,'disk':found.get('disk','')}
    result['recognized']=bool(brand or model or serial)
    maker=device_brands.find(brand)
    result['brand_slug']=maker['slug'] if maker else device_brands.slug(brand)
    return result
