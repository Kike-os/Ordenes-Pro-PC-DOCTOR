"""Presupuestos con la base remota (libSQL/Turso por HTTP): crear → guardar → actualizar → enviar → volver a abrir → reintentar.

Reproduce la incidencia INC-20261020-003 (OperationalError en remote_db.py:309 al enviar): el servidor remoto cierra las
conexiones HTTP inactivas y el correo tarda más que ese plazo. Usa un servidor libSQL de pruebas sobre una base temporal con
datos ficticios; el correo se simula (no sale ningún mensaje)."""
import sqlite3
import time
import unittest
from unittest.mock import patch
import test_app
import app,remote_db,autocare
from hrana_fake import FakeLibsql

MAIL={'username':'taller@example.invalid','password':'x'}


class RemoteQuoteFlowTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        self.cookie,self.csrf=self.login()
        self.server=FakeLibsql(str(app.DB),idle=0.25)
        self.remote=patch.dict(app.os.environ,{'TURSO_DATABASE_URL':self.server.url,'TURSO_AUTH_TOKEN':''});self.remote.start()
        remote_db._pool.__dict__.pop('connections',None)

    def tearDown(self):
        self.remote.stop();remote_db._pool.__dict__.pop('connections',None);self.server.stop()
        test_app.SecurityTests.tearDown(self)

    def post(self,path,**body):return self.request(path,body,cookie=self.cookie,csrf=self.csrf)
    def get(self,path):return self.request(path,cookie=self.cookie)

    def errors(self):
        with app.connect() as c:return autocare._load(c,'autocare_errors',[])

    def new_order(self,key):
        made=self.post('/api/orders',**self.order_data({'email':'cliente@example.invalid','brand':'HP','model':'Ficticio','request_key':'remote-quote-request-'+key}))
        self.assertEqual(made['status'],201,made['body']);return made['body']

    def slow_mail(self,seconds=0.6,fail=False):
        """El servidor de correo tarda más de lo que el servidor remoto mantiene abierta una conexión inactiva."""
        sent=[]
        def deliver(config,message,recipients):
            time.sleep(seconds)
            if fail:raise app.mail_pro.MailError('conexion','Servidor de correo ficticio sin respuesta.')
            sent.append(recipients);return {'refused':{},'dsn':False}
        return sent,[patch.object(app.mail_pro,'configured',return_value=True),patch.object(app.mail_pro,'settings',return_value=MAIL),patch.object(app.mail_pro,'deliver',side_effect=deliver)]

    def send(self,quote,**mail):
        sent,patches=self.slow_mail(**mail)
        for item in patches:item.start()
        try:return self.post('/api/quotes/%d'%quote,action='send'),sent
        finally:
            for item in patches:item.stop()

    def items(self,price=3500):
        return [{'description':'Mantenimiento preventivo ficticio','category':'servicio','quantity':1,'unit_cents':price,'taxed':True},{'description':'Licencia ficticia','category':'licencia','quantity':2,'unit_cents':1250,'taxed':False}]

    def test_save_update_send_reopen_with_slow_mail_and_stale_connections(self):
        order=self.new_order('0001');valid=(app.reception_now().date()+app.appointments.timedelta(days=10)).isoformat()
        quote=self.post('/api/orders/%d/quote'%order['id'])['body']['id']
        saved=self.post('/api/quotes/%d'%quote,action='save',items=self.items(),valid_until=valid,notes='Observación ficticia',discount='500',require_id=True)
        self.assertEqual(saved['status'],200,saved['body'])
        time.sleep(0.4)  # la conexión reutilizable queda inactiva y el servidor la cierra
        updated=self.post('/api/quotes/%d'%quote,action='save',items=self.items(4000),valid_until=valid,notes='Observación actualizada',discount='500',require_id=True)['body']['quote']
        # Importes guardados: 4000 + 2×1250 = 6500 antes del descuento del 5 % por línea (200 + 125) → 6175; IVA 15 % solo de la línea gravada.
        t=updated['totals'];self.assertEqual((t['gross'],t['discount'],t['quoted']),(6500,325,6175));self.assertEqual(t['base_taxed']+t['base_zero']+t['tax'],t['quoted']);self.assertEqual(t['tax'],3800-3304)
        result,sent=self.send(quote)
        self.assertEqual(result['status'],200,result['body']);self.assertEqual((result['body']['mail'],len(sent)),('sent',1))
        again=self.get('/api/quotes/%d'%quote)['body']['quote']
        self.assertEqual((again['status'],again['notes'],again['require_id'],again['discount_bp'],again['valid_until'],again['mail_state']),('enviado','Observación actualizada',1,500,valid,'sent'))
        self.assertEqual(again['totals'],t)
        with app.connect() as c:
            archived=c.execute("SELECT status FROM mail_archive WHERE kind='quote' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(archived['status'],'enviado')
        self.assertEqual(self.errors(),[])

    def test_failed_mail_keeps_quote_and_retry_sends(self):
        order=self.new_order('0002');quote=self.post('/api/orders/%d/quote'%order['id'])['body']['id']
        self.post('/api/quotes/%d'%quote,action='save',items=self.items())
        failed,_=self.send(quote,fail=True)
        self.assertEqual(failed["status"],200,(failed["body"],self.errors()));self.assertEqual(failed['body']['mail'],'failed');self.assertIn('/presupuesto/',failed['body']['link'])
        kept=self.get('/api/quotes/%d'%quote)['body']['quote'];self.assertEqual((kept['status'],kept['mail_state'],len(kept['items'])),('enviado','failed',2))
        retry,sent=self.send(quote)
        self.assertEqual((retry['status'],retry['body']['mail'],len(sent)),(200,'sent',1))
        self.assertEqual(self.get('/api/quotes/%d'%quote)['body']['quote']['mail_state'],'sent')
        self.assertEqual(self.errors(),[])

    def test_consecutive_quotes_do_not_raise_operational_errors(self):
        for n in range(4):
            order=self.new_order('01%02d'%n);quote=self.post('/api/orders/%d/quote'%order['id'])['body']['id']
            self.assertEqual(self.post('/api/quotes/%d'%quote,action='save',items=self.items(3000+n*100))['status'],200)
            result,sent=self.send(quote,seconds=0.35)
            self.assertEqual((result['status'],result['body'].get('mail')),(200,'sent'),result['body'])
            time.sleep(0.3)
        self.assertEqual(self.errors(),[])


class RemoteConnectionTests(unittest.TestCase):
    """remote_db ante conexiones que el servidor cerró: transacción con pausa larga, primer paso reintentable y operación en el error."""
    def setUp(self):
        import tempfile,sqlite3
        self.temp=tempfile.TemporaryDirectory();path=self.temp.name+'/r.sqlite3'
        with sqlite3.connect(path) as c:c.execute('CREATE TABLE fixture(id INTEGER PRIMARY KEY,name TEXT)')
        self.server=FakeLibsql(path,idle=0.2);remote_db._pool.__dict__.pop('connections',None)

    def tearDown(self):
        remote_db._pool.__dict__.pop('connections',None);self.server.stop();self.temp.cleanup()

    def test_transaction_survives_a_long_pause_and_first_write_after_idle_is_retried(self):
        c=remote_db.Connection(self.server.url,'')
        c.execute("INSERT INTO fixture(name) VALUES ('uno')");time.sleep(0.5)  # el servidor cierra la conexión inactiva
        with patch.object(remote_db,'IDLE_REUSE',0.1):c.execute("INSERT INTO fixture(name) VALUES ('dos')");c.commit()
        time.sleep(0.5)
        with patch.object(remote_db,'IDLE_REUSE',60):c.execute("UPDATE fixture SET name='tres' WHERE id=1");c.commit()  # primer paso sin baton: se reintenta
        self.assertEqual([tuple(r) for r in c.execute('SELECT id,name FROM fixture ORDER BY id')],[(1,'tres'),(2,'dos')])

    def test_lost_response_inside_a_transaction_is_not_repeated_and_names_the_operation(self):
        c=remote_db.Connection(self.server.url,'')
        c.execute("INSERT INTO fixture(name) VALUES ('uno')")
        self.server.fail_next=1
        with self.assertRaises(sqlite3.OperationalError) as raised:c.execute("UPDATE fixture SET name='x' WHERE id=1")
        self.assertEqual(raised.exception.operation,'UPDATE fixture');self.assertFalse(c.in_transaction)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM fixture').fetchone()[0],0)  # la transacción interrumpida se descartó entera


if __name__=='__main__':unittest.main()
