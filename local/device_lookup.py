"""Identificación de equipos por número de serie.

Primero se consulta el historial propio de Órdenes Pro. La consulta a fabricantes solo se hace con un adaptador
oficial configurado (device_manufacturers); sin él se informa «no disponible» y nunca se deduce un modelo a partir
del formato de la serie. El catálogo de marcas y portales está en device_brands.
"""
import re

import device_brands
import device_manufacturers

SERIAL=re.compile(r'[A-Z0-9-]{4,150}')


def normalize(value):
    return re.sub(r'\s+','',str(value or '')).upper()


def internal(c,serial):
    """Equipos ya ingresados con esa serie, agrupados por cliente, marca y modelo."""
    rows=c.execute("""SELECT d.id device_id,d.code device_code,o.status status_code,COALESCE(NULLIF(d.kind,''),NULLIF(d.category,''),d.type) type,COALESCE(d.brand,'') brand,COALESCE(d.model,'') model,d.serial,COALESCE(d.color,'') color,d.client_id,cl.name client,
        d.identity_source,d.identity_confirmed_at,u.name confirmed_by,o.id order_id,o.code order_code,o.created_at,s.label status
        FROM devices d JOIN clients cl ON cl.id=d.client_id LEFT JOIN users u ON u.id=d.identity_confirmed_by LEFT JOIN orders o ON o.device_id=d.id LEFT JOIN statuses s ON s.code=o.status
        WHERE upper(replace(COALESCE(d.serial,''),' ',''))=? ORDER BY d.id DESC,o.id DESC LIMIT 200""",(serial,)).fetchall()
    found={}
    for r in rows:
        key=(r['client_id'],r['type'],r['brand'].strip().lower(),r['model'].strip().lower())
        item=found.setdefault(key,{'device_id':r['device_id'],'device_code':r['device_code'] or '','open_order':'','history':[],'type':r['type'],'brand':r['brand'],'model':r['model'],'serial':r['serial'],'color':r['color'],'client_id':r['client_id'],'client':r['client'],'orders':0,'last_order':None,
            'identity_source':r['identity_source'] or '','confirmed_by':r['confirmed_by'] or '','confirmed_at':r['identity_confirmed_at'] or ''})
        if r['order_id'] is None:continue
        item['orders']+=1
        code=r['order_code'] or 'OP-%05d'%r['order_id']
        if len(item['history'])<4:item['history'].append({'id':r['order_id'],'code':code,'created_at':r['created_at'],'status':r['status']})
        # Un ingreso sin entregar del mismo equipo: registrar otro sería duplicarlo.
        if r['status_code']!='entregado' and r['device_id']==item['device_id'] and not item['open_order']:item['open_order']=code
        if item['last_order'] is None:item['last_order']={'id':r['order_id'],'code':r['order_code'] or 'OP-%05d'%r['order_id'],'created_at':r['created_at'],'status':r['status']}
    return list(found.values())[:5]


CACHE_SECONDS=6*3600
_verified={}


def identify(c,value,brand='',allow_external=lambda:True):
    """Primero el historial propio; después, solo un adaptador oficial configurado para la marca indicada."""
    serial=normalize(value)
    if not SERIAL.fullmatch(serial):return 400,{'error':'Indica un número de serie de 4 a 150 caracteres: letras, números y guiones.'}
    matches=internal(c,serial)
    maker=device_brands.find(brand)
    state={'available':False,'state':'unavailable','brand':maker['slug'] if maker else '','message':'Identificación automática no disponible','result':None}
    # La serie solo sale del sistema si no está en el historial, la marca tiene un servicio oficial configurado y no se superó el límite.
    if not matches and maker and maker['slug'] in device_manufacturers.configured():
        state['available']=True
        import time
        cached=_verified.get((maker['slug'],serial))
        if cached and cached[0]>time.time():state.update(state='found',message='Identificado por el servicio oficial de '+maker['name'],result=dict(cached[1],source='fabricante:'+maker['slug']),cached=True)
        elif not allow_external():state.update(state='limited',message='Se alcanzó el límite de consultas al fabricante. Intenta más tarde o continúa manualmente.')
        else:
            try:
                found=device_manufacturers.lookup(maker['slug'],serial)
                if found:
                    if len(_verified)>500:_verified.clear()
                    _verified[(maker['slug'],serial)]=(time.time()+CACHE_SECONDS,found)
                if found:state.update(state='found',message='Identificado por el servicio oficial de '+maker['name'],result=dict(found,source='fabricante:'+maker['slug']))
                else:state.update(state='not_found',message=maker['name']+' no reconoce esta serie.')
            except device_manufacturers.ProviderError as error:
                print('device-lookup',maker['slug'],error.kind,flush=True)
                state.update(state='error',message='El servicio de '+maker['name']+' no está disponible ahora. Continúa con el ingreso manual.')
    # Conflicto: la misma serie figura con marcas distintas en el historial; el técnico debe verificar el equipo.
    brands={device_brands.slug(m['brand']) for m in matches if m['brand'].strip()}
    return 200,{'serial':serial,'matches':matches,'conflict':len(brands)>1,'manufacturer':state}


def source(value):
    """Procedencia válida de la marca y el modelo confirmados por el técnico."""
    value=str(value or '')
    return value if value in ('manual','historial') or re.fullmatch(r'fabricante:[a-z0-9-]{1,30}',value) else ''
