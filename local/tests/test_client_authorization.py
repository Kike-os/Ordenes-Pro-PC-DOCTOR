"""Autorización electrónica del cliente por enlace seguro (SMTP simulado: no se envía nada real)."""
import io,json,re,unittest
from email.message import Message
from unittest.mock import patch
from urllib.parse import urlencode
import test_app
import app,mail_pro,client_authorization
app.os.environ.setdefault('LOGIN_CAPTCHA','off')

CONFIG={'imap_host':'imap.example.invalid','imap_port':993,'smtp_host':'smtp.example.invalid','smtp_port':465,'username':'taller@example.invalid','password':'x'}


class ClientAuthorizationTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data

    def form(self,token,fields):
        """Envío de formulario como lo hace el navegador del cliente: sin sesión ni JSON."""
        handler=object.__new__(app.Handler);handler.path='/autorizar/'+token;handler.client_address=('203.0.113.9',40000);handler.headers=Message()
        handler.headers['Content-Type']='application/x-www-form-urlencoded';handler.headers['User-Agent']='Navegador de prueba';raw=urlencode(fields).encode();handler.headers['Content-Length']=str(len(raw));handler.rfile=io.BytesIO(raw);result={}
        handler.reply=lambda status,body,content_type=None,cookie=None,filename=None:result.update(status=status,body=body,type=content_type)
        handler.do_POST();return result

    def start(self,cookie,csrf,sent,**changes):
        oid=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','brand':'HP','model':'ProBook','request_key':'client-auth-order-%04d'%len(sent),**changes}),cookie=cookie,csrf=csrf)['body']['id']
        made=self.request('/api/orders/%d/client-authorization'%oid,{'action':'send'},cookie=cookie,csrf=csrf)
        return oid,made

    def test_full_flow_identity_code_decisions_evidence_and_notices(self):
        cookie,csrf=self.login();sent=[]
        def deliver(config,message,recipients):sent.append((message,recipients))
        with patch.object(mail_pro,'configured',return_value=True),patch.object(mail_pro,'settings',return_value=CONFIG),patch.object(mail_pro,'deliver',side_effect=deliver):
            oid,made=self.start(cookie,csrf,sent)
            self.assertEqual(made['status'],200,made);self.assertEqual(made['body']['result'],'sent');url=made['body']['url'];token=url.rsplit('/',1)[1]
            link_mail=[m for m,r in sent if 'Autorización de servicio' in str(m['Subject'])][-1]
            self.assertIn(url,link_mail.get_body(preferencelist=('plain',)).get_content());self.assertTrue([part for part in link_mail.iter_attachments() if part.get_content_type()=='image/png'])
            with app.connect() as c:stored=dict(c.execute('SELECT * FROM client_authorizations WHERE order_id=?',(oid,)).fetchone())
            self.assertNotIn(token,json.dumps(stored));self.assertEqual(stored['token_hash'],client_authorization.digest(token))
            # Paso 1: identificación enmascarada, sin revelar los últimos dígitos.
            page=self.request('/autorizar/'+token);self.assertEqual(page['status'],200);self.assertIn('01********',page['body']);self.assertNotIn('0017',page['body']);self.assertNotIn('0100000017',page['body'])
            self.assertEqual(self.request('/autorizar/'+'x'*43)['status'],404)
            wrong=self.form(token,{'step':'identify','last4':'9999'});self.assertIn('no coinciden',wrong['body'])
            before=len(sent);right=self.form(token,{'step':'identify','last4':'0017'});self.assertIn('Código de verificación',right['body'])
            code_mail=sent[before][0];self.assertEqual(sent[before][1],['cliente@example.invalid']);code=re.search(r'\b(\d{6})\b',code_mail.get_body(preferencelist=('plain',)).get_content())[1]
            with app.connect() as c:self.assertNotIn(code,json.dumps(dict(c.execute('SELECT * FROM client_authorizations WHERE order_id=?',(oid,)).fetchone())))
            # Paso 2: código incorrecto y correcto.
            self.assertIn('no es correcto',self.form(token,{'step':'verify','code':'000000' if code!='000000' else '111111'})['body'])
            decide=self.form(token,{'step':'verify','code':code});self.assertIn('Confirmar y firmar autorización',decide['body']);passkey=re.search(r'name="pass" value="([^"]+)"',decide['body'])[1]
            # Paso 3: nada se acepta por omisión.
            partial=self.form(token,{'step':'sign','pass':passkey,'service':'authorized','confirm':'1'});self.assertIn('Elija expresamente',partial['body'])
            with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM client_authorizations WHERE order_id=?',(oid,)).fetchone()[0],'pending')
            self.assertIn('caducó',self.form(token,{'step':'sign','pass':'otro','service':'authorized','operating_system':'authorized','files':'denied','data_operations':'denied','confirm':'1'})['body'])
            # La verificación fallida anterior obliga a repetir identidad: se vuelve a pedir el código.
            self.form(token,{'step':'identify','last4':'0017'});code=re.search(r'\b(\d{6})\b',sent[-1][0].get_body(preferencelist=('plain',)).get_content())[1]
            passkey=re.search(r'name="pass" value="([^"]+)"',self.form(token,{'step':'verify','code':code})['body'])[1]
            choices={'step':'sign','pass':passkey,'service':'authorized','operating_system':'authorized','files':'denied','data_operations':'denied','comment':'No respalden mis fotos.','confirm':'1'}
            with app.connect() as c:has_terms=bool(app.service_terms.current(c,app.reception_now()))
            if has_terms:
                self.assertIn('aceptar las condiciones',self.form(token,choices)['body']);choices['terms_accept']='1'
            before=len(sent);done=self.form(token,choices);self.assertIn('Sus decisiones quedaron registradas',done['body'])
            notice=[m for m,r in sent[before:] if 'Autorización del cliente' in str(m['Subject'])];self.assertEqual(len(notice),1)
            text=notice[0].get_body(preferencelist=('plain',)).get_content()
            for expected in ('Diagnóstico y servicio técnico solicitado: AUTORIZADO','Acceso a archivos personales y respaldos: NO AUTORIZADO','No respalden mis fotos.','Huella de la evidencia'):self.assertIn(expected,text)
            # Doble envío: no cambia nada ni repite el aviso.
            again=len(sent);self.form(token,choices);self.assertEqual(len(sent),again)
        state=self.request('/api/orders/%d'%oid,cookie=cookie)['body']['order']['client_authorization']
        self.assertEqual((state['status'],state['notice_result'],state['evidence']['decisions']['files']),('signed','sent','denied'))
        self.assertEqual(state['evidence']['method'],client_authorization.METHOD);self.assertEqual(bool(state['evidence']['terms']),has_terms)
        with app.connect() as c:row=dict(c.execute('SELECT * FROM client_authorizations WHERE order_id=?',(oid,)).fetchone())
        self.assertTrue(client_authorization.verify_evidence(row));self.assertFalse(client_authorization.verify_evidence(dict(row,evidence=row['evidence'].replace('denied','authorized'))))
        for path,kwargs in (('/autorizar/'+token+'/comprobante.pdf',{}),('/api/orders/%d/client-authorization.pdf'%oid,{'cookie':cookie})):
            pdf=self.request(path,**kwargs);self.assertEqual(pdf['status'],200);self.assertTrue(pdf['body'].startswith(b'%PDF'))
        self.assertEqual(self.request('/api/orders/%d/client-authorization.pdf'%oid)['status'],401)
        # Las autorizaciones registradas por el técnico no se tocan.
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM order_access_consents WHERE order_id=?',(oid,)).fetchone()[0],1)

    def test_limits_lock_expiry_replacement_and_requirements(self):
        cookie,csrf=self.login();sent=[]
        with patch.object(mail_pro,'configured',return_value=True),patch.object(mail_pro,'settings',return_value=CONFIG),patch.object(mail_pro,'deliver',side_effect=lambda *a:sent.append(a)):
            # Sin correo válido no hay enlace; sin sesión o sin permiso tampoco.
            bare=self.request('/api/orders',self.order_data({'client':'Cliente Sin Correo','identification':'0100000025','email':'','request_key':'client-auth-noemail-01'}),cookie=cookie,csrf=csrf)['body']['id']
            self.assertEqual(self.request('/api/orders/%d/client-authorization'%bare,{'action':'send'},cookie=cookie,csrf=csrf)['status'],400)
            self.assertEqual(self.request('/api/orders/%d/client-authorization'%bare,{'action':'send'})['status'],401)
            oid,first=self.start(cookie,csrf,sent);self.assertEqual(first['status'],200,first);old=first['body']['url'].rsplit('/',1)[1]
            # Un enlace nuevo deja sin efecto el anterior.
            new=self.request('/api/orders/%d/client-authorization'%oid,{'action':'send'},cookie=cookie,csrf=csrf)['body']['url'].rsplit('/',1)[1]
            self.assertIn('reemplazado',self.request('/autorizar/'+old)['body']);self.assertIn('reemplazado',self.form(old,{'step':'identify','last4':'0017'})['body'])
            # Cinco intentos fallidos bloquean el enlace, también con los dígitos correctos después.
            for _ in range(client_authorization.MAX_ID_ATTEMPTS):page=self.form(new,{'step':'identify','last4':'1234'})
            self.assertIn('se bloqueó',page['body']);self.assertIn('se bloqueó',self.form(new,{'step':'identify','last4':'0017'})['body'])
            # Caducidad.
            fresh=self.request('/api/orders/%d/client-authorization'%oid,{'action':'send'},cookie=cookie,csrf=csrf)['body']['url'].rsplit('/',1)[1]
            with app.connect() as c:c.execute("UPDATE client_authorizations SET expires_at='2020-01-01T00:00:00-05:00' WHERE token_hash=?",(client_authorization.digest(fresh),))
            self.assertIn('caducó',self.request('/autorizar/'+fresh)['body'])
        # Apagado por defecto: registrar una orden no envía nada al cliente.
        self.assertFalse(self.request('/api/orders/%d'%oid,cookie=cookie)['body']['order']['client_authorization_auto'])
        self.assertEqual(self.request('/api/client-authorization/settings',{'auto':'sí'},cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request('/api/client-authorization/settings',{'auto':True},cookie=cookie,csrf=csrf)['status'],200)
        with patch.object(mail_pro,'configured',return_value=True),patch.object(mail_pro,'settings',return_value=CONFIG),patch.object(mail_pro,'deliver',side_effect=lambda *a:sent.append(a)):
            made=self.request('/api/orders',self.order_data({'email':'auto@example.invalid','request_key':'client-auth-auto-0001'}),cookie=cookie,csrf=csrf)['body']
        self.assertEqual(made['client_authorization']['result'],'sent');self.assertNotIn('url',made['client_authorization'])


if __name__=='__main__':
    unittest.main()
