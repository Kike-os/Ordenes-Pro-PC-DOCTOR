"""Agenda persistente; las entregas y los avisos se procesan transaccionalmente."""
import calendar,secrets
from datetime import date,datetime
from zoneinfo import ZoneInfo
ZONE=ZoneInfo('America/Guayaquil')
PROFILES={
 'general':('Equipo de taller',['Inspección física y funcional.','Limpieza conforme a las especificaciones del fabricante.','Revisión preventiva según diagnóstico y condiciones de uso.'],'según uso y fabricante'),
 'gaming':('Portátil Gaming',['Inspección y limpieza de refrigeración.','Revisión de temperaturas de CPU y GPU.','Evaluación de ventiladores, batería y materiales térmicos según diagnóstico.'],'3 a 6 meses en uso intensivo'),
 'office':('Oficina o estudio',['Limpieza de ventilación.','Verificación de temperaturas y batería.','Revisión de almacenamiento y sistema operativo.'],'6 a 12 meses'),
 'workstation':('Workstation',['Revisión térmica bajo carga.','Inspección y limpieza de refrigeración.','Diagnóstico de ventiladores y almacenamiento.'],'3 a 6 meses según carga'),
 'ultrabook':('Ultrabook',['Revisión de temperaturas.','Limpieza de entradas y salidas de aire.','Evaluación de batería y estado físico.'],'6 a 12 meses')}
def six_months(day):
    month=day.month+6;year=day.year+(month-1)//12;month=(month-1)%12+1
    return date(year,month,min(day.day,calendar.monthrange(year,month)[1]))
def transition(c,oid,old,new,now):
    """Al confirmarse la entrega crea (una sola vez por orden) la previsión a seis meses calendario. Devuelve la previsión creada."""
    if old==new:return None
    stamp=now.astimezone(ZONE).isoformat(timespec='microseconds')
    if new=='entregado':
        category=c.execute('SELECT d.category FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?',(oid,)).fetchone()[0]
        c.execute('UPDATE orders SET delivered_at=? WHERE id=?',(stamp,oid))
        c.execute("INSERT INTO maintenance(order_id,delivered_at,due_date,profile,updated_at,unsubscribe_token) VALUES (?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET delivered_at=excluded.delivered_at,due_date=excluded.due_date,state='scheduled',generation=maintenance.generation+1,updated_at=excluded.updated_at",(oid,stamp,six_months(now.astimezone(ZONE).date()).isoformat(),'gaming' if category=='gaming' else 'office' if category=='portatil' else 'general',stamp,secrets.token_urlsafe(32)))
        # Una entrega nueva es un hecho nuevo: se levanta la exclusión que dejó una cita eliminada.
        c.execute('UPDATE maintenance SET auto_appointment_blocked=0 WHERE order_id=?',(oid,))
        row=c.execute('SELECT id,due_date FROM maintenance WHERE order_id=?',(oid,)).fetchone()
        return {'id':row['id'],'due_date':row['due_date']}
    elif old=='entregado':
        # La entrega se revirtió: la previsión queda cancelada con su historial, no se borra.
        # Su cita automática, si aún no se atendió, se cancela con registro en el historial de la cita.
        linked=c.execute("SELECT a.id,a.status,a.starts_at FROM maintenance m JOIN appointments a ON a.id=m.appointment_id WHERE m.order_id=? AND a.status IN ('solicitada','confirmada','reprogramada')",(oid,)).fetchone()
        if linked:
            c.execute("UPDATE appointments SET status='cancelada',updated_at=? WHERE id=?",(stamp,linked['id']))
            c.execute("INSERT INTO appointment_events(appointment_id,event,old_start,old_status,new_status,created_at,detail) VALUES (?,'cancelled',?,?,'cancelada',?,'La entrega de la orden fue reabierta')",(linked['id'],linked['starts_at'],linked['status'],stamp))
        c.execute("UPDATE maintenance SET state='cancelled',appointment_id=NULL,generation=generation+1,updated_at=? WHERE order_id=?",(stamp,oid))
        # La orden ya no está entregada: la fecha de entrega revertida no debe seguir contando como entrega (estadías, reportes, último servicio).
        c.execute("UPDATE orders SET delivered_at='' WHERE id=?",(oid,))
    return None

def proximity(days):
    """Nivel de cercanía de la fecha prevista; es independiente del estado operativo del mantenimiento."""
    return 'overdue' if days<0 else 'today' if days==0 else 'week' if days<=7 else 'fortnight' if days<=15 else 'month' if days<=30 else 'quarter' if days<=90 else 'far'
def rows(c,today=None):
    """Previsiones con sus días restantes, nivel de proximidad y avance (entrega → fecha prevista) calculados en America/Guayaquil."""
    today=today or datetime.now(ZONE).date();out=[]
    for row in _rows(c):
        try:
            due=date.fromisoformat(row['due_date']);start=datetime.fromisoformat(row['delivered_at']).astimezone(ZONE).date()
            span=(due-start).days;row['days_left']=(due-today).days;row['proximity']=proximity(row['days_left'])
            row['progress']=100 if span<=0 else max(0,min(100,round((today-start).days*100/span)))
        except (ValueError,TypeError):row['days_left']=None;row['proximity']='unknown';row['progress']=None
        out.append(row)
    return out
def _rows(c):
    # Una previsión anulada porque se revirtió la entrega no es un mantenimiento pendiente: no se lista. Se conserva en la base con su
    # historial y la preferencia de recordatorios del cliente, y vuelve a «Programado» si la orden se entrega de verdad.
    return [dict(r) for r in c.execute("SELECT m.*,o.code,o.qr_url,c.id client_id,d.id device_id,c.name client,c.phone,c.email,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,d.serial,(SELECT a.starts_at FROM appointments a WHERE a.id=m.appointment_id) appointment_start,(SELECT a.status FROM appointments a WHERE a.id=m.appointment_id) appointment_status,(SELECT a.public_code FROM appointments a WHERE a.id=m.appointment_id) appointment_code,COALESCE((SELECT result FROM maintenance_notifications n WHERE n.maintenance_id=m.id AND n.generation=m.generation AND n.channel='email'),'Sin enviar') reminder FROM maintenance m JOIN orders o ON o.id=m.order_id JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id WHERE m.state!='cancelled' ORDER BY m.due_date,m.id")]

def due(c,now):
    stamp=now.astimezone(ZONE).isoformat();today=now.astimezone(ZONE).date().isoformat()
    c.execute("INSERT OR IGNORE INTO maintenance_notifications(maintenance_id,generation,channel,result,created_at) SELECT id,generation,'admin','pending',? FROM maintenance WHERE due_date<=? AND state IN ('scheduled','appointment')",(stamp,today))

def update(c,mid,data,user,now):
    row=c.execute('SELECT * FROM maintenance WHERE id=?',(mid,)).fetchone()
    if not row:return 404,{'error':'Mantenimiento no disponible.'}
    action=data.get('action');stamp=now.astimezone(ZONE).isoformat()
    if action=='reschedule':
        try:
            day=date.fromisoformat(str(data.get('due_date','')))
            if day.isoformat()!=data['due_date']:raise ValueError()
        except (ValueError,KeyError):return 400,{'error':'Indica una fecha válida.'}
        profile=data.get('profile',row['profile'])
        if profile not in PROFILES:return 400,{'error':'Selecciona un perfil válido.'}
        # Si ya tiene una cita vinculada conserva el estado «con cita»; la cita se reprograma desde la agenda.
        c.execute("UPDATE maintenance SET due_date=?,profile=?,state=CASE WHEN appointment_id IS NOT NULL THEN 'appointment' ELSE 'scheduled' END,generation=generation+1,updated_at=? WHERE id=?",(day.isoformat(),profile,stamp,mid))
    elif action in ('completed','appointment'):
        if row['state']=='cancelled':return 409,{'error':'La entrega fue reabierta. Confirma una nueva entrega antes de programar.'}
        c.execute('UPDATE maintenance SET state=?,updated_at=? WHERE id=?',(action,stamp,mid))
    elif action=='retry_email':
        if row['state'] not in ('scheduled','appointment') or row['consent']!='accepted' or row['due_date']>now.astimezone(ZONE).date().isoformat():return 400,{'error':'Se requiere una programación vencida o para hoy y consentimiento vigente.'}
        c.execute('UPDATE maintenance SET generation=generation+1,updated_at=? WHERE id=?',(stamp,mid))
    elif action=='consent':
        consent=data.get('consent')
        if consent not in ('accepted','declined'):return 400,{'error':'Registra aceptación o rechazo explícito del cliente.'}
        c.execute('UPDATE maintenance SET consent=?,consent_at=?,consent_actor=?,updated_at=? WHERE id=?',(consent,stamp,user['id'],stamp,mid))
    else:return 400,{'error':'Acción no disponible.'}
    from order_workspace import event
    event(c,row['order_id'],user['id'],now,'maintenance',{'completed':'Mantenimiento realizado.','appointment':'Cita de mantenimiento confirmada.','consent':'Preferencia de recordatorios registrada.','reschedule':'Mantenimiento reprogramado.','retry_email':'Nuevo recordatorio de correo solicitado por administración.'}[action])
    return 200,{'ok':True}

def card(row,thermal=False):
    from document_canvas import Canvas
    from corporate import settings
    corp=settings();w=226.77 if thermal else 420;h=500 if thermal else 380
    doc=Canvas(w,h,'Próximo mantenimiento · '+row['code'],thermal);left=12 if thermal else 22
    paragraphs=[('PRÓXIMO MANTENIMIENTO PREVENTIVO',11,True)]
    for label,value in [('Cliente',row['client']),('Equipo',' '.join([row['brand'],row['model']])),('Orden original',row['code']),('Último servicio',row['delivered_at'][:10]),('Próxima revisión',row['due_date'])]:paragraphs.append((label+': '+value,9,False))
    for recommendation in PROFILES[row['profile']][1]:paragraphs.append(('• '+recommendation,8,False))
    paragraphs.extend([('Intervalo orientativo: '+PROFILES[row['profile']][2]+'. Intervenciones según diagnóstico y garantía.',7,False),('WhatsApp '+corp['whatsapp']+' · '+corp['website'],7,False)])
    layout=[(doc.wrap(text,w-2*left,size),size,bold) for text,size,bold in paragraphs]
    doc.h=86+sum(len(lines)*size*1.4+5 for lines,size,bold in layout)+14
    doc.page();doc.logo(left,18,60);doc.text(corp['name'],left+68,25,10,True);y=86
    for lines,size,bold in layout:
        for line in lines:doc.text(line,left,y,size,bold);y+=size*1.4
        y+=5
    return doc.finish()


def link_appointment(c,mid,aid,user,now):
    """Vincula la cita real que el cliente aceptó con su previsión; la previsión pasa a «con cita»."""
    row=c.execute("SELECT * FROM maintenance WHERE id=? AND state IN ('scheduled','appointment')",(mid,)).fetchone()
    if not row:return False
    c.execute("UPDATE maintenance SET appointment_id=?,state='appointment',updated_at=? WHERE id=?",(aid,now.astimezone(ZONE).isoformat(),mid))
    from order_workspace import event
    event(c,row['order_id'],user['id'],now,'maintenance','Cita de mantenimiento preventivo registrada.')
    return True


def appointment_changed(c,aid,status,now):
    """Mantiene la previsión coherente con su cita: cancelada o no asistida vuelve a programada; completada la cierra."""
    stamp=now.astimezone(ZONE).isoformat()
    # La previsión se conserva; la cita cancelada no se regenera sola (se puede agendar otra a mano).
    if status in ('cancelada','no_asistio'):c.execute("UPDATE maintenance SET state='scheduled',appointment_id=NULL,auto_appointment_blocked=1,updated_at=? WHERE appointment_id=? AND state='appointment'",(stamp,aid))
    elif status=='completada':c.execute("UPDATE maintenance SET state='completed',updated_at=? WHERE appointment_id=? AND state='appointment'",(stamp,aid))
