import json
import sqlite3
import unittest
from unittest.mock import patch
import test_app
import app
app.os.environ.setdefault('LOGIN_CAPTCHA','off')  # Las pruebas inician sesión sin verificación salvo que la activen.
import technical_access
import code128


class ThermalAccessTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data

    def create(self,**changes):
        cookie,csrf=self.login();data=self.order_data(changes);r=self.request('/api/orders',data,cookie=cookie,csrf=csrf)
        self.assertEqual(r['status'],201,r)
        return cookie,csrf,data,r['body']['id']

    def test_decision_required_and_no_implicit_scopes(self):
        cookie,csrf=self.login();data=self.order_data();data.pop('technical_access')
        result=self.request('/api/orders',data,cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],400);self.assertIn('technical_access',result['body']['fields'])
        for changes,field in [({'technical_access':'authorized'},'technical_access'),({'access_confirmed':False},'access_confirmed'),({'access_operating_system':True},'technical_access'),({'technical_access':'authorized','access_specific_files':True},'access_detail'),({'technical_access':'authorized','access_specific_files':True,'access_detail':'Sí'},'access_detail'),({'destructive_action':'authorized','destructive_confirmed':True,'destructive_detail':'Sí'},'destructive_detail'),({'destructive_action':'denied','risk_format':True},'destructive_action'),({'destructive_action':'authorized','destructive_confirmed':True,'destructive_detail':'Unidad: SSD, 512 GB. Partición del sistema','risk_format':False},'destructive_action'),({'destructive_action':'authorized'},'destructive_detail'),({'destructive_action':'authorized','destructive_detail':'Formatear el disco'},'destructive_confirmed'),({'destructive_action':'authorized','destructive_confirmed':True},'destructive_detail')]:
            r=self.request('/api/orders',{**self.order_data(),**changes},cookie=cookie,csrf=csrf)
            self.assertEqual(r['status'],400,r);self.assertIn(field,r['body']['fields'])
        with app.connect() as c:self.assertEqual(c.execute('select count(*) from orders').fetchone()[0],0)

    def test_ticket_header_has_no_ink_band_and_names_each_copy(self):
        import re,zlib,thermal_pdf
        self.assertEqual(thermal_pdf.COPIES,{'cliente':('COPIA DEL CLIENTE',),'taller':('COPIA DEL ESTABLECIMIENTO',),'ambas':('COPIA DEL CLIENTE','COPIA DEL ESTABLECIMIENTO')})
        cookie,csrf,_,oid=self.create()
        for copy,pages in (('cliente',1),('taller',1),('ambas',2)):
            pdf=self.request('/api/orders/%d/thermal.pdf?copy=%s'%(oid,copy),cookie=cookie)['body'];self.assertEqual(len(re.findall(rb'/Type /Page\b',pdf)),pages,copy)
            streams=[zlib.decompress(m) for m in re.findall(rb'stream\r?\n(.*?)\r?\nendstream',pdf,re.S) if m[:1]==b'x']
            pages_ops=[text for text in streams if b'/F2 ' in text and b' Tf' in text];self.assertEqual(len(pages_ops),pages)
            for text in pages_ops:
                # Título azul oscuro y copia en rosado; ningún rectángulo relleno ocupa el ancho útil con más de 2 pt de alto (la antigua franja negra).
                self.assertRegex(text,rb'0\.098\d* 0\.168\d* 0\.270\d* rg');self.assertRegex(text,rb'0\.666\d* 0\.278\d* 0\.486\d* rg')
                self.assertFalse([m for m in re.findall(rb'([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re',text) if float(m[2])>150 and float(m[3])>2])

    def test_files_decision_is_independent_explicit_and_never_assumed(self):
        cookie,csrf=self.login()
        # Combinaciones incoherentes: se rechazan sin crear la orden.
        for changes in [{'files_access':'quizás'},{'technical_access':'denied','files_access':'authorized'},{'technical_access':'authorized','access_operating_system':True,'files_access':'authorized'},
                        {'technical_access':'authorized','access_operating_system':True,'files_access':'denied','access_backup':True,'access_detail':'Respaldar la carpeta Documentos del cliente.'}]:
            r=self.request('/api/orders',{**self.order_data(),**changes},cookie=cookie,csrf=csrf)
            self.assertEqual(r['status'],400,changes);self.assertIn('files_access',r['body']['fields'],changes)
        with app.connect() as c:self.assertEqual(c.execute('select count(*) from orders').fetchone()[0],0)
        # Rechazo expreso: queda registrado como tal y aparece en los documentos.
        denied=self.request('/api/orders',self.order_data({'technical_access':'authorized','access_operating_system':True,'files_access':'denied','request_key':'files-decision-denied-0001'}),cookie=cookie,csrf=csrf)
        self.assertEqual(denied['status'],201,denied);order=self.request('/api/orders/%d'%denied['body']['id'],cookie=cookie)['body']['order'];p=order['access_authorization']['permissions']
        self.assertEqual((p['files_decision'],p['operating_system'],p['specific_files'],p['backup']),('denied',True,False,False))
        self.assertEqual(self.request('/api/orders/%d/receipt.pdf'%denied['body']['id'],cookie=cookie)['status'],200)
        self.assertEqual(self.request('/api/orders/%d/thermal.pdf'%denied['body']['id'],cookie=cookie)['status'],200)
        # Autorización expresa con alcance, y ausencia de decisión: nunca se guarda un rechazo que no se expresó.
        granted=self.request('/api/orders',self.order_data({'technical_access':'authorized','access_operating_system':True,'files_access':'authorized','access_backup':True,'access_detail':'Respaldar la carpeta Documentos del cliente.','request_key':'files-decision-granted-001'}),cookie=cookie,csrf=csrf)
        self.assertEqual(granted['status'],201,granted)
        self.assertEqual(self.request('/api/orders/%d'%granted['body']['id'],cookie=cookie)['body']['order']['access_authorization']['permissions']['files_decision'],'authorized')
        silent=self.request('/api/orders',self.order_data({'technical_access':'authorized','access_operating_system':True,'request_key':'files-decision-pending-001'}),cookie=cookie,csrf=csrf)
        self.assertNotIn('files_decision',self.request('/api/orders/%d'%silent['body']['id'],cookie=cookie)['body']['order']['access_authorization']['permissions'])

    def test_access_evidence_and_destructive_separation(self):
        cookie,csrf,_,oid=self.create(technical_access='authorized',access_operating_system=True,access_signed_in_tests=True)
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];a=order['access_authorization']
        self.assertEqual(a['decision'],'authorized');self.assertEqual(a['actor_id'],self.uid);self.assertEqual(a['recorded_at'],order['received_at']);self.assertTrue(a['permissions']['operating_system']);self.assertFalse(a['permissions']['specific_files']);self.assertIsNone(order['destructive_authorization'])
        with app.connect() as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute('update order_access_consents set decision=\'denied\' where order_id=?',(oid,))
        payload={'technical_access':'denied','access_confirmed':True,'access_revision':str(order['access_revision']),'request_key':'access-second-request-0001'}
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/authorizations',payload,cookie=cookie,csrf=csrf)['status'],201)
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/authorizations',payload,cookie=cookie,csrf=csrf)['status'],200)
        latest=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];self.assertEqual(len(latest['access_history']),2);self.assertEqual(latest['access_authorization']['decision'],'denied');self.assertEqual(latest['qr_url'],order['qr_url'])
        stale={**payload,'request_key':'access-stale-request-0001'};self.assertEqual(self.request('/api/orders/'+str(oid)+'/authorizations',stale,cookie=cookie,csrf=csrf)['status'],409)
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/authorizations',payload,cookie=cookie)['status'],403)

    def test_additional_destructive_permission_is_independent(self):
        cookie,csrf,_,oid=self.create(destructive_action='authorized',destructive_confirmed=True,risk_format=True,risk_reinstall=True,risk_erase=False,destructive_detail='Reinstalar sistema; eliminar partición acordada.')
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
        self.assertEqual(order['access_authorization']['decision'],'denied')
        self.assertEqual(order['destructive_authorization']['decision'],'authorized')
        self.assertEqual(len(order['access_history']),2)
        # Cada operación queda guardada por separado; las no marcadas no se interpretan como autorizadas.
        self.assertEqual({k:order['destructive_authorization']['permissions'][k] for k in ('reinstall','format','erase','factory_reset')},{'reinstall':True,'format':True,'erase':False,'factory_reset':False})

    def test_historical_record_truth_and_later_acceptance(self):
        cookie,csrf=self.login()
        data=self.order_data()
        with app.connect() as c:
            did=c.execute("INSERT INTO devices(client_id,type,category) VALUES (?,'portatil','portatil')",(data['client_id'],)).lastrowid
            oid=c.execute("INSERT INTO orders(device_id,status,problem,created_by,created_at,code,received_at,qr_url) VALUES (?,'pendiente','Prueba histórica',?,0,'PCD-20200101-0001','2020-01-01T10:00:00-05:00','https://example.invalid/orders/PCD-20200101-0001')",(did,self.uid)).lastrowid
        before=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];self.assertIsNone(before['access_authorization']);self.assertIsNone(before['terms'])
        payload={'technical_access':'denied','access_confirmed':True,'access_revision':'0','request_key':'historical-access-request-01','complete_terms':True,'terms_document_id':data['terms_document_id'],'terms_accept':True}
        r=self.request('/api/orders/'+str(oid)+'/authorizations',payload,cookie=cookie,csrf=csrf);self.assertEqual(r['status'],201,r)
        after=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];self.assertNotEqual(after['terms_accepted_at'],after['received_at']);self.assertEqual(before['qr_url'],after['qr_url']);self.assertEqual(after['code'],before['code'])

    def test_reprint_does_not_create_records_or_change_qr(self):
        cookie,csrf,data,oid=self.create(request_key='thermal-reprint-request-00001')
        original=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
        for i in range(2):
            r=self.request('/api/orders/'+str(oid)+'/thermal.pdf',cookie=cookie);self.assertEqual(r['status'],200);self.assertTrue(r['body'].startswith(b'%PDF'));self.assertEqual(r['body'].count(b'/Subtype /Image'),1);self.assertIn(b'/ColorSpace /DeviceGray',r['body'])
        with app.connect() as c:
            self.assertEqual(c.execute('select count(*) from orders').fetchone()[0],1);self.assertEqual(c.execute('select count(*) from order_access_consents').fetchone()[0],1)
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/thermal.pdf')['status'],401)
        self.assertEqual(self.request('/api/order-by-code/'+original['code'],cookie=cookie)['body']['id'],oid)
        self.assertEqual(self.request('/api/orders',data,cookie=cookie,csrf=csrf)['body']['id'],oid)
        self.assertEqual(self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']['qr_url'],original['qr_url'])

    def test_public_tracking_link_is_random_limited_and_revocable(self):
        cookie,csrf,data,oid=self.create(request_key='thermal-tracking-request-0001',serial='SERIE-PRIVADA-1')
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];link=order['tracking']['url']
        self.assertRegex(link,r'^https://[^/]+/s/[A-Za-z0-9_-]{22}$');self.assertNotIn(order['code'],link)
        path=link[link.index('/s/'):]
        page=self.request(path);self.assertEqual(page['status'],200)
        self.assertIn(order['code'],page['body']);self.assertIn('En espera',page['body'])
        # La página pública no expone datos personales ni técnicos reservados.
        for private in (data['client'],data.get('phone',''),data.get('identification',''),data['problem'],'SERIE-PRIVADA-1'):
            if private:self.assertNotIn(private,page['body'])
        self.assertEqual(self.request('/s/'+'A'*22)['status'],404)
        self.assertEqual(self.request('/s/x')['status'],404)
        for copy,pages in (('cliente',1),('taller',1),('ambas',2)):
            r=self.request('/api/orders/%d/thermal.pdf?copy=%s'%(oid,copy),cookie=cookie);self.assertEqual(r['status'],200);self.assertEqual(r['body'].count(b'/Type /Page/'),pages)
        self.assertEqual(self.request('/api/orders/%d/thermal.pdf?copy=otra'%oid,cookie=cookie)['status'],400)
        url='/api/orders/%d/tracking'%oid
        self.assertEqual(self.request(url,{'action':'revoke'},cookie=cookie)['status'],403)
        self.assertEqual(self.request(url,{'action':'borrar'},cookie=cookie,csrf=csrf)['status'],400)
        revoked=self.request(url,{'action':'revoke'},cookie=cookie,csrf=csrf);self.assertEqual((revoked['status'],revoked['body']['tracking']['active']),(200,False))
        self.assertEqual(self.request(path)['status'],404)
        self.assertEqual(self.request('/api/orders/%d/thermal.pdf'%oid,cookie=cookie)['status'],200)
        renewed=self.request(url,{'action':'create'},cookie=cookie,csrf=csrf)['body']['tracking']
        self.assertTrue(renewed['active']);self.assertNotEqual(renewed['url'],link)
        self.assertEqual(self.request(path)['status'],404);self.assertEqual(self.request(renewed['url'][renewed['url'].index('/s/'):])['status'],200)
        self.assertEqual(self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']['qr_url'],order['qr_url'])
        with app.connect() as c:self.assertEqual(c.execute('select count(*) from order_tracking_links').fetchone()[0],2)

    def test_code128_checksum_and_printable_width(self):
        for value in ['PCD-20261009-0001','OP-00001','PCD-20261009-12345']:
            words=code128.symbols(value)
            self.assertEqual(words[-1],106);self.assertEqual(words[-2],(words[0]+sum(i*w for i,w in enumerate(words[1:-2],1)))%103)
            self.assertLessEqual((sum(code128.widths(value))+20)*2,576)

    def test_direct_print_is_authenticated_csrf_protected_and_idempotent(self):
        cookie,csrf,_,oid=self.create()
        payload={'request_key':'printer-request-key-00001'};url='/api/orders/'+str(oid)+'/thermal-print'
        self.assertEqual(self.request(url,payload)['status'],401)
        self.assertEqual(self.request(url,payload,cookie=cookie)['status'],403)
        with patch.object(app.thermal_printing,'capability',return_value={'available':True,'queue':'MOCK-ONLY'}),patch.object(app.thermal_printing,'inspect_pdf',return_value=3200),patch.object(app.thermal_printing,'send',return_value='test-job-1') as send:
            first=self.request(url,payload,cookie=cookie,csrf=csrf);self.assertEqual(first['status'],200,first)
            repeat=self.request(url,payload,cookie=cookie,csrf=csrf);self.assertTrue(repeat['body']['duplicate']);send.assert_called_once()
            with app.connect() as c:
                self.assertEqual(c.execute('select count(*) from orders').fetchone()[0],1)
                self.assertEqual(c.execute('select state from thermal_print_jobs').fetchone()[0],'submitted')
            payload['request_key']='printer-request-key-00002'
            self.assertEqual(self.request(url,payload,cookie=cookie,csrf=csrf)['status'],200);self.assertEqual(send.call_count,2)

    def test_unconfirmed_print_is_not_automatically_sent_again(self):
        cookie,csrf,_,oid=self.create();payload={'request_key':'printer-failure-key-0001'};url='/api/orders/'+str(oid)+'/thermal-print'
        with patch.object(app.thermal_printing,'capability',return_value={'available':True,'queue':'MOCK-ONLY'}),patch.object(app.thermal_printing,'inspect_pdf',return_value=3200),patch.object(app.thermal_printing,'send',side_effect=OSError('Prueba aislada')) as send:
            self.assertEqual(self.request(url,payload,cookie=cookie,csrf=csrf)['status'],503)
            self.assertEqual(self.request(url,payload,cookie=cookie,csrf=csrf)['status'],409);send.assert_called_once()
            with app.connect() as c:self.assertEqual(c.execute('select state from thermal_print_jobs').fetchone()[0],'uncertain')


class CompactTicketTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data

    def text_of(self,pdf):
        import subprocess,tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf') as handle:
            handle.write(pdf);handle.flush()
            text=subprocess.run(['pdftotext','-layout',handle.name,'-'],capture_output=True,text=True,check=True).stdout
            info=subprocess.run(['pdfinfo',handle.name],capture_output=True,text=True,check=True).stdout
        return text,info

    def test_compact_conditions_summary_keeps_every_mandatory_element(self):
        import shutil,thermal_pdf
        if not shutil.which('pdftotext'):self.skipTest('pdftotext no disponible')
        self.assertEqual(len(thermal_pdf.SUMMARY),7)
        cookie,csrf=self.login();oid=self.request('/api/orders',self.order_data({'request_key':'ticket-compact-request-01','client':'Cliente Ficticio Con Un Nombre Bastante Largo De Prueba'}),cookie=cookie,csrf=csrf)['body']['id']
        pdf=self.request('/api/orders/%d/thermal.pdf'%oid,cookie=cookie)['body']
        text,info=self.text_of(pdf);flat=' '.join(text.split())
        self.assertIn('Pages:           1',info);self.assertIn('Title:           TICKET-',info)
        self.assertIn('CONDICIONES DE RECEPCIÓN',flat)
        for n,item in enumerate(thermal_pdf.SUMMARY,1):self.assertIn(str(n)+'. '+item,flat)
        # Orden pedido: número, recepción, cliente, equipo, falla, servicio, condiciones, QR, firma.
        order=[flat.index(mark) for mark in ('COMPROBANTE DE RECEPCIÓN','Recepción:','CLIENTE Nombre','EQUIPO Tipo','Accesorios','FALLA REPORTADA','SERVICIO SOLICITADO','CONDICIONES DE RECEPCIÓN','Condiciones completas','Seguimiento de tu','FIRMA Y CONSTANCIA')]
        self.assertEqual(order,sorted(order))
        # Se conservan las autorizaciones técnicas, firmas y datos del cliente.
        for required in ('AUTORIZACIÓN DE ACCESO TÉCNICO','Reinstalar / formatear / eliminar','Firma del cliente','Recibido por','Cliente Ficticio','Versión aceptada'):self.assertIn(required,flat)
        self.assertNotIn('Datos personales: se recomienda',flat);self.assertNotIn('https://',flat.split('CONDICIONES DE RECEPCIÓN')[1].split('FIRMA')[0])

    def test_ticket_is_named_after_the_real_order_and_can_be_previewed_inside_the_system(self):
        cookie,csrf=self.login();order=self.request('/api/orders',self.order_data({'request_key':'ticket-compact-request-02'}),cookie=cookie,csrf=csrf)['body']
        code=self.request('/api/orders/%d'%order['id'],cookie=cookie)['body']['order']['code']
        handler=object.__new__(app.Handler);sent={}
        handler.send_response=lambda status:None;handler.end_headers=lambda:None;handler.wfile=__import__('io').BytesIO()
        handler.send_header=lambda name,value:sent.__setitem__(name,value)
        handler.command='GET';handler.headers={}
        app.Handler.reply(handler,200,b'%PDF-1.4','application/pdf',filename='TICKET-'+code+'.pdf')
        self.assertEqual(sent['Content-Disposition'],'inline; filename="TICKET-'+code+'.pdf"')
        # Los PDF tampoco se pueden incrustar: la vista previa usa una URL de objeto temporal (blob:).
        self.assertIn("frame-ancestors 'none'",sent['Content-Security-Policy'])
        # El resto de respuestas mantiene la prohibición de incrustarse.
        handler=object.__new__(app.Handler);other={}
        handler.send_response=lambda status:None;handler.end_headers=lambda:None;handler.wfile=__import__('io').BytesIO()
        handler.send_header=lambda name,value:other.__setitem__(name,value);handler.command='GET';handler.headers={}
        app.Handler.reply(handler,200,{'ok':True})
        self.assertIn("frame-ancestors 'none'",other['Content-Security-Policy'])
        js=(app.ROOT/'static'/'app.js').read_text()
        self.assertIn("download.download=kind==='thermal'?'TICKET-'+order.code+'.pdf'",js)
        self.assertIn("frame.src=documentBlobUrl+'#toolbar=0&navpanes=0&view=FitH'",js)
        self.assertNotIn('frame.src=named?source',js)
        # «Ticket listo» solo cuando el visor cargó el documento; si no, aviso y «Reintentar».
        block=js[js.index('async function load(){const version=++loadVersion;'):js.index("if(kind==='label')for(const input of")]
        self.assertLess(block.index('frame.onload='),block.index("say(ready,'ready'"))
        self.assertIn("retry.hidden=false",block)
