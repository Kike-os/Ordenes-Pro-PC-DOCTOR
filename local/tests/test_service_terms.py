import json
import sqlite3
from datetime import datetime,timedelta
from unittest.mock import patch
import unittest
import test_app
import app
app.os.environ.setdefault('LOGIN_CAPTCHA','off')  # Las pruebas inician sesión sin verificación salvo que la activen.
import reception
import service_terms


class ServiceTermsTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data

    def publish(self,cookie,csrf,version='TEST-1',effective='2020-01-01'):
        payload={'version':version,'effective_date':effective,'full_text':'TEXTO FICTICIO DE PRUEBA. Recepción, información y revisión técnica.\n\nPárrafo de prueba: cédula, número, garantía, ñ y acentos.\n\n<script>alert(1)</script> no es código ejecutable.','compact_text':'TEXTO FICTICIO DE PRUEBA. Recepción y revisión.\n\nConsultar la versión completa.','approved':True}
        result=self.request('/api/conditions',payload,cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],201,result)
        return result['body']['id']

    def test_acceptance_is_required_and_transactional(self):
        cookie,csrf=self.login();tid=self.publish(cookie,csrf)
        payload=self.order_data({'request_key':'terms-test-request-key-001','terms_document_id':tid})
        for updates,status in [({},400),({'terms_accept':'on'},400),({'terms_document_id':'stale','terms_accept':True},409)]:
            result=self.request('/api/orders',{**payload,**updates},cookie=cookie,csrf=csrf)
            self.assertEqual(result['status'],status,result)
            self.assertIn('terms_accept',result['body']['fields'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM clients').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM daily_order_sequences').fetchone()[0],0)
        payload['terms_accept']=True
        result=self.request('/api/orders',payload,cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],201,result);oid=result['body']['id']
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
        self.assertEqual(order['terms']['id'],tid);self.assertEqual(order['terms_acceptor'],payload['client'])
        self.assertEqual(order['terms_mechanism'],'checkbox_presencial');self.assertEqual(order['terms_actor_id'],self.uid)
        self.assertEqual(order['terms_accepted_at'],order['received_at']);self.assertEqual(len(order['terms_acceptance_id']),32)
        self.assertEqual(self.request('/api/orders',payload,cookie=cookie,csrf=csrf)['body']['id'],oid)
        for suffix in ['/receipt.pdf','/thermal.pdf']:
            r=self.request('/api/orders/'+str(oid)+suffix,cookie=cookie);self.assertEqual(r['status'],200);self.assertTrue(r['body'].startswith(b'%PDF'))
        self.assertEqual(self.request('/api/orders/'+str(oid)+'/thermal.pdf')['status'],401)

    def test_public_version_has_no_customer_data_and_is_immutable(self):
        cookie,csrf=self.login();tid=self.publish(cookie,csrf)
        result=self.request('/conditions/'+tid)
        self.assertEqual(result['status'],200);self.assertNotIn('<script>',result['body']);self.assertIn('&lt;script&gt;',result['body'])
        self.assertNotIn('0100000017',result['body']);self.assertNotIn('Cliente ficticio',result['body'])
        with app.connect() as c:
            for statement in ['UPDATE service_terms SET full_text=\'cambio\' WHERE id=?','DELETE FROM service_terms WHERE id=?']:
                with self.assertRaises(sqlite3.IntegrityError):c.execute(statement,(tid,))
        duplicate=self.request('/api/conditions',{'version':'TEST-1','effective_date':'2020-01-01','full_text':'Aprobado de prueba','compact_text':'Prueba','approved':True},cookie=cookie,csrf=csrf)
        self.assertEqual(duplicate['status'],400)

    def test_historical_version_and_future_effective_date(self):
        cookie,csrf=self.login();first=self.publish(cookie,csrf)
        initial=self.request('/api/orders',self.order_data({'terms_document_id':first,'terms_accept':True}),cookie=cookie,csrf=csrf)
        self.assertEqual(initial['status'],201);oid=initial['body']['id']
        second=self.publish(cookie,csrf,'TEST-2','2021-01-01');self.publish(cookie,csrf,'TEST-FUTURE','2099-01-01')
        self.assertEqual(self.request('/api/conditions/current',cookie=cookie)['body']['terms']['id'],second)
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];self.assertEqual(order['terms']['id'],first)
        original=order['qr_url'];app.migrate()
        restored=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];self.assertEqual(restored['qr_url'],original);self.assertEqual(restored['terms_acceptance_id'],order['terms_acceptance_id'])
        with app.connect() as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute('UPDATE orders SET terms_accepted_at=? WHERE id=?',('2099-01-01',oid))

    def test_no_retroactive_acceptance_and_no_unconfigured_production(self):
        cookie,csrf=self.login()
        # Con la exigencia activada y sin condiciones publicadas, no se registra.
        with patch.dict(app.os.environ,{'REQUIRE_SERVICE_TERMS':'true'}):
            self.assertTrue(self.request('/api/conditions/current',cookie=cookie)['body']['required'])
            self.assertEqual(self.request('/api/orders',self.order_data({'request_key':'terms-required-order-0001'}),cookie=cookie,csrf=csrf)['status'],503)
        # Sin exigencia: la orden se registra con su número y QR, y no se fabrica ninguna aceptación (ni aunque el navegador la envíe).
        current=self.request('/api/conditions/current',cookie=cookie)['body'];self.assertEqual((current['terms'],current['required']),(None,False))
        result=self.request('/api/orders',self.order_data({'terms_accept':True,'terms_document_id':'inventado','request_key':'terms-free-order-000001'}),cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],201)
        free=self.request('/api/orders/'+str(result['body']['id']),cookie=cookie)['body']['order']
        self.assertEqual((free['terms'],free['terms_acceptance_id'],free['code']==result['body']['code'],bool(free['qr_url'])),(None,None,True,True))
        # Sus documentos se generan igual, sin texto ni evidencia de condiciones.
        for doc in ('/api/orders/%d/thermal.pdf','/api/orders/%d/tracking-qr.png'):self.assertEqual(self.request(doc%result['body']['id'],cookie=cookie)['status'],200)
        with app.connect() as c:
            did=c.execute("INSERT INTO devices(client_id,type,category) VALUES (1,'portatil','portatil')").lastrowid
            oid=c.execute("INSERT INTO orders(device_id,status,problem,created_by,created_at,code,received_at) VALUES (?,'pendiente','Histórica',?,0,'OP-00001','2020-01-01T10:00:00-05:00')",(did,self.uid)).lastrowid
        self.publish(cookie,csrf)
        old=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order'];self.assertIsNone(old['terms']);self.assertIsNone(old['terms_acceptance_id'])
        with patch.dict(app.os.environ,{'REQUIRE_SERVICE_TERMS':'true'}):
            with patch.object(app,'reception_now',return_value=datetime(2019,1,1,tzinfo=reception.ECUADOR_TZ)):
                r=self.request('/api/orders',self.order_data(),cookie=cookie,csrf=csrf);self.assertEqual(r['status'],503)

    def test_publication_permission_and_printable_characters(self):
        cookie,csrf=self.login()
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        self.assertEqual(self.request('/api/conditions',{'approved':True},cookie=cookie,csrf=csrf)['status'],403)
        _,errors=service_terms.validate_publication({'version':'TEST-1','effective_date':'2026-10-09','full_text':'Texto 😊','compact_text':'Prueba','approved':True})
        self.assertIn('full_text',errors)
        _,errors=service_terms.validate_publication({'version':'TEST-1','effective_date':'fecha incorrecta','full_text':'Prueba','compact_text':'Prueba','approved':False})
        self.assertIn('approved',errors);self.assertIn('effective_date',errors)
