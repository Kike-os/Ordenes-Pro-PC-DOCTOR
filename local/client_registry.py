"""Fichas reutilizables; las recepciones conservan su instantánea histórica."""
import re
from reception import LIMITS,validate_order
KEYS=('name','client_type','country','document_type','identification','trade_name','phone','email','province','province_code','canton','canton_code','parish','parish_code','city','locality_code','address','main_street','secondary_street','building_number','location_reference','geo_version')
PERSONAL=set(KEYS)-{'name','client_type','country'}

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
    return 200 if data.get('id') else 201,{'ok':True,'id':int(oid)}
