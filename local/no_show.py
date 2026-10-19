"""Inasistencias y reagendamiento de citas.

1) Detección: una cita confirmada cuya hora pasó, más la tolerancia, sin que el taller registrara la llegada del cliente, pasa a
   «No asistió». Solo actúa si administración lo activó, solo sobre citas posteriores a esa activación y nunca dos veces.
2) Aviso: se crea un enlace privado (en la base solo queda su huella) y se envía un correo con el botón «Reagendar mi cita».
3) Reagendamiento: el cliente elige fecha y hora entre los horarios realmente libres; la cita conserva su código, sus datos y su
   historial, y queda marcada como reagendada. Nada de esto borra ni duplica registros.

El estado «No asistió» es distinto de «Cancelada», y administración puede revertirlo con «Reactivar cita»."""
import hashlib,json,re,secrets
from datetime import datetime,timedelta

import appointments

DEFAULTS={'auto':False,'grace':15,'mail':True,'link_days':7,'max_reschedules':2,'since':''}
LIMITS={'grace':(5,240),'link_days':(1,30),'max_reschedules':(1,5)}
SWEEP_WINDOW_HOURS=72          # nunca se revisan citas más antiguas: no hay cambios masivos sobre el historial
MAIL_ATTEMPTS=3
EMAIL=re.compile(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+')
NOTE_AUTO='Inasistencia registrada automáticamente'
NOTE_CLIENT='Cliente reagendó desde su enlace privado'


def digest(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def settings(c):
    row=c.execute("SELECT value FROM system_state WHERE key='appointment_no_show'").fetchone()
    try:stored=json.loads(row['value']) if row else {}
    except ValueError:stored={}
    out=dict(DEFAULTS)
    for key,value in stored.items():
        if key in DEFAULTS and type(value) is type(DEFAULTS[key]):out[key]=value
    return out


def save_settings(c,data,now):
    """Guarda la configuración de administración. Al activar el control automático se anota el momento: solo se revisan citas posteriores."""
    current=settings(c);fresh=dict(current)
    for key in ('auto','mail'):
        if key in data:
            if data[key] not in (True,False):raise ValueError('Valor no válido.')
            fresh[key]=data[key]
    for key,(low,high) in LIMITS.items():
        if key in data:
            text=str(data[key]).strip()
            if not text.isdigit() or not low<=int(text)<=high:raise ValueError({'grace':'La tolerancia debe estar entre %d y %d minutos.','link_days':'La vigencia del enlace debe estar entre %d y %d días.','max_reschedules':'El límite de reagendamientos debe estar entre %d y %d.'}[key]%(low,high))
            fresh[key]=int(text)
    if fresh['auto'] and not current['auto']:fresh['since']=appointments.stamp(now)
    c.execute("INSERT INTO system_state(key,value) VALUES ('appointment_no_show',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(fresh),))
    return fresh


def due(c,now,cfg):
    """Citas que ya deberían constar como inasistencia: confirmadas (o reprogramadas), sin llegada registrada, con la tolerancia vencida."""
    if not cfg['auto'] or not cfg['since']:return []
    limit=now-timedelta(minutes=cfg['grace']);floor=max(datetime.fromisoformat(cfg['since']),now-timedelta(hours=SWEEP_WINDOW_HOURS))
    rows=c.execute("SELECT * FROM appointments WHERE deleted_at IS NULL AND status IN ('confirmada','reprogramada') AND converted_order_id IS NULL ORDER BY starts_at").fetchall()
    return [row for row in rows if floor<=datetime.fromisoformat(row['starts_at'])<=limit]


def mark(c,row,now,cfg):
    """Registra la inasistencia de una cita. Devuelve True solo si esta llamada hizo el cambio (dos ejecutadas a la vez no lo repiten)."""
    stamp=appointments.stamp(now)
    done=c.execute("UPDATE appointments SET status='no_asistio',updated_at=? WHERE id=? AND status=? AND deleted_at IS NULL",(stamp,row['id'],row['status'])).rowcount
    if not done:return False
    c.execute("INSERT INTO appointment_events(appointment_id,actor_id,event,old_start,new_start,old_status,new_status,created_at,detail) VALUES (?,NULL,'no_show_auto',?,?,?,'no_asistio',?,?)",
              (row['id'],row['starts_at'],row['starts_at'],row['status'],stamp,NOTE_AUTO+': pasaron %d minutos desde la hora de la cita sin que se registrara la llegada del cliente.'%cfg['grace']))
    return True


def issue(c,row,now,cfg,reason='inasistencia'):
    """Crea el enlace privado de reagendamiento de una cita (anula los anteriores sin usar). Devuelve (token, id): el token solo existe aquí."""
    stamp=appointments.stamp(now);token=secrets.token_urlsafe(32)
    c.execute("UPDATE appointment_reschedule_links SET revoked_at=? WHERE appointment_id=? AND used_at='' AND revoked_at=''",(stamp,row['id']))
    link=c.execute('INSERT INTO appointment_reschedule_links(appointment_id,token_hash,reason,created_at,expires_at) VALUES (?,?,?,?,?)',(row['id'],digest(token),reason,stamp,appointments.stamp(now+timedelta(days=cfg['link_days'])))).lastrowid
    return token,link


def revoke(c,appointment_id,now):
    c.execute("UPDATE appointment_reschedule_links SET revoked_at=? WHERE appointment_id=? AND used_at='' AND revoked_at=''",(appointments.stamp(now),appointment_id))


def latest(c,appointment_id):
    row=c.execute('SELECT id,reason,created_at,expires_at,used_at,revoked_at,mail_status,mail_detail,mail_attempts FROM appointment_reschedule_links WHERE appointment_id=? ORDER BY id DESC LIMIT 1',(appointment_id,)).fetchone()
    return dict(row) if row else None


def sweep(c,now,notify=None):
    """Una pasada: registra las inasistencias vencidas y, si `notify` está disponible, envía los avisos pendientes (una vez por cita).
    `notify(c, cita, url) -> (estado, detalle)` lo aporta la aplicación. Devuelve un resumen para el registro administrativo."""
    cfg=settings(c);summary={'marked':0,'notified':0,'failed':0,'skipped':0}
    for row in due(c,now,cfg):
        if mark(c,row,now,cfg):summary['marked']+=1
    if not notify or not cfg['auto']:return summary
    floor=appointments.stamp(now-timedelta(hours=SWEEP_WINDOW_HOURS))
    for row in c.execute("SELECT a.* FROM appointments a WHERE a.deleted_at IS NULL AND a.status='no_asistio' AND a.starts_at>=? AND EXISTS(SELECT 1 FROM appointment_events e WHERE e.appointment_id=a.id AND e.event='no_show_auto' AND e.id=(SELECT MAX(x.id) FROM appointment_events x WHERE x.appointment_id=a.id AND x.new_status!=''))",(floor,)).fetchall():
        last=latest(c,row['id'])
        if last and (last['mail_status'] in ('enviado','sin_correo','sin_autorizacion','desactivado') or last['mail_attempts']>=MAIL_ATTEMPTS or last['used_at']):continue
        state=deliver(c,row,now,cfg,notify,attempts=(last['mail_attempts'] if last else 0))
        summary['notified' if state=='enviado' else 'failed' if state=='error' else 'skipped']+=1
    return summary


def deliver(c,row,now,cfg,notify,reason='inasistencia',attempts=0):
    """Crea un enlace nuevo y envía el aviso al cliente. El resultado queda en el propio enlace; un fallo no deshace la inasistencia."""
    token,link=issue(c,row,now,cfg,reason);email=(row['email'] or '').strip()
    if not cfg['mail']:state,detail='desactivado','El correo automático está desactivado en la configuración.'
    elif not email or not EMAIL.fullmatch(email):state,detail='sin_correo','El cliente no dejó un correo válido: contáctalo por teléfono o WhatsApp.'
    elif not row['communications_consent']:state,detail='sin_autorizacion','El cliente no autorizó recibir avisos por correo.'
    else:
        try:state,detail=notify(c,row,token)
        except Exception as error:state,detail='error',type(error).__name__
    c.execute('UPDATE appointment_reschedule_links SET mail_status=?,mail_detail=?,mail_attempts=? WHERE id=?',(state,str(detail)[:300],attempts+1,link))
    c.execute("INSERT INTO appointment_events(appointment_id,actor_id,event,created_at,detail) VALUES (?,NULL,'note',?,?)",(row['id'],appointments.stamp(now),{'enviado':'Aviso de reagendamiento enviado al correo del cliente.','error':'El aviso de reagendamiento no se pudo enviar: '+str(detail)[:120],'sin_correo':'Aviso de reagendamiento pendiente: el cliente no tiene correo.','sin_autorizacion':'Aviso de reagendamiento no enviado: el cliente no autorizó avisos por correo.','desactivado':'Enlace de reagendamiento creado; el correo automático está desactivado.'}[state]))
    return state


def find(c,token,now):
    """Estado de un enlace: ('ok' | 'invalid' | 'expired' | 'used' | 'closed' | 'limit', cita, enlace)."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{30,80}',str(token or '')):return 'invalid',None,None
    link=c.execute('SELECT * FROM appointment_reschedule_links WHERE token_hash=?',(digest(token),)).fetchone()
    if not link:return 'invalid',None,None
    row=c.execute('SELECT a.*,s.label service_label FROM appointments a LEFT JOIN appointment_services s ON s.code=a.service_code WHERE a.id=? AND a.deleted_at IS NULL',(link['appointment_id'],)).fetchone()
    if not row or link['revoked_at']:return 'invalid',None,None
    if link['used_at']:return 'used',row,link
    if datetime.fromisoformat(link['expires_at'])<now:return 'expired',row,link
    if row['status']!='no_asistio':return 'closed',row,link
    if row['reschedules']>=settings(c)['max_reschedules']:return 'limit',row,link
    return 'ok',row,link


def public(row,link=None):
    """Lo que ve el cliente en la página de reagendamiento: su cita, sin datos de contacto ni identificadores internos."""
    out={'code':row['public_code'],'service':row['service_label'] or 'Servicio técnico','service_code':row['service_code'],'starts_at':row['starts_at'],'duration':row['duration_minutes'],
         'device':' '.join(part for part in (row['brand'],row['model']) if part) or 'Equipo','name':(row['customer_name'] or '').split(' ')[0]}
    if link:out['expires_at']=link['expires_at']
    return out


def confirm(c,token,day,clock,now):
    """El cliente confirma su nueva fecha y hora. Devuelve (código HTTP, respuesta). Se ejecuta dentro de una transacción de escritura:
    si dos personas eligen el mismo horario a la vez, solo una lo obtiene y la otra recibe alternativas."""
    state,row,link=find(c,token,now)
    if state!='ok':return {'invalid':404,'expired':410,'used':409,'closed':409,'limit':409}[state],{'error':MESSAGES[state],'state':state}
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(day)) or not re.fullmatch(r'\d{2}:\d{2}',str(clock)):return 400,{'error':'Selecciona una fecha y una hora de la lista.'}
    try:
        open_slots=[slot['time'] for slot in appointments.available_slots(c,day,row['service_code'])]
        start=appointments.parse_start(day+'T'+clock)
    except ValueError as error:return 400,{'error':str(error)}
    busy={'error':'Este horario ya no está disponible. Selecciona otra opción.','conflict':True,'alternatives':appointments.alternatives(c,day,row['service_code'],clock)}
    if clock not in open_slots:return 409,busy
    result=appointments.reschedule(c,row,start,None)
    if not result.get('ok'):return 409,dict(busy,alternatives=result.get('alternatives') or busy['alternatives'])
    stamp=appointments.stamp(now)
    c.execute('UPDATE appointment_reschedule_links SET used_at=? WHERE id=?',(stamp,link['id']))
    c.execute("INSERT INTO appointment_events(appointment_id,actor_id,event,old_start,new_start,created_at,detail) VALUES (?,NULL,'note',?,?,?,?)",(row['id'],row['starts_at'],result['starts_at'],stamp,NOTE_CLIENT+'. Cita anterior: '+datetime.fromisoformat(row['starts_at']).strftime('%d/%m/%Y, %H:%M')+'.'))
    return 200,{'ok':True,'code':row['public_code'],'starts_at':result['starts_at'],'message':'Tu cita técnica fue reagendada correctamente.'}


MESSAGES={'invalid':'Este enlace de reagendamiento no es válido.','expired':'El enlace de reagendamiento ha caducado. Solicita uno nuevo.','used':'Este enlace ya se utilizó: la cita fue reagendada.',
          'closed':'Esta cita ya no necesita reagendarse. Si tienes dudas, contáctanos.','limit':'Esta cita alcanzó el número máximo de reagendamientos. Contáctanos para ayudarte.'}


def renewable(c,code,identification,now):
    """Cita para la que se puede pedir un enlace nuevo: «No asistió», con su código y la identificación del cliente, y dentro del límite."""
    code=str(code or '').strip().upper();number=re.sub(r'\s+','',str(identification or '')).upper()
    if not re.fullmatch(r'[A-Z0-9-]{6,40}',code) or len(number)<5:return None
    row=c.execute("SELECT * FROM appointments WHERE upper(public_code)=? AND deleted_at IS NULL AND status='no_asistio'",(code,)).fetchone()
    if not row or (row['identification'] or '').upper()!=number or row['reschedules']>=settings(c)['max_reschedules']:return None
    return row
