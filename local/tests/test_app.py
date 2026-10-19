import io
import re
from urllib.parse import quote
import json
import sys
import tempfile
import time
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
app.os.environ.setdefault('UPDATE_REGISTRY_URL','off')  # Las pruebas no consultan el registro publicado.
app.os.environ.setdefault('LOGIN_CAPTCHA','off')  # Las pruebas inician sesión sin verificación salvo que la activen.


def open_requests():
    """Las solicitudes de cita en línea se cierran a una hora fija: con el reloj real la batería no debe depender de la hora en que se
    ejecuta. Las pruebas que fijan su propia hora (patch de reception_now) siguen usando la regla real."""
    import business_hours
    from unittest.mock import Mock
    real=business_hours.requests_open
    return patch.object(business_hours,'requests_open',side_effect=lambda config,now:real(config,now) if isinstance(app.reception_now,Mock) else (True,''))


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hash = app.password_hash('contraseña-segura-de-prueba')

    def setUp(self):
        self.jobs=patch.object(app,'dispatch_security_job',side_effect=lambda job:job())
        self.jobs.start()
        self.request_clock=open_requests()
        self.request_clock.start()
        self.temp = tempfile.TemporaryDirectory()
        self.paths = patch.multiple(app, DATA=Path(self.temp.name), DB=Path(self.temp.name)/'test.sqlite3')
        self.paths.start()
        self.env = patch.dict(app.os.environ, {'APP_URL':'http://127.0.0.1:8010','SESSION_SECURE':'false','MAIL_IMAP_HOST':'','MAIL_SMTP_HOST':'','MAIL_USERNAME':'','MAIL_PASSWORD':'','SMTP_HOST':'','SMTP_FROM':'','ANTHROPIC_API_KEY':'','OPENAI_API_KEY':''})
        self.env.start()
        app.migrate()
        with app.connect() as c:
            self.uid = c.execute('INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES (?,?,?,?,?,?)',('demo','demo@example.invalid','Persona de prueba',self.hash,'administrador',int(time.time()))).lastrowid
            if self.__class__.__name__!='ServiceTermsTests':
                app.service_terms.publish(c,{'version':'FIXTURE-ONLY','effective_date':'2020-01-01','full_text':'Condiciones ficticias de prueba, sin efectos reales.','compact_text':'Resumen ficticio de prueba.','approved':True},{'id':self.uid},app.reception_now())

    def tearDown(self):
        self.request_clock.stop()
        self.jobs.stop()
        self.env.stop()
        self.paths.stop()
        self.temp.cleanup()

    def request(self,path,body=None,cookie='',origin='http://127.0.0.1:8010',csrf=''):
        handler = object.__new__(app.Handler)
        handler.path=path
        handler.client_address=('127.0.0.1',12345)
        handler.headers=Message()
        handler.headers['Cookie']=cookie
        handler.headers['Origin']=origin
        handler.headers['Content-Type']='application/json'
        handler.headers['X-CSRF-Token']=csrf
        raw=json.dumps(body or {}).encode()
        handler.headers['Content-Length']=str(len(raw))
        handler.rfile=io.BytesIO(raw)
        result={}
        def reply(status,body,content_type=None,cookie=None,filename=None):
            result.update(status=status,body=body,cookie=cookie)
        handler.reply=reply
        if body is None:
            handler.do_GET()
        else:
            handler.do_POST()
        return result

    def order_data(self, overrides=None):
        data={'client':'Cliente ficticio','identification':'0100000017','phone':'0991234567',
                'document_type':'cedula','province':'Azuay','province_code':'01','canton':'Cuenca','canton_code':'0101','parish':'Bellavista','parish_code':'010101','city':'Cuenca','locality_code':'010150','main_street':'Dirección ficticia 123','address':'Dirección ficticia 123',
                'type':'portatil','problem':'No enciende','physical_condition':'Sin golpes visibles','technical_access':'denied','access_confirmed':True,
                **(overrides or {})}
        import client_registry
        with app.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT id FROM clients WHERE identification=?',(data['identification'],)).fetchone()
            if row:cid=row[0]
            else:
                fields,errors=client_registry.validate(dict(data,name=data['client']))
                if errors:raise AssertionError(('Ficha de prueba inválida',errors))
                cid=c.execute('INSERT INTO clients('+','.join(client_registry.KEYS)+') VALUES ('+','.join('?' for _ in client_registry.KEYS)+')',tuple(fields[k] for k in client_registry.KEYS)).lastrowid
            data['client_id']=str(cid)
            if self.__class__.__name__!='ServiceTermsTests':
                terms=app.service_terms.current(c,app.reception_now())
                if terms:
                    data.setdefault('terms_document_id',terms['id']);data.setdefault('terms_accept',True)
        return data

    def login(self,remember=False):
        result=self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba','remember':remember})
        self.assertEqual(result['status'],200)
        cookie=result['cookie'].split(';')[0]
        me=self.request('/api/me',cookie=cookie)
        return cookie,me['body']['user']['csrf']

    def test_password_is_salted_and_verified(self):
        self.assertTrue(app.password_ok('contraseña-segura-de-prueba',self.hash))
        self.assertFalse(app.password_ok('otra',self.hash))
        self.assertNotEqual(self.hash,app.password_hash('contraseña-segura-de-prueba'))
        self.assertNotIn('contraseña',self.hash)

    def test_migrations_are_repeatable(self):
        app.migrate()
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_private_routes_require_session(self):
        for path in ('/api/me','/api/dashboard'):
            self.assertEqual(self.request(path)['status'],401)

    def test_errors_do_not_disclose_account(self):
        existing=self.request('/api/login',{'login':'demo','password':'incorrecta'})
        missing=self.request('/api/login',{'login':'nadie','password':'incorrecta'})
        self.assertEqual(existing['body'],missing['body'])
        self.assertEqual(existing['status'],401)

    def test_rate_limit(self):
        for _ in range(8):
            self.request('/api/login',{'login':'demo','password':'incorrecta'})
        self.assertEqual(self.request('/api/login',{'login':'demo','password':'incorrecta'})['status'],429)

    def test_cookie_and_csrf(self):
        cookie,csrf=self.login()
        self.assertNotIn('contraseña',cookie)
        self.assertEqual(self.request('/api/logout',{},cookie=cookie)['status'],403)
        self.assertEqual(self.request('/api/logout',{},cookie=cookie,csrf=csrf)['status'],200)
        self.assertEqual(self.request('/api/me',cookie=cookie)['status'],401)

    def test_remember_and_secure_cookie(self):
        with patch.dict(app.os.environ,{'SESSION_SECURE':'true'}):
            result=self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba','remember':True})
        for value in ('HttpOnly','Secure','SameSite=Strict','Max-Age=2592000'):
            self.assertIn(value,result['cookie'])

    def test_loopback_aliases_preserve_origin_protection(self):
        # Cuerpo vacío: comprueba el origen sin probar credenciales ni registrar fallos.
        self.assertEqual(self.request('/api/login',{},origin='http://localhost:8010')['status'],400)
        for origin in ('http://localhost:8011','http://localhost.evil.invalid:8010','null','', 'https://localhost:8010'):
            self.assertEqual(self.request('/api/login',{},origin=origin)['status'],403)
        with patch.dict(app.os.environ,{'APP_URL':'https://example.invalid'}):
            self.assertEqual(self.request('/api/login',{},origin='http://localhost:8010')['status'],403)
        with patch.dict(app.os.environ,{'APP_URL':'http://192.168.1.20:8010'}):
            self.assertEqual(self.request('/api/login',{},origin='http://localhost:8010')['status'],403)

    def test_foreign_origin_is_blocked(self):
        self.assertEqual(self.request('/api/login',{'login':'demo','password':'x'},origin='https://evil.invalid')['status'],403)

    def test_lan_origin_requires_configured_address(self):
        data={'login':'demo','password':'contraseña-segura-de-prueba'}
        with patch.dict(app.os.environ,{'APP_URL':'http://192.168.1.20:8010'}):
            self.assertEqual(self.request('/api/login',data,origin='http://192.168.1.20:8010')['status'],200)
            self.assertEqual(self.request('/api/login',data,origin='http://192.168.1.21:8010')['status'],403)

    def test_order_real_counts_and_audit(self):
        cookie,csrf=self.login()
        data=self.order_data({'brand':'Prueba','model':'M1'})
        result=self.request('/api/orders',data,cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],201)
        dash=self.request('/api/dashboard',cookie=cookie)['body']
        self.assertEqual(sum(dash['counts'].values()),1)
        self.assertEqual(dash['counts']['pendiente'],1)
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='order_created'").fetchone()[0],1)
            with self.assertRaises(app.sqlite3.IntegrityError):
                c.execute("UPDATE audit SET action='alterado'")

    def test_technician_can_create_reception(self):
        cookie,csrf=self.login()
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        self.assertEqual(self.request('/api/orders',self.order_data(),cookie=cookie,csrf=csrf)['status'],201)

    def test_invalid_order_creates_no_rows(self):
        cookie,csrf=self.login()
        self.assertEqual(self.request('/api/orders',{'client':'Ficticio','type':'otro','problem':'Prueba'},cookie=cookie,csrf=csrf)['status'],400)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM clients').fetchone()[0],0)

    def test_reset_single_use_and_sessions_revoked(self):
        cookie,_=self.login()
        tokens=[]
        with patch.object(app,'send_reset',side_effect=lambda email,token:tokens.append(token)):
            result=self.request('/api/forgot',{'email':'demo@example.invalid'})
        self.assertEqual(result['status'],200)
        token=tokens[0]
        with app.connect() as c:
            self.assertNotEqual(c.execute('SELECT token_hash FROM reset_tokens').fetchone()[0],token)
        body={'token':token,'password':'nueva-contraseña-segura'}
        self.assertEqual(self.request('/api/reset',body)['status'],200)
        self.assertEqual(self.request('/api/reset',body)['status'],400)
        self.assertEqual(self.request('/api/me',cookie=cookie)['status'],401)

    def test_expired_token_rejected(self):
        with app.connect() as c:
            c.execute('INSERT INTO reset_tokens VALUES (?,?,?)',(app.digest('vencido'),self.uid,int(time.time())-1))
        self.assertEqual(self.request('/api/reset',{'token':'vencido','password':'contraseña-segura-nueva'})['status'],400)

    def test_reset_generic_even_when_smtp_fails(self):
        with patch.object(app,'send_reset',side_effect=RuntimeError('SMTP no configurado')):
            a=self.request('/api/forgot',{'email':'demo@example.invalid'})
            b=self.request('/api/forgot',{'email':'nadie@example.invalid'})
        self.assertEqual(a['body'],b['body'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM reset_tokens').fetchone()[0],0)

    def test_fifth_failure_starts_full_lock_without_extension(self):
        with patch.object(app.time,'time',return_value=2000000000),patch.object(app,'LOGIN_WAITS',{}):
            for _ in range(4):
                self.assertEqual(self.request('/api/login',{'login':'demo','password':'wrong'})['status'],401)
        with patch.object(app.time,'time',return_value=2000000800):
            self.assertEqual(self.request('/api/login',{'login':'demo','password':'wrong'})['status'],429)
            with app.connect() as c:
                expiry=c.execute('SELECT expires FROM attempts WHERE bucket=?',('login-user:'+app.digest('demo'),)).fetchone()[0]
            self.assertEqual(expiry,2000001700)
        with patch.object(app.time,'time',return_value=2000001000):
            self.assertEqual(self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba'})['status'],429)
            with app.connect() as c:self.assertEqual(c.execute('SELECT expires FROM attempts WHERE bucket=?',('login-user:'+app.digest('demo'),)).fetchone()[0],expiry)
        with patch.object(app.time,'time',return_value=expiry):
            self.assertEqual(self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba'})['status'],200)

    def test_policy_bounds_permissions_and_session_expiry(self):
        cookie,csrf=self.login()
        policy={'lockout_seconds':'1200','session_hours':'2','remember_days':'7','password_min':'16'}
        self.assertEqual(self.request('/api/auth/policy',policy,cookie=cookie)['status'],403)
        self.assertEqual(self.request('/api/auth/policy',dict(policy,password_min='5'),cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request('/api/auth/policy',policy,cookie=cookie,csrf=csrf)['status'],200)
        result=self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba','remember':True},cookie=cookie)
        self.assertIn('Max-Age=604800',result['cookie'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM sessions').fetchone()[0],1)
            c.execute("UPDATE users SET role='tecnico'")
        new_cookie=result['cookie'].split(';')[0]
        me=self.request('/api/me',cookie=new_cookie)['body']['user']
        self.assertEqual(self.request('/api/auth/policy',policy,cookie=new_cookie,csrf=me['csrf'])['status'],403)

    def test_reset_changes_credentials_notifies_and_does_not_login(self):
        cookie,_=self.login()
        with app.connect() as c:c.execute('INSERT INTO reset_tokens VALUES (?,?,?)',(app.digest('test-reset'),self.uid,int(time.time())+1200))
        body={'token':'test-reset','password':'frase nueva de prueba segura','repeat':'otra'}
        self.assertEqual(self.request('/api/reset',body)['status'],400)
        body['repeat']=body['password']
        with patch.object(app,'send_security_mail') as mail:
            result=self.request('/api/reset',body)
            mail.assert_called_once()
            self.assertEqual(mail.call_args.args[0],'demo@example.invalid')
        self.assertEqual(result['status'],200)
        self.assertIsNone(result['cookie'])
        with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
        self.assertEqual(self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba'})['status'],401)
        self.assertEqual(self.request('/api/login',{'login':'demo','password':body['password']})['status'],200)

    def test_antibot_is_adaptive_and_verified_on_server(self):
        with patch.dict(app.os.environ,{'TURNSTILE_SITE_KEY':'public-key','TURNSTILE_SECRET_KEY':'private-key','TURNSTILE_LOGIN_MODE':'adaptive'}),patch.object(app,'LOGIN_WAITS',{}):
            for _ in range(2):self.assertEqual(self.request('/api/login',{'login':'demo','password':'wrong'})['status'],401)
            with patch.object(app,'verify_bot',return_value=False) as verify:
                result=self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba','bot_token':'forged'})
                self.assertEqual(result['status'],403)
                self.assertTrue(result['body']['challenge'])
                verify.assert_called_once_with('forged','login')
            with patch.object(app,'verify_bot',return_value=True):
                self.assertEqual(self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba','bot_token':'valid'})['status'],200)

    def test_antibot_is_required_on_every_login_when_configured(self):
        self.assertIn('data-sitekey=""',self.request('/login')['body'])
        with patch.dict(app.os.environ,{'TURNSTILE_SITE_KEY':'public-key','TURNSTILE_SECRET_KEY':'private-key'}):
            self.assertIn('data-sitekey="public-key"',self.request('/login')['body'])
            with patch.object(app,'verify_bot',return_value=False) as verify:
                result=self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba'})
                self.assertEqual(result['status'],403)
                self.assertTrue(result['body']['challenge'])
                verify.assert_called_once_with('','login')
            with patch.object(app,'verify_bot',return_value=True):
                self.assertEqual(self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba','bot_token':'valid'})['status'],200)
            with patch.dict(app.os.environ,{'TURNSTILE_LOGIN_MODE':'adaptive'}):
                self.assertIn('data-sitekey=""',self.request('/login')['body'])

    def test_local_captcha_is_single_use_and_verified_on_server(self):
        import hashlib
        good={'login':'demo','password':'contraseña-segura-de-prueba'}
        self.assertIn('data-captcha=""',self.request('/login')['body'])
        self.assertEqual(self.request('/api/captcha',{})['status'],404)
        with patch.dict(app.os.environ,{'LOGIN_CAPTCHA':'always'}),patch.object(app,'CAPTCHA_BITS',8):
            self.assertIn('data-captcha="local"',self.request('/login')['body'])
            for token in ('','local:'+'x'*32+':1'):
                result=self.request('/api/login',dict(good,bot_token=token))
                self.assertEqual(result['status'],403)
                self.assertTrue(result['body']['challenge'])
            challenge=self.request('/api/captcha',{})['body']
            self.assertEqual(challenge['bits'],8)
            work=lambda n:hashlib.sha256((challenge['nonce']+':'+str(n)).encode()).digest()[0]
            solved=next(n for n in range(100000) if work(n)==0)
            unsolved=next(n for n in range(100000) if work(n)!=0)
            token='local:'+challenge['nonce']+':'+str(solved)
            self.assertEqual(self.request('/api/login',dict(good,bot_token=token))['status'],200)
            self.assertEqual(self.request('/api/login',dict(good,bot_token=token))['status'],403)
            other=self.request('/api/captcha',{})['body']
            unsolved=next(n for n in range(100000) if hashlib.sha256((other['nonce']+':'+str(n)).encode()).digest()[0]!=0)
            self.assertEqual(self.request('/api/login',dict(good,bot_token='local:'+other['nonce']+':'+str(unsolved)))['status'],403)
            with app.connect() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM attempts WHERE bucket LIKE 'login-%'").fetchone()[0],0)
        with patch.dict(app.os.environ,{'LOGIN_CAPTCHA':'on','TURNSTILE_SITE_KEY':'public-key','TURNSTILE_SECRET_KEY':'private-key'}):
            self.assertIn('data-captcha="turnstile"',self.request('/login')['body'])

    def test_favicon_files_are_public_and_linked(self):
        for path,kind,magic in (('/favicon.ico','image/x-icon',b'\x00\x00\x01\x00'),('/static/favicon-16.png','image/png',b'\x89PNG'),('/static/favicon-32.png','image/png',b'\x89PNG'),('/static/favicon-48.png','image/png',b'\x89PNG'),('/static/apple-touch-icon.png','image/png',b'\x89PNG'),('/apple-touch-icon.png','image/png',b'\x89PNG')):
            handler=object.__new__(app.Handler);handler.path=path+'?v=2';handler.headers=Message();sent={}
            handler.reply=lambda status,body,content_type=None,cookie=None:sent.update(status=status,body=body,type=content_type)
            handler.do_GET()
            self.assertEqual((sent['status'],sent['type']),(200,kind),path)
            self.assertTrue(sent['body'].startswith(magic),path)
        handler=object.__new__(app.Handler);handler.path='/static/adi-widget.js';handler.headers=Message();sent={}
        handler.reply=lambda status,body,content_type=None,cookie=None:sent.update(status=status,type=content_type)
        handler.do_GET()
        self.assertEqual((sent['status'],sent['type']),(200,'text/javascript; charset=utf-8'))
        self.assertIn('src="/static/adi-widget.js"',self.request('/citas')['body'])
        notice=self.request('/privacidad')
        self.assertEqual(notice['status'],200)
        self.assertIn('<h1>Aviso de privacidad</h1>',notice['body'])
        self.assertIn(app.corporate.settings()['support_email'],notice['body'])
        self.assertNotIn('{{',notice['body'])
        self.assertIn('href="/privacidad"',self.request('/citas')['body'])
        import versioning
        current=versioning.load()['releases'][0]['version']
        page=self.request('/login')['body']
        self.assertIn('Versión del sistema',page);self.assertIn('<strong>v'+current+'</strong>',page);self.assertIn('data-state="checking"',page);self.assertNotIn('Release',page);self.assertNotIn('{{',page)
        # El estado no viene escrito en la página: lo da el servidor al comprobar la versión desplegada contra el registro publicado.
        with patch.object(versioning,'registry_url',return_value=''):
            status=self.request('/api/public/version')['body']
        self.assertEqual((status['version'],status['state'],status['latest']),(current,'updated',current));self.assertTrue(status['notes'])
        newer={'unreleased':{},'releases':[dict(versioning.load()['releases'][0],version='99.0.0',type='minor')]+versioning.load()['releases']}
        with patch.object(versioning,'registry_url',return_value='https://example.invalid/r.json'),patch.object(versioning,'fetch_published',return_value=newer):
            self.assertEqual(self.request('/api/public/version')['body']['state'],'updated')  # dentro de los 20 minutos se usa la comprobación guardada
            found=self.request('/api/public/version?refresh=1')['body']
        self.assertEqual((found['state'],found['latest'],found['version']),('important','99.0.0',current))
        with patch.object(versioning,'registry_url',return_value='https://example.invalid/r.json'),patch.object(versioning,'fetch_published',side_effect=versioning.RegistryError('x')):
            self.assertEqual(self.request('/api/public/version?refresh=1')['body']['state'],'error')
        news=self.request('/novedades')
        self.assertEqual(news['status'],200)
        self.assertIn('<span>v'+current+'</span><em>Última versión</em>',news['body'])
        for page in ('/login','/forgot','/citas'):
            body=self.request(page)['body']
            self.assertIn('href="/favicon.ico?v=2"',body)
            self.assertIn('rel="apple-touch-icon"',body)
        self.assertIn('<title>Órdenes Pro | PC-DOCTOR S.A.</title>',self.request('/login')['body'])

    def test_public_registration_is_closed_and_only_admin_creates_accounts(self):
        data={'name':'Persona Solicitante','username':'nueva.persona','email':'nueva@example.invalid','phone':'0991234567','identification':'','job_title':'Técnico de prueba','password':'clave-de-prueba','repeat':'clave-de-prueba'}
        # Sin registro público: ni enlace en el acceso, ni página, ni alta por la API.
        page=self.request('/login')['body'];self.assertNotIn('/registro',page);self.assertNotIn('Solicitar acceso',page)
        self.assertEqual(self.request('/registro')['status'],404)
        self.assertEqual(self.request('/api/register',data)['status'],404)
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM users WHERE username='nueva.persona'").fetchone()[0],0)
        new={'name':'Persona Nueva','email':'nueva@example.invalid','username':'','role':'tecnico'}
        self.assertEqual(self.request('/api/users/create',new)['status'],401)
        cookie,csrf=self.login()
        self.assertEqual(self.request('/api/users/create',new,cookie=cookie)['status'],403)
        self.assertIn('settings?tab=users',self.request('/registro',cookie=cookie)['body'])
        bad=self.request('/api/users/create',{'name':'x','email':'sin-arroba','username':'a b','role':'jefe'},cookie=cookie,csrf=csrf)
        self.assertEqual((bad['status'],set(bad['body']['fields'])),(400,{'name','email','username','role'}))
        sent=[]
        with patch.object(app,'security_mail_ready',return_value='mail'),patch.object(app,'send_security_mail',side_effect=lambda *mail:sent.append(mail)):
            made=self.request('/api/users/create',new,cookie=cookie,csrf=csrf)
        self.assertEqual((made['status'],made['body']['mail'],made['body']['link'],made['body']['username']),(201,'sent','','nueva'))
        # El correo lleva solo el enlace temporal: ninguna contraseña. La cuenta queda aprobada y activa, con una clave que nadie conoce.
        self.assertEqual(sent[0][0],'nueva@example.invalid');link=re.search(r'http\S+/reset\?token=\S+',sent[0][2])[0];token=link.split('token=')[1]
        self.assertEqual(len(re.findall(r'token=',sent[0][2])),1);self.assertIn('Establecer mi contraseña',sent[0][3])
        uid=made['body']['id']
        with app.connect() as c:
            row=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            self.assertEqual((row['active'],row['approval'],row['role'],row['name']),(1,'approved','tecnico','Persona Nueva'))
            self.assertEqual({r[0] for r in c.execute("SELECT action FROM audit WHERE entity_id=?",(uid,))},{'account_created','account_invitation_sent'})
            self.assertGreater(c.execute('SELECT expires FROM reset_tokens WHERE user_id=?',(uid,)).fetchone()[0],time.time()+71*3600)
        self.assertEqual(self.request('/api/users/create',new,cookie=cookie,csrf=csrf)['body']['fields'],{'email':'Ya existe una cuenta con ese correo.'})
        self.assertIn('nueva',[a['username'] for a in self.request('/api/settings',cookie=cookie)['body']['accounts']])
        # La persona establece su propia contraseña con el enlace (un solo uso) y la activación queda registrada.
        self.assertEqual(self.request('/api/login',{'login':'nueva','password':'clave-elegida-por-mi'})['status'],401)
        self.assertEqual(self.request('/api/reset',{'token':token,'password':'clave-elegida-por-mi','repeat':'clave-elegida-por-mi'})['status'],200)
        self.assertEqual(self.request('/api/reset',{'token':token,'password':'otra-clave-distinta','repeat':'otra-clave-distinta'})['status'],400)
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='account_activated' AND entity_id=?",(uid,)).fetchone()[0],1)
        granted=self.request('/api/login',{'login':'nueva','password':'clave-elegida-por-mi'});self.assertEqual(granted['status'],200)
        # Un técnico no puede crear cuentas, restablecer accesos ni abrir /registro.
        tech=granted['cookie'].split(';')[0];tech_csrf=self.request('/api/me',cookie=tech)['body']['user']['csrf']
        self.assertEqual(self.request('/api/users/create',dict(new,email='otra@example.invalid'),cookie=tech,csrf=tech_csrf)['status'],403)
        self.assertEqual(self.request('/api/users/access',{'id':str(self.uid)},cookie=tech,csrf=tech_csrf)['status'],403)
        self.assertEqual(self.request('/registro',cookie=tech)['status'],404)
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM users WHERE email='otra@example.invalid'").fetchone()[0],0)
        # Restablecer acceso: sin correo disponible, el enlace se entrega una vez a administración; el anterior queda sustituido.
        with patch.object(app,'security_mail_ready',return_value=''):
            reset=self.request('/api/users/access',{'id':str(uid)},cookie=cookie,csrf=csrf)['body']
        self.assertEqual(reset['mail'],'unavailable');self.assertIn('/reset?token=',reset['link'])
        self.assertEqual(self.request('/api/users/access',{'id':str(self.uid)},cookie=cookie,csrf=csrf)['status'],400)
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='account_access_reset' AND entity_id=?",(uid,)).fetchone()[0],1)
        # Las solicitudes antiguas siguen pudiendo aprobarse o rechazarse.
        with app.connect() as c:old=c.execute("INSERT INTO users(username,email,name,password_hash,role,active,created_at,approval,requested_at) VALUES ('antigua','antigua@example.invalid','Solicitud Antigua','x','tecnico',0,0,'pending',0)").lastrowid
        self.assertEqual([r['username'] for r in self.request('/api/settings',cookie=cookie)['body']['requests']],['antigua'])
        self.assertEqual(self.request('/api/users/approval',{'id':str(old),'action':'approve','role':'tecnico'},cookie=cookie,csrf=csrf)['status'],200)

    def test_notifications_are_per_user_and_read_state_persists(self):
        self.assertEqual(self.request('/api/notifications')['status'],401)
        cookie,csrf=self.login()
        with app.connect() as c:
            other=c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico','tec@example.invalid','Técnico de prueba',?,'tecnico',1)",(self.hash,)).lastrowid
        tech=self.request('/api/login',{'login':'tecnico','password':'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        tech_csrf=self.request('/api/me',cookie=tech)['body']['user']['csrf']
        created=self.request('/api/orders',self.order_data({'request_key':'notification-request-key-0001'}),cookie=tech,csrf=tech_csrf)
        self.assertEqual(created['status'],201,created)
        mine=self.request('/api/notifications',cookie=cookie)['body']
        events=[item for item in mine['items'] if item['key'].startswith('event:')]
        self.assertEqual(len(events),1)
        self.assertIn('Nueva orden registrada',events[0]['title'])
        self.assertEqual(events[0]['href'],'#orders?id='+str(created['body']['id']))
        self.assertTrue(any(item['key'].startswith('version:') for item in mine['items']))
        self.assertEqual(mine['unread'],len(mine['items']))
        # Quien hizo el cambio no recibe su propio evento.
        theirs=self.request('/api/notifications',cookie=tech)['body']
        self.assertFalse([item for item in theirs['items'] if item['key'].startswith('event:')])
        self.assertEqual(self.request('/api/notifications/read',{'keys':events[0]['key']},cookie=cookie)['status'],403)
        after=self.request('/api/notifications/read',{'keys':events[0]['key']+',event:999999,otra cosa'},cookie=cookie,csrf=csrf)['body']
        self.assertEqual(after['unread'],mine['unread']-1)
        self.assertTrue(next(item for item in after['items'] if item['key']==events[0]['key'])['read'])
        with app.connect() as c:
            self.assertEqual([tuple(r) for r in c.execute('SELECT user_id,key FROM notification_reads')],[(self.uid if isinstance(self.uid,int) else 1,events[0]['key'])])
        # La lectura es de cada usuario y sobrevive a una recarga.
        self.assertEqual(self.request('/api/notifications',cookie=cookie)['body']['unread'],after['unread'])
        self.assertEqual(self.request('/api/notifications',cookie=tech)['body']['unread'],theirs['unread'])
        self.assertEqual(self.request('/api/notifications/read',{'all':True},cookie=cookie,csrf=csrf)['body']['unread'],0)

    def test_password_change_other_sessions_and_account_management(self):
        cookie,csrf=self.login()
        second=self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        settings=self.request('/api/settings',cookie=cookie)['body']
        self.assertEqual((settings['active_sessions'],settings['accounts'][0]['sessions']),(2,2))
        self.assertTrue(settings['accounts'][0]['last_login'])
        self.assertIn('Inicio de sesión',[item['label'] for item in settings['security_activity']])
        self.assertEqual(self.request('/api/sessions/revoke-others',{},cookie=cookie)['status'],403)
        self.assertEqual(self.request('/api/sessions/revoke-others',{},cookie=cookie,csrf=csrf)['body']['closed'],1)
        self.assertEqual(self.request('/api/me',cookie=second)['status'],401)
        self.assertEqual(self.request('/api/me',cookie=cookie)['status'],200)
        second=self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        change=lambda **values:self.request('/api/account/password',{'current':'contraseña-segura-de-prueba','password':'nueva-clave-ficticia','repeat':'nueva-clave-ficticia',**values},cookie=cookie,csrf=csrf)
        self.assertEqual(change(current='incorrecta')['body']['fields'],{'current':'La contraseña actual no es correcta.'})
        self.assertIn('repeat',change(repeat='otra')['body']['fields'])
        self.assertIn('password',change(password='abc',repeat='abc')['body']['fields'])
        self.assertEqual(change()['status'],200)
        self.assertEqual(self.request('/api/me',cookie=second)['status'],401)
        self.assertEqual(self.request('/api/me',cookie=cookie)['status'],200)
        self.assertEqual(self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba'})['status'],401)
        self.assertEqual(self.request('/api/login',{'login':'demo','password':'nueva-clave-ficticia'})['status'],200)
        with app.connect() as c:
            other=c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico','tec@example.invalid','Técnico de prueba',?,'tecnico',1)",(self.hash,)).lastrowid
            me=c.execute("SELECT id FROM users WHERE username='demo'").fetchone()[0]
        tech=self.request('/api/login',{'login':'tecnico','password':'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        tech_csrf=self.request('/api/me',cookie=tech)['body']['user']['csrf']
        manage=lambda who,token,**values:self.request('/api/users/manage',values,cookie=who,csrf=token)
        self.assertEqual(manage(tech,tech_csrf,id=str(me),action='deactivate')['status'],403)
        self.assertEqual(manage(cookie,csrf,id=str(me),action='deactivate')['status'],400)
        self.assertEqual(manage(cookie,csrf,id=str(other),action='role',role='otro')['status'],400)
        self.assertEqual(manage(cookie,csrf,id=str(other),action='deactivate')['status'],200)
        self.assertEqual(self.request('/api/me',cookie=tech)['status'],401)
        self.assertEqual(self.request('/api/login',{'login':'tecnico','password':'contraseña-segura-de-prueba'})['status'],401)
        self.assertEqual(manage(cookie,csrf,id=str(other),action='activate')['status'],200)
        self.assertEqual(manage(cookie,csrf,id=str(other),action='role',role='administrador')['status'],200)
        with app.connect() as c:self.assertEqual(tuple(c.execute('SELECT role,active FROM users WHERE id=?',(other,)).fetchone()),('administrador',1))

    def test_order_photos_require_session_are_validated_and_limited(self):
        import base64
        cookie,csrf=self.login()
        created=self.request('/api/orders',self.order_data(),cookie=cookie,csrf=csrf);self.assertEqual(created['status'],201);oid=created['body']['id']
        jpeg=b'\xff\xd8\xff\xe0'+b'x'*400+b'\xff\xd9';body={'data':base64.b64encode(jpeg).decode(),'position':'0','main':True}
        self.assertEqual(self.request(f'/api/orders/{oid}/photos',body)['status'],401)
        self.assertEqual(self.request(f'/api/orders/{oid}/photos',body,cookie=cookie)['status'],403)
        first=self.request(f'/api/orders/{oid}/photos',body,cookie=cookie,csrf=csrf);self.assertEqual(first['status'],201)
        second=self.request(f'/api/orders/{oid}/photos',dict(body,position='1',main=False),cookie=cookie,csrf=csrf)['body']['id']
        # Solo JPEG real: se rechazan otros contenidos aunque lleguen como «foto».
        for bad in (b'<svg onload=alert(1)>'+b'x'*300,b'\x89PNG\r\n\x1a\n'+b'x'*300,b'\xff\xd8\xff'+b'x'*10):
            self.assertEqual(self.request(f'/api/orders/{oid}/photos',dict(body,data=base64.b64encode(bad).decode()),cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request(f'/api/orders/{oid}/photos',dict(body,data='no-es-base64!'),cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request('/api/orders/999999/photos',body,cookie=cookie,csrf=csrf)['status'],404)
        photos=self.request(f'/api/orders/{oid}',cookie=cookie)['body']['order']['photos']
        self.assertEqual([(p['id'],p['is_main']) for p in photos],[(first['body']['id'],1),(second,0)])
        self.assertEqual(self.request(f'/api/order-photo/{second}')['status'],401)
        image=self.request(f'/api/order-photo/{second}',cookie=cookie);self.assertEqual(image['body'],jpeg)
        # Cambiar la principal y eliminar; el número de orden y sus datos no cambian.
        self.assertEqual(self.request(f'/api/orders/{oid}/photos',{'action':'main','photo_id':str(second)},cookie=cookie,csrf=csrf)['status'],200)
        self.assertEqual(self.request(f'/api/orders/{oid}/photos',{'action':'delete','photo_id':str(first['body']['id'])},cookie=cookie,csrf=csrf)['status'],200)
        after=self.request(f'/api/orders/{oid}',cookie=cookie)['body']['order']
        self.assertEqual(([(p['id'],p['is_main']) for p in after['photos']],after['code']),([(second,1)],created['body']['code']))
        for i in range(app.ORDER_PHOTO_LIMIT-1):self.assertEqual(self.request(f'/api/orders/{oid}/photos',dict(body,main=False),cookie=cookie,csrf=csrf)['status'],201)
        self.assertEqual(self.request(f'/api/orders/{oid}/photos',dict(body,main=False),cookie=cookie,csrf=csrf)['status'],409)

    def test_public_chat_reports_real_advisor_state(self):
        first=self.request('/api/public/adi/message',{'message':'Hola, tengo una consulta ficticia'})
        self.assertEqual((first['status'],first['body']['state']),(201,'adi'))
        chat=first['cookie'].split(';')[0];cid=first['body']['conversation_id']
        self.assertEqual(self.request('/api/public/adi/messages',cookie=chat)['body']['state'],'adi')
        # Solicitar asesor: queda en espera y no se duplica el registro al repetir.
        self.assertEqual(self.request('/api/public/adi/human',{},cookie=chat)['body']['state'],'waiting')
        self.assertEqual(self.request('/api/public/adi/human',{},cookie=chat)['body']['state'],'waiting')
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM adi_messages WHERE conversation_id=? AND content='El cliente solicita atención humana.'",(cid,)).fetchone()[0],1)
        cookie,csrf=self.login()
        titles=[item['title'] for item in self.request('/api/notifications',cookie=cookie)['body']['items']]
        self.assertIn('1 cliente espera a un asesor',titles)
        self.assertEqual(self.request('/api/public/adi/messages',cookie=chat)['body']['state'],'waiting')
        # Solo cuando un usuario real responde se informa «asesor conectado».
        self.assertEqual(self.request(f'/api/adi/live/{cid}',{'action':'reply','message':'Hola, soy un asesor ficticio.'},cookie=cookie,csrf=csrf)['status'],200)
        seen=self.request('/api/public/adi/messages?after=0',cookie=chat)['body']
        self.assertEqual(seen['state'],'advisor')
        self.assertEqual(seen['messages'][-1]['author'],'operator')
        follow=self.request('/api/public/adi/message',{'message':'Gracias, sigo aquí'},cookie=chat)['body']
        self.assertEqual((follow['state'],follow['messages'][-1]['author']),('advisor','client'))
        self.assertNotIn('1 cliente espera a un asesor',[item['title'] for item in self.request('/api/notifications',cookie=cookie)['body']['items']])
        # Finalizada: se informa y, si el cliente vuelve a escribir, continúa con ADI conservando el historial.
        self.request(f'/api/adi/live/{cid}',{'action':'close'},cookie=cookie,csrf=csrf)
        self.assertEqual(self.request('/api/public/adi/messages',cookie=chat)['body']['state'],'closed')
        again=self.request('/api/public/adi/message',{'message':'¿Cuál es el horario?'},cookie=chat)
        self.assertEqual((again['body']['state'],again['body']['conversation_id'],again['body']['messages'][-1]['author']),('adi',cid,'adi'))
        self.assertGreaterEqual(len(self.request('/api/public/adi/messages?after=0',cookie=chat)['body']['messages']),6)

    def test_adi_conversations_are_saved_per_user(self):
        cookie,csrf=self.login()
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('otra','otra@example.invalid','Otra administradora',?,'administrador',1)",(self.hash,))
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico','tec@example.invalid','Técnico de prueba',?,'tecnico',1)",(self.hash,))
        session=lambda name:(lambda ck:(ck,self.request('/api/me',cookie=ck)['body']['user']['csrf']))(self.request('/api/login',{'login':name,'password':'contraseña-segura-de-prueba'})['cookie'].split(';')[0])
        other,other_csrf=session('otra');tech,tech_csrf=session('tecnico')
        first=self.request('/api/adi/admin',{'message':'Resumen del taller'},cookie=cookie,csrf=csrf)
        self.assertEqual(first['status'],200);cid=first['body']['conversation']['id']
        self.assertEqual(first['body']['conversation']['title'],'Resumen del taller')
        second=self.request('/api/adi/admin',{'message':'¿Qué órdenes están vencidas?','conversation_id':str(cid)},cookie=cookie,csrf=csrf)
        self.assertEqual(second['body']['conversation']['id'],cid)
        saved=self.request('/api/adi/conversations/'+str(cid),cookie=cookie)['body']
        self.assertEqual([m['role'] for m in saved['messages']],['user','adi','user','adi'])
        self.assertTrue(saved['messages'][1]['links'])
        self.assertEqual([r['id'] for r in self.request('/api/adi/conversations',cookie=cookie)['body']['rows']],[cid])
        self.assertEqual(len(self.request('/api/adi/conversations?q=vencidas',cookie=cookie)['body']['rows']),1)
        self.assertEqual(self.request('/api/adi/conversations?q=zzzz',cookie=cookie)['body']['rows'],[])
        # Otra persona no ve, continúa, renombra ni borra la conversación; un técnico no accede al módulo.
        self.assertEqual(self.request('/api/adi/conversations',cookie=other)['body']['rows'],[])
        self.assertEqual(self.request('/api/adi/conversations/'+str(cid),cookie=other)['status'],404)
        self.assertEqual(self.request('/api/adi/admin',{'message':'hola','conversation_id':str(cid)},cookie=other,csrf=other_csrf)['status'],404)
        self.assertEqual(self.request('/api/adi/conversations/'+str(cid),{'action':'delete'},cookie=other,csrf=other_csrf)['status'],404)
        self.assertEqual(self.request('/api/adi/conversations',cookie=tech)['status'],403)
        self.assertEqual(self.request('/api/adi/conversations/'+str(cid),{'action':'rename','title':'Revisión diaria'},cookie=cookie)['status'],403)
        self.assertEqual(self.request('/api/adi/conversations/'+str(cid),{'action':'rename','title':'Revisión diaria'},cookie=cookie,csrf=csrf)['body']['title'],'Revisión diaria')
        self.assertEqual(self.request('/api/adi/conversations/'+str(cid),{'action':'rename','title':''},cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request('/api/adi/conversations/'+str(cid),{'action':'delete'},cookie=cookie,csrf=csrf)['status'],200)
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM adi_admin_messages').fetchone()[0],0)

    def test_server_validation_and_https_cookie(self):
        for data in ({'login':'','password':'x'},{'login':'bad@','password':'x'},{'login':'demo','password':''}):
            self.assertEqual(self.request('/api/login',data)['status'],400)
        self.assertEqual(self.request('/api/forgot',{'email':'invalid'})['status'],400)
        with patch.dict(app.os.environ,{'APP_URL':'https://example.invalid','SESSION_SECURE':'false'}):
            self.assertIn('Secure',self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba'},origin='https://example.invalid')['cookie'])

    def test_injection_not_authenticated(self):
        result=self.request('/api/login',{'login':"' OR 1=1 --",'password':'incorrecta'})
        self.assertEqual(result['status'],401)


    def test_new_modules_require_authentication_and_admin_writes(self):
        paths=('/api/orders','/api/clients','/api/devices','/api/reports','/api/settings')
        for path in paths:
            self.assertEqual(self.request(path)['status'],401)
        cookie,csrf=self.login()
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        for path in paths[:-1]:
            self.assertEqual(self.request(path,cookie=cookie)['status'],200)
        self.assertEqual(self.request('/api/settings',cookie=cookie)['status'],403)
        for path in ('/api/clients','/api/devices','/api/order-status','/api/settings'):
            self.assertEqual(self.request(path,{},cookie=cookie,csrf=csrf)['status'],403)

    def test_client_device_edit_preserves_order_relationships(self):
        cookie,csrf=self.login()
        self.request('/api/orders',self.order_data({'client':'Original','problem':'Prueba'}),cookie=cookie,csrf=csrf)
        clients=self.request('/api/clients',cookie=cookie)['body']['rows']
        cid=str(clients[0]['id'])
        self.assertEqual(self.request('/api/clients',{'id':cid,'name':'Actualizado','phone':'0991234567','email':'test@example.invalid'},cookie=cookie,csrf=csrf)['status'],200)
        devices=self.request('/api/devices',cookie=cookie)['body']['rows']
        self.assertEqual(self.request('/api/devices',{'id':str(devices[0]['id']),'client_id':cid,'type':'escritorio','brand':'Prueba'},cookie=cookie,csrf=csrf)['status'],200)
        order=self.request('/api/orders',cookie=cookie)['body']['rows'][0]
        self.assertEqual(order['client'],'Actualizado')
        self.assertEqual(order['type'],'escritorio')
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_new_writes_require_csrf_and_validate_references(self):
        cookie,csrf=self.login()
        for path in ('/api/clients','/api/devices','/api/order-status','/api/settings'):
            self.assertEqual(self.request(path,{},cookie=cookie)['status'],403)
        self.assertEqual(self.request('/api/devices',{'client_id':'999','type':'portatil'},cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request('/api/clients',{'name':'','email':'mal'},cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request('/api/clients',{'id':'999','name':'Prueba'},cookie=cookie,csrf=csrf)['status'],404)

    def test_search_pagination_and_reports_are_complete(self):
        cookie,csrf=self.login()
        with app.connect() as c:
            c.executemany('INSERT INTO clients(name,phone) VALUES (?,?)',[(f'Cliente {i}','') for i in range(55)])
        first=self.request('/api/clients',cookie=cookie)['body']
        second=self.request('/api/clients?page=2',cookie=cookie)['body']
        self.assertEqual(first['total'],55)
        self.assertEqual(len(first['rows']),50)
        self.assertEqual(len(second['rows']),5)
        self.assertEqual(self.request('/api/clients?q=Cliente%2054',cookie=cookie)['body']['total'],1)
        self.assertEqual(self.request('/api/clients?q=%27%20OR%201%3D1',cookie=cookie)['body']['total'],0)
        self.assertEqual(self.request('/api/clients?page=bad',cookie=cookie)['status'],400)
        self.assertEqual(self.request('/api/reports',cookie=cookie)['body']['clients'],55)

    def test_order_history_records_real_transitions(self):
        cookie,csrf=self.login()
        order=self.request('/api/orders',self.order_data({'client':'Prueba','problem':'Prueba'}),cookie=cookie,csrf=csrf)['body']['id']
        post=lambda status,**extra:self.request('/api/order-status',dict({'id':str(order),'status':status},**extra),cookie=cookie,csrf=csrf)['status']
        self.assertEqual(post('reparacion'),200)
        self.assertEqual(post('reparacion'),200)
        self.assertEqual(post('reparacion',comment='Se limpió el ventilador.'),200)
        self.assertEqual(post('espera_entrega'),200)
        rows=self.request('/api/activity?order=%d'%order,cookie=cookie)['body']['rows']
        self.assertEqual([(r['event'],r['previous_label'],r['status_label']) for r in rows],[('status','Procesando','En espera de entrega'),('follow_up','Procesando','Procesando'),('status','En espera','Procesando'),('created',None,'En espera')])
        self.assertEqual(rows[0]['comment'],'Estado cambiado de «Procesando» a «En espera de entrega».')
        self.assertEqual(rows[1]['comment'],'Se limpió el ventilador.')
        detail=self.request('/api/orders/%d'%order,cookie=cookie)['body']['order']
        self.assertEqual([r['id'] for r in detail['history']],[r['id'] for r in rows])
        self.assertEqual(detail['history'][0]['previous_label'],'Procesando')
        self.assertEqual(self.request('/api/activity?recent=1',cookie=cookie)['body']['rows'][0]['previous_label'],'Procesando')
        self.assertEqual(self.request('/api/activity?order=x',cookie=cookie)['status'],400)
        self.assertEqual(self.request('/api/activity?order=%d'%order)['status'],401)

    def test_device_identified_by_serial_from_own_history(self):
        cookie,csrf=self.login()
        self.assertEqual(self.request('/api/devices/identify?serial=SN-ABC123')['status'],401)
        empty=self.request('/api/devices/identify?serial=SN-ABC123',cookie=cookie)
        self.assertEqual((empty['status'],empty['body']['matches'],empty['body']['manufacturer']),(200,[],{'available':False,'state':'unavailable','brand':'','message':'Identificación automática no disponible','result':None}))
        first=self.request('/api/orders',self.order_data({'client':'Prueba','problem':'Prueba','brand':'Lenovo','model':'ThinkPad T14','serial':'SN-ABC123'}),cookie=cookie,csrf=csrf)['body']['id']
        found=self.request('/api/devices/identify?serial=%20sn-abc123%20',cookie=cookie)['body']
        self.assertEqual(found['serial'],'SN-ABC123')
        self.assertEqual(len(found['matches']),1)
        match=found['matches'][0]
        self.assertEqual((match['brand'],match['model'],match['orders'],match['last_order']['id'],match['last_order']['status']),('Lenovo','ThinkPad T14',1,first,'En espera'))
        self.assertEqual(self.request('/api/devices/identify?serial=SN-ABC12',cookie=cookie)['body']['matches'],[])
        for bad in ('abc','%27%20OR%201%3D1','serie%25'):self.assertEqual(self.request('/api/devices/identify?serial='+bad,cookie=cookie)['status'],400)

    def test_manufacturer_lookup_only_with_official_credentials(self):
        import device_manufacturers as makers
        from unittest.mock import patch
        cookie,csrf=self.login();url='/api/devices/identify?serial=ABC1234&brand=Dell'
        catalog={m['slug']:m for m in self.request('/api/reception-options',cookie=cookie)['body']['manufacturers']}
        self.assertEqual(set(catalog),{'hp','dell','lenovo','acer','asus','apple','msi','samsung','huawei','dynabook','epson'})
        self.assertFalse(any(m['automatic'] for m in catalog.values()))
        # Sin credenciales no se hace ninguna consulta externa.
        with patch.object(makers,'_request',side_effect=AssertionError('no debe consultar')):
            self.assertEqual(self.request(url,cookie=cookie)['body']['manufacturer']['state'],'unavailable')
        calls=[]
        def fake(address,data=None,headers=None):
            calls.append(address)
            return {'access_token':'token-de-prueba','expires_in':3600} if address.endswith('/token') else [{'serviceTag':'ABC1234','productLineDescription':'LATITUDE 5420','shipDate':'2021-06-01T00:00:00Z','invalid':False}]
        with patch.dict(app.os.environ,{'DELL_API_CLIENT_ID':'id-de-prueba','DELL_API_CLIENT_SECRET':'secreto-de-prueba'}):
            makers._tokens.clear()
            with patch.object(makers,'_request',side_effect=fake):
                found=self.request(url,cookie=cookie)['body']['manufacturer']
                self.assertEqual((found['state'],found['result']),('found',{'brand':'Dell','model':'LATITUDE 5420','type':'','factory':{'Fecha de envío':'2021-06-01'},'source':'fabricante:dell'}))
                self.assertNotIn('secreto-de-prueba',json.dumps(found));self.assertTrue(all('dell.com' in c for c in calls))
                # Otra marca o una serie que no es Service Tag no se envían a Dell.
                before=len(calls)
                self.assertEqual(self.request('/api/devices/identify?serial=ABC1234&brand=Lenovo',cookie=cookie)['body']['manufacturer']['state'],'unavailable')
                self.assertEqual(self.request('/api/devices/identify?serial=SERIE-MUY-LARGA-123&brand=Dell',cookie=cookie)['body']['manufacturer']['state'],'not_found')
                self.assertEqual(len(calls),before)
            with patch.object(makers,'_request',side_effect=makers.ProviderError('conexion','x')):
                # Una serie ya verificada se sirve de la memoria aunque el fabricante falle; aquí se prueba el fallo sin resultado guardado.
                import device_lookup;device_lookup._verified.clear()
                makers._tokens.clear();failed=self.request(url,cookie=cookie)
                self.assertEqual((failed['status'],failed['body']['manufacturer']['state']),(200,'error'))
            # El historial propio tiene prioridad: una serie ya registrada no sale del sistema.
            self.request('/api/orders',self.order_data({'client':'Prueba','problem':'Prueba','brand':'Dell','model':'Latitude 5420','serial':'ABC1234','identity_source':'fabricante:dell'}),cookie=cookie,csrf=csrf)
            with patch.object(makers,'_request',side_effect=AssertionError('no debe consultar')):
                known=self.request(url,cookie=cookie)['body'];self.assertEqual((len(known['matches']),known['manufacturer']['state']),(1,'unavailable'))
        makers._tokens.clear()

    def test_device_source_is_saved_and_same_device_is_not_duplicated(self):
        cookie,csrf=self.login();base={'client':'Prueba','problem':'Prueba','brand':'HP','model':'ProBook 440','serial':'5CD-1234'}
        first=self.request('/api/orders',self.order_data(dict(base,identity_source='historial',request_key='device-source-request-0001')),cookie=cookie,csrf=csrf)['body']['id']
        second=self.request('/api/orders',self.order_data(dict(base,serial='5cd-1234',identity_source='<script>',request_key='device-source-request-0002')),cookie=cookie,csrf=csrf)['body']['id']
        third=self.request('/api/orders',self.order_data(dict(base,model='ProBook 450',identity_source='otra cosa',request_key='device-source-request-0003')),cookie=cookie,csrf=csrf)['body']['id']
        self.assertEqual(len({first,second,third}),3)
        with app.connect() as c:
            rows=c.execute('SELECT d.id,d.model,d.identity_source,(SELECT COUNT(*) FROM orders o WHERE o.device_id=d.id) n FROM devices d ORDER BY d.id').fetchall()
            self.assertEqual([(r['model'],r['identity_source'],r['n']) for r in rows],[('ProBook 440','historial',2),('ProBook 450','manual',1)])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],3)

    def test_confirmed_identity_is_reused_and_brand_conflicts_are_flagged(self):
        cookie,csrf=self.login();base={'client':'Prueba','problem':'Prueba','serial':'SN-CONF-1'}
        self.request('/api/orders',self.order_data(dict(base,brand='HP',model='ProBook 440 G8',identity_source='manual',request_key='identity-confirm-request-01')),cookie=cookie,csrf=csrf)
        known=self.request('/api/devices/identify?serial=sn-conf-1',cookie=cookie)['body']
        match=known['matches'][0]
        self.assertEqual((known['conflict'],match['brand'],match['model'],match['identity_source'],bool(match['confirmed_by']),bool(match['confirmed_at'])),(False,'HP','ProBook 440 G8','manual',True,True))
        self.request('/api/orders',self.order_data(dict(base,brand='Dell',model='Latitude 5420',request_key='identity-confirm-request-02')),cookie=cookie,csrf=csrf)
        clash=self.request('/api/devices/identify?serial=SN-CONF-1',cookie=cookie)['body']
        self.assertEqual((clash['conflict'],sorted(m['brand'] for m in clash['matches'])),(True,['Dell','HP']))
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM devices WHERE identity_confirmed_by IS NOT NULL AND identity_confirmed_at!=''").fetchone()[0],2)

    def test_header_search_returns_total_exact_code_first_and_all_fields(self):
        cookie,csrf=self.login();codes=[]
        for n in range(10):
            oid=self.request('/api/orders',self.order_data({'client':'Prueba','problem':'Prueba','brand':'Lenovo','model':'ThinkPad T%d'%n,'serial':'SRCH-%04d'%n,'request_key':'header-search-request-%04d'%n}),cookie=cookie,csrf=csrf)['body']['id']
            codes.append(self.request('/api/orders/%d'%oid,cookie=cookie)['body']['order']['code'])
        many=self.request('/api/search?q=lenovo',cookie=cookie)['body']
        self.assertEqual((len(many['rows']),many['total']),(8,10));self.assertEqual(len({r['id'] for r in many['rows']}),8)
        exact=self.request('/api/search?q='+codes[0].lower(),cookie=cookie)['body']
        self.assertEqual((exact['rows'][0]['code'],exact['total']),(codes[0],1))
        partial=self.request('/api/search?q='+codes[0][:5],cookie=cookie)['body'];self.assertEqual((codes[0],partial['total']),('OP-0001',10))
        for term,expected in (('SRCH-0007',1),('thinkpad t3',1),('srch-',10),('no-existe-xyz',0),("' OR 1=1",0)):
            found=self.request('/api/search?q='+quote(term),cookie=cookie)['body'];self.assertEqual((found['total'],len(found['rows'])),(expected,min(expected,8)),term)
        # Tolerancia a errores de escritura, tildes y varias palabras en cualquier orden; los números no se aproximan.
        typo=self.request('/api/search?q=lenvo',cookie=cookie)['body']
        self.assertEqual((typo['total'],typo['fuzzy'],typo['suggestion'],typo['rows'][0]['hits']),(10,True,'Lenovo',['Lenovo']))
        self.assertEqual(self.request('/api/search?q='+quote('thinkpd t3'),cookie=cookie)['body']['suggestion'],'ThinkPad t3')
        self.assertEqual(self.request('/api/search?q='+quote('T4 prueba lenovo'),cookie=cookie)['body']['total'],1)
        self.assertEqual(self.request('/api/search?q='+quote('prúeba LENOVÓ'),cookie=cookie)['body']['total'],10)
        self.assertEqual(self.request('/api/search?q=SRCH-0017',cookie=cookie)['body']['total'],0)
        self.assertEqual(self.request('/api/search?q=099123456X',cookie=cookie)['body']['total'],0)
        self.assertNotIn('identification',typo['rows'][0]);self.assertNotIn('phone',typo['rows'][0])
        self.assertEqual(self.request('/api/search?q=a',cookie=cookie)['body']['rows'],[])
        self.assertEqual(self.request('/api/search?q=lenovo')['status'],401)

    def test_tablet_phone_router_and_server_types(self):
        cookie,csrf=self.login()
        types=self.request('/api/reception-options',cookie=cookie)['body']['device_types']
        self.assertEqual((types['tablet'],types['celular'],types['router'],types['servidor']),('Tablet','Celular','Router / equipo de red','Servidor'))
        for n,kind in enumerate(('tablet','celular','router','servidor')):
            made=self.request('/api/orders',self.order_data({'type':kind,'brand':'Marca','model':'Modelo %d'%n,'serial':'NEWTYPE-%d'%n,'request_key':'new-device-type-%06d'%n}),cookie=cookie,csrf=csrf)
            self.assertEqual(made['status'],201,made);self.assertEqual(self.request('/api/orders/%d'%made['body']['id'],cookie=cookie)['body']['order']['type'],kind)
            for suffix in ('/receipt.pdf','/thermal.pdf'):self.assertEqual(self.request('/api/orders/%d%s'%(made['body']['id'],suffix),cookie=cookie)['status'],200)

    def test_new_device_types_are_saved_listed_and_printed(self):
        cookie,csrf=self.login()
        types=self.request('/api/reception-options',cookie=cookie)['body']['device_types']
        self.assertEqual((types['portatil'],types['notebook'],types['consola']),('Portátil (Laptop)','Notebook','Consolas'))
        self.assertEqual(list(types)[:2],['portatil','notebook'])
        ids={}
        for n,kind in enumerate(('notebook','consola','portatil')):
            ids[kind]=self.request('/api/orders',self.order_data({'client':'Prueba','problem':'Prueba','type':kind,'brand':'Sony' if kind=='consola' else 'HP','model':'Modelo %d'%n,'serial':'KIND-%d'%n,'request_key':'device-kind-request-%04d'%n}),cookie=cookie,csrf=csrf)
            self.assertEqual(ids[kind]['status'],201,ids[kind])
        with app.connect() as c:
            self.assertEqual([(r['category'],r['kind'],r['type']) for r in c.execute('SELECT category,kind,type FROM devices ORDER BY id')],[('portatil','notebook','portatil'),('otro','consola','escritorio'),('portatil','portatil','portatil')])
        listed={r['id']:r['type'] for r in self.request('/api/orders',cookie=cookie)['body']['rows']}
        self.assertEqual([listed[ids[k]['body']['id']] for k in ('notebook','consola','portatil')],['notebook','consola','portatil'])
        for kind in ('notebook','consola'):
            oid=ids[kind]['body']['id']
            self.assertEqual(self.request('/api/orders/%d'%oid,cookie=cookie)['body']['order']['type'],kind)
            for doc in ('receipt.pdf','thermal.pdf','label.pdf','service.pdf'):self.assertEqual(self.request('/api/orders/%d/%s'%(oid,doc),cookie=cookie)['status'],200,doc)
        self.assertEqual(self.request('/api/devices/identify?serial=KIND-1',cookie=cookie)['body']['matches'][0]['type'],'consola')
        self.assertEqual({r['type'] for r in self.request('/api/devices',cookie=cookie)['body']['rows']},{'notebook','consola','portatil'})
        self.assertEqual(self.request('/api/orders',self.order_data({'client':'Prueba','problem':'Prueba','type':'televisor','request_key':'device-kind-request-9999'}),cookie=cookie,csrf=csrf)['status'],400)

    def test_brand_logo_files_are_listed_and_served(self):
        cookie,csrf=self.login()
        folder=app.ROOT/'static'/'brands';svg=folder/'zz-prueba.svg';png=folder/'zz-prueba.png'
        try:
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>');png.write_bytes(b'\x89PNG prueba')
            self.assertEqual(self.request('/api/reception-options',cookie=cookie)['body']['brand_logos']['zz-prueba'],'zz-prueba.svg')
            self.assertEqual(self.request('/static/brands/zz-prueba.svg')['status'],200)
            self.assertEqual(self.request('/static/brands/zz-prueba.png')['status'],200)
        finally:
            svg.unlink(missing_ok=True);png.unlink(missing_ok=True)
        self.assertNotIn('zz-prueba',self.request('/api/reception-options',cookie=cookie)['body']['brand_logos'])
        for missing in ('/static/brands/zz-prueba.svg','/static/brands/..%2Fapp.svg','/static/brands/README.md','/static/brands/Dell.svg'):self.assertIn(self.request(missing)['status'],(401,404))

    def test_order_status_updates_active_filter_and_report(self):
        cookie,csrf=self.login()
        order=self.request('/api/orders',self.order_data({'client':'Prueba','problem':'Prueba'}),cookie=cookie,csrf=csrf)['body']['id']
        self.assertEqual(self.request('/api/order-status',{'id':str(order),'status':'entregado'},cookie=cookie,csrf=csrf)['status'],200)
        self.assertEqual(self.request('/api/orders?active=1',cookie=cookie)['body']['total'],0)
        self.assertEqual(self.request('/api/orders',cookie=cookie)['body']['total'],1)
        report=self.request('/api/reports',cookie=cookie)['body']
        self.assertEqual(next(s['total'] for s in report['statuses'] if s['code']=='entregado'),1)
        self.assertEqual(self.request('/api/order-status',{'id':str(order),'status':'inválido'},cookie=cookie,csrf=csrf)['status'],400)

    def test_settings_never_expose_secrets(self):
        cookie,csrf=self.login()
        settings=self.request('/api/settings',cookie=cookie)['body']
        encoded=json.dumps(settings)
        for forbidden in ('password_hash','csrf','token_hash','SMTP_PASSWORD'):
            self.assertNotIn(forbidden,encoded)
        self.assertEqual(self.request('/api/settings',{'name':'Nuevo nombre','email':'new@example.invalid'},cookie=cookie,csrf=csrf)['status'],200)
        me=self.request('/api/me',cookie=cookie)['body']['user']
        self.assertEqual(me['name'],'Nuevo nombre')
        self.assertEqual(me['email'],'new@example.invalid')


if __name__=='__main__':
    unittest.main()
