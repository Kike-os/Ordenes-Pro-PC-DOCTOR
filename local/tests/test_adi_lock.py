"""La llamada a la IA no retiene la base de datos: otra petición puede escribir mientras ADI espera la respuesta."""
import sqlite3,threading,time,unittest
from unittest.mock import patch
import test_app
import app,adi_ai
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class AdiLockTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request

    def test_database_is_free_while_the_ai_answers(self):
        cookie,csrf=self.login();inside=threading.Event();release=threading.Event();outcome={}
        def slow(system,user):
            inside.set();release.wait(8);return 'El equipo necesita una revisión técnica.',10,10
        def improve():outcome['write']=self.request('/api/adi/write',{'text':'El equpo nesecita una revision tecnica','mode':'ortografia','field':'comment'},cookie=cookie,csrf=csrf)
        with patch.dict(app.os.environ,{'OPENAI_API_KEY':'clave-ficticia-de-prueba'}),patch.object(adi_ai,'_complete',side_effect=slow):
            worker=threading.Thread(target=improve);worker.start();self.assertTrue(inside.wait(5))
            # Con la IA todavía «pensando», una escritura independiente debe poder hacerse de inmediato.
            started=time.time()
            try:
                other=sqlite3.connect(app.DB,timeout=1.5);other.execute('BEGIN IMMEDIATE');other.execute("INSERT INTO attempts VALUES ('prueba-bloqueo',1,?)",(int(time.time())+60,));other.commit();other.close();free=True
            except sqlite3.OperationalError:free=False
            waited=time.time()-started;release.set();worker.join(10)
        self.assertTrue(free,'la base quedó bloqueada mientras ADI esperaba a la IA');self.assertLess(waited,1.0)
        self.assertEqual(outcome['write']['status'],200,outcome['write']);self.assertTrue(outcome['write']['body']['changed'])
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM adi_actions WHERE action='writing_improve'").fetchone()[0],1)


if __name__=='__main__':
    unittest.main()
