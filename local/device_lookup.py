"""Identificación de equipos por número de serie.

Primero se consulta el historial propio de Órdenes Pro. La consulta a fabricantes solo se hace con un servicio
oficial configurado; mientras no exista ninguno, se informa «no disponible» y nunca se deduce un modelo a partir
del formato de la serie.
"""
import re

SERIAL=re.compile(r'[A-Z0-9-]{4,150}')
# Adaptadores oficiales por fabricante. Vacío hasta contar con credenciales autorizadas de cada programa.
MANUFACTURERS={}


def normalize(value):
    return re.sub(r'\s+','',str(value or '')).upper()


def internal(c,serial):
    """Equipos ya ingresados con esa serie, agrupados por cliente, marca y modelo."""
    rows=c.execute("""SELECT d.id device_id,COALESCE(NULLIF(d.category,''),d.type) type,COALESCE(d.brand,'') brand,COALESCE(d.model,'') model,d.serial,COALESCE(d.color,'') color,d.client_id,cl.name client,
        o.id order_id,o.code order_code,o.created_at,s.label status
        FROM devices d JOIN clients cl ON cl.id=d.client_id LEFT JOIN orders o ON o.device_id=d.id LEFT JOIN statuses s ON s.code=o.status
        WHERE upper(replace(COALESCE(d.serial,''),' ',''))=? ORDER BY d.id DESC,o.id DESC LIMIT 200""",(serial,)).fetchall()
    found={}
    for r in rows:
        key=(r['client_id'],r['type'],r['brand'].strip().lower(),r['model'].strip().lower())
        item=found.setdefault(key,{'type':r['type'],'brand':r['brand'],'model':r['model'],'serial':r['serial'],'color':r['color'],'client_id':r['client_id'],'client':r['client'],'orders':0,'last_order':None})
        if r['order_id'] is None:continue
        item['orders']+=1
        if item['last_order'] is None:item['last_order']={'id':r['order_id'],'code':r['order_code'] or 'OP-%05d'%r['order_id'],'created_at':r['created_at'],'status':r['status']}
    return list(found.values())[:5]


def identify(c,value):
    serial=normalize(value)
    if not SERIAL.fullmatch(serial):return 400,{'error':'Indica un número de serie de 4 a 150 caracteres: letras, números y guiones.'}
    matches=internal(c,serial)
    # Sin adaptador oficial no se envía la serie a ningún servicio externo.
    return 200,{'serial':serial,'matches':matches,'manufacturer':{'available':bool(MANUFACTURERS),'message':'' if MANUFACTURERS else 'Identificación automática no disponible'}}
