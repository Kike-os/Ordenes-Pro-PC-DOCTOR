import io,json,sys,tempfile,unittest
from datetime import timedelta
from email.message import Message
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,appointments,adi,appointments_cron
app.os.environ.setdefault('LOGIN_CAPTCHA','off')  # Las pruebas inician sesión sin verificación salvo que la activen.

class AppointmentAndAdiTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.paths=patch.multiple(app,DATA=Path(self.temp.name),DB=Path(self.temp.name)/'test.sqlite3');self.paths.start();self.env=patch.dict(app.os.environ,{'APP_URL':'http://127.0.0.1:8010','SESSION_SECURE':'false'});self.env.start();app.migrate()
  with app.connect() as c:
   self.admin=c.execute('INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES (?,?,?,?,?,?)',('admin','a@example.invalid','Admin','hash','administrador',1)).lastrowid
   self.tech=c.execute('INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES (?,?,?,?,?,?)',('tech','t@example.invalid','Tech','hash','tecnico',1)).lastrowid
 def tearDown(self):self.env.stop();self.paths.stop();self.temp.cleanup()
 def post(self,path,data,cookie='',csrf=''):
  h=object.__new__(app.Handler);h.path=path;h.client_address=('127.0.0.1',4444);h.headers=Message();h.headers['Origin']='http://127.0.0.1:8010';h.headers['Content-Type']='application/json';h.headers['Cookie']=cookie;h.headers['X-CSRF-Token']=csrf;raw=json.dumps(data).encode();h.headers['Content-Length']=str(len(raw));h.rfile=io.BytesIO(raw);out={};h.reply=lambda status,body,*args,**kwargs:out.update(status=status,body=body,cookie=kwargs.get('cookie'));h.do_POST();return out
 def data(self,day,time='09:00',**extra):return {'name':'Reserva de Prueba','identification':'','phone':'0991234567','email':'prueba@example.invalid','device_type':'portatil','brand':'Acer','model':'Prueba','service':'diagnostico','description':'Revisión general','notes':'','date':day.isoformat(),'time':time,'privacy_consent':True,'communications_consent':False,'request_key':'req_test_appointment_00001',**extra}
 def day(self):
  day=appointments.now().date()+timedelta(days=1)
  while day.weekday()==6:day+=timedelta(days=1)
  return day
 def test_booking_is_persisted_without_order_and_request_is_idempotent(self):
  payload=self.data(self.day());first=self.post('/api/public/appointments',payload);self.assertEqual(first['status'],201,first);self.assertEqual(first['body']['status'],'confirmada');self.assertTrue(first['body']['manage_token'])
  again=self.post('/api/public/appointments',payload);self.assertEqual(again['status'],200);self.assertTrue(again['body']['duplicate'])
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM appointments').fetchone()[0],1);self.assertEqual(c.execute('SELECT count(*) FROM orders').fetchone()[0],0);self.assertEqual(c.execute('SELECT count(*) FROM clients').fetchone()[0],1)
 def test_conflicting_slot_is_rejected_and_cancellation_is_capability_protected(self):
  p=self.data(self.day());one=self.post('/api/public/appointments',p);self.assertEqual(one['status'],201);p2=self.data(self.day(),request_key='req_test_appointment_00002');two=self.post('/api/public/appointments',p2);self.assertEqual(two['status'],201);p3=self.data(self.day(),request_key='req_test_appointment_00003');three=self.post('/api/public/appointments',p3);self.assertEqual(three['status'],409)
  token=one['body']['manage_token'];h=object.__new__(app.Handler);h.path='/api/public/appointments/manage?code='+one['body']['code']+'&token='+token;h.client_address=('127.0.0.1',1);h.headers=Message();h.headers['Cookie']='';out={};h.reply=lambda status,body,*a,**k:out.update(status=status,body=body);h.do_GET();self.assertEqual(out['status'],200)
  cancelled=self.post('/api/public/appointments/manage',{'action':'cancel','code':one['body']['code'],'token':token});self.assertEqual(cancelled['status'],200)
  bad=self.post('/api/public/appointments/manage',{'action':'cancel','code':one['body']['code'],'token':'wrong'});self.assertEqual(bad['status'],404)
 def test_hours_services_holidays_and_slot_validation(self):
  day=self.day()
  with app.connect() as c:
   self.assertTrue(appointments.available_slots(c,day.isoformat(),'diagnostico'))
   c.execute('INSERT INTO appointment_holidays(day,label) VALUES (?,?)',(day.isoformat(),'Cierre'))
   self.assertEqual(appointments.available_slots(c,day.isoformat(),'diagnostico'),[])
   status,result=appointments.update_settings(c,{'services':[{'code':'diagnostico','duration_minutes':45,'active':True}]});self.assertEqual(status,200)
   self.assertEqual(appointments.services(c)[0]['duration_minutes'],45)
 def test_agenda_configuration_saves_hours_staff_and_keeps_services_active(self):
  with app.connect() as c:
   app.appointments.ensure_staff_hours(c,self.tech);cfg=appointments.settings(c)
   self.assertTrue(cfg['services'] and all(item['active']==1 for item in cfg['services']))
  with patch.object(app.Handler,'session',lambda handler,c:({'id':self.admin,'username':'admin','name':'Admin','email':'a@example.invalid','role':'administrador','csrf':'token'},'t')):
   payload={'hours':[dict(h,enabled=bool(h['enabled']),end_time='14:00' if h['weekday']==5 else h['end_time']) for h in cfg['hours']],'staff_hours':[dict(technician_id=h['technician_id'],weekday=h['weekday'],start_time=h['start_time'],end_time=h['end_time'],enabled=bool(h['enabled'])) for h in cfg['staff_hours']],'services':[dict(code=s['code'],duration_minutes=s['duration_minutes'],active=bool(s['active'])) for s in cfg['services']]}
   self.assertTrue(payload['staff_hours'])
   result=self.post('/api/appointments/config',payload,csrf='token')
   self.assertEqual(result['status'],200,result)
  with app.connect() as c:
   after=appointments.settings(c)
   self.assertEqual(next(h for h in after['hours'] if h['weekday']==5)['end_time'],'14:00')
   self.assertEqual(len(appointments.services(c)),len(cfg['services']))

 def test_chat_uses_http_only_identity_and_never_exposes_conversation_hash(self):
  result=self.post('/api/public/adi/message',{'message':'¿Qué servicios ofrecen?'});self.assertEqual(result['status'],201);self.assertIn('HttpOnly',result['cookie']);self.assertNotIn('token_hash',json.dumps(result['body']))
  cookie=result['cookie'].split(';')[0];h=object.__new__(app.Handler);h.path='/api/public/adi/messages?after=0';h.client_address=('127.0.0.1',1);h.headers=Message();h.headers['Cookie']=cookie;out={};h.reply=lambda status,body,*a,**k:out.update(status=status,body=body);h.do_GET();self.assertEqual(len(out['body']['messages']),2)
  with app.connect() as c:self.assertEqual(c.execute("SELECT mode FROM adi_conversations").fetchone()[0],'adi')
 def test_adi_fallback_uses_configured_data_and_never_invents_prices(self):
  with patch.dict(app.os.environ,{'OPENAI_API_KEY':''}),app.connect() as c:
   hours=adi.reply(c,'¿Cuál es el horario de atención?')
   self.assertIn(adi.schedule_text(appointments.settings(c)['hours']),hours)
   price=adi.reply(c,'¿Cuánto cuesta formatear mi laptop?')
   self.assertIn('revisión técnica',price);self.assertNotRegex(price,r'\$|\bUSD\b|[0-9]+ ?d[oó]lares')
   self.assertIn('/citas',adi.reply(c,'Quiero agendar una cita'))
   self.assertIn('Solicitar un asesor',adi.reply(c,'quiero hablar con una persona'))
   self.assertIn('número de orden',adi.reply(c,'¿cómo va mi equipo? estado de mi orden'))
   self.assertIn('No encuentro una orden',adi.reply(c,'orden PCD-20260101-0001 cédula 0100000017'))
   self.assertIn(app.corporate.settings()['whatsapp'],adi.reply(c,'¿Dónde están ubicados?'))
   self.assertNotIn('Horario de atención',adi.reply(c,'ahora necesito una opcion'))
  self.assertEqual(adi.schedule_text([{'weekday':0,'start_time':'09:00','end_time':'17:00','enabled':1},{'weekday':1,'start_time':'09:00','end_time':'17:00','enabled':1},{'weekday':2,'start_time':'09:00','end_time':'13:00','enabled':1},{'weekday':3,'start_time':'09:00','end_time':'13:00','enabled':0}]),'lunes a martes de 09:00 a 17:00; miércoles de 09:00 a 13:00')

 def test_admin_answers_are_database_backed(self):
  with app.connect() as c:
   answer=adi.admin_answer(c,'¿Cuántas órdenes tengo en espera?');self.assertIn('0 orden',answer)
 def test_confirmation_notification_requires_consent_and_is_recorded_after_send(self):
  payload=self.data(self.day(),communications_consent=True);result=self.post('/api/public/appointments',payload);self.assertEqual(result['status'],201)
  with app.connect() as c:self.assertEqual(c.execute('SELECT result FROM appointment_notifications').fetchone()[0],'pending')
  with patch.object(appointments_cron,'DB',Path(self.temp.name)/'test.sqlite3'),patch.dict(app.os.environ,{'SMTP_HOST':'smtp.example.invalid','SMTP_FROM':'service@example.invalid'}),patch.object(appointments_cron,'send') as sender:
   appointments_cron.run();sender.assert_called_once()
  with app.connect() as c:self.assertEqual(c.execute('SELECT result FROM appointment_notifications').fetchone()[0],'sent')
 def test_login_lockout_stops_at_five_and_does_not_extend_block(self):
  key='login-user:'+app.digest('persona');
  with app.connect() as c:
   for _ in range(5):app.limited(c,key,4,900)
   row=c.execute('SELECT expires FROM attempts WHERE bucket=?',(key,)).fetchone();original=row['expires'];self.assertTrue(app.limit_reached(c,key));app.limited(c,key,4,900);self.assertEqual(c.execute('SELECT expires FROM attempts WHERE bucket=?',(key,)).fetchone()['expires'],original)
