import io
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
app.os.environ.setdefault('LOGIN_CAPTCHA','off')  # Las pruebas inician sesión sin verificación salvo que la activen.


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hash = app.password_hash('contraseña-segura-de-prueba')

    def setUp(self):
        self.jobs=patch.object(app,'dispatch_security_job',side_effect=lambda job:job())
        self.jobs.start()
        self.temp = tempfile.TemporaryDirectory()
        self.paths = patch.multiple(app, DATA=Path(self.temp.name), DB=Path(self.temp.name)/'test.sqlite3')
        self.paths.start()
        self.env = patch.dict(app.os.environ, {'APP_URL':'http://127.0.0.1:8010','SESSION_SECURE':'false'})
        self.env.start()
        app.migrate()
        with app.connect() as c:
            self.uid = c.execute('INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES (?,?,?,?,?,?)',('demo','demo@example.invalid','Persona de prueba',self.hash,'administrador',int(time.time()))).lastrowid
            if self.__class__.__name__!='ServiceTermsTests':
                app.service_terms.publish(c,{'version':'FIXTURE-ONLY','effective_date':'2020-01-01','full_text':'Condiciones ficticias de prueba, sin efectos reales.','compact_text':'Resumen ficticio de prueba.','approved':True},{'id':self.uid},app.reception_now())

    def tearDown(self):
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
        def reply(status,body,content_type=None,cookie=None):
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
        with patch.object(app.time,'time',return_value=2000000000):
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
        with patch.dict(app.os.environ,{'TURNSTILE_SITE_KEY':'public-key','TURNSTILE_SECRET_KEY':'private-key','TURNSTILE_LOGIN_MODE':'adaptive'}):
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
        with patch.dict(app.os.environ,{'LOGIN_CAPTCHA':'on'}),patch.object(app,'CAPTCHA_BITS',8):
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
        self.assertIn('Órdenes Pro · v'+current,self.request('/login')['body'])
        news=self.request('/novedades')
        self.assertEqual(news['status'],200)
        self.assertIn('<span>v'+current+'</span><em>Última versión</em>',news['body'])
        for page in ('/login','/forgot','/citas'):
            body=self.request(page)['body']
            self.assertIn('href="/favicon.ico?v=2"',body)
            self.assertIn('rel="apple-touch-icon"',body)
        self.assertIn('<title>Órdenes Pro | PC-DOCTOR S.A.</title>',self.request('/login')['body'])

    def test_registration_creates_pending_account_that_admin_must_approve(self):
        data={'name':'Persona Solicitante','username':'nueva.persona','email':'nueva@example.invalid','phone':'0991234567','identification':'','job_title':'Técnico de prueba','password':'clave-de-prueba','repeat':'clave-de-prueba'}
        self.assertIn('href="/registro"',self.request('/login')['body'])
        self.assertIn('id="register-form"',self.request('/registro')['body'])
        bad=self.request('/api/register',dict(data,username='a b',phone='123',repeat='otra'))
        self.assertEqual(bad['status'],400)
        self.assertEqual(set(bad['body']['fields']),{'username','phone','repeat'})
        first=self.request('/api/register',data)
        self.assertEqual(first['status'],201)
        # Mismo mensaje para un usuario o correo ya registrado: no se revela su existencia ni se duplica.
        again=self.request('/api/register',dict(data,email='demo@example.invalid',username='otra.persona'))
        self.assertEqual((again['status'],again['body']),(201,first['body']))
        with app.connect() as c:
            row=c.execute("SELECT * FROM users WHERE username='nueva.persona'").fetchone()
            self.assertEqual((row['active'],row['approval'],row['role'],row['phone']),(0,'pending','tecnico','0991234567'))
            self.assertNotIn('clave-de-prueba',row['password_hash'])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM users WHERE username='otra.persona'").fetchone()[0],0)
        login={'login':'nueva.persona','password':'clave-de-prueba'}
        self.assertEqual(self.request('/api/login',login)['status'],401)
        cookie,csrf=self.login()
        settings=self.request('/api/settings',cookie=cookie)['body']
        self.assertEqual([r['username'] for r in settings['requests']],['nueva.persona'])
        self.assertNotIn('nueva.persona',[a['username'] for a in settings['accounts']])
        self.assertNotIn('password_hash',settings['requests'][0])
        self.assertEqual(self.request('/api/users/approval',{'id':str(row['id']),'action':'approve','role':'tecnico'},cookie=cookie)['status'],403)
        self.assertEqual(self.request('/api/users/approval',{'id':str(row['id']),'action':'approve','role':'tecnico'},cookie=cookie,csrf=csrf)['status'],200)
        self.assertEqual(self.request('/api/users/approval',{'id':str(row['id']),'action':'approve','role':'tecnico'},cookie=cookie,csrf=csrf)['status'],400)
        granted=self.request('/api/login',login)
        self.assertEqual(granted['status'],200)
        tech=granted['cookie'].split(';')[0];tech_csrf=self.request('/api/me',cookie=tech)['body']['user']['csrf']
        self.assertEqual(self.request('/api/users/approval',{'id':'1','action':'approve','role':'administrador'},cookie=tech,csrf=tech_csrf)['status'],403)
        # Una solicitud rechazada sigue visible, puede aprobarse y puede volver a enviarse.
        other=dict(data,username='otra.solicitud',email='otra@example.invalid')
        self.request('/api/register',other)
        with app.connect() as c:oid=c.execute("SELECT id FROM users WHERE username='otra.solicitud'").fetchone()[0]
        self.assertEqual(self.request('/api/users/approval',{'id':str(oid),'action':'reject','role':'tecnico'},cookie=cookie,csrf=csrf)['status'],200)
        listed=self.request('/api/settings',cookie=cookie)['body']['requests']
        self.assertEqual([(r['username'],r['approval']) for r in listed],[('otra.solicitud','rejected')])
        self.assertEqual(self.request('/api/users/approval',{'id':str(oid),'action':'reject','role':'tecnico'},cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request('/api/register',dict(other,phone='0987654321',password='otra-clave-nueva',repeat='otra-clave-nueva'))['status'],201)
        with app.connect() as c:
            again=c.execute('SELECT approval,active,phone FROM users WHERE id=?',(oid,)).fetchone()
            self.assertEqual(tuple(again),('pending',0,'0987654321'))
            c.execute("UPDATE users SET approval='rejected' WHERE id=?",(oid,))
        self.assertEqual(self.request('/api/users/approval',{'id':str(oid),'action':'approve','role':'tecnico'},cookie=cookie,csrf=csrf)['status'],200)
        self.assertEqual(self.request('/api/login',{'login':'otra.solicitud','password':'otra-clave-nueva'})['status'],200)
        with app.connect() as c:c.execute("DELETE FROM attempts WHERE bucket LIKE 'register-ip:%'")
        with patch.dict(app.os.environ,{'LOGIN_CAPTCHA':'on'}):
            self.assertEqual(self.request('/api/register',dict(data,username='sin.captcha',email='sc@example.invalid'))['status'],403)
        with patch.dict(app.os.environ,{'REGISTRATION':'off'}):
            self.assertEqual(self.request('/registro')['status'],404)
            self.assertEqual(self.request('/api/register',data)['status'],404)
            self.assertIn('class="register-link" hidden',self.request('/login')['body'])

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
