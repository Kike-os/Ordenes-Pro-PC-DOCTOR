from reception import valid_ecuador_phone
"""Reglas transaccionales de reservas, disponibilidad y atención asistida."""
from datetime import date,datetime,time,timedelta
from zoneinfo import ZoneInfo
import hashlib,secrets,re
import reception
TZ=ZoneInfo('America/Guayaquil')
STATUSES={'solicitada':'Pendiente de confirmación','confirmada':'Confirmada','reprogramada':'Reprogramada','cancelada':'Cancelada','presente':'En atención','completada':'Completada','no_asistio':'No asistió'}
# Las reservas en línea verifican la disponibilidad en el servidor. «auto» las deja confirmadas al instante (comportamiento
# original); «manual» las deja pendientes hasta que el taller las confirme. Se guarda en system_state.
def confirmation_mode(c):
 row=c.execute("SELECT value FROM system_state WHERE key='appointments_confirmation'").fetchone()
 return 'manual' if row and row['value']=='manual' else 'auto'

def now():return datetime.now(TZ)
def stamp(value):return value.astimezone(TZ).isoformat(timespec='seconds')
def token_hash(value):return hashlib.sha256(value.encode()).hexdigest()
def services(c):return [dict(r) for r in c.execute('SELECT code,label,duration_minutes FROM appointment_services WHERE active=1 ORDER BY label')]
def ensure_staff_hours(c,technician_id):
 for weekday in range(7):
  end='13:00' if weekday==5 else '17:00';enabled=0 if weekday==6 else 1
  c.execute('INSERT OR IGNORE INTO appointment_staff_hours(technician_id,weekday,start_time,end_time,enabled) VALUES (?,?,?,?,?)',(technician_id,weekday,'09:00',end,enabled))
def settings(c):return {'confirmation':confirmation_mode(c),'hours':[dict(r) for r in c.execute('SELECT * FROM appointment_hours ORDER BY weekday')],'staff_hours':[dict(r) for r in c.execute('SELECT h.*,u.name technician FROM appointment_staff_hours h JOIN users u ON u.id=h.technician_id ORDER BY u.name,h.weekday')],'holidays':[dict(r) for r in c.execute('SELECT * FROM appointment_holidays ORDER BY day')],'services':[dict(r) for r in c.execute('SELECT code,label,duration_minutes,active FROM appointment_services ORDER BY label')]}
def update_settings(c,data):
 try:
  for item in data.get('hours',[]):
   weekday=int(item['weekday']);start=time.fromisoformat(str(item['start_time']));end=time.fromisoformat(str(item['end_time']));enabled=1 if item.get('enabled') else 0
   if weekday not in range(7) or start>=end:return 400,{'error':'Revisa los días y horarios de atención.'}
   c.execute('UPDATE appointment_hours SET start_time=?,end_time=?,enabled=? WHERE weekday=?',(start.strftime('%H:%M'),end.strftime('%H:%M'),enabled,weekday))
  for item in data.get('staff_hours',[]):
   technician=int(item['technician_id']);weekday=int(item['weekday']);start=time.fromisoformat(str(item['start_time']));end=time.fromisoformat(str(item['end_time']));enabled=1 if item.get('enabled') else 0
   if weekday not in range(7) or start>=end or not c.execute("SELECT 1 FROM users WHERE id=? AND active=1 AND role IN ('administrador','tecnico')",(technician,)).fetchone():return 400,{'error':'Horario de técnico inválido.'}
   c.execute('INSERT INTO appointment_staff_hours(technician_id,weekday,start_time,end_time,enabled) VALUES (?,?,?,?,?) ON CONFLICT(technician_id,weekday) DO UPDATE SET start_time=excluded.start_time,end_time=excluded.end_time,enabled=excluded.enabled',(technician,weekday,start.strftime('%H:%M'),end.strftime('%H:%M'),enabled))
  for item in data.get('services',[]):
   code=str(item.get('code',''));duration=int(item.get('duration_minutes',0));active=1 if item.get('active') else 0
   if not c.execute('SELECT 1 FROM appointment_services WHERE code=?',(code,)).fetchone() or duration not in range(15,241,15):return 400,{'error':'Duración de servicio inválida; usa intervalos de 15 minutos.'}
   c.execute('UPDATE appointment_services SET duration_minutes=?,active=? WHERE code=?',(duration,active,code))
  if data.get('confirmation') in ('auto','manual'):
   c.execute("INSERT INTO system_state(key,value) VALUES ('appointments_confirmation',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(data['confirmation'],))
  # Servicios administrables: renombrar los existentes y añadir nuevos (código interno generado).
  for item in data.get('services',[]):
   label=str(item.get('label','')).strip()
   if label and 3<=len(label)<=80:c.execute('UPDATE appointment_services SET label=? WHERE code=?',(label,str(item.get('code',''))))
  created=data.get('new_service')
  if created:
   label=str(created.get('label','')).strip();duration=int(created.get('duration_minutes',0))
   if not 3<=len(label)<=80 or duration not in range(15,241,15):return 400,{'error':'El servicio necesita un nombre de 3 a 80 caracteres y una duración en intervalos de 15 minutos.'}
   if c.execute('SELECT 1 FROM appointment_services WHERE lower(label)=lower(?)',(label,)).fetchone():return 400,{'error':'Ya existe un servicio con ese nombre.'}
   c.execute('INSERT INTO appointment_services(code,label,duration_minutes,active) VALUES (?,?,?,1)',('svc_'+secrets.token_hex(4),label,duration))
  holiday=data.get('holiday')
  if holiday:
   day=date.fromisoformat(str(holiday.get('day','')));label=str(holiday.get('label','')).strip()[:100]
   if not label:return 400,{'error':'Escribe el motivo del día no laborable.'}
   c.execute('INSERT INTO appointment_holidays(day,label) VALUES (?,?) ON CONFLICT(day) DO UPDATE SET label=excluded.label',(day.isoformat(),label))
  if data.get('remove_holiday'):
   c.execute('DELETE FROM appointment_holidays WHERE day=?',(str(data['remove_holiday']),))
 except (ValueError,TypeError,KeyError):return 400,{'error':'La configuración de la agenda contiene datos inválidos.'}
 return 200,{'ok':True,'settings':settings(c)}
def parse_start(raw):
 try:
  value=datetime.fromisoformat(str(raw))
  if value.tzinfo is None:value=value.replace(tzinfo=TZ)
  value=value.astimezone(TZ)
  if value.second or value.microsecond or value.minute%30:raise ValueError()
  if value<=now()+timedelta(minutes=10) or value>now()+timedelta(days=90):raise ValueError()
  return value
 except (ValueError,TypeError):raise ValueError('Selecciona una fecha futura disponible en intervalos de 30 minutos.')
def slot_open(c,start,duration):
 if start.tzinfo is None:start=start.replace(tzinfo=TZ)
 local=start.astimezone(TZ);day=local.date()
 hours=c.execute('SELECT * FROM appointment_hours WHERE weekday=?',(day.weekday(),)).fetchone()
 if not hours or not hours['enabled'] or c.execute('SELECT 1 FROM appointment_holidays WHERE day=?',(day.isoformat(),)).fetchone():return False
 begin=time.fromisoformat(hours['start_time']);end=time.fromisoformat(hours['end_time']);clock=local.timetz().replace(tzinfo=None)
 if clock<begin or (datetime.combine(day,clock)+timedelta(minutes=duration)).time()>end or clock.minute%30:return False
 return True
def technicians(c,start,duration,exclude=None):
 start_s=stamp(start);end_s=stamp(start+timedelta(minutes=duration))
 staff=[dict(r) for r in c.execute("SELECT id,name FROM users WHERE active=1 AND role IN ('administrador','tecnico') ORDER BY id")]
 if not staff:return [None] if slot_open(c,start,duration) else []
 available=[]
 for person in staff:
  staff_hours=c.execute('SELECT * FROM appointment_staff_hours WHERE technician_id=? AND weekday=?',(person['id'],start.astimezone(TZ).weekday())).fetchone()
  if staff_hours:
   staff_time=start.astimezone(TZ).timetz().replace(tzinfo=None)
   if not staff_hours['enabled'] or staff_time<time.fromisoformat(staff_hours['start_time']) or (datetime.combine(start.astimezone(TZ).date(),staff_time)+timedelta(minutes=duration)).time()>time.fromisoformat(staff_hours['end_time']):continue
  args=[person['id'],end_s,start_s]
  ignore=' AND id!=?' if exclude else ''
  if exclude:args.append(exclude)
  clash=c.execute("SELECT 1 FROM appointments WHERE deleted_at IS NULL AND technician_id=? AND status NOT IN ('cancelada','completada','no_asistio') AND datetime(starts_at)<datetime(?) AND datetime(starts_at,'+'||duration_minutes||' minutes')>datetime(?)"+ignore,args).fetchone()
  if not clash and slot_open(c,start,duration):available.append(person['id'])
 return available
def available_slots(c,day_text,service_code,staff=False):
 # La reserva pública empieza mañana; el personal también puede registrar citas para hoy en los horarios que aún no pasan.
 try:day=date.fromisoformat(day_text)
 except (ValueError,TypeError):raise ValueError('Fecha no válida.')
 first=now().date() if staff else now().date()+timedelta(days=1)
 if day.isoformat()!=day_text or not first<=day<=now().date()+timedelta(days=90):raise ValueError('Elige una fecha entre hoy y los próximos 90 días.' if staff else 'Elige una fecha entre mañana y los próximos 90 días.')
 service=c.execute('SELECT * FROM appointment_services WHERE code=? AND active=1',(service_code,)).fetchone()
 if not service:raise ValueError('Selecciona un servicio disponible.')
 hours=c.execute('SELECT * FROM appointment_hours WHERE weekday=?',(day.weekday(),)).fetchone()
 if not hours or not hours['enabled'] or c.execute('SELECT 1 FROM appointment_holidays WHERE day=?',(day.isoformat(),)).fetchone():return []
 cursor=datetime.combine(day,time.fromisoformat(hours['start_time']),TZ);finish=datetime.combine(day,time.fromisoformat(hours['end_time']),TZ);out=[]
 while cursor+timedelta(minutes=service['duration_minutes'])<=finish:
  free=technicians(c,cursor,service['duration_minutes']) if cursor>now()+timedelta(minutes=10) else []
  if free:out.append({'time':cursor.strftime('%H:%M'),'technician_id':free[0]})
  cursor+=timedelta(minutes=30)
 return out
def validate_booking(data,c):
 fields={k:str(data.get(k,'')).strip() for k in ['name','identification','phone','email','device_type','brand','model','service','description','date','time','notes']};errors={}
 if len(fields['name'])<2 or len(fields['name'])>150:errors['name']='Indica el nombre completo (2 a 150 caracteres).'
 if not valid_ecuador_phone(fields['phone']):errors['phone']='Ingresa un número de teléfono válido.'
 if fields['email'] and (len(fields['email'])>254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+',fields['email'])):errors['email']='Ingresa un correo electrónico válido.'
 if fields['identification']:
  err=reception.document_error(fields['identification'])
  if err:errors['identification']=err
  elif len(fields['identification']) not in (10,13):errors['identification']='Usa una cédula de 10 o un RUC de 13 dígitos.'
 if fields['device_type'] not in reception.DEVICE_TYPES:errors['device_type']='Selecciona el tipo de equipo.'
 if not fields['service'] or not c.execute('SELECT 1 FROM appointment_services WHERE code=? AND active=1',(fields['service'],)).fetchone():errors['service']='Selecciona un servicio.'
 if len(fields['description'])<3 or len(fields['description'])>1000:errors['description']='Describe brevemente la falla (3 a 1000 caracteres).'
 if len(fields['brand'])>100 or len(fields['model'])>100 or len(fields['notes'])>1000:errors['notes']='Revisa la longitud de marca, modelo u observaciones.'
 if data.get('privacy_consent') is not True:errors['privacy_consent']='Confirma el aviso de privacidad para registrar la cita.'
 if data.get('communications_consent') not in (True,False):errors['communications_consent']='Selecciona si autorizas comunicaciones de la cita.'
 try:
  start=parse_start(fields['date']+'T'+fields['time']+':00-05:00');service=c.execute('SELECT duration_minutes FROM appointment_services WHERE code=?',(fields['service'],)).fetchone()
  if service and not slot_open(c,start,service['duration_minutes']):errors['time']='Ese horario no está disponible. Consulta otros espacios.'
 except ValueError as error:errors['time']=str(error);start=None
 return fields,errors,start
def lookup_client(c,identification,phone,email):
 if identification:
  row=c.execute('SELECT * FROM clients WHERE identification=? ORDER BY id LIMIT 1',(identification,)).fetchone()
  if row:return row
 if phone:
  row=c.execute('SELECT * FROM clients WHERE phone=? ORDER BY id LIMIT 1',(phone,)).fetchone()
  if row:return row
 if email:
  row=c.execute('SELECT * FROM clients WHERE lower(email)=lower(?) ORDER BY id LIMIT 1',(email,)).fetchone()
  if row:return row
 return None
def create(c,data,user=None):
 key=str(data.get('request_key','')).strip()
 if key and c.execute('SELECT 1 FROM appointments WHERE deleted_at IS NULL AND request_key=?',(key,)).fetchone():return 409,{'error':'Esta solicitud ya fue registrada.'}
 fields,errors,start=validate_booking(data,c)
 if errors:return 400,{'error':'Revisa los datos de la cita.','fields':errors}
 duration=c.execute('SELECT duration_minutes FROM appointment_services WHERE code=?',(fields['service'],)).fetchone()['duration_minutes']
 staff=technicians(c,start,duration)
 if not staff:return 409,{'error':'Ese espacio acaba de ocuparse. Elige otro horario.'}
 technician=staff[0];chosen=str(data.get('client_id','')) if user else ''
 client=c.execute('SELECT * FROM clients WHERE id=?',(int(chosen),)).fetchone() if chosen.isdigit() else None
 if chosen and not client:return 404,{'error':'El cliente seleccionado ya no está disponible.'}
 if not client:client=lookup_client(c,fields['identification'],fields['phone'],fields['email'])
 if not client:client_id=c.execute('INSERT INTO clients(name,email,phone,identification) VALUES (?,?,?,?)',(fields['name'],fields['email'],fields['phone'],fields['identification'])).lastrowid
 else:client_id=client['id']
 token=secrets.token_urlsafe(32);created=stamp(now());public='CIT-'+now().strftime('%Y%m%d')+'-'+secrets.token_hex(3).upper()
 initial='confirmada' if user or confirmation_mode(c)=='auto' else 'solicitada'
 cursor=c.execute("INSERT INTO appointments(public_code,manage_token_hash,client_id,technician_id,customer_name,identification,phone,email,device_type,brand,model,service_code,description,notes,starts_at,duration_minutes,status,privacy_consent,communications_consent,created_at,updated_at,request_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)",(public,token_hash(token),client_id,technician,fields['name'],fields['identification'],fields['phone'],fields['email'],fields['device_type'],fields['brand'],fields['model'],fields['service'],fields['description'],fields['notes'],stamp(start),duration,initial,int(data.get('communications_consent') is True),created,created,key or None))
 aid=cursor.lastrowid;c.execute("INSERT INTO appointment_events(appointment_id,actor_id,event,new_start,new_status,created_at) VALUES (?,?,?,?,?,?)",(aid,user['id'] if user else None,'created',stamp(start),initial,created))
 if initial=='confirmada' and fields['email'] and data.get('communications_consent') is True:c.execute("INSERT OR IGNORE INTO appointment_notifications(appointment_id,generation,event,channel,result,created_at) VALUES (?,1,'confirmation','email','pending',?)",(aid,created))
 return 201,{'id':aid,'code':public,'manage_token':token,'starts_at':stamp(start),'status':initial,'duration_minutes':duration}
def reschedule(c,row,start,user):
 duration=row['duration_minutes'];staff=technicians(c,start,duration,exclude=row['id'])
 if not staff:return 409,{'error':'Ese espacio no está disponible.'}
 old=row['starts_at'];oldstatus=row['status'];created=stamp(now());generation=row['generation']+1
 c.execute("UPDATE appointments SET starts_at=?,technician_id=?,status='reprogramada',generation=?,updated_at=? WHERE id=?",(stamp(start),staff[0],generation,created,row['id']))
 c.execute('INSERT INTO appointment_events(appointment_id,actor_id,event,old_start,new_start,old_status,new_status,created_at) VALUES (?,?,?,?,?,?,?,?)',(row['id'],user['id'] if user else None,'rescheduled',old,stamp(start),oldstatus,'reprogramada',created))
 if row['email'] and row['communications_consent']:c.execute("INSERT OR IGNORE INTO appointment_notifications(appointment_id,generation,event,channel,result,created_at) VALUES (?,?,'rescheduled','email','pending',?)",(row['id'],generation,created))
 return {'ok':True,'starts_at':stamp(start)}
EDITABLE=('name','phone','email','device_type','brand','model','description','notes')
def edit(c,row,data,user):
 """Corrige los datos de contacto, equipo y descripción de una cita; fecha y estado se cambian con sus propias acciones."""
 fields={k:str(data.get(k,'')).strip() for k in EDITABLE};errors={}
 if len(fields['name'])<2 or len(fields['name'])>150:errors['name']='Indica el nombre completo (2 a 150 caracteres).'
 if not valid_ecuador_phone(fields['phone']):errors['phone']='Ingresa un número de teléfono válido.'
 if fields['email'] and (len(fields['email'])>254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+',fields['email'])):errors['email']='Ingresa un correo electrónico válido.'
 if fields['device_type'] not in reception.DEVICE_TYPES:errors['device_type']='Selecciona el tipo de equipo.'
 if len(fields['description'])<3 or len(fields['description'])>1000:errors['description']='Describe brevemente la falla (3 a 1000 caracteres).'
 if len(fields['brand'])>100 or len(fields['model'])>100 or len(fields['notes'])>1000:errors['notes']='Revisa la longitud de marca, modelo u observaciones.'
 if errors:return 400,{'error':'Revisa los datos de la cita.','fields':errors}
 columns={'name':'customer_name'};changed=[k for k in EDITABLE if fields[k]!=(row[columns.get(k,k)] or '')]
 if not changed:return 200,{'ok':True,'changed':[]}
 created=stamp(now());c.execute('UPDATE appointments SET customer_name=?,phone=?,email=?,device_type=?,brand=?,model=?,description=?,notes=?,updated_at=? WHERE id=?',(*(fields[k] for k in EDITABLE),created,row['id']))
 labels={'name':'nombre','phone':'teléfono','email':'correo','device_type':'tipo de equipo','brand':'marca','model':'modelo','description':'descripción','notes':'observaciones'}
 c.execute("INSERT INTO appointment_events(appointment_id,actor_id,event,old_start,new_start,old_status,new_status,created_at,detail) VALUES (?,?,'edited',?,?,?,?,?,?)",(row['id'],user['id'],row['starts_at'],row['starts_at'],row['status'],row['status'],created,'Datos modificados: '+', '.join(labels[k] for k in changed)))
 return 200,{'ok':True,'changed':changed}
def remove(c,row,user,reason):
 """Eliminación lógica: la cita sale de la agenda activa y libera su horario; la fila, su historial y la orden o el mantenimiento de origen se conservan."""
 created=stamp(now());reason=str(reason or '').strip()[:300]
 c.execute('UPDATE appointments SET deleted_at=?,deleted_by=?,delete_reason=?,updated_at=? WHERE id=? AND deleted_at IS NULL',(created,user['id'],reason,created,row['id']))
 c.execute("INSERT INTO appointment_events(appointment_id,actor_id,event,old_start,new_start,old_status,new_status,created_at,detail) VALUES (?,?,'deleted',?,?,?,?,?,?)",(row['id'],user['id'],row['starts_at'],row['starts_at'],row['status'],row['status'],created,reason))
 # Si era la cita de un mantenimiento, la previsión queda «programado» y marcada para que no se regenere sola.
 linked=c.execute('SELECT id FROM maintenance WHERE appointment_id=?',(row['id'],)).fetchone()
 if linked:c.execute("UPDATE maintenance SET appointment_id=NULL,state=CASE WHEN state='appointment' THEN 'scheduled' ELSE state END,auto_appointment_blocked=1,updated_at=? WHERE id=?",(now().isoformat(),linked['id']))
 return {'ok':True,'maintenance_id':linked['id'] if linked else None}
def create_for_maintenance(c,mid,user=None):
 """Cita automática del mantenimiento preventivo: se propone para la fecha prevista (o el primer día laborable con horario libre) y queda pendiente de confirmación.
 No duplica: si la previsión ya tiene una cita activa devuelve esa. Sin teléfono del cliente o sin horarios en 45 días no se crea."""
 row=c.execute("SELECT m.*,o.code,cl.id client_id,cl.name client,cl.phone,cl.email,cl.identification,COALESCE(NULLIF(d.kind,''),d.category) kind,d.brand,d.model FROM maintenance m JOIN orders o ON o.id=m.order_id JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE m.id=?",(mid,)).fetchone()
 if not row or row['state'] not in ('scheduled','appointment') or row['auto_appointment_blocked']:return None
 if row['appointment_id']:
  current=c.execute("SELECT id,public_code,starts_at,status FROM appointments WHERE deleted_at IS NULL AND id=? AND status NOT IN ('cancelada','no_asistio','completada')",(row['appointment_id'],)).fetchone()
  if current:return dict(current)
 phone=re.sub(r'\s+','',row['phone'] or '')
 if not 7<=len(phone)<=30 or len(row['client'] or '')<2:return None
 service=c.execute("SELECT * FROM appointment_services WHERE code='mantenimiento'").fetchone()
 if not service:return None
 day=max(date.fromisoformat(row['due_date']),now().date()+timedelta(days=1));start=technician=None
 for _ in range(45):
  hours=c.execute('SELECT * FROM appointment_hours WHERE weekday=?',(day.weekday(),)).fetchone()
  if hours and hours['enabled'] and not c.execute('SELECT 1 FROM appointment_holidays WHERE day=?',(day.isoformat(),)).fetchone():
   cursor=datetime.combine(day,time.fromisoformat(hours['start_time']),TZ);finish=datetime.combine(day,time.fromisoformat(hours['end_time']),TZ)
   while cursor+timedelta(minutes=service['duration_minutes'])<=finish and start is None:
    free=technicians(c,cursor,service['duration_minutes'])
    if free:start=cursor;technician=free[0]
    cursor+=timedelta(minutes=30)
  if start:break
  day+=timedelta(days=1)
 if not start:return None
 created=stamp(now());public='CIT-'+now().strftime('%Y%m%d')+'-'+secrets.token_hex(3).upper();kind=row['kind'] if row['kind'] in reception.DEVICE_TYPES else 'otro'
 aid=c.execute("INSERT INTO appointments(public_code,manage_token_hash,client_id,technician_id,customer_name,identification,phone,email,device_type,brand,model,service_code,description,notes,starts_at,duration_minutes,status,privacy_consent,communications_consent,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'solicitada',1,0,?,?)",(public,token_hash(secrets.token_urlsafe(32)),row['client_id'],technician,row['client'],row['identification'] or '',phone,row['email'] or '',kind,row['brand'] or '',row['model'] or '','mantenimiento','Mantenimiento preventivo programado automáticamente tras la entrega de la orden '+row['code']+'.','Cita generada por el sistema. Fecha y hora propuestas: confirmar con el cliente.',stamp(start),service['duration_minutes'],created,created)).lastrowid
 c.execute("INSERT INTO appointment_events(appointment_id,actor_id,event,new_start,new_status,created_at,detail) VALUES (?,?,?,?,?,?,?)",(aid,user['id'] if user else None,'created',stamp(start),'solicitada',created,'Generada automáticamente al entregar la orden '+row['code']))
 c.execute("UPDATE maintenance SET appointment_id=?,state='appointment',updated_at=? WHERE id=?",(aid,now().isoformat(),mid))
 return {'id':aid,'public_code':public,'starts_at':stamp(start),'status':'solicitada'}
def admin_rows(c,start,end):
 return [dict(r) for r in c.execute("SELECT a.*,s.label service_label,u.name technician FROM appointments a JOIN appointment_services s ON s.code=a.service_code LEFT JOIN users u ON u.id=a.technician_id WHERE a.deleted_at IS NULL AND a.starts_at>=? AND a.starts_at<? ORDER BY a.starts_at,a.id",(start,end))]

def queue_notice(c,row,event,generation=None):
 """Encola un correo al cliente (confirmación o cancelación) solo si dejó correo y autorizó comunicaciones."""
 if row['email'] and row['communications_consent']:c.execute("INSERT OR IGNORE INTO appointment_notifications(appointment_id,generation,event,channel,result,created_at) VALUES (?,?,?,'email','pending',?)",(row['id'],generation or row['generation'],event,stamp(now())))
def detail(c,aid):
 """Cita con su servicio, técnico, cliente vinculado e historial de modificaciones."""
 row=c.execute("SELECT a.*,s.label service_label,u.name technician FROM appointments a JOIN appointment_services s ON s.code=a.service_code LEFT JOIN users u ON u.id=a.technician_id WHERE a.id=? AND a.deleted_at IS NULL",(aid,)).fetchone()
 if not row:return None
 data=dict(row);data.pop('manage_token_hash',None);data.pop('request_key',None)
 data['events']=[dict(r) for r in c.execute("SELECT e.id,e.event,e.old_start,e.new_start,e.old_status,e.new_status,e.created_at,e.detail,u.name actor FROM appointment_events e LEFT JOIN users u ON u.id=e.actor_id WHERE e.appointment_id=? ORDER BY e.id DESC",(aid,))]
 data['notices']=[dict(r) for r in c.execute("SELECT event,channel,result,created_at,completed_at FROM appointment_notifications WHERE appointment_id=? ORDER BY id DESC",(aid,))]
 order=c.execute('SELECT id,code FROM orders WHERE id=?',(row['converted_order_id'],)).fetchone() if row['converted_order_id'] else None
 data['order']=dict(order) if order else None
 source=c.execute('SELECT m.id,m.due_date,o.id order_id,o.code FROM maintenance m JOIN orders o ON o.id=m.order_id WHERE m.appointment_id=?',(aid,)).fetchone()
 data['maintenance']=dict(source) if source else None
 import appointment_mail
 data['mails']=appointment_mail.history(c,aid)
 return data
def agenda(c,start,end):
 """Fuente única de la Agenda de Mantenimientos de Clientes: citas del período y su resumen."""
 rows=admin_rows(c,start,end)
 for row in rows:row.pop('manage_token_hash',None);row.pop('request_key',None)
 today=now().date();day_start=stamp(datetime.combine(today,time.min,TZ));day_end=stamp(datetime.combine(today+timedelta(days=1),time.min,TZ));current=stamp(now())
 count=lambda sql,*args:c.execute(sql,args).fetchone()[0]
 summary={'today':count("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND starts_at>=? AND starts_at<? AND status NOT IN ('cancelada','no_asistio')",day_start,day_end),
  'pending':count("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND status='solicitada' AND starts_at>=?",current),
  'confirmed':count("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND status IN ('confirmada','reprogramada') AND starts_at>=?",current),
  'attending':count("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND status='presente'")}
 return rows,summary
