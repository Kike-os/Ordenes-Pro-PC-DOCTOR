"""Entrega avisos de citas desde cron en cPanel. Requiere SMTP y consentimiento."""
import os,sqlite3,time,smtplib,ssl
from email.message import EmailMessage
from pathlib import Path
import appointments,remote_db
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

def send_staff(row):
 """Aviso al taller de una cita nueva. Solo datos de la cita; se envía al buzón del taller, no al cliente."""
 host=os.getenv('SMTP_HOST');sender=os.getenv('SMTP_FROM');target=os.getenv('APPOINTMENTS_NOTIFY_TO') or sender
 if not host or not sender or not target:raise RuntimeError('SMTP no configurado')
 start=appointments.datetime.fromisoformat(row['starts_at']).astimezone(appointments.TZ)
 message=EmailMessage();message['From']=sender;message['To']=target;message['Subject']=f"Nueva cita {'por confirmar' if row['status']=='solicitada' else 'reservada'} · {row['public_code']}"
 message.set_content(f"Se registró una cita desde la agenda en línea.\n\nCódigo: {row['public_code']}\nEstado: {appointments.STATUSES.get(row['status'],row['status'])}\nCliente: {row['customer_name']}\nServicio: {row['service_label']}\nFecha: {start.strftime('%d/%m/%Y')} {start.strftime('%H:%M')} (hora de Ecuador)\nEquipo: {row['device_type']} · {row['brand']} {row['model']}\n\nRevísala en Órdenes Pro → Agenda de Mantenimientos de Clientes.\n")
 port=int(os.getenv('SMTP_PORT','587'))
 with smtplib.SMTP(host,port,timeout=20) as smtp:
  smtp.starttls(context=ssl.create_default_context())
  if os.getenv('SMTP_USER'):smtp.login(os.environ['SMTP_USER'],os.getenv('SMTP_PASSWORD',''))
  smtp.send_message(message)

def notify_staff(conn):
 """Un correo por cita nueva, sin repetir: el último id avisado queda en system_state."""
 state=conn.execute("SELECT value FROM system_state WHERE key='appointments_staff_notified'").fetchone();last=int(state['value']) if state and str(state['value']).isdigit() else None
 if last is None:
  # Primera ejecución: no se avisan las citas antiguas.
  newest=conn.execute('SELECT COALESCE(MAX(id),0) FROM appointments').fetchone()[0];conn.execute("INSERT INTO system_state(key,value) VALUES ('appointments_staff_notified',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(newest),));conn.commit();return 0
 sent=0
 for row in conn.execute("SELECT a.*,COALESCE(NULLIF(a.services_summary,''),s.label) service_label FROM appointments a JOIN appointment_services s ON s.code=a.service_code WHERE a.id>? AND a.deleted_at IS NULL ORDER BY a.id LIMIT 20",(last,)).fetchall():
  try:send_staff(row)
  except Exception as error:
   print('citas: aviso al taller no enviado:',str(error)[:120]);break
  conn.execute("UPDATE system_state SET value=? WHERE key='appointments_staff_notified'",(str(row['id']),));conn.commit();sent+=1
 return sent

def run():
 if remote_db.configured():conn=remote_db.connect()
 else:conn=sqlite3.connect(DB,timeout=20);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON')
 now=appointments.now();now_s=appointments.stamp(now)
 try:
  conn.execute('BEGIN IMMEDIATE')
  conn.execute("UPDATE appointment_notifications SET result='pending' WHERE result='sending' AND created_at<?",(appointments.stamp(now-appointments.timedelta(minutes=15)),))
  active=conn.execute("SELECT * FROM appointments WHERE deleted_at IS NULL AND communications_consent=1 AND email!='' AND status IN ('confirmada','reprogramada','presente') AND starts_at>? AND starts_at<?",(now_s,appointments.stamp(now+appointments.timedelta(hours=25)))).fetchall()
  for row in active:
   start=appointments.datetime.fromisoformat(row['starts_at']).astimezone(appointments.TZ);delta=(start-now).total_seconds()/3600
   event='reminder_24h' if 23<=delta<=25 else ('reminder_2h' if 1.5<=delta<=2.5 else None)
   if event:conn.execute("INSERT OR IGNORE INTO appointment_notifications(appointment_id,generation,event,channel,result,created_at) VALUES (?,?,?,'email','pending',?)",(row['id'],row['generation'],event,now_s))
  conn.commit()
  pending=conn.execute("SELECT n.id,n.event,a.* ,COALESCE(NULLIF(a.services_summary,''),s.label) service_label FROM appointment_notifications n JOIN appointments a ON a.id=n.appointment_id JOIN appointment_services s ON s.code=a.service_code WHERE n.result='pending' AND n.channel='email' AND a.deleted_at IS NULL AND a.communications_consent=1 AND a.email!='' ORDER BY n.id LIMIT 100").fetchall()
  sent=failed=0
  for row in pending:
   cur=conn.execute("UPDATE appointment_notifications SET result='sending' WHERE id=? AND result='pending'",(row['id'],));conn.commit()
   if not cur.rowcount:continue
   try:
    send(row,row['event']);conn.execute("UPDATE appointment_notifications SET result='sent',completed_at=?,detail='SMTP aceptó el mensaje' WHERE id=?",(appointments.stamp(appointments.now()),row['id']));sent+=1
   except Exception as error:
    conn.execute("UPDATE appointment_notifications SET result='failed',completed_at=?,detail=? WHERE id=?",(appointments.stamp(appointments.now()),str(error)[:300],row['id']));failed+=1
   conn.commit()
  staff=notify_staff(conn)
  print(f"citas: enviados={sent}; fallidos={failed}; avisos al taller={staff}; hora={now_s}")
 finally:conn.close()
if __name__=='__main__':load_env();run()
