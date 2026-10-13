"""Presupuestos: catálogo, IVA incluido, versiones ligadas a la orden, estados por ítem, aprobación del cliente con firma y evidencia."""
import json,re,unittest
from unittest.mock import patch
import test_app
import app,quotes
app.os.environ.setdefault('LOGIN_CAPTCHA','off')
SIGN=json.dumps([[[100,200],[250,60],[400,220],[550,80],[700,210],[850,90]],[[120,250],[880,250]]])


class QuoteMathTests(unittest.TestCase):
    def test_prices_include_tax_and_totals_split_by_decision(self):
        self.assertEqual(quotes.split(11500,1,1500),(10000,1500));self.assertEqual(quotes.split(3500,1,1500),(3043,457));self.assertEqual(quotes.split(2500,0,1500),(2500,0));self.assertEqual(quotes.split(999,1,0),(999,0))
        items=[{'quantity':1,'unit_cents':3500,'taxed':1,'status':'aprobado'},{'quantity':2,'unit_cents':1250,'taxed':0,'status':'rechazado'},{'quantity':1,'unit_cents':1000,'taxed':1,'status':'pendiente'},{'quantity':1,'unit_cents':9999,'taxed':1,'status':'cancelado'}]
        t=quotes.totals(items,1500)
        self.assertEqual((t['quoted'],t['approved'],t['rejected'],t['pending'],t['cancelled']),(7000,3500,2500,1000,9999))
        self.assertEqual(t['base_taxed']+t['base_zero']+t['tax'],t['quoted']);self.assertEqual(t['approved_base_taxed']+t['approved_base_zero']+t['approved_tax'],t['approved'])
        for text,value in (('35',3500),('35,5',3550),('0.99',99)):self.assertEqual(quotes.cents(text),value)
        for bad in ('','-1','1.999','abc','1000000'):
            with self.assertRaises(quotes.QuoteError):quotes.cents(bad)
        self.assertEqual(quotes.clean_signature('[[[1,1]]]'),[]);self.assertEqual(len(quotes.clean_signature(SIGN)),2);self.assertEqual(quotes.clean_signature('<script>'),[])


class QuoteFlowTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def form(self,path,fields):
        from urllib.parse import urlencode
        from email.message import Message
        import io
        handler=object.__new__(app.Handler);handler.path=path;handler.client_address=('127.0.0.1',5555);handler.headers=Message();body=urlencode(fields).encode()
        handler.headers['Content-Type']='application/x-www-form-urlencoded';handler.headers['Content-Length']=str(len(body));handler.headers['Origin']='http://127.0.0.1:8010';handler.rfile=io.BytesIO(body);result={}
        handler.reply=lambda status,content,content_type='application/json; charset=utf-8',cookie=None,filename=None:result.update(status=status,body=content)
        handler.do_POST();return result

    def prepare(self):
        cookie,csrf=self.login()
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','brand':'HP','model':'Ficticio','request_key':'quote-flow-request-key-0001'}),cookie=cookie,csrf=csrf)['body']
        post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        ids=[post('/api/catalog',name=name,category=category,price=price,taxed=taxed)['body']['id'] for name,category,price,taxed in (('Mantenimiento preventivo','servicio','35',True),('Licencia ficticia','licencia','12,50',False),('Disco SSD ficticio','repuesto','80.00',True))]
        return cookie,csrf,order,post,ids

    def test_catalog_is_admin_only_and_changes_do_not_touch_issued_quotes(self):
        cookie,csrf,order,post,ids=self.prepare()
        listing=self.request('/api/catalog',cookie=cookie)['body']
        self.assertEqual((len(listing['rows']),listing['tax_rate_bp'],listing['rows'][0]['price_cents']),(3,1500,1250))
        for bad in ({'name':'x','category':'servicio','price':'1'},{'name':'Válido','category':'inventada','price':'1'},{'name':'Válido','category':'servicio','price':'-1'}):self.assertEqual(post('/api/catalog',**bad)['status'],400)
        quote=post('/api/orders/%d/quote'%order['id'])['body']['id']
        saved=post('/api/quotes/%d'%quote,action='save',items=[{'catalog_id':ids[0],'description':'Mantenimiento preventivo','category':'servicio','quantity':1,'unit_cents':3500,'taxed':True}])['body']['quote']
        self.assertEqual((saved['code'],saved['totals']['quoted'],saved['status']),(order['code']+'-P1',3500,'borrador'))
        # El precio del catálogo cambia y el elemento deja de estar disponible: el presupuesto emitido conserva su importe.
        self.assertEqual(post('/api/catalog',id=str(ids[0]),name='Mantenimiento preventivo',category='servicio',price='50',available=False)['status'],200)
        self.assertEqual(self.request('/api/quotes/%d'%quote,cookie=cookie)['body']['quote']['items'][0]['unit_cents'],3500)
        self.assertEqual(len(self.request('/api/catalog',cookie=cookie)['body']['rows']),2);self.assertEqual(len(self.request('/api/catalog?all=1',cookie=cookie)['body']['rows']),3)
        self.assertEqual(post('/api/catalog/tax',tax='12')['body']['tax_rate_bp'],1200);self.assertEqual(post('/api/catalog/tax',tax='45')['status'],400)
        self.assertEqual(self.request('/api/quotes/%d'%quote,cookie=cookie)['body']['quote']['tax_rate_bp'],1500)  # la tarifa queda fijada al crear el presupuesto
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
        self.assertEqual(post('/api/catalog',name='Otro',category='otro',price='1')['status'],403);self.assertEqual(post('/api/quotes/%d'%quote,action='send')['status'],403)
        self.assertEqual(post('/api/quotes/%d'%quote,action='save',items=[])['status'],200)  # el técnico sí prepara el borrador
        self.assertEqual(self.request('/api/catalog')['status'],401)

    def test_client_approves_some_items_with_signature_and_evidence(self):
        cookie,csrf,order,post,ids=self.prepare()
        quote=post('/api/orders/%d/quote'%order['id'])['body']['id']
        items=[{'catalog_id':ids[0],'description':'Mantenimiento preventivo','category':'servicio','quantity':1,'unit_cents':3500,'taxed':True},{'catalog_id':ids[1],'description':'Licencia ficticia','category':'licencia','quantity':2,'unit_cents':1250,'taxed':False},{'description':'Trabajo adicional sin catálogo','category':'otro','quantity':1,'unit_cents':1000,'taxed':True}]
        self.assertEqual(post('/api/quotes/%d'%quote,action='send')['status'],400)  # vacío: no se envía
        post('/api/quotes/%d'%quote,action='save',items=items,valid_until=(app.reception_now().date()+app.appointments.timedelta(days=10)).isoformat(),notes='Nota ficticia')
        sent=[]
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app.mail_pro,'settings',return_value={'username':'taller@example.invalid','password':'x'}),patch.object(app.mail_pro,'deliver',side_effect=lambda config,message,recipients:sent.append((recipients,message))):
            result=post('/api/quotes/%d'%quote,action='send')['body']
        self.assertEqual((result['mail'],result['recipient'],result['quote']['status'],len(sent)),('sent','cliente@example.invalid','enviado',1))
        text=sent[0][1].get_body(('plain',)).get_content();self.assertIn(result['link'],text);self.assertIn('$70,00',text);self.assertNotIn('0100000017',text)
        token=result['link'].rsplit('/',1)[1];path='/presupuesto/'+token
        # Enviado: ya no se edita; el estado de la orden no cambia.
        self.assertEqual(post('/api/quotes/%d'%quote,action='save',items=items)['status'],409)
        first=self.request(path);self.assertEqual(first['status'],200);self.assertIn('últimos cuatro dígitos',first['body']);self.assertNotIn('$35,00',first['body'])
        self.assertEqual(self.request(path+'/documento.pdf')['status'],404)
        self.assertIn('no coinciden',self.form(path,{'last4':'9999'})['body'])
        page=self.form(path,{'last4':'0017'})['body'];self.assertIn('$35,00',page);self.assertIn('Total cotizado',page);self.assertIn('ejecutar exclusivamente los servicios aceptados',page)
        passkey=re.search(r'name="passkey" value="([^"]+)"',page)[1];item_ids=[int(v) for v in dict.fromkeys(re.findall(r'name="decision_(\d+)"',page))]
        self.assertEqual(self.request(path+'/documento.pdf?k='+passkey)['body'][:4],b'%PDF')
        base={'passkey':passkey,'action':'decide','name':'Cliente Ficticio','accept':'on','decision_%d'%item_ids[0]:'aprobado','decision_%d'%item_ids[1]:'rechazado','decision_%d'%item_ids[2]:'aprobado'}
        # Sin firma, sin aceptación o sin decidir todo no se registra nada.
        for broken,expected in ((dict(base,signature=''),'Firma en el recuadro'),({k:v for k,v in dict(base,signature=SIGN).items() if k!='accept'},'aceptar expresamente'),({k:v for k,v in dict(base,signature=SIGN).items() if k!='decision_%d'%item_ids[2]},'apruebas o rechazas cada servicio')):
            self.assertIn(expected,self.form(path,broken)['body'])
        self.assertEqual(self.form(path,dict(base,passkey='llave-falsa',signature=SIGN))['status'],200)
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM quote_acceptances').fetchone()[0],0)
        done=self.form(path,dict(base,signature=SIGN,comment='Solo lo necesario'))['body']
        self.assertIn('Parcialmente aprobado',done);self.assertIn('$45,00',done)
        detail=self.request('/api/quotes/%d'%quote,cookie=cookie)['body']['quote']
        self.assertEqual((detail['status'],detail['decided_by'],detail['totals']['quoted'],detail['totals']['approved'],detail['totals']['rejected']),('parcial','cliente',7000,4500,2500))
        self.assertEqual([item['status'] for item in detail['items']],['aprobado','rechazado','aprobado']);self.assertEqual((detail['acceptance']['signer_name'],detail['acceptance']['signed']),('Cliente Ficticio',True))
        order_now=self.request('/api/orders/%d'%order['id'],cookie=cookie)['body'];order_now=order_now.get('order',order_now)
        # Lo aprobado pasa al total a cobrar de la orden; el estado de la orden no cambia por la aprobación.
        self.assertEqual((order_now['status'],order_now['budget']['total_cents'],order_now['money']['balance_cents']),('pendiente',4500,4500))
        with app.connect() as c:
            self.assertTrue(quotes.evidence_ok(c,quote))
            evidence=json.loads(c.execute('SELECT evidence FROM quote_acceptances').fetchone()[0]);self.assertEqual((evidence['signer'],evidence['totals']['approved'],[i['decision'] for i in evidence['items']]),('Cliente Ficticio',4500,['aprobado','rechazado','aprobado']))
            for sql in ('UPDATE quote_acceptances SET signer_name=?','DELETE FROM quote_acceptances WHERE signer_name!=?','UPDATE quote_events SET detail=?'):
                with self.assertRaises(Exception):c.execute(sql,('x',))
        # El enlace ya no decide de nuevo: muestra el resultado. El PDF incluye la decisión y oculta la identificación.
        again=self.form(path,dict(base,signature=SIGN));self.assertIn('Parcialmente aprobado',again['body']);self.assertEqual(self.request(path+'/documento.pdf')['body'][:4],b'%PDF')
        self.assertEqual(self.request('/api/quotes/%d/pdf'%quote,cookie=cookie)['body'][:4],b'%PDF');self.assertEqual(self.request('/api/quotes/%d/pdf'%quote)['status'],401)
        self.assertEqual(post('/api/quotes/%d'%quote,action='cancel')['status'],409)
        self.assertEqual(self.request('/presupuesto/'+'x'*40)['status'],404)

    def test_versions_staff_decision_change_request_and_payments_guard(self):
        cookie,csrf,order,post,ids=self.prepare()
        one=post('/api/orders/%d/quote'%order['id'])['body']['id'];self.assertEqual(post('/api/orders/%d/quote'%order['id'])['status'],409)
        line={'description':'Mantenimiento preventivo','category':'servicio','quantity':1,'unit_cents':3500,'taxed':True}
        post('/api/quotes/%d'%one,action='save',items=[line])
        link=post('/api/quotes/%d'%one,action='send')['body']['link'];path='/presupuesto/'+link.rsplit('/',1)[1]
        page=self.form(path,{'last4':'0017'})['body'];passkey=re.search(r'name="passkey" value="([^"]+)"',page)[1]
        self.assertIn('Escribe tu solicitud.',self.form(path,{'passkey':passkey,'action':'change','comment':''})['body'])
        self.assertIn('solicitud de modificación',self.form(path,{'passkey':passkey,'action':'change','comment':'Quiero incluir un disco nuevo'})['body'])
        current=self.request('/api/orders/%d/quote'%order['id'],cookie=cookie)['body']
        self.assertEqual((current['current']['status'],current['current']['editable']),('modificacion',True))
        # Nueva versión: P2 copia los ítems, cancela la anterior y revoca su enlace.
        two=post('/api/quotes/%d'%one,action='version')['body']['id']
        both=self.request('/api/orders/%d/quote'%order['id'],cookie=cookie)['body']
        self.assertEqual([(v['code'][-3:],v['status']) for v in both['versions']],[('-P2','borrador'),('-P1','cancelado')]);self.assertEqual(len(both['current']['items']),1);self.assertEqual(self.request(path)['status'],200)
        post('/api/quotes/%d'%two,action='save',items=[line,{'description':'Disco SSD ficticio','category':'repuesto','quantity':1,'unit_cents':8000,'taxed':True}])
        post('/api/quotes/%d'%two,action='send');detail=self.request('/api/quotes/%d'%two,cookie=cookie)['body']['quote'];a,b=[item['id'] for item in detail['items']]
        # Decisión registrada por el personal: exige nota y decidir todos los ítems.
        self.assertEqual(post('/api/quotes/%d'%two,action='decide',approved=str(a),rejected=str(b),note='')['status'],400)
        self.assertEqual(post('/api/quotes/%d'%two,action='decide',approved=str(a),note='Aprobó por teléfono')['status'],400)
        decided=post('/api/quotes/%d'%two,action='decide',approved='%d,%d'%(a,b),note='Aprobó por teléfono')['body']['quote']
        self.assertEqual((decided['status'],decided['totals']['approved'],decided['acceptance']),('aprobado',11500,None));self.assertTrue(decided['decided_by'].startswith('personal:'))
        self.assertEqual(post('/api/quotes/%d'%two,action='decide',approved='%d,%d'%(a,b),note='Otra vez')['status'],409)
        # Con pagos registrados, una versión posterior no puede aprobar menos de lo ya cobrado.
        self.assertEqual(self.request('/api/orders/%d/payments'%order['id'],{'amount':'100','method':'efectivo'},cookie=cookie,csrf=csrf)['status'],201)
        three=post('/api/quotes/%d'%two,action='version')['body']['id'];post('/api/quotes/%d'%three,action='save',items=[line]);post('/api/quotes/%d'%three,action='send')
        only=self.request('/api/quotes/%d'%three,cookie=cookie)['body']['quote']['items'][0]['id']
        blocked=post('/api/quotes/%d'%three,action='decide',approved=str(only),note='Aprobó en el local');self.assertEqual(blocked['status'],409);self.assertIn('pagos registrados',blocked['body']['error'])
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM order_history WHERE order_id=? AND comment LIKE 'Presupuesto%'",(order['id'],)).fetchone()[0],5)


if __name__=='__main__':unittest.main()


class CatalogProTests(unittest.TestCase):
    """Catálogo profesional: códigos, modos de precio, historial, imágenes, catálogo inicial sin duplicados y descuentos autorizados."""
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def test_price_modes_codes_history_images_and_initial_catalog(self):
        cookie,csrf=self.login();post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        self.assertEqual((quotes.price_from(3000,'incluido',1500),quotes.price_from(3000,'agregar',1500),quotes.price_from(3000,'sin_iva',1500)),((3000,1),(3450,1),(3000,0)))
        a=post('/api/catalog',name='Servicio con IVA incluido',category='servicio',price='30',price_mode='incluido',brand='Marca Ficticia')['body']['id']
        b=post('/api/catalog',name='Servicio con IVA agregado',category='servicio',price='30',price_mode='agregar')['body']['id']
        cc=post('/api/catalog',name='Producto sin IVA',category='otro',price='30',price_mode='sin_iva',license_term='1 año',devices='2 dispositivos')['body']['id']
        rows={r['id']:r for r in self.request('/api/catalog?all=1',cookie=cookie)['body']['rows']}
        self.assertEqual([(rows[i]['code'],rows[i]['price_cents'],rows[i]['entered_cents'],rows[i]['taxed']) for i in (a,b,cc)],[('PS-%04d'%a,3000,3000,1),('PS-%04d'%b,3450,3000,1),('PS-%04d'%cc,3000,3000,0)])
        self.assertEqual((rows[cc]['license_term'],rows[cc]['devices'],rows[a]['brand']),('1 año','2 dispositivos','Marca Ficticia'))
        # Sin productos duplicados: mismo nombre (sin distinguir mayúsculas) se rechaza.
        dup=post('/api/catalog',name='servicio con iva incluido',category='servicio',price='1');self.assertEqual(dup['status'],400);self.assertIn('Ya existe',dup['body']['error'])
        self.assertEqual(post('/api/catalog',name='Otro',category='servicio',price='1',price_mode='raro')['status'],400)
        # Historial de precios: solo cuando el precio final cambia.
        post('/api/catalog',id=str(a),name='Servicio con IVA incluido',category='servicio',price='30',price_mode='incluido',brand='Otra marca')
        post('/api/catalog',id=str(a),name='Servicio con IVA incluido',category='servicio',price='35.50',price_mode='incluido')
        history=self.request('/api/catalog/%d/history'%a,cookie=cookie)['body']['rows'];self.assertEqual([(h['old_cents'],h['new_cents'],h['actor']) for h in history],[(3000,3550,'Persona de prueba')])
        with app.connect() as c:
            with self.assertRaises(Exception):c.execute('DELETE FROM catalog_price_history')
        # Imagen: solo imágenes reales y de tamaño acotado.
        import base64
        png=base64.b64encode(b'\x89PNG\r\n\x1a\n'+b'\x00'*120).decode()
        self.assertEqual(self.request('/api/catalog/%d/image'%a,cookie=cookie)['status'],404)
        self.assertEqual(post('/api/catalog/%d/image'%a,data=base64.b64encode(b'<svg onload=alert(1)>').decode())['status'],400)
        self.assertTrue(post('/api/catalog/%d/image'%a,data=png)['body']['image']);self.assertEqual(self.request('/api/catalog/%d/image'%a,cookie=cookie)['body'][:4],b'\x89PNG')
        self.assertEqual(post('/api/catalog/%d/image'%a,action='delete')['status'],200);self.assertEqual(self.request('/api/catalog/%d/image'%a,cookie=cookie)['status'],404)
        # Catálogo entregado por la administración: 19 elementos iniciales y 10 de la segunda carga, una sola vez, con sus precios tal cual.
        listing=self.request('/api/catalog',cookie=cookie)['body'];self.assertEqual(listing['initial_missing'],29)
        first=post('/api/catalog/seed')['body'];again=post('/api/catalog/seed')['body']
        self.assertEqual(((first['created'],first['existing']),(again['created'],again['existing'])),((29,0),(0,29)))
        seeded={r['name']:r for r in self.request('/api/catalog?all=1',cookie=cookie)['body']['rows']}
        self.assertEqual(len(seeded),32);self.assertEqual(self.request('/api/catalog',cookie=cookie)['body']['initial_missing'],0)
        expected={'Programación o flasheo de BIOS corrupta – PlayStation 5':15000,'Mantenimiento parcial – PlayStation 5':5500,'Cambio profesional de metal líquido – PlayStation 5':18900,'Tanque o caja de mantenimiento para impresora Epson':6856,
                  'Microsoft Office Pro Plus 2024 + Windows 11 Pro':18999,'Microsoft Office 365 Pro Plus – 5 dispositivos':15500,'Microsoft Office 2024 Estándar':8599,'Microsoft Office Professional Plus 2021':7999,'Microsoft Office Professional Plus 2024':9999,
                  'Windows 11 Pro – Licencia empresarial':16500,'Chequeo y diagnóstico profesional de memoria RAM':1800,'Windows 11 Home ES – Licencia':6999,'Windows 11 Pro – Actualización':11299,'Kaspersky Standard – Licencia Antivirus de 1 Año':3000,
                  'Kaspersky Standard – Licencia Antivirus de Duración Ilimitada, 1 dispositivo':12500,'McAfee Plus – Licencia Antivirus, 1 dispositivo, 1 año':2500,'Defender Plus – Licencia Antivirus, 1 año':4500,'Norton 360 Estándar – Licencia Antivirus, 1 dispositivo, 1 año':4500,'ESET NOD32 Antivirus – Licencia de 1 Año':4000}
        self.assertEqual({name:seeded[name]['price_cents'] for name in expected},expected)
        self.assertTrue(all(seeded[name]['price_mode']=='incluido' and seeded[name]['taxed']==1 and seeded[name]['entered_cents']==price for name,price in expected.items()))
        self.assertEqual(self.request('/api/catalog?category=seguridad',cookie=cookie)['body']['rows'][0]['category'],'seguridad');self.assertEqual(len(self.request('/api/catalog?q=kaspersky',cookie=cookie)['body']['rows']),2)
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
        for path in ('/api/catalog/seed','/api/catalog/%d/image'%a):self.assertEqual(post(path,data=png)['status'],403)
        self.assertEqual(self.request('/api/catalog/%d/history'%a,cookie=cookie)['status'],403)

    def test_authorized_discount_is_admin_only_and_limited(self):
        cookie,csrf=self.login();post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'quote-discount-request-0001'}),cookie=cookie,csrf=csrf)['body']
        quote=post('/api/orders/%d/quote'%order['id'])['body']['id']
        items=[{'description':'Servicio de cien','category':'servicio','quantity':1,'unit_cents':10000,'taxed':True},{'description':'Producto sin IVA','category':'otro','quantity':3,'unit_cents':3333,'taxed':False}]
        self.assertEqual(quotes.net(10000,500),9500);self.assertEqual(quotes.net(9999,300),9699);self.assertEqual(quotes.net(1,500),1)
        for bad in ('1000','250','-300','abc'):self.assertEqual(post('/api/quotes/%d'%quote,action='save',items=items,discount=bad)['status'],400)
        saved=post('/api/quotes/%d'%quote,action='save',items=items,discount='500')['body']['quote'];t=saved['totals']
        self.assertEqual((saved['discount_bp'],t['gross'],t['discount'],t['quoted']),(500,19999,1000,18999))
        self.assertEqual(t['base_taxed']+t['base_zero']+t['tax'],t['quoted']);self.assertEqual([i['net_cents'] for i in saved['items']],[9500,9499])
        with app.connect() as c:
            row=c.execute('SELECT discount_by,discount_at FROM quotes WHERE id=?',(quote,)).fetchone();self.assertTrue(row['discount_by'] and row['discount_at'])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM quote_events WHERE quote_id=? AND event='descuento'",(quote,)).fetchone()[0],1)
            c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
        # El técnico puede guardar el borrador, pero no tocar el descuento.
        self.assertEqual(post('/api/quotes/%d'%quote,action='save',items=items,discount='0')['status'],403)
        kept=post('/api/quotes/%d'%quote,action='save',items=items,discount='500');self.assertEqual((kept['status'],kept['body']['quote']['discount_bp']),(200,500))
        self.assertEqual(post('/api/quotes/%d'%quote,action='save',items=items)['body']['quote']['discount_bp'],500)
        with app.connect() as c:c.execute("UPDATE users SET role='administrador' WHERE username='demo'");c.commit()
        post('/api/quotes/%d'%quote,action='send');detail=self.request('/api/quotes/%d'%quote,cookie=cookie)['body']['quote'];a,b=[i['id'] for i in detail['items']]
        done=post('/api/quotes/%d'%quote,action='decide',approved=str(a),rejected=str(b),note='Aprobó en el local')['body']['quote']
        self.assertEqual((done['totals']['approved'],done['totals']['rejected']),(9500,9499))
        order_now=self.request('/api/orders/%d'%order['id'],cookie=cookie)['body'];order_now=order_now.get('order',order_now);self.assertEqual(order_now['budget']['total_cents'],9500)
        self.assertEqual(self.request('/api/quotes/%d/pdf'%quote,cookie=cookie)['body'][:4],b'%PDF')
        # La versión siguiente hereda el descuento autorizado.
        self.assertEqual(self.request('/api/quotes/%d'%post('/api/quotes/%d'%quote,action='version')['body']['id'],cookie=cookie)['body']['quote']['discount_bp'],500)


class QuoteIdentityTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data;form=QuoteFlowTests.form

    def test_identity_document_only_when_requested_and_admin_only(self):
        import base64,hashlib
        cookie,csrf=self.login();post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'quote-identity-request-0001'}),cookie=cookie,csrf=csrf)['body']
        quote=post('/api/orders/%d/quote'%order['id'])['body']['id'];items=[{'description':'Servicio ficticio','category':'servicio','quantity':1,'unit_cents':4000,'taxed':True}]
        png=b'\x89PNG\r\n\x1a\n'+b'documento ficticio de prueba '*20;paper=base64.b64encode(png).decode()
        self.assertEqual(quotes.clean_document(paper),('image/png',png));self.assertEqual(quotes.clean_document(base64.b64encode(b'%PDF-1.4 '+b'x'*300).decode())[0],'application/pdf')
        for bad in ('',base64.b64encode(b'<html>'+b'x'*300).decode(),'no es base64 !!',base64.b64encode(b'\x89PNG\r\n\x1a\n'+b'x'*(quotes.DOCUMENT_LIMIT+1)).decode(),base64.b64encode(b'\x89PNG').decode()):self.assertIsNone(quotes.clean_document(bad))
        # El técnico guarda el borrador, pero no decide pedir el documento.
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
        self.assertEqual(post('/api/quotes/%d'%quote,action='save',items=items,require_id=True)['status'],403)
        self.assertEqual(post('/api/quotes/%d'%quote,action='save',items=items)['body']['quote']['require_id'],0)
        with app.connect() as c:c.execute("UPDATE users SET role='administrador' WHERE username='demo'");c.commit()
        saved=post('/api/quotes/%d'%quote,action='save',items=items,require_id=True)['body']['quote'];self.assertEqual((saved['require_id'],saved['identity_document']),(1,None))
        with patch.object(app.mail_pro,'configured',return_value=False):result=post('/api/quotes/%d'%quote,action='send')['body']
        path='/presupuesto/'+result['link'].rsplit('/',1)[1]
        page=self.form(path,{'last4':'0017'})['body'];self.assertIn('name="id_document"',page);self.assertIn('no se comparte con terceros',page)
        passkey=re.search(r'name="passkey" value="([^"]+)"',page)[1];item=int(re.search(r'name="decision_(\d+)"',page)[1])
        base={'passkey':passkey,'action':'decide','name':'Cliente Ficticio','accept':'on','signature':SIGN,'decision_%d'%item:'aprobado'}
        # Sin documento, o con un archivo que no es imagen ni PDF, la aprobación no se registra.
        for wrong in ({},{'id_document':base64.b64encode(b'MZ'+b'x'*400).decode()}):self.assertIn('Adjunta una foto o PDF',self.form(path,dict(base,**wrong))['body'])
        with app.connect() as c:self.assertEqual((c.execute('SELECT COUNT(*) FROM quote_acceptances').fetchone()[0],c.execute('SELECT COUNT(*) FROM quote_documents').fetchone()[0]),(0,0))
        self.assertIn('Aprobado',self.form(path,dict(base,id_document=paper))['body'])
        detail=self.request('/api/quotes/%d'%quote,cookie=cookie)['body']['quote']
        self.assertEqual((detail['status'],detail['identity_document']['mime'],detail['identity_document']['size']),('aprobado','image/png',len(png)));self.assertNotIn('data',detail['identity_document'])
        with app.connect() as c:
            self.assertTrue(quotes.evidence_ok(c,quote));self.assertEqual(json.loads(c.execute('SELECT evidence FROM quote_acceptances').fetchone()[0])['identity_document_sha256'],hashlib.sha256(png).hexdigest())
            with self.assertRaises(Exception):c.execute("UPDATE quote_documents SET mime='image/jpeg'")
        # El archivo no aparece en la página ni en el PDF del cliente; solo lo descarga administración con sesión, y queda auditado.
        self.assertNotIn(paper[:60],self.request(path)['body']);self.assertEqual(self.request('/api/quotes/%d/identity'%quote)['status'],401)
        self.assertEqual(self.request('/api/quotes/%d/identity'%quote,cookie=cookie)['body'],png)
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='quote_identity_viewed'").fetchone()[0],1)
            c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
        self.assertEqual(self.request('/api/quotes/%d/identity'%quote,cookie=cookie)['status'],403);self.assertEqual(post('/api/quotes/%d'%quote,action='remove_identity')['status'],403)
        with app.connect() as c:c.execute("UPDATE users SET role='administrador' WHERE username='demo'");c.commit()
        # Eliminación a pedido: desaparece el archivo; la aceptación y su evidencia siguen íntegras.
        removed=post('/api/quotes/%d'%quote,action='remove_identity');self.assertEqual((removed['status'],removed['body']['quote']['identity_document']),(200,None))
        self.assertEqual(post('/api/quotes/%d'%quote,action='remove_identity')['status'],404);self.assertEqual(self.request('/api/quotes/%d/identity'%quote,cookie=cookie)['status'],404)
        with app.connect() as c:self.assertTrue(quotes.evidence_ok(c,quote));self.assertEqual(c.execute('SELECT COUNT(*) FROM quote_acceptances').fetchone()[0],1)

    def test_quotes_without_request_do_not_ask_for_a_document(self):
        cookie,csrf=self.login();post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'quote-identity-request-0002'}),cookie=cookie,csrf=csrf)['body']
        quote=post('/api/orders/%d/quote'%order['id'])['body']['id'];post('/api/quotes/%d'%quote,action='save',items=[{'description':'Servicio ficticio','category':'servicio','quantity':1,'unit_cents':4000,'taxed':True}])
        with patch.object(app.mail_pro,'configured',return_value=False):result=post('/api/quotes/%d'%quote,action='send')['body']
        path='/presupuesto/'+result['link'].rsplit('/',1)[1];page=self.form(path,{'last4':'0017'})['body'];self.assertNotIn('id_document',page)
        passkey=re.search(r'name="passkey" value="([^"]+)"',page)[1];item=int(re.search(r'name="decision_(\d+)"',page)[1])
        self.assertIn('Aprobado',self.form(path,{'passkey':passkey,'action':'decide','name':'Cliente Ficticio','accept':'on','signature':SIGN,'decision_%d'%item:'aprobado','id_document':'ignorado'})['body'])
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM quote_documents').fetchone()[0],0)


class QuoteBriefTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def test_each_unit_shows_its_own_quote_summary(self):
        cookie,csrf=self.login();post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        make=lambda key,**extra:self.request('/api/orders',self.order_data(dict({'email':'cliente@example.invalid','request_key':'quote-brief-request-'+key},**extra)),cookie=cookie,csrf=csrf)['body']
        first=make('0001',serial='BRIEF-1');second=make('0002',serial='BRIEF-2',group_order_id=str(first['id']),new_unit='1')
        units=lambda oid:{u['id']:u for u in (lambda d:d.get('order',d))(self.request('/api/orders/%d'%oid,cookie=cookie)['body'])['group']['units']}
        self.assertEqual([u['quote'] for u in units(first['id']).values()],[None,None]);self.assertTrue(all(u['type_label'] for u in units(first['id']).values()))
        quote=post('/api/orders/%d/quote'%second['id'])['body']['id']
        post('/api/quotes/%d'%quote,action='save',items=[{'description':'Servicio ficticio','category':'servicio','quantity':2,'unit_cents':2000,'taxed':True},{'description':'Repuesto ficticio','category':'repuesto','quantity':1,'unit_cents':1500,'taxed':True}])
        # El resumen pertenece solo al equipo del presupuesto; el otro equipo sigue sin presupuesto, se mire la orden desde cualquiera de los dos.
        for seen in (first['id'],second['id']):
            group=units(seen);self.assertIsNone(group[first['id']]['quote']);brief=group[second['id']]['quote']
            self.assertEqual((brief['id'],brief['status'],brief['editable'],brief['lines'],brief['quoted_cents'],brief['approved_cents'],brief['pending_cents']),(quote,'borrador',True,2,5500,0,5500))
        with patch.object(app.mail_pro,'configured',return_value=False):post('/api/quotes/%d'%quote,action='send')
        ids=[str(i['id']) for i in self.request('/api/quotes/%d'%quote,cookie=cookie)['body']['quote']['items']]
        self.assertEqual(post('/api/quotes/%d'%quote,action='decide',note='Aprobó por teléfono (ficticio)',approved=ids[0],rejected=ids[1])['status'],200)
        unit=units(first['id'])[second['id']];brief=unit['quote']
        self.assertEqual((brief['status'],brief['editable'],brief['approved_cents'],brief['rejected_cents'],brief['pending_cents'],unit['budget_cents'],unit['balance_cents']),('parcial',False,4000,1500,0,4000,4000))
        self.assertEqual(units(first['id'])[first['id']]['budget_cents'],0)

    def test_approved_amounts_are_locked_and_units_stay_independent(self):
        cookie,csrf=self.login();post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        make=lambda key,**extra:self.request('/api/orders',self.order_data(dict({'email':'cliente@example.invalid','request_key':'quote-lock-request-'+key},**extra)),cookie=cookie,csrf=csrf)['body']
        first=make('0001',serial='LOCK-1');second=make('0002',serial='LOCK-2',group_order_id=str(first['id']),new_unit='1')
        order=lambda oid:(lambda d:d.get('order',d))(self.request('/api/orders/%d'%oid,cookie=cookie)['body'])
        work=lambda oid,**extra:self.request('/api/orders/%d/workspace'%oid,dict({'revision':order(oid)['revision'],'status':'pendiente','priority':'normal','assigned_to':'','estimated_delivery':'','problem':'Trabajo ficticio','internal_notes':'','findings':'','recommendations':'','comment':''},**extra),cookie=cookie,csrf=csrf)
        # Sin presupuesto aprobado los importes manuales se editan; editar E02 no toca E01.
        self.assertEqual(work(second['id'],status='reparacion',priority='alta',internal_notes='Nota de E02',findings='Hallazgo de E02',lines=[{'category':'labor','description':'Manual','amount_cents':1000}])['status'],200)
        one,two=order(first['id']),order(second['id'])
        self.assertEqual((one['status'],one['priority'],one['internal_notes'],one['findings'],one['budget']['total_cents'],one['budget_locked']),('pendiente','normal','','',0,''))
        self.assertEqual((two['status'],two['priority'],two['internal_notes'],two['findings'],two['budget']['total_cents'],two['budget_locked']),('reparacion','alta','Nota de E02','Hallazgo de E02',1000,''))
        # Presupuesto aprobado en E01: sus importes quedan fijados.
        quote=post('/api/orders/%d/quote'%first['id'])['body']['id'];post('/api/quotes/%d'%quote,action='save',items=[{'description':'Servicio ficticio','category':'servicio','quantity':1,'unit_cents':4000,'taxed':True}])
        with patch.object(app.mail_pro,'configured',return_value=False):post('/api/quotes/%d'%quote,action='send')
        item=str(self.request('/api/quotes/%d'%quote,cookie=cookie)['body']['quote']['items'][0]['id'])
        self.assertEqual(post('/api/quotes/%d'%quote,action='decide',note='Aprobó por teléfono (ficticio)',approved=item)['status'],200)
        locked=order(first['id']);code=locked['budget_locked'];self.assertTrue(code.endswith('-P1'));self.assertEqual(locked['budget']['total_cents'],4000)
        denied=work(first['id'],lines=[{'category':'labor','description':'Alterado','amount_cents':1}]);self.assertEqual(denied['status'],409);self.assertIn(code,denied['body']['error'])
        self.assertEqual(work(first['id'],lines=[])['status'],409)
        # Guardar el informe técnico sin tocar importes (o reenviando los mismos) conserva lo autorizado.
        self.assertEqual(work(first['id'],findings='Diagnóstico de E01')['status'],200)
        same=[{'category':l['category'],'description':l['description'],'amount_cents':l['amount_cents']} for l in order(first['id'])['budget_lines']]
        self.assertEqual(work(first['id'],findings='Diagnóstico de E01',recommendations='Limpieza anual',lines=same)['status'],200)
        kept=order(first['id']);self.assertEqual((kept['budget']['total_cents'],len(kept['budget_lines']),kept['findings'],kept['recommendations'],kept['money']['balance_cents']),(4000,1,'Diagnóstico de E01','Limpieza anual',4000))
        self.assertEqual((order(second['id'])['findings'],order(second['id'])['budget']['total_cents']),('Hallazgo de E02',1000))
        # Entregar exige saldo en cero también con importes fijados.
        self.assertEqual(work(first['id'],status='entregado')['status'],409)
        # Mientras se prepara una versión nueva sigue vigente (y fijado) lo que el cliente ya autorizó.
        post('/api/quotes/%d'%quote,action='version');again=order(first['id']);self.assertEqual((again['budget_locked'],again['budget']['total_cents']),(code,4000))

    def test_order_detail_shows_current_contact_and_keeps_reception_copy(self):
        cookie,csrf=self.login()
        made=self.request('/api/orders',self.order_data({'email':'antes@example.invalid','request_key':'contact-current-request-01'}),cookie=cookie,csrf=csrf)['body']
        order=lambda:(lambda d:d.get('order',d))(self.request('/api/orders/%d'%made['id'],cookie=cookie)['body'])
        first=order();self.assertEqual(first['email'],'antes@example.invalid');self.assertNotIn('reception_email',first)
        with app.connect() as c:c.execute("UPDATE clients SET email='ahora@example.invalid'");c.commit()
        now=order();self.assertEqual((now['email'],now['reception_email']),('ahora@example.invalid','antes@example.invalid'));self.assertNotIn('reception_phone',now)


class QuotePendingTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data;form=QuoteFlowTests.form

    def client(self,link,choices,**extra):
        path='/presupuesto/'+link.rsplit('/',1)[1];page=self.form(path,{'last4':'0017'})['body']
        passkey=re.search(r'name="passkey" value="([^"]+)"',page)[1];ids=[int(v) for v in dict.fromkeys(re.findall(r'name="decision_(\d+)"',page))]
        self.assertIn('Lo decidiré después',page)
        return self.form(path,dict({'passkey':passkey,'action':'decide','name':'Cliente Ficticio','accept':'on','signature':SIGN},**{'decision_%d'%i:v for i,v in zip(ids,choices)},**extra))['body']

    def test_pending_items_move_to_a_follow_up_version_and_execution_is_tracked(self):
        cookie,csrf=self.login();post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'quote-pending-request-0001'}),cookie=cookie,csrf=csrf)['body']
        detail=lambda:(lambda d:d.get('order',d))(self.request('/api/orders/%d'%order['id'],cookie=cookie)['body'])
        quote=post('/api/orders/%d/quote'%order['id'])['body']['id']
        post('/api/quotes/%d'%quote,action='save',items=[{'description':'Mantenimiento ficticio','category':'servicio','quantity':1,'unit_cents':3000,'taxed':True},{'description':'Disco ficticio','category':'repuesto','quantity':1,'unit_cents':8000,'taxed':True},{'description':'Licencia ficticia','category':'licencia','quantity':1,'unit_cents':2500,'taxed':False}])
        with patch.object(app.mail_pro,'configured',return_value=False):link=post('/api/quotes/%d'%quote,action='send')['body']['link']
        # Dejar todo pendiente no registra nada.
        self.assertIn('Decide al menos un servicio',self.client(link,['pendiente','pendiente','pendiente']))
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM quote_acceptances').fetchone()[0],0)
        done=self.client(link,['aprobado','pendiente','rechazado']);self.assertIn('Por decidir',done);self.assertIn('nuevo presupuesto',done)
        first=self.request('/api/quotes/%d'%quote,cookie=cookie)['body']['quote']
        self.assertEqual((first['status'],[i['status'] for i in first['items']],first['totals']['approved'],first['totals']['pending'],first['totals']['rejected']),('parcial',['aprobado','pendiente','rechazado'],3000,8000,2500))
        now=detail();self.assertEqual((now['budget']['total_cents'],now['budget_locked'],[(i['description'],i['net_cents'],i['execution'],i['signed']) for i in now['authorized_items']]),(3000,first['code'],[('Mantenimiento ficticio',3000,'pendiente',True)]))
        # Ejecución: solo partidas aprobadas, valores válidos, y queda en el historial.
        approved_id,pending_id=str(first['items'][0]['id']),str(first['items'][1]['id'])
        self.assertEqual(post('/api/quotes/%d'%quote,action='execution',item=approved_id,value='proceso')['status'],200)
        self.assertEqual(post('/api/quotes/%d'%quote,action='execution',item=approved_id,value='terminado')['status'],400)
        self.assertEqual(post('/api/quotes/%d'%quote,action='execution',item=pending_id,value='realizado')['status'],409)
        self.assertEqual(detail()['authorized_items'][0]['execution'],'proceso')
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM quote_events WHERE quote_id=? AND event='ejecucion'",(quote,)).fetchone()[0],1)
        # Versión de continuación: solo la partida pendiente; lo autorizado sigue vigente y fijado mientras se prepara y se envía.
        follow=post('/api/quotes/%d'%quote,action='pending_version');self.assertEqual(follow['status'],201);second=follow['body']['id']
        draft=self.request('/api/quotes/%d'%second,cookie=cookie)['body']['quote'];self.assertEqual(([i['description'] for i in draft['items']],draft['continues_id']),(['Disco ficticio'],quote))
        self.assertEqual((detail()['budget']['total_cents'],detail()['budget_locked']),(3000,first['code']))
        with patch.object(app.mail_pro,'configured',return_value=False):link2=post('/api/quotes/%d'%second,action='send')['body']['link']
        self.assertIn('Aprobado',self.client(link2,['aprobado']))
        final=detail();code2=self.request('/api/quotes/%d'%second,cookie=cookie)['body']['quote']['code']
        # Cada partida se cuenta una sola vez: 3000 de la primera versión + 8000 de la continuación.
        self.assertEqual((final['budget']['total_cents'],final['money']['balance_cents'],final['budget_locked'],[(i['description'],i['quote_code'],i['execution']) for i in final['authorized_items']]),(11000,11000,code2,[('Mantenimiento ficticio',first['code'],'proceso'),('Disco ficticio',code2,'pendiente')]))
        self.assertEqual(len(final['budget_lines']),2)
        with app.connect() as c:self.assertTrue(quotes.evidence_ok(c,quote) and quotes.evidence_ok(c,second))
        # Sin partidas pendientes no se crea una continuación.
        self.assertEqual(post('/api/quotes/%d'%second,action='pending_version')['status'],409)

    def test_follow_up_rejection_keeps_previous_authorization_and_roles(self):
        cookie,csrf=self.login();post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'quote-pending-request-0002'}),cookie=cookie,csrf=csrf)['body']
        detail=lambda:(lambda d:d.get('order',d))(self.request('/api/orders/%d'%order['id'],cookie=cookie)['body'])
        quote=post('/api/orders/%d/quote'%order['id'])['body']['id']
        post('/api/quotes/%d'%quote,action='save',items=[{'description':'Servicio A','category':'servicio','quantity':1,'unit_cents':2000,'taxed':True},{'description':'Servicio B','category':'servicio','quantity':1,'unit_cents':5000,'taxed':True}])
        with patch.object(app.mail_pro,'configured',return_value=False):link=post('/api/quotes/%d'%quote,action='send')['body']['link']
        self.client(link,['aprobado','pendiente'])
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
        # El técnico marca la ejecución, pero no crea versiones ni decide por el cliente.
        item=str(self.request('/api/quotes/%d'%quote,cookie=cookie)['body']['quote']['items'][0]['id'])
        self.assertEqual(post('/api/quotes/%d'%quote,action='execution',item=item,value='realizado')['status'],200)
        self.assertEqual(post('/api/quotes/%d'%quote,action='pending_version')['status'],403)
        with app.connect() as c:c.execute("UPDATE users SET role='administrador' WHERE username='demo'");c.commit()
        second=post('/api/quotes/%d'%quote,action='pending_version')['body']['id']
        with patch.object(app.mail_pro,'configured',return_value=False):link2=post('/api/quotes/%d'%second,action='send')['body']['link']
        self.client(link2,['rechazado'],signature='')
        final=detail();self.assertEqual((final['budget']['total_cents'],[(i['description'],i['execution']) for i in final['authorized_items']]),(2000,[('Servicio A','realizado')]));self.assertTrue(final['budget_locked'])


class QuotePriorityTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data;form=QuoteFlowTests.form

    def test_money_format_for_documents(self):
        self.assertEqual([quotes.usd(v) for v in (0,5,4500,99999,100000,123456789,-1000)],['$0,00','$0,05','$45,00','$999,99','$1.000,00','$1.234.567,89','-$10,00'])

    def test_additions_icons_tax_pending_and_no_duplicates(self):
        import catalog_icons
        cookie,csrf=self.login();post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        # Un mantenimiento de PC de escritorio previo, con otro nombre y precio: debe actualizarse, no duplicarse.
        old=post('/api/catalog',name='Mantenimiento de PC de escritorio',category='servicio',price='40',price_mode='incluido')['body']['id']
        first=post('/api/catalog/seed')['body'];self.assertEqual((first['created'],first['updated'],first['total']),(19+9,1,29))
        again=post('/api/catalog/seed')['body'];self.assertEqual((again['created'],again['updated'],again['existing']),(0,0,29))
        data=self.request('/api/catalog?all=1',cookie=cookie)['body'];rows={r['name']:r for r in data['rows']};self.assertEqual(len(rows),29);self.assertEqual(data['initial_missing'],0)
        expected={'Cambio de pantalla de portátil de 14 pulgadas':(11500,'otro','pantalla',0),'Cambio de pantalla de portátil de 15,6 pulgadas':(15000,'otro','pantalla',0),'Cambio de pantalla de portátil gamer de 15,6 pulgadas':(28000,'otro','pantalla_gamer',0),
                  'Reparación de bisagras de portátil de 14 pulgadas':(3200,'servicio','bisagra',0),'Reparación de bisagras de portátil de 15,6 pulgadas':(4800,'servicio','bisagra',0),'Pegado de bisagras de portátil de 14 pulgadas':(3500,'servicio','bisagra',0),'Pegado de bisagras de portátil de 15,6 pulgadas':(4800,'servicio','bisagra',0),
                  'Mantenimiento de PC de escritorio y cambio de pasta térmica del CPU, sin tarjeta gráfica dedicada':(4500,'servicio','escritorio',0),'Mantenimiento de PC Gamer con cambio de pasta térmica del CPU':(7500,'servicio','pc_gamer',0),'Creación de nueva BIOS para computadora portátil':(13000,'servicio','bios',0)}
        for name,(price,category,icon,pending) in expected.items():
            row=rows[name];self.assertEqual((row['price_cents'],row['entered_cents'],row['category'],row['icon'],row['tax_pending']),(price,price,category,icon,pending),name)
        # El mantenimiento de escritorio conservó su identificador y dejó constancia del cambio de precio.
        desk=rows['Mantenimiento de PC de escritorio y cambio de pasta térmica del CPU, sin tarjeta gráfica dedicada'];self.assertEqual(desk['id'],old)
        self.assertEqual([(h['old_cents'],h['new_cents']) for h in self.request('/api/catalog/%d/history'%old,cookie=cookie)['body']['rows']],[(4000,4500)])
        self.assertEqual(data['categories']['otro'],'Productos');self.assertEqual(set(data['priorities']),{'necesario','obligatorio','opcional'});self.assertEqual(data['priorities']['opcional']['color'],'#38BDF8')
        # Iconos: todos los elementos tienen uno válido; los del catálogo inicial se proponen por categoría y palabras clave.
        self.assertTrue(all(r['icon'] in data['icons'] for r in rows.values()))
        self.assertEqual((rows['ESET NOD32 Antivirus – Licencia de 1 Año']['icon'],rows['Windows 11 Home ES – Licencia']['icon'],rows['Microsoft Office 2024 Estándar']['icon'],rows['Mantenimiento parcial – PlayStation 5']['icon']),('antivirus','windows','ofimatica','consola'))
        self.assertEqual(catalog_icons.guess('otro','Sin coincidencias'),'producto');self.assertEqual(catalog_icons.valid('inexistente'),'generico')
        # Reemplazo manual del icono; activar o desactivar el elemento no lo pierde. Un icono inválido se rechaza.
        bios=rows['Creación de nueva BIOS para computadora portátil'];base={'id':str(bios['id']),'name':bios['name'],'description':bios['description'],'category':'servicio','price':'130.00','price_mode':'incluido'}
        self.assertEqual(post('/api/catalog',**dict(base,icon='no-existe'))['status'],400)
        post('/api/catalog',**dict(base,icon='repuesto',tax_pending=True));post('/api/catalog',**dict(base,available=False))
        now={r['id']:r for r in self.request('/api/catalog?all=1',cookie=cookie)['body']['rows']}[bios['id']];self.assertEqual((now['icon'],now['available'],now['tax_pending']),('repuesto',0,1))
        # Confirmar el IVA es un acto expreso de administración.
        post('/api/catalog',**dict(base,price_mode='agregar',tax_confirmed=True,available=True))
        now={r['id']:r for r in self.request('/api/catalog?all=1',cookie=cookie)['body']['rows']}[bios['id']];self.assertEqual((now['tax_pending'],now['price_cents'],now['entered_cents']),(0,14950,13000))

    def test_priority_is_saved_shown_and_never_approves(self):
        cookie,csrf=self.login();post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        post('/api/catalog/seed');rows={r['name']:r for r in self.request('/api/catalog?all=1',cookie=cookie)['body']['rows']}
        screen,hinge=rows['Cambio de pantalla de portátil de 14 pulgadas'],rows['Reparación de bisagras de portátil de 14 pulgadas']
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'quote-priority-request-001'}),cookie=cookie,csrf=csrf)['body']
        quote=post('/api/orders/%d/quote'%order['id'])['body']['id']
        line=lambda item,priority,**extra:dict({'catalog_id':item['id'],'description':item['name'],'category':item['category'],'quantity':1,'unit_cents':item['price_cents'],'taxed':bool(item['taxed']),'priority':priority},**extra)
        free={'description':'Limpieza de teclado ficticia','category':'servicio','quantity':2,'unit_cents':60000,'taxed':True}
        self.assertEqual(post('/api/quotes/%d'%quote,action='save',items=[line(screen,'urgente')])['status'],400)
        saved=post('/api/quotes/%d'%quote,action='save',items=[line(screen,'obligatorio'),line(hinge,'necesario'),dict(free,priority='opcional'),dict(free,description='Sin clasificar ficticio')])['body']['quote']
        self.assertEqual([(i['priority'],i['priority_label'],i['icon'],i['status']) for i in saved['items']],[('obligatorio','Obligatorio','pantalla','pendiente'),('necesario','Necesario','bisagra','pendiente'),('opcional','Opcional','mantenimiento','pendiente'),('','','servicio','pendiente')])
        # La clasificación no cambia importes ni autoriza: el total es la suma de las partidas y nada pasa a lo aprobado.
        self.assertEqual((saved['totals']['quoted'],saved['totals']['approved']),(11500+3200+120000+120000,0))
        detail=lambda:(lambda d:d.get('order',d))(self.request('/api/orders/%d'%order['id'],cookie=cookie)['body']);self.assertEqual((detail()['authorized_items'],detail()['budget']['total_cents']),([],0))
        # Se conserva al reabrir y al crear una versión; el PDF se genera con iconos, clasificación e importes con $.
        self.assertEqual([i['priority'] for i in self.request('/api/quotes/%d'%quote,cookie=cookie)['body']['quote']['items']],['obligatorio','necesario','opcional',''])
        pdf=self.request('/api/quotes/%d/pdf'%quote,cookie=cookie)['body'];self.assertEqual(pdf[:4],b'%PDF')
        # No se envía mientras el IVA de un elemento del catálogo esté marcado como «por confirmar».
        post('/api/catalog',id=str(hinge['id']),name=hinge['name'],description=hinge['description'],category='servicio',price='32.00',price_mode='incluido',tax_pending=True)
        with patch.object(app.mail_pro,'configured',return_value=False):blocked=post('/api/quotes/%d'%quote,action='send')
        self.assertEqual(blocked['status'],409);self.assertIn('falta confirmar el IVA',blocked['body']['error']);self.assertIn('Reparación de bisagras',blocked['body']['error'])
        post('/api/catalog',id=str(hinge['id']),name=hinge['name'],description=hinge['description'],category='servicio',price='32.00',price_mode='incluido',tax_confirmed=True)
        with patch.object(app.mail_pro,'configured',return_value=False):sent=post('/api/quotes/%d'%quote,action='send')
        self.assertEqual(sent['status'],200);path='/presupuesto/'+sent['body']['link'].rsplit('/',1)[1]
        page=self.form(path,{'last4':'0017'})['body']
        for text in ('data-priority="obligatorio">Obligatorio<','data-priority="necesario">Necesario<','data-priority="opcional">Opcional<','class="quote-icon"','$1.200,00','$2.547,00'):self.assertIn(text,page)
        self.assertEqual(page.count('class="quote-priority"'),3);self.assertNotIn('style=',page)
        version=post('/api/quotes/%d'%quote,action='version')['body']['id']
        self.assertEqual([i['priority'] for i in self.request('/api/quotes/%d'%version,cookie=cookie)['body']['quote']['items']],['obligatorio','necesario','opcional',''])


class QuoteDraftRemovalTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def test_only_unsent_drafts_are_removed_and_history_is_kept(self):
        cookie,csrf=self.login();post=lambda path,**body:self.request(path,body,cookie=cookie,csrf=csrf)
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'quote-removal-request-0001'}),cookie=cookie,csrf=csrf)['body']
        other=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','serial':'OTRO-1','request_key':'quote-removal-request-0002'}),cookie=cookie,csrf=csrf)['body']
        listing=lambda oid=order['id']:self.request('/api/orders/%d/quote'%oid,cookie=cookie)['body']
        items=[{'description':'Servicio ficticio','category':'servicio','quantity':1,'unit_cents':4000,'taxed':True}]
        first=post('/api/orders/%d/quote'%order['id'])['body']['id'];post('/api/quotes/%d'%first,action='save',items=items)
        keep=post('/api/orders/%d/quote'%other['id'])['body']['id'];post('/api/quotes/%d'%keep,action='save',items=items)
        card=listing()['versions'][0];self.assertEqual((card['status'],card['removable'],card['lines'],card['quoted_cents']),('borrador',True,1,4000))
        # Enviado: ya no es eliminable (se anula, no se elimina).
        with patch.object(app.mail_pro,'configured',return_value=False):post('/api/quotes/%d'%first,action='send')
        self.assertFalse(listing()['versions'][0]['removable']);denied=post('/api/quotes/%d'%first,action='delete_draft');self.assertEqual(denied['status'],409);self.assertIn('se anula, no se elimina',denied['body']['error'])
        # Aprobado: tampoco. Su nueva versión en borrador sí, y eliminarla no toca la aprobada ni el otro equipo.
        item=str(self.request('/api/quotes/%d'%first,cookie=cookie)['body']['quote']['items'][0]['id']);post('/api/quotes/%d'%first,action='decide',note='Aprobó por teléfono (ficticio)',approved=item)
        self.assertEqual(post('/api/quotes/%d'%first,action='delete_draft')['status'],409)
        second=post('/api/quotes/%d'%first,action='version')['body']['id'];self.assertEqual([(v['version'],v['status'],v['removable']) for v in listing()['versions']],[(2,'borrador',True),(1,'aprobado',False)])
        detail=lambda:(lambda d:d.get('order',d))(self.request('/api/orders/%d'%order['id'],cookie=cookie)['body']);before=(detail()['budget']['total_cents'],len(detail()['authorized_items']))
        # Un técnico que no creó el borrador no lo elimina.
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.execute('UPDATE quotes SET created_by=NULL WHERE id=?',(second,));c.commit()
        self.assertEqual(post('/api/quotes/%d'%second,action='delete_draft')['status'],403)
        with app.connect() as c:c.execute("UPDATE users SET role='administrador' WHERE username='demo'");c.commit()
        removed=post('/api/quotes/%d'%second,action='delete_draft');self.assertEqual((removed['status'],removed['body']['deleted']),(200,removed['body']['deleted']));self.assertTrue(removed['body']['deleted'].endswith('-P2'))
        # No reaparece, no se puede abrir ni volver a eliminar; lo aprobado y el otro equipo siguen intactos.
        self.assertEqual([(v['version'],v['status']) for v in listing()['versions']],[(1,'aprobado')]);self.assertEqual(listing()['current']['id'],first)
        self.assertEqual(self.request('/api/quotes/%d'%second,cookie=cookie)['status'],404);self.assertEqual(post('/api/quotes/%d'%second,action='delete_draft')['status'],404)
        self.assertEqual((detail()['budget']['total_cents'],len(detail()['authorized_items'])),before);self.assertEqual((before,detail()['budget_locked'].endswith('-P1')),((4000,1),True))
        self.assertEqual([(v['id'],v['status']) for v in listing(other['id'])['versions']],[(keep,'borrador')])
        # El registro y su historial se conservan para auditoría; el siguiente presupuesto no reutiliza el número eliminado.
        with app.connect() as c:
            row=c.execute('SELECT status,deleted_at,deleted_by FROM quotes WHERE id=?',(second,)).fetchone();self.assertTrue(row['status']=='borrador' and row['deleted_at'] and row['deleted_by'])
            self.assertEqual([r[0] for r in c.execute('SELECT event FROM quote_events WHERE quote_id=? ORDER BY id',(second,))][-1],'eliminado')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='quote_draft_deleted'").fetchone()[0],1);self.assertTrue(quotes.evidence_ok(c,first) is not None)
        third=post('/api/quotes/%d'%first,action='version')['body']['id'];self.assertTrue(self.request('/api/quotes/%d'%third,cookie=cookie)['body']['quote']['code'].endswith('-P3'))
        brief=detail()['group']['units'][0]['quote'];self.assertEqual((brief['id'],brief['approved_count'],brief['pending_count'],brief['authorized_cents']),(third,0,1,4000))

