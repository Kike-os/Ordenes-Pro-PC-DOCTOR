"""Voz de ADI y ADI administrativa con la base remota (libSQL/Turso por HTTP).

Reproduce INC-20261021-001 (OperationalError en remote_db.py:233 en POST /api/public/adi/speech): la ruta abría una transacción
(límite por conexión) y la dejaba inactiva mientras OpenAI generaba el audio; Turso la descartaba («stream was idle for too long»).
Servidor libSQL de pruebas sobre una base temporal con datos ficticios; OpenAI simulado (ninguna llamada real)."""
import base64
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import test_app
import app,adi,adi_voice,autocare,remote_db
from hrana_fake import FakeLibsql

KEY={'OPENAI_API_KEY':'sk-prueba-ficticia-123'}
SLOW=0.5  # la llamada simulada a OpenAI tarda más de lo que el servidor conserva un flujo inactivo


class RemoteVoiceTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        self.server=FakeLibsql(str(app.DB),idle=5,stream_idle=0.2)
        self.remote=patch.dict(app.os.environ,{'TURSO_DATABASE_URL':self.server.url,'TURSO_AUTH_TOKEN':'',**KEY});self.remote.start()
        remote_db._pool.__dict__.pop('connections',None)

    def tearDown(self):
        self.remote.stop();remote_db._pool.__dict__.pop('connections',None);self.server.stop()
        test_app.SecurityTests.tearDown(self)

    def errors(self):
        with app.connect() as c:return autocare._load(c,'autocare_errors',[])

    def slow(self,result):
        def fake(url,data,headers,binary=False):
            time.sleep(SLOW);return result
        return patch.object(adi_voice,'_request',side_effect=fake)

    def test_public_speech_and_listen_survive_a_slow_openai_call(self):
        with self.slow(b'ID3'+b'\0'*400):
            for _ in range(2):  # el segundo saludo sale de la caché
                spoken=self.request('/api/public/adi/speech',{'kind':'greeting'})
                self.assertEqual(spoken['status'],200,(spoken['body'],self.errors()));self.assertTrue(base64.b64decode(spoken['body']['audio']).startswith(b'ID3'))
        with patch.object(adi,'ask',return_value='Con gusto, te ayudo con tu equipo.'):
            sent=self.request('/api/public/adi/message',{'message':'Hola'})
        cookie=sent['cookie'].split(';')[0];audio=base64.b64encode(b'\x1aE\xdf\xa3'+b'0'*5000).decode()
        with self.slow({'text':'Quiero agendar una cita'}):
            heard=self.request('/api/public/adi/listen',{'audio':audio,'mime':'audio/webm','duration_ms':'2400'},cookie=cookie)
        self.assertEqual((heard['status'],heard['body'].get('text')),(200,'Quiero agendar una cita'),heard['body'])
        with app.connect() as c:self.assertGreater(adi_voice.usage(c,app.reception_now()),0)  # el consumo se registró después de la llamada
        self.assertEqual(self.errors(),[])

    def test_admin_voice_and_admin_assistant_survive_a_slow_openai_call(self):
        self.server.stream_idle=None;cookie,csrf=self.login();self.server.stream_idle=0.2  # el cálculo de la contraseña no entra en la prueba
        post=lambda path,**b:self.request(path,b,cookie=cookie,csrf=csrf)
        with self.slow(b'ID3'+b'\0'*300):
            self.assertEqual(post('/api/adi/voice/sample',voice='nova')['status'],200)
            self.assertEqual(post('/api/adi/speech',text='Hay 3 órdenes listas para entregar.')['status'],200)
        def slow_ask(*args,**kwargs):
            time.sleep(SLOW);return 'Resumen ficticio del día.'
        with patch.object(adi,'ask',side_effect=slow_ask):
            answer=post('/api/adi/admin',message='Resume el estado del taller y sugiere prioridades')
        self.assertEqual(answer['status'],200,(answer['body'],self.errors()))
        self.assertEqual(self.errors(),[])


class ExpiredStreamTests(unittest.TestCase):
    """remote_db ante un flujo que Turso descartó por inactividad: el error nombra la operación y la conexión queda limpia."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();path=self.temp.name+'/r.sqlite3'
        with sqlite3.connect(path) as c:c.execute('CREATE TABLE fixture(id INTEGER PRIMARY KEY,name TEXT)')
        self.server=FakeLibsql(path,idle=5,stream_idle=0.2)

    def tearDown(self):
        self.server.stop();self.temp.cleanup()

    def test_idle_transaction_is_released_and_next_operation_starts_clean(self):
        c=remote_db.Connection(self.server.url,'')
        c.execute("INSERT INTO fixture(name) VALUES ('uno')");time.sleep(0.4)
        with self.assertRaises(sqlite3.OperationalError) as raised:c.execute("UPDATE fixture SET name='x' WHERE id=1")
        self.assertIn('idle for too long',str(raised.exception));self.assertEqual(raised.exception.operation,'UPDATE fixture')
        self.assertFalse(c.in_transaction);self.assertIsNone(c._baton)
        c.execute("INSERT INTO fixture(name) VALUES ('dos')");c.commit()  # la conexión sigue sirviendo
        self.assertEqual([tuple(r) for r in c.execute('SELECT name FROM fixture')],[('dos',)])  # lo descartado no se confirmó


if __name__=='__main__':unittest.main()
