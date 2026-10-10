"""Cron: avisos administrativos siempre; correo solo con habilitación y consentimiento."""
import argparse,os,smtplib,ssl
from email.message import EmailMessage
import app,maintenance
from reception import reception_now,public_base_url

def run(send_email=False):
    now=reception_now();stamp=now.isoformat();summary={'pending':0,'accepted':0,'failed':0}
    with app.connect() as c:
        c.execute('BEGIN IMMEDIATE');maintenance.due(c,now)
        summary['pending']=c.execute("SELECT count(*) FROM maintenance_notifications WHERE channel='admin' AND result='pending'").fetchone()[0]
    if not send_email:return summary
    if os.getenv('MAINTENANCE_EMAIL_ENABLED','false').lower()!='true':raise RuntimeError('Habilita MAINTENANCE_EMAIL_ENABLED después de configurar SMTP y revisar los consentimientos.')
    host=os.getenv('SMTP_HOST');sender=os.getenv('SMTP_FROM')
    if not host or not sender:raise RuntimeError('SMTP no configurado.')
    with app.connect() as c:items=maintenance.rows(c)
    for row in items:
        if row['state'] not in ('scheduled','appointment') or row['due_date']>now.date().isoformat() or row['consent']!='accepted' or not row['email']:continue
        with app.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            # Revalidar consentimiento y versión dentro del bloqueo antes de reservar.
            current=c.execute('SELECT * FROM maintenance WHERE id=?',(row['id'],)).fetchone()
            if current['generation']!=row['generation'] or current['consent']!='accepted' or current['state'] not in ('scheduled','appointment'):continue
            cursor=c.execute("INSERT OR IGNORE INTO maintenance_notifications(maintenance_id,generation,channel,result,created_at) VALUES (?,?,'email','processing',?)",(row['id'],row['generation'],stamp))
            if not cursor.rowcount:continue
        message=EmailMessage();message['Subject']='Próximo mantenimiento preventivo · PC-DOCTOR S.A.';message['From']=sender;message['To']=row['email'];message['Message-ID']='<maintenance-'+str(row['id'])+'-'+str(row['generation'])+'@ordenes-pro.ecuadorpcdoctor.com>'
        stop=public_base_url()+'/maintenance-preferences/'+row['unsubscribe_token']
        message.set_content('Hola '+row['client']+',\n\nSu revisión preventiva está recomendada para '+row['due_date']+'. Equipo: '+row['brand']+' '+row['model']+'. Orden original: '+row['code']+'.\nCoordine su cita con PC-DOCTOR S.A.: +593 98 746 0591.\n\nPara dejar de recibir recordatorios: '+stop)
        try:
            with smtplib.SMTP(host,int(os.getenv('SMTP_PORT','587')),timeout=20) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if os.getenv('SMTP_USER'):smtp.login(os.environ['SMTP_USER'],os.getenv('SMTP_PASSWORD',''))
                refused=smtp.send_message(message)
                if refused:raise RuntimeError('El servidor rechazó al destinatario.')
            result='accepted';detail='Aceptado por SMTP; no acredita lectura ni entrega final.';summary['accepted']+=1
        except (OSError,RuntimeError,smtplib.SMTPException):
            result='failed';detail='No se confirmó aceptación del proveedor. Revisión manual antes de reintentar.';summary['failed']+=1
        with app.connect() as c:c.execute("UPDATE maintenance_notifications SET result=?,completed_at=?,detail=? WHERE maintenance_id=? AND generation=? AND channel='email'",(result,reception_now().isoformat(),detail,row['id'],row['generation']))
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--send-email',action='store_true');args=parser.parse_args();app.load_env();app.migrate();print(run(args.send_email))
