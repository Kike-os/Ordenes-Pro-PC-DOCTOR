import sys,time,secrets
from pathlib import Path
sys.path.insert(0,'/home/admin-red/Work/ordenes-pro/local/tests')
import test_app,app,appointments
T=test_app.SecurityTests
T.setUpClass()
t=T('test_password_is_salted_and_verified');t.setUp()
app.os.environ['APP_URL']='http://127.0.0.1:8010'
cookie,csrf=t.login()
# Test harness accepts only its configured origin, so prepare data before serving with the preview URL.
app.os.environ['APP_URL']='http://127.0.0.1:8010'
for i,status in enumerate(['esperando_cliente','presupuesto','reparacion','listo','entregado','espera_entrega']):
 data=t.order_data({'brand':'Lenovo' if i%2 else 'HP','model':'Equipo de prueba '+str(i+1),'serial':'TEST-'+str(i),'estimated_delivery':app.reception_now().date().isoformat(),'assigned_to':str(t.uid),'priority':'normal','request_key':'fixture-request-'+str(i)})
 result=t.request('/api/orders',data,cookie=cookie,csrf=csrf)
 if result['status']!=201:raise RuntimeError(result)
 oid=result['body']['id'];t.request('/api/order-status',{'id':str(oid),'status':status},cookie=cookie,csrf=csrf)
now=appointments.stamp(appointments.now());today=now[:10]
with app.connect() as c:
 for i in range(2):
  c.execute("INSERT INTO appointments(public_code,manage_token_hash,technician_id,customer_name,phone,device_type,service_code,description,starts_at,duration_minutes,privacy_consent,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",('DEMO-CITA-'+str(i),app.digest(secrets.token_urlsafe(32)),t.uid,'Cliente de prueba '+str(i+1),'0991234567','portatil','diagnostico','Diagnóstico de prueba',today+('T10:00:00-05:00' if i==0 else 'T14:00:00-05:00'),60,1,now,now))
 for i in range(3):
  cid=c.execute('INSERT INTO adi_conversations(token_hash,mode,created_at,updated_at) VALUES (?,?,?,?)',(app.digest(secrets.token_urlsafe(32)),'human' if i<2 else 'adi',now,now)).lastrowid
  c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'client','Consulta de prueba',?)",(cid,now))
app.os.environ['APP_URL']='http://127.0.0.1:8018'
print('Vista previa aislada preparada',flush=True)
app.ThreadingHTTPServer(('127.0.0.1',8018),app.Handler).serve_forever()
