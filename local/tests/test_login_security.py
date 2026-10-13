"""Acceso: límites de longitud, campo trampa, esperas progresivas, verificación silenciosa solo con riesgo y cierre por inactividad."""
import hashlib,unittest
from unittest.mock import patch
import test_app
import app
GOOD={'login':'demo','password':'contraseña-segura-de-prueba'}


class LoginSecurityTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def test_length_limits_keep_existing_credentials_working(self):
        with patch.dict(app.os.environ,{'LOGIN_CAPTCHA':'off'}):
            self.assertEqual(self.request('/api/login',{'login':'u'*51,'password':'x'})['status'],400)
            self.assertEqual(self.request('/api/login',{'login':'a'*60+'@example.invalid','password':'x'})['status'],401)  # un correo puede superar los 50
            self.assertEqual(self.request('/api/login',{'login':'demo','password':'x'*257})['status'],400)
            # Una contraseña larga ya existente (hasta 256) sigue entrando: no se trunca ni se rechaza.
            with app.connect() as c:c.execute('UPDATE users SET password_hash=? WHERE username=?',(app.password_hash('p'*200),'demo'))
            with patch.object(app,'LOGIN_WAITS',{}):
                self.assertEqual(self.request('/api/login',{'login':'demo','password':'p'*199})['status'],401)
                self.assertEqual(self.request('/api/login',{'login':'demo','password':'p'*200})['status'],200)
            page=self.request('/login')['body'];self.assertIn('data-masked="true"',page);self.assertIn('name="website"',page);self.assertNotIn('No soy un robot',page)

    def test_honeypot_is_rejected_generically_and_recorded(self):
        with patch.dict(app.os.environ,{'LOGIN_CAPTCHA':'off'}):
            trapped=self.request('/api/login',dict(GOOD,website='http://example.invalid'))
            wrong=self.request('/api/login',{'login':'demo','password':'incorrecta'})
            self.assertEqual((trapped['status'],trapped['body']),(401,wrong['body']));self.assertIsNone(trapped['cookie'])
            with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='login_bot_suspected'").fetchone()[0],1)

    def test_progressive_waits_then_lock(self):
        clock=[2000000000]
        with patch.dict(app.os.environ,{'LOGIN_CAPTCHA':'off'}),patch.object(app.time,'time',side_effect=lambda:clock[0]):
            bad=lambda:self.request('/api/login',{'login':'demo','password':'incorrecta'})
            self.assertEqual(bad()['status'],401)                       # 1.er fallo: sin espera
            self.assertEqual(bad()['status'],401)                       # 2.º fallo: activa 3 s
            held=bad();self.assertEqual((held['status'],held['body']['retry_after']),(429,3))
            # Durante la espera ni siquiera las credenciales correctas se evalúan, y el intento no cuenta como fallo.
            self.assertEqual(self.request('/api/login',GOOD)['status'],429)
            clock[0]+=3;self.assertEqual(bad()['status'],401)           # 3.er fallo: 8 s
            clock[0]+=7;self.assertEqual(bad()['body']['retry_after'],1)
            clock[0]+=1;self.assertEqual(bad()['status'],401)           # 4.º fallo: 20 s
            clock[0]+=20;locked=bad();self.assertEqual(locked['status'],429);self.assertNotIn('retry_after',locked['body'])  # 5.º: bloqueo temporal
            # El bloqueo no es permanente: vence solo.
            clock[0]+=app.auth_policy(app.connect())['lockout_seconds']+1
            self.assertEqual(self.request('/api/login',GOOD)['status'],200)

    def test_silent_challenge_only_after_failures_and_single_use(self):
        with patch.dict(app.os.environ,{'LOGIN_CAPTCHA':'on'}),patch.object(app,'CAPTCHA_BITS',8),patch.object(app,'LOGIN_WAITS',{}):
            # Uso habitual: sin desafío.
            self.assertEqual(self.request('/api/login',GOOD)['status'],200)
            for _ in range(2):self.assertEqual(self.request('/api/login',{'login':'demo','password':'incorrecta'})['status'],401)
            asked=self.request('/api/login',GOOD);self.assertEqual((asked['status'],asked['body']['challenge'],asked['body']['silent']),(403,True,True))
            challenge=self.request('/api/captcha',{})['body']
            solved=next(n for n in range(100000) if hashlib.sha256((challenge['nonce']+':'+str(n)).encode()).digest()[0]==0)
            token='local:'+challenge['nonce']+':'+str(solved)
            self.assertEqual(self.request('/api/login',dict(GOOD,bot_token=token))['status'],200)
            # La misma respuesta no sirve dos veces.
            for _ in range(2):self.request('/api/login',{'login':'demo','password':'incorrecta'})
            self.assertEqual(self.request('/api/login',dict(GOOD,bot_token=token))['status'],403)

    def test_idle_session_expires_on_server_and_activity_renews_it(self):
        clock=[2000000000]
        with patch.dict(app.os.environ,{'LOGIN_CAPTCHA':'off'}),patch.object(app.time,'time',side_effect=lambda:clock[0]):
            for remember in (False,True):
                result=self.request('/api/login',dict(GOOD,remember=remember));cookie=result['cookie'].split(';')[0]
                me=self.request('/api/me',cookie=cookie)['body'];csrf=me['user']['csrf'];self.assertEqual(me['idle'],{'seconds':900,'warning':120})
                # Las consultas automáticas no renuevan la sesión: a los 15 minutos (más el margen de sincronización) deja de valer, con o sin «Recordarme».
                clock[0]+=600;self.assertEqual(self.request('/api/tracking',cookie=cookie)['status'],200)
                clock[0]+=299+app.IDLE_GRACE;self.assertEqual(self.request('/api/me',cookie=cookie)['status'],200)
                # La actividad real (o «Continuar sesión») sí la renueva; exige el token CSRF.
                self.assertEqual(self.request('/api/session/activity',{},cookie=cookie)['status'],403)
                self.assertEqual(self.request('/api/session/activity',{},cookie=cookie,csrf=csrf)['body']['idle_seconds'],900)
                clock[0]+=899+app.IDLE_GRACE;self.assertEqual(self.request('/api/me',cookie=cookie)['status'],200)
                clock[0]+=2;self.assertEqual(self.request('/api/me',cookie=cookie)['status'],401)
                self.assertEqual(self.request('/api/session/activity',{},cookie=cookie,csrf=csrf)['status'],401)
            # Iniciar sesión otra vez emite un identificador nuevo y limpia las sesiones vencidas.
            fresh=self.request('/api/login',GOOD)['cookie'].split(';')[0];self.assertNotEqual(fresh,cookie)
            with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],1)
            new_csrf=self.request('/api/me',cookie=fresh)['body']['user']['csrf']
            self.assertEqual(self.request('/api/logout',{'reason':'idle'},cookie=fresh,csrf=new_csrf)['status'],200)
            with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='logout_idle'").fetchone()[0],1)


    def test_public_version_history_is_paged_and_has_no_session_requirement(self):
        first=self.request('/api/public/versions')['body'];total=first['total']
        self.assertEqual((first['page'],len(first['rows'])),(1,min(12,total)));self.assertEqual(first['pages'],max(1,(total+11)//12))
        self.assertEqual(set(first['rows'][0]),{'version','date','type','summary','notes'})
        self.assertEqual(first['rows'][0]['version'],self.request('/api/public/version')['body']['version'])
        last=self.request('/api/public/versions?page=99999')['body'];self.assertEqual(last['page'],1)  # página fuera de rango: se ignora
        self.assertEqual(self.request('/api/public/versions?page='+str(first['pages']))['body']['page'],first['pages'])


if __name__=='__main__':unittest.main()
