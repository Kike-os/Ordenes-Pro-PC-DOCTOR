"""Licencias Pro — Control de Vigencia y Renovaciones.

Producto = elemento del catálogo (categoría «licencia» o «seguridad») con su logo; sus datos de licencia (línea, edición, modalidad,
duración, desde cuándo cuenta la vigencia, proveedor y costo) están en license_products. Debajo, una unidad por clave, serial o cuenta,
con su estado. Un borrador de presupuesto no descuenta nada: al aprobarse se reservan unidades concretas. La entrega la confirma
manualmente administración (sin depender de la confirmación del pago; si la orden tiene saldo, hay que aceptarlo expresamente).

Vigencia: duración mensual, anual, bianual, trianual, perpetua o personalizada (meses). Se cuenta desde la activación real, desde la
compra o hasta una fecha fija del proveedor, según el producto. Los meses son de calendario (19/10/2026 + 12 meses = 19/10/2027). Una
licencia que cuenta desde la activación no tiene vencimiento hasta que se registra su activación: Órdenes Pro registra la fecha que
indica el personal; no afirma que la licencia se activó en los servidores del fabricante.

Cifrado de credenciales (solo biblioteca estándar): clave maestra de 32 bytes fuera de la base (LICENSE_ENCRYPTION_KEY en Vercel; en el
servidor local, license.key 0600 en la carpeta de datos). Cifrado en modo contador con HMAC-SHA256 y autenticación encrypt-then-MAC. La
huella (HMAC) de la clave o cuenta impide registrarla dos veces, salvo en productos de clave compartida (hasta su número de puestos)."""
import base64,calendar,hashlib,hmac,json,os,re,secrets,struct
from datetime import date,datetime,timedelta
from pathlib import Path

import reception

KINDS={'m365':'Microsoft 365','windows_office':'Windows y Office','antivirus':'Antivirus','otro':'Otro producto digital'}
LINES={'antivirus':'Antivirus','microsoft':'Microsoft','sistema':'Sistema operativo','ofimatica':'Ofimática','utilitarios':'Utilitarios','otros':'Otros'}
MODELS={'suscripcion':'Suscripción','perpetua':'Perpetua','otra':'Otra'}
DURATIONS={'mensual':'Mensual','anual':'Anual','bianual':'Bianual','trianual':'Trianual','perpetua':'Perpetua','personalizada':'Personalizada'}
MONTHS={'mensual':1,'anual':12,'bianual':24,'trianual':36}
VALIDITY={'activacion':'Desde la activación','compra':'Desde la compra','fija':'Fecha fija del proveedor'}
STATUSES={'disponible':'Disponible','reservada':'Reservada','entregada':'Entregada','anulada':'Anulada','vencida':'Vencida'}
# Estados que ve el personal (calculados a partir de la unidad y la fecha de hoy), con su color.
STATES={'disponible':('Disponible','azul'),'reservada':('Reservada','celeste'),'pendiente_activacion':('Entregada, pendiente de activación','naranja'),
        'activa':('Activa','verde'),'por_vencer':('Próxima a vencer','amarillo'),'vencida':('Vencida','rojo'),'renovada':('Renovada','turquesa'),'anulada':('Anulada','gris')}
PRODUCT_CATEGORIES=('licencia','seguridad')
SECRET_LABELS={'key':'Clave de producto o serial','serial':'Serial o código de activación','username':'Usuario o correo de activación','password':'Contraseña de activación','license_code':'Código de licencia o identificador del fabricante'}
SECRET_INPUTS=('key','username','password','license_code')
# Método de activación de cada producto: solo se piden y se guardan los campos que ese método usa.
# Vacío = producto anterior a la migración 069: el método se deduce de los datos guardados, como antes.
ACTIVATION={'clave':'Clave de producto o serial','cuenta':'Usuario y contraseña','mixta':'Activación mixta','archivo':'Archivo de licencia'}
ACTIVATION_FIELDS={'clave':('key','license_code'),'cuenta':('username','password','license_code'),'mixta':('key','username','password','license_code'),'archivo':('license_code',)}
ACTIVATION_REQUIRED={'clave':('key',),'cuenta':('username','password'),'mixta':('key','username','password'),'archivo':()}
# Archivo de licencia del fabricante: tipos de activación habituales; nunca programas, scripts ni comprimidos (se entrega al cliente tal cual).
FILE_LIMIT=256*1024
FILE_TYPES={'lic':'application/octet-stream','key':'application/octet-stream','dat':'application/octet-stream','xml':'application/xml','json':'application/json',
            'txt':'text/plain','cfg':'text/plain','ini':'text/plain','pdf':'application/pdf'}
TEXT_FILES=('xml','json','txt','cfg','ini')
DUPLICATE_REASON_MIN=10
FIELDS=('edition','license_type','manufacturer','version','devices','term','purchased_at','activated_at','expires_at','download_url','instructions')
FIELD_LABELS={'edition':'Versión o edición','license_type':'Tipo de licencia','manufacturer':'Fabricante','version':'Versión','devices':'Dispositivos','term':'Duración',
              'purchased_at':'Fecha de compra','activated_at':'Fecha de activación','expires_at':'Fecha de vencimiento','download_url':'Enlace de descarga o activación','instructions':'Instrucciones de instalación'}
DATES=('purchased_at','activated_at','expires_at')
ALERT_DAYS=(30,15,7,1,0)
SOON_DAYS=30
LINK_HOURS=72
CODE_MINUTES=10
MAX_CODE_FAILURES=5
MAX_BULK=200
RECEIPT_LIMIT=1500000
CONTACT={'phone':'+593 98 746 0591','email':'licencias-orig@ecuadorpcdoctor.com'}


class LicenseError(ValueError):
    def __init__(self,message,status=400,fields=None,extra=None):
        super().__init__(message);self.status=status;self.fields=fields or {};self.extra=extra or {}


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
    """Lo que identifica la credencial: la clave o serial (sin espacios ni guiones, en mayúsculas) o, si no hay, la cuenta en minúsculas."""
    main=values.get('key') or values.get('serial') or ''
    if main:return 'key:'+re.sub(r'[\s-]+','',main).upper()
    if not values.get('username') and values.get('file_sha256'):return 'file:'+values['file_sha256']
    return 'm365:'+str(values.get('username','')).strip().lower()


def fingerprint(kind,values,seat=1):
    base=normalized(kind,values)+('' if seat==1 else '#%d'%seat)
    return hmac.new(_keys()[2],base.encode(),hashlib.sha256).hexdigest()


def _hash(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


# ---- Utilidades -------------------------------------------------------------------------------------------------------
def stamp(now):return now.isoformat(timespec='seconds')


def event(c,name,now,detail='',unit=None,product=None,delivery=None,order=None,client=None,user=None,actor=''):
    c.execute('INSERT INTO license_events(unit_id,product_id,delivery_id,order_id,client_id,event,detail,actor_id,actor,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
              (unit,product,delivery,order,client,name,detail[:500],user['id'] if user else None,actor or ('' if user else 'sistema'),stamp(now)))


def add_months(day,months):
    """Meses de calendario: el mismo día del mes de destino (o su último día si no existe: 31/01 + 1 mes = 28 o 29/02)."""
    year,month=divmod(day.month-1+months,12);year+=day.year;month+=1
    return date(year,month,min(day.day,calendar.monthrange(year,month)[1]))


def months_of(product,duration=None,custom=None):
    duration=duration or product.get('duration') or 'anual'
    if duration=='perpetua':return None
    if duration=='personalizada':return custom if custom is not None else product.get('duration_months')
    return MONTHS[duration]


def compute_expiry(product,purchased_at,activated_at,manual=''):
    """Vencimiento según el producto. Sin activación (si cuenta desde la activación) o sin compra (si cuenta desde la compra) no hay
    vencimiento: nunca se inventa una fecha. Las perpetuas no vencen."""
    months=months_of(product)
    if months is None:return ''
    mode=product.get('validity_mode') or 'activacion'
    if mode=='fija':return manual
    base=activated_at if mode=='activacion' else purchased_at
    return add_months(date.fromisoformat(base),months).isoformat() if base else ''


def display_settings(c):
    """Umbral (en días) desde el que una licencia vendida se muestra «Por vencer» (amarillo). Configurable por administración."""
    row=c.execute("SELECT value FROM system_state WHERE key='license_display'").fetchone()
    try:stored=json.loads(row['value']) if row else {}
    except ValueError:stored={}
    soon=stored.get('soon_days')
    return {'soon_days':soon if type(soon) is int and 1<=soon<=180 else SOON_DAYS}


def save_display(c,data,user,now):
    text=str(data.get('soon_days') or '').strip()
    if not text.isdigit() or not 1<=int(text)<=180:raise LicenseError('El aviso de próximo vencimiento debe estar entre 1 y 180 días.',fields={'soon_days':'Valor no válido.'})
    c.execute("INSERT INTO system_state(key,value) VALUES ('license_display',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps({'soon_days':int(text)}),))
    event(c,'configuracion',now,'Aviso de próximo vencimiento: %s días.'%text,user=user)
    return display_settings(c)


def state_of(unit,today,mode='activacion',soon=None):
    """Estado visible de una unidad hoy (y días restantes cuando tiene vencimiento)."""
    days=(date.fromisoformat(unit['expires_at'])-today).days if unit.get('expires_at') else None
    if unit['status']=='anulada':return 'anulada',days
    if unit.get('renewed_to'):return 'renovada',days
    if unit['status'] in ('disponible','vencida'):return ('vencida' if unit['status']=='vencida' or (days is not None and days<0) else 'disponible'),days
    if unit['status']=='reservada':return 'reservada',days
    if days is not None and days<0:return 'vencida',days
    if not unit.get('activated'):return 'pendiente_activacion',days
    if days is not None and days<=(soon or SOON_DAYS):return 'por_vencer',days
    return 'activa',days


def expire(c,now):
    """Unidades en inventario cuyo vencimiento ya pasó: pasan a «Vencida» (no se venden). Las vendidas no cambian de estado guardado."""
    today=now.date().isoformat()
    rows=c.execute("SELECT id,product_id FROM license_units WHERE status='disponible' AND expires_at!='' AND expires_at<?",(today,)).fetchall()
    for row in rows:
        c.execute("UPDATE license_units SET status='vencida',updated_at=? WHERE id=? AND status='disponible'",(stamp(now),row['id']))
        event(c,'vencida',now,'La licencia superó su fecha de vencimiento sin venderse.',row['id'],row['product_id'])
    return len(rows)


def _product(c,product_id):
    row=c.execute("SELECT i.id,i.name,i.category,i.brand,i.description,i.price_cents,i.available,p.kind,p.line,p.model,p.edition,p.supplier,p.purchase_cents,p.term,p.devices,"
                  "p.duration,p.duration_months,p.validity_mode,p.shared_seats,COALESCE(p.activation_method,'') activation_method FROM catalog_items i LEFT JOIN license_products p ON p.item_id=i.id WHERE i.id=?",(product_id,)).fetchone()
    if not row or row['category'] not in PRODUCT_CATEGORIES:raise LicenseError('Producto de licencia no disponible.',404)
    return dict(row)


def _text(data,key,limit,label):
    value=re.sub(r'[ \t]+',' ',str(data.get(key) or '')).strip()
    if key!='instructions':value=re.sub(r'\s+',' ',value)
    if len(value)>limit:raise LicenseError('%s admite hasta %d caracteres.'%(label,limit),fields={key:'Texto demasiado largo.'})
    return value


def _cents(value,key,label):
    text=str(value if value is not None else '').strip().replace(',','.')
    if not text:return None
    if not re.fullmatch(r'\d{1,7}(\.\d{1,2})?',text):raise LicenseError('Indica %s en USD con hasta dos decimales.'%label,fields={key:'Importe no válido.'})
    whole,_,part=text.partition('.');return int(whole)*100+int((part+'00')[:2])


def _date(value,key,today=None,future=True):
    text=str(value or '').strip()
    if not text:return ''
    try:
        if date.fromisoformat(text).isoformat()!=text:raise ValueError
    except ValueError:raise LicenseError('Indica una fecha válida.',fields={key:'Fecha no válida.'})
    if not future and today and text>today.isoformat():raise LicenseError('%s no puede ser posterior a hoy.'%FIELD_LABELS.get(key,'La fecha'),fields={key:'Fecha futura.'})
    return text


def _devices(value,key='devices'):
    text=str(value if value is not None else '').strip()
    if not text:return None
    if not text.isdigit() or not 1<=int(text)<=1000:raise LicenseError('Indica la cantidad de dispositivos (1 a 1000).',fields={key:'Cantidad no válida.'})
    return int(text)


def _url(value):
    text=str(value or '').strip()
    if text and (len(text)>300 or not re.fullmatch(r'https?://[^\s<>"]+',text)):raise LicenseError('El enlace debe empezar por https:// (o http://).',fields={'download_url':'Enlace no válido.'})
    return text


# ---- Productos --------------------------------------------------------------------------------------------------------
def _product_settings(data,product=None):
    product=product or {}
    line=str(data.get('line') or product.get('line') or 'otros');model=str(data.get('model') or product.get('model') or 'otra')
    duration=str(data.get('duration') or product.get('duration') or 'anual');validity=str(data.get('validity_mode') or product.get('validity_mode') or 'activacion')
    if line not in LINES:raise LicenseError('Selecciona la categoría.',fields={'line':'Categoría no válida.'})
    if model not in MODELS:raise LicenseError('Selecciona el tipo de licencia.',fields={'model':'Tipo no válido.'})
    if duration not in DURATIONS:raise LicenseError('Selecciona la duración.',fields={'duration':'Duración no válida.'})
    if validity not in VALIDITY:raise LicenseError('Selecciona desde cuándo cuenta la vigencia.',fields={'validity_mode':'Opción no válida.'})
    custom=None
    if duration=='personalizada':
        raw=str(data.get('duration_months') if data.get('duration_months') is not None else product.get('duration_months') or '').strip()
        if not raw.isdigit() or not 1<=int(raw)<=120:raise LicenseError('Indica la duración personalizada en meses (1 a 120).',fields={'duration_months':'Meses no válidos.'})
        custom=int(raw)
    if duration=='perpetua' and validity!='activacion':validity='activacion'
    if model=='perpetua' and duration!='perpetua':raise LicenseError('Una licencia perpetua debe tener duración «Perpetua».',fields={'duration':'Duración incompatible.'})
    seats=str(data.get('shared_seats') if data.get('shared_seats') is not None else product.get('shared_seats') or 0).strip() or '0'
    if not seats.isdigit() or int(seats)>100 or int(seats)==1:raise LicenseError('Clave compartida: indica de 2 a 100 clientes, o 0 si cada cliente recibe su propia clave.',fields={'shared_seats':'Valor no válido.'})
    method=str(data.get('activation_method') if data.get('activation_method') is not None else product.get('activation_method') or '')
    if method and method not in ACTIVATION:raise LicenseError('Selecciona el método de activación.',fields={'activation_method':'Método no válido.'})
    kind='antivirus' if line=='antivirus' else (product.get('kind') if product.get('kind') in KINDS else 'otro')
    return {'activation_method':method,'kind':kind,'line':line,'model':model,'duration':duration,'duration_months':custom,'validity_mode':validity,'shared_seats':int(seats),
            'edition':_text(data,'edition',120,'La versión o edición'),'supplier':_text(data,'supplier',120,'El proveedor'),
            'purchase_cents':_cents(data.get('purchase_price'),'purchase_price','el costo de adquisición'),'term':DURATIONS[duration] if duration!='personalizada' else '%d meses'%custom,'devices':_devices(data.get('devices'))}


def _store_settings(c,item_id,s,user,now):
    c.execute('INSERT INTO license_products(item_id,kind,supplier,purchase_cents,term,devices,line,model,edition,duration,duration_months,validity_mode,shared_seats,activation_method,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
              'ON CONFLICT(item_id) DO UPDATE SET kind=excluded.kind,supplier=excluded.supplier,purchase_cents=excluded.purchase_cents,term=excluded.term,devices=excluded.devices,line=excluded.line,model=excluded.model,'
              'edition=excluded.edition,duration=excluded.duration,duration_months=excluded.duration_months,validity_mode=excluded.validity_mode,shared_seats=excluded.shared_seats,activation_method=excluded.activation_method,updated_at=excluded.updated_at,updated_by=excluded.updated_by',
              (item_id,s['kind'],s['supplier'],s['purchase_cents'],s['term'],s['devices'],s['line'],s['model'],s['edition'],s['duration'],s['duration_months'],s['validity_mode'],s['shared_seats'],s['activation_method'],stamp(now),user['id']))


def _catalog_values(data,product=None):
    product=product or {}
    name=re.sub(r'\s+',' ',str(data.get('name') if data.get('name') is not None else product.get('name') or '')).strip()
    price=data.get('price') if data.get('price') not in (None,'') else (('%.2f'%(product['price_cents']/100)) if product.get('price_cents') is not None else '')
    return {'name':name,'brand':str(data.get('brand') if data.get('brand') is not None else product.get('brand') or ''),'description':str(data.get('description') if data.get('description') is not None else product.get('description') or ''),
            'price':price}


def save_logo(c,item_id,content_b64,user,now):
    if not content_b64:return
    import quotes
    try:content=base64.b64decode(str(content_b64),validate=True)
    except Exception:raise LicenseError('El logotipo no se pudo leer.',fields={'logo':'Archivo no válido.'})
    try:quotes.save_image(c,item_id,content,user,now)
    except quotes.QuoteError as error:raise LicenseError(str(error),fields={'logo':str(error)})


def create_product(c,data,user,now):
    """Producto nuevo (aunque la marca o el producto no existan todavía en el catálogo): lo registra en el catálogo y en el inventario."""
    import quotes
    settings=_product_settings(data);values=_catalog_values(data)
    if not values['price']:raise LicenseError('Indica el precio de venta en USD.',fields={'price':'Precio obligatorio.'})
    try:item=quotes.save_catalog_item(c,{'name':values['name'],'description':values['description'],'category':'seguridad' if settings['line']=='antivirus' else 'licencia','brand':values['brand'],
                                         'price':values['price'],'price_mode':'incluido','license_term':settings['term'],'devices':'%d dispositivo%s'%(settings['devices'],'' if settings['devices']==1 else 's') if settings['devices'] else ''},user,now)
    except quotes.QuoteError as error:raise LicenseError(str(error),error.status,error.fields)
    _store_settings(c,item,settings,user,now);save_logo(c,item,data.get('logo'),user,now)
    event(c,'producto',now,'Producto «%s» creado (%s · %s).'%(values['name'],LINES[settings['line']],DURATIONS[settings['duration']]),product=item,user=user)
    return item


def save_product(c,data,user,now):
    """Edita un producto: datos del catálogo (nombre, marca, descripción, precio de venta) y de licencia. No toca las licencias registradas."""
    import quotes
    item=str(data.get('item_id',''))
    if not item.isdigit():raise LicenseError('Selecciona el producto del catálogo.',fields={'item_id':'Producto no válido.'})
    product=_product(c,int(item))
    if data.get('kind') in KINDS and not data.get('line'):data=dict(data,line={'antivirus':'antivirus','m365':'microsoft','windows_office':'microsoft'}.get(data['kind'],'otros'))
    settings=_product_settings(data,product if product.get('line') else {})
    if data.get('kind') in KINDS:settings['kind']=data['kind']
    if product['kind'] and product['kind']!=settings['kind'] and c.execute('SELECT 1 FROM license_units WHERE product_id=?',(product['id'],)).fetchone():settings['kind']=product['kind']
    values=_catalog_values(data,product)
    try:quotes.save_catalog_item(c,{'id':str(product['id']),'name':values['name'],'description':values['description'],'category':'seguridad' if settings['line']=='antivirus' else 'licencia','brand':values['brand'],
                                    'price':values['price'],'price_mode':'incluido','license_term':settings['term'],'devices':'%d dispositivo%s'%(settings['devices'],'' if settings['devices']==1 else 's') if settings['devices'] else '',
                                    'available':bool(product['available'])},user,now)
    except quotes.QuoteError as error:raise LicenseError(str(error),error.status,error.fields)
    _store_settings(c,product['id'],settings,user,now);save_logo(c,product['id'],data.get('logo'),user,now)
    event(c,'producto',now,'Datos del producto «%s» guardados.'%values['name'],product=product['id'],user=user)
    return product['id']


def duplicate_product(c,item_id,name,user,now):
    """Copia un producto (datos y logo) con otro nombre, sin licencias. Útil para otra edición o duración del mismo fabricante."""
    product=_product(c,item_id)
    if not product['kind']:raise LicenseError('Configura primero el producto que quieres duplicar.',409)
    data={key:product[key] for key in ('line','model','edition','supplier','duration','duration_months','validity_mode','shared_seats','brand','description')}
    data.update(name=name,price='%.2f'%(product['price_cents']/100),purchase_price='%.2f'%(product['purchase_cents']/100) if product['purchase_cents'] is not None else '',devices=product['devices'] or '')
    item=create_product(c,data,user,now)
    logo=c.execute('SELECT mime,data FROM catalog_images WHERE item_id=?',(item_id,)).fetchone()
    if logo:c.execute('INSERT INTO catalog_images(item_id,mime,data,updated_at,updated_by) VALUES (?,?,?,?,?)',(item,logo['mime'],logo['data'],stamp(now),user['id']))
    return item


def toggle_product(c,item_id,active,user,now):
    """Desactivar: el producto deja de ofrecerse en los presupuestos; sus licencias y su historial se conservan."""
    product=_product(c,item_id)
    c.execute('UPDATE catalog_items SET available=?,updated_at=?,updated_by=? WHERE id=?',(1 if active else 0,stamp(now),user['id'],item_id))
    event(c,'producto',now,'Producto «%s» %s.'%(product['name'],'activado' if active else 'desactivado'),product=item_id,user=user)


def products(c,now):
    """Productos de licencia con existencias por estado (a partir de las unidades individuales)."""
    today=now.date()
    rows=[dict(r) for r in c.execute("SELECT i.id,i.code,i.name,i.category,i.brand,i.description,i.price_cents,i.available,i.license_term,(SELECT updated_at FROM catalog_images g WHERE g.item_id=i.id) image,"
                                     "p.kind,p.line,p.model,p.edition,p.supplier,p.purchase_cents,p.term,p.devices,p.duration,p.duration_months,p.validity_mode,p.shared_seats,COALESCE(p.activation_method,'') activation_method "
                                     "FROM catalog_items i LEFT JOIN license_products p ON p.item_id=i.id WHERE i.category IN ('licencia','seguridad') ORDER BY i.name COLLATE NOCASE")]
    counts={}
    for unit in c.execute('SELECT product_id,status,expires_at,activated,renewed_to FROM license_units'):
        state,_=state_of(dict(unit),today);counts.setdefault(unit['product_id'],{}).setdefault(state,0);counts[unit['product_id']][state]+=1
    for row in rows:
        row['image']=row['image'] or '';row['managed']=bool(row['kind'])
        row['line_label']=LINES.get(row['line'] or '','Sin configurar') if row['managed'] else 'Sin configurar'
        row['kind_label']=row['line_label']
        row['duration_label']=row['term'] or '';row['validity_label']=VALIDITY.get(row['validity_mode'] or '','')
        row['model_label']=MODELS.get(row['model'] or '','');row['activation_label']=ACTIVATION.get(row['activation_method'],'Según los datos guardados')
        row['stock']={key:counts.get(row['id'],{}).get(key,0) for key in STATES}
        row['stock'].update({'entregada':row['stock']['pendiente_activacion']+row['stock']['activa']+row['stock']['por_vencer']})
        row['pending']=sum(item['missing'] for item in pending_items(c,row['id']))
    return rows


# ---- Registro de licencias --------------------------------------------------------------------------------------------
def _clean_unit(product,data,today):
    out={}
    for key in FIELDS:
        if key in DATES:out[key]=_date(data.get(key),key,today,future=key=='expires_at')
        elif key=='devices':out[key]=_devices(data.get(key))
        elif key=='download_url':out[key]=_url(data.get(key))
        elif key=='instructions':out[key]=_text(data,key,2000,FIELD_LABELS[key])
        else:out[key]=_text(data,key,120,FIELD_LABELS[key])
    if out['activated_at'] and out['purchased_at'] and out['activated_at']<out['purchased_at']:raise LicenseError('La activación no puede ser anterior a la compra.',fields={'activated_at':'Revisa la fecha.'})
    if (product.get('validity_mode')=='fija' and months_of(product) is not None) and not out['expires_at']:raise LicenseError('Este producto vence en una fecha fija del proveedor: indícala.',fields={'expires_at':'Fecha obligatoria.'})
    if months_of(product) is None:out['expires_at']=''
    elif product.get('validity_mode')!='fija':out['expires_at']=compute_expiry(product,out['purchased_at'],out['activated_at'])
    if out['expires_at'] and out['activated_at'] and out['expires_at']<out['activated_at']:raise LicenseError('El vencimiento no puede ser anterior a la activación.',fields={'expires_at':'Revisa la fecha.'})
    out['term']=out['term'] or product.get('term') or ''
    out['devices']=out['devices'] or product.get('devices')
    out['edition']=out['edition'] or product.get('edition') or ''
    out['manufacturer']=out['manufacturer'] or product.get('brand') or ''
    return out


def _clean_secret(data,required=True,method=''):
    allowed=ACTIVATION_FIELDS.get(method,SECRET_INPUTS);values={}
    for key in SECRET_INPUTS:
        if key not in allowed:continue
        raw=str(data.get(key) if data.get(key) is not None else data.get('serial') if key=='key' and data.get('serial') else '')
        value=raw if key=='password' else re.sub(r'\s+',' ',raw).strip()
        if '\n' in value or len(value)>300:raise LicenseError('%s admite hasta 300 caracteres en una línea.'%SECRET_LABELS[key],fields={key:'Dato no válido.'})
        if value:values[key]=value
    if method in ACTIVATION:
        for key in ACTIVATION_REQUIRED[method] if required else ():
            if not values.get(key):raise LicenseError('Falta %s (método «%s»).'%(SECRET_LABELS[key][0].lower()+SECRET_LABELS[key][1:],ACTIVATION[method]),fields={key:'Dato obligatorio.'})
    elif required and not values.get('key') and not values.get('username'):raise LicenseError('Indica la clave de producto o serial, o el usuario de activación.',fields={'key':'Dato obligatorio.'})
    if values.get('key') and len(re.sub(r'[\s-]+','',values['key']))<5:raise LicenseError('La clave o serial es demasiado corta.',fields={'key':'Revisa el dato.'})
    if values.get('password') and not values.get('username'):raise LicenseError('Indica el usuario de la contraseña.',fields={'username':'Usuario obligatorio.'})
    return values


def _clean_file(data):
    """Archivo de licencia del fabricante: extensión, tamaño y contenido validados. Devuelve None si no se adjuntó."""
    raw=data.get('file')
    if not raw:return None
    name=str(data.get('file_name') or '').strip();ext=name.rsplit('.',1)[-1].lower() if '.' in name else ''
    if ext not in FILE_TYPES:raise LicenseError('El archivo de licencia debe ser .lic, .key, .dat, .xml, .json, .txt, .cfg, .ini o .pdf.',fields={'file':'Formato no admitido.'})
    try:content=base64.b64decode(str(raw),validate=True)
    except Exception:raise LicenseError('El archivo de licencia no se pudo leer.',fields={'file':'Archivo no válido.'})
    if not content:raise LicenseError('El archivo de licencia está vacío.',fields={'file':'Archivo vacío.'})
    if len(content)>FILE_LIMIT:raise LicenseError('El archivo de licencia supera el máximo de 256 KB.',fields={'file':'Archivo demasiado grande.'})
    if content[:2]==b'MZ' or content[:4] in (b'\x7fELF',b'PK\x03\x04',b'Rar!',b'\xca\xfe\xba\xbe') or content[:2]==b'#!' or content[:6]==b'7z\xbc\xaf\x27\x1c':
        raise LicenseError('No se admiten programas, scripts ni archivos comprimidos como archivo de licencia.',fields={'file':'Contenido no permitido.'})
    if ext=='pdf' and content[:5]!=b'%PDF-':raise LicenseError('El archivo no es un PDF válido.',fields={'file':'PDF no válido.'})
    if ext in TEXT_FILES:
        try:content.decode('utf-8')
        except UnicodeDecodeError:raise LicenseError('Un archivo .%s debe ser texto (UTF-8).'%ext,fields={'file':'Contenido no válido.'})
    clean=re.sub(r'[^\w .()-]+','',name)[:120] or 'licencia.'+ext
    return {'name':clean,'mime':FILE_TYPES[ext],'size':len(content),'sha256':hashlib.sha256(content).hexdigest(),'data':content}


def _credential(data,method,required=True):
    """Credencial de una licencia según el método del producto: valores cifrables y, si es «archivo», el archivo validado."""
    values=_clean_secret(data,required,method);file=_clean_file(data) if method=='archivo' else None
    if method=='archivo':
        if required and not file:raise LicenseError('Adjunta el archivo de licencia del fabricante.',fields={'file':'Archivo obligatorio.'})
        if file:values['file_sha256']=file['sha256']
    return values,file


def _store_file(c,unit,file,user,now):
    c.execute('INSERT INTO license_files(unit_id,name,mime,size,sha256,sealed,created_at,created_by) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(unit_id) DO UPDATE SET '
              'name=excluded.name,mime=excluded.mime,size=excluded.size,sha256=excluded.sha256,sealed=excluded.sealed,created_at=excluded.created_at,created_by=excluded.created_by',
              (unit,file['name'],file['mime'],file['size'],file['sha256'],seal({'data':base64.b64encode(file['data']).decode()}),stamp(now),user['id']))


def file_of(c,unit_id):
    """Archivo de licencia descifrado (nombre, tipo y contenido en base64) o None."""
    row=c.execute('SELECT name,mime,size,sealed FROM license_files WHERE unit_id=?',(unit_id,)).fetchone()
    if not row:return None
    return {'name':row['name'],'mime':row['mime'],'size':row['size'],'data':unseal(row['sealed'])['data']}


def _method_for(c,product,data,user,now):
    """Método con el que se registran las licencias nuevas. Si el formulario elige otro, se guarda en el producto (las ya registradas no cambian)."""
    wanted=str(data.get('activation_method') or '');current=product.get('activation_method') or ''
    if wanted and wanted not in ACTIVATION:raise LicenseError('Selecciona el método de activación.',fields={'activation_method':'Método no válido.'})
    if wanted and wanted!=current:
        c.execute('UPDATE license_products SET activation_method=?,updated_at=?,updated_by=? WHERE item_id=?',(wanted,stamp(now),user['id'],product['id']))
        event(c,'metodo_activacion',now,'Método de activación del producto: %s%s. Las licencias ya registradas conservan sus datos.'%(ACTIVATION[wanted],' (antes: %s)'%ACTIVATION[current] if current else ''),product=product['id'],user=user)
        product['activation_method']=wanted
    return product.get('activation_method') or ''


def _free_seat(c,product,values,exclude=None,extra=0):
    """Puesto libre para esta credencial: 1 si es única; en productos de clave compartida, el siguiente libre hasta su número de puestos.
    `extra` solo se usa para una coincidencia de CUENTA autorizada con justificación (una cuenta con varias licencias legítimas)."""
    seats=max(1,product.get('shared_seats') or 0)+extra
    for seat in range(1,seats+1):
        mark=fingerprint(product['kind'],values,seat)
        found=c.execute('SELECT id,code FROM license_units WHERE fingerprint=?',(mark,)).fetchone()
        if not found or found['id']==exclude:return seat,mark
    found=c.execute('SELECT code FROM license_units WHERE fingerprint=?',(fingerprint(product['kind'],values,1),)).fetchone()
    raise LicenseError(('Esta clave ya está registrada (%s).'%found['code']) if seats==1 else 'Esta clave compartida ya tiene sus %d puestos registrados.'%seats,409,{'key':'Duplicada.'})


def _insert_unit(c,product,fields,values,batch,user,now,notes='',file=None,extra=0):
    if fields['activated_at']:
        raise LicenseError('Una licencia en inventario aún no está activada: la fecha real de activación se registra al entregarla o con «Confirmar activación».',fields={'activated_at':'Solo al entregar o confirmar la activación.'})
    seat,mark=_free_seat(c,product,values,extra=extra)
    import inventory_center
    # Producto clasificado en el Centro de Inventario: código de su categoría (PCD-AV-000001). Sin clasificar: LIC-000001 (disparador).
    code=inventory_center.license_code(c,product['id'])
    unit=c.execute('INSERT INTO license_units(code,product_id,batch_id,kind,edition,license_type,manufacturer,version,devices,term,purchased_at,activated_at,expires_at,download_url,instructions,secret,fingerprint,seat,notes,created_by,created_at,updated_at) '
                   'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (code,product['id'],batch,product['kind'],fields['edition'],fields['license_type'],fields['manufacturer'],fields['version'],fields['devices'],fields['term'],fields['purchased_at'],
                    fields['activated_at'],fields['expires_at'],fields['download_url'],fields['instructions'],seal(values),mark,seat,notes,user['id'],stamp(now),stamp(now))).lastrowid
    if fields['activated_at']:c.execute('UPDATE license_units SET activated=1 WHERE id=?',(unit,))
    if file:_store_file(c,unit,file,user,now)
    expired=fields['expires_at'] and fields['expires_at']<now.date().isoformat()
    if expired:c.execute("UPDATE license_units SET status='vencida' WHERE id=?",(unit,))
    event(c,'registrada',now,'Licencia registrada en el inventario%s.'%(' (ya vencida)' if expired else '' if seat==1 else ' (puesto %d de la clave compartida)'%seat),unit,product['id'],user=user)
    return unit


def _batch(c,product,data,quantity,user,now):
    batch=c.execute('INSERT INTO license_batches(product_id,supplier,unit_cost_cents,purchased_at,invoice,quantity,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (product['id'],_text(data,'supplier',120,'El proveedor') or product.get('supplier') or '',_cents(data.get('unit_cost'),'unit_cost','el costo de adquisición') if data.get('unit_cost') not in (None,'') else product.get('purchase_cents'),
                     _date(data.get('batch_date') or data.get('purchased_at'),'batch_date',now.date(),future=False),_text(data,'invoice',80,'La factura'),quantity,user['id'],stamp(now))).lastrowid
    save_receipt(c,batch,data.get('receipt'),data.get('receipt_name'),user,now)
    return batch


def save_receipt(c,batch,content_b64,name,user,now):
    if not content_b64:return
    try:content=base64.b64decode(str(content_b64),validate=True)
    except Exception:raise LicenseError('El comprobante no se pudo leer.',fields={'receipt':'Archivo no válido.'})
    mime='application/pdf' if content[:5]==b'%PDF-' else 'image/png' if content[:8]==b'\x89PNG\r\n\x1a\n' else 'image/jpeg' if content[:3]==b'\xff\xd8\xff' else 'image/webp' if content[:4]==b'RIFF' and content[8:12]==b'WEBP' else None
    if not mime:raise LicenseError('El comprobante debe ser un PDF o una imagen PNG, JPG o WebP.',fields={'receipt':'Formato no admitido.'})
    if len(content)>RECEIPT_LIMIT:raise LicenseError('El comprobante supera el máximo de 1,5 MB.',fields={'receipt':'Archivo demasiado grande.'})
    clean=re.sub(r'[^\w .()-]+','',str(name or 'comprobante'))[:120] or 'comprobante'
    c.execute('INSERT INTO license_receipts(batch_id,name,mime,data,created_at,created_by) VALUES (?,?,?,?,?,?)',(batch,clean,mime,content,stamp(now),user['id']))


def _managed(c,product_id):
    product=_product(c,product_id)
    if not product['kind']:raise LicenseError('Configura primero los datos de licencia de este producto («Editar»).',409,{'product_id':'Producto sin configurar.'})
    return product


def register(c,data,user,now):
    """Una licencia de un producto existente («Agregar stock»): datos visibles, credencial cifrada y compra. Después se reservan las ventas
    aprobadas que esperaban existencias."""
    pid=str(data.get('product_id',''))
    if not pid.isdigit():raise LicenseError('Selecciona el producto.',fields={'product_id':'Producto no válido.'})
    product=_managed(c,int(pid));method=_method_for(c,product,data,user,now);fields=_clean_unit(product,data,now.date());values,file=_credential(data,method)
    report,reason=guard_duplicates(c,product,[values],data,user,now)
    batch=_batch(c,product,data,1,user,now)
    unit=_insert_unit(c,product,fields,values,batch,user,now,_text(data,'notes',500,'Las observaciones'),file=file,extra=100 if reason else 0)
    _log_authorized(c,report,[unit],reason,product,user,now)
    fill_pending(c,product['id'],now,user)
    return unit


def register_new(c,data,user,now):
    """«+ Registrar nueva licencia»: crea el producto si todavía no existe (con su logo) y registra la primera licencia, todo o nada."""
    if str(data.get('product_id') or '').isdigit():
        return {'product_id':int(data['product_id']),'unit_id':register(c,data,user,now)}
    if str(data.get('lines') or '').strip() or isinstance(data.get('rows'),list):
        # Producto nuevo con varias licencias: todo en la misma transacción (si una línea falla, no se crea nada).
        product=create_product(c,data,user,now)
        units=register_many(c,dict(data,product_id=str(product)),user,now)
        return {'product_id':product,'unit_id':units[0],'count':len(units)}
    _credential(data,str(data.get('activation_method') or ''))
    product=create_product(c,data,user,now)
    unit=register(c,dict(data,product_id=str(product)),user,now)
    return {'product_id':product,'unit_id':unit,'count':1}


def register_many(c,data,user,now):
    """Varias licencias del mismo producto: una por línea. «clave», o «usuario;contraseña», o «clave;usuario;contraseña». Todo o nada."""
    pid=str(data.get('product_id',''))
    if not pid.isdigit():raise LicenseError('Selecciona el producto.',fields={'product_id':'Producto no válido.'})
    product=_managed(c,int(pid));method=_method_for(c,product,data,user,now);fields=_clean_unit(product,data,now.date())
    if isinstance(data.get('rows'),list):
        # Filas del formulario: cada licencia con sus propios campos (y archivo, si el método lo usa); errores por fila y campo.
        rows=data['rows']
        if not rows:raise LicenseError('Agrega al menos una licencia.',fields={'rows':'Sin licencias.'})
        if len(rows)>MAX_BULK:raise LicenseError('Registra hasta %d licencias por vez.'%MAX_BULK,fields={'rows':'Demasiadas filas.'})
        parsed,files=[],[]
        for number,row in enumerate(rows,1):
            if not isinstance(row,dict) or any(not isinstance(v,str) for v in row.values()):raise LicenseError('Fila %d: datos no válidos.'%number,fields={'rows':'Fila no válida.'})
            try:values,file=_credential(row,method)
            except LicenseError as error:raise LicenseError('Fila %d: %s'%(number,error),error.status,{'row-%d-%s'%(number,k):v for k,v in error.fields.items()},{'row':number})
            parsed.append(values);files.append(file)
        return _register_parsed(c,product,fields,parsed,files,data,user,now,'row-%d-key')
    lines=[line.strip() for line in str(data.get('lines') or '').replace('\r','').split('\n') if line.strip()]
    if not lines:raise LicenseError('Escribe al menos una licencia (una por línea).',fields={'lines':'Sin licencias.'})
    if len(lines)>MAX_BULK:raise LicenseError('Registra hasta %d licencias por vez.'%MAX_BULK,fields={'lines':'Demasiadas líneas.'})
    parsed=[]
    for number,line in enumerate(lines,1):
        parts=[part.strip() for part in line.split(';')]
        if len(parts)==1:raw={'key':parts[0]} if '@' not in parts[0] or product['kind']!='m365' else {'username':parts[0]}
        elif len(parts)==2:raw={'username':parts[0],'password':parts[1]} if '@' in parts[0] else {'key':parts[0],'license_code':parts[1]}
        elif len(parts)==3:raw={'key':parts[0],'username':parts[1],'password':parts[2]}
        else:raise LicenseError('Línea %d: usa «clave», «usuario;contraseña» o «clave;usuario;contraseña».'%number,fields={'lines':'Formato no válido.'})
        try:values=_clean_secret(raw,method=method if method!='archivo' else '')
        except LicenseError as error:raise LicenseError('Línea %d: %s'%(number,error),fields={'lines':'Línea %d no válida.'%number})
        parsed.append(values)
    if method=='archivo':raise LicenseError('Las licencias con archivo se registran por filas, una con su archivo.',fields={'lines':'Usa las filas.'})
    return _register_parsed(c,product,fields,parsed,[None]*len(parsed),data,user,now,'lines')


def _register_parsed(c,product,fields,parsed,files,data,user,now,field):
    """Todo o nada: duplicados revisados (inventario y la propia lista), puestos libres comprobados y después el lote y sus licencias."""
    report,reason=guard_duplicates(c,product,parsed,data,user,now,label='Línea' if field=='lines' else 'Fila')
    extra=100 if reason else 0
    for number,values in enumerate(parsed,1):
        try:_free_seat(c,product,values,extra=extra)
        except LicenseError as error:raise LicenseError('%s %d: %s'%('Línea' if field=='lines' else 'Fila',number,error),409,{field if field=='lines' else field%number:'Licencia duplicada.'})
    batch=_batch(c,product,data,len(parsed),user,now)
    units=[_insert_unit(c,product,fields,values,batch,user,now,file=file,extra=extra) for values,file in zip(parsed,files)]
    _log_authorized(c,report,units,reason,product,user,now)
    fill_pending(c,product['id'],now,user)
    return units


# ---- ADI Duplicate Protection Pro ---------------------------------------------------------------------------------------
# Cada dato sensible se compara por su huella (HMAC con la clave del servidor), nunca en claro: ni la respuesta ni el historial
# contienen claves, usuarios ni contraseñas. Rojo = no se registra (serial o archivo ya registrado: sería la misma licencia dos veces);
# ámbar = coincidencia que puede ser legítima (una cuenta con varias licencias, mismo código del fabricante) y exige justificación
# de administración; una contraseña repetida por sí sola nunca se marca.
DUPLICATE_LABELS={'key':'Clave de producto o serial','username':'Usuario o correo de activación','account':'Usuario y contraseña','license_code':'Código del fabricante','file':'Archivo de licencia'}
LEVELS=('green','amber','red')


def credential_marks(values,product_id,key=None):
    key=key or _keys()[2];mark=lambda label,value:hmac.new(key,('dup:'+label+':'+value).encode(),hashlib.sha256).hexdigest()
    marks={};main=values.get('key') or values.get('serial');user=str(values.get('username') or '').strip().lower()
    if main:marks['key']=mark('key',re.sub(r'[\s-]+','',str(main)).upper())
    if user:
        marks['username']=mark('user',user)
        if values.get('password'):marks['account']=mark('account',user+'\x00'+str(values['password']))
    if values.get('license_code'):marks['license_code']=mark('code:%s'%product_id,re.sub(r'[\s-]+','',str(values['license_code'])).upper())
    if values.get('file_sha256'):marks['file']=mark('file',values['file_sha256'])
    return marks


def _credential_index(c,today,exclude=None):
    key=_keys()[2];index={}
    for row in c.execute('SELECT u.id,u.code,u.product_id,u.status,u.expires_at,u.activated,u.renewed_to,u.created_at,u.secret,i.name product FROM license_units u JOIN catalog_items i ON i.id=u.product_id ORDER BY u.id'):
        unit=dict(row)
        if unit['id']==exclude:continue
        try:values=unseal(unit['secret'])
        except LicenseError:continue
        state,_=state_of(unit,today)
        info={'unit_id':unit['id'],'code':unit['code'],'product_id':unit['product_id'],'product':unit['product'],'status':unit['status'],'state_label':STATES[state][0],'created_at':unit['created_at']}
        for kind,mark in credential_marks(values,unit['product_id'],key).items():index.setdefault((kind,mark),[]).append(info)
    return index


def check_duplicates(c,product,entries,today,exclude=None):
    """Coincidencias de cada licencia nueva (o editada) con el inventario y con las demás de la misma lista. Sin datos sensibles."""
    index=_credential_index(c,today,exclude);key=_keys()[2];seats=max(1,product.get('shared_seats') or 0);earlier={};results=[]
    for number,values in enumerate(entries,1):
        fields={}
        for kind,mark in credential_marks(values,product['id'],key).items():
            found=index.get((kind,mark),[]);rows=earlier.setdefault((kind,mark),[])
            if not found and not rows:fields[kind]={'level':'green','message':'Sin coincidencias.'}
            elif kind in ('key','file'):
                shared=seats>1 and all(item['product_id']==product['id'] for item in found) and len(found)+len(rows)<seats
                fields[kind]={'level':'green' if shared else 'red','message':('Clave compartida: puesto %d de %d.'%(len(found)+len(rows)+1,seats)) if shared else
                              (('Este serial' if kind=='key' else 'Este archivo de licencia')+(' ya se encuentra registrado en el inventario.' if found else ' está repetido en la fila %d de esta lista.'%rows[0]))}
            elif kind=='username':
                fields[kind]={'level':'amber','message':('Esta cuenta ya tiene %d %s en el inventario.'%(len(found),'licencia registrada' if len(found)==1 else 'licencias registradas') if found else 'Esta cuenta también está en la fila %d.'%rows[0])+' Una cuenta puede tener varias licencias legítimas: confirma con una justificación.'}
            elif kind=='account':
                fields[kind]={'level':'amber','message':'Ya existe una licencia con este mismo usuario y contraseña'+(' (fila %d).'%rows[0] if not found else '.')+' La contraseña registrada no se muestra.'}
            else:
                fields[kind]={'level':'amber','message':'Este código del fabricante ya está registrado en este producto'+(' (fila %d).'%rows[0] if not found else '.')}
            fields[kind]['matches']=found[:5];fields[kind]['rows']=rows[:5];fields[kind]['label']=DUPLICATE_LABELS[kind]
            rows.append(number)
        level=max((item['level'] for item in fields.values()),key=LEVELS.index,default='green')
        results.append({'row':number,'level':level,'fields':fields})
    overall=max((item['level'] for item in results),key=LEVELS.index,default='green')
    return {'level':overall,'entries':results,'reason_required':overall=='amber'}


def guard_duplicates(c,product,entries,data,user,now,exclude=None,label='Fila'):
    """Se repite al guardar (aunque el formulario ya lo haya comprobado): rojo bloquea; ámbar exige justificación de administración."""
    report=check_duplicates(c,product,entries,now.date(),exclude)
    if report['level']=='red':
        entry=next(item for item in report['entries'] if item['level']=='red');kind,info=next((k,v) for k,v in entry['fields'].items() if v['level']=='red')
        # Repetida en la propia lista = dato del formulario a corregir (400); ya registrada en el inventario = conflicto (409).
        raise LicenseError(('%s %d: '%(label,entry['row']) if len(entries)>1 else '')+info['message']+(' (%s)'%', '.join(m['code'] for m in info['matches']) if info['matches'] else ''),
                           409 if info['matches'] else 400,{(kind if label=='Fila' or len(entries)==1 else 'lines'):'Duplicado no permitido.'},{'duplicates':report})
    if report['level']=='amber':
        reason=re.sub(r'\s+',' ',str(data.get('duplicate_reason') or '')).strip()[:300]
        if user['role']!='administrador':raise LicenseError('Solo administración puede autorizar una coincidencia.',403,extra={'duplicates':report})
        if len(reason)<DUPLICATE_REASON_MIN:
            raise LicenseError('Posible licencia duplicada: revisa la coincidencia y, si es legítima, escribe la justificación.',409,{'duplicate_reason':'Justificación obligatoria (mínimo %d caracteres).'%DUPLICATE_REASON_MIN},{'duplicates':report,'reason_required':True})
        return report,reason
    return report,''


def _log_authorized(c,report,units,reason,product,user,now):
    """Cada coincidencia autorizada queda en el historial de la licencia: qué dato coincidía, con qué registros, quién, cuándo y por qué."""
    if not reason:return
    for entry,unit in zip(report['entries'],units):
        flagged=[(info['label'],info['matches']) for info in entry['fields'].values() if info['level']=='amber']
        if not flagged:continue
        detail='Coincidencia autorizada: '+'; '.join(label+(' con '+', '.join(m['code'] for m in matches) if matches else ' en la misma lista') for label,matches in flagged)+'. Motivo: '+reason
        event(c,'duplicado_autorizado',now,detail,unit,product['id'],user=user)


def _guard_delivery(c,units):
    """Un serial (o archivo) ya entregado no se entrega otra vez, salvo clave compartida con puestos libres. Autorizar una coincidencia al
    registrar no permite eludir esta regla."""
    if not units:return
    key=_keys()[2];delivered={}
    for row in c.execute("SELECT u.id,u.code,u.product_id,u.secret FROM license_units u WHERE u.status='entregada'"):
        try:values=unseal(row['secret'])
        except LicenseError:continue
        for kind,mark in credential_marks(values,row['product_id'],key).items():
            if kind in ('key','file'):delivered.setdefault(mark,[]).append(row['code'])
    for unit in units:
        try:values=unseal(unit['secret'])
        except LicenseError:continue
        seats=max(1,(_product(c,unit['product_id']).get('shared_seats') or 0))
        for kind,mark in credential_marks(values,unit['product_id'],key).items():
            if kind in ('key','file') and len(delivered.get(mark,[]))>=seats:
                raise LicenseError('%s ya fue entregado (%s) y esta licencia no admite otra asignación. Revisa el inventario antes de entregar.'%(unit['code']+': el serial' if kind=='key' else unit['code']+': el archivo de licencia',', '.join(delivered[mark][:3])),409)
            if kind in ('key','file'):delivered.setdefault(mark,[]).append(unit['code'])


def duplicate_review(c,now):
    """Informe administrativo del inventario guardado: solo lectura, nunca modifica registros históricos ni muestra credenciales."""
    today=now.date();key=_keys()[2];groups={kind:{} for kind in ('key','license_code','username','file')};stock=[];unreadable=[];seats={}
    for row in c.execute('SELECT u.*,i.name product,COALESCE(p.shared_seats,0) shared_seats FROM license_units u JOIN catalog_items i ON i.id=u.product_id LEFT JOIN license_products p ON p.item_id=u.product_id ORDER BY u.id'):
        unit=dict(row);state,_=state_of(unit,today);seats[unit['product_id']]=max(1,unit['shared_seats'] or 0)
        info={'unit_id':unit['id'],'code':unit['code'],'product_id':unit['product_id'],'product':unit['product'],'status':unit['status'],'state_label':STATES[state][0],'created_at':unit['created_at'],'hint':_hint(unit)}
        try:values=unseal(unit['secret'])
        except LicenseError:unreadable.append(dict(info,problem='La credencial guardada no se puede verificar.'));continue
        for kind,mark in credential_marks(values,unit['product_id'],key).items():
            if kind in groups:groups[kind].setdefault(mark,[]).append(info)
        problem=('Disponible pero vinculada a un cliente, una venta o una entrega.' if unit['status']=='disponible' and (unit['client_id'] or unit['delivery_id'] or unit['sale_id']) else
                 'Reservada sin venta, presupuesto ni orden.' if unit['status']=='reservada' and not (unit['sale_id'] or unit['quote_id'] or unit['order_id']) else
                 'Entregada sin registro de entrega.' if unit['status']=='entregada' and not unit['delivery_id'] else
                 'Entregada sin cliente.' if unit['status']=='entregada' and not unit['client_id'] else
                 'Marcada como activada sin fecha de activación.' if unit['activated'] and not unit['activated_at'] and unit['status']!='anulada' else '')
        if problem:stock.append(dict(info,problem=problem))
    def many(kind,keep):return [items for items in groups[kind].values() if len(items)>1 and keep(items)]
    within=lambda items:len({i['product_id'] for i in items})==1 and len(items)<=seats[items[0]['product_id']]
    serials=many('key',lambda items:not within(items));files=many('file',lambda items:not within(items))
    # Entregas en conflicto: el mismo serial o archivo entregado más veces de las que permite la licencia.
    delivered=[]
    for items in list(groups['key'].values())+list(groups['file'].values()):
        given=[i for i in items if i['status']=='entregada']
        if given and len(given)>seats.get(given[0]['product_id'],1):delivered.append(given)
    report={'serials':serials,'files':files,'codes':many('license_code',lambda items:True),'accounts':many('username',lambda items:len({i['product_id'] for i in items})>1),
            'delivered':delivered,'stock':stock,'unreadable':unreadable,'checked_at':stamp(now)}
    report['total']=sum(len(report[k]) for k in ('serials','files','codes','accounts','delivered','stock','unreadable'))
    return report


# ---- Ajuste de stock: el inventario son licencias individuales (LIC-…), no un contador ------------------------------------
ADJUST_REASONS={'duplicada':'Registro duplicado','incorrecta':'Registro incorrecto','invalida':'Clave inválida o rechazada por el fabricante','proveedor':'Devuelta al proveedor','extravio':'No localizada o extraviada','otro':'Otro motivo'}


def _hint(unit):
    """Últimos 4 caracteres de la clave o del usuario, enmascarados, para distinguir registros duplicados sin mostrar la credencial."""
    try:values=unseal(unit['secret'])
    except LicenseError:return ''
    text=re.sub(r'[\s-]+','',values.get('key') or values.get('username') or '')
    return ('•••• '+text[-4:]) if len(text)>=6 else ''


def stock_detail(c,product_id,now):
    if not c.execute('SELECT 1 FROM license_products WHERE item_id=?',(product_id,)).fetchone():raise LicenseError('Este producto no tiene inventario de licencias.',404)
    product=_product(c,product_id);today=now.date().isoformat()
    rows=[dict(r) for r in c.execute("SELECT u.id,u.code,u.secret,u.created_at,u.purchased_at,u.expires_at,u.notes,b.supplier,b.invoice FROM license_units u LEFT JOIN license_batches b ON b.id=u.batch_id "
                                       "WHERE u.product_id=? AND u.status='disponible' AND (u.expires_at='' OR u.expires_at>=?) ORDER BY u.id",(product_id,today))]
    counts={key:0 for key in STATUSES}
    for r in c.execute('SELECT status,COUNT(*) n FROM license_units WHERE product_id=? GROUP BY status',(product_id,)):counts[r['status']]=r['n']
    return {'product':{'id':product['id'],'name':product['name']},'available':[{k:v for k,v in dict(r,hint=_hint(r)).items() if k!='secret'} for r in rows],'counts':counts,'reasons':ADJUST_REASONS}


def adjust_stock(c,data,user,now):
    """Corrige las existencias disponibles de un producto al número real. Para disminuir hay que elegir QUÉ licencias se retiran:
    pasan a «Anulada» (no se venden) con el motivo, y sus claves, usuarios y su historial se conservan. Nunca se tocan licencias
    reservadas, entregadas, ventas, pagos ni clientes. Para aumentar hay que registrar las licencias reales con «Agregar stock»."""
    if user['role']!='administrador':raise LicenseError('Solo administración ajusta el stock.',403)
    pid=str(data.get('item_id') or '')
    if not pid.isdigit():raise LicenseError('Producto no válido.',404)
    detail=stock_detail(c,int(pid),now);available={u['id']:u for u in detail['available']};before=len(available)
    real=str(data.get('real_quantity') if data.get('real_quantity') is not None else '').strip()
    if not real.isdigit():raise LicenseError('Indica la cantidad real disponible (0 o más).',fields={'real_quantity':'Cantidad no válida.'})
    real=int(real)
    if real>before:raise LicenseError('Para aumentar el stock registra las %d licencia(s) reales con «Agregar stock»: el inventario se compone de licencias individuales con su clave.'%(real-before),409,{'real_quantity':'Registra las licencias que faltan.'})
    if real==before:raise LicenseError('La cantidad real coincide con el stock disponible: no hay nada que ajustar.',409,{'real_quantity':'Sin diferencia.'})
    reason=str(data.get('reason') or '')
    if reason not in ADJUST_REASONS:raise LicenseError('Selecciona el motivo del ajuste.',fields={'reason':'Motivo obligatorio.'})
    notes=_text(data,'notes',300,'Las observaciones')
    if reason=='otro' and len(notes)<5:raise LicenseError('Describe el motivo en las observaciones.',fields={'notes':'Detalle obligatorio.'})
    chosen=[int(x) for x in (data.get('unit_ids') or []) if str(x).isdigit()]
    if len(set(chosen))!=len(chosen) or any(x not in available for x in chosen):raise LicenseError('Alguna licencia elegida ya no está disponible. Vuelve a abrir el ajuste.',409,{'unit_ids':'Selección no válida.'})
    if len(chosen)!=before-real:raise LicenseError('Selecciona exactamente %d licencia(s) para retirar del inventario.'%(before-real),fields={'unit_ids':'Selección incompleta.'})
    label=ADJUST_REASONS[reason]+('. '+notes if notes else '');moment=stamp(now)
    for unit in chosen:
        if not c.execute("UPDATE license_units SET status='anulada',delivery_id=NULL,updated_at=? WHERE id=? AND status='disponible'",(moment,unit)).rowcount:
            raise LicenseError('Una licencia cambió de estado durante el ajuste. Vuelve a intentarlo.',409)
        event(c,'retirada',now,'Retirada del inventario por ajuste de stock (disponibles: %d → %d). Motivo: %s. La clave y el historial se conservan.'%(before,real,label),unit,int(pid),user=user)
    codes=[available[x]['code'] for x in chosen]
    event(c,'ajuste_stock',now,'Ajuste de stock de «%s»: disponibles %d → %d. Retiradas: %s. Motivo: %s. Responsable: %s.'%(detail['product']['name'],before,real,', '.join(codes),label,user['name']),product=int(pid),user=user)
    return {'before':before,'after':real,'retired':codes}


def unit_row(c,unit_id):
    row=c.execute('SELECT * FROM license_units WHERE id=?',(unit_id,)).fetchone()
    if not row:raise LicenseError('Licencia no disponible.',404)
    return dict(row)


def _edit_credential(unit,product,data):
    """Actualización parcial de la credencial: lo escrito sustituye a lo guardado y el resto se conserva (nunca se borra un dato sin
    querer). Si la licencia tiene datos de otro método (registrada antes de elegirlo), se validan todos sin descartar ninguno."""
    method=product.get('activation_method') or '';typed={key:data.get(key) for key in SECRET_INPUTS if str(data.get(key) or '').strip()}
    file=_clean_file(data) if method=='archivo' else None
    if not typed and not file:return None
    current=unseal(unit['secret']);merged={key:value for key,value in current.items() if key in SECRET_INPUTS+('serial',)};merged.update(typed)
    if 'serial' in merged and 'key' not in merged:merged['key']=merged.pop('serial')
    fits=set(merged)<=set(ACTIVATION_FIELDS.get(method,SECRET_INPUTS))
    values=_clean_secret(merged,required=method!='archivo',method=method if fits else '')
    sha=file['sha256'] if file else current.get('file_sha256')
    if method=='archivo' and not sha:raise LicenseError('Adjunta el archivo de licencia del fabricante.',fields={'file':'Archivo obligatorio.'})
    if sha:values['file_sha256']=sha
    return values,file


def edit(c,unit_id,data,user,now):
    """Corrige datos de una licencia no entregada. La credencial solo se reemplaza si se escribe una nueva (nunca se sobrescribe sin querer)."""
    unit=unit_row(c,unit_id)
    if unit['status'] in ('entregada','anulada'):
        if unit['status']=='entregada' and set(data)-{'action','notes','activated'}<=set():pass
        else:raise LicenseError('Una licencia %s no se modifica: usa «Confirmar activación» o «Renovar licencia».'%STATUSES[unit['status']].lower(),409)
    product=_product(c,unit['product_id']);fields=_clean_unit(product,dict({k:unit[k] for k in FIELDS},**{k:v for k,v in data.items() if k in FIELDS}),now.date());changes=[]
    secret,mark,seat=unit['secret'],unit['fingerprint'],unit['seat'];report,reason,file=None,'',None
    credential=_edit_credential(unit,product,data)
    if credential:
        values,file=credential;report,reason=guard_duplicates(c,product,[values],data,user,now,exclude=unit_id)
        seat,mark=_free_seat(c,product,values,exclude=unit_id,extra=100 if reason else 0);secret=seal(values);changes.append('credencial actualizada'+(' con un archivo de licencia nuevo' if file else ''))
    changes+=[FIELD_LABELS[key].lower() for key in FIELDS if fields[key]!=unit[key]]
    notes=_text(data,'notes',500,'Las observaciones') if 'notes' in data else unit['notes']
    activated=int(data['activated']) if data.get('activated') in (True,False) else (1 if fields['activated_at'] else unit['activated'])
    if unit['status'] in ('disponible','vencida'):
        # En inventario no hay activación real: solo se puede retirar un dato anterior inconsistente (queda en el historial).
        if fields['activated_at']:raise LicenseError('Una licencia en inventario aún no está activada: deja vacía la fecha de activación.',fields={'activated_at':'Solo al entregar o confirmar la activación.'})
        activated=0
    if activated!=unit['activated']:changes.append('marcada como activada' if activated else 'activación retirada')
    status=unit['status']
    if status in ('disponible','vencida'):status='vencida' if fields['expires_at'] and fields['expires_at']<now.date().isoformat() else 'disponible'
    c.execute('UPDATE license_units SET edition=?,license_type=?,manufacturer=?,version=?,devices=?,term=?,purchased_at=?,activated_at=?,expires_at=?,download_url=?,instructions=?,secret=?,fingerprint=?,seat=?,notes=?,activated=?,status=?,updated_at=? WHERE id=?',
              (*[fields[key] for key in FIELDS],secret,mark,seat,notes,activated,status,stamp(now),unit_id))
    if file:_store_file(c,unit_id,file,user,now)
    if report:_log_authorized(c,report,[unit_id],reason,product,user,now)
    event(c,'editada',now,'Datos corregidos: '+(', '.join(changes) if changes else 'sin cambios')+'.',unit_id,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)
    if status=='disponible':fill_pending(c,product['id'],now,user)


def confirm_activation(c,unit_id,activated_at,user,now):
    """Registra la fecha real de activación que indica el personal y recalcula el vencimiento (si cuenta desde la activación).
    Es un dato declarado: no se comprueba con el fabricante."""
    unit=unit_row(c,unit_id)
    if unit['status'] not in ('entregada','reservada'):raise LicenseError('Solo se registra la activación de una licencia vendida.',409)
    if unit['renewed_to']:raise LicenseError('Esta licencia fue renovada: registra la activación en la nueva.',409)
    day=_date(activated_at or now.date().isoformat(),'activated_at',now.date(),future=False)
    if unit['purchased_at'] and day<unit['purchased_at']:raise LicenseError('La activación no puede ser anterior a la compra.',fields={'activated_at':'Revisa la fecha.'})
    product=_product(c,unit['product_id']);expires=unit['expires_at']
    if product.get('validity_mode')=='activacion':expires=compute_expiry(product,unit['purchased_at'],day)
    c.execute('UPDATE license_units SET activated=1,activated_at=?,expires_at=?,updated_at=? WHERE id=?',(day,expires,stamp(now),unit_id))
    event(c,'activada',now,'Activación registrada el %s (dato indicado por el personal; no verificado con el fabricante).%s'%(day,' Vence el %s.'%expires if expires else ' Sin vencimiento.'),unit_id,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)
    return expires


def _sale_lock(c,unit):
    if unit.get('sale_id') and unit['status']=='reservada':
        code=c.execute('SELECT code FROM license_sales WHERE id=?',(unit['sale_id'],)).fetchone()
        raise LicenseError('Esta licencia está reservada para la venta %s: cancela la venta para liberarla.'%(code[0] if code else ''),409)


def void(c,unit_id,reason,user,now):
    unit=unit_row(c,unit_id);reason=str(reason or '').strip();_sale_lock(c,unit)
    if unit['status']=='anulada':raise LicenseError('La licencia ya está anulada.',409)
    if len(reason)<5:raise LicenseError('Indica el motivo.',fields={'reason':'Motivo obligatorio.'})
    returned=unit['status']=='entregada'
    c.execute("UPDATE license_units SET status='anulada',updated_at=? WHERE id=?",(stamp(now),unit_id))
    if not returned:c.execute('UPDATE license_units SET delivery_id=NULL WHERE id=?',(unit_id,))
    event(c,'devolucion' if returned else 'anulada',now,('Devolución autorizada: la licencia entregada queda anulada y no vuelve al inventario. Motivo: ' if returned else 'Registro invalidado. Motivo: ')+reason[:300],
          unit_id,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)


def retire_activation(c,unit_id,reason,user,now):
    """Corrección manual autorizada de un dato inconsistente: una licencia en inventario (sin vender) que figura con activación. Se retira
    la activación y se recalcula el vencimiento; los valores anteriores, el motivo, la persona y la hora quedan en el historial."""
    if user['role']!='administrador':raise LicenseError('Solo administración corrige datos de licencias.',403)
    unit=unit_row(c,unit_id);reason=re.sub(r'\s+',' ',str(reason or '')).strip()
    if unit['status'] not in ('disponible','vencida'):raise LicenseError('Solo se retira la activación de una licencia en inventario (sin vender).',409)
    if not (unit['activated'] or unit['activated_at']):raise LicenseError('Esta licencia no tiene activación registrada.',409)
    if len(reason)<5:raise LicenseError('Indica el motivo de la corrección.',fields={'reason':'Motivo obligatorio.'})
    product=_product(c,unit['product_id'])
    expires=unit['expires_at'] if product.get('validity_mode')=='fija' else compute_expiry(product,unit['purchased_at'],'')
    status='vencida' if expires and expires<now.date().isoformat() else 'disponible'
    c.execute("UPDATE license_units SET activated=0,activated_at='',expires_at=?,status=?,updated_at=? WHERE id=?",(expires,status,stamp(now),unit_id))
    event(c,'correccion',now,'Corrección autorizada de datos inconsistentes: se retira la activación registrada en inventario (activación anterior: %s; vencimiento anterior: %s). Motivo: %s'%(unit['activated_at'] or 'sin fecha',unit['expires_at'] or 'sin fecha',reason[:300]),unit_id,unit['product_id'],user=user)
    return status


def release(c,unit_id,user,now,from_sale=False):
    """Anula la reserva: la licencia vuelve a estar disponible solo si no fue activada ni entregada."""
    unit=unit_row(c,unit_id)
    if not from_sale:_sale_lock(c,unit)
    if unit['status']!='reservada':raise LicenseError('Esta licencia no está reservada.',409)
    if unit['activated']:raise LicenseError('La licencia ya fue activada: no vuelve al inventario. Anúlala si no se usará.',409)
    expired=unit['expires_at'] and unit['expires_at']<now.date().isoformat()
    c.execute("UPDATE license_units SET status=?,quote_id=NULL,quote_item_id=NULL,order_id=NULL,client_id=NULL,delivery_id=NULL,reserved_at='',updated_at=? WHERE id=?",('vencida' if expired else 'disponible',stamp(now),unit_id))
    event(c,'reserva_anulada',now,'Reserva anulada: la licencia vuelve a estar %s.'%('vencida' if expired else 'disponible'),unit_id,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)


# ---- Renovaciones -----------------------------------------------------------------------------------------------------
def renew(c,unit_id,data,user,now):
    """«Renovar licencia»: nuevo período desde la fecha efectiva indicada (no se asume el día del pago). Con una clave nueva se crea otra
    licencia para el mismo cliente; sin ella se prolonga la misma. La renovación queda en el historial y nada anterior se borra."""
    unit=unit_row(c,unit_id)
    if unit['status']!='entregada':raise LicenseError('Solo se renuevan licencias entregadas a un cliente.',409)
    if unit['renewed_to']:raise LicenseError('Esta licencia ya fue renovada con otra clave.',409)
    product=_product(c,unit['product_id'])
    duration=str(data.get('duration') or product.get('duration') or 'anual')
    if duration not in DURATIONS or duration=='perpetua':raise LicenseError('Elige el nuevo período de vigencia (las licencias perpetuas no se renuevan).',fields={'duration':'Período no válido.'})
    custom=None
    if duration=='personalizada':
        raw=str(data.get('duration_months') or '').strip()
        if not raw.isdigit() or not 1<=int(raw)<=120:raise LicenseError('Indica los meses del nuevo período (1 a 120).',fields={'duration_months':'Meses no válidos.'})
        custom=int(raw)
    start=_date(data.get('starts_at'),'starts_at')
    if not start:raise LicenseError('Indica la fecha efectiva de inicio de la nueva vigencia (según las condiciones del fabricante).',fields={'starts_at':'Fecha obligatoria.'})
    manual=_date(data.get('expires_at'),'expires_at')
    expires=manual or add_months(date.fromisoformat(start),MONTHS.get(duration,custom)).isoformat()
    if expires<=start:raise LicenseError('El nuevo vencimiento debe ser posterior al inicio.',fields={'expires_at':'Revisa la fecha.'})
    cost=_cents(data.get('cost'),'cost','el costo');price=_cents(data.get('price'),'price','el precio de venta')
    values=_clean_secret(data,required=False);new_unit=None
    if values:
        values=_clean_secret(data)
        fields={key:unit[key] for key in FIELDS};fields.update(purchased_at=start if start<=now.date().isoformat() else now.date().isoformat(),activated_at='',expires_at=expires,term=DURATIONS[duration] if duration!='personalizada' else '%d meses'%custom)
        seat,mark=_free_seat(c,product,values)
        new_unit=c.execute('INSERT INTO license_units(product_id,kind,edition,license_type,manufacturer,version,devices,term,purchased_at,activated_at,expires_at,download_url,instructions,secret,fingerprint,seat,status,quote_id,quote_item_id,order_id,client_id,delivery_id,delivered_at,renewed_from,notes,created_by,created_at,updated_at) '
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'entregada',?,?,?,?,?,?,?,?,?,?,?)",
                           (unit['product_id'],unit['kind'],fields['edition'],fields['license_type'],fields['manufacturer'],fields['version'],fields['devices'],fields['term'],fields['purchased_at'],'',expires,
                            fields['download_url'],fields['instructions'],seal(values),mark,seat,unit['quote_id'],unit['quote_item_id'],unit['order_id'],unit['client_id'],unit['delivery_id'],stamp(now),unit_id,
                            'Renovación de '+unit['code'],user['id'],stamp(now),stamp(now))).lastrowid
        c.execute('UPDATE license_units SET renewed_to=?,updated_at=? WHERE id=?',(new_unit,stamp(now),unit_id))
    else:
        c.execute('UPDATE license_units SET expires_at=?,updated_at=? WHERE id=?',(expires,stamp(now),unit_id))
    renewal=c.execute('INSERT INTO license_renewals(unit_id,new_unit_id,client_id,previous_expires_at,starts_at,expires_at,duration,duration_months,cost_cents,price_cents,key_changed,notes,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (unit_id,new_unit,unit['client_id'],unit['expires_at'],start,expires,duration,custom,cost,price,1 if new_unit else 0,_text(data,'notes',300,'Las observaciones'),user['id'],stamp(now))).lastrowid
    detail='Renovada: nueva vigencia del %s al %s%s.'%(start,expires,' con una clave nueva' if new_unit else '')+(' Costo %s, precio %s.'%(usd(cost),usd(price)) if cost is not None or price is not None else '')
    event(c,'renovada',now,detail,unit_id,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)
    if new_unit:event(c,'registrada',now,'Licencia de renovación de %s, entregada al mismo cliente.'%unit['code'],new_unit,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)
    return {'renewal_id':renewal,'new_unit_id':new_unit,'expires_at':expires}


def usd(cents):
    return '—' if cents is None else '$'+format(cents//100,',').replace(',','.')+',%02d'%(cents%100)


# ---- Reservas desde presupuestos --------------------------------------------------------------------------------------
def pending_items(c,product_id=None,order_id=None):
    """Partidas aprobadas de productos con inventario que aún no tienen todas sus unidades reservadas (las más antiguas primero)."""
    sql=("SELECT q.id quote_id,q.code quote_code,q.order_id,q.decided_at,i.id item_id,i.catalog_id product_id,i.quantity,i.description,"
         "(SELECT COUNT(*) FROM license_units u WHERE u.quote_item_id=i.id AND u.status IN ('reservada','entregada') AND u.renewed_from IS NULL) assigned "
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
    for unit in c.execute("SELECT id FROM license_units WHERE product_id=? AND status='disponible' AND (expires_at='' OR expires_at>=?) ORDER BY expires_at='',expires_at,id LIMIT ?",(item['product_id'],today,item['missing'])).fetchall():
        client=_client_of(c,item['order_id'])
        if c.execute("UPDATE license_units SET status='reservada',quote_id=?,quote_item_id=?,order_id=?,client_id=?,reserved_at=?,updated_at=? WHERE id=? AND status='disponible'",
                     (item['quote_id'],item['item_id'],item['order_id'],client,stamp(now),stamp(now),unit['id'])).rowcount:
            done+=1;event(c,'reservada',now,'Reservada para el presupuesto %s.'%item['quote_code'],unit['id'],item['product_id'],order=item['order_id'],client=client,user=user,actor=actor)
    return done


def reserve_for_quote(c,quote,now,user=None,actor=''):
    """Al aprobarse un presupuesto: reserva unidades concretas para cada partida de licencia aprobada. Lo que falte queda pendiente."""
    expire(c,now);reserved=missing=0
    for item in pending_items(c,order_id=quote['order_id']):
        if item['quote_id']!=quote['id']:continue
        got=_reserve_item(c,item,now,user,actor);reserved+=got;missing+=item['missing']-got
    return {'reserved':reserved,'missing':missing}


def fill_pending(c,product_id,now,user=None):
    total=0
    for item in pending_items(c,product_id=product_id):
        total+=_reserve_item(c,item,now,user)
    return total


# ---- Entrega (confirmación manual de administración) ------------------------------------------------------------------
def _order_units(c,order_id,delivery_id=None):
    sql="SELECT u.*,i.name product_name FROM license_units u JOIN catalog_items i ON i.id=u.product_id WHERE u.order_id=?"
    args=[order_id]
    if delivery_id is not None:sql+=' AND u.delivery_id=?';args.append(delivery_id)
    return [dict(r) for r in c.execute(sql+' ORDER BY u.id',args)]


def _delivery_units(c,delivery_id):
    return [dict(r) for r in c.execute("SELECT u.*,i.name product_name FROM license_units u JOIN catalog_items i ON i.id=u.product_id WHERE u.delivery_id=? ORDER BY u.id",(delivery_id,))]


def _resolve_order(c,client_id,order_code,quote_code):
    order=quote=None
    if order_code:
        row=c.execute("SELECT o.id,d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE upper(o.code)=upper(?)",(reception.current_order_code(c,order_code),)).fetchone()
        if not row:raise LicenseError('No existe una orden con ese número.',404,{'order_code':'Orden no encontrada.'})
        if client_id and row['client_id']!=client_id:raise LicenseError('Esa orden pertenece a otro cliente.',409,{'order_code':'Otro cliente.'})
        order=row['id'];client_id=row['client_id']
    if quote_code:
        row=c.execute("SELECT id,order_id FROM quotes WHERE upper(code)=upper(?) AND deleted_at=''",(quote_code.strip(),)).fetchone()
        if not row:raise LicenseError('No existe un presupuesto con ese número.',404,{'quote_code':'Presupuesto no encontrado.'})
        if order and row['order_id']!=order:raise LicenseError('Ese presupuesto es de otra orden.',409,{'quote_code':'Otra orden.'})
        quote=row['id'];order=row['order_id'];client_id=client_id or _client_of(c,order)
    return client_id,order,quote


def deliver(c,data,user,now):
    """Entrega confirmada manualmente por administración. Dos casos: las licencias reservadas de una orden (desde su presupuesto) o una
    venta directa a un cliente (con orden o presupuesto opcional). No depende de la confirmación del pago; si la orden tiene saldo
    pendiente hay que aceptarlo expresamente, y queda registrado. Una licencia entregada no puede entregarse otra vez."""
    import equipment
    if user['role']!='administrador':raise LicenseError('Solo administración confirma entregas de licencias.',403)
    order_id=int(data['order_id']) if str(data.get('order_id') or '').isdigit() else None
    if order_id:
        client=_client_of(c,order_id);quote=None
        wanted={int(x) for x in str(data.get('unit_ids') or '').split(',') if x.strip().isdigit()}
        units=[u for u in _order_units(c,order_id) if u['status']=='reservada' and (not wanted or u['id'] in wanted)]
        if not units:raise LicenseError('No hay licencias reservadas para entregar en esta orden.',409)
        kind='orden'
    else:
        client=int(data['client_id']) if str(data.get('client_id') or '').isdigit() else None
        if not client or not c.execute('SELECT 1 FROM clients WHERE id=?',(client,)).fetchone():raise LicenseError('Selecciona el cliente que recibe la licencia.',fields={'client_id':'Cliente obligatorio.'})
        client,order_id,quote=_resolve_order(c,client,str(data.get('order_code') or ''),str(data.get('quote_code') or ''))
        pid=str(data.get('product_id') or '')
        if not pid.isdigit():raise LicenseError('Selecciona el producto.',fields={'product_id':'Producto obligatorio.'})
        unit_id=str(data.get('unit_id') or '')
        today=now.date().isoformat()
        if unit_id.isdigit():
            row=c.execute("SELECT * FROM license_units WHERE id=? AND product_id=?",(int(unit_id),int(pid))).fetchone()
            if not row or row['status']!='disponible' or (row['expires_at'] and row['expires_at']<today):raise LicenseError('Esa licencia ya no está disponible (pudo entregarse o vencer).',409,{'unit_id':'No disponible.'})
        else:
            row=c.execute("SELECT * FROM license_units WHERE product_id=? AND status='disponible' AND (expires_at='' OR expires_at>=?) ORDER BY expires_at='',expires_at,id LIMIT 1",(int(pid),today)).fetchone()
            if not row:raise LicenseError('No hay licencias disponibles de este producto.',409,{'product_id':'Sin existencias.'})
        units=[dict(row,product_name=_product(c,int(pid))['name'])];kind='directa'
    balance=equipment.money(c,order_id)['balance_cents'] if order_id else 0
    if balance>0 and data.get('accept_balance') is not True:
        raise LicenseError('La orden tiene un saldo pendiente de %s. Para entregar igualmente, confírmalo expresamente.'%equipment.usd(balance),409,{'accept_balance':'Confirmación obligatoria.'})
    notes=_text(data,'notes',300,'Las observaciones');moment=stamp(now);token=secrets.token_urlsafe(32)
    # Datos comerciales informativos: precio, descuento autorizado y estado del pago. No se confirma ni registra ningún pago.
    price=_cents(data.get('price'),'price','el precio de venta')
    if price is None and kind=='directa':price=_product(c,units[0]['product_id'])['price_cents']
    discount=_cents(data.get('discount'),'discount','el descuento') or 0
    if price is not None and discount>price:raise LicenseError('El descuento no puede superar el precio de venta.',fields={'discount':'Descuento mayor que el precio.'})
    payment=str(data.get('payment_status') or '')
    if payment not in ('','pagado','parcial','pendiente','incluido'):raise LicenseError('Selecciona el estado del pago.',fields={'payment_status':'Opción no válida.'})
    activation=_date(data.get('activated_at'),'activated_at',now.date(),future=False) if data.get('activated') is True else ''
    if data.get('activated') is True and not activation:raise LicenseError('Indica la fecha real de activación.',fields={'activated_at':'Fecha obligatoria.'})
    delivery=c.execute("INSERT INTO license_deliveries(order_id,client_id,kind,status,payment_confirmed_by,payment_confirmed_at,balance_cents,authorized_by,authorized_at,token_hash,token_expires_at,notes,price_cents,discount_cents,payment_status,created_at,updated_at) VALUES (?,?,?,'autorizada',?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (order_id,client,kind,user['id'],moment,balance,user['id'],moment,_hash(token),stamp(now+timedelta(hours=LINK_HOURS)),notes,price,discount,payment,moment,moment)).lastrowid
    _guard_delivery(c,units)
    for unit in units:
        allowed=('reservada',) if kind=='orden' else ('disponible',)
        if not c.execute("UPDATE license_units SET status='entregada',delivered_at=?,client_id=?,order_id=COALESCE(order_id,?),quote_id=COALESCE(quote_id,?),delivery_id=?,updated_at=? WHERE id=? AND status IN (%s)"%','.join('?'*len(allowed)),
                         (moment,client,order_id,quote,delivery,moment,unit['id'],*allowed)).rowcount:
            raise LicenseError('Una licencia cambió de estado mientras se entregaba. Vuelve a intentarlo.',409)
        event(c,'entregada',now,'Entrega confirmada manualmente por administración%s.%s'%(' con saldo pendiente de '+equipment.usd(balance)+' aceptado' if balance>0 else '',' '+notes if notes else ''),unit['id'],unit['product_id'],delivery,order_id,client,user)
    event(c,'entrega_autorizada',now,'Entrega de %d %s al cliente. Enlace privado válido %d horas.%s'%(len(units),'licencia' if len(units)==1 else 'licencias',LINK_HOURS,
          (' Precio %s, descuento %s, total %s; pago: %s (informativo).'%(usd(price),usd(discount),usd(price-discount),payment or 'sin indicar')) if price is not None else ''),delivery=delivery,order=order_id,client=client,user=user)
    if activation:
        for unit in units:confirm_activation(c,unit['id'],activation,user,now)
    if order_id:
        import order_workspace
        order_workspace.event(c,order_id,user['id'],now,'follow_up','Licencias entregadas: '+', '.join(u['code']+' ('+u['product_name']+')' for u in units)+'.')
    return delivery,token


def order_info(c,code):
    """Resumen informativo de una orden para la venta: cliente, saldo y presupuestos. None si no existe."""
    import equipment
    row=c.execute("SELECT o.id,o.code,d.client_id,cl.name client FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE upper(o.code)=upper(?)",(reception.current_order_code(c,code),)).fetchone()
    if not row:return None
    money=equipment.money(c,row['id'])
    return {'order_id':row['id'],'code':row['code'],'client_id':row['client_id'],'client':row['client'],'balance_cents':money['balance_cents'],'paid_cents':money['paid_cents'],
            'quotes':[r[0] for r in c.execute("SELECT code FROM quotes WHERE order_id=? AND deleted_at='' ORDER BY version DESC",(row['id'],))]}


def delivery_row(c,delivery_id):
    row=c.execute('SELECT * FROM license_deliveries WHERE id=?',(delivery_id,)).fetchone()
    if not row:raise LicenseError('Entrega no disponible.',404)
    return dict(row)


def renew_link(c,delivery_id,user,now):
    if user['role']!='administrador':raise LicenseError('Solo administración puede generar el enlace de entrega.',403)
    delivery=delivery_row(c,delivery_id)
    if delivery['status']!='autorizada':raise LicenseError('La entrega no está confirmada.',409)
    token=secrets.token_urlsafe(32)
    c.execute("UPDATE license_deliveries SET token_hash=?,token_expires_at=?,code_hash='',code_expires_at='',code_failures=0,updated_at=? WHERE id=?",(_hash(token),stamp(now+timedelta(hours=LINK_HOURS)),stamp(now),delivery_id))
    event(c,'enlace_renovado',now,'Nuevo enlace privado de entrega (el anterior deja de funcionar).',delivery=delivery_id,order=delivery['order_id'],client=delivery['client_id'],user=user)
    return token


# ---- Consulta privada de credenciales ---------------------------------------------------------------------------------
def lookup(c,token,now):
    if not re.fullmatch(r'[A-Za-z0-9_-]{30,80}',token or ''):return None
    row=c.execute("SELECT * FROM license_deliveries WHERE token_hash=? AND status='autorizada'",(_hash(token),)).fetchone()
    if not row or datetime.fromisoformat(row['token_expires_at'])<now:return None
    return dict(row)


def _same_identification(a,b):
    clean=lambda value:re.sub(r'[\s.-]+','',str(value or '')).upper()
    return bool(clean(a)) and hmac.compare_digest(clean(a),clean(b))


def request_code(c,delivery,identification,now):
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
    code=re.sub(r'\D','',str(code or ''))
    if delivery['code_failures']>=MAX_CODE_FAILURES or not delivery['code_hash'] or not delivery['code_expires_at'] or datetime.fromisoformat(delivery['code_expires_at'])<now:return None
    if len(code)!=6 or not hmac.compare_digest(delivery['code_hash'],_hash(str(delivery['id'])+':'+code)):
        c.execute('UPDATE license_deliveries SET code_failures=code_failures+1,updated_at=? WHERE id=?',(stamp(now),delivery['id']));return None
    units=_delivery_units(c,delivery['id'])
    # Solo las licencias que siguen entregadas a este cliente (una devolución las retira del enlace).
    if not any(u['status']=='entregada' for u in units):return None
    c.execute("UPDATE license_deliveries SET code_hash='',code_expires_at='',reveal_count=reveal_count+1,last_revealed_at=?,updated_at=? WHERE id=?",(stamp(now),stamp(now),delivery['id']))
    event(c,'credenciales_consultadas',now,'El cliente consultó sus credenciales por el enlace privado.'+(' Origen: '+origin[:80] if origin else ''),delivery=delivery['id'],order=delivery['order_id'],client=delivery['client_id'],actor='cliente')
    return card(c,delivery['id'],private=True)


def credentials(unit,c=None):
    values=unseal(unit['secret'])
    items=[{'key':key,'label':SECRET_LABELS[key],'value':values[key]} for key in ('key','serial','username','password','license_code') if values.get(key)]
    found=c.execute('SELECT name,size FROM license_files WHERE unit_id=?',(unit['id'],)).fetchone() if c is not None else None
    if found:items.append({'key':'file','label':'Archivo de licencia','value':found['name'],'size':found['size'],'file':True})
    return items


def admin_reveal(c,unit_id,user,now):
    if user['role']!='administrador':raise LicenseError('Acceso no permitido.',403)
    unit=unit_row(c,unit_id)
    event(c,'credenciales_consultadas',now,'Credencial consultada por administración.',unit_id,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)
    return credentials(unit,c)


def admin_file(c,unit_id,user,now):
    """Descarga del archivo de licencia por administración; queda en el historial como cualquier consulta de credenciales."""
    if user['role']!='administrador':raise LicenseError('Acceso no permitido.',403)
    unit=unit_row(c,unit_id);found=file_of(c,unit_id)
    if not found:raise LicenseError('Esta licencia no tiene archivo.',404)
    event(c,'archivo_descargado',now,'Archivo de licencia descargado por administración.',unit_id,unit['product_id'],order=unit['order_id'],client=unit['client_id'],user=user)
    return found


METHODS={'clave':'Licencia con clave de producto','cuenta':'Licencia mediante cuenta','cuenta_clave':'Licencia con cuenta y clave',
         'mixta':'Activación mixta (clave y cuenta)','archivo':'Licencia con archivo del fabricante'}


def method_of(unit,stored=''):
    """Método de activación: el guardado en el producto o, en productos anteriores, el que se deduce de los campos guardados (cifrados).
    Devuelve también los NOMBRES de los campos presentes; nunca sus valores."""
    try:
        values=unseal(unit['secret'])
    except Exception:
        return stored,[]
    present=[key for key in ('key','serial','license_code','username','password') if values.get(key)]
    if stored in ACTIVATION:return stored,[SECRET_LABELS[key] for key in present]+(['Archivo de licencia'] if values.get('file_sha256') else [])
    has_key=any(key in present for key in ('key','serial','license_code'));has_account=any(key in present for key in ('username','password'))
    method='cuenta_clave' if has_key and has_account else 'cuenta' if has_account else 'clave' if has_key else ''
    return method,[SECRET_LABELS[key] for key in present]


def card(c,delivery_id,private=False,now=None):
    delivery=delivery_row(c,delivery_id)
    today=now.date() if now else date.today();soon=display_settings(c)['soon_days']
    client=c.execute('SELECT name FROM clients WHERE id=?',(delivery['client_id'],)).fetchone()
    order=c.execute("SELECT COALESCE(code,'OP-'||printf('%05d',id)) code FROM orders WHERE id=?",(delivery['order_id'],)).fetchone() if delivery['order_id'] else None
    items=[]
    for unit in _delivery_units(c,delivery_id):
        if unit['status']!='entregada':continue
        item={'unit_code':unit['code'],'product_id':unit['product_id'],'product':unit['product_name'],'kind':KINDS[unit['kind']],'devices':unit['devices'],'term':unit['term'],
              'expires_at':unit['expires_at'],'activated_at':unit['activated_at'],'edition':unit['edition'],'license_type':unit['license_type'],'manufacturer':unit['manufacturer'],'version':unit['version'],
              'has_logo':bool(c.execute('SELECT 1 FROM catalog_images WHERE item_id=?',(unit['product_id'],)).fetchone())}
        # Vigencia real (desde las fechas guardadas: editar no reinicia el periodo), método de activación y nombres de los campos.
        state,days=state_of(unit,today,soon=soon)
        period=None
        if unit['activated_at'] and unit['expires_at']:
            try:period=max(1,(date.fromisoformat(unit['expires_at'])-date.fromisoformat(unit['activated_at'][:10])).days)
            except ValueError:period=None
        method,fields=method_of(unit,_product(c,unit['product_id']).get('activation_method') or '')
        item.update(unit_id=unit['id'],state=state,state_label=STATES[state][0],days_left=days,period_days=period,method=method,method_label=METHODS.get(method,''),fields=fields)
        if private:item.update(credentials=credentials(unit,c),download_url=unit['download_url'],instructions=unit['instructions'],file=file_of(c,unit['id']))
        items.append(item)
    return {'delivery_id':delivery_id,'client':client['name'] if client else '','order':order['code'] if order else '','delivered_at':delivery['authorized_at'],'status':delivery['status'],
            'items':items,'contact':CONTACT,'private':private}


# ---- Consultas para la interfaz ---------------------------------------------------------------------------------------
def units(c,now,product_id=None,status='',query='',state='',date_from='',date_to='',client_id=None,field=''):
    today=now.date();soon=display_settings(c)['soon_days']
    sql=("SELECT u.id,u.code,u.product_id,i.name product,i.brand,u.kind,u.edition,u.license_type,u.manufacturer,u.version,u.devices,u.term,u.purchased_at,u.activated_at,u.expires_at,u.activated,u.notes,"
         "u.download_url,u.instructions,u.status,u.reserved_at,u.delivered_at,u.created_at,u.renewed_from,u.renewed_to,u.seat,u.batch_id,"
         "q.code quote_code,COALESCE(o.code,'') order_code,u.order_id,u.client_id,COALESCE(cl.name,'') client,COALESCE(cl.identification,'') client_identification,b.supplier batch_supplier,b.invoice,b.unit_cost_cents,"
         "(SELECT 1 FROM license_receipts r WHERE r.batch_id=u.batch_id) has_receipt,p.validity_mode,p.duration,p.duration_months,COALESCE(p.activation_method,'') activation_method,(SELECT 1 FROM license_files f WHERE f.unit_id=u.id) has_file,(SELECT COUNT(*) FROM license_renewals n WHERE n.unit_id=u.id) renewals,"
         "(SELECT s.code FROM license_sales s WHERE s.id=u.sale_id) sale_code,(SELECT s.payment_status FROM license_sales s WHERE s.id=u.sale_id) sale_payment,u.sale_id "
         "FROM license_units u JOIN catalog_items i ON i.id=u.product_id LEFT JOIN license_products p ON p.item_id=u.product_id LEFT JOIN quotes q ON q.id=u.quote_id LEFT JOIN orders o ON o.id=u.order_id "
         "LEFT JOIN clients cl ON cl.id=u.client_id LEFT JOIN license_batches b ON b.id=u.batch_id WHERE 1=1")
    args=[]
    if product_id:sql+=' AND u.product_id=?';args.append(product_id)
    if client_id:sql+=' AND u.client_id=?';args.append(client_id)
    rows=[]
    for r in c.execute(sql+' ORDER BY u.id DESC LIMIT 2000',args):
        row=dict(r);row['state'],row['days_left']=state_of(row,today,soon=soon);row['issues']=issues(row);row['term_days']=term_days(row)
        row['state_label'],row['state_color']=STATES[row['state']];row['status_label']=STATUSES.get(row['status'],row['status']);row['kind_label']=KINDS[row['kind']]
        rows.append(row)
    if status:rows=[r for r in rows if r['status']==status]
    if state=='revision':rows=[r for r in rows if r['issues']]
    elif state:rows=[r for r in rows if r['state']==state]
    if date_from or date_to:
        start=date_from or '0000-01-01';end=date_to or '9999-12-31';keys=[DATE_FIELDS[field]] if field in DATE_FIELDS else ['purchased_at','delivered_at','activated_at','expires_at']
        rows=[r for r in rows if any(start<=(r[k] or '')[:10]<=end for k in keys if r[k])]
    words=[w for w in re.sub(r'\s+',' ',str(query or '').lower()).split(' ') if w]
    if words:
        # Buscar por la clave o la cuenta compara su huella: encuentra la licencia sin mostrar ni guardar la credencial en claro.
        marks=set()
        try:
            for seat in range(1,11):marks|={fingerprint('otro',{'key':query},seat),fingerprint('m365',{'username':query},seat)}
        except LicenseError:marks=set()
        exact={r['id'] for r in c.execute('SELECT id FROM license_units WHERE fingerprint IN (%s)'%','.join('?'*len(marks)),list(marks))} if marks else set()
        rows=[r for r in rows if r['id'] in exact or all(w in ' '.join(str(r[k] or '') for k in ('code','product','brand','edition','license_type','manufacturer','client','client_identification','order_code','quote_code','batch_supplier','invoice','sale_code')).lower() for w in words)]
    return rows


DATE_FIELDS={'compra':'purchased_at','registro':'created_at','entrega':'delivered_at','activacion':'activated_at','vencimiento':'expires_at'}


def issues(row):
    """Datos que no cuadran entre sí, para revisión administrativa. Solo se señalan: nunca se corrigen automáticamente."""
    out=[]
    if row['status'] in ('disponible','vencida') and (row['activated_at'] or row['activated']):out.append('Figura con activación estando en inventario (sin vender).')
    elif row['activated_at'] and not row['activated']:out.append('Tiene fecha de activación sin activación confirmada.')
    if row['activated'] and not row['activated_at']:out.append('Marcada como activada sin fecha de activación.')
    if row['expires_at'] and row['activated_at'] and row['expires_at']<row['activated_at']:out.append('El vencimiento es anterior a la activación.')
    if row['status']=='entregada' and not row['delivered_at']:out.append('Entregada sin fecha de entrega.')
    return out


def term_days(row):
    """Días que dura el período de esta licencia según la duración de SU producto (mensual, anual, bianual…), sin suponer 365."""
    if not row.get('expires_at'):return None
    months=row.get('duration_months') if row.get('duration')=='personalizada' else MONTHS.get(row.get('duration') or '')
    end=date.fromisoformat(row['expires_at'])
    if months:return max(1,(end-add_months(end,-months)).days)
    start=row.get('activated_at') or row.get('purchased_at')
    return max(1,(end-date.fromisoformat(start[:10])).days) if start else None


def export_csv(rows):
    """Exportación ordinaria del inventario: sin claves, seriales, usuarios ni contraseñas."""
    import csv,io
    out=io.StringIO();writer=csv.writer(out)
    safe=lambda value:("'"+value) if isinstance(value,str) and value[:1] in ('=','+','-','@','\t','\r') else value
    writer.writerow(['Código','Producto','Fabricante','Cliente','Estado','Compra','Registro','Entrega','Activación','Vencimiento','Días restantes','Orden','Venta','Proveedor','Factura','Revisión'])
    for r in rows:
        writer.writerow([safe(v) for v in (r['code'],r['product'],r['manufacturer'] or r['brand'] or '',r['client'],r['state_label'],r['purchased_at'],(r['created_at'] or '')[:10],(r['delivered_at'] or '')[:10],r['activated_at'],r['expires_at'],
                         '' if r['days_left'] is None else r['days_left'],r['order_code'],r['sale_code'] or '',r['batch_supplier'] or '',r['invoice'] or '',' '.join(r['issues']))])
    return '\ufeff'+out.getvalue()


def dashboard(c,now):
    """Indicadores del panel: disponibles, reservadas, activas, por vencer, vencidas y renovaciones realizadas."""
    counts={key:0 for key in STATES};soon=display_settings(c)['soon_days'];review=0
    for unit in c.execute('SELECT status,expires_at,activated,activated_at,renewed_to,delivered_at FROM license_units'):
        counts[state_of(dict(unit),now.date(),soon=soon)[0]]+=1;review+=bool(issues(dict(unit)))
    return {'disponibles':counts['disponible'],'reservadas':counts['reservada'],'activas':counts['activa'],'pendientes_activacion':counts['pendiente_activacion'],
            'por_vencer':counts['por_vencer'],'vencidas':counts['vencida'],'renovaciones':c.execute('SELECT COUNT(*) FROM license_renewals').fetchone()[0],'anuladas':counts['anulada'],'revision':review,'soon_days':soon}


def deliveries(c,now):
    out=[]
    orders=[r['order_id'] for r in c.execute("SELECT DISTINCT order_id FROM license_units WHERE order_id IS NOT NULL AND status='reservada' ORDER BY 1 DESC LIMIT 300")]
    orders=list(dict.fromkeys(orders+[r['order_id'] for r in pending_items(c)]))
    import equipment
    logos={r[0] for r in c.execute('SELECT item_id FROM catalog_images')}
    for order_id in orders:
        info=c.execute("SELECT COALESCE(o.code,'') code,cl.name client FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?",(order_id,)).fetchone()
        if not info:continue
        waiting=[u for u in _order_units(c,order_id) if u['status']=='reservada' and not u.get('sale_id')]
        # Reservas agrupadas por presupuesto y producto: cantidad, fecha de la primera reserva y estado.
        groups={}
        for u in waiting:
            g=groups.setdefault((u['quote_id'],u['product_id']),{'quote_id':u['quote_id'],'product_id':u['product_id'],'product':u['product_name'],'quantity':0,'reserved_at':u['reserved_at'],'activated':0,'units':[]})
            g['quantity']+=1;g['activated']+=1 if u['activated'] else 0;g['reserved_at']=min(g['reserved_at'] or u['reserved_at'],u['reserved_at'] or g['reserved_at']);g['units'].append(u['code'])
        quotes={r['id']:r['code'] for r in c.execute('SELECT id,code FROM quotes WHERE order_id=?',(order_id,))}
        client=c.execute('SELECT d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?',(order_id,)).fetchone()
        out.append({'order_id':order_id,'order':info['code'],'client':info['client'],'client_id':client['client_id'] if client else None,'balance_cents':equipment.money(c,order_id)['balance_cents'],
                    'reserved':[{'id':u['id'],'code':u['code'],'product':u['product_name'],'activated':u['activated']} for u in waiting],
                    'groups':[dict(g,quote=quotes.get(g['quote_id'],''),has_logo=g['product_id'] in logos,state='Reservada, pendiente de entrega') for g in groups.values()],
                    'pending':[{'product':r['description'],'missing':r['missing'],'quote':r['quote_code']} for r in pending_items(c,order_id=order_id)]})
    history=[]
    for r in c.execute("SELECT d.*,COALESCE(cl.name,'') client,COALESCE(o.code,'') order_code,COALESCE(u.name,'') by_name FROM license_deliveries d LEFT JOIN clients cl ON cl.id=d.client_id LEFT JOIN orders o ON o.id=d.order_id "
                       "LEFT JOIN users u ON u.id=d.authorized_by ORDER BY d.id DESC LIMIT 300"):
        row=dict(r);units_of=_delivery_units(c,row['id'])
        history.append({'id':row['id'],'kind':row['kind'],'status':row['status'],'client':row['client'],'order':row['order_code'],'by':row['by_name'],'at':row['authorized_at'] or row['payment_confirmed_at'],
                        'balance_cents':row['balance_cents'],'notes':row['notes'],'reveal_count':row['reveal_count'],'price_cents':row['price_cents'],'discount_cents':row['discount_cents'],'payment_status':row['payment_status'],'link_active':row['status']=='autorizada' and row['token_expires_at']>stamp(now),
                        'units':[{'code':u['code'],'product':u['product_name'],'status':u['status']} for u in units_of],
                        'sale_code':(c.execute('SELECT code FROM license_sales WHERE delivery_id=?',(row['id'],)).fetchone() or [''])[0],'client_id':row['client_id'],'order_id':row['order_id'],
                        'products':[dict(g,has_logo=g['product_id'] in logos) for g in _group_units(units_of)]})
    return {'waiting':out,'history':history}


def _group_units(units_of):
    """Licencias de una entrega agrupadas por producto: cantidad entregada, devueltas y sus códigos internos (LIC-…, no son claves)."""
    groups={}
    for u in units_of:
        g=groups.setdefault(u['product_id'],{'product_id':u['product_id'],'product':u['product_name'],'count':0,'delivered':0,'returned':0,'codes':[]})
        g['count']+=1;g['delivered']+=u['status']=='entregada';g['returned']+=u['status']=='anulada';g['codes'].append(u['code'])
    return list(groups.values())


def delivery_events(c,delivery_id):
    """Registro completo de una entrega: sus eventos y los de sus licencias, con fecha, responsable y detalle (sin credenciales)."""
    delivery_row(c,delivery_id)
    return [dict(r) for r in c.execute("SELECT e.created_at,e.event,e.detail,COALESCE(u.name,e.actor) actor,COALESCE(lu.code,'') unit_code FROM license_events e LEFT JOIN users u ON u.id=e.actor_id "
                                       "LEFT JOIN license_units lu ON lu.id=e.unit_id WHERE e.delivery_id=? OR e.unit_id IN (SELECT id FROM license_units WHERE delivery_id=?) ORDER BY e.id",(delivery_id,delivery_id))]


def history(c,limit=300,unit_id=None,product_id=None):
    sql=("SELECT e.id,e.event,e.detail,e.created_at,COALESCE(u.name,e.actor) actor,lu.code unit_code,i.name product,COALESCE(o.code,'') order_code,COALESCE(cl.name,'') client "
         "FROM license_events e LEFT JOIN users u ON u.id=e.actor_id LEFT JOIN license_units lu ON lu.id=e.unit_id LEFT JOIN catalog_items i ON i.id=e.product_id "
         "LEFT JOIN orders o ON o.id=e.order_id LEFT JOIN clients cl ON cl.id=e.client_id")
    args=[]
    if unit_id:sql+=' WHERE e.unit_id=?';args.append(unit_id)
    elif product_id:sql+=' WHERE e.product_id=? OR lu.product_id=?';args+=[product_id,product_id]
    return [dict(r) for r in c.execute(sql+' ORDER BY e.id DESC LIMIT ?',(*args,limit))]


def renewals(c,unit_id):
    return [dict(r) for r in c.execute("SELECT n.*,COALESCE(u.name,'') by_name,nu.code new_code FROM license_renewals n LEFT JOIN users u ON u.id=n.created_by LEFT JOIN license_units nu ON nu.id=n.new_unit_id WHERE n.unit_id=? ORDER BY n.id DESC",(unit_id,))]


def stock(c,now):
    today=now.date().isoformat()
    managed={r['item_id'] for r in c.execute('SELECT item_id FROM license_products')}
    free={r['product_id']:r['n'] for r in c.execute("SELECT product_id,COUNT(*) n FROM license_units WHERE status='disponible' AND (expires_at='' OR expires_at>=?) GROUP BY product_id",(today,))}
    return {item:free.get(item,0) for item in managed}


# ---- Alertas de vencimiento -------------------------------------------------------------------------------------------
def expiring(c,now,limit=200):
    """Licencias vendidas con vencimiento en los próximos 30 días o ya vencidas (sin renovar): para el panel y la campana."""
    today=now.date();out=[];soon=display_settings(c)['soon_days']
    for r in c.execute("SELECT u.id,u.code,u.expires_at,u.status,u.activated,u.renewed_to,i.name product,COALESCE(cl.name,'') client FROM license_units u JOIN catalog_items i ON i.id=u.product_id "
                       "LEFT JOIN clients cl ON cl.id=u.client_id WHERE u.status='entregada' AND u.expires_at!='' AND u.renewed_to IS NULL ORDER BY u.expires_at LIMIT ?",(limit,)):
        days=(date.fromisoformat(r['expires_at'])-today).days
        if days<=soon:out.append(dict(r,days_left=days))
    return out


def tick(c,now):
    """Avisos de 30, 15, 7 y 1 días antes y del día del vencimiento: uno por licencia, fecha y anticipación (sin duplicados), con su
    registro en el historial. Las perpetuas y las que aún no tienen vencimiento (sin activar) no generan avisos. Devuelve los nuevos."""
    expire(c,now);new=[]
    for unit in expiring(c,now,limit=2000):
        days=unit['days_left'];threshold=next((t for t in reversed(ALERT_DAYS) if days<=t),None) if days>=0 else 0
        if threshold is None:continue
        if c.execute('INSERT OR IGNORE INTO license_alerts(unit_id,expires_at,days,created_at) VALUES (?,?,?,?)',(unit['id'],unit['expires_at'],threshold,stamp(now))).rowcount:
            text='Vence hoy' if days==0 else 'Vencida el %s'%unit['expires_at'] if days<0 else 'Vence en %d día%s (%s)'%(days,'' if days==1 else 's',unit['expires_at'])
            event(c,'aviso_vencimiento',now,'%s: %s.'%(unit['product'],text),unit['id'],client=None)
            new.append(dict(unit,threshold=threshold,text=text))
    return new
