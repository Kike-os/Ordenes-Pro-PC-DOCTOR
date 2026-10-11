import json
import sqlite3
import unittest
from unittest.mock import patch
import test_app
import app
app.os.environ.setdefault('LOGIN_CAPTCHA','off')  # Las pruebas inician sesión sin verificación salvo que la activen.
import technical_access
import code128


class ThermalAccessTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data

    def create(self,**changes):
        cookie,csrf=self.login();data=self.order_data(changes);r=self.request('/api/orders',data,cookie=cookie,csrf=csrf)
        self.assertEqual(r['status'],201,r)
        return cookie,csrf,data,r['body']['id']

    def test_decision_required_and_no_implicit_scopes(self):
        cookie,csrf=self.login();data=self.order_data();data.pop('technical_access')
        result=self.request('/api/orders',data,cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],400);self.assertIn('technical_access',result['body']['fields'])
        for changes,field in [({'technical_access':'authorized'},'technical_access'),({'access_confirmed':False},'access_confirmed'),({'access_operating_system':True},'technical_access'),({'technical_access':'authorized','access_specific_files':True},'access_detail'),({'destructive_action':'authorized'},'destructive_action')]:
            r=self.request('/api/orders',{**self.order_data(),**changes},cookie=cookie,csrf=csrf)
            self.assertEqual(r['status'],400,r);self.assertIn(field,r['body']['fields'])
        with app.connect() as c:self.assertEqual(c.execute('select count(*) from orders').fetchone()[0],0)

    def test_access_evidence_and_destructive_separation(self):
        cookie,csrf,_,oid=self.create(technical_access='authorized',access_operating_system=True,access_signed_in_tests=True)
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];a=order['access_authorization']
        self.assertEqual(a['decision'],'authorized');self.assertEqual(a['actor_id'],self.uid);self.assertEqual(a['recorded_at'],order['received_at']);self.assertTrue(a['permissions']['operating_system']);self.assertFalse(a['permissions']['specific_files']);self.assertIsNone(order['destructive_authorization'])
        with app.connect() as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute('update order_access_consents set decision=\'denied\' where order_id=?',(oid,))
        payload={'technical_access':'denied','access_confirmed':True,'access_revision':str(order['access_revision']),'request_key':'access-second-request-0001'}
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/authorizations',payload,cookie=cookie,csrf=csrf)['status'],201)
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/authorizations',payload,cookie=cookie,csrf=csrf)['status'],200)
        latest=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];self.assertEqual(len(latest['access_history']),2);self.assertEqual(latest['access_authorization']['decision'],'denied');self.assertEqual(latest['qr_url'],order['qr_url'])
        stale={**payload,'request_key':'access-stale-request-0001'};self.assertEqual(self.request('/api/orders/'+str(oid)+'/authorizations',stale,cookie=cookie,csrf=csrf)['status'],409)
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/authorizations',payload,cookie=cookie)['status'],403)

    def test_additional_destructive_permission_is_independent(self):
        cookie,csrf,_,oid=self.create(destructive_action='authorized',destructive_confirmed=True,destructive_detail='Reinstalar sistema; eliminar partición acordada.')
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
        self.assertEqual(order['access_authorization']['decision'],'denied')
        self.assertEqual(order['destructive_authorization']['decision'],'authorized')
        self.assertEqual(len(order['access_history']),2)

    def test_historical_record_truth_and_later_acceptance(self):
        cookie,csrf=self.login()
        data=self.order_data()
        with app.connect() as c:
            did=c.execute("INSERT INTO devices(client_id,type,category) VALUES (?,'portatil','portatil')",(data['client_id'],)).lastrowid
            oid=c.execute("INSERT INTO orders(device_id,status,problem,created_by,created_at,code,received_at,qr_url) VALUES (?,'pendiente','Prueba histórica',?,0,'PCD-20200101-0001','2020-01-01T10:00:00-05:00','https://example.invalid/orders/PCD-20200101-0001')",(did,self.uid)).lastrowid
        before=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];self.assertIsNone(before['access_authorization']);self.assertIsNone(before['terms'])
        payload={'technical_access':'denied','access_confirmed':True,'access_revision':'0','request_key':'historical-access-request-01','complete_terms':True,'terms_document_id':data['terms_document_id'],'terms_accept':True}
        r=self.request('/api/orders/'+str(oid)+'/authorizations',payload,cookie=cookie,csrf=csrf);self.assertEqual(r['status'],201,r)
        after=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];self.assertNotEqual(after['terms_accepted_at'],after['received_at']);self.assertEqual(before['qr_url'],after['qr_url']);self.assertEqual(after['code'],before['code'])

    def test_reprint_does_not_create_records_or_change_qr(self):
        cookie,csrf,data,oid=self.create(request_key='thermal-reprint-request-00001')
        original=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
        for i in range(2):
            r=self.request('/api/orders/'+str(oid)+'/thermal.pdf',cookie=cookie);self.assertEqual(r['status'],200);self.assertTrue(r['body'].startswith(b'%PDF'));self.assertNotIn(b'/XObject',r['body'])
        with app.connect() as c:
            self.assertEqual(c.execute('select count(*) from orders').fetchone()[0],1);self.assertEqual(c.execute('select count(*) from order_access_consents').fetchone()[0],1)
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/thermal.pdf')['status'],401)
        self.assertEqual(self.request('/api/order-by-code/'+original['code'],cookie=cookie)['body']['id'],oid)
        self.assertEqual(self.request('/api/orders',data,cookie=cookie,csrf=csrf)['body']['id'],oid)
        self.assertEqual(self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']['qr_url'],original['qr_url'])

    def test_code128_checksum_and_printable_width(self):
        for value in ['PCD-20261009-0001','OP-00001','PCD-20261009-12345']:
            words=code128.symbols(value)
            self.assertEqual(words[-1],106);self.assertEqual(words[-2],(words[0]+sum(i*w for i,w in enumerate(words[1:-2],1)))%103)
            self.assertLessEqual((sum(code128.widths(value))+20)*2,576)

    def test_direct_print_is_authenticated_csrf_protected_and_idempotent(self):
        cookie,csrf,_,oid=self.create()
        payload={'request_key':'printer-request-key-00001'};url='/api/orders/'+str(oid)+'/thermal-print'
        self.assertEqual(self.request(url,payload)['status'],401)
        self.assertEqual(self.request(url,payload,cookie=cookie)['status'],403)
        with patch.object(app.thermal_printing,'capability',return_value={'available':True,'queue':'MOCK-ONLY'}),patch.object(app.thermal_printing,'inspect_pdf',return_value=3200),patch.object(app.thermal_printing,'send',return_value='test-job-1') as send:
            first=self.request(url,payload,cookie=cookie,csrf=csrf);self.assertEqual(first['status'],200,first)
            repeat=self.request(url,payload,cookie=cookie,csrf=csrf);self.assertTrue(repeat['body']['duplicate']);send.assert_called_once()
            with app.connect() as c:
                self.assertEqual(c.execute('select count(*) from orders').fetchone()[0],1)
                self.assertEqual(c.execute('select state from thermal_print_jobs').fetchone()[0],'submitted')
            payload['request_key']='printer-request-key-00002'
            self.assertEqual(self.request(url,payload,cookie=cookie,csrf=csrf)['status'],200);self.assertEqual(send.call_count,2)

    def test_unconfirmed_print_is_not_automatically_sent_again(self):
        cookie,csrf,_,oid=self.create();payload={'request_key':'printer-failure-key-0001'};url='/api/orders/'+str(oid)+'/thermal-print'
        with patch.object(app.thermal_printing,'capability',return_value={'available':True,'queue':'MOCK-ONLY'}),patch.object(app.thermal_printing,'inspect_pdf',return_value=3200),patch.object(app.thermal_printing,'send',side_effect=OSError('Prueba aislada')) as send:
            self.assertEqual(self.request(url,payload,cookie=cookie,csrf=csrf)['status'],503)
            self.assertEqual(self.request(url,payload,cookie=cookie,csrf=csrf)['status'],409);send.assert_called_once()
            with app.connect() as c:self.assertEqual(c.execute('select state from thermal_print_jobs').fetchone()[0],'uncertain')
