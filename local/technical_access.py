"""Decisiones expresas de acceso; sin permisos implícitos ni aceptación retroactiva."""
import json
import re

EXPLANATION='El acceso técnico puede comprender el ingreso al sistema operativo y la ejecución de pruebas de funcionamiento. La revisión de archivos personales, cuentas o información privada requiere autorización específica y justificación técnica.'
SCOPES={'operating_system':'Acceso al sistema operativo','signed_in_tests':'Pruebas con sesión iniciada','specific_files':'Acceso a archivos específicos','backup':'Respaldo de información'}


def weak(text):
    """Una descripción útil nombra archivos, datos u operaciones: «sí», «ok» o una sola palabra no bastan."""
    return len(text)<15 or len(text.split())<3


def validate(data):
    errors={};decision=data.get('technical_access')
    if decision not in ('authorized','denied'):errors['technical_access']='Selecciona expresamente si el cliente autoriza o no el acceso técnico.'
    if data.get('access_confirmed') is not True:errors['access_confirmed']='Confirma que esta decisión fue expresada por el cliente.'
    permissions={key:data.get('access_'+key) is True for key in SCOPES}
    for key in SCOPES:
        if data.get('access_'+key) not in (None,True,False):errors['technical_access']='Los permisos deben ser opciones explícitas.'
    detail=str(data.get('access_detail','')).strip()
    if len(detail)>1000:errors['access_detail']='Usa hasta 1000 caracteres.'
    if decision=='denied' and any(permissions.values()):errors['technical_access']='Sin acceso autorizado no pueden habilitarse permisos de acceso.'
    if decision=='authorized' and not any(permissions.values()):errors['technical_access']='Selecciona al menos una operación autorizada.'
    if (permissions['specific_files'] or permissions['backup']) and weak(detail):errors['access_detail']='Describe qué carpetas, archivos o datos se pueden revisar y con qué finalidad, sin incluir claves.'
    destructive=data.get('destructive_action','not_requested')
    if destructive not in ('not_requested','authorized','denied'):errors['destructive_action']='Selecciona una decisión válida para reinstalación o eliminación.'
    destructive_detail=str(data.get('destructive_detail','')).strip()
    if len(destructive_detail)>1000:errors['destructive_detail']='Usa hasta 1000 caracteres.'
    # Operación irreversible: se exige describirla y una confirmación independiente del cliente; cada falta se informa en su propio campo.
    if destructive=='authorized':
        if weak(destructive_detail):errors['destructive_detail']='Describe qué operación se hará y qué información se verá afectada.'
        if data.get('destructive_confirmed') is not True:errors['destructive_confirmed']='Marca la confirmación del cliente para esta operación; sin ella no se puede registrar la autorización.'
    return {'decision':decision,'permissions':permissions,'justification':detail,'destructive':destructive,'destructive_detail':destructive_detail},errors


def record(c,oid,user,now,acceptor,values,key):
    for action,decision,permissions,detail in [('technical',values['decision'],values['permissions'],values['justification']),('destructive',values['destructive'],{'reinstall_or_erase':values['destructive']=='authorized'},values['destructive_detail'])]:
        if decision=='not_requested':continue
        c.execute('INSERT INTO order_access_consents(order_id,action,decision,permissions,justification,acceptor,recorded_at,actor_id,request_key) VALUES (?,?,?,?,?,?,?,?,?)',(oid,action,decision,json.dumps(permissions,sort_keys=True),detail,acceptor,now.isoformat(timespec='microseconds'),user['id'],key))


def attach(c,order):
    rows=[dict(row) for row in c.execute('SELECT a.*,u.name operator FROM order_access_consents a JOIN users u ON u.id=a.actor_id WHERE a.order_id=? ORDER BY a.id',(order['id'],))]
    latest={}
    for row in rows:
        row['permissions']=json.loads(row['permissions']);row.pop('request_key');latest[row['action']]=row
    order['access_authorization']=latest.get('technical')
    order['destructive_authorization']=latest.get('destructive')
    order['access_history']=rows
    order['access_revision']=rows[-1]['id'] if rows else 0
    return order
