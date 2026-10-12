"""Recordatorios de mantenimiento por etapas y respuestas del cliente por enlace seguro (correo simulado)."""
import io,unittest
from datetime import timedelta
from email.message import Message
from unittest.mock import patch
from urllib.parse import urlencode
import test_app
import app,mail_pro,maintenance_reminders
app.os.environ.setdefault('LOGIN_CAPTCHA','off')

CONFIG={'imap_host':'imap.example.invalid','imap_port':993,'smtp_host':'smtp.example.invalid','smtp_port':465,'username':'taller@example.invalid','password':'x'}


class MaintenanceReminderTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data

    def form(self,token,fields):
        handler=object.__new__(app.Handler);handler.path='/mantenimiento/'+token;handler.client_address=('203.0.113.9',40000);handler.headers=Message();handler.headers['Content-Type']='application/x-www-form-urlencoded'
        raw=urlencode(fields).encode();handler.headers['Content-Length']=str(len(raw));handler.rfile=io.BytesIO(raw);result={}
        handler.reply=lambda status,body,content_type=None,cookie=None,filename=None:result.update(status=status,body=body);handler.do_POST();return result

    def delivered(self,cookie,csrf,days,consent='accepted',email='cliente@example.invalid'):
        """Orden entregada con su mantenimiento previsto a «days» días (datos ficticios)."""
        oid=self.request('/api/orders',self.order_data({'email':email,'brand':'HP','model':'ProBook','request_key':'maint-reminder-%06d'%abs(hash((days,consent,email))%999999)}),cookie=cookie,csrf=csrf)['body']['id']
        self.assertEqual(self.request('/api/order-status',{'id':str(oid),'status':'entregado'},cookie=cookie,csrf=csrf)['status'],200)
        due=(app.reception_now().date()+timedelta(days=days)).isoformat()
        with app.connect() as c:
            c.execute('UPDATE maintenance SET due_date=?,consent=? WHERE order_id=?',(due,consent,oid));c.execute("UPDATE clients SET email=? WHERE id=(SELECT client_id FROM devices WHERE id=(SELECT device_id FROM orders WHERE id=?))",(email,oid))
            row=c.execute('SELECT id,unsubscribe_token FROM maintenance WHERE order_id=?',(oid,)).fetchone()
        return oid,row['id'],row['unsubscribe_token']

    def test_stages(self):
        self.assertEqual([maintenance_reminders.stage_for(d) for d in (45,30,29,15,8,7,4,3,1,0,-2,-4,None)],[None,30,30,15,15,7,7,3,3,0,0,None,None])

    def test_reminders_respect_consent_stages_and_never_repeat(self):
        cookie,csrf=self.login();sent=[]
        oid,mid,token=self.delivered(cookie,csrf,7)
        deliver=lambda config,message,recipients:sent.append((message,recipients))
        with patch.object(mail_pro,'configured',return_value=True),patch.object(mail_pro,'settings',return_value=CONFIG),patch.object(mail_pro,'deliver',side_effect=deliver):
            # Apagados por defecto: no se envía nada y no se puede forzar.
            state=self.request('/api/maintenance',cookie=cookie)['body']['reminders'];self.assertFalse(state['enabled']);self.assertEqual(state['pending_total'],1)
            self.assertEqual(self.request('/api/maintenance/reminders',{'action':'run'},cookie=cookie,csrf=csrf)['status'],409)
            self.request('/api/dashboard',cookie=cookie);self.assertEqual(sent,[])
            self.assertEqual(self.request('/api/maintenance/reminders',{'enabled':True},cookie=cookie,csrf=csrf)['status'],200)
            run=self.request('/api/maintenance/reminders',{'action':'run'},cookie=cookie,csrf=csrf)['body']
            self.assertEqual((run['summary']['sent'],run['reminders']['pending_total']),(1,0));self.assertEqual(len(sent),1)
            message,recipients=sent[0];text=message.get_body(preferencelist=('plain',)).get_content()
            self.assertEqual(recipients,['cliente@example.invalid']);self.assertIn('/mantenimiento/'+token,text);self.assertIn('dentro de 7 días',text)
            # Misma etapa: no se repite. Al pasar a la siguiente etapa se envía una sola vez más.
            self.assertEqual(self.request('/api/maintenance/reminders',{'action':'run'},cookie=cookie,csrf=csrf)['body']['summary']['sent'],0)
            with app.connect() as c:c.execute('UPDATE maintenance SET due_date=? WHERE id=?',((app.reception_now().date()+timedelta(days=3)).isoformat(),mid))
            self.assertEqual(self.request('/api/maintenance/reminders',{'action':'run'},cookie=cookie,csrf=csrf)['body']['summary']['sent'],1);self.assertEqual(len(sent),2)
        with app.connect() as c:self.assertEqual([r[0] for r in c.execute('SELECT stage FROM maintenance_reminders WHERE maintenance_id=? ORDER BY id',(mid,))],[7,3])
        self.assertEqual(self.request('/api/maintenance/reminders',{'enabled':True})['status'],401)

    def test_client_page_confirm_reschedule_and_decline(self):
        cookie,csrf=self.login();oid,mid,token=self.delivered(cookie,csrf,15)
        page=self.request('/mantenimiento/'+token);self.assertEqual(page['status'],200)
        for expected in ('Confirmar esta fecha','Solicitar otro horario','No deseo recibir recordatorios','HP ProBook'):self.assertIn(expected,page['body'])
        for private in ('0100000017','0991234567','cliente@example.invalid','Cliente ficticio'):self.assertNotIn(private,page['body'])
        self.assertEqual(self.request('/mantenimiento/'+'x'*43)['status'],404);self.assertEqual(self.form(token,{'action':'borrar'})['status'],400)
        self.assertIn('Registramos su confirmación',self.form(token,{'action':'confirm'})['body']);self.form(token,{'action':'confirm'})
        self.assertIn('Recibimos su solicitud',self.form(token,{'action':'reschedule','note':'Prefiero el sábado por la mañana'})['body'])
        state=self.request('/api/maintenance',cookie=cookie)['body']['reminders']
        self.assertEqual([(r['action'],r['note']) for r in state['responses']],[('reschedule','Prefiero el sábado por la mañana'),('confirm','')])
        self.assertEqual(self.request('/api/maintenance/reminders',{'action':'handled','id':str(state['responses'][0]['id'])},cookie=cookie,csrf=csrf)['body']['reminders']['responses'][0]['action'],'confirm')
        # Darse de baja retira el consentimiento: deja de haber recordatorios pendientes para ese cliente.
        self.assertIn('no recibirá más recordatorios',self.form(token,{'action':'decline'})['body'])
        with app.connect() as c:self.assertEqual(c.execute('SELECT consent FROM maintenance WHERE id=?',(mid,)).fetchone()[0],'declined')
        self.assertEqual(self.request('/api/maintenance',cookie=cookie)['body']['reminders']['pending_total'],0)
        history=self.request('/api/orders/%d'%oid,cookie=cookie)['body']['order'];self.assertIn('Respuesta del cliente por enlace seguro',str(history))


if __name__=='__main__':
    unittest.main()
