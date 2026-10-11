import concurrent.futures
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch
import unittest
from datetime import datetime, timedelta

import test_app
import app
app.os.environ.setdefault('LOGIN_CAPTCHA','off')  # Las pruebas inician sesión sin verificación salvo que la activen.
import reception


class ReceptionTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    def setUp(self):
        test_app.SecurityTests.setUp(self)
        self.fixed=datetime(2026,10,9,20,35,14,tzinfo=reception.ECUADOR_TZ)
        self.clock=patch.object(app,'reception_now',return_value=self.fixed)
        self.clock_mock=self.clock.start()
        self.addCleanup(self.clock.stop)
    tearDown = test_app.SecurityTests.tearDown
    login = test_app.SecurityTests.login
    request = test_app.SecurityTests.request
    order_data = test_app.SecurityTests.order_data

    def test_document_algorithms(self):
        valid=['0100000017','1719304188','0100000017001','1790016919001','1760001550001']
        for value in valid:
            self.assertEqual(reception.document_error(value),'',value)
            changed=value[:7]+str((int(value[7])+1)%10)+value[8:]
            self.assertTrue(reception.document_error(changed),changed)
        for value in ['0000000000','2500000017','0100000017000','010000001700','01000000170a1','０１００００００１７','0100000017-','1234567890']:
            self.assertTrue(reception.document_error(value),value)


    def test_server_validation_and_persistence(self):
        cookie,csrf=self.login()
        for key,value in [('identification','1234567890'),('email','a@@b.com'),('parish','Incompatible'),('address','x'*501)]:
            payload=self.order_data()
            payload[key]=value;payload['name']=payload['client']
            if key=='parish':payload['parish_code']='170150'
            result=self.request('/api/client-registry',payload,cookie=cookie,csrf=csrf)
            self.assertEqual(result['status'],400,(key,result))
            self.assertIn(key,result['body']['fields'])
        for key,value in [('serial','ABC_123'),('type','inventado'),('physical_condition','')]:
            result=self.request('/api/orders',self.order_data({key:value}),cookie=cookie,csrf=csrf)
            self.assertEqual(result['status'],400,(key,result));self.assertIn(key,result['body']['fields'])
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)
        for index,category in enumerate(reception.DEVICE_TYPES,1):
            payload=self.order_data({'type':category,'brand':'Marca especializada','serial':'ABC-123',
                'color':'Gris','accessories':'Cargador','technician_notes':'Observación inicial',
                'email':'cliente@example.invalid','location_reference':'Esquina de prueba'})
            self.request('/api/client-registry',dict(payload,id=payload['client_id'],name=payload['client']),cookie=cookie,csrf=csrf)
            result=self.request('/api/orders',payload,cookie=cookie,csrf=csrf)
            self.assertEqual(result['status'],201,result)
            self.assertEqual(result['body']['code'],f'PCD-20261009-{index:04d}')
            detail=self.request('/api/orders/'+str(result['body']['id']),cookie=cookie)['body']['order']
            for key,value in payload.items():
                if key not in ('client_id','technical_access','access_confirmed','terms_accept'):self.assertEqual(detail[key],value,key)
        with app.connect() as c:self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])


    def test_retries_concurrency_and_qr(self):
        cookie,csrf=self.login()
        data=self.order_data({'request_key':'synthetic-request-key-0001'})
        def create(_):return self.request('/api/orders',data,cookie=cookie,csrf=csrf)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(create,range(4)))
        self.assertEqual(len({r['body']['id'] for r in results}),1,results)
        self.assertEqual(sorted(r['status'] for r in results),[200,200,200,201])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM clients').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
            c.execute("UPDATE daily_order_sequences SET value=9998 WHERE reception_date='20261009'")
        for code in ['PCD-20261009-9999','PCD-20261009-10000']:
            self.assertEqual(self.request('/api/orders',self.order_data(),cookie=cookie,csrf=csrf)['body']['code'],code)
        qr=self.request('/api/orders/1/qr.svg',cookie=cookie)
        self.assertEqual(qr['status'],200)
        self.assertIn(b'<svg',qr['body'])
        self.assertTrue(self.request('/api/orders/1/qr.png',cookie=cookie)['body'].startswith(b'\x89PNG'))
        for path in ['/api/reception-options','/api/orders/1','/api/orders/1/qr.svg']:
            self.assertEqual(self.request(path)['status'],401)
        self.assertEqual(self.request('/api/orders/9999',cookie=cookie)['status'],404)
        searched=self.request('/api/orders?q=PCD-20261009-0001',cookie=cookie)['body']
        self.assertEqual(searched['total'],1)


    def test_catalog_and_permissions(self):
        cookie,csrf=self.login()
        options=self.request('/api/reception-options',cookie=cookie)['body']
        self.assertEqual(len(self.request('/api/geo/provinces',cookie=cookie)['body']['rows']),24)
        self.assertEqual(options['geo_metadata']['version'],'2026')
        self.assertEqual(len(options['device_types']),8)
        self.assertIn({'name':'TUXEDO Computers','category':'computer'},options['brands'])
        self.assertIn({'name':'Epson','category':'printer'},options['brands'])
        self.request('/api/orders',self.order_data({'brand':'Nueva Marca','type':'impresora'}),cookie=cookie,csrf=csrf)
        self.request('/api/orders',self.order_data({'brand':'nueva marca','type':'impresora'}),cookie=cookie,csrf=csrf)
        options=self.request('/api/reception-options',cookie=cookie)['body']
        self.assertEqual(sum(b['name'].lower()=='nueva marca' for b in options['brands']),1)
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        self.assertEqual(self.request('/api/orders/1',cookie=cookie)['status'],200)
        self.assertEqual(self.request('/api/orders',self.order_data(),cookie=cookie,csrf=csrf)['status'],201)


    def test_production_notice(self):
        cookie,_=self.login()
        def page():return self.request('/',cookie=cookie)['body']
        with patch.dict(app.os.environ,{'APP_ENV':'production','PRODUCTION_ENABLED':'true','APP_URL':'https://taller.example.invalid','SESSION_SECURE':'true'}):
            self.assertNotIn('Esta versión es de evaluación',page())
            self.assertNotIn('Evaluación local',page())
        with patch.dict(app.os.environ,{'APP_ENV':'production','PRODUCTION_ENABLED':'false'}):
            self.assertIn('Esta versión es de evaluación',page())
        self.assertIn('Esta versión es de evaluación',page())

    def test_midnight_timezone_persistence_and_immutable_codes(self):
        cookie,csrf=self.login()
        # UTC 04:59:59 equivale a 23:59:59 del día anterior en Ecuador.
        midnight=datetime(2026,10,10,0,0,0,tzinfo=reception.ECUADOR_TZ)
        self.clock_mock.return_value=midnight-timedelta(seconds=1)
        first=self.request('/api/orders',self.order_data(),cookie=cookie,csrf=csrf)['body']
        self.assertEqual(first['code'],'PCD-20261009-0001')
        self.clock_mock.return_value=midnight
        second=self.request('/api/orders',self.order_data(),cookie=cookie,csrf=csrf)['body']
        self.assertEqual(second['code'],'PCD-20261010-0001')
        # Reejecutar la migración y abrir otra conexión simula el estado tras reinicio.
        app.migrate()
        third=self.request('/api/orders',self.order_data(),cookie=cookie,csrf=csrf)['body']
        self.assertEqual(third['code'],'PCD-20261010-0002')
        detail=self.request('/api/orders/'+str(first['id']),cookie=cookie)['body']['order']
        self.assertTrue(detail['received_at'].endswith('-05:00'))
        self.assertIn('/orders/PCD-20261009-0001',detail['qr_url'])
        self.assertNotIn(detail['identification'],detail['qr_url'])
        with app.connect() as c:
            c.execute('UPDATE orders SET created_at=0 WHERE id=?',(first['id'],))
            with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE orders SET code='CAMBIADO' WHERE id=?",(first['id'],))
            with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE orders SET qr_url='https://otro.invalid' WHERE id=?",(first['id'],))
            with self.assertRaises(sqlite3.IntegrityError):c.execute("DELETE FROM daily_order_sequences")
            with self.assertRaises(sqlite3.IntegrityError):c.execute('DELETE FROM orders WHERE id=?',(third['id'],))
        fourth=self.request('/api/orders',self.order_data(),cookie=cookie,csrf=csrf)['body']
        self.assertEqual(fourth['code'],'PCD-20261010-0003')
        self.assertEqual(self.request('/api/order-by-code/'+third['code'],cookie=cookie)['status'],200)

    def test_parallel_independent_technicians_get_distinct_numbers(self):
        cookie,csrf=self.login()
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
            uid=c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('qa2','qa2@example.invalid','Técnico 2',?,'tecnico',0)",(self.hash,)).lastrowid
            token,csrf2,_=app.make_session(c,uid)
        cookie2='pcdoctor_session='+token
        def create(index):
            user_cookie,user_csrf=(cookie,csrf) if index%2 else (cookie2,csrf2)
            return self.request('/api/orders',self.order_data({'request_key':f'parallel-unique-request-{index:04d}'}),cookie=user_cookie,csrf=user_csrf)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(create,range(12)))
        self.assertTrue(all(r['status']==201 for r in results),results)
        self.assertEqual({r['body']['code'] for r in results},{f'PCD-20261009-{i:04d}' for i in range(1,13)})

    def test_geographic_hierarchy_manual_locality_and_snapshots(self):
        cookie,csrf=self.login()
        import geography
        with app.connect() as c:
            for table,rows in [('geo_provinces',geography.PROVINCES),('geo_cantons',geography.CANTONS),('geo_parishes',geography.PARISHES)]:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],len(rows))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM geo_provinces').fetchone()[0],24)
        for province,canton,parish in [('01','0101','010101'),('10','1004','100450'),('17','1701','170150')]:
            cantons=self.request('/api/geo/cantons?province='+province,cookie=cookie)['body']['rows']
            self.assertTrue(any(r['code']==canton for r in cantons))
            self.assertTrue(all(r['province_code']==province for r in cantons))
            parishes=self.request('/api/geo/parishes?canton='+canton,cookie=cookie)['body']['rows']
            self.assertTrue(any(r['code']==parish for r in parishes))
        self.assertEqual(len(self.request('/api/geo/provinces?q=canar',cookie=cookie)['body']['rows']),1)
        payload=self.order_data({'city':'Localidad manual ficticia','locality_code':''})
        result=self.request('/api/orders',payload,cookie=cookie,csrf=csrf)
        self.assertEqual(result['status'],201,result)
        with app.connect() as c:
            c.execute("UPDATE clients SET name='Nombre editado',city='Otro sitio'")
            c.execute("UPDATE devices SET brand='Marca editada'")
        detail=self.request('/api/orders/'+str(result['body']['id']),cookie=cookie)['body']['order']
        self.assertEqual(detail['client'],payload['client'])
        self.assertEqual(detail['city'],payload['city'])
        self.assertEqual(detail['province_code'],'01')
        self.assertEqual(detail['parish_code'],'010101')
        invalid=dict(payload,parish_code='170150',name=payload['client'],id=payload['client_id'])
        self.assertEqual(self.request('/api/client-registry',invalid,cookie=cookie,csrf=csrf)['status'],400)

    def test_pdf_qr_and_private_code_lookup(self):
        cookie,csrf=self.login()
        result=self.request('/api/orders',self.order_data(),cookie=cookie,csrf=csrf)['body']
        path='/api/orders/'+str(result['id'])+'/receipt.pdf'
        pdf=self.request(path,cookie=cookie)
        self.assertEqual(pdf['status'],200)
        self.assertTrue(pdf['body'].startswith(b'%PDF-'))
        self.assertIn(result['code'].encode(),pdf['body'])
        self.assertEqual(self.request(path)['status'],401)
        lookup='/api/order-by-code/'+result['code']
        self.assertEqual(self.request(lookup,cookie=cookie)['body']['id'],result['id'])
        self.assertEqual(self.request(lookup)['status'],401)
        self.assertEqual(self.request('/orders/'+result['code'])['status'],200)
        self.assertNotIn('Cliente ficticio',self.request('/orders/'+result['code'])['body'])


class MigrationTests(unittest.TestCase):
    def test_existing_records_are_preserved_and_backed_up(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Path(directory)/'legacy.sqlite3'
            c=sqlite3.connect(db)
            c.executescript((app.ROOT/'migrations/001_initial.sql').read_text())
            c.execute('CREATE TABLE migrations (name TEXT PRIMARY KEY)')
            c.execute("INSERT INTO migrations VALUES ('001_initial.sql')")
            c.execute("INSERT INTO users VALUES (1,'legacy','legacy@example.invalid','Legado','hash','administrador',1,0)")
            c.execute("INSERT INTO clients VALUES (1,'Legado',NULL,NULL)")
            c.execute("INSERT INTO devices VALUES (1,1,'escritorio','Marca previa','Modelo previo','SER-1')")
            c.execute("INSERT INTO orders VALUES (1,1,'pendiente','Falla previa',1,0)")
            c.commit();c.close()
            with patch.multiple(app,DATA=Path(directory),DB=db):
                app.migrate();app.migrate()
                with app.connect() as c:
                    self.assertEqual(c.execute('SELECT problem FROM orders WHERE id=1').fetchone()[0],'Falla previa')
                    self.assertEqual(c.execute('SELECT category FROM devices WHERE id=1').fetchone()[0],'escritorio')
                    self.assertEqual(c.execute('SELECT code FROM orders WHERE id=1').fetchone()[0],'OP-00001')
                    self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(len(list(Path(directory).glob('backup-*.sqlite3'))),len(list((app.ROOT/'migrations').glob('*.sql')))-1)
