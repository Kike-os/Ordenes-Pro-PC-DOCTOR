"""Llamadas externas lentas con la base remota (libSQL/Turso por HTTP): fabricante del equipo, correo de prueba y verificación Turnstile.

Mismo origen que INC-20261021-001: si la ruta deja una transacción abierta mientras espera a un servicio externo, Turso la descarta
(«stream was idle for too long») y la escritura siguiente falla. Servidor libSQL de pruebas sobre una base temporal con datos
ficticios; fabricante, correo y Cloudflare simulados (ninguna consulta ni envío real)."""
import time
import unittest
from unittest.mock import patch
import test_app
import app,autocare,device_manufacturers,remote_db
from hrana_fake import FakeLibsql

IDLE=0.8  # el servidor de pruebas descarta un flujo inactivo más de este tiempo (el cálculo de la contraseña tarda menos)
SLOW=1.5  # el servicio externo simulado tarda más


class RemoteExternalCallTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        self.server=FakeLibsql(str(app.DB),idle=5,stream_idle=IDLE)
        self.remote=patch.dict(app.os.environ,{'TURSO_DATABASE_URL':self.server.url,'TURSO_AUTH_TOKEN':''});self.remote.start()
        remote_db._pool.__dict__.pop('connections',None)

    def tearDown(self):
        self.remote.stop();remote_db._pool.__dict__.pop('connections',None);self.server.stop()
        test_app.SecurityTests.tearDown(self)

    def errors(self):
        with app.connect() as c:return autocare._load(c,'autocare_errors',[])

    def slow(self,value):
        def wait(*args,**kwargs):
            time.sleep(SLOW);return value
        return wait

    def test_manufacturer_lookup_survives_a_slow_official_service(self):
        cookie,_=self.login()
        env={'DELL_API_CLIENT_ID':'cliente-ficticio','DELL_API_CLIENT_SECRET':'secreto-ficticio'}
        with patch.dict(app.os.environ,env),patch.object(device_manufacturers,'lookup',side_effect=self.slow({'brand':'Dell','model':'Latitude ficticia'})):
            found=self.request('/api/devices/identify?serial=ZZ9FIC1&brand=Dell',cookie=cookie)
        self.assertEqual(found['status'],200,(found['body'],self.errors()));self.assertEqual(found['body']['manufacturer']['state'],'found')
        self.assertEqual(self.errors(),[])

    def test_test_mail_survives_a_slow_mail_server(self):
        cookie,csrf=self.login()
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app.mail_pro,'settings',return_value={'username':'taller@example.invalid','password':'x'}),\
             patch.object(app.mail_pro,'deliver',side_effect=self.slow({'refused':{},'dsn':False})):
            sent=self.request('/api/receipt-mail/settings',{'action':'test'},cookie=cookie,csrf=csrf)
        self.assertEqual((sent['status'],sent['body'].get('result')),(200,'sent'),(sent['body'],self.errors()))
        self.assertEqual(self.errors(),[])

    def test_login_survives_a_slow_turnstile_check(self):
        env={'TURNSTILE_SITE_KEY':'sitio-ficticio','TURNSTILE_SECRET_KEY':'secreto-ficticio'}
        with patch.dict(app.os.environ,env),patch.object(app,'verify_bot',side_effect=self.slow(True)):
            cookie,_=self.login()
        self.assertTrue(cookie);self.assertEqual(self.errors(),[])


if __name__=='__main__':unittest.main()
