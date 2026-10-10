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
    if old==new:return
    stamp=now.astimezone(ZONE).isoformat(timespec='microseconds')
    if new=='entregado':
        category=c.execute('SELECT d.category FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?',(oid,)).fetchone()[0]
        c.execute('UPDATE orders SET delivered_at=? WHERE id=?',(stamp,oid))
        c.execute("INSERT INTO maintenance(order_id,delivered_at,due_date,profile,updated_at,unsubscribe_token) VALUES (?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET delivered_at=excluded.delivered_at,due_date=excluded.due_date,state='scheduled',generation=maintenance.generation+1,updated_at=excluded.updated_at",(oid,stamp,six_months(now.astimezone(ZONE).date()).isoformat(),'gaming' if category=='gaming' else 'office' if category=='portatil' else 'general',stamp,secrets.token_urlsafe(32)))
    elif old=='entregado':
        c.execute("UPDATE maintenance SET state='cancelled',generation=generation+1,updated_at=? WHERE order_id=?",(stamp,oid))

def rows(c):
    return [dict(r) for r in c.execute("SELECT m.*,o.code,o.qr_url,c.name client,c.phone,c.email,d.category type,d.brand,d.model,d.serial,COALESCE((SELECT result FROM maintenance_notifications n WHERE n.maintenance_id=m.id AND n.generation=m.generation AND n.channel='email'),'Sin enviar') reminder FROM maintenance m JOIN orders o ON o.id=m.order_id JOIN devices d ON d.id=o.device_id JOIN clients c ON c.id=d.client_id ORDER BY m.due_date,m.id")]

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
        c.execute("UPDATE maintenance SET due_date=?,profile=?,state='scheduled',generation=generation+1,updated_at=? WHERE id=?",(day.isoformat(),profile,stamp,mid))
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
