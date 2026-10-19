"""Licencias Pro — Control de Vigencia y Renovaciones: registro, cifrado, inventario, entrega manual, vigencia, renovaciones, avisos y
correos de renovación, «Mis licencias» del cliente y permisos. Datos ficticios."""
import base64
import concurrent.futures
import io
import sqlite3
import unittest
from datetime import date,timedelta
from email.message import Message
from unittest.mock import patch
from urllib.parse import urlencode
import test_app
import app,licenses,license_mail
app.os.environ.setdefault('LOGIN_CAPTCHA','off')
SERIAL='KASP-FICT-1234-ABCD-9999'
PNG=base64.b64encode(b'\x89PNG\r\n\x1a\n'+b'\x00'*64).decode()
PDF=base64.b64encode(b'%PDF-1.4 comprobante ficticio %%EOF').decode()
MAIL={'imap_host':'i','imap_port':993,'smtp_host':'s','smtp_port':465,'username':'licencias@example.invalid','password':'x'}


class LicenseProTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request
    login=test_app.SecurityTests.login
    order_data=test_app.SecurityTests.order_data

    def form(self,path,fields):
        handler=object.__new__(app.Handler);handler.path=path;handler.client_address=('127.0.0.1',5555);handler.headers=Message();body=urlencode(fields).encode()
        handler.headers['Content-Type']='application/x-www-form-urlencoded';handler.headers['Content-Length']=str(len(body));handler.headers['Origin']='http://127.0.0.1:8010';handler.rfile=io.BytesIO(body);result={}
        handler.reply=lambda status,content,content_type='application/json; charset=utf-8',cookie=None,filename=None:result.update(status=status,body=content)
        handler.do_POST();return result

    def admin(self):
        self.cookie,self.csrf=self.login()
        self.post=lambda path,**body:self.request(path,body,cookie=self.cookie,csrf=self.csrf)
        self.get=lambda path:self.request(path,cookie=self.cookie)

    def today(self):return app.reception_now().date()

    def new_product(self,name='ESET NOD32 Antivirus ficticio',line='antivirus',duration='anual',validity='activacion',key=SERIAL,**extra):
        made=self.post('/api/licenses/new',**dict(dict(name=name,brand='ESET',line=line,model='perpetua' if duration=='perpetua' else 'suscripcion',edition='2026',description='Antivirus de prueba',devices='1',
                       duration=duration,validity_mode=validity,price='30',purchase_price='18,50',supplier='Mayorista ficticio',key=key),**extra))
        self.assertEqual(made['status'],201,made['body']);return made['body']

    def order_with_quote(self,product,quantity=1,key='0001',extra_cents=0):
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'license-order-request-'+key}),cookie=self.cookie,csrf=self.csrf)['body']
        quote=self.post('/api/orders/%d/quote'%order['id'])['body']['id']
        items=[{'catalog_id':product,'description':'Licencia ficticia','category':'seguridad','quantity':quantity,'unit_cents':3000,'taxed':True}]
        if extra_cents:items.append({'description':'Servicio ficticio','category':'servicio','quantity':1,'unit_cents':extra_cents,'taxed':True})
        self.assertEqual(self.post('/api/quotes/%d'%quote,action='save',items=items)['status'],200)
        return order['id'],quote

    def approve(self,quote):
        self.assertEqual(self.post('/api/quotes/%d'%quote,action='send')['status'],200)
        with app.connect() as c:ids=[str(r[0]) for r in c.execute('SELECT id FROM quote_items WHERE quote_id=?',(quote,))]
        return self.post('/api/quotes/%d'%quote,action='decide',approved=','.join(ids),note='Aprobó por teléfono (ficticio)')

    def unit(self,unit_id):
        with app.connect() as c:return dict(c.execute('SELECT * FROM license_units WHERE id=?',(unit_id,)).fetchone())

    def client_id(self):
        with app.connect() as c:
            row=c.execute("SELECT id FROM clients WHERE identification='0100000017'").fetchone()
            if row:return row[0]
        self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'license-client-0000'}),cookie=self.cookie,csrf=self.csrf)
        return self.client_id()

    def test_new_license_creates_product_with_logo_receipt_and_optional_credentials(self):
        self.admin()
        made=self.new_product(logo=PNG,receipt=PDF,receipt_name='factura-001.pdf',invoice='FAC-001',license_code='ESET-ID-778',download_url='https://www.eset.com/descargas',
                              instructions='1. Descargar.\n2. Instalar.',purchased_at=self.today().isoformat())
        product=next(p for p in self.get('/api/licenses')['body']['products'] if p['id']==made['product_id'])
        self.assertEqual((product['category'],product['line'],product['managed'],product['stock']['disponible']),('seguridad','antivirus',True,1));self.assertTrue(product['image'])
        self.assertEqual(self.get('/api/catalog/%d/image'%made['product_id'])['status'],200)
        unit=self.unit(made['unit_id']);self.assertEqual(licenses.unseal(unit['secret']),{'key':SERIAL,'license_code':'ESET-ID-778'})
        self.assertEqual((unit['download_url'],unit['instructions'],unit['expires_at']),('https://www.eset.com/descargas','1. Descargar.\n2. Instalar.',''))
        receipt=self.get('/api/licenses/batches/%d/receipt'%unit['batch_id']);self.assertEqual(receipt['status'],200);self.assertTrue(receipt['body'].startswith(b'%PDF'))
        self.new_product(name='Microsoft 365 Familia ficticio',line='microsoft',key='',username='cuenta1@example.invalid',password='Clave Ficticia 1')
        bad=self.post('/api/licenses/new',name='Producto sin clave',line='otros',duration='anual',price='10');self.assertEqual(bad['status'],400)
        with app.connect() as c:self.assertIsNone(c.execute("SELECT 1 FROM catalog_items WHERE name='Producto sin clave'").fetchone())
        self.assertEqual(self.post('/api/licenses/new',name='ESET NOD32 Antivirus ficticio',line='antivirus',duration='anual',price='30',key='OTRA-CLAVE-0001')['status'],400)

    def test_credentials_are_encrypted_hidden_and_duplicates_rejected(self):
        self.admin();made=self.new_product()
        for variant in (SERIAL.lower(),SERIAL.replace('-',' '),' '+SERIAL+' '):
            again=self.post('/api/licenses/units',product_id=str(made['product_id']),key=variant);self.assertEqual(again['status'],409,variant)
        with app.connect() as c:
            row=c.execute('SELECT secret FROM license_units').fetchone();dump='\n'.join(c.iterdump())
        self.assertNotIn(SERIAL,dump);self.assertNotIn('1234-ABCD',dump)
        tampered=row['secret'][:-3]+('AAA' if row['secret'][-3:]!='AAA' else 'BBB')
        with self.assertRaises(licenses.LicenseError):licenses.unseal(tampered)
        listing=self.get('/api/licenses/units?q='+SERIAL.lower())['body'];self.assertEqual(len(listing['rows']),1);self.assertNotIn(SERIAL,str(listing))
        self.assertNotIn(SERIAL,str(self.get('/api/licenses/history')['body']))
        shown=self.post('/api/licenses/units/%d'%made['unit_id'],action='reveal')['body']['credentials']
        self.assertEqual(shown,[{'key':'key','label':'Clave de producto o serial','value':SERIAL}])
        shared=self.new_product(name='Antivirus multiusuario ficticio',key='SHARED-KEY-0001',shared_seats='3')
        for n in range(2):self.assertEqual(self.post('/api/licenses/units',product_id=str(shared['product_id']),key='SHARED-KEY-0001')['status'],201)
        self.assertEqual(self.post('/api/licenses/units',product_id=str(shared['product_id']),key='SHARED-KEY-0001')['status'],409)

    def test_bulk_stock_is_all_or_nothing_and_does_not_overwrite(self):
        self.admin();made=self.new_product();pid=str(made['product_id'])
        bad=self.post('/api/licenses/units/bulk',product_id=pid,lines='SERIAL-AAAA-0001\nSERIAL-AAAA-0002\nSERIAL-AAAA-0001')
        self.assertEqual(bad['status'],400);self.assertIn('Línea 3',bad['body']['error'])
        dup=self.post('/api/licenses/units/bulk',product_id=pid,lines='SERIAL-AAAA-0009\n'+SERIAL);self.assertEqual(dup['status'],409)
        good=self.post('/api/licenses/units/bulk',product_id=pid,lines='SERIAL-AAAA-0001\n\nSERIAL-AAAA-0002;CODIGO-2\nSERIAL-AAAA-0003;cuenta@example.invalid;Clave 3',unit_cost='15',receipt=PDF)
        self.assertEqual((good['status'],good['body']['count']),(201,3))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM license_units').fetchone()[0],4)
            self.assertEqual(licenses.unseal(c.execute('SELECT secret FROM license_units WHERE id=?',(made['unit_id'],)).fetchone()[0]),{'key':SERIAL})
            last=licenses.unseal(c.execute('SELECT secret FROM license_units ORDER BY id DESC LIMIT 1').fetchone()[0])
        self.assertEqual(last,{'key':'SERIAL-AAAA-0003','username':'cuenta@example.invalid','password':'Clave 3'})

    def test_validity_modes_calendar_months_and_perpetual(self):
        self.assertEqual(licenses.add_months(date(2026,10,19),12),date(2027,10,19))
        self.assertEqual(licenses.add_months(date(2024,1,31),1),date(2024,2,29));self.assertEqual(licenses.add_months(date(2025,1,31),1),date(2025,2,28))
        self.assertEqual(licenses.add_months(date(2026,3,1),12)-date(2026,3,1),timedelta(days=365))
        self.assertEqual(licenses.add_months(date(2027,3,1),12)-date(2027,3,1),timedelta(days=366))
        self.admin();today=self.today()
        act=self.new_product(name='Por activación',key='ACT-KEY-00001');self.assertEqual(self.unit(act['unit_id'])['expires_at'],'')
        buy=self.new_product(name='Por compra',key='BUY-KEY-00001',validity='compra',purchased_at=(today-timedelta(days=10)).isoformat())
        self.assertEqual(self.unit(buy['unit_id'])['expires_at'],licenses.add_months(today-timedelta(days=10),12).isoformat())
        self.assertEqual(self.post('/api/licenses/new',name='Fija sin fecha',line='otros',duration='anual',validity_mode='fija',price='9',key='FIX-KEY-00001')['status'],400)
        fixed=self.new_product(name='Fecha fija',key='FIX-KEY-00002',validity='fija',expires_at='2028-03-31');self.assertEqual(self.unit(fixed['unit_id'])['expires_at'],'2028-03-31')
        perpetual=self.new_product(name='Perpetua',key='PERP-KEY-0001',duration='perpetua',activated_at=today.isoformat())
        self.assertEqual(self.unit(perpetual['unit_id'])['expires_at'],'')
        self.assertEqual(licenses.state_of({'status':'entregada','expires_at':(today+timedelta(days=10)).isoformat(),'activated':1,'renewed_to':None},today),('por_vencer',10))
        self.assertEqual(licenses.state_of({'status':'entregada','expires_at':'','activated':0,'renewed_to':None},today)[0],'pendiente_activacion')
        self.assertEqual(licenses.state_of({'status':'entregada','expires_at':(today-timedelta(days=1)).isoformat(),'activated':1,'renewed_to':None},today)[0],'vencida')
        # Un vencimiento de compra ya pasado deja la licencia vencida en inventario: no se vende.
        old=self.new_product(name='Comprada hace años',key='OLD-KEY-00001',validity='compra',purchased_at='2020-01-01');self.assertEqual(self.unit(old['unit_id'])['status'],'vencida')

    def test_draft_does_not_reserve_and_approval_reserves_without_revealing(self):
        self.admin();made=self.new_product(key='SERIAL-RESV-0000');pid=made['product_id']
        self.post('/api/licenses/units',product_id=str(pid),key='SERIAL-RESV-0001')
        order,quote=self.order_with_quote(pid,quantity=3)
        with app.connect() as c:self.assertEqual([r[0] for r in c.execute("SELECT status FROM license_units ORDER BY id")],['disponible','disponible'])
        self.assertEqual(self.approve(quote)['status'],200)
        with app.connect() as c:self.assertEqual([r[0] for r in c.execute("SELECT status FROM license_units ORDER BY id")],['reservada','reservada'])
        waiting=self.get('/api/licenses/deliveries')['body']['waiting'];self.assertEqual(waiting[0]['pending'][0]['missing'],1);self.assertNotIn('SERIAL-RESV',str(waiting))
        self.post('/api/licenses/units',product_id=str(pid),key='SERIAL-RESV-0099')
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM license_units WHERE status='reservada'").fetchone()[0],3)

    def test_manual_delivery_from_order_and_client_licenses(self):
        self.admin();made=self.new_product()
        order,quote=self.order_with_quote(made['product_id'],extra_cents=2000);self.approve(quote)
        need=self.post('/api/licenses/deliver',order_id=str(order));self.assertEqual(need['status'],409);self.assertIn('accept_balance',need['body']['fields'])
        sent=[]
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_institutional',side_effect=lambda *a,**k:sent.append((a,k))):
            done=self.post('/api/licenses/deliver',order_id=str(order),accept_balance=True,send_mail=True)
        self.assertEqual(done['status'],200,done['body']);self.assertEqual(done['body']['mail'],'sent');self.assertNotIn(SERIAL,str(sent))
        unit=self.unit(made['unit_id']);self.assertEqual((unit['status'],unit['client_id'],unit['order_id']),('entregada',self.client_id(),order))
        self.assertEqual(self.post('/api/licenses/deliver',order_id=str(order),accept_balance=True)['status'],409)
        with app.connect() as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE license_units SET status='disponible' WHERE id=?",(made['unit_id'],))
        mine=self.get('/api/clients/%d/licenses'%self.client_id())['body']['rows']
        self.assertEqual([(r['code'],r['state']) for r in mine],[(unit['code'],'pendiente_activacion')]);self.assertTrue(mine[0]['order_code']);self.assertNotIn(SERIAL,str(mine))
        day=(self.today()-timedelta(days=3)).isoformat()
        act=self.post('/api/licenses/units/%d'%made['unit_id'],action='activate',activated_at=day);self.assertEqual(act['body']['expires_at'],licenses.add_months(date.fromisoformat(day),12).isoformat())
        self.assertEqual(self.post('/api/licenses/units/%d'%made['unit_id'],action='activate',activated_at=(self.today()+timedelta(days=2)).isoformat())['status'],400)
        self.assertEqual(self.get('/api/clients/%d/licenses'%self.client_id())['body']['rows'][0]['state'],'activa')
        self.assertIn('activada',[r['event'] for r in self.get('/api/licenses/history?unit=%d'%made['unit_id'])['body']['rows']])

    def test_direct_sale_to_client_return_and_public_delivery(self):
        self.admin();made=self.new_product();order,_=self.order_with_quote(made['product_id'])
        client=self.client_id()
        with app.connect() as c:
            other=c.execute("INSERT INTO clients(name,phone,identification) VALUES ('Otra Persona Ficticia','0990000001','1710034065')").lastrowid
            code=c.execute('SELECT code FROM orders WHERE id=?',(order,)).fetchone()[0]
        self.assertEqual(self.post('/api/licenses/deliver',client_id=str(other),product_id=str(made['product_id']),order_code=code)['status'],409)
        self.assertEqual(self.post('/api/licenses/deliver',product_id=str(made['product_id']))['status'],400)
        done=self.post('/api/licenses/deliver',client_id=str(client),product_id=str(made['product_id']),order_code=code,notes='Venta en mostrador');self.assertEqual(done['status'],200,done['body'])
        self.assertEqual(self.post('/api/licenses/deliver',client_id=str(client),product_id=str(made['product_id']))['status'],409)
        token=done['body']['link'].rsplit('/',1)[1]
        codes=[]
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_verification_code',side_effect=lambda to,code,*rest:codes.append(code)):
            wrong=self.form('/licencias/'+token,{'step':'identify','identification':'0999999999'});right=self.form('/licencias/'+token,{'step':'identify','identification':'0100000017'})
        self.assertEqual(wrong['body'],right['body']);self.assertEqual(len(codes),1)
        shown=self.form('/licencias/'+token,{'step':'verify','code':codes[0]});self.assertIn(SERIAL,shown['body']);self.assertIn('+593 98 746 0591',shown['body'])
        self.assertEqual(self.form('/licencias/'+token,{'step':'verify','code':codes[0]})['status'],400)
        self.assertEqual(self.post('/api/licenses/units/%d'%made['unit_id'],action='void',reason='Devolución autorizada por el cliente')['status'],200)
        self.assertEqual(self.unit(made['unit_id'])['status'],'anulada')
        codes.clear()
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_verification_code',side_effect=lambda to,code,*rest:codes.append(code)):
            self.form('/licencias/'+token,{'step':'identify','identification':'0100000017'})
        self.assertNotIn(SERIAL,str(self.form('/licencias/'+token,{'step':'verify','code':codes[0]})['body']))
        with app.connect() as c:self.assertIn('devolucion',[r[0] for r in c.execute('SELECT event FROM license_events')])

    def test_failed_codes_lock_the_link(self):
        self.admin();made=self.new_product();client=self.client_id()
        token=self.post('/api/licenses/deliver',client_id=str(client),product_id=str(made['product_id']))['body']['link'].rsplit('/',1)[1]
        for _ in range(licenses.MAX_CODE_FAILURES):self.form('/licencias/'+token,{'step':'identify','identification':'0999999999'})
        codes=[]
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_verification_code',side_effect=lambda to,code,*rest:codes.append(code)):
            self.form('/licencias/'+token,{'step':'identify','identification':'0100000017'})
        self.assertEqual(codes,[])
        with app.connect() as c:delivery=c.execute('SELECT id FROM license_deliveries').fetchone()[0]
        renewed=self.post('/api/licenses/deliveries/%d'%delivery,action='renew')['body']['link'].rsplit('/',1)[1]
        self.assertEqual(self.request('/licencias/'+token)['status'],404);self.assertEqual(self.request('/licencias/'+renewed)['status'],200)

    def test_renewal_keeps_history_and_suspends_previous_notices(self):
        self.admin();made=self.new_product();client=self.client_id()
        self.post('/api/licenses/deliver',client_id=str(client),product_id=str(made['product_id']))
        start=self.today()-timedelta(days=360);self.post('/api/licenses/units/%d'%made['unit_id'],action='activate',activated_at=start.isoformat())
        before=self.unit(made['unit_id'])['expires_at']
        with app.connect() as c:c.execute("INSERT INTO license_notices(unit_id,client_id,expires_at,days,recipient,status,created_at) VALUES (?,?,?,7,'x@example.invalid','error','x')",(made['unit_id'],client,before))
        self.assertEqual(self.post('/api/licenses/units/%d'%made['unit_id'],action='renew',duration='anual')['status'],400)
        same=self.post('/api/licenses/units/%d'%made['unit_id'],action='renew',duration='anual',starts_at=before,cost='20',price='32');self.assertEqual(same['status'],200,same['body'])
        self.assertEqual(self.unit(made['unit_id'])['expires_at'],licenses.add_months(date.fromisoformat(before),12).isoformat())
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT status FROM license_notices WHERE unit_id=?",(made['unit_id'],)).fetchone()[0],'cancelado')
            self.assertEqual(c.execute('SELECT previous_expires_at FROM license_renewals').fetchone()[0],before)
        newer=self.post('/api/licenses/units/%d'%made['unit_id'],action='renew',duration='anual',starts_at=self.today().isoformat(),key='NEW-KEY-RENEW-01')
        self.assertEqual(newer['status'],200,newer['body']);fresh=self.unit(newer['body']['new_unit_id'])
        self.assertEqual((fresh['client_id'],fresh['status'],fresh['renewed_from']),(client,'entregada',made['unit_id']))
        rows={r['id']:r for r in self.get('/api/clients/%d/licenses'%client)['body']['rows']}
        self.assertEqual(rows[made['unit_id']]['state'],'renovada');self.assertEqual(len(rows[made['unit_id']]['renewal_history']),2)
        self.assertEqual(self.get('/api/licenses')['body']['dashboard']['renovaciones'],2)
        self.assertEqual(self.post('/api/licenses/units/%d'%made['unit_id'],action='renew',duration='anual',starts_at=self.today().isoformat())['status'],409)

    def test_alerts_and_renewal_mails_without_duplicates(self):
        self.admin();client=self.client_id();today=self.today()
        def sold(name,key,days_left,duration='anual',activate=True):
            made=self.new_product(name=name,key=key,duration=duration)
            self.post('/api/licenses/deliver',client_id=str(client),product_id=str(made['product_id']))
            if activate:self.post('/api/licenses/units/%d'%made['unit_id'],action='activate',activated_at=today.isoformat())
            if days_left is not None:
                with app.connect() as c:c.execute('UPDATE license_units SET expires_at=? WHERE id=?',((today+timedelta(days=days_left)).isoformat(),made['unit_id']))
            return made['unit_id']
        soon=sold('Vence en 7','KEY-SOON-0007',7);later=sold('Vence en 100','KEY-LATE-0100',100)
        perpetual=sold('Perpetua ficticia','KEY-PERP-0001',None,duration='perpetua');pending=sold('Sin activar','KEY-PEND-0001',None,activate=False)
        delivered=[]
        config=lambda **extra:self.post('/api/licenses/notices',**dict({'enabled':True,'days':'30,15,7,1,0','subject':'Recordatorio de renovación de licencia | PC-DOCTOR S.A.','intro':license_mail.DEFAULTS['intro']},**extra))
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app.mail_pro,'settings',return_value=MAIL),patch.object(app.mail_pro,'deliver',side_effect=lambda cfg,message,to,**k:delivered.append((message,to)) or {'refused':{},'dsn':False}):
            with app.connect() as c:app.license_notices_tick(c,app.reception_now())
            self.assertEqual(delivered,[])
            self.assertEqual(config()['status'],200)
            for _ in range(2):
                with app.connect() as c:app.license_notices_tick(c,app.reception_now())
        self.assertEqual(len(delivered),1);message,to=delivered[0];self.assertEqual(to,['cliente@example.invalid'])
        html=message.get_body(('html',)).get_content()
        for text in ('Cliente ficticio','Vence en 7','SOLICITAR RENOVACIÓN','https://wa.me/593987460591','licencias-orig@ecuadorpcdoctor.com','7 días','cid:'):self.assertIn(text,html)
        self.assertNotIn('KEY-SOON',message.as_string())
        with app.connect() as c:
            notices=[tuple(r) for r in c.execute('SELECT unit_id,days,status FROM license_notices')]
            alerts={r[0] for r in c.execute('SELECT unit_id FROM license_alerts')}
        self.assertEqual(notices,[(soon,7,'enviado')]);self.assertEqual(alerts,{soon})
        for other in (perpetual,pending,later):self.assertNotIn(other,alerts)
        self.assertEqual(self.get('/api/licenses/notices')['body']['rows'][0]['result'],'Aceptado por el servidor de correo')
        with app.connect() as c:c.execute('UPDATE license_units SET expires_at=? WHERE id=?',((today+timedelta(days=1)).isoformat(),later))
        self.assertEqual(self.post('/api/licenses/optout',client_id=str(client),off=True)['status'],200)
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app.mail_pro,'settings',return_value=MAIL),patch.object(app.mail_pro,'deliver',side_effect=AssertionError('no debe enviar')):
            with app.connect() as c:app.license_notices_tick(c,app.reception_now())
        with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM license_notices WHERE unit_id=?',(later,)).fetchone()[0],'omitido')
        self.post('/api/licenses/optout',client_id=str(client),off=False)
        with app.connect() as c:c.execute("UPDATE license_notices SET status='error',attempts=1,next_retry_at='2000-01-01' WHERE unit_id=?",(later,))
        def fail(cfg,message,to,**k):raise app.mail_pro.MailError('conexion','Servidor no disponible (ficticio).')
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app.mail_pro,'settings',return_value=MAIL),patch.object(app.mail_pro,'deliver',side_effect=fail):
            with app.connect() as c:app.license_notices_tick(c,app.reception_now())
        with app.connect() as c:row=c.execute('SELECT status,attempts,next_retry_at FROM license_notices WHERE unit_id=?',(later,)).fetchone()
        self.assertEqual((row['status'],row['attempts']),('error',2));self.assertGreater(row['next_retry_at'],app.reception_now().isoformat())
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app.mail_pro,'settings',return_value=MAIL),patch.object(app.mail_pro,'deliver',return_value={'refused':{},'dsn':False}):
            with app.connect() as c:notice=c.execute('SELECT id FROM license_notices WHERE unit_id=?',(later,)).fetchone()[0]
            self.assertTrue(self.post('/api/licenses/notices/%d/resend'%notice)['body']['ok'])
            self.assertTrue(self.post('/api/licenses/notices/test',email='prueba@example.invalid')['body']['ok'])
            self.assertTrue(self.post('/api/licenses/units/%d'%soon,action='send_info')['body']['ok'])
        self.assertEqual(self.post('/api/licenses/notices',enabled=True,days='200',subject='Asunto válido',intro='x'*30)['status'],400)
        import adi
        with app.connect() as c:answer=adi.admin_reply(c,'¿qué licencias vencen pronto?',app.reception_now())['answer']
        self.assertIn('próxima',answer);self.assertIn('recordatorio',answer)

    def test_products_edit_duplicate_toggle(self):
        self.admin();made=self.new_product(logo=PNG);pid=made['product_id']
        edited=self.post('/api/licenses/products',item_id=str(pid),name='ESET NOD32 Antivirus ficticio 2026',line='antivirus',model='suscripcion',duration='bianual',validity_mode='compra',price='55',devices='3')
        self.assertEqual(edited['status'],200,edited['body'])
        product=next(p for p in self.get('/api/licenses')['body']['products'] if p['id']==pid)
        self.assertEqual((product['name'],product['duration'],product['validity_mode'],product['price_cents'],product['devices']),('ESET NOD32 Antivirus ficticio 2026','bianual','compra',5500,3))
        copy=self.post('/api/licenses/products/duplicate',item_id=str(pid),name='ESET NOD32 copia ficticia');self.assertEqual(copy['status'],201,copy['body'])
        twin=next(p for p in self.get('/api/licenses')['body']['products'] if p['id']==copy['body']['id'])
        self.assertTrue(twin['image']);self.assertEqual(twin['stock']['disponible'],0)
        self.assertEqual(self.post('/api/licenses/products/toggle',item_id=str(pid),active=False)['status'],200)
        self.assertNotIn(pid,[r['id'] for r in self.get('/api/catalog')['body']['rows']])
        self.assertEqual(self.unit(made['unit_id'])['status'],'disponible')

    def test_simultaneous_approvals_never_sell_the_same_unit(self):
        self.admin();made=self.new_product()
        quotes=[self.order_with_quote(made['product_id'],key='%04d'%n)[1] for n in range(4)]
        for quote in quotes:self.assertEqual(self.post('/api/quotes/%d'%quote,action='send')['status'],200)
        def decide(quote):
            with app.connect() as c:ids=[str(r[0]) for r in c.execute('SELECT id FROM quote_items WHERE quote_id=?',(quote,))]
            return self.post('/api/quotes/%d'%quote,action='decide',approved=','.join(ids),note='Aprobó por teléfono (ficticio)')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(decide,quotes))
        self.assertTrue(all(r['status']==200 for r in results),results)
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM license_units WHERE status='reservada'").fetchone()[0],1)

    def test_only_administration_manages_licenses(self):
        self.admin();made=self.new_product();client=self.client_id()
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        for path in ('/api/licenses','/api/licenses/units','/api/licenses/deliveries','/api/licenses/history','/api/licenses/notices'):
            self.assertEqual(self.get(path)['status'],403,path)
        for path,body in (('/api/licenses/new',{'name':'x'}),('/api/licenses/units/%d'%made['unit_id'],{'action':'reveal'}),('/api/licenses/deliver',{}),('/api/licenses/notices',{})):
            self.assertEqual(self.request(path,body,cookie=self.cookie,csrf=self.csrf)['status'],403,path)
        self.assertEqual(self.request('/api/licenses')['status'],401)
        self.assertEqual(list(self.get('/api/catalog')['body']['license_stock'].values()),[1])
        mine=self.get('/api/clients/%d/licenses'%client)['body'];self.assertFalse(mine['can_manage'])


if __name__=='__main__':unittest.main()


class LicenseSaleRedesignTests(LicenseProTests):
    """Rediseño de la venta y del registro: datos comerciales, activación al entregar, alta con varias claves y ventanas sin desbordes."""
    # Solo reutiliza los ayudantes: las pruebas de la clase base no se repiten aquí.
    for _name in [n for n in vars(LicenseProTests) if n.startswith('test_')]:locals()[_name]=None
    def test_sale_with_price_discount_payment_and_activation(self):
        self.admin();made=self.new_product();client=self.client_id();order,_=self.order_with_quote(made['product_id'])
        with app.connect() as c:code=c.execute('SELECT code FROM orders WHERE id=?',(order,)).fetchone()[0]
        info=self.get('/api/licenses/order-info?code='+code.lower())['body'];self.assertEqual((info['order_id'],info['client_id']),(order,client))
        self.assertEqual(self.get('/api/licenses/order-info?code=PCD-00000000-0000')['status'],404)
        bad=self.post('/api/licenses/deliver',client_id=str(client),product_id=str(made['product_id']),price='30',discount='31')
        self.assertEqual(bad['status'],400);self.assertEqual(self.unit(made['unit_id'])['status'],'disponible')      # nada a medias
        day=(self.today()-timedelta(days=2)).isoformat()
        done=self.post('/api/licenses/deliver',client_id=str(client),product_id=str(made['product_id']),unit_id=str(made['unit_id']),order_code=code,price='30',discount='5',payment_status='pagado',activated=True,activated_at=day)
        self.assertEqual(done['status'],200,done['body'])
        with app.connect() as c:row=c.execute('SELECT price_cents,discount_cents,payment_status FROM license_deliveries').fetchone()
        self.assertEqual(tuple(row),(3000,500,'pagado'))
        unit=self.unit(made['unit_id']);self.assertEqual((unit['status'],unit['activated'],unit['activated_at'],unit['expires_at']),('entregada',1,day,licenses.add_months(date.fromisoformat(day),12).isoformat()))
        history=self.get('/api/licenses/deliveries')['body']['history'][0];self.assertEqual((history['price_cents'],history['discount_cents'],history['payment_status']),(3000,500,'pagado'))
        self.assertEqual(self.post('/api/licenses/deliver',client_id=str(client),product_id=str(made['product_id']),unit_id=str(made['unit_id']))['status'],409)

    def test_new_product_with_several_keys_is_atomic(self):
        self.admin()
        failed=self.post('/api/licenses/new',name='Lote fallido ficticio',line='antivirus',duration='anual',validity_mode='activacion',price='20',lines='LOTE-KEY-0001\nLOTE-KEY-0001')
        self.assertEqual(failed['status'],400)
        with app.connect() as c:self.assertIsNone(c.execute("SELECT 1 FROM catalog_items WHERE name='Lote fallido ficticio'").fetchone())
        made=self.post('/api/licenses/new',name='Lote correcto ficticio',line='antivirus',duration='anual',validity_mode='activacion',price='20',lines='LOTE-KEY-0001\nLOTE-KEY-0002\ncuenta@example.invalid;Clave 3')
        self.assertEqual((made['status'],made['body']['count']),(201,3),made['body'])

    def test_license_dialog_styles_never_force_a_minimum_width(self):
        css=(app.ROOT/'static'/'app.css').read_text(encoding='utf-8')
        self.assertNotIn('license-dialog-wide .license-form-grid{min-width',css)
        self.assertIn('.license-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 16px;min-width:0}',css)
        self.assertIn('.license-form-body{overflow-y:auto;overflow-x:hidden',css)


class NoticeCenterTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request
    login=test_app.SecurityTests.login
    order_data=test_app.SecurityTests.order_data

    def test_hide_restore_and_exact_counters(self):
        cookie,csrf=self.login()
        for n in range(2):self.request('/api/orders',self.order_data({'request_key':'notice-center-%04d'%n}),cookie=cookie,csrf=csrf)
        with app.connect() as c:
            other=c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tec2','tec2@example.invalid','Técnico 2',?,'tecnico',0)",(self.hash,)).lastrowid
            c.execute("INSERT INTO order_history(order_id,actor_id,event,status_label,comment,occurred_at) SELECT id,?, 'follow_up','', 'Seguimiento ficticio', ? FROM orders",(other,app.reception_now().isoformat()))
        data=self.request('/api/notifications',cookie=cookie)['body']
        self.assertEqual(data['total'],len(data['items']));self.assertGreaterEqual(data['total'],1)
        item=next(i for i in data['items'] if i['hideable'])
        hidden=self.request('/api/notifications/hide',{'keys':item['key']},cookie=cookie,csrf=csrf)['body']
        self.assertNotIn(item['key'],[i['key'] for i in hidden['items']]);self.assertEqual((hidden['total'],hidden['hidden_count']),(data['total']-1,1))
        listed=self.request('/api/notifications?hidden=1',cookie=cookie)['body']['items'];self.assertEqual([i['key'] for i in listed],[item['key']])
        restored=self.request('/api/notifications/hide',{'keys':item['key'],'restore':True},cookie=cookie,csrf=csrf)['body']
        self.assertIn(item['key'],[i['key'] for i in restored['items']]);self.assertEqual(restored['hidden_count'],0)
        self.assertEqual(self.request('/api/notifications/hide',{'keys':''},cookie=cookie,csrf=csrf)['status'],400)
        read=self.request('/api/notifications/read',{'all':True},cookie=cookie,csrf=csrf)['body'];self.assertEqual(read['unread'],0)
        self.assertEqual(self.request('/api/notifications',cookie=cookie)['body']['unread'],0)                  # se conserva al recargar
        import notifications
        self.assertTrue(notifications.CRITICAL.match('storage:local'));self.assertFalse(notifications.CRITICAL.match('event:12'))
