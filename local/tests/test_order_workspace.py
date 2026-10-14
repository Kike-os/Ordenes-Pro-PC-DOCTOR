import unittest
from datetime import datetime
from unittest.mock import patch
import json
import sqlite3
import tempfile
from pathlib import Path
import app
app.os.environ.setdefault('LOGIN_CAPTCHA','off')  # Las pruebas inician sesión sin verificación salvo que la activen.
import test_app
import order_workspace

class WorkspaceTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data

    def create(self,cookie,csrf):
        r=self.request('/api/orders',self.order_data(),cookie=cookie,csrf=csrf)
        self.assertEqual(r['status'],201,r)
        return r['body']['id']

    def test_seven_states_history_filters_and_server_dates(self):
        cookie,csrf=self.login()
        with patch.object(app,'reception_now',return_value=datetime.fromisoformat('2026-10-09T23:59:59-05:00')):oid=self.create(cookie,csrf)
        options=self.request('/api/order-options',cookie=cookie)['body']
        self.assertEqual(options['statuses'],order_workspace.STATUSES)
        self.assertEqual(len(options['statuses']),8)
        for state,label in options['statuses'].items():
            r=self.request('/api/order-status',{'id':str(oid),'status':state,'comment':'Prueba de '+label},cookie=cookie,csrf=csrf)
            self.assertEqual(r['status'],200,r)
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
        self.assertEqual(len(order['history']),10)  # incluye la cita de mantenimiento generada al entregar y la revisión recurrente
        self.assertEqual(order['history'][0]['actor_id'],self.uid)
        for query,total in [('status=entregado',1),('active=1',0),('from=2026-10-09&to=2026-10-09',1),('from=2026-10-10',0),('client=NO-EXISTE',0),('equipment=NO-EXISTE',0)]:
            self.assertEqual(self.request('/api/orders?'+query,cookie=cookie)['body']['total'],total)
        self.assertEqual(self.request('/api/orders?from=bad',cookie=cookie)['status'],400)
        self.assertEqual(self.request('/api/orders?from=2026-10-10&to=2026-10-09',cookie=cookie)['status'],400)
        self.assertEqual(self.request('/api/orders?status=diagnostico',cookie=cookie)['status'],400)
        with app.connect() as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE order_history SET comment='editado'")

    def test_edit_budget_cents_conflicts_and_immutable_reception(self):
        cookie,csrf=self.login();oid=self.create(cookie,csrf)
        original=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
        payload={'revision':0,'problem':'Descripción actualizada','status':'presupuesto','priority':'alta','assigned_to':str(self.uid),'estimated_delivery':'2026-10-20','internal_notes':'Nota técnica','findings':'Hallazgo','recommendations':'Recomendación','comment':'Revisión de presupuesto','lines':[{'category':'labor','description':'Diagnóstico','amount_cents':1001},{'category':'parts','description':'Repuesto','amount_cents':2033}]}
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/workspace',payload,cookie=cookie,csrf=csrf)['status'],200)
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
        self.assertEqual(order['budget']['total_cents'],3034)
        self.assertEqual(order['current_problem'],'Descripción actualizada')
        self.assertEqual(order['problem'],original['problem'])
        for key in ('code','qr_url','received_at','terms_acceptance_id'):self.assertEqual(order[key],original[key])
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/workspace',payload,cookie=cookie,csrf=csrf)['status'],409)
        for changes in [{'priority':'inventada'},{'estimated_delivery':'2026-02-30'},{'assigned_to':'99999'},{'lines':[{'category':'parts','description':'x','amount_cents':-1}]},{'lines':[{'category':'parts','description':'x','amount_cents':1.1}]}]:
            self.assertEqual(self.request('/api/orders/'+str(oid)+'/workspace',{**payload,'revision':1,**changes},cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']['revision'],1)
        for suffix in ('receipt.pdf','thermal.pdf','service.pdf'):
            result=self.request('/api/orders/'+str(oid)+'/'+suffix,cookie=cookie)
            self.assertEqual(result['status'],200,result);self.assertTrue(result['body'].startswith(b'%PDF'))
            self.assertEqual(self.request('/api/orders/'+str(oid)+'/'+suffix)['status'],401)

    def test_follow_up_permissions_and_validation(self):
        cookie,csrf=self.login();oid=self.create(cookie,csrf)
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        for value,status in [('',400),('x'*2001,400),('Avance técnico',201)]:
            self.assertEqual(self.request('/api/orders/'+str(oid)+'/follow-up',{'comment':value},cookie=cookie,csrf=csrf)['status'],status)
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/workspace',{},cookie=cookie,csrf=csrf)['status'],403)
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/follow-up',{'comment':'x'},cookie=cookie,csrf='bad')['status'],403)
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
        self.assertEqual(order['history'][0]['comment'],'Avance técnico')
        self.assertEqual(order['revision'],1)

    def test_migration_preserves_diagnostic_history_and_qr(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.multiple(app,DATA=Path(directory),DB=Path(directory)/'db.sqlite3'):
                c=sqlite3.connect(app.DB)
                c.execute('CREATE TABLE migrations(name TEXT PRIMARY KEY)')
                for migration in sorted(app.ROOT.joinpath('migrations').glob('*.sql')):
                    if migration.name.startswith('006'):break
                    c.executescript(migration.read_text());c.execute('INSERT INTO migrations VALUES (?)',(migration.name,))
                c.execute("INSERT INTO users VALUES (1,'old','old@example.invalid','Anterior','hash','administrador',1,0)")
                c.execute("INSERT INTO clients(name) VALUES ('Histórico')")
                c.execute("INSERT INTO devices(client_id,type,category) VALUES (1,'escritorio','escritorio')")
                c.execute("INSERT INTO orders(device_id,status,problem,created_by,created_at,code,qr_url) VALUES (1,'diagnostico','Falla histórica',1,0,'LEGACY-1','https://example.invalid/original')")
                c.commit();c.close();app.migrate();app.migrate()
                with app.connect() as c:
                    row=c.execute('SELECT code,qr_url,status FROM orders').fetchone()
                    self.assertEqual(tuple(row),('LEGACY-1','https://example.invalid/original','reparacion'))
                    self.assertEqual(c.execute('SELECT status_label FROM order_history').fetchone()[0],'En diagnóstico')
                    self.assertEqual(c.execute('SELECT count(*) FROM statuses').fetchone()[0],8)  # 7 originales + «En revisión por falla recurrente»
                    self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_order_search_includes_customer_contacts_equipment_and_valid_page(self):
        from urllib.parse import urlencode
        cookie,csrf=self.login();oid=self.create(cookie,csrf)
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
        with app.connect() as c:c.execute("UPDATE devices SET brand='ASUS',model='E1586369',serial='SERIAL-SCAN-001' WHERE id=?",(order['device_id'],))
        for term in [order['code'],order['client'],order['identification'],order['phone'],'ASUS','E1586369','SERIAL-SCAN-001']:
            result=self.request('/api/orders?'+urlencode({'q':term}),cookie=cookie)
            self.assertEqual(result['status'],200,result);self.assertEqual(result['body']['total'],1,term)
        result=self.request('/api/orders?page=999',cookie=cookie)['body'];self.assertEqual(result['page'],1);self.assertEqual(len(result['rows']),1)
        self.assertEqual(self.request('/api/orders?q=SERIAL-SCAN-001')['status'],401)
