"""Inventario de Licencias Digitales: productos, unidades individuales (cuentas o seriales), reservas, pago, autorización y entrega.

Producto = elemento del catálogo (categoría «licencia» o «seguridad») con su logo; sus datos de inventario están en license_products.
Debajo, una unidad por cuenta o serial, con su estado. Un borrador no descuenta nada: al aprobarse el presupuesto se reservan unidades
concretas, sin revelar sus credenciales. Las credenciales solo se liberan cuando el presupuesto está aprobado, el pago está confirmado,
no queda saldo y un administrador autorizó la entrega; el servidor vuelve a comprobarlo todo en cada consulta.

Cifrado de credenciales (solo biblioteca estándar, el mismo esquema que la verificación en dos pasos pero con OTRA clave): clave maestra
de 32 bytes fuera de la base (variable LICENSE_ENCRYPTION_KEY en Vercel; en el servidor local, el archivo license.key 0600 en la carpeta
de datos). De ella se derivan con HMAC-SHA256 la clave de cifrado, la de autenticación y la de huellas. Cifrado en modo contador con
HMAC-SHA256 y autenticación encrypt-then-MAC. La huella (HMAC) del serial o cuenta impide registrarlo dos veces sin guardarlo en claro."""
import base64,hashlib,hmac,json,os,re,secrets,struct
from datetime import date,datetime,timedelta
from pathlib import Path

KINDS={'m365':'Microsoft 365','windows_office':'Windows y Office','antivirus':'Antivirus','otro':'Otro producto digital'}
STATUSES={'disponible':'Disponible','reservada':'Reservada','entregada':'Entregada','anulada':'Anulada','vencida':'Vencida'}
PRODUCT_CATEGORIES=('licencia','seguridad')
# Credenciales (cifradas) y datos visibles de cada tipo. Cada cuenta o serial es un registro individual.
SECRETS={'m365':(('username','Usuario'),('password','Contraseña')),'windows_office':(('key','Clave de activación'),),
         'antivirus':(('serial','Serial o código de activación'),),'otro':(('serial','Serial, clave o código de activación'),)}
FIELDS={'m365':('license_type','devices','activated_at','expires_at'),'windows_office':('edition','license_type','purchased_at'),
        'antivirus':('manufacturer','version','devices','term','expires_at'),'otro':('edition','license_type','devices','term','expires_at')}
FIELD_LABELS={'edition':'Producto y edición','license_type':'Tipo de licencia','manufacturer':'Fabricante','version':'Versión','devices':'Dispositivos',
              'term':'Duración','purchased_at':'Fecha de compra','activated_at':'Fecha de activación','expires_at':'Fecha de vencimiento'}
DATES=('purchased_at','activated_at','expires_at')
LINK_HOURS=72
CODE_MINUTES=10
MAX_CODE_FAILURES=5
MAX_BULK=200
CONTACT={'phone':'+593 98 746 0591','email':'licencias-orig@ecuadorpcdoctor.com'}


class LicenseError(ValueError):
    def __init__(self,message,status=400,fields=None):
        super().__init__(message);self.status=status;self.fields=fields or {}


# ---- Cifrado ----------------------------------------------------------------------------------------------------------
def master_key():
    raw=os.getenv('LICENSE_ENCRYPTION_KEY','').strip()
    if raw:
        key=base64.urlsafe_b64decode(raw+'='*(-len(raw)%4))
        if len(key)<32:raise LicenseError('La clave de cifrado de licencias no es válida.',503)
        return key[:32]
    if os.getenv('VERCEL'):raise LicenseError('Falta la clave de cifrado de licencias en el servidor.',503)
    import app
    path=Path(app.DATA)/'license.key'
    if not path.exists():
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as handle:handle.write(secrets.token_bytes(32))
    return path.read_bytes()[:32]


def _keys():
    key=master_key()
    return tuple(hmac.new(key,label,hashlib.sha256).digest() for label in (b'ordenes-pro:licencias:cifrado',b'ordenes-pro:licencias:autenticacion',b'ordenes-pro:licencias:huella'))


def _stream(key,nonce,length):
    out=b'';counter=0
    while len(out)<length:
        out+=hmac.new(key,nonce+struct.pack('>Q',counter),hashlib.sha256).digest();counter+=1
    return out[:length]


def seal(values):
    enc,mac,_=_keys();nonce=secrets.token_bytes(16);plain=json.dumps(values,ensure_ascii=False,sort_keys=True).encode()
    body=bytes(a^b for a,b in zip(plain,_stream(enc,nonce,len(plain))))
    tag=hmac.new(mac,b'lic1'+nonce+body,hashlib.sha256).digest()
    return 'lic1:'+base64.urlsafe_b64encode(nonce+body+tag).decode().rstrip('=')


def unseal(value):
    value=str(value or '')
    if not value.startswith('lic1:'):raise LicenseError('Credencial guardada no válida.',500)
    raw=base64.urlsafe_b64decode(value[5:]+'='*(-len(value[5:])%4));nonce,body,tag=raw[:16],raw[16:-32],raw[-32:]
    enc,mac,_=_keys()
    if not hmac.compare_digest(tag,hmac.new(mac,b'lic1'+nonce+body,hashlib.sha256).digest()):raise LicenseError('La credencial guardada no se pudo verificar.',500)
    return json.loads(bytes(a^b for a,b in zip(body,_stream(enc,nonce,len(body)))).decode())


def normalized(kind,values):
    """Valor que identifica la cuenta o serial (para no registrarlo dos veces): la cuenta en minúsculas o la clave sin espacios ni guiones."""
    if kind=='m365':return 'm365:'+values['username'].strip().lower()
    main=values.get('key') or values.get('serial') or ''
    return 'key:'+re.sub(r'[\s-]+','',main).upper()


def fingerprint(kind,values):
    return hmac.new(_keys()[2],normalized(kind,values).encode(),hashlib.sha256).hexdigest()


def _hash(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


# ---- Utilidades -------------------------------------------------------------------------------------------------------
def stamp(now):return now.isoformat(timespec='seconds')


def event(c,name,now,detail='',unit=None,product=None,delivery=None,order=None,client=None,user=None,actor=''):
    c.execute('INSERT INTO license_events(unit_id,product_id,delivery_id,order_id,client_id,event,detail,actor_id,actor,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
              (unit,product,delivery,order,client,name,detail[:500],user['id'] if user else None,actor or ('' if user else 'sistema'),stamp(now)))


def expire(c,now):
    """Unidades disponibles cuyo vencimiento ya pasó: pasan a «Vencida» (no se venden). Las reservadas o entregadas no cambian."""
    today=now.date().isoformat()
    rows=c.execute("SELECT id,product_id FROM license_units WHERE status='disponible' AND expires_at!='' AND expires_at<?",(today,)).fetchall()
    for row in rows:
        c.execute("UPDATE license_units SET status='vencida',updated_at=? WHERE id=? AND status='disponible'",(stamp(now),row['id']))
        event(c,'vencida',now,'La licencia superó su fecha de vencimiento sin venderse.',row['id'],row['product_id'])
    return len(rows)


def _product(c,product_id):
    row=c.execute("SELECT i.id,i.name,i.category,i.brand,i.price_cents,i.available,p.kind,p.supplier,p.purchase_cents,p.term,p.devices FROM catalog_items i LEFT JOIN license_products p ON p.item_id=i.id WHERE i.id=?",(product_id,)).fetchone()
    if not row or row['category'] not in PRODUCT_CATEGORIES:raise LicenseError('Producto de licencia no disponible.',404)
    return dict(row)


def _text(data,key,limit,label):
    value=re.sub(r'\s+',' ',str(data.get(key) or '')).strip()
    if len(value)>limit:raise LicenseError('%s admite hasta %d caracteres.'%(label,limit),fields={key:'Texto demasiado largo.'})
    return value


def _cents(value,key,label):
    text=str(value if value is not None else '').strip().replace(',','.')
    if not text:return None
    if not re.fullmatch(r'\d{1,7}(\.\d{1,2})?',text):raise LicenseError('Indica %s en USD con hasta dos decimales.'%label,fields={key:'Importe no válido.'})
    whole,_,part=text.partition('.');return int(whole)*100+int((part+'00')[:2])


def _date(value,key):
    text=str(value or '').strip()
    if not text:return ''
    try:
        if date.fromisoformat(text).isoformat()!=text:raise ValueError
    except ValueError:raise LicenseError('Indica una fecha válida.',fields={key:'Fecha no válida.'})
    return text


def _devices(value,key='devices'):
    text=str(value if value is not None else '').strip()
    if not text:return None
    if not text.isdigit() or not 1<=int(text)<=1000:raise LicenseError('Indica la cantidad de dispositivos (1 a 1000).',fields={key:'Cantidad no válida.'})
    return int(text)


# ---- Productos --------------------------------------------------------------------------------------------------------
def products(c,now):
    """Productos de licencia del catálogo con sus existencias por estado (calculadas a partir de las unidades individuales)."""
    today=now.date().isoformat()
    rows=[dict(r) for r in c.execute("SELECT i.id,i.code,i.name,i.category,i.brand,i.price_cents,i.available,i.license_term,i.devices catalog_devices,(SELECT updated_at FROM catalog_images g WHERE g.item_id=i.id) image,"
                                     "p.kind,p.supplier,p.purchase_cents,p.term,p.devices FROM catalog_items i LEFT JOIN license_products p ON p.item_id=i.id WHERE i.category IN ('licencia','seguridad') ORDER BY i.name COLLATE NOCASE")]
    counts={}
    for r in c.execute("SELECT product_id,CASE WHEN status='disponible' AND expires_at!='' AND expires_at<? THEN 'vencida' ELSE status END state,COUNT(*) n FROM license_units GROUP BY product_id,state",(today,)):
        counts.setdefault(r['product_id'],{})[r['state']]=r['n']
    for row in rows:
        row['image']=row['image'] or '';row['managed']=bool(row['kind']);row['kind_label']=KINDS.get(row['kind'] or '','Sin configurar')
        row['stock']={key:counts.get(row['id'],{}).get(key,0) for key in STATUSES}
        row['pending']=sum(item['missing'] for item in pending_items(c,row['id']))
    return rows


def save_product(c,data,user,now):
    item=str(data.get('item_id',''))
    if not item.isdigit():raise LicenseError('Selecciona el producto del catálogo.',fields={'item_id':'Producto no válido.'})
    product=_product(c,int(item));kind=str(data.get('kind',''))
    if kind not in KINDS:raise LicenseError('Selecciona el tipo de licencia.',fields={'kind':'Tipo no válido.'})
    if product['kind'] and product['kind']!=kind and c.execute('SELECT 1 FROM license_units WHERE product_id=?',(product['id'],)).fetchone():
        raise LicenseError('Este producto ya tiene licencias registradas: su tipo no se puede cambiar.',409,{'kind':'Tipo fijo.'})
    values=(_text(data,'supplier',120,'El proveedor'),_cents(data.get('purchase_price'),'purchase_price','el precio de compra'),_text(data,'term',60,'La duración'),_devices(data.get('devices')))
    c.execute('INSERT INTO license_products(item_id,kind,supplier,purchase_cents,term,devices,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET '
              'kind=excluded.kind,supplier=excluded.supplier,purchase_cents=excluded.purchase_cents,term=excluded.term,devices=excluded.devices,updated_at=excluded.updated_at,updated_by=excluded.updated_by',
              (product['id'],kind,*values,stamp(now),user['id']))
    event(c,'producto',now,'Datos de inventario del producto «%s» guardados (%s).'%(product['name'],KINDS[kind]),product=product['id'],user=user)
    return product['id']


# ---- Registro de licencias --------------------------------------------------------------------------------------------
def _clean_unit(kind,data,partial=False):
    """Datos visibles de la unidad según su tipo. Los campos que no corresponden al tipo se ignoran."""
    out={}
    for key in FIELDS[kind]:
        if key in DATES:out[key]=_date(data.get(key),key)
        elif key=='devices':out[key]=_devices(data.get(key))
        else:out[key]=_text(data,key,120,FIELD_LABELS[key])
    if out.get('activated_at') and out.get('expires_at') and out['expires_at']<out['activated_at']:
        raise LicenseError('La fecha de vencimiento no puede ser anterior a la de activación.',fields={'expires_at':'Revisa la fecha.'})
    return out


def _clean_secret(kind,data):
    values={}
    for key,label in SECRETS[kind]:
        raw=str(data.get(key) or '')
        value=raw if key=='password' else re.sub(r'\s+',' ',raw).strip()
        if not value or len(value)>300 or '\n' in value:raise LicenseError('Indica %s (hasta 300 caracteres).'%label.lower(),fields={key:'Dato obligatorio.'})
        values[key]=value
    if kind=='m365' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values['username']):raise LicenseError('El usuario de Microsoft 365 debe ser una cuenta de correo.',fields={'username':'Cuenta no válida.'})
    if kind!='m365' and len(re.sub(r'[\s-]+','',values[SECRETS[kind][0][0]]))<5:raise LicenseError('La clave o serial es demasiado corta.',fields={SECRETS[kind][0][0]:'Revisa el dato.'})
    return values


def _insert_unit(c,product,kind,fields,values,batch,user,now,notes=''):
    mark=fingerprint(kind,values)
    found=c.execute('SELECT code FROM license_units WHERE fingerprint=?',(mark,)).fetchone()
    if found:raise LicenseError('Esta cuenta o clave ya está registrada (%s).'%found['code'],409,{SECRETS[kind][0][0]:'Duplicada.'})
    unit=c.execute('INSERT INTO license_units(product_id,batch_id,kind,edition,license_type,manufacturer,version,devices,term,purchased_at,activated_at,expires_at,secret,fingerprint,notes,created_by,created_at,updated_at) '
                   'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (product['id'],batch,kind,fields.get('edition',''),fields.get('license_type',''),fields.get('manufacturer',''),fields.get('version',''),fields.get('devices',product.get('devices')),
                    fields.get('term') or product.get('term') or '',fields.get('purchased_at',''),fields.get('activated_at',''),fields.get('expires_at',''),seal(values),mark,notes,user['id'],stamp(now),stamp(now))).lastrowid
    status='vencida' if fields.get('expires_at') and fields['expires_at']<now.date().isoformat() else 'disponible'
    if status=='vencida':c.execute("UPDATE license_units SET status='vencida' WHERE id=?",(unit,))
    event(c,'registrada',now,'Licencia registrada en el inventario%s.'%(' (ya vencida)' if status=='vencida' else ''),unit,product['id'],user=user)
    return unit


def _batch(c,product,data,quantity,user,now):
    return c.execute('INSERT INTO license_batches(product_id,supplier,unit_cost_cents,purchased_at,invoice,quantity,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
                     (product['id'],_text(data,'supplier',120,'El proveedor') or product.get('supplier') or '',_cents(data.get('unit_cost'),'unit_cost','el costo unitario') if data.get('unit_cost') not in (None,'') else product.get('purchase_cents'),
                      _date(data.get('batch_date') or data.get('purchased_at'),'batch_date'),_text(data,'invoice',80,'La factura'),quantity,user['id'],stamp(now))).lastrowid


def _managed(c,product_id):
    product=_product(c,product_id)
    if not product['kind']:raise LicenseError('Configura primero el tipo de licencia de este producto en «Administrar productos y logos».',409,{'product_id':'Producto sin configurar.'})
    return product


def register(c,data,user,now):
    """Una licencia: sus datos visibles y su credencial cifrada. Después se reservan automáticamente las ventas aprobadas que esperaban existencias."""
    pid=str(data.get('product_id',''))
    if not pid.isdigit():raise LicenseError('Selecciona el producto.',fields={'product_id':'Producto no válido.'})
    product=_managed(c,int(pid));kind=product['kind']
    fields=_clean_unit(kind,data);values=_clean_secret(kind,data)
    batch=_batch(c,product,data,1,user,now)
    unit=_insert_unit(c,product,kind,fields,values,batch,user,now,_text(data,'notes',300,'Las observaciones'))
    fill_pending(c,product['id'],now,user)
    return unit


def register_many(c,data,user,now):
    """Varias licencias del mismo producto: una por línea («usuario;contraseña» en Microsoft 365, la clave o serial en los demás).
    Todo o nada: si una línea no es válida o está repetida, no se registra ninguna."""
    pid=str(data.get('product_id',''))
    if not pid.isdigit():raise LicenseError('Selecciona el producto.',fields={'product_id':'Producto no válido.'})
    product=_managed(c,int(pid));kind=product['kind'];fields=_clean_unit(kind,data)
    lines=[line.strip() for line in str(data.get('lines') or '').replace('\r','').split('\n') if line.strip()]
    if not lines:raise LicenseError('Escribe al menos una licencia (una por línea).',fields={'lines':'Sin licencias.'})
    if len(lines)>MAX_BULK:raise LicenseError('Registra hasta %d licencias por vez.'%MAX_BULK,fields={'lines':'Demasiadas líneas.'})
    parsed=[];marks=set()
    for number,line in enumerate(lines,1):
        if kind=='m365':
            if ';' not in line:raise LicenseError('Línea %d: usa el formato usuario;contraseña.'%number,fields={'lines':'Formato no válido.'})
            username,password=line.split(';',1);raw={'username':username,'password':password}
        else:raw={SECRETS[kind][0][0]:line}
        try:values=_clean_secret(kind,raw)
        except LicenseError as error:raise LicenseError('Línea %d: %s'%(number,error),fields={'lines':'Línea %d no válida.'%number})
        mark=fingerprint(kind,values)
        if mark in marks:raise LicenseError('Línea %d: está repetida en la lista.'%number,fields={'lines':'Línea repetida.'})
        found=c.execute('SELECT code FROM license_units WHERE fingerprint=?',(mark,)).fetchone()
        if found:raise LicenseError('Línea %d: ya está registrada (%s).'%(number,found['code']),409,{'lines':'Licencia duplicada.'})
        marks.add(mark);parsed.append(values)
    batch=_batch(c,product,data,len(parsed),user,now)
    units=[_insert_unit(c,product,kind,fields,values,batch,user,now) for values in parsed]
    fill_pending(c,product['id'],now,user)
    return units


def unit_row(c,unit_id):
    row=c.execute('SELECT * FROM license_units WHERE id=?',(unit_id,)).fetchone()
    if not row:raise LicenseError('Licencia no disponible.',404)
    return dict(row)


def edit(c,unit_id,data,user,now):
    """Corrige datos de una licencia que no se ha entregado. La credencial solo se reemplaza si se escribe una nueva."""
    unit=unit_row(c,unit_id)
    if unit['status'] in ('entregada','anulada'):raise LicenseError('Una licencia %s no se modifica.'%STATUSES[unit['status']].lower(),409)
    kind=unit['kind'];fields=_clean_unit(kind,data);changes=[]
    product=_product(c,unit['product_id'])
    secret,mark=unit['secret'],unit['fingerprint']
    if any(str(data.get(key) or '').strip() for key,_ in SECRETS[kind]):
        values=_clean_secret(kind,data);mark=fingerprint(kind,values)
        other=c.execute('SELECT code FROM license_units WHERE fingerprint=? AND id!=?',(mark,unit_id)).fetchone()
        if other:raise LicenseError('Esa cuenta o clave ya está registrada (%s).'%other['code'],409)
        secret=seal(values);changes.append('credencial reemplazada')
    columns=['edition','license_type','manufacturer','version','devices','term','purchased_at','activated_at','expires_at']
    current={key:fields.get(key,unit[key]) for key in columns}
    changes+=[FIELD_LABELS[key].lower() for key in columns if current[key]!=unit[key]]
    notes=_text(data,'notes',300,'Las observaciones') if 'notes' in data else unit['notes']
    if data.get('activated') in (True,False) and bool(unit['activated'])!=data['activated']:changes.append('marcada como activada' if data['activated'] else 'activación retirada')
    activated=int(data['activated']) if data.get('activated') in (True,False) else unit['activated']
    status=unit['status']
    if status in ('disponible','vencida'):status='vencida' if current['expires_at'] and current['expires_at']<now.date().isoformat() else 'disponible'
    c.execute('UPDATE license_units SET edition=?,license_type=?,manufacturer=?,version=?,devices=?,term=?,purchased_at=?,activated_at=?,expires_at=?,secret=?,fingerprint=?,notes=?,activated=?,status=?,updated_at=? WHERE id=?',
              (*[current[key] for key in columns],secret,mark,notes,activated,status,stamp(now),unit_id))
    event(c,'editada',now,'Datos corregidos: '+(', '.join(changes) if changes else 'sin cambios')+'.',unit_id,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)
    if status=='disponible':fill_pending(c,product['id'],now,user)


def void(c,unit_id,reason,user,now):
    unit=unit_row(c,unit_id);reason=str(reason or '').strip()
    if unit['status'] in ('entregada','anulada'):raise LicenseError('Una licencia %s no se anula.'%STATUSES[unit['status']].lower(),409)
    if len(reason)<5:raise LicenseError('Indica el motivo de la anulación.',fields={'reason':'Motivo obligatorio.'})
    c.execute("UPDATE license_units SET status='anulada',delivery_id=NULL,updated_at=? WHERE id=?",(stamp(now),unit_id))
    event(c,'anulada',now,'Registro invalidado. Motivo: '+reason[:300],unit_id,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)


def release(c,unit_id,user,now):
    """Anula la reserva: la licencia vuelve a estar disponible solo si no fue activada ni entregada."""
    unit=unit_row(c,unit_id)
    if unit['status']!='reservada':raise LicenseError('Esta licencia no está reservada.',409)
    if unit['delivery_id'] and c.execute("SELECT 1 FROM license_deliveries WHERE id=? AND status!='anulada'",(unit['delivery_id'],)).fetchone():
        raise LicenseError('El pago de esta reserva ya fue confirmado: anula primero esa confirmación.',409)
    if unit['activated']:raise LicenseError('La licencia ya fue activada: no vuelve al inventario. Anúlala si no se usará.',409)
    expired=unit['expires_at'] and unit['expires_at']<now.date().isoformat()
    c.execute("UPDATE license_units SET status=?,quote_id=NULL,quote_item_id=NULL,order_id=NULL,client_id=NULL,delivery_id=NULL,reserved_at='',updated_at=? WHERE id=?",('vencida' if expired else 'disponible',stamp(now),unit_id))
    event(c,'reserva_anulada',now,'Reserva anulada: la licencia vuelve a estar %s.'%('vencida' if expired else 'disponible'),unit_id,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)


# ---- Reservas desde presupuestos --------------------------------------------------------------------------------------
def pending_items(c,product_id=None,order_id=None):
    """Partidas aprobadas de productos con inventario que aún no tienen todas sus unidades reservadas (las más antiguas primero)."""
    sql=("SELECT q.id quote_id,q.code quote_code,q.order_id,q.decided_at,i.id item_id,i.catalog_id product_id,i.quantity,i.description,"
         "(SELECT COUNT(*) FROM license_units u WHERE u.quote_item_id=i.id AND u.status IN ('reservada','entregada')) assigned "
         "FROM quote_items i JOIN quotes q ON q.id=i.quote_id JOIN license_products p ON p.item_id=i.catalog_id "
         "WHERE i.status='aprobado' AND q.status IN ('aprobado','parcial') AND q.deleted_at=''")
    args=[]
    if product_id is not None:sql+=' AND i.catalog_id=?';args.append(product_id)
    if order_id is not None:sql+=' AND q.order_id=?';args.append(order_id)
    rows=[dict(r,missing=r['quantity']-r['assigned']) for r in c.execute(sql+' ORDER BY q.decided_at,q.id,i.position',args)]
    return [row for row in rows if row['missing']>0]


def _client_of(c,order_id):
    row=c.execute('SELECT d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?',(order_id,)).fetchone()
    return row['client_id'] if row else None


def _reserve_item(c,item,now,user=None,actor=''):
    today=now.date().isoformat();done=0
    # Primero las que vencen antes (y las que no vencen, al final). La condición del UPDATE evita vender dos veces la misma unidad.
    for unit in c.execute("SELECT id FROM license_units WHERE product_id=? AND status='disponible' AND (expires_at='' OR expires_at>=?) ORDER BY expires_at='',expires_at,id LIMIT ?",(item['product_id'],today,item['missing'])).fetchall():
        client=_client_of(c,item['order_id'])
        if c.execute("UPDATE license_units SET status='reservada',quote_id=?,quote_item_id=?,order_id=?,client_id=?,reserved_at=?,updated_at=? WHERE id=? AND status='disponible'",
                     (item['quote_id'],item['item_id'],item['order_id'],client,stamp(now),stamp(now),unit['id'])).rowcount:
            done+=1;event(c,'reservada',now,'Reservada para el presupuesto %s.'%item['quote_code'],unit['id'],item['product_id'],order=item['order_id'],client=client,user=user,actor=actor)
    return done


def reserve_for_quote(c,quote,now,user=None,actor=''):
    """Al aprobarse un presupuesto: reserva unidades concretas para cada partida de licencia aprobada. Lo que falte queda «pendiente de existencias»."""
    expire(c,now);reserved=missing=0
    for item in pending_items(c,order_id=quote['order_id']):
        if item['quote_id']!=quote['id']:continue
        got=_reserve_item(c,item,now,user,actor);reserved+=got;missing+=item['missing']-got
    return {'reserved':reserved,'missing':missing}


def fill_pending(c,product_id,now,user=None):
    """Con existencias nuevas, se reservan las ventas aprobadas que esperaban (por orden de aprobación)."""
    total=0
    for item in pending_items(c,product_id=product_id):
        total+=_reserve_item(c,item,now,user)
    return total


# ---- Pago, autorización y entrega -------------------------------------------------------------------------------------
def _order_units(c,order_id,delivery_id=None):
    sql="SELECT u.*,i.name product_name FROM license_units u JOIN catalog_items i ON i.id=u.product_id WHERE u.order_id=?"
    args=[order_id]
    if delivery_id is not None:sql+=' AND u.delivery_id=?';args.append(delivery_id)
    return [dict(r) for r in c.execute(sql+' ORDER BY u.id',args)]


def blockers(c,order_id,units):
    """Motivos por los que NO se pueden liberar las credenciales. Lista vacía = se puede continuar. Se evalúa siempre en el servidor."""
    import equipment
    reasons=[]
    if not units:reasons.append('No hay licencias reservadas pendientes de entrega en esta orden.')
    for unit in units:
        row=c.execute("SELECT q.status,i.status item_status FROM quote_items i JOIN quotes q ON q.id=i.quote_id WHERE i.id=?",(unit['quote_item_id'],)).fetchone()
        if not row or row['status'] not in ('aprobado','parcial') or row['item_status']!='aprobado':
            reasons.append('El presupuesto de %s no está aprobado.'%unit['code']);break
    balance=equipment.money(c,order_id)['balance_cents']
    if balance>0:reasons.append('La orden tiene un saldo pendiente de %s: registra el pago completo antes de entregar.'%equipment.usd(balance))
    return reasons


def confirm_payment(c,order_id,user,now):
    """«Confirmar pago»: administración comprueba que el pago está completo. Agrupa las licencias reservadas de la orden en una entrega."""
    import equipment
    if user['role']!='administrador':raise LicenseError('Solo administración puede confirmar pagos de licencias.',403)
    if c.execute("SELECT 1 FROM license_deliveries WHERE order_id=? AND status='pago_confirmado'",(order_id,)).fetchone():
        raise LicenseError('El pago de esta orden ya está confirmado y espera la autorización de entrega.',409)
    units=[u for u in _order_units(c,order_id) if u['status']=='reservada' and not u['delivery_id']]
    problems=blockers(c,order_id,units)
    if problems:raise LicenseError(' '.join(problems),409)
    client=_client_of(c,order_id)
    delivery=c.execute("INSERT INTO license_deliveries(order_id,client_id,status,payment_confirmed_by,payment_confirmed_at,balance_cents,created_at,updated_at) VALUES (?,?,'pago_confirmado',?,?,?,?,?)",
                       (order_id,client,user['id'],stamp(now),equipment.money(c,order_id)['balance_cents'],stamp(now),stamp(now))).lastrowid
    for unit in units:c.execute('UPDATE license_units SET delivery_id=?,updated_at=? WHERE id=?',(delivery,stamp(now),unit['id']))
    event(c,'pago_confirmado',now,'Pago completo confirmado para %d %s.'%(len(units),'licencia' if len(units)==1 else 'licencias'),delivery=delivery,order=order_id,client=client,user=user)
    return delivery


def delivery_row(c,delivery_id):
    row=c.execute('SELECT * FROM license_deliveries WHERE id=?',(delivery_id,)).fetchone()
    if not row:raise LicenseError('Entrega no disponible.',404)
    return dict(row)


def authorize(c,delivery_id,user,now):
    """«Autorizar entrega»: administración libera las credenciales. Se vuelven a comprobar todas las condiciones. Devuelve el enlace privado."""
    if user['role']!='administrador':raise LicenseError('Solo administración puede autorizar la entrega de licencias.',403)
    delivery=delivery_row(c,delivery_id)
    if delivery['status']!='pago_confirmado':raise LicenseError('Esta entrega no está pendiente de autorización.',409)
    units=_order_units(c,delivery['order_id'],delivery_id)
    if not units or any(u['status']!='reservada' for u in units):raise LicenseError('Las licencias de esta entrega ya no están reservadas.',409)
    problems=blockers(c,delivery['order_id'],units)
    if problems:raise LicenseError(' '.join(problems),409)
    token=secrets.token_urlsafe(32);moment=stamp(now)
    for unit in units:
        if not c.execute("UPDATE license_units SET status='entregada',delivered_at=?,client_id=?,updated_at=? WHERE id=? AND status='reservada'",(moment,delivery['client_id'],moment,unit['id'])).rowcount:
            raise LicenseError('Una licencia cambió de estado mientras se autorizaba. Vuelve a intentarlo.',409)
        event(c,'entregada',now,'Entrega autorizada por administración.',unit['id'],unit['product_id'],delivery_id,delivery['order_id'],delivery['client_id'],user)
    c.execute("UPDATE license_deliveries SET status='autorizada',authorized_by=?,authorized_at=?,token_hash=?,token_expires_at=?,updated_at=? WHERE id=?",
              (user['id'],moment,_hash(token),stamp(now+timedelta(hours=LINK_HOURS)),moment,delivery_id))
    event(c,'entrega_autorizada',now,'Entrega autorizada: %d %s para el cliente. Enlace privado válido %d horas.'%(len(units),'licencia' if len(units)==1 else 'licencias',LINK_HOURS),delivery=delivery_id,order=delivery['order_id'],client=delivery['client_id'],user=user)
    return token


def void_confirmation(c,delivery_id,reason,user,now):
    if user['role']!='administrador':raise LicenseError('Solo administración puede anular la confirmación del pago.',403)
    delivery=delivery_row(c,delivery_id);reason=str(reason or '').strip()
    if delivery['status']!='pago_confirmado':raise LicenseError('Solo se anula una confirmación de pago todavía no autorizada.',409)
    if len(reason)<5:raise LicenseError('Indica el motivo.',fields={'reason':'Motivo obligatorio.'})
    c.execute("UPDATE license_deliveries SET status='anulada',voided_by=?,voided_at=?,void_reason=?,updated_at=? WHERE id=?",(user['id'],stamp(now),reason[:300],stamp(now),delivery_id))
    c.execute("UPDATE license_units SET delivery_id=NULL,updated_at=? WHERE delivery_id=? AND status='reservada'",(stamp(now),delivery_id))
    event(c,'pago_anulado',now,'Confirmación de pago anulada. Motivo: '+reason[:300],delivery=delivery_id,order=delivery['order_id'],client=delivery['client_id'],user=user)


def renew_link(c,delivery_id,user,now):
    if user['role']!='administrador':raise LicenseError('Solo administración puede generar el enlace de entrega.',403)
    delivery=delivery_row(c,delivery_id)
    if delivery['status']!='autorizada':raise LicenseError('La entrega no está autorizada.',409)
    token=secrets.token_urlsafe(32)
    c.execute("UPDATE license_deliveries SET token_hash=?,token_expires_at=?,code_hash='',code_expires_at='',code_failures=0,updated_at=? WHERE id=?",(_hash(token),stamp(now+timedelta(hours=LINK_HOURS)),stamp(now),delivery_id))
    event(c,'enlace_renovado',now,'Nuevo enlace privado de entrega (el anterior deja de funcionar).',delivery=delivery_id,order=delivery['order_id'],client=delivery['client_id'],user=user)
    return token


# ---- Consulta privada de credenciales ---------------------------------------------------------------------------------
def lookup(c,token,now):
    """Entrega autorizada del enlace, o None si no existe, venció o fue reemplazado."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{30,80}',token or ''):return None
    row=c.execute("SELECT * FROM license_deliveries WHERE token_hash=? AND status='autorizada'",(_hash(token),)).fetchone()
    if not row or datetime.fromisoformat(row['token_expires_at'])<now:return None
    return dict(row)


def _same_identification(a,b):
    clean=lambda value:re.sub(r'[\s.-]+','',str(value or '')).upper()
    return bool(clean(a)) and hmac.compare_digest(clean(a),clean(b))


def request_code(c,delivery,identification,now):
    """Paso 1: si la identificación coincide con la del cliente y tiene correo registrado, devuelve (correo, código) para enviarlo. Si no, None.
    La respuesta pública es siempre la misma: no revela si coincidió."""
    if delivery['code_failures']>=MAX_CODE_FAILURES:return None
    client=c.execute('SELECT identification,email FROM clients WHERE id=?',(delivery['client_id'],)).fetchone()
    if not client or not _same_identification(identification,client['identification']):
        c.execute('UPDATE license_deliveries SET code_failures=code_failures+1,updated_at=? WHERE id=?',(stamp(now),delivery['id']));return None
    email=(client['email'] or '').strip()
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+',email):return None
    code='%06d'%secrets.randbelow(1000000)
    c.execute('UPDATE license_deliveries SET code_hash=?,code_expires_at=?,updated_at=? WHERE id=?',(_hash(str(delivery['id'])+':'+code),stamp(now+timedelta(minutes=CODE_MINUTES)),stamp(now),delivery['id']))
    event(c,'codigo_enviado',now,'Código de acceso enviado al correo registrado del cliente.',delivery=delivery['id'],order=delivery['order_id'],client=delivery['client_id'],actor='cliente')
    return email,code


def verify_code(c,delivery,code,now,origin=''):
    """Paso 2: con el código correcto (un solo uso) y todas las condiciones vigentes, devuelve la tarjeta privada con credenciales. Si no, None."""
    code=re.sub(r'\D','',str(code or ''))
    if delivery['code_failures']>=MAX_CODE_FAILURES or not delivery['code_hash'] or not delivery['code_expires_at'] or datetime.fromisoformat(delivery['code_expires_at'])<now:return None
    if len(code)!=6 or not hmac.compare_digest(delivery['code_hash'],_hash(str(delivery['id'])+':'+code)):
        c.execute('UPDATE license_deliveries SET code_failures=code_failures+1,updated_at=? WHERE id=?',(stamp(now),delivery['id']));return None
    units=_order_units(c,delivery['order_id'],delivery['id'])
    # Nueva comprobación en el servidor: aprobado, sin saldo y entregado. Si algo cambió (por ejemplo, un pago anulado), no se revela nada.
    import equipment
    if not units or any(u['status']!='entregada' for u in units) or equipment.money(c,delivery['order_id'])['balance_cents']>0:return None
    c.execute("UPDATE license_deliveries SET code_hash='',code_expires_at='',reveal_count=reveal_count+1,last_revealed_at=?,updated_at=? WHERE id=?",(stamp(now),stamp(now),delivery['id']))
    event(c,'credenciales_consultadas',now,'El cliente consultó sus credenciales por el enlace privado.'+(' Origen: '+origin[:80] if origin else ''),delivery=delivery['id'],order=delivery['order_id'],client=delivery['client_id'],actor='cliente')
    return card(c,delivery['id'],private=True)


def admin_reveal(c,unit_id,user,now):
    """Credencial de una unidad para administración (registro y soporte). Queda registrada cada consulta."""
    if user['role']!='administrador':raise LicenseError('Acceso no permitido.',403)
    unit=unit_row(c,unit_id)
    event(c,'credenciales_consultadas',now,'Credencial consultada por administración.',unit_id,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)
    values=unseal(unit['secret'])
    return [{'key':key,'label':label,'value':values.get(key,'')} for key,label in SECRETS[unit['kind']]]


def card(c,delivery_id,private=False):
    """Datos de la tarjeta de entrega. La versión pública no incluye usuarios, contraseñas ni seriales."""
    delivery=delivery_row(c,delivery_id)
    client=c.execute('SELECT name FROM clients WHERE id=?',(delivery['client_id'],)).fetchone()
    order=c.execute("SELECT COALESCE(code,'OP-'||printf('%05d',id)) code FROM orders WHERE id=?",(delivery['order_id'],)).fetchone()
    items=[]
    for unit in _order_units(c,delivery['order_id'],delivery_id):
        item={'unit_code':unit['code'],'product_id':unit['product_id'],'product':unit['product_name'],'kind':KINDS[unit['kind']],'devices':unit['devices'],'term':unit['term'],
              'expires_at':unit['expires_at'],'activated_at':unit['activated_at'],'edition':unit['edition'],'license_type':unit['license_type'],'manufacturer':unit['manufacturer'],'version':unit['version'],
              'has_logo':bool(c.execute('SELECT 1 FROM catalog_images WHERE item_id=?',(unit['product_id'],)).fetchone())}
        if private:
            values=unseal(unit['secret']);item['credentials']=[{'label':label,'value':values.get(key,'')} for key,label in SECRETS[unit['kind']]]
        items.append(item)
    return {'delivery_id':delivery_id,'client':client['name'] if client else '','order':order['code'] if order else '','delivered_at':delivery['authorized_at'],'status':delivery['status'],
            'items':items,'contact':CONTACT,'private':private}


# ---- Consultas para la interfaz ---------------------------------------------------------------------------------------
def units(c,now,product_id=None,status='',query=''):
    today=now.date().isoformat()
    sql=("SELECT u.id,u.code,u.product_id,i.name product,u.kind,u.edition,u.license_type,u.manufacturer,u.version,u.devices,u.term,u.purchased_at,u.activated_at,u.expires_at,u.activated,u.notes,"
         "CASE WHEN u.status='disponible' AND u.expires_at!='' AND u.expires_at<? THEN 'vencida' ELSE u.status END status,u.reserved_at,u.delivered_at,u.created_at,"
         "q.code quote_code,COALESCE(o.code,CASE WHEN o.id IS NULL THEN '' ELSE 'OP-'||printf('%05d',o.id) END) order_code,u.order_id,COALESCE(cl.name,'') client,b.supplier batch_supplier,b.invoice "
         "FROM license_units u JOIN catalog_items i ON i.id=u.product_id LEFT JOIN quotes q ON q.id=u.quote_id LEFT JOIN orders o ON o.id=u.order_id LEFT JOIN clients cl ON cl.id=u.client_id LEFT JOIN license_batches b ON b.id=u.batch_id WHERE 1=1")
    args=[today]
    if product_id:sql+=' AND u.product_id=?';args.append(product_id)
    rows=[dict(r,status_label=STATUSES.get(r['status'],r['status']),kind_label=KINDS[r['kind']]) for r in c.execute(sql+' ORDER BY u.id DESC LIMIT 1000',args)]
    if status:rows=[r for r in rows if r['status']==status]
    words=[w for w in re.sub(r'\s+',' ',str(query or '').lower()).split(' ') if w]
    if words:
        # La búsqueda por clave o cuenta compara la huella: encuentra la licencia sin guardar ni mostrar la credencial en claro.
        marks=set()
        for kind in KINDS:
            try:marks.add(fingerprint(kind,{'username':query,'key':query,'serial':query}))
            except LicenseError:break
        exact={r['id'] for r in c.execute('SELECT id FROM license_units WHERE fingerprint IN (%s)'%','.join('?'*len(marks)),list(marks))} if marks else set()
        rows=[r for r in rows if r['id'] in exact or all(w in ' '.join(str(r[k] or '') for k in ('code','product','edition','license_type','manufacturer','client','order_code','quote_code','batch_supplier','invoice')).lower() for w in words)]
    return rows


def deliveries(c,now):
    """Órdenes con licencias reservadas o entregadas, y el estado de su pago y autorización (para «Historial de ventas y entregas»)."""
    import equipment
    out=[]
    orders=[r['order_id'] for r in c.execute("SELECT DISTINCT order_id FROM license_units WHERE order_id IS NOT NULL UNION SELECT DISTINCT order_id FROM license_deliveries ORDER BY 1 DESC LIMIT 300")]
    orders=list(dict.fromkeys(orders+[r['order_id'] for r in pending_items(c)]))
    for order_id in orders:
        info=c.execute("SELECT COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,cl.name client,COALESCE(cl.email,'') email FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?",(order_id,)).fetchone()
        if not info:continue
        all_units=_order_units(c,order_id)
        waiting=[u for u in all_units if u['status']=='reservada' and not u['delivery_id']]
        out.append({'order_id':order_id,'order':info['code'],'client':info['client'],'has_email':bool(info['email']),'balance_cents':equipment.money(c,order_id)['balance_cents'],
                    'reserved':[{'id':u['id'],'code':u['code'],'product':u['product_name'],'activated':u['activated']} for u in waiting],
                    'pending':[{'product':r['description'],'missing':r['missing'],'quote':r['quote_code']} for r in pending_items(c,order_id=order_id)],
                    'blockers':blockers(c,order_id,waiting) if waiting else [],
                    'deliveries':[dict(r,units=[{'code':u['code'],'product':u['product_name'],'status':u['status']} for u in all_units if u['delivery_id']==r['id']],
                                       confirmed_by=(c.execute('SELECT name FROM users WHERE id=?',(r['payment_confirmed_by'],)).fetchone() or {'name':''})['name'],
                                       authorized_by_name=(c.execute('SELECT name FROM users WHERE id=?',(r['authorized_by'],)).fetchone() or {'name':''})['name'] if r['authorized_by'] else '',
                                       link_active=r['status']=='autorizada' and r['token_expires_at']>stamp(now))
                                  for r in [dict(x) for x in c.execute('SELECT id,status,payment_confirmed_by,payment_confirmed_at,authorized_by,authorized_at,token_expires_at,reveal_count,last_revealed_at,void_reason FROM license_deliveries WHERE order_id=? ORDER BY id DESC',(order_id,))]]})
    return out


def history(c,limit=300):
    return [dict(r) for r in c.execute("SELECT e.id,e.event,e.detail,e.created_at,COALESCE(u.name,e.actor) actor,lu.code unit_code,i.name product,COALESCE(o.code,'') order_code,COALESCE(cl.name,'') client "
                                       "FROM license_events e LEFT JOIN users u ON u.id=e.actor_id LEFT JOIN license_units lu ON lu.id=e.unit_id LEFT JOIN catalog_items i ON i.id=e.product_id "
                                       "LEFT JOIN orders o ON o.id=e.order_id LEFT JOIN clients cl ON cl.id=e.client_id ORDER BY e.id DESC LIMIT ?",(limit,))]


def stock(c,now):
    """Existencias disponibles por producto, para el selector del presupuesto (sin datos de licencias)."""
    today=now.date().isoformat()
    managed={r['item_id'] for r in c.execute('SELECT item_id FROM license_products')}
    free={r['product_id']:r['n'] for r in c.execute("SELECT product_id,COUNT(*) n FROM license_units WHERE status='disponible' AND (expires_at='' OR expires_at>=?) GROUP BY product_id",(today,))}
    return {item:free.get(item,0) for item in managed}
