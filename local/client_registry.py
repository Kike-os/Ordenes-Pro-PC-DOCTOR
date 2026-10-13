"""Fichas reutilizables; las recepciones conservan su instantánea histórica."""
import re
from reception import LIMITS,validate_order
KEYS=('name','client_type','country','document_type','identification','trade_name','phone','email','province','province_code','canton','canton_code','parish','parish_code','city','locality_code','address','main_street','secondary_street','building_number','location_reference','geo_version')
PERSONAL=set(KEYS)-{'name','client_type','country'}

LABELS={'name':'Nombre o razón social','identification':'Identificación válida','document_type':'Tipo de documento','phone':'Teléfono','email':'Correo electrónico','province':'Provincia','province_code':'Provincia','canton':'Cantón','canton_code':'Cantón',
        'parish':'Parroquia','parish_code':'Parroquia','city':'Ciudad o localidad','locality_code':'Ciudad o localidad','address':'Dirección','main_street':'Dirección','client_type':'Tipo de cliente','country':'País'}
FOLDS=(('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ü','u'),('ñ','n'),('Á','a'),('É','e'),('Í','i'),('Ó','o'),('Ú','u'),('Ü','u'),('Ñ','n'))

def fold(text):
    """Texto para comparar sin tildes ni mayúsculas (la «ñ» se compara como «n»)."""
    out=str(text or '').lower()
    for accented,plain in FOLDS:out=out.replace(accented,plain)
    return ' '.join(out.split())

def fold_sql(expression):
    """La misma normalización dentro de SQLite, cuya función lower() no convierte letras acentuadas."""
    out='lower('+expression+')'
    for accented,plain in FOLDS:out="replace("+out+",'"+accented+"','"+plain+"')"
    return out

def missing(row):
    """Datos obligatorios que le faltan a una ficha para poder registrar órdenes. Los campos opcionales no cuentan."""
    _,errors=validate(dict(row))
    labels=[]
    for key in errors:
        label=LABELS.get(key)
        if label and label not in labels:labels.append(label)
    return labels

def similar(c,fields,own=None):
    """Otras fichas que comparten teléfono o correo. Es solo un aviso: los contactos compartidos (familias, empresas) son válidos."""
    out=[]
    for column,value,label in (('phone',fields.get('phone'),'teléfono'),('email',fields.get('email'),'correo')):
        if not value:continue
        for row in c.execute('SELECT id,name FROM clients WHERE '+('lower(email)=lower(?)' if column=='email' else 'phone=?')+' AND id!=? ORDER BY id LIMIT 3',(value,own or -1)):
            out.append({'id':row['id'],'name':row['name'],'match':label})
    return out

def profile(row):
    data=dict(row);data['client']=data['name'];return data

def validate(data):
    values=dict(data,client=data.get('name',data.get('client','')),type='portatil',physical_condition='Ficha de cliente',problem='Ficha de cliente')
    fields,errors=validate_order(values)
    errors={k:v for k,v in errors.items() if k in PERSONAL or k=='client'}
    if 'client' in errors:errors['name']=errors.pop('client')
    fields['name']=fields.pop('client');fields['client_type']=str(data.get('client_type','natural'));fields['country']=str(data.get('country','Ecuador'))
    if fields['client_type'] not in ('natural','empresa'):errors['client_type']='Selecciona persona natural o empresa.'
    if fields['client_type']=='empresa' and fields['document_type']!='ruc':errors['document_type']='Para una empresa selecciona RUC.'
    if fields['country']!='Ecuador':errors['country']='Selecciona Ecuador para el catálogo territorial disponible.'
    return {k:fields[k] for k in KEYS},errors

def save(c,data,user):
    fields,errors=validate(data)
    if errors:return 400,{'error':'Revisa la información del cliente.','fields':errors}
    oid=str(data.get('id',''))
    extra={'phone_secondary':str(data.get('phone_secondary','')).strip(),'notes':str(data.get('notes','')).strip()}
    if len(extra['phone_secondary'])>30:return 400,{'error':'Revisa la información del cliente.','fields':{'phone_secondary':'Usa hasta 30 caracteres.'}}
    if len(extra['notes'])>2000:return 400,{'error':'Revisa la información del cliente.','fields':{'notes':'Usa hasta 2000 caracteres.'}}
    # Técnicos pueden completar una ficha importada pendiente de revisión; el resto de ediciones es de administración.
    if oid and user['role']!='administrador' and not c.execute('SELECT 1 FROM clients WHERE id=? AND needs_review=1',(oid,)).fetchone():return 403,{'error':'Solo administración puede editar fichas.'}
    duplicate=c.execute('SELECT id,name FROM clients WHERE identification=? AND id!=? ORDER BY id LIMIT 1',(fields['identification'],oid or -1)).fetchone()
    if duplicate:return 409,{'error':'Ya existe un cliente con esta identificación. Selecciona su ficha.','existing_id':duplicate['id'],'fields':{'identification':'Esta identificación ya está registrada.'}}
    key=fields['document_type']+':'+fields['identification']
    if oid:
        if not c.execute('SELECT 1 FROM clients WHERE id=?',(oid,)).fetchone():return 404,{'error':'Cliente no disponible.'}
        c.execute('UPDATE clients SET '+','.join(k+'=?' for k in KEYS)+',identity_key=?,phone_secondary=?,notes=?,needs_review=0 WHERE id=?',(*(fields[k] for k in KEYS),key,extra['phone_secondary'],extra['notes'],oid))
    else:
        oid=c.execute('INSERT INTO clients('+','.join(KEYS)+',identity_key,phone_secondary,notes) VALUES ('+','.join('?' for _ in range(len(KEYS)+3))+')',(*(fields[k] for k in KEYS),key,extra['phone_secondary'],extra['notes'])).lastrowid
    return 200 if data.get('id') else 201,{'ok':True,'id':int(oid),'similar':similar(c,fields,int(oid))}
