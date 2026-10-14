"""Correos de citas al cliente: solicitud recibida, cita confirmada, reprogramación y cancelación.

Se envían al momento por el SMTP de Mail Pro con los datos guardados en el servidor. Requieren correo del cliente y su
autorización de comunicaciones. Un envío por tipo y versión de la cita (sin duplicados); un fallo nunca afecta a la cita.
«sent» significa que el servidor de correo aceptó el mensaje, no que el cliente lo haya leído.
"""
import html
import re
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate,make_msgid
from pathlib import Path

import appointments,mail_pro
from corporate import settings
from reception import DEVICE_TYPES

KINDS={'request':('Solicitud de cita recibida','Tu solicitud fue registrada y está pendiente de confirmación.','#B7791F','Pendiente de confirmación'),
       'confirmation':('Cita técnica confirmada','Tu cita técnica está confirmada para {date} a las {time}.','#1F8F65','Confirmada'),
       'rescheduled':('Cita técnica reprogramada','Tu cita técnica fue reprogramada para {date} a las {time}.','#6B5BD2','Reprogramada'),
       'cancelled':('Cita técnica cancelada','Tu cita técnica fue cancelada. Si deseas una nueva fecha, puedes reservarla cuando lo necesites.','#5F6F85','Cancelada')}
MONTHS=('enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre')
DAYS=('lunes','martes','miércoles','jueves','viernes','sábado','domingo')


def kind_for(status):
    return 'confirmation' if status=='confirmada' else 'request' if status=='solicitada' else 'rescheduled' if status=='reprogramada' else 'cancelled' if status=='cancelada' else ''


def compose(row,kind,config,signature=None):
    """Mensaje con versión de texto y HTML sencillo (tablas y estilos en línea, compatible con Gmail y Outlook)."""
    company=settings();title,lead,color,state=KINDS[kind]
    start=datetime.fromisoformat(row['starts_at']).astimezone(appointments.TZ)
    date=DAYS[start.weekday()]+', '+str(start.day)+' de '+MONTHS[start.month-1]+' de '+str(start.year);clock=start.strftime('%H:%M')
    lead=lead.format(date=date,time=clock)
    device=' · '.join(x for x in (DEVICE_TYPES.get(row['device_type'],''),row['brand'],row['model']) if x) or 'No indicado'
    facts=[('Código de cita',row['public_code']),('Cliente',row['customer_name']),('Fecha',date.capitalize()),('Hora',clock+' (hora de Ecuador)'),('Equipo',device),('Servicio',row['service_label']),('Estado',state)]
    advice='' if kind=='cancelled' else 'Lleva tu equipo con su cargador y los accesorios relacionados con la falla. La orden de reparación se registra cuando recibimos físicamente el equipo.'
    contact='WhatsApp '+company['whatsapp']+' · '+company['website']
    text='Hola '+row['customer_name']+':\n\n'+lead+'\n\n'+'\n'.join(label+': '+value for label,value in facts)+('\n\n'+advice if advice else '')+'\n\nPara cambiar o cancelar tu cita, contáctanos.\n'+contact+'\n\n'+company['name']+'\n'+company['specialty']
    # Plantilla institucional común (encabezado textual, datos en tabla y firma autorizada al final).
    import mailing
    page_text='Hola '+row['customer_name']+':\n\n'+lead+'\n\n'+'\n'.join(label+': '+value for label,value in facts)+('\n\n'+advice if advice else '')+'\n\nPara cambiar o cancelar tu cita, contáctanos.\n'+contact
    # La firma la compone el mismo punto único que usan los demás correos del sistema (mail_pro.signature_part).
    sign=signature if isinstance(signature,dict) and signature.get('enabled') else None
    sign_html,sign_cid,sign_image,sign_kind=mail_pro.signature_part(sign,config['username'].split('@')[-1]) if sign else ('','',None,'png')
    body=mailing.html(page_text,title,sign_html)
    if sign:text+='\n\n-- \n'+mail_pro.signature_text(sign)
    message=EmailMessage()
    message['From']=company['name']+' <'+config['username']+'>';message['To']=row['email']
    message['Subject']=title+' — '+row['public_code']+' | '+company['name']
    message['Date']=formatdate(localtime=True);message['Message-ID']=make_msgid(domain=config['username'].split('@')[-1])
    message.set_content(text);message.add_alternative(body,subtype='html')
    if sign_image:message.get_payload()[1].add_related(sign_image,'image',sign_kind,cid=sign_cid,disposition='inline')
    return message


def send(c,appointment_id,kind,force=False):
    """Envía (una sola vez por tipo y versión) y registra el resultado. Nunca lanza errores hacia la reserva."""
    if kind not in KINDS:return None
    row=c.execute('SELECT a.*,s.label service_label FROM appointments a JOIN appointment_services s ON s.code=a.service_code WHERE a.id=?',(appointment_id,)).fetchone()
    if not row:return None
    previous=c.execute('SELECT id,result FROM appointment_mail WHERE appointment_id=? AND kind=? AND generation=?',(row['id'],kind,row['generation'])).fetchone()
    if previous and (previous['result']=='sent' or not force):return previous['result']
    email=(row['email'] or '').strip();result='sent';detail='El servidor de correo aceptó el mensaje.'
    try:ready=mail_pro.configured()
    except mail_pro.MailError:ready=False
    if not email or not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+',email):result,detail='no_email',''
    elif not row['communications_consent']:result,detail='no_consent',''
    elif not ready:result,detail='not_configured',''
    else:
        try:
            import json,mailing
            config=mail_pro.settings()
            message=compose(row,kind,config,mail_pro.load_signature(c,config['username']))
            import mail_tracking
            archive_id=mailing.archive(c,'appointment',None,email,str(message['Subject']),message,'plantilla',None,appointments.now())
            tracked=mail_tracking.start(c,[email],kind='appointment',subject=str(message['Subject']),now=appointments.now(),archive_id=archive_id)
            c.commit()
            try:
                # No se reintenta automáticamente hacia una dirección declarada inválida por un rebote permanente.
                refusal=mail_tracking.blocked(c,email)
                if refusal:raise mail_pro.MailError('destinatario',refusal+' No se reintenta automáticamente: corrige la dirección del cliente.')
                outcome=mail_pro.deliver(config,message,[email])
            except mail_pro.MailError as error:
                mailing.mark(c,archive_id,'error',str(error));mail_tracking.failed(c,tracked,error,appointments.now());raise
            mailing.mark(c,archive_id,'enviado','El servidor de correo aceptó el mensaje.',str(message['Message-ID'] or ''),appointments.now())
            mail_tracking.accepted(c,tracked,str(message['Message-ID'] or ''),appointments.now(),outcome)
        except mail_pro.MailError as error:
            print('appointment-mail',kind,error.kind,flush=True);result,detail='failed',str(error)[:300]
        except Exception as error:  # Un fallo inesperado del correo no debe afectar a la cita.
            print('appointment-mail',kind,type(error).__name__,flush=True);result,detail='failed','No se pudo preparar el mensaje.'
    stamp=appointments.stamp(appointments.now())
    c.execute('INSERT INTO appointment_mail(appointment_id,kind,generation,recipient,result,detail,created_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(appointment_id,kind,generation) DO UPDATE SET recipient=excluded.recipient,result=excluded.result,detail=excluded.detail,created_at=excluded.created_at',(row['id'],kind,row['generation'],email if result in ('sent','failed') else '',result,detail,stamp))
    if result=='sent' and kind!='request':
        # El aviso heredado (tarea programada) queda marcado como enviado para que nunca se repita.
        c.execute("UPDATE appointment_notifications SET result='sent',completed_at=?,detail='Enviado al momento por Mail Pro' WHERE appointment_id=? AND generation=? AND event=? AND channel='email' AND result!='sent'",(stamp,row['id'],row['generation'],kind))
    return result


def history(c,appointment_id):
    return [dict(r) for r in c.execute('SELECT kind,generation,recipient,result,detail,created_at FROM appointment_mail WHERE appointment_id=? ORDER BY id DESC',(appointment_id,))]
