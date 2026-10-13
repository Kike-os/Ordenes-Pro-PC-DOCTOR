import unittest
from datetime import date,datetime
from unittest.mock import patch,MagicMock
import test_app,app,maintenance,maintenance_cron,client_registry
app.os.environ.setdefault('LOGIN_CAPTCHA','off')  # Las pruebas inician sesión sin verificación salvo que la activen.

class OperationsTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data
    def create(self):
        cookie,csrf=self.login();data=self.order_data();result=self.request('/api/orders',data,cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],201,result);return cookie,csrf,data,result['body']
    def test_clients_reused_and_historical_snapshot(self):
        cookie,csrf=self.login();data=self.order_data();cid=data['client_id']
        with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM orders').fetchone()[0],0)
        duplicate=self.request('/api/client-registry',dict(data,name=data['client']),cookie=cookie,csrf=csrf)
        self.assertEqual(duplicate['status'],409);self.assertEqual(duplicate['body']['existing_id'],int(cid))
        first=self.request('/api/orders',data,cookie=cookie,csrf=csrf)['body']
        edited=dict(data,id=cid,name='Nombre actualizado',phone='0997654321')
        self.assertEqual(self.request('/api/client-registry',edited,cookie=cookie,csrf=csrf)['status'],200)
        second=self.request('/api/orders',dict(data,client='NO CONFIAR EN ESTE VALOR'),cookie=cookie,csrf=csrf)['body']
        one=self.request('/api/orders/'+str(first['id']),cookie=cookie)['body']['order'];two=self.request('/api/orders/'+str(second['id']),cookie=cookie)['body']['order']
        self.assertEqual(one['client'],'Cliente ficticio');self.assertEqual(two['client'],'Nombre actualizado');self.assertEqual(one['client_id'],two['client_id'])
        self.assertEqual(self.request('/api/clients/'+cid,cookie=cookie)['body']['client']['phone'],'0997654321')
        self.assertEqual(self.request('/api/orders',dict(data,client_id='999'),cookie=cookie,csrf=csrf)['status'],400)
        with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM clients').fetchone()[0],1)
    def test_passport_and_company_validation(self):
        data=self.order_data();data.update(name='Empresa prueba',client_type='empresa')
        fields,errors=client_registry.validate(data);self.assertIn('document_type',errors)
        fields,errors=client_registry.validate(dict(data,client_type='natural',document_type='pasaporte',identification='A-0001'))
        self.assertEqual(errors,{});self.assertEqual(fields['identification'],'A-0001')
    def test_delivery_calendar_reopening_idempotence(self):
        self.assertEqual(maintenance.six_months(date(2026,8,31)),date(2027,2,28));self.assertEqual(maintenance.six_months(date(2027,8,31)),date(2028,2,29))
        cookie,csrf,data,order=self.create();oid=order['id'];fixed=datetime.fromisoformat('2026-10-09T23:59:59-05:00')
        with patch.object(app,'reception_now',return_value=fixed):
            for _ in range(2):self.assertEqual(self.request('/api/order-status',{'id':str(oid),'status':'entregado'},cookie=cookie,csrf=csrf)['status'],200)
        row=self.request('/api/maintenance',cookie=cookie)['body']['rows'][0];self.assertEqual(row['due_date'],'2027-04-09');self.assertEqual(row['generation'],1)
        self.request('/api/order-status',{'id':str(oid),'status':'reparacion'},cookie=cookie,csrf=csrf)
        self.assertEqual(self.request('/api/maintenance',cookie=cookie)['body']['rows'][0]['state'],'cancelled')
        self.request('/api/order-status',{'id':str(oid),'status':'entregado'},cookie=cookie,csrf=csrf)
        rows=self.request('/api/maintenance',cookie=cookie)['body']['rows'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['generation'],3)
        for suffix in ['card.pdf','thermal.pdf']:
            result=self.request('/api/maintenance/'+str(row['id'])+'/'+suffix,cookie=cookie);self.assertEqual(result['status'],200,result);self.assertTrue(result['body'].startswith(b'%PDF'))
        unchanged=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];self.assertEqual(unchanged['code'],order['code'])
    def test_due_cron_consent_provider_result_and_optout(self):
        cookie,csrf,data,order=self.create();self.request('/api/order-status',{'id':str(order['id']),'status':'entregado'},cookie=cookie,csrf=csrf)
        row=self.request('/api/maintenance',cookie=cookie)['body']['rows'][0];mid=row['id']
        self.request('/api/maintenance/'+str(mid),{'action':'reschedule','due_date':'2020-01-01'},cookie=cookie,csrf=csrf)
        with app.connect() as c:c.execute("UPDATE clients SET email='synthetic@example.invalid'")
        env={'MAINTENANCE_EMAIL_ENABLED':'true','SMTP_HOST':'smtp.example.invalid','SMTP_FROM':'test@example.invalid'}
        with patch.dict(app.os.environ,env),patch.object(maintenance_cron.smtplib,'SMTP') as provider:
            smtp=provider.return_value.__enter__.return_value;smtp.send_message.return_value={}
            maintenance_cron.run(True);provider.assert_not_called()
            self.request('/api/maintenance/'+str(mid),{'action':'consent','consent':'accepted'},cookie=cookie,csrf=csrf)
            result=maintenance_cron.run(True);self.assertEqual(result['accepted'],1);maintenance_cron.run(True);smtp.send_message.assert_called_once()
        with app.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM maintenance_notifications WHERE channel='admin'").fetchone()[0],1)
        self.assertEqual(self.request('/maintenance-preferences/'+row['unsubscribe_token'])['status'],200)
        self.assertEqual(self.request('/maintenance-preferences/'+row['unsubscribe_token'],{})['status'],200)
        self.assertEqual(self.request('/api/maintenance',cookie=cookie)['body']['rows'][0]['consent'],'declined')
    def test_dashboard_attention_search_activity_access(self):
        cookie,csrf,data,order=self.create();oid=order['id']
        self.request('/api/order-status',{'id':str(oid),'status':'esperando_cliente'},cookie=cookie,csrf=csrf)
        dash=self.request('/api/dashboard',cookie=cookie)['body'];self.assertEqual(dash['counts']['esperando_cliente'],1);self.assertEqual(dash['attention'][0]['id'],oid);self.assertEqual(dash['activity'][0]['status_label'],'Esperando respuesta del cliente')
        from urllib.parse import quote
        for term in [data['client'],data['phone'],data['identification'],order['code']]:self.assertEqual(len(self.request('/api/search?q='+quote(term),cookie=cookie)['body']['rows']),1)
        for path in ['/api/maintenance','/api/search?q=01','/api/activity','/api/clients/1']:self.assertEqual(self.request(path)['status'],401)
    def test_customer_documents_exclude_internal_notes(self):
        cookie,csrf,data,order=self.create();oid=order['id']
        with app.connect() as c:c.execute("UPDATE orders SET internal_notes='PRIVADO-INTERNO-XYZ' WHERE id=?",(oid,))
        import zlib,re
        for suffix in ['receipt.pdf','thermal.pdf','label.pdf']:
            result=self.request('/api/orders/'+str(oid)+'/'+suffix,cookie=cookie);self.assertEqual(result['status'],200,result)
            streams=[]
            for raw in re.findall(rb'stream\n(.*?)\nendstream',result['body'],re.S):
                try:streams.append(zlib.decompress(raw))
                except zlib.error:streams.append(raw)
            self.assertNotIn(b'PRIVADO-INTERNO-XYZ',b''.join(streams))
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/label.pdf?size=custom&width=2&height=50',cookie=cookie)['status'],400)

    def test_phone_validation_for_client_and_appointment(self):
        import reception,appointments
        for value in ['0991234567','02 234 5678','+593 99 123 4567','59322345678']:
            self.assertTrue(reception.valid_ecuador_phone(value),value)
        for value in ['123','099123','0000000000','+5930991234567','letters','+1 555 123 4567']:
            self.assertFalse(reception.valid_ecuador_phone(value),value)
        cookie,csrf=self.login();data=self.order_data()
        result=self.request('/api/client-registry',dict(data,name=data['client'],identification='A-PHONE',document_type='pasaporte',phone='1234567'),cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],400);self.assertIn('phone',result['body']['fields'])
        self.assertEqual(self.request('/api/clients',{'name':'Prueba','phone':'1234567'},cookie=cookie,csrf=csrf)['status'],400)
        with app.connect() as c:
            _,errors,_=appointments.validate_booking({'name':'Prueba','phone':'1234567'},c)
            self.assertIn('phone',errors)

    def test_company_passport_and_duplicate_keep_existing_profile(self):
        cookie,csrf=self.login();base=self.order_data()
        company=dict(base,name='Empresa ficticia',client_type='empresa',document_type='ruc',identification='1790016919001',trade_name='Taller de prueba')
        result=self.request('/api/client-registry',company,cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],201,result)
        duplicate=self.request('/api/client-registry',dict(company,name='No sobrescribir'),cookie=cookie,csrf=csrf)
        self.assertEqual(duplicate['status'],409)
        self.assertEqual(self.request('/api/clients/'+str(result['body']['id']),cookie=cookie)['body']['client']['name'],'Empresa ficticia')
        passport=dict(base,name='Visitante ficticio',client_type='natural',document_type='pasaporte',identification='p-test-001')
        result=self.request('/api/client-registry',passport,cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],201,result)
        self.assertEqual(self.request('/api/clients/'+str(result['body']['id']),cookie=cookie)['body']['client']['identification'],'P-TEST-001')

    def test_dashboard_assistance_counts_and_permissions(self):
        cookie,csrf=self.login();now=app.reception_now().isoformat()
        with app.connect() as c:
            for i,(mode,seen,last) in enumerate([('human','','client'),('human',now,'operator'),('adi','','client'),('closed','','client')]):
                cid=c.execute('INSERT INTO adi_conversations(token_hash,mode,created_at,updated_at,last_seen_admin) VALUES (?,?,?,?,?)',('test-conv-'+str(i),mode,now,now,seen)).lastrowid
                c.execute('INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,?,?,?)',(cid,last,'Prueba',now))
        dash=self.request('/api/dashboard',cookie=cookie)['body']
        # Cada conversación abierta cuenta en una sola categoría: una espera respuesta humana, otra está en curso con un asesor y otra es nueva con ADI.
        self.assertEqual({key:dash['assistance'][key] for key in ('new_conversations','waiting','transferred','total')},{'new_conversations':1,'waiting':1,'transferred':1,'total':3})
        self.assertEqual([(item['kind'],item['source']) for item in dash['assistance']['pending']],[('waiting','Transferida por ADI'),('new_conversations','Chat con ADI')])
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico'")
        self.assertIsNone(self.request('/api/dashboard',cookie=cookie)['body']['assistance'])
        self.assertEqual(self.request('/api/adi/admin',cookie=cookie)['status'],403)

    def test_ready_delivery_without_date_remains_visible(self):
        cookie,csrf,data,order=self.create()
        self.request('/api/order-status',{'id':str(order['id']),'status':'listo'},cookie=cookie,csrf=csrf)
        rows=self.request('/api/dashboard',cookie=cookie)['body']['deliveries']
        self.assertEqual(rows[0]['id'],order['id'])
        for key in ['client','brand','model','status','estimated_delivery']:
            self.assertIn(key,rows[0])
