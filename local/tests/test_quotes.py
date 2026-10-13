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
        # Catálogo inicial: 19 elementos, una sola vez, con sus precios finales tal cual.
        listing=self.request('/api/catalog',cookie=cookie)['body'];self.assertEqual(listing['initial_missing'],19)
        first=post('/api/catalog/seed')['body'];again=post('/api/catalog/seed')['body']
        self.assertEqual(((first['created'],first['existing']),(again['created'],again['existing'])),((19,0),(0,19)))
        seeded={r['name']:r for r in self.request('/api/catalog?all=1',cookie=cookie)['body']['rows']}
        self.assertEqual(len(seeded),22);self.assertEqual(self.request('/api/catalog',cookie=cookie)['body']['initial_missing'],0)
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

