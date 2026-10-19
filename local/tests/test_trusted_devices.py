"""Recordar mi sesión, confiar en este equipo (segundo paso), dispositivos de confianza y cierre de sesión en todos los dispositivos.
Un «navegador» de prueba guarda sus cookies como lo haría uno real: al cerrarlo se pierden las que no tienen Max-Age."""
import io,json,sys,time,unittest
from email.message import Message
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,test_app,two_factor,trusted_devices
PASSWORD='contraseña-segura-de-prueba'
CHROME='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36'
FIREFOX='Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0'


class Browser:
    """Tarro de cookies mínimo: guarda nombre, valor, ruta y si es persistente (Max-Age); respeta Max-Age=0 y la ruta."""
    def __init__(self,test,agent):self.test,self.agent,self.jar=test,agent,{}

    def store(self,raw):
        for line in ([raw] if isinstance(raw,str) else raw or []):
            parts=[part.strip() for part in line.split(';')];name,value=parts[0].split('=',1)
            attrs={k.lower():(v if v else True) for k,_,v in (p.partition('=') for p in parts[1:])}
            if attrs.get('max-age')=='0' or value=='':self.jar.pop(name,None);continue
            self.jar[name]={'value':value,'path':attrs.get('path','/'),'persistent':'max-age' in attrs,'attrs':attrs}

    def restart(self):
        """Cerrar y abrir el navegador: sobreviven solo las cookies persistentes."""
        self.jar={k:v for k,v in self.jar.items() if v['persistent']}

    def call(self,path,body=None,csrf=''):
        handler=object.__new__(app.Handler);handler.path=path;handler.client_address=('127.0.0.1',23456);handler.headers=Message()
        handler.headers['Cookie']='; '.join(k+'='+v['value'] for k,v in self.jar.items() if path.startswith(v['path']))
        handler.headers['Origin']='http://127.0.0.1:8010';handler.headers['Content-Type']='application/json';handler.headers['X-CSRF-Token']=csrf;handler.headers['User-Agent']=self.agent
        raw=json.dumps(body or {}).encode();handler.headers['Content-Length']=str(len(raw));handler.rfile=io.BytesIO(raw);result={}
        handler.reply=lambda status,content,content_type=None,cookie=None,filename=None:result.update(status=status,body=content,cookie=cookie)
        handler.do_GET() if body is None else handler.do_POST()
        self.store(result.get('cookie'));return result

    def me(self):return self.call('/api/me')


class TrustedDeviceTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        from unittest.mock import patch
        # Reloj controlado (a mitad de un intervalo de 30 s) para simular el paso de minutos y días.
        self.now=int(time.time())//30*30+10;clock=patch.object(two_factor.time,'time',lambda:self.now);clock.start();self.addCleanup(clock.stop)

    def code(self,offset=0):
        with app.connect() as c:secret=two_factor.unseal(c.execute('SELECT secret FROM user_mfa WHERE user_id=?',(self.uid,)).fetchone()[0])
        return two_factor.code_at(secret,self.now//30+offset)

    def enable(self):
        cookie,csrf=self.login();setup=lambda **body:self.request('/api/account/second-step',body,cookie=cookie,csrf=csrf)
        started=setup(action='start',password=PASSWORD);done=setup(action='confirm',code=self.code(),setup=started['body']['setup'])
        self.assertEqual(done['status'],200,done['body']);return done['body']

    def advance(self,seconds):self.now+=seconds

    def full_login(self,browser,remember=False,trust=False):
        """Usuario y contraseña y, si se pide, el código. Devuelve la respuesta del paso que abrió la sesión."""
        first=browser.call('/api/login',{'login':'demo','password':PASSWORD,'remember':remember})
        self.assertEqual(first['status'],200,first['body'])
        if not first['body'].get('second_step'):return first
        self.advance(30)
        return browser.call('/api/login/second-step',{'challenge':first['body']['challenge'],'code':self.code(),'trust_device':trust})

    def test_remember_session_survives_idle_time_and_browser_restart(self):
        normal=Browser(self,CHROME);self.full_login(normal,remember=False)
        self.assertFalse(normal.jar['pcdoctor_session']['persistent']);self.assertEqual(normal.me()['status'],200)
        self.assertIsNotNone(normal.me()['body']['idle'])
        normal.restart();self.assertEqual(normal.me()['status'],401)                       # sin recordar: se pierde al cerrar el navegador
        again=Browser(self,CHROME);self.full_login(again);self.advance(20*60);self.assertEqual(again.me()['status'],401)   # y caduca por inactividad
        kept=Browser(self,CHROME);self.full_login(kept,remember=True)
        cookie=kept.jar['pcdoctor_session'];self.assertTrue(cookie['persistent']);self.assertEqual(cookie['attrs']['max-age'],str(30*86400))
        self.assertIn('httponly',cookie['attrs']);self.assertEqual(cookie['attrs']['samesite'],'Strict')
        me=kept.me();self.assertEqual(me['status'],200);self.assertIsNone(me['body']['idle'])
        self.assertNotIn(PASSWORD,json.dumps(me['body'],ensure_ascii=False))
        self.advance(3*3600);kept.restart();self.assertEqual(kept.me()['status'],200)         # cerrar y abrir el navegador tras horas sin uso
        self.advance(26*86400);self.assertEqual(kept.me()['status'],200)
        self.advance(4*86400);self.assertEqual(kept.me()['status'],401)                       # nunca más de 30 días
        # Cerrar sesión manualmente siempre funciona.
        manual=Browser(self,CHROME);self.full_login(manual,remember=True);csrf=manual.me()['body']['user']['csrf']
        self.assertEqual(manual.call('/api/logout',{},csrf=csrf)['status'],200);manual.restart();self.assertEqual(manual.me()['status'],401)

    def test_remember_never_skips_the_second_step(self):
        self.enable();browser=Browser(self,CHROME)
        first=browser.call('/api/login',{'login':'demo','password':PASSWORD,'remember':True})
        self.assertTrue(first['body'].get('second_step'));self.assertNotIn('pcdoctor_session',browser.jar)
        self.advance(30);ok=browser.call('/api/login/second-step',{'challenge':first['body']['challenge'],'code':self.code()})
        self.assertEqual(ok['status'],200);self.assertTrue(browser.jar['pcdoctor_session']['persistent']);self.assertNotIn(trusted_devices.COOKIE,browser.jar)
        browser.restart();self.assertEqual(browser.me()['status'],200)
        # Sesión recordada pero sin equipo de confianza: un nuevo inicio de sesión vuelve a pedir el código.
        self.assertTrue(browser.call('/api/login',{'login':'demo','password':PASSWORD,'remember':True})['body'].get('second_step'))

    def test_trusted_device_skips_the_code_only_in_the_same_browser(self):
        self.enable();laptop=Browser(self,CHROME)
        done=self.full_login(laptop,remember=True,trust=True);self.assertTrue(done['body']['trusted'])
        trust=laptop.jar[trusted_devices.COOKIE];self.assertTrue(trust['persistent']);self.assertEqual(trust['path'],'/api/login')
        self.assertEqual((trust['attrs']['max-age'],trust['attrs']['samesite']),(str(30*86400),'Strict'));self.assertIn('httponly',trust['attrs'])
        with app.connect() as c:self.assertNotIn(trust['value'],json.dumps([list(r) for r in c.execute('SELECT * FROM trusted_devices')]))
        # Se cierra el navegador, se cierra la sesión y se vuelve a entrar: solo la contraseña.
        csrf=laptop.me()['body']['user']['csrf'];laptop.call('/api/logout',{},csrf=csrf);laptop.restart()
        self.advance(3600);again=laptop.call('/api/login',{'login':'demo','password':PASSWORD,'remember':False})
        self.assertEqual((again['status'],again['body'].get('trusted_device'),again['body'].get('second_step')),(200,True,None));self.assertEqual(laptop.me()['status'],200)
        # La contraseña sigue siendo obligatoria.
        self.assertEqual(laptop.call('/api/login',{'login':'demo','password':'incorrecta-123456'})['status'],401)
        # Un equipo nuevo, sin el token, sigue pidiendo el código.
        other=Browser(self,CHROME);self.assertTrue(other.call('/api/login',{'login':'demo','password':PASSWORD})['body'].get('second_step'))
        # El token copiado a otro navegador o sistema no sirve y se revoca (actividad sospechosa).
        thief=Browser(self,FIREFOX);thief.jar[trusted_devices.COOKIE]=dict(trust)
        self.assertTrue(thief.call('/api/login',{'login':'demo','password':PASSWORD})['body'].get('second_step'))
        self.assertTrue(laptop.call('/api/login',{'login':'demo','password':PASSWORD})['body'].get('second_step'))
        with app.connect() as c:self.assertIn('sospechosa',c.execute('SELECT revoked_reason FROM trusted_devices').fetchone()[0])

    def test_trust_expires_after_thirty_days_and_recovery_codes_do_not_create_it(self):
        recovery=self.enable()['recovery'];laptop=Browser(self,CHROME);self.full_login(laptop,trust=True)
        self.advance(29*86400);self.assertTrue(laptop.call('/api/login',{'login':'demo','password':PASSWORD})['body'].get('trusted_device'))
        self.advance(2*86400);self.assertTrue(laptop.call('/api/login',{'login':'demo','password':PASSWORD})['body'].get('second_step'))
        fresh=Browser(self,CHROME);first=fresh.call('/api/login',{'login':'demo','password':PASSWORD})
        used=fresh.call('/api/login/second-step',{'challenge':first['body']['challenge'],'code':recovery[0],'trust_device':True})
        self.assertEqual((used['status'],used['body']['trusted']),(200,False));self.assertNotIn(trusted_devices.COOKIE,fresh.jar)

    def test_logout_everywhere_closes_all_sessions_and_revokes_trust(self):
        self.enable();laptop,phone=Browser(self,CHROME),Browser(self,CHROME)
        self.full_login(laptop,remember=True,trust=True);self.advance(30);self.full_login(phone,remember=True,trust=True)
        csrf=phone.me()['body']['user']['csrf']
        done=phone.call('/api/sessions/revoke',{},csrf=csrf);self.assertEqual(done['status'],200)
        self.assertEqual(laptop.me()['status'],401);self.assertEqual(phone.me()['status'],401);self.assertNotIn(trusted_devices.COOKIE,phone.jar)
        # El equipo que conserva su token ya no es de confianza: pide usuario, contraseña y código.
        laptop.restart();self.assertTrue(laptop.call('/api/login',{'login':'demo','password':PASSWORD})['body'].get('second_step'))
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM trusted_devices WHERE revoked_at IS NULL').fetchone()[0],0)

    def test_devices_are_listed_and_revoked_tokens_cannot_be_reused(self):
        self.enable();laptop=Browser(self,CHROME);self.full_login(laptop,remember=True,trust=True)
        settings=laptop.call('/api/settings');devices=settings['body']['trusted_devices']
        self.assertEqual(len(devices),1);device=devices[0]
        self.assertEqual((device['name'],device['browser']),('Chrome en Windows','Chrome'));self.assertEqual(device['expires_at']-device['created_at'],30*86400)
        for key in ('created_at','last_used_at'):self.assertIn(key,device)
        self.assertNotIn('token_hash',device)
        csrf=laptop.me()['body']['user']['csrf']
        self.assertEqual(laptop.call('/api/trusted-devices/revoke',{'id':str(device['id'])},csrf=csrf)['status'],200)
        self.assertEqual(laptop.call('/api/trusted-devices/revoke',{'id':str(device['id'])},csrf=csrf)['status'],404)
        self.assertTrue(laptop.call('/api/login',{'login':'demo','password':PASSWORD})['body'].get('second_step'))
        self.assertEqual(laptop.me()['status'],200)    # revocar la confianza no cierra la sesión abierta

    def test_password_change_and_administration_revoke_trust(self):
        self.enable();laptop=Browser(self,CHROME);self.full_login(laptop,trust=True)
        csrf=laptop.me()['body']['user']['csrf']
        changed=laptop.call('/api/account/password',{'current':PASSWORD,'password':'otra-contraseña-segura-2026','repeat':'otra-contraseña-segura-2026'},csrf=csrf)
        self.assertEqual(changed['status'],200,changed['body'])
        first=laptop.call('/api/login',{'login':'demo','password':'otra-contraseña-segura-2026'});self.assertTrue(first['body'].get('second_step'))
        self.advance(30);laptop.call('/api/login/second-step',{'challenge':first['body']['challenge'],'code':self.code(),'trust_device':True})
        with app.connect() as c:
            other=c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at,approval) VALUES ('jefa','jefa@example.invalid','Administración 2',?,'administrador',0,'approved')",(self.hash,)).lastrowid
            token,admin_csrf,_=app.make_session(c,other)
        result=self.request('/api/users/manage',{'id':str(self.uid),'action':'revoke_devices'},cookie='pcdoctor_session='+token,csrf=admin_csrf)
        self.assertEqual((result['status'],result['body'].get('revoked')),(200,1),result)
        self.assertTrue(laptop.call('/api/login',{'login':'demo','password':'otra-contraseña-segura-2026'})['body'].get('second_step'))


if __name__=='__main__':unittest.main()
