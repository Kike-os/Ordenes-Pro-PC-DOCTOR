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
        # PDF oficial de la versión publicada y PDF del borrador: mismo contenido público, sin sesión para el oficial.
        official=self.request('/conditions/'+tid+'.pdf');self.assertEqual(official['status'],200);self.assertTrue(official['body'].startswith(b'%PDF'))
        self.assertEqual(self.request('/conditions/'+'0'*32+'.pdf')['status'],404)
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
        # Al publicarse después una versión oficial, la orden la ofrece para consulta pero sigue sin aceptación atribuida.
        self.assertIsNone(free['terms_current']);self.publish(cookie,csrf,version='TEST-POST')
        later=self.request('/api/orders/'+str(result['body']['id']),cookie=cookie)['body']['order']
        self.assertEqual((later['terms'],later['terms_acceptance_id'],later['terms_current']['version']),(None,None,'TEST-POST'))
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


class TermsWorkflowTests(unittest.TestCase):
    """Numeración automática, borrador pendiente, comparación e historial de cambios."""
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    FULL='1. Diagnóstico\nRevisiones acordadas con el cliente.\n\n2. Garantía\nNoventa días sobre el servicio realizado.\n\n3. Entrega\nEl cliente verifica el equipo al retirarlo.'
    COMPACT='1. Diagnóstico acordado.\n\n2. Garantía de noventa días.'

    def test_automatic_numbering_draft_diff_and_history(self):
        cookie,csrf=self.login();now=app.reception_now();prefix='%d.%d.'%(now.year,now.month)
        post=lambda path,body:self.request(path,body,cookie=cookie,csrf=csrf)
        # Sin aprobación expresa no se publica, aunque el número sea automático.
        self.assertEqual(post('/api/conditions',{'full_text':self.FULL,'compact_text':self.COMPACT})['status'],400)
        first=post('/api/conditions',{'full_text':self.FULL,'compact_text':self.COMPACT,'approved':True})
        self.assertEqual((first['status'],first['body']['version']),(201,prefix+'1'))
        # Mismo texto: no hay nada que publicar.
        self.assertEqual(post('/api/conditions',{'full_text':self.FULL,'compact_text':self.COMPACT,'approved':True})['status'],400)
        changed=self.FULL.replace('Noventa días','Ciento veinte días')+'\n\n4. Almacenamiento\nSe informará cualquier cargo antes de aplicarlo.'
        # Guardar un borrador no publica nada; queda pendiente y se avisa a administración.
        self.assertEqual(post('/api/conditions/draft',{'full_text':changed,'compact_text':self.COMPACT,'note':'Amplía la garantía'})['status'],200)
        view=self.request('/api/conditions',cookie=cookie)['body']
        self.assertEqual((view['current']['version'],view['next_version'],len(view['rows'])),(prefix+'1',prefix+'2',2))  # la base de pruebas trae además una versión de ejemplo
        self.assertEqual((view['draft']['note'],view['draft']['diff']['stats'],view['draft']['compact_changed']),('Amplía la garantía',{'added':1,'removed':0,'changed':1},False))
        block=[item for item in view['draft']['diff']['blocks'] if item['kind']=='changed'][0]
        self.assertIn(('removed','Noventa'),[tuple(word) for word in block['words']]);self.assertIn('Ciento',''.join(text for kind,text in block['words'] if kind=='added'))
        alerts=[item for item in self.request('/api/notifications',cookie=cookie)['body']['items'] if item['key'].startswith('alert:terms-draft')]
        self.assertEqual((len(alerts),alerts[0]['href']),(1,'#settings?tab=terms'))
        live=post('/api/conditions/compare',{'full_text':self.FULL+'\n\n9. Nuevo\nTexto.','compact_text':'otro'})['body']
        self.assertEqual((live['diff']['stats']['added'],live['compact_changed'],live['current']),(1,True,prefix+'1'))
        # Una orden registrada ahora queda ligada a la versión vigente; publicar después no la altera.
        oid=post('/api/orders',self.order_data({'request_key':'terms-flow-order-0001','terms_accept':True,'terms_document_id':view['current']['id']}))['body']['id']
        second=post('/api/conditions',{'full_text':changed,'compact_text':self.COMPACT,'approved':True,'note':'Amplía la garantía'})
        self.assertEqual((second['status'],second['body']['version']),(201,prefix+'2'))
        after=self.request('/api/conditions',cookie=cookie)['body']
        self.assertIsNone(after['draft']);self.assertEqual([row['version'] for row in after['rows']],[prefix+'2',prefix+'1','FIXTURE-ONLY']);self.assertEqual(after['next_version'],prefix+'3')
        newest=after['rows'][0];self.assertEqual((newest['changes'],newest['note'],newest['current'],bool(newest['publisher'])),({'added':1,'removed':0,'changed':1},'Amplía la garantía',True,True))
        self.assertFalse([item for item in self.request('/api/notifications',cookie=cookie)['body']['items'] if item['key'].startswith('alert:terms-draft')])
        order=self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']
        self.assertEqual((order['terms']['version'],order['terms_current']['version']),(prefix+'1',prefix+'2'))
        diff=self.request('/api/conditions/compare/'+newest['id'],cookie=cookie)['body']
        self.assertEqual((diff['version'],diff['previous'],diff['diff']['stats']['changed']),(prefix+'2',prefix+'1',1))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM service_terms').fetchone()[0],3)
            self.assertEqual(c.execute("SELECT full_text FROM service_terms WHERE version=?",(prefix+'1',)).fetchone()[0],self.FULL)
            c.execute("UPDATE users SET role='tecnico'")
        # Un técnico puede preparar un borrador, pero no publicar, descartar ni ver el historial de publicación.
        self.assertEqual(post('/api/conditions/draft',{'full_text':changed+'\n\n5. Otro\nTexto.','compact_text':self.COMPACT})['status'],200)
        self.assertEqual(post('/api/conditions',{'full_text':changed+'\n\n5. Otro\nTexto.','compact_text':self.COMPACT,'approved':True})['status'],403)
        self.assertEqual(post('/api/conditions/draft/discard',{'ok':True})['status'],403);self.assertEqual(self.request('/api/conditions',cookie=cookie)['status'],403)
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM service_terms').fetchone()[0],3)
