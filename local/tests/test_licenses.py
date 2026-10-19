"""Inventario de Licencias Digitales: cifrado, duplicados, reservas al aprobar, pagos parciales, autorización y entrega segura."""
import concurrent.futures
import io
import re
import sqlite3
import unittest
from email.message import Message
from unittest.mock import patch
from urllib.parse import urlencode
import test_app
import app,licenses
app.os.environ.setdefault('LOGIN_CAPTCHA','off')
SERIAL='KASP-FICT-1234-ABCD-9999'


class LicenseInventoryTests(unittest.TestCase):
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

    def setup_product(self,kind='antivirus',name='Kaspersky Standard ficticio'):
        self.cookie,self.csrf=self.login()
        self.post=lambda path,**body:self.request(path,body,cookie=self.cookie,csrf=self.csrf)
        item=self.post('/api/catalog',name=name,category='seguridad' if kind=='antivirus' else 'licencia',price='30',taxed=True)['body']['id']
        self.assertEqual(self.post('/api/licenses/products',item_id=str(item),kind=kind,supplier='Proveedor ficticio',purchase_price='18,50',term='1 año',devices='1')['status'],200)
        return item

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

    def register(self,product,serial=SERIAL,**extra):
        return self.post('/api/licenses/units',product_id=str(product),serial=serial,manufacturer='Kaspersky',version='2026',devices='1',term='1 año',**extra)

    def pay(self,order,amount):
        return self.post('/api/orders/%d/payments'%order,amount=amount,method='efectivo')

    def statuses(self,product):
        with app.connect() as c:return [r[0] for r in c.execute('SELECT status FROM license_units WHERE product_id=? ORDER BY id',(product,))]

    def test_credentials_are_encrypted_and_duplicates_rejected(self):
        product=self.setup_product()
        made=self.register(product);self.assertEqual(made['status'],201,made['body'])
        for variant in (SERIAL.lower(),SERIAL.replace('-',' '),' '+SERIAL+' '):
            again=self.register(product,variant);self.assertEqual(again['status'],409,variant);self.assertIn('ya está registrada',again['body']['error'])
        with app.connect() as c:
            row=c.execute('SELECT secret,fingerprint FROM license_units').fetchone()
            self.assertTrue(row['secret'].startswith('lic1:'));self.assertNotIn(SERIAL,row['secret']);self.assertNotIn(SERIAL.lower(),row['fingerprint'])
            dump='\n'.join(c.iterdump())
        self.assertNotIn(SERIAL,dump);self.assertNotIn('1234-ABCD',dump)
        self.assertEqual(licenses.unseal(row['secret']),{'serial':SERIAL})
        tampered=row['secret'][:-3]+('AAA' if row['secret'][-3:]!='AAA' else 'BBB')
        with self.assertRaises(licenses.LicenseError):licenses.unseal(tampered)
        # Las consultas del inventario y el historial no incluyen la credencial; buscar por la clave la encuentra por su huella.
        listing=self.request('/api/licenses/units?q='+SERIAL.lower(),cookie=self.cookie)['body']
        self.assertEqual(len(listing['rows']),1);self.assertNotIn(SERIAL,str(listing));self.assertNotIn(SERIAL,str(self.request('/api/licenses/history',cookie=self.cookie)['body']))
        shown=self.post('/api/licenses/units/%d'%made['body']['id'],action='reveal')['body']['credentials']
        self.assertEqual(shown,[{'key':'serial','label':'Serial o código de activación','value':SERIAL}])
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM license_events WHERE event='credenciales_consultadas'").fetchone()[0],1)

    def test_bulk_registration_is_all_or_nothing_and_m365_has_account_and_password(self):
        product=self.setup_product()
        bad=self.post('/api/licenses/units/bulk',product_id=str(product),lines='SERIAL-AAAA-0001\nSERIAL-AAAA-0002\nSERIAL-AAAA-0001',manufacturer='Kaspersky')
        self.assertEqual(bad['status'],400);self.assertIn('Línea 3',bad['body']['error']);self.assertEqual(self.statuses(product),[])
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM license_batches').fetchone()[0],0)
        good=self.post('/api/licenses/units/bulk',product_id=str(product),lines='SERIAL-AAAA-0001\n\nSERIAL-AAAA-0002\nSERIAL-AAAA-0003',manufacturer='Kaspersky',expires_at='2099-01-01',supplier='Mayorista ficticio',unit_cost='15')
        self.assertEqual((good['status'],good['body']['count']),(201,3));self.assertEqual(self.statuses(product),['disponible']*3)
        m365=self.setup_product('m365','Microsoft 365 ficticio')
        self.assertEqual(self.post('/api/licenses/units/bulk',product_id=str(m365),lines='sin-separador@example.invalid')['status'],400)
        made=self.post('/api/licenses/units/bulk',product_id=str(m365),lines='cuenta1@example.invalid;Clave Ficticia 1\nCUENTA1@example.invalid;otra')
        self.assertIn('repetida',made['body']['error'])
        made=self.post('/api/licenses/units',product_id=str(m365),username='cuenta1@example.invalid',password='Clave Ficticia 1',license_type='Familia',devices='5',activated_at='2026-10-01',expires_at='2027-10-01')
        self.assertEqual(made['status'],201,made['body'])
        with app.connect() as c:self.assertEqual(licenses.unseal(c.execute('SELECT secret FROM license_units WHERE id=?',(made['body']['id'],)).fetchone()[0]),{'username':'cuenta1@example.invalid','password':'Clave Ficticia 1'})

    def test_draft_does_not_reserve_and_approval_reserves_without_revealing(self):
        product=self.setup_product()
        for n in range(2):self.register(product,'SERIAL-RESV-%04d'%n,expires_at='2099-0%d-01'%(n+1))
        order,quote=self.order_with_quote(product,quantity=3)
        self.assertEqual(self.statuses(product),['disponible','disponible'])
        approved=self.approve(quote);self.assertEqual(approved['status'],200,approved['body'])
        self.assertEqual(self.statuses(product),['reservada','reservada'])
        catalog=self.request('/api/catalog',cookie=self.cookie)['body'];self.assertEqual(catalog['license_stock'][str(product)] if str(product) in catalog['license_stock'] else catalog['license_stock'][product],0)
        rows=self.request('/api/licenses/deliveries',cookie=self.cookie)['body']['rows']
        self.assertEqual(rows[0]['pending'][0]['missing'],1);self.assertNotIn('SERIAL-RESV',str(rows))
        # Con una existencia nueva se completa la venta que esperaba.
        self.register(product,'SERIAL-RESV-0099');self.assertEqual(self.statuses(product),['reservada']*3)
        self.assertEqual(self.request('/api/licenses/deliveries',cookie=self.cookie)['body']['rows'][0]['pending'],[])

    def test_expired_units_are_not_sold_and_released_units_return_only_if_not_activated(self):
        product=self.setup_product()
        self.register(product,'SERIAL-VIEJA-0001',expires_at='2020-01-01');self.register(product,'SERIAL-NUEVA-0002')
        order,quote=self.order_with_quote(product,quantity=1);self.approve(quote)
        self.assertEqual(self.statuses(product),['vencida','reservada'])
        with app.connect() as c:unit=c.execute("SELECT id FROM license_units WHERE status='reservada'").fetchone()[0]
        self.post('/api/licenses/units/%d'%unit,action='edit',activated=True)
        refused=self.post('/api/licenses/units/%d'%unit,action='release');self.assertEqual(refused['status'],409);self.assertIn('activada',refused['body']['error'])
        self.post('/api/licenses/units/%d'%unit,action='edit',activated=False)
        self.assertEqual(self.post('/api/licenses/units/%d'%unit,action='release')['status'],200);self.assertEqual(self.statuses(product),['vencida','disponible'])

    def test_payment_authorization_and_secure_delivery(self):
        product=self.setup_product()
        unit=self.register(product)['body']['id']
        order,quote=self.order_with_quote(product,quantity=1,extra_cents=2000);self.approve(quote)
        # Saldo pendiente: no se confirma el pago (pago parcial).
        self.assertEqual(self.pay(order,'20')['status'],201)
        blocked=self.post('/api/licenses/orders/%d/confirm-payment'%order);self.assertEqual(blocked['status'],409);self.assertIn('saldo pendiente',blocked['body']['error'])
        self.assertEqual(self.pay(order,'30')['status'],201)
        confirmed=self.post('/api/licenses/orders/%d/confirm-payment'%order);self.assertEqual(confirmed['status'],200,confirmed['body'])
        delivery=confirmed['body']['delivery']
        self.assertEqual(self.post('/api/licenses/orders/%d/confirm-payment'%order)['status'],409)
        sent=[]
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_institutional',side_effect=lambda *a,**k:sent.append((a,k))):
            done=self.post('/api/licenses/deliveries/%d'%delivery,action='authorize')
        self.assertEqual(done['status'],200,done['body']);self.assertEqual(done['body']['mail'],'sent')
        self.assertNotIn(SERIAL,str(sent));self.assertIn('/licencias/',str(sent))
        token=done['body']['link'].rsplit('/',1)[1]
        self.assertEqual(self.statuses(product),['entregada'])
        with app.connect() as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE license_units SET status='disponible' WHERE id=?",(unit,))
            with self.assertRaises(sqlite3.IntegrityError):c.execute('DELETE FROM license_units WHERE id=?',(unit,))
            self.assertEqual(c.execute('SELECT client_id IS NOT NULL,order_id FROM license_units WHERE id=?',(unit,)).fetchone()[1],order)
        self.assertEqual(self.post('/api/licenses/units/%d'%unit,action='release')['status'],409)
        # Entrega pública: la página no muestra nada sin identificación y código.
        page=self.request('/licencias/'+token)
        # La hoja de estilos pública se sirve sin sesión y con un nombre que Vercel no descarta (los «license*» se omiten del paquete).
        self.assertIn('/static/licencias.css',str(page['body']));self.assertEqual(self.request('/static/licencias.css')['status'],200)
        self.assertEqual(page['status'],200);self.assertNotIn(SERIAL,str(page['body']))
        self.assertEqual(self.request('/licencias/'+'x'*40)['status'],404)
        codes=[]
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_verification_code',side_effect=lambda to,code,*rest:codes.append((to,code))):
            wrong=self.form('/licencias/'+token,{'step':'identify','identification':'0999999999'})
            self.assertEqual(wrong['status'],200);self.assertEqual(codes,[])
            right=self.form('/licencias/'+token,{'step':'identify','identification':'0100000017'})
        self.assertEqual(wrong['body'],right['body']);self.assertEqual(len(codes),1);self.assertEqual(codes[0][0],'cliente@example.invalid')
        code=codes[0][1];bad=('000000' if code!='000000' else '111111')
        failed=self.form('/licencias/'+token,{'step':'verify','code':bad});self.assertEqual(failed['status'],400);self.assertNotIn(SERIAL,str(failed['body']))
        shown=self.form('/licencias/'+token,{'step':'verify','code':code})
        self.assertEqual(shown['status'],200);self.assertIn(SERIAL,shown['body']);self.assertIn('Kaspersky Standard ficticio',shown['body'])
        self.assertIn('+593 98 746 0591',shown['body']);self.assertIn('licencias-orig@ecuadorpcdoctor.com',shown['body'])
        self.assertEqual(self.form('/licencias/'+token,{'step':'verify','code':code})['status'],400)  # un solo uso
        public_card=self.request('/api/licenses/deliveries/%d/card'%delivery,cookie=self.cookie)['body']
        self.assertNotIn(SERIAL,str(public_card));self.assertFalse(public_card['private'])
        # Si después aparece un saldo (por ejemplo, un pago anulado), ya no se revela nada aunque el código sea correcto.
        with app.connect() as c:payment=c.execute('SELECT id FROM order_payments WHERE order_id=? ORDER BY id DESC',(order,)).fetchone()[0]
        self.assertEqual(self.post('/api/orders/%d/payments/void'%order,payment_id=str(payment),reason='Pago anulado ficticio')['status'],200)
        codes.clear()
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_verification_code',side_effect=lambda to,code,*rest:codes.append((to,code))):
            self.form('/licencias/'+token,{'step':'identify','identification':'0100000017'})
        self.assertNotIn(SERIAL,str(self.form('/licencias/'+token,{'step':'verify','code':codes[0][1]})['body']))
        with app.connect() as c:
            self.assertNotIn(SERIAL,'\n'.join(c.iterdump()))
            events=[r[0] for r in c.execute('SELECT event FROM license_events ORDER BY id')]
        for name in ('registrada','reservada','pago_confirmado','entregada','entrega_autorizada','codigo_enviado','credenciales_consultadas'):self.assertIn(name,events)

    def test_failed_codes_lock_the_link(self):
        product=self.setup_product();self.register(product)
        order,quote=self.order_with_quote(product);self.approve(quote);self.pay(order,'30')
        delivery=self.post('/api/licenses/orders/%d/confirm-payment'%order)['body']['delivery']
        token=self.post('/api/licenses/deliveries/%d'%delivery,action='authorize')['body']['link'].rsplit('/',1)[1]
        for _ in range(licenses.MAX_CODE_FAILURES):self.form('/licencias/'+token,{'step':'identify','identification':'0999999999'})
        codes=[]
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_verification_code',side_effect=lambda to,code,*rest:codes.append(code)):
            self.form('/licencias/'+token,{'step':'identify','identification':'0100000017'})
        self.assertEqual(codes,[])
        renewed=self.post('/api/licenses/deliveries/%d'%delivery,action='renew')['body']['link'].rsplit('/',1)[1]
        self.assertEqual(self.request('/licencias/'+token)['status'],404);self.assertEqual(self.request('/licencias/'+renewed)['status'],200)

    def test_simultaneous_approvals_never_sell_the_same_unit(self):
        product=self.setup_product();self.register(product)
        quotes=[self.order_with_quote(product,key='%04d'%n)[1] for n in range(4)]
        for quote in quotes:self.assertEqual(self.post('/api/quotes/%d'%quote,action='send')['status'],200)
        def decide(quote):
            with app.connect() as c:ids=[str(r[0]) for r in c.execute('SELECT id FROM quote_items WHERE quote_id=?',(quote,))]
            return self.post('/api/quotes/%d'%quote,action='decide',approved=','.join(ids),note='Aprobó por teléfono (ficticio)')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(decide,quotes))
        self.assertTrue(all(r['status']==200 for r in results),results)
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM license_units WHERE status='reservada'").fetchone()[0],1)
        with app.connect() as c:self.assertEqual(sum(row['missing'] for row in licenses.pending_items(c,product_id=product)),3)

    def test_only_administration_manages_licenses(self):
        product=self.setup_product();unit=self.register(product)['body']['id']
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        for path in ('/api/licenses','/api/licenses/units','/api/licenses/deliveries','/api/licenses/history'):
            self.assertEqual(self.request(path,cookie=self.cookie)['status'],403,path)
        for path,body in (('/api/licenses/units',{'product_id':str(product),'serial':'SERIAL-TEC-0001'}),('/api/licenses/units/%d'%unit,{'action':'reveal'}),('/api/licenses/products',{'item_id':str(product),'kind':'antivirus'})):
            self.assertEqual(self.request(path,body,cookie=self.cookie,csrf=self.csrf)['status'],403,path)
        self.assertEqual(self.request('/api/licenses')['status'],401)
        # El técnico sí ve la disponibilidad en el catálogo del presupuesto, sin datos de las licencias.
        stock=self.request('/api/catalog',cookie=self.cookie)['body']['license_stock']
        self.assertEqual(list(stock.values()),[1])


if __name__=='__main__':unittest.main()
