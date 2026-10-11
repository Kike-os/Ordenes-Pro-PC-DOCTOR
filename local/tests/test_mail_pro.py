import smtplib
import socket
import ssl
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mail_pro
import test_app
import app

ENV={'MAIL_IMAP_HOST':'mail.example.invalid','MAIL_IMAP_PORT':'993','MAIL_SMTP_HOST':'mail.example.invalid','MAIL_SMTP_PORT':'465','MAIL_USERNAME':'buzon@example.invalid','MAIL_PASSWORD':'secreto-ficticio-123'}


class MailProTests(unittest.TestCase):
    def test_status_never_exposes_the_password(self):
        info=mail_pro.status(ENV)
        self.assertEqual((info['configured'],info['password_set'],info['account']),(True,True,'buzon@example.invalid'))
        self.assertNotIn('secreto-ficticio-123',repr(info))
        self.assertFalse(mail_pro.status({})['configured'])

    def test_only_tls_ports_are_accepted_and_verification_stays_on(self):
        for bad in ({'MAIL_IMAP_PORT':'143'},{'MAIL_SMTP_PORT':'25'},{'MAIL_SMTP_PORT':'abc'}):
            with self.assertRaises(mail_pro.MailError):mail_pro.settings({**ENV,**bad})
        self.assertEqual(mail_pro.settings({**ENV,'MAIL_SMTP_PORT':'587'})['smtp_port'],587)
        ctx=mail_pro.context()
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)

    def test_failures_are_classified_without_secrets(self):
        cases=[(socket.gaierror(),'dns'),(ssl.SSLCertVerificationError(),'tls'),(socket.timeout(),'red'),(ConnectionRefusedError(),'red'),(smtplib.SMTPAuthenticationError(535,b'auth'),'credenciales'),(mail_pro.imaplib.IMAP4.error('LOGIN failed secreto-ficticio-123'),'credenciales')]
        for error,kind in cases:
            failure=mail_pro.classify(error,'mail.example.invalid',993)
            self.assertEqual(failure.kind,kind)
            self.assertNotIn('secreto',str(failure))

    def test_tests_require_configuration_and_report_network_failure(self):
        with self.assertRaises(mail_pro.MailError) as missing:mail_pro.test_imap({})
        self.assertEqual(missing.exception.kind,'configuracion')
        with patch.object(mail_pro.socket,'getaddrinfo',side_effect=socket.gaierror()):
            with self.assertRaises(mail_pro.MailError) as dns:mail_pro.test_imap(ENV)
        self.assertEqual(dns.exception.kind,'dns')
        with patch.object(mail_pro.smtplib,'SMTP_SSL',side_effect=socket.timeout()):
            with self.assertRaises(mail_pro.MailError) as net:mail_pro.test_smtp(ENV)
        self.assertEqual(net.exception.kind,'red')

    def test_html_is_sanitized_and_remote_content_blocked(self):
        dirty='<p onclick="x()">Hola <b>mundo</b></p><script>alert(1)</script><style>p{}</style><img src="https://rastreo.invalid/p.gif" alt="logo"><a href="javascript:alert(1)">malo</a><a href="https://example.invalid/a?b=1&c=2">bueno</a><iframe src="x"></iframe><svg><script>1</script></svg>'
        clean,blocked=mail_pro.sanitize_html(dirty)
        self.assertEqual(blocked,1)
        for bad in ('script','onclick','javascript:','<img','iframe','rastreo.invalid','<style','svg','alert'):
            self.assertNotIn(bad,clean)
        self.assertIn('<p>Hola <b>mundo</b></p>',clean)
        self.assertIn('<a href="https://example.invalid/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer nofollow">bueno</a>',clean)
        self.assertIn('<a>malo</a>',clean)

    def test_addresses_filenames_and_message_building(self):
        self.assertEqual(mail_pro.clean_addresses('Ana <ana@example.invalid>; luis@example.invalid, ANA@example.invalid'),['ana@example.invalid','luis@example.invalid'])
        for bad in ('sin-arroba','a@b','x@example.invalid\nBcc: z@example.invalid'):
            with self.assertRaises(mail_pro.MailError):mail_pro.clean_addresses(bad)
        self.assertEqual(mail_pro.safe_filename('../../etc/pas:swd\x00.pdf'),'_.._etc_pas_swd_.pdf')
        config=mail_pro.settings(ENV)
        message,recipients=mail_pro.build_message(config,{'to':'cliente@example.invalid','cc':'otro@example.invalid','subject':'Asunto\r\nBcc: intruso@example.invalid','body':'Texto','from_name':'PC-DOCTOR S.A.','in_reply_to':'<abc@example.invalid>','references':'<uno@example.invalid> <abc@example.invalid>','attachments':[{'name':'informe.pdf','type':'application/pdf','data':'JVBERi0='}]},'Firma ficticia')
        self.assertEqual(recipients,['cliente@example.invalid','otro@example.invalid'])
        self.assertEqual(str(message['From']),'"PC-DOCTOR S.A." <buzon@example.invalid>')
        self.assertNotIn('\n',str(message['Subject']));self.assertIsNone(message['Bcc'])
        self.assertEqual((str(message['In-Reply-To']),str(message['References'])),('<abc@example.invalid>','<uno@example.invalid> <abc@example.invalid>'))
        self.assertTrue(str(message['Message-ID']).endswith('@example.invalid>'))
        self.assertIn('Firma ficticia',message.get_body(('plain',)).get_content())
        self.assertEqual([part.get_filename() for part in message.iter_attachments()],['informe.pdf'])
        with self.assertRaises(mail_pro.MailError):mail_pro.build_message(config,{'to':'','subject':'x','body':'y'})
        with self.assertRaises(mail_pro.MailError):mail_pro.build_message(config,{'to':'a@example.invalid','subject':'x','body':'y','attachments':[{'name':'g.bin','data':'A'*5_000_000}]})


class MailRouteTests(test_app.SecurityTests):
    KEY='clave-de-solicitud-0001'

    def test_mail_routes_require_permission_and_send_is_not_duplicated(self):
        cookie,csrf=self.login()
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico','tec@example.invalid','Técnico de prueba',?,'tecnico',1)",(self.hash,))
        tech=self.request('/api/login',{'login':'tecnico','password':'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        tech_csrf=self.request('/api/me',cookie=tech)['body']['user']['csrf']
        body={'to':'cliente@example.invalid','cc':'','subject':'Prueba','body':'Texto','attachments':'[]','request_key':self.KEY,'order_code':''}
        self.assertEqual(self.request('/api/mail/overview')['status'],401)
        # Sin configurar, nadie accede.
        with patch.dict(app.os.environ,{k:'' for k in ENV}):
            self.assertEqual(self.request('/api/mail/overview',cookie=cookie)['status'],403)
            self.assertFalse(self.request('/api/me',cookie=cookie)['body']['user']['mail'])
        with patch.dict(app.os.environ,ENV):
            self.assertTrue(self.request('/api/me',cookie=cookie)['body']['user']['mail'])
            self.assertEqual(self.request('/api/mail/overview',cookie=tech)['status'],403)
            self.assertEqual(self.request('/api/mail/send',body,cookie=tech,csrf=tech_csrf)['status'],403)
            self.assertEqual(self.request('/api/mail/send',body,cookie=cookie)['status'],403)
            settings=self.request('/api/settings',cookie=cookie)['body']
            self.assertTrue(settings['mail']['configured']);self.assertNotIn('secreto-ficticio-123',repr(settings))
            sent=[]
            with patch.object(mail_pro,'deliver',side_effect=lambda config,message,recipients:sent.append((str(message['Subject']),recipients))),patch.object(mail_pro,'open_imap',side_effect=mail_pro.MailError('red','sin red')):
                first=self.request('/api/mail/send',body,cookie=cookie,csrf=csrf)
                self.assertEqual((first['status'],first['body']['saved_in_sent']),(201,False))
                again=self.request('/api/mail/send',body,cookie=cookie,csrf=csrf)
                self.assertEqual((again['status'],again['body'].get('duplicate')),(200,True))
                self.assertEqual(sent,[('Prueba',['cliente@example.invalid'])])
                self.assertEqual(self.request('/api/mail/send',dict(body,to='no-valido',request_key='clave-de-solicitud-0002'),cookie=cookie,csrf=csrf)['status'],400)
            with patch.object(mail_pro,'deliver',side_effect=mail_pro.MailError('red','El servidor no respondió.')):
                failed=self.request('/api/mail/send',dict(body,request_key='clave-de-solicitud-0003'),cookie=cookie,csrf=csrf)
                self.assertEqual(failed['status'],502)
            with app.connect() as c:
                self.assertEqual({r['request_key']:r['status'] for r in c.execute('SELECT request_key,status FROM mail_outbox')},{self.KEY:'sent','clave-de-solicitud-0003':'failed'})
            # Un envío fallido se puede reintentar con la misma clave.
            with patch.object(mail_pro,'deliver',return_value=None),patch.object(mail_pro,'open_imap',side_effect=mail_pro.MailError('red','sin red')):
                self.assertEqual(self.request('/api/mail/send',dict(body,request_key='clave-de-solicitud-0003'),cookie=cookie,csrf=csrf)['status'],201)
            with patch.object(mail_pro,'test_imap',side_effect=mail_pro.MailError('credenciales','El servidor rechazó el usuario o la contraseña.')):
                result=self.request('/api/mail/test',{'kind':'imap'},cookie=cookie,csrf=csrf)['body']
                self.assertEqual((result['ok'],result['kind']),(False,'credenciales'))
            self.assertEqual(self.request('/api/mail/test',{'kind':'imap'},cookie=tech,csrf=tech_csrf)['status'],403)
            self.assertEqual(self.request('/api/mail/signature',{'signature':'Firma de prueba'},cookie=cookie,csrf=csrf)['status'],200)
            self.assertEqual(self.request('/api/settings',cookie=cookie)['body']['mail_signature'],'Firma de prueba')


    def test_new_mail_is_detected_once_and_history_is_not_announced(self):
        import notifications
        from datetime import datetime,timedelta
        cookie,csrf=self.login();box=FakeInbox([3,4]);start=datetime(2026,1,2,10,0,tzinfo=app.appointments.TZ)
        with patch.dict(app.os.environ,ENV),patch.object(mail_pro,'open_imap',side_effect=lambda *a,**k:box):
            with app.connect() as c:
                # Primera sincronización: fija el punto de partida y no anuncia el correo que ya existía.
                first=notifications.mail_status(c,start)
                self.assertEqual((first['last_uid'],first['unread'],notifications.mail_events(c)),(4,2,[]))
                self.assertEqual(first['quota'],{'used':800*1024,'limit':1000*1024})
                box.uids+=[5,6];box.seen.add(6)
                # Dentro del minuto se usa la copia guardada; después se consulta y solo se registra el mensaje sin leer.
                self.assertEqual(notifications.mail_status(c,start+timedelta(seconds=20))['last_uid'],4)
                notifications.mail_status(c,start+timedelta(seconds=90))
                self.assertEqual([(e['uid'],e['from'],e['subject']) for e in notifications.mail_events(c)],[(5,'Cliente ficticio','Consulta 5')])
                notifications.mail_status(c,start+timedelta(seconds=200));notifications.mail_status(c,start+timedelta(seconds=400))
                self.assertEqual(len(notifications.mail_events(c)),1)
            items=self.request('/api/notifications',cookie=cookie)['body']['items']
            new=[item for item in items if item['key'].startswith('mail:new:')]
            self.assertEqual([(item['title'],item['detail'],item['href']) for item in new],[('Correo nuevo · Cliente ficticio','Consulta 5','#mail?folder=INBOX&uid=5')])
            self.assertTrue([item for item in items if item['key']=='mailquota:75' and '80 %' in item['title']])
            self.assertTrue(all(item.get('quiet') for item in items if item['key'].startswith('mail:') and not item['key'].startswith('mail:new:')))
            self.assertEqual(self.request('/api/mail/prefs',{'prefs':'{"received":true,"volume":7,"otro":"x"}'},cookie=cookie)['status'],403)
            saved=self.request('/api/mail/prefs',{'prefs':'{"received":true,"volume":7,"otro":"x"}'},cookie=cookie,csrf=csrf)['body']['prefs']
            self.assertEqual((saved['received'],saved['sent'],saved['volume'],'otro' in saved),(True,False,1.0,False))
            self.assertEqual(self.request('/api/me',cookie=cookie)['body']['user']['mail_prefs'],saved)
            check=self.request('/api/mail/check',cookie=cookie)['body']
            self.assertEqual((check['unread'],[e['uid'] for e in check['events']]),(3,[5]))
        # Quien no tiene acceso al correo no recibe remitentes ni asuntos.
        with patch.dict(app.os.environ,{k:'' for k in ENV}):
            self.assertFalse([item for item in self.request('/api/notifications',cookie=cookie)['body']['items'] if item['key'].startswith('mail')])
            self.assertEqual(self.request('/api/mail/check',cookie=cookie)['status'],403)

    def test_previews_folders_quota_and_blind_copies(self):
        self.assertEqual(mail_pro._first_text('1 (UID 5 BODYSTRUCTURE ("text" "plain" ("charset" "utf-8") NIL NIL "quoted-printable" 20 1)')[0],'1')
        self.assertEqual(mail_pro._first_text('1 (BODYSTRUCTURE ((("text" "html" ("charset" "iso-8859-1") NIL NIL "base64" 20 1)("text" "plain" NIL NIL NIL "7bit" 1 1) "alternative")("application" "pdf" NIL NIL NIL "base64" 9) "mixed")'),('1.1','html','iso-8859-1','base64'))
        self.assertIsNone(mail_pro._first_text('1 (BODYSTRUCTURE ("application" "pdf" NIL NIL NIL "base64" 9))'))
        self.assertEqual(mail_pro._preview(b'Se=C3=B1or cliente:=\r\n su equipo est=C3=A1 listo','plain','utf-8','quoted-printable'),'Señor cliente: su equipo está listo')
        self.assertEqual(mail_pro._preview(mail_pro.base64.b64encode('<style>p{color:red}</style><p>Hola &amp; gracias</p><img src="x'.encode()),'html','utf-8','base64'),'Hola & gracias')
        self.assertEqual(mail_pro._preview(b'\xff\xfe','plain','juego-inexistente','7bit'),'')
        box=FakeInbox([1])
        self.assertEqual([(f['id'],f['label'],f['duplicate']) for f in mail_pro.list_folders(box) if f['role']=='junk'],[('INBOX.Junk','Spam',False),('INBOX.spam','spam',True)])
        self.assertEqual(mail_pro.quota(box),{'used':800*1024,'limit':1000*1024})
        box.quota_line=b'"User quota" (STORAGE 50 0)';self.assertEqual(mail_pro.quota(box),{'used':50*1024,'limit':None})
        box.quota_line=b'';self.assertIsNone(mail_pro.quota(box))
        import notifications
        self.assertEqual((notifications.quota_level({'used':95,'limit':100}),notifications.quota_level({'used':5,'limit':None}),notifications.quota_level(None)),(95,None,None))
        message,recipients=mail_pro.build_message({'username':'taller@example.invalid'},{'to':'a@example.invalid','cc':'b@example.invalid','bcc':'c@example.invalid, a@example.invalid','subject':'Prueba','body':'Texto'})
        self.assertEqual(recipients,['a@example.invalid','b@example.invalid','c@example.invalid'])
        self.assertNotIn('c@example.invalid',message.as_string())
        rich,_=mail_pro.build_message({'username':'taller@example.invalid'},{'to':'a@example.invalid','subject':'Formato','body':'Hola **cliente** <script>x</script>\n- uno\n- dos\n_gracias_','rich':True},'Firma')
        page=rich.get_body(('html',)).get_content()
        self.assertIn('<strong>cliente</strong>',page);self.assertIn('<ul>\n<li>uno</li>\n<li>dos</li>\n</ul>',page);self.assertIn('<em>gracias</em>',page)
        self.assertNotIn('<script>',page);self.assertIn('&lt;script&gt;',page);self.assertIn('**cliente**',rich.get_body(('plain',)).get_content())


    def test_cpanel_storage_is_read_only_classified_and_cached(self):
        import cpanel,notifications,io,json as js
        from datetime import datetime,timedelta
        from urllib.error import HTTPError,URLError
        env={'CPANEL_HOST':'cpanel.example.invalid','CPANEL_USER':'propietario','CPANEL_TOKEN':'TOKENFICTICIO1234567890ABCD'}
        self.assertFalse(cpanel.configured({}));self.assertNotIn('TOKENFICTICIO',repr(cpanel.status(env)))
        with self.assertRaises(cpanel.CpanelError) as missing:cpanel.mailbox_usage('buzon@example.invalid',{})
        self.assertEqual(missing.exception.kind,'sin_configurar')
        with self.assertRaises(cpanel.CpanelError) as plain:cpanel.mailbox_usage('buzon@example.invalid',dict(env,CPANEL_PORT='2082'))
        self.assertEqual(plain.exception.kind,'sin_configurar')
        seen=[]
        def answer(body,code=200):
            def run(request,timeout=None,context=None):
                seen.append(request)
                if code!=200:raise HTTPError(request.full_url,code,'x',{},None)
                return io.BytesIO(body if isinstance(body,bytes) else js.dumps(body).encode())
            return run
        rows=[{'email':'otro@example.invalid','_diskused':'5','_diskquota':'10'},{'email':'buzon@example.invalid','_diskused':'2097152.00','_diskquota':'1073741824','diskquota':'1024'}]
        with patch.object(cpanel,'urlopen',side_effect=answer({'status':1,'data':rows})):
            self.assertEqual(cpanel.mailbox_usage('Buzon@Example.invalid',env),{'used':2097152,'limit':1073741824})
        request=seen[-1];self.assertTrue(request.full_url.startswith('https://cpanel.example.invalid:2083/execute/Email/list_pops_with_disk?domain=example.invalid'))
        self.assertEqual((request.get_method(),request.headers['Authorization']),('GET','cpanel propietario:TOKENFICTICIO1234567890ABCD'))
        with patch.object(cpanel,'urlopen',side_effect=answer({'status':1,'data':[dict(rows[1],_diskquota='0',diskquota='unlimited')]})):
            self.assertEqual(cpanel.mailbox_usage('buzon@example.invalid',env)['limit'],None)
        for body,code,kind in [(b'<html>login</html>',200,'autenticacion'),({},401,'autenticacion'),({'status':0,'errors':['You do not have access to the feature']},200,'permisos'),({'status':1,'data':[]},200,'vacio'),({'status':1,'data':[rows[0]]},200,'no_encontrada'),({'status':1,'data':[dict(rows[1],_diskused='abc')]},200,'respuesta')]:
            with patch.object(cpanel,'urlopen',side_effect=answer(body,code)),self.assertRaises(cpanel.CpanelError) as failed:cpanel.mailbox_usage('buzon@example.invalid',env)
            self.assertEqual(failed.exception.kind,kind);self.assertNotIn('TOKENFICTICIO',str(failed.exception))
        with patch.object(cpanel,'urlopen',side_effect=URLError('sin red')),self.assertRaises(cpanel.CpanelError) as offline:cpanel.mailbox_usage('buzon@example.invalid',env)
        self.assertEqual(offline.exception.kind,'red')
        # Estado para la interfaz: cPanel primero, IMAP como respaldo, lectura anterior marcada como desactualizada si todo falla.
        cookie,csrf=self.login();start=datetime(2026,1,2,10,0,tzinfo=app.appointments.TZ);box=FakeInbox([1])
        with patch.dict(app.os.environ,dict(ENV,**env)),patch.object(mail_pro,'open_imap',side_effect=lambda *a,**k:box):
            with app.connect() as c:
                with patch.object(cpanel,'urlopen',side_effect=answer({'status':1,'data':rows})) as calls:
                    first=notifications.mail_storage(c,start);again=notifications.mail_storage(c,start+timedelta(seconds=30))
                    self.assertEqual((first['state'],first['used'],first['limit'],first['source'],first['stale'],calls.call_count),('ok',2097152,1073741824,'cPanel (UAPI)',False,1));self.assertEqual(again,first)
                with patch.object(cpanel,'urlopen',side_effect=answer({},403)):
                    fallback=notifications.mail_storage(c,start+timedelta(seconds=400))
                    self.assertEqual((fallback['state'],fallback['used'],fallback['source'],fallback['cpanel']),('ok',800*1024,'servidor de correo (IMAP QUOTA)','autenticacion'));self.assertIn('cPanel rechazó el token',fallback['detail'])
                    box.quota_line=b''
                    stale=notifications.mail_storage(c,start+timedelta(seconds=800))
                    self.assertEqual((stale['stale'],stale['used'],stale['failed']),(True,800*1024,'permisos'));self.assertIn('STORAGE',stale['detail'])
                    c.execute("DELETE FROM system_state WHERE key='mail_storage'")
                    denied=notifications.mail_storage(c,start+timedelta(seconds=1200))
                    self.assertEqual((denied['state'],denied['used']),('permisos',None))
            with patch.object(cpanel,'urlopen',side_effect=answer({},403)):body=self.request('/api/mail/storage',cookie=cookie)['body']
            self.assertEqual(body['state'],'permisos');self.assertNotIn('TOKENFICTICIO',repr(body));self.assertNotIn('good',body)
            with patch.object(cpanel,'urlopen',side_effect=answer({'status':1,'data':rows})):
                test=self.request('/api/mail/test',{'kind':'cpanel'},cookie=cookie,csrf=csrf)['body']
            self.assertTrue(test['ok']);self.assertNotIn('TOKENFICTICIO',repr(test))
        with patch.dict(app.os.environ,ENV),patch.object(mail_pro,'open_imap',side_effect=lambda *a,**k:FakeInbox([1])):
            with app.connect() as c:c.execute("DELETE FROM system_state WHERE key='mail_storage'")
            only_imap=self.request('/api/mail/storage?now=1',cookie=cookie)['body']
            self.assertEqual((only_imap['state'],only_imap['cpanel'],only_imap['source']),('ok','sin_configurar','servidor de correo (IMAP QUOTA)'))
        self.assertEqual(self.request('/api/mail/storage')['status'],401)

    def test_corporate_signature_is_generated_safely_and_placed_before_the_quote(self):
        card=mail_pro.clean_signature({'name':'Persona <b>ficticia</b>\nX','role':'SOPORTE','phone':'+593 99 000 0000','web':'example.invalid','address':'Calle ficticia','enabled':True,'on_new':True,'on_reply':False,'html':'<script>'},'buzon@example.invalid')
        self.assertEqual((card['name'],card['email'],card['on_reply'],'html' in card),('Persona b ficticia /b X','buzon@example.invalid',False,False))
        body='Texto **importante**\n\n\nEl 1 ene 2026, Cliente escribió:\n> mensaje anterior'
        message,_=mail_pro.build_message({'username':'buzon@example.invalid'},{'to':'a@example.invalid','subject':'Firma','body':body},card)
        plain=message.get_body(('plain',)).get_content();page=message.get_body(('html',)).get_content()
        self.assertLess(plain.index('Texto **importante**'),plain.index('-- \nPersona'));self.assertLess(plain.index('Tel.: +593 99 000 0000'),plain.index('escribió:'))
        self.assertEqual(plain.count('-- \n'),1);self.assertEqual(page.count('alt="PC-DOCTOR S.A."'),1)
        self.assertLess(page.index('<strong>importante</strong>'),page.index('<table'));self.assertLess(page.index('</table></td></tr></table>'),page.index('<blockquote'))
        for expected in ('href="tel:+593990000000"','href="mailto:buzon@example.invalid"','href="https://example.invalid"','bgcolor="#2b2d31"','border-bottom:3px solid #e03a3e','src="cid:'):
            self.assertIn(expected,page)
        self.assertNotIn('<script',page);self.assertNotIn('<b>',page.split('<table')[1].split('Persona')[1][:40])
        # Estructura MIME: alternativa texto/HTML, con el logo como parte relacionada (CID) y sin rutas locales.
        html_part=message.get_payload()[1];self.assertEqual((message.get_content_type(),html_part.get_content_type()),('multipart/alternative','multipart/related'))
        logo=html_part.get_payload()[1];self.assertEqual((logo.get_content_type(),logo.get_content_disposition()),('image/png','inline'))
        self.assertIn(logo['Content-ID'][1:-1],page);self.assertNotIn('/home/',message.as_string())
        with_file,_=mail_pro.build_message({'username':'buzon@example.invalid'},{'to':'a@example.invalid','subject':'Firma','body':'Hola','attachments':[{'name':'a.txt','type':'text/plain','data':'aG9sYQ=='}]},card)
        self.assertEqual(with_file.get_content_type(),'multipart/mixed')
        none,_=mail_pro.build_message({'username':'buzon@example.invalid'},{'to':'a@example.invalid','subject':'Sin firma','body':'Hola'},'')
        self.assertEqual((none.get_content_type(),'-- ' in none.get_content()),('text/plain',False))
        cookie,csrf=self.login()
        with patch.dict(app.os.environ,ENV):
            self.assertEqual(self.request('/api/settings',cookie=cookie)['body']['mail_signature_card']['name'],'Enrique Martínez Gómez')
            saved=self.request('/api/mail/signature',{'card':'{"name":"Técnica ficticia","role":"TALLER","enabled":true,"on_new":true,"on_reply":true}'},cookie=cookie,csrf=csrf)['body']['card']
            self.assertEqual((saved['name'],saved['role'],saved['email']),('Técnica ficticia','TALLER','buzon@example.invalid'))
            sent=[]
            with patch.object(mail_pro,'deliver',side_effect=lambda config,message,recipients:sent.append(message)),patch.object(mail_pro,'open_imap',side_effect=mail_pro.MailError('red','sin red')):
                base={'to':'cliente@example.invalid','cc':'','subject':'Con firma','body':'Hola','attachments':'[]','order_code':''}
                self.request('/api/mail/send',dict(base,request_key='clave-de-firma-000001',signature=True),cookie=cookie,csrf=csrf)
                self.request('/api/mail/send',dict(base,request_key='clave-de-firma-000002',signature=False),cookie=cookie,csrf=csrf)
            self.assertIn('Técnica ficticia',sent[0].get_body(('html',)).get_content());self.assertEqual(sent[1].get_content_type(),'text/plain')
            self.assertEqual(self.request('/api/mail/signature',{'restore':True},cookie=cookie,csrf=csrf)['body']['card']['name'],'Enrique Martínez Gómez')
            loaded=self.request('/api/mail/signature',cookie=cookie)['body']['card'];self.assertEqual((loaded['on_forward'],loaded['email']),(True,'buzon@example.invalid'))
        self.assertEqual(self.request('/api/mail/signature')['status'],401)
        # El borrador guarda la preferencia de firma sin incluir la firma: al recuperarlo no puede duplicarse.
        draft,_=mail_pro.build_message({'username':'buzon@example.invalid'},{'to':'','subject':'Pendiente','body':'Texto','draft':True,'signature_pref':False},'')
        self.assertEqual((draft['X-OrdenesPro-Signature'],'-- ' in draft.get_content()),('off',False))
        self.assertIsNone(mail_pro.build_message({'username':'buzon@example.invalid'},{'to':'a@example.invalid','subject':'x','body':'y','signature_pref':True},'')[0]['X-OrdenesPro-Signature'])

    def test_replaced_draft_is_removed_only_when_it_is_a_draft(self):
        class Box:
            def __init__(self,flags):self.flags=flags;self.calls=[]
            def select(self,name,readonly=True):self.calls.append(('select',name,readonly));return 'OK',[b'1']
            def uid(self,command,*args):
                self.calls.append((command,)+args)
                return ('OK',[('7 (UID 7 FLAGS (%s))'%self.flags).encode()]) if command=='FETCH' else ('OK',[b''])
            def expunge(self):self.calls.append(('expunge',))
        draft=Box('\\Draft \\Seen');self.assertTrue(mail_pro.remove_draft(draft,'INBOX.Drafts',7))
        self.assertIn(('STORE','7','+FLAGS','(\\Deleted)'),draft.calls);self.assertIn(('EXPUNGE','7'),draft.calls);self.assertNotIn(('expunge',),draft.calls)
        normal=Box('\\Seen');self.assertFalse(mail_pro.remove_draft(normal,'INBOX',7))
        self.assertFalse([call for call in normal.calls if call[0] in ('STORE','EXPUNGE','expunge')])


class FakeInbox:
    """Servidor IMAP ficticio y mínimo: bandeja con UID crecientes, cuota y dos carpetas de correo no deseado."""
    def __init__(self,uids):self.uids=list(uids);self.seen=set();self.quota_line=b'"User quota" (STORAGE 800 1000)'
    def list(self):return 'OK',[b'(\\HasNoChildren) "." INBOX',b'(\\HasNoChildren \\Junk) "." INBOX.Junk',b'(\\HasNoChildren) "." INBOX.spam']
    def status(self,name,fields):
        inbox=name.strip('"')=='INBOX';unread=len([u for u in self.uids if u not in self.seen]) if inbox else 0
        return 'OK',[('%s (MESSAGES %d UNSEEN %d UIDNEXT %d UIDVALIDITY 77)'%(name,len(self.uids) if inbox else 0,unread,max(self.uids)+1 if inbox else 1)).encode()]
    def select(self,name,readonly=True):return 'OK',[b'1']
    def getquotaroot(self,name):return 'OK',[[b'INBOX "User quota"'],[self.quota_line]]
    def logout(self):pass
    def uid(self,command,*args):
        if command=='SEARCH':return 'OK',[' '.join(str(u) for u in self.uids if u>=int(args[-1].split(':')[0]) or u==max(self.uids)).encode()]
        data=[]
        for u in (int(x) for x in args[0].split(',')):
            flags='\\Seen' if u in self.seen else ''
            data+=[(('%d (UID %d FLAGS (%s) RFC822.SIZE 900 BODYSTRUCTURE ("text" "plain" NIL NIL NIL "7bit" 5 1) BODY[HEADER.FIELDS (FROM)] {60}'%(u,u,flags)).encode(),('From: Cliente ficticio <cliente@example.invalid>\r\nSubject: Consulta %d\r\nDate: Fri, 02 Jan 2026 10:00:00 -0500\r\n\r\n'%u).encode()),b')']
        return 'OK',data


for name in [name for name in dir(test_app.SecurityTests) if name.startswith('test_')]:
    setattr(MailRouteTests,name,None)
del test_app
