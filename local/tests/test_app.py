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
        self.assertEqual(self.request('/api/auth/policy',dict(policy,password_min='8'),cookie=cookie,csrf=csrf)['status'],400)
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
        with patch.dict(app.os.environ,{'TURNSTILE_SITE_KEY':'public-key','TURNSTILE_SECRET_KEY':'private-key'}):
            for _ in range(2):self.assertEqual(self.request('/api/login',{'login':'demo','password':'wrong'})['status'],401)
            with patch.object(app,'verify_bot',return_value=False) as verify:
                result=self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba','bot_token':'forged'})
                self.assertEqual(result['status'],403)
                self.assertTrue(result['body']['challenge'])
                verify.assert_called_once_with('forged','login')
            with patch.object(app,'verify_bot',return_value=True):
                self.assertEqual(self.request('/api/login',{'login':'demo','password':'contraseña-segura-de-prueba','bot_token':'valid'})['status'],200)

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
