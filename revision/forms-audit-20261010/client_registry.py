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
    if oid and user['role']!='administrador':return 403,{'error':'Solo administración puede editar fichas.'}
    duplicate=c.execute('SELECT id,name FROM clients WHERE identification=? AND id!=? ORDER BY id LIMIT 1',(fields['identification'],oid or -1)).fetchone()
    if duplicate:return 409,{'error':'Ya existe un cliente con esta identificación. Selecciona su ficha.','existing_id':duplicate['id'],'fields':{'identification':'Esta identificación ya está registrada.'}}
    key=fields['document_type']+':'+fields['identification']
    if oid:
        if not c.execute('SELECT 1 FROM clients WHERE id=?',(oid,)).fetchone():return 404,{'error':'Cliente no disponible.'}
        c.execute('UPDATE clients SET '+','.join(k+'=?' for k in KEYS)+',identity_key=? WHERE id=?',(*(fields[k] for k in KEYS),key,oid))
    else:
        oid=c.execute('INSERT INTO clients('+','.join(KEYS)+',identity_key) VALUES ('+','.join('?' for _ in range(len(KEYS)+1))+')',(*(fields[k] for k in KEYS),key)).lastrowid
    return 200 if data.get('id') else 201,{'ok':True,'id':int(oid)}
