"""Entrega avisos de citas desde cron en cPanel. Requiere SMTP y consentimiento."""
import os,sqlite3,time,smtplib,ssl
from email.message import EmailMessage
from pathlib import Path
import appointments
ROOT=Path(__file__).resolve().parent
DB=Path(os.getenv('APP_DB',ROOT/'var'/'ordenes.sqlite3'))

def load_env():
 for line in (ROOT/'.env').read_text().splitlines() if (ROOT/'.env').exists() else []:
  if line.strip() and not line.lstrip().startswith('#') and '=' in line:
   key,value=line.split('=',1);os.environ.setdefault(key.strip(),value.strip())

def send(row,event):
 host=os.getenv('SMTP_HOST');sender=os.getenv('SMTP_FROM')
 if not host or not sender:raise RuntimeError('SMTP no configurado')
 message=EmailMessage();message['From']=sender;message['To']=row['email'];message['Subject']=f"PC-DOCTOR S.A. · {row['service_label']} · {row['public_code']}"
 start=appointments.datetime.fromisoformat(row['starts_at']).astimezone(appointments.TZ)
 action={'confirmation':'confirmada','reminder_24h':'mañana','reminder_2h':'en aproximadamente dos horas','rescheduled':'reprogramada','cancelled':'cancelada'}.get(event,event)
 message.set_content(f"Hola {row['customer_name']},\n\nTu cita técnica está {action}.\nCódigo: {row['public_code']}\nServicio: {row['service_label']}\nFecha: {start.strftime('%d/%m/%Y')}\nHora: {start.strftime('%H:%M')} (hora de Ecuador)\nEquipo: {row['device_type']} · {row['brand']} {row['model']}\n\nSi necesitas cambiar la cita, visita https://ordenes-pro.ecuadorpcdoctor.com/citas y contacta a PC-DOCTOR S.A.\nWhatsApp: +593 98 746 0591\nEste mensaje se envía únicamente conforme al consentimiento registrado para comunicaciones de citas.")
 port=int(os.getenv('SMTP_PORT','587'))
 with smtplib.SMTP(host,port,timeout=20) as smtp:
  smtp.starttls(context=ssl.create_default_context())
  if os.getenv('SMTP_USER'):smtp.login(os.environ['SMTP_USER'],os.getenv('SMTP_PASSWORD',''))
  smtp.send_message(message)

def run():
 conn=sqlite3.connect(DB,timeout=20);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON');now=appointments.now();now_s=appointments.stamp(now)
 try:
  conn.execute('BEGIN IMMEDIATE')
  conn.execute("UPDATE appointment_notifications SET result='pending' WHERE result='sending' AND created_at<?",(appointments.stamp(now-appointments.timedelta(minutes=15)),))
  active=conn.execute("SELECT * FROM appointments WHERE communications_consent=1 AND email!='' AND status IN ('confirmada','reprogramada','presente') AND starts_at>? AND starts_at<?",(now_s,appointments.stamp(now+appointments.timedelta(hours=25)))).fetchall()
  for row in active:
   start=appointments.datetime.fromisoformat(row['starts_at']).astimezone(appointments.TZ);delta=(start-now).total_seconds()/3600
   event='reminder_24h' if 23<=delta<=25 else ('reminder_2h' if 1.5<=delta<=2.5 else None)
   if event:conn.execute("INSERT OR IGNORE INTO appointment_notifications(appointment_id,generation,event,channel,result,created_at) VALUES (?,?,?,'email','pending',?)",(row['id'],row['generation'],event,now_s))
  conn.commit()
  pending=conn.execute("SELECT n.id,n.event,a.* ,s.label service_label FROM appointment_notifications n JOIN appointments a ON a.id=n.appointment_id JOIN appointment_services s ON s.code=a.service_code WHERE n.result='pending' AND n.channel='email' AND a.communications_consent=1 AND a.email!='' ORDER BY n.id LIMIT 100").fetchall()
  sent=failed=0
  for row in pending:
   cur=conn.execute("UPDATE appointment_notifications SET result='sending' WHERE id=? AND result='pending'",(row['id'],));conn.commit()
   if not cur.rowcount:continue
   try:
    send(row,row['event']);conn.execute("UPDATE appointment_notifications SET result='sent',completed_at=?,detail='SMTP aceptó el mensaje' WHERE id=?",(appointments.stamp(appointments.now()),row['id']));sent+=1
   except Exception as error:
    conn.execute("UPDATE appointment_notifications SET result='failed',completed_at=?,detail=? WHERE id=?",(appointments.stamp(appointments.now()),str(error)[:300],row['id']));failed+=1
   conn.commit()
  print(f"citas: enviados={sent}; fallidos={failed}; hora={now_s}")
 finally:conn.close()
if __name__=='__main__':load_env();run()
