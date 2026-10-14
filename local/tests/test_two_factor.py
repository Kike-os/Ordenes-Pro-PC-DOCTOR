"""Verificación en dos pasos: activación con contraseña, segundo paso en el acceso, códigos de un solo uso y recuperación. Datos ficticios."""
import base64,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,test_app,two_factor
PASSWORD='contraseña-segura-de-prueba'


class TwoFactorTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def setUp(self):
        # Reloj detenido a mitad de un intervalo de 30 s: los códigos «actual» y «siguiente» no dependen del instante en que corre la prueba.
        test_app.SecurityTests.setUp(self)
        from unittest.mock import patch
        self.now=int(time.time())//30*30+10;clock=patch.object(two_factor.time,'time',lambda:self.now);clock.start();self.addCleanup(clock.stop)

    def code(self,offset=0):
        with app.connect() as c:secret=two_factor.unseal(c.execute('SELECT secret FROM user_mfa WHERE user_id=?',(self.uid,)).fetchone()[0])
        return two_factor.code_at(secret,self.now//30+offset)

    def enable(self):
        cookie,csrf=self.login();setup=lambda **body:self.request('/api/account/second-step',body,cookie=cookie,csrf=csrf)
        started=setup(action='start',password=PASSWORD);self.assertEqual(started['status'],200,started['body'])
        done=setup(action='confirm',code=self.code());self.assertEqual(done['status'],200,done['body'])
        return cookie,csrf,setup,started['body'],done['body']

    def sign_in(self):return self.request('/api/login',{'login':'demo','password':PASSWORD})
    def second(self,challenge,code):return self.request('/api/login/second-step',{'challenge':challenge,'code':code})

    def test_algorithm_matches_the_standard_and_rejects_reuse(self):
        secret=base64.b32encode(b'12345678901234567890').decode()                       # vectores del RFC 6238 (SHA-1), a 6 dígitos
        self.assertEqual([two_factor.code_at(secret,t//30) for t in (59,1111111109,1234567890,2000000000)],['287082','081804','005924','279037'])
        step=two_factor.matching_step(secret,'287082',now=59);self.assertEqual(step,1)
        self.assertEqual(two_factor.matching_step(secret,'287 082',now=59+30),1)       # el código anterior aún vale 30 s más
        self.assertIsNone(two_factor.matching_step(secret,'287082',now=59+90));self.assertIsNone(two_factor.matching_step(secret,'287082',now=59,after=1))
        for bad in ('','12345','1234567','abcdef',None):self.assertIsNone(two_factor.matching_step(secret,bad,now=59))
        self.assertTrue(two_factor.uri(secret,'demo@example.invalid').startswith('otpauth://totp/'));self.assertEqual(len(two_factor.new_secret()),32)

    def test_setup_needs_password_and_a_valid_code(self):
        cookie,csrf=self.login();setup=lambda **body:self.request('/api/account/second-step',body,cookie=cookie,csrf=csrf)
        self.assertEqual(self.request('/api/settings',cookie=cookie)['body']['second_step'],{'enabled':False,'state':'off','since':None,'recovery_left':0})
        self.assertEqual(setup(action='start',password='otra')['status'],400);self.assertEqual(self.request('/api/account/second-step',{'action':'start','password':PASSWORD},cookie=cookie)['status'],403)
        started=setup(action='start',password=PASSWORD)['body'];self.assertEqual(len(started['secret']),32);self.assertIn('<svg',started['qr'])
        # Sin confirmar no protege ni bloquea nada: el acceso sigue siendo solo con contraseña.
        self.assertEqual(setup(action='confirm',code='000000')['status'],400);self.assertNotIn('second_step',self.sign_in()['body'])
        done=setup(action='confirm',code=self.code());self.assertEqual((done['status'],len(done['body']['recovery']),done['body']['second_step']['enabled'],done['body']['second_step']['recovery_left']),(200,10,True,10))
        self.assertEqual(setup(action='start',password=PASSWORD)['status'],409)
        with app.connect() as c:
            stored=c.execute('SELECT recovery FROM user_mfa').fetchone()[0];self.assertFalse(any(code in stored for code in done['body']['recovery']))   # solo huellas
            self.assertEqual([r[0] for r in c.execute("SELECT action FROM audit WHERE action LIKE 'second_step%' ORDER BY id")],['second_step_setup_started','second_step_confirm_failed','second_step_enabled'])

    def test_login_requires_the_second_step(self):
        cookie,csrf,setup,started,done=self.enable()
        first=self.sign_in();self.assertEqual((first['status'],first['body'].get('second_step'),first['cookie']),(200,True,None))     # contraseña correcta: aún sin sesión
        challenge=first['body']['challenge'];self.assertEqual(self.request('/api/settings')['status'],401)
        self.assertEqual(self.second(challenge,'000000')['status'],401);self.assertEqual(self.second('desafio-inventado',self.code(1))['body'].get('restart'),True)
        # El código con el que se activó ya se usó: no sirve de nuevo. El siguiente sí.
        self.assertEqual(self.second(challenge,self.code())['status'],401)
        ok=self.second(challenge,self.code(1));self.assertEqual((ok['status'],ok['body']['recovery_used']),(200,False));self.assertTrue(ok['cookie'])
        self.assertEqual(self.request('/api/settings',cookie=ok['cookie'].split(';')[0])['status'],200)
        # El desafío se consume y un código no vale dos veces.
        self.assertEqual(self.second(challenge,self.code(1))['body'].get('restart'),True)
        again=self.sign_in()['body']['challenge'];self.assertEqual(self.second(again,self.code(1))['status'],401)
        # Contraseña incorrecta: mismo mensaje de siempre, sin revelar que la cuenta tiene segundo paso.
        wrong=self.request('/api/login',{'login':'demo','password':'incorrecta-123456'});self.assertEqual(wrong['status'],401);self.assertNotIn('second_step',wrong['body'])

    def test_challenge_expires_after_five_wrong_codes(self):
        self.enable();challenge=self.sign_in()['body']['challenge']
        codes=[self.second(challenge,'111111') for _ in range(5)];self.assertEqual([r['status'] for r in codes],[401]*5);self.assertTrue(codes[-1]['body'].get('restart'))
        self.assertTrue(self.second(challenge,self.code(1))['body'].get('restart'))      # agotado: ni el código correcto lo reabre
        with app.connect() as c:c.execute('UPDATE mfa_challenges SET expires=1');c.commit()
        fresh=self.sign_in()['body']['challenge']
        with app.connect() as c:c.execute('UPDATE mfa_challenges SET expires=1');c.commit()
        self.assertTrue(self.second(fresh,self.code(1))['body'].get('restart'))          # caducado

    def test_recovery_codes_work_once_and_can_be_renewed(self):
        cookie,csrf,setup,started,done=self.enable();codes=done['recovery']
        used=self.second(self.sign_in()['body']['challenge'],codes[0].lower().replace('-',' '));self.assertEqual((used['status'],used['body']['recovery_used'],used['body']['recovery_left']),(200,True,9))
        self.assertEqual(self.second(self.sign_in()['body']['challenge'],codes[0])['status'],401)
        session=used['cookie'].split(';')[0];csrf2=None
        with app.connect() as c:csrf2=c.execute('SELECT csrf FROM sessions ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        renew=self.request('/api/account/second-step',{'action':'recovery','password':PASSWORD,'code':self.code(1)},cookie=session,csrf=csrf2)
        self.assertEqual((renew['status'],len(renew['body']['recovery'])),(200,10));self.assertEqual(self.second(self.sign_in()['body']['challenge'],codes[1])['status'],401)   # los anteriores dejan de valer
        self.assertEqual(self.second(self.sign_in()['body']['challenge'],renew['body']['recovery'][0])['status'],200)

    def test_disable_needs_password_and_code_and_admin_can_reset_another_account(self):
        cookie,csrf,setup,started,done=self.enable()
        self.assertEqual(setup(action='disable',password='otra',code=self.code(1))['status'],400);self.assertEqual(setup(action='disable',password=PASSWORD,code='000000')['status'],400)
        self.assertEqual(setup(action='disable',password=PASSWORD,code=self.code(1))['status'],200);self.assertNotIn('second_step',self.sign_in()['body'])
        # Otra cuenta con el segundo paso activo: administración lo retira y se cierran sus sesiones.
        with app.connect() as c:
            other=c.execute("INSERT INTO users(username,email,name,password_hash,role,active,created_at,approval) VALUES ('tecnica','tecnica@example.invalid','Técnica Ficticia',?,'tecnico',1,0,'approved')",(app.password_hash(PASSWORD),)).lastrowid
            c.execute("INSERT INTO user_mfa(user_id,secret,confirmed_at,created_at) VALUES (?,?,1,1)",(other,two_factor.new_secret()));c.commit()
        cookie,csrf=self.login();manage=lambda uid:self.request('/api/users/manage',{'id':str(uid),'action':'second_step_reset','role':''},cookie=cookie,csrf=csrf)
        accounts=self.request('/api/settings',cookie=cookie)['body']['accounts'];self.assertEqual({a['username']:a['second_step'] for a in accounts},{'demo':0,'tecnica':1})
        self.assertEqual(manage(self.uid)['status'],400);self.assertEqual(manage(other)['status'],200);self.assertEqual(manage(other)['status'],409)
        with app.connect() as c:self.assertFalse(two_factor.active(c,other));self.assertEqual(c.execute("SELECT entity_id FROM audit WHERE action='second_step_reset_by_admin'").fetchone()[0],other)
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
        self.assertEqual(manage(other)['status'],403)


    def test_any_user_sees_own_status_and_maintenance_script_resets(self):
        import importlib.util,io,contextlib,sys as _sys
        cookie,csrf,setup,started,done=self.enable()
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
        first=self.sign_in()['body'];ok=self.second(first['challenge'],self.code(1));session=ok['cookie'].split(';')[0]
        self.assertEqual(self.request('/api/settings',cookie=session)['status'],403)                      # Configuración sigue siendo de administración…
        mine=self.request('/api/account/second-step',cookie=session);self.assertEqual((mine['status'],mine['body']['second_step']['enabled']),(200,True))   # …pero su segundo paso es suyo
        self.assertNotIn('secret',str(mine['body']));self.assertEqual(self.request('/api/account/second-step')['status'],401)
        spec=importlib.util.spec_from_file_location('second_step_reset',str(Path(app.ROOT).parent/'maintenance'/'second-step-reset.py'));tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
        def run(*args):
            old=_sys.argv;_sys.argv=['second-step-reset.py',*args];out=io.StringIO()
            try:
                with contextlib.redirect_stdout(out):code=tool.main()
            finally:_sys.argv=old
            return code,out.getvalue()
        self.assertEqual(run('nadie')[0],1);code,text=run('demo');self.assertIn('--confirmar',text)
        with app.connect() as c:self.assertTrue(two_factor.active(c,self.uid))                              # sin --confirmar no cambia nada
        code,text=run('demo','--confirmar');self.assertEqual(code,0);self.assertNotIn(started['secret'],text)
        with app.connect() as c:
            self.assertFalse(two_factor.active(c,self.uid));self.assertEqual(c.execute('SELECT COUNT(*) FROM sessions WHERE user_id=?',(self.uid,)).fetchone()[0],0)
            self.assertEqual(c.execute("SELECT entity_id FROM audit WHERE action='second_step_reset_by_maintenance'").fetchone()[0],self.uid)
        self.assertNotIn('second_step',self.sign_in()['body'])


if __name__=='__main__':unittest.main()


class SecretAtRestTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def test_secret_is_encrypted_authenticated_and_never_stored_in_clear(self):
        sealed=two_factor.seal('JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP')
        self.assertTrue(sealed.startswith('enc1:'));self.assertNotIn('JBSWY3DP',sealed)
        self.assertEqual(two_factor.unseal(sealed),'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP')
        self.assertNotEqual(two_factor.seal('JBSWY3DPEHPK3PXP'),two_factor.seal('JBSWY3DPEHPK3PXP'))  # nonce aleatorio
        tampered=sealed[:-3]+('A' if sealed[-3]!='A' else 'B')+sealed[-2:]
        with self.assertRaises(Exception):two_factor.unseal(tampered)
        # Con otra clave maestra el valor no se puede abrir.
        with patch.dict(app.os.environ,{'MFA_ENCRYPTION_KEY':two_factor.base64.urlsafe_b64encode(b'x'*32).decode()}):
            with self.assertRaises(Exception):two_factor.unseal(sealed)
        # En Vercel sin clave configurada no se genera ninguna: se informa del problema.
        with patch.dict(app.os.environ,{'VERCEL':'1','MFA_ENCRYPTION_KEY':''}):
            with self.assertRaises(two_factor.KeyError_):two_factor.seal('JBSWY3DPEHPK3PXP')
        cookie,csrf=self.login()
        started=self.request('/api/account/second-step',{'action':'start','password':PASSWORD},cookie=cookie,csrf=csrf)
        self.assertEqual(started['status'],200)
        with app.connect() as c:
            stored=c.execute('SELECT secret FROM user_mfa WHERE user_id=?',(self.uid,)).fetchone()[0]
            self.assertTrue(stored.startswith('enc1:'));self.assertNotIn(started['body']['secret'],stored)
        self.assertEqual(self.request('/api/settings',cookie=cookie)['body']['second_step']['state'],'pending')
        # Una clave anterior sin cifrar (versiones previas) se sigue leyendo y se cifra al usarse.
        with app.connect() as c:
            c.execute("UPDATE user_mfa SET secret='JBSWY3DPEHPK3PXP',confirmed_at=1,recovery='[]' WHERE user_id=?",(self.uid,))
            now=time.time();code=two_factor.code_at('JBSWY3DPEHPK3PXP',int(now//30))
            self.assertEqual(two_factor.check(c,self.uid,code,now),'totp')
            self.assertTrue(c.execute('SELECT secret FROM user_mfa WHERE user_id=?',(self.uid,)).fetchone()[0].startswith('enc1:'))
            self.assertIsNone(two_factor.check(c,self.uid,code,now))  # el mismo código no sirve dos veces
