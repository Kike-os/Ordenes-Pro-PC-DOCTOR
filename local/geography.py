"""Catálogo INEC DPA 2026. Sin consultas externas al recibir equipos."""
import json
from pathlib import Path
import unicodedata

CATALOG = json.loads((Path(__file__).resolve().parent/'data/inec-2026.json').read_text())
METADATA = CATALOG['metadata']
PROVINCES = {r['code']:r for r in CATALOG['provinces']}
CANTONS = {r['code']:r for r in CATALOG['cantons']}
PARISHES = {r['code']:r for r in CATALOG['parishes']}
LOCALITIES = {r['code']:r for r in CATALOG['localities']}


def initialize_catalog(c):
    if c.execute('SELECT 1 FROM geo_catalog WHERE version=?',(METADATA['version'],)).fetchone():
        return
    for table,rows,keys in [
        ('geo_provinces',PROVINCES.values(),('code','name')),
        ('geo_cantons',CANTONS.values(),('code','name','province_code')),
        ('geo_parishes',PARISHES.values(),('code','name','canton_code','kind','locality_code')),
        ('geo_localities',LOCALITIES.values(),('code','name','canton_code','kind'))]:
        c.executemany('INSERT INTO '+table+'('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')',
                      [tuple(r[k] for k in keys) for r in rows])
    c.execute('INSERT INTO geo_catalog VALUES (?,?,?,?,?)',
              (METADATA['version'],METADATA['source'],METADATA['retrieved_at'],METADATA['sha256'],METADATA['url']))


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFD',value.casefold()) if not unicodedata.combining(c))


def search(level, province='', canton='', parish='', query=''):
    if level=='provinces':rows=list(PROVINCES.values())
    elif level=='cantons':rows=[r for r in CANTONS.values() if r['province_code']==province]
    elif level=='parishes':rows=[r for r in PARISHES.values() if r['canton_code']==canton]
    elif level=='localities':
        parent=PARISHES.get(parish,{})
        rows=[r for r in LOCALITIES.values() if r['canton_code']==canton and (not parish or r['code']==parent.get('locality_code'))]
    else:return []
    return sorted((r for r in rows if normalize(query) in normalize(r['name'])),key=lambda r:normalize(r['name']))


def validate_location(fields, errors):
    province=PROVINCES.get(fields['province_code'])
    canton=CANTONS.get(fields['canton_code'])
    parish=PARISHES.get(fields['parish_code'])
    if not province:errors['province']='Selecciona una provincia del catálogo INEC.'
    else:fields['province']=province['name']
    if not canton or canton['province_code']!=fields['province_code']:
        errors['canton']='Selecciona un cantón de la provincia elegida.'
    else:fields['canton']=canton['name']
    if not parish or parish['canton_code']!=fields['canton_code']:
        errors['parish']='Selecciona una parroquia del cantón elegido.'
    else:fields['parish']=parish['name']
    if fields['locality_code']:
        locality=LOCALITIES.get(fields['locality_code'])
        available=search('localities',canton=fields['canton_code'],parish=fields['parish_code'])
        if not locality or locality not in available:errors['city']='La localidad seleccionada no corresponde a esta ubicación.'
        elif normalize(fields['city'])!=normalize(locality['name']):errors['city']='La localidad no coincide con su código.'
    fields['address']=', '.join(v for v in [fields['main_street'],fields['building_number'],fields['secondary_street']] if v)
    fields['geo_version']=METADATA['version']
