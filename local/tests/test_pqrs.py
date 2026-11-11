"""1.5.278 · PQRS: registro público validado en el servidor con código único y sin duplicados, enlace con una orden solo con la
identidad del cliente, adjuntos por partes con el tipo real comprobado, seguimiento privado sin datos personales ni notas internas,
permisos por rol en el servidor, avisos registrados aunque el correo falle, WhatsApp solo con autorización, conservación sin borrado
y exportación segura. Base temporal, datos ficticios, sin correos ni WhatsApp reales."""
import base64
import hashlib
import json
import unittest
from unittest.mock import patch
import test_app
import test_whatsapp_business as wab
import app,pqrs

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


class PqrsTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data
    _w=vars(wab.WhatsAppBusinessTests);session=_w['session'];order=_w['order'];technician=_w['technician'];enable=_w['enable']

    def form(self,key='0001',**extra):
        return dict({'category':'queja','name':'Cliente Ficticio Prueba','email':'cliente@example.invalid','phone':'0991234567','site':'Matriz',
                     'subject':'Demora en la entrega','description':'El equipo no se entregó en la fecha indicada (texto ficticio de prueba).',
                     'privacy_consent':True,'whatsapp_consent':False,'request_key':'pqrs-prueba-solicitud-'+key,'locale':'es-EC'},**extra)

    def submit(self,**extra):
        got=self.request('/api/public/pqrs',self.form(**extra))
        self.assertIn(got['status'],(200,201),got['body']);return got['body']

    def upload(self,draft,raw,name='foto.png',kind='image/png'):
        start=self.request('/api/public/pqrs/upload/start',{'draft':draft,'name':name,'size':str(len(raw)),'sha256':hashlib.sha256(raw).hexdigest(),'type':kind})
        if start['status']!=200:return start
        self.assertEqual(self.request('/api/public/pqrs/upload/part',{'draft':draft,'token':start['body']['token'],'index':'0','data':base64.b64encode(raw).decode()})['status'],200)
        return self.request('/api/public/pqrs/upload/finish',{'draft':draft,'token':start['body']['token']})

    def case(self,code):
        with app.connect() as c:return dict(c.execute('SELECT * FROM pqrs_cases WHERE code=?',(code,)).fetchone())

    def test_public_page_options_and_registration_with_unique_codes(self):
        page=self.request('/pqrs')['body'];page=page if isinstance(page,str) else page.decode()
        self.assertIn('data-i18n-public',page);self.assertLess(page.index('/static/i18n.js'),page.index('/static/pqrs.js'))
        options=self.request('/api/public/pqrs/options')['body']
        self.assertEqual((options['categories'],options['sites'],options['max_files'],options['max_bytes']),(['peticion','queja','reclamo','sugerencia'],['Matriz'],3,10*1024*1024))
        year=app.reception_now().year
        first=self.submit();second=self.submit(key='0002',category='sugerencia',locale='en-US')
        self.assertEqual((first['code'],second['code']),('PQRS-%d-0001'%year,'PQRS-%d-0002'%year))
        self.assertEqual((first['status'],second['language']),('recibida','en-US'))
        again=self.request('/api/public/pqrs',self.form())  # misma solicitud enviada dos veces: no se duplica
        self.assertEqual((again['status'],again['body']['code'],again['body']['duplicate']),(200,first['code'],True))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM pqrs_cases').fetchone()[0],2)
            row=c.execute('SELECT * FROM pqrs_cases WHERE code=?',(first['code'],)).fetchone()
            self.assertEqual((row['phone'],row['status'],row['privacy_consent'],row['order_id']),('+593991234567','recibida',1,None))
            self.assertNotEqual(row['track_hash'],first['token']);self.assertEqual(row['track_hash'],pqrs.token_hash(first['token']))  # el token no se guarda legible
            notice=c.execute('SELECT event,channel,result,attempts FROM pqrs_notifications WHERE case_id=?',(row['id'],)).fetchone()
            self.assertEqual(tuple(notice),('recibida','email','sin_configurar',1))  # sin correo configurado: queda anotado y el caso sigue registrado
            self.assertEqual(c.execute("SELECT kind FROM pqrs_events WHERE case_id=?",(row['id'],)).fetchone()[0],'creada')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='pqrs_created'").fetchone()[0],2)

    def test_validation_errors_and_rate_limit(self):
        got=self.request('/api/public/pqrs',self.form(category='otra',name='Ana',email='malo',phone='12',site='Otra sede',subject='Hey',description='corta',privacy_consent=False,order_code='PCD 2026 ¿?'))
        self.assertEqual(got['status'],400)
        self.assertEqual(set(got['body']['fields']),{'category','name','email','phone','site','subject','description','privacy_consent','order_code'})
        self.assertEqual(self.request('/api/public/pqrs',self.form(request_key='corta'))['status'],400)
        for i in range(4):self.submit(key='%04d'%(100+i))  # los dos envíos con errores también cuentan para el límite (6 por hora)
        self.assertEqual(self.request('/api/public/pqrs',self.form(key='0200'))['status'],429)

    def test_order_link_requires_the_client_identity_and_reveals_nothing(self):
        cookie,csrf,post=self.session();oid=self.order(post,'pqrs-0001')
        with app.connect() as c:code=c.execute('SELECT code FROM orders WHERE id=?',(oid,)).fetchone()[0]
        good=self.submit(key='0010',order_code=code,identification='0100000017');bad=self.submit(key='0011',order_code=code,identification='0999999999')
        self.assertEqual(set(good),set(bad))  # la respuesta no indica si la orden existe o si la identidad coincide
        self.assertEqual((self.case(good['code'])['order_id'],self.case(good['code'])['order_verified']),(oid,1))
        self.assertEqual((self.case(bad['code'])['order_id'],self.case(bad['code'])['order_verified'],self.case(bad['code'])['order_code']),(None,0,code))

    def test_attachments_are_checked_by_content_size_and_count(self):
        draft='borrador-prueba-0000000001'
        ok=self.upload(draft,PNG);self.assertEqual((ok['status'],ok['body']['mime']),(200,'image/png'))
        fake=self.upload(draft,b'MZ\x90\x00'+b'\x00'*200,'factura.pdf.exe','application/pdf');self.assertEqual(fake['status'],400)  # un ejecutable con otro nombre se rechaza
        big=self.request('/api/public/pqrs/upload/start',{'draft':draft,'name':'grande.pdf','size':str(10*1024*1024+1),'sha256':'0'*64,'type':'application/pdf'})
        self.assertEqual(big['status'],400)
        self.upload(draft,PNG,'dos.png');self.upload(draft,PNG,'tres.png')
        self.assertEqual(self.upload(draft,PNG,'cuatro.png')['status'],400)  # máximo 3
        with app.connect() as c:tokens=[r[0] for r in c.execute("SELECT token FROM pqrs_uploads WHERE draft=? AND status='lista'",(draft,))]
        made=self.submit(key='0020',draft=draft,files=','.join(tokens))
        cookie,csrf,post=self.session()
        detail=self.request('/api/pqrs/%d'%self.case(made['code'])['id'],cookie=cookie)['body']
        self.assertEqual(len(detail['files']),3)
        fid=detail['files'][0]['id'];part=self.request('/api/pqrs/%d/files/%d/0'%(detail['id'],fid),cookie=cookie)['body']
        self.assertEqual(base64.b64decode(part['data']),PNG)
        view=self.request('/api/public/pqrs/track',{'code':made['code'],'token':made['token']})['body']
        self.assertEqual(view['files'],3);self.assertNotIn('data',json.dumps(view))  # el seguimiento público no entrega adjuntos
        with app.connect() as c:
            with self.assertRaises(Exception):c.execute('DELETE FROM pqrs_uploads WHERE id=?',(fid,))

    def test_public_tracking_is_private_and_client_can_reply(self):
        made=self.submit(key='0030')
        self.assertEqual(self.request('/api/public/pqrs/track',{'code':made['code'],'token':'x'*32})['status'],404)
        self.assertEqual(self.request('/api/public/pqrs/track',{'code':'PQRS-2026-9999','token':made['token']})['status'],404)
        cookie,csrf,post=self.session();cid=self.case(made['code'])['id']
        post('/api/pqrs/%d'%cid,action='note',body='Nota interna confidencial ficticia')
        post('/api/pqrs/%d'%cid,action='reply',body='Necesitamos la factura de compra (respuesta ficticia).',status='esperando_cliente')
        view=self.request('/api/public/pqrs/track',{'code':made['code'],'token':made['token']})['body']
        dump=json.dumps(view,ensure_ascii=False)
        for secret in ('cliente@example.invalid','+593991234567','Nota interna confidencial','Cliente Ficticio Prueba','assigned'):self.assertNotIn(secret,dump)
        self.assertEqual(view['status'],'esperando_cliente');self.assertIn('Necesitamos la factura',dump)
        replied=self.request('/api/public/pqrs/reply',{'code':made['code'],'token':made['token'],'message':'Adjunto la información pedida (ficticia).'})
        self.assertEqual((replied['status'],replied['body']['status']),(200,'en_revision'))
        post('/api/pqrs/%d'%cid,action='close',body='Se entregó el equipo y se ofreció una disculpa (ficticio).')
        self.assertEqual(self.request('/api/public/pqrs/reply',{'code':made['code'],'token':made['token'],'message':'Otro mensaje'})['status'],409)

    def test_roles_are_enforced_on_the_server(self):
        made=self.submit(key='0040');cid=self.case(made['code'])['id']
        tech,tech_cookie=self.technician()
        self.assertEqual(self.request('/api/pqrs/%d'%cid,cookie=tech_cookie)['status'],404)  # no asignada: no la ve
        self.assertEqual(self.request('/api/pqrs',cookie=tech_cookie)['body']['total'],0)
        self.assertEqual(tech('/api/pqrs/%d'%cid,action='reply',body='Hola')['status'],404)
        cookie,csrf,post=self.session()
        with app.connect() as c:tid=c.execute("SELECT id FROM users WHERE username='tecnicowa'").fetchone()[0]
        got=post('/api/pqrs/%d'%cid,action='assign',user_id=str(tid));self.assertEqual((got['status'],got['body']['status']),(200,'asignada'))
        self.assertEqual(self.request('/api/pqrs/%d'%cid,cookie=tech_cookie)['status'],200)
        self.assertEqual(tech('/api/pqrs/%d'%cid,action='close',body='Cierre no permitido')['status'],403)
        self.assertEqual(tech('/api/pqrs/%d'%cid,action='priority',priority='alta')['status'],403)
        self.assertEqual(tech('/api/pqrs/%d'%cid,action='status',status='en_solucion')['status'],200)
        self.assertEqual(self.request('/api/pqrs/export.csv',cookie=tech_cookie)['status'],403)
        self.assertEqual(self.request('/api/pqrs/%d'%cid,{'action':'note','body':'sin token'},cookie=cookie)['status'],403)  # CSRF obligatorio
        self.assertEqual(self.request('/api/pqrs')['status'],401)

    def test_staff_workflow_metrics_export_and_retention(self):
        made=self.submit(key='0050',name='=HYPERLINK("x") Ficticio');cid=self.case(made['code'])['id']
        cookie,csrf,post=self.session()
        listed=self.request('/api/pqrs?status=recibida',cookie=cookie)['body']
        self.assertEqual((listed['total'],listed['metrics']['new']),(1,1))
        self.assertEqual(self.request('/api/pqrs/count',cookie=cookie)['body']['new'],1)
        self.assertEqual(post('/api/pqrs/%d'%cid,action='priority',priority='urgente')['body']['priority'],'urgente')
        self.assertEqual(post('/api/pqrs/%d'%cid,action='close',body='')['status'],400)  # el cierre exige la resolución
        answered=post('/api/pqrs/%d'%cid,action='reply',body='Respuesta ficticia al cliente.')['body']
        self.assertTrue(answered['first_response_at']);self.assertEqual(answered['status'],'respondida')
        self.assertEqual([n['event'] for n in answered['notifications']],['recibida','respuesta'])
        closed=post('/api/pqrs/%d'%cid,action='close',body='Caso resuelto (ficticio).')['body'];self.assertEqual(closed['status'],'cerrada')
        self.assertEqual(post('/api/pqrs/%d'%cid,action='reply',body='Otra')['status'],409)
        reopened=post('/api/pqrs/%d'%cid,action='reopen',body='El cliente aportó información nueva.')['body'];self.assertEqual(reopened['status'],'en_revision')
        failed=[n for n in reopened['notifications'] if n['result']!='enviado'][0]
        self.assertEqual(post('/api/pqrs/%d'%cid,action='retry',notification_id=str(failed['id']))['status'],200)
        metrics=self.request('/api/pqrs',cookie=cookie)['body']['metrics'];self.assertIsNotNone(metrics['first_response_hours'])
        csv=self.request('/api/pqrs/export.csv',cookie=cookie)['body'];csv=csv if isinstance(csv,str) else csv.decode()
        self.assertIn(made['code'],csv);self.assertIn("'=HYPERLINK",csv)  # sin fórmulas al abrirlo en una hoja de cálculo
        with app.connect() as c:
            with self.assertRaises(Exception):c.execute('DELETE FROM pqrs_cases WHERE id=?',(cid,))
            with self.assertRaises(Exception):c.execute("UPDATE pqrs_cases SET description='cambiada' WHERE id=?",(cid,))
            with self.assertRaises(Exception):c.execute('DELETE FROM pqrs_events WHERE case_id=?',(cid,))
        items=self.request('/api/notifications',cookie=cookie)['body']['items']
        self.assertFalse(any(i['key'].startswith('pqrs:%d:'%cid) for i in items))  # ya no está «recibida»: deja de avisar

    def test_whatsapp_only_with_consent_and_configuration(self):
        cookie,csrf,post=self.session()
        with patch.dict(app.os.environ,wab.FAKE):
            self.enable(post)
            plain=self.submit(key='0060');wanted=self.submit(key='0061',whatsapp_consent=True)
            with app.connect() as c:
                rows={r['pqrs_id']:(r['event'],r['status'],r['reason_kind']) for r in c.execute('SELECT * FROM whatsapp_outbox WHERE pqrs_id IS NOT NULL')}
                consent=c.execute("SELECT decision,source FROM whatsapp_consents ORDER BY id DESC").fetchone()
        self.assertEqual(rows[self.case(plain['code'])['id']],('pqrs_recibida','omitido','consentimiento'))
        self.assertEqual(rows[self.case(wanted['code'])['id']],('pqrs_recibida','pendiente',''))
        self.assertEqual(tuple(consent),('aceptado','formulario'))


if __name__=='__main__':
    unittest.main()
