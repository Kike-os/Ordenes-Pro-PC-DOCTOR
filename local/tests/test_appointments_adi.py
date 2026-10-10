import io,json,sys,tempfile,unittest
from datetime import timedelta
from email.message import Message
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,appointments,adi,appointments_cron

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
 def test_chat_uses_http_only_identity_and_never_exposes_conversation_hash(self):
  result=self.post('/api/public/adi/message',{'message':'¿Qué servicios ofrecen?'});self.assertEqual(result['status'],201);self.assertIn('HttpOnly',result['cookie']);self.assertNotIn('token_hash',json.dumps(result['body']))
  cookie=result['cookie'].split(';')[0];h=object.__new__(app.Handler);h.path='/api/public/adi/messages?after=0';h.client_address=('127.0.0.1',1);h.headers=Message();h.headers['Cookie']=cookie;out={};h.reply=lambda status,body,*a,**k:out.update(status=status,body=body);h.do_GET();self.assertEqual(len(out['body']['messages']),2)
  with app.connect() as c:self.assertEqual(c.execute("SELECT mode FROM adi_conversations").fetchone()[0],'adi')
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
