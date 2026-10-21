"""Inventario y credenciales: método de activación por producto (clave, cuenta, mixta, archivo), archivo de licencia cifrado, registro
por filas y ADI Duplicate Protection Pro (rojo bloquea, ámbar exige justificación, la contraseña sola nunca se marca, sin credenciales en
las respuestas), bloqueo de una segunda entrega y revisión del inventario sin modificarlo. Base temporal y datos ficticios."""
import base64
import json
import unittest
import test_app,test_licenses
import app,licenses

LIC_FILE=b'<?xml version="1.0"?><license><id>FICT-0001</id><owner>Prueba</owner></license>'
b64=lambda raw:base64.b64encode(raw).decode()


class LicenseMethodTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data
    _b=vars(test_licenses.LicenseProTests);admin=_b['admin'];new_product=_b['new_product'];client_id=_b['client_id'];today=_b['today']

    def product(self,method,name,**extra):
        self.admin() if not hasattr(self,'post') else None
        return self.new_product(name=name,activation_method=method,**extra)['product_id']

    def secrets_of(self,unit):
        with app.connect() as c:return licenses.unseal(c.execute('SELECT secret FROM license_units WHERE id=?',(unit,)).fetchone()[0])

    def units_of(self,pid):
        with app.connect() as c:return [r[0] for r in c.execute('SELECT id FROM license_units WHERE product_id=? ORDER BY id',(pid,))]

    def events(self,name):
        with app.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM license_events WHERE event=? ORDER BY id',(name,))]

    def test_method_is_stored_and_only_its_fields_are_required_and_saved(self):
        self.admin()
        pid=self.product('cuenta','Microsoft 365 ficticio',line='microsoft',key='CLAVE-QUE-NO-APLICA',username='cuenta1@example.invalid',password='Uno-Ficticio-1')
        listed={p['id']:p for p in self.get('/api/licenses')['body']['products']}[pid]
        self.assertEqual((listed['activation_method'],listed['activation_label']),('cuenta','Usuario y contraseña'))
        self.assertEqual(self.secrets_of(self.units_of(pid)[0]),{'username':'cuenta1@example.invalid','password':'Uno-Ficticio-1'})  # la clave no aplica: no se guarda
        missing=self.post('/api/licenses/units',product_id=str(pid),username='cuenta2@example.invalid')
        self.assertEqual((missing['status'],list(missing['body']['fields'])),(400,['password']))
        mixed=self.product('mixta','Suite mixta ficticia',key='MIXTA-FICT-0001',username='mixta@example.invalid',password='Mixta-Ficticia-1')
        self.assertEqual(self.post('/api/licenses/units',product_id=str(mixed),key='MIXTA-FICT-0002')['status'],400)
        # Cambiar el método al agregar stock: queda en el producto y en el historial; las licencias registradas conservan sus datos.
        changed=self.post('/api/licenses/units',product_id=str(pid),activation_method='mixta',key='M365-FICT-0002',username='cuenta2@example.invalid',password='Dos-Ficticio-2')
        self.assertEqual(changed['status'],201,changed['body'])
        self.assertEqual(self.secrets_of(self.units_of(pid)[0]),{'username':'cuenta1@example.invalid','password':'Uno-Ficticio-1'})
        self.assertIn('antes: Usuario y contraseña',self.events('metodo_activacion')[-1]['detail'])

    def test_license_file_is_validated_encrypted_revealed_by_name_and_delivered_once(self):
        self.admin()
        bad=[('instalador.exe',b'MZ\x90\x00'),('licencia.lic',b'MZ\x90\x00programa'),('licencia.zip',b'PK\x03\x04'),('licencia.txt',b'\xff\xfe\x00binario'),('licencia.lic',b'x'*(licenses.FILE_LIMIT+1))]
        for name,raw in bad:
            made=self.post('/api/licenses/new',name='Autodesk ficticio '+name,brand='Autodesk',line='utilitarios',model='suscripcion',duration='anual',validity_mode='activacion',price='99',activation_method='archivo',file=b64(raw),file_name=name)
            self.assertEqual((made['status'],list(made['body'].get('fields',{}))),(400,['file']),name)
        self.assertEqual(self.post('/api/licenses/new',name='Sin archivo ficticio',brand='X',line='utilitarios',model='suscripcion',duration='anual',validity_mode='activacion',price='9',activation_method='archivo')['status'],400)
        made=self.post('/api/licenses/new',name='Autodesk ficticio',brand='Autodesk',line='utilitarios',model='suscripcion',duration='anual',validity_mode='activacion',price='99',activation_method='archivo',
                       file=b64(LIC_FILE),file_name='licencia ficticia.xml',license_code='AD-FICT-1')
        self.assertEqual(made['status'],201,made['body']);unit=made['body']['unit_id']
        with app.connect() as c:stored=dict(c.execute('SELECT * FROM license_files WHERE unit_id=?',(unit,)).fetchone())
        self.assertNotIn('FICT-0001',stored['sealed']);self.assertEqual((stored['name'],stored['mime'],stored['size']),('licencia ficticia.xml','application/xml',len(LIC_FILE)))
        shown=self.post('/api/licenses/units/%d'%unit,action='reveal')['body']['credentials']
        self.assertEqual([(x['key'],x['value']) for x in shown],[('license_code','AD-FICT-1'),('file','licencia ficticia.xml')])
        got=self.post('/api/licenses/units/%d'%unit,action='file')['body'];self.assertEqual(base64.b64decode(got['data']),LIC_FILE)
        self.assertEqual(len(self.events('archivo_descargado')),1)
        # El mismo archivo otra vez: es la misma licencia (rojo).
        again=self.post('/api/licenses/units',product_id=str(made['body']['product_id']),file=b64(LIC_FILE),file_name='copia.xml')
        self.assertEqual(again['status'],409);self.assertEqual(again['body']['duplicates']['level'],'red')
        # Entrega: la página privada del cliente ofrece el archivo una sola vez, desde la misma página.
        client=self.client_id();sale=self.post('/api/licenses/sales',client_id=str(client),items=[{'product_id':made['body']['product_id'],'quantity':1}],deliver=True,accept_balance=True)
        self.assertEqual(sale['status'],201,sale['body'])
        delivery=self.get('/api/licenses/sales/%d'%sale['body']['sale'])['body']['delivery_id']
        with app.connect() as c:card=licenses.card(c,delivery,private=True,now=app.reception_now())
        import license_pages
        page=license_pages.card_page('t0ken',card)
        self.assertIn('download="licencia ficticia.xml"',page);self.assertIn(b64(LIC_FILE),page)
        self.assertEqual(card['items'][0]['method_label'],'Licencia con archivo del fabricante')

    def test_rows_are_validated_one_by_one_and_repeated_keys_in_the_list_are_red(self):
        self.admin();pid=self.product('clave','Kaspersky ficticio',key='KASP-FICT-0001')
        rows=[{'key':'KASP-FICT-0002'},{'key':''},{'key':'KASP-FICT-0004'}]
        bad=self.post('/api/licenses/units/bulk',product_id=str(pid),rows=rows)
        self.assertEqual((bad['status'],list(bad['body']['fields'])),(400,['row-2-key']));self.assertTrue(bad['body']['error'].startswith('Fila 2:'))
        rows[1]['key']='KASP-FICT-0002'
        dup=self.post('/api/licenses/units/bulk',product_id=str(pid),rows=rows)
        self.assertEqual(dup['status'],400);entry=dup['body']['duplicates']['entries'][1]
        self.assertEqual((entry['level'],entry['fields']['key']['rows']),('red',[1]))
        rows[1]['key']='KASP-FICT-0003'
        ok=self.post('/api/licenses/units/bulk',product_id=str(pid),rows=rows);self.assertEqual((ok['status'],ok['body']['count']),(201,3))
        self.assertEqual(len(self.units_of(pid)),4)

    def test_duplicate_levels_reason_and_no_secrets_in_responses(self):
        self.admin()
        pid=self.product('cuenta','Office ficticio',line='ofimatica',key='',username='compartida@example.invalid',password='Secreta-Ficticia-1',license_code='COD-1')
        check=lambda **row:self.post('/api/licenses/check',product_id=str(pid),rows=[row])['body']
        # Serial y archivo: rojo. Cuenta: ámbar. Misma cuenta y contraseña: ámbar reforzado. Contraseña sola: nunca se marca.
        same_account=check(username='Compartida@Example.invalid',password='Secreta-Ficticia-1')
        self.assertEqual((same_account['level'],same_account['entries'][0]['fields']['account']['level']),('amber','amber'))
        self.assertNotIn('Secreta-Ficticia-1',json.dumps(same_account));self.assertNotIn('compartida@example',json.dumps(same_account).lower())
        self.assertEqual(check(username='otra@example.invalid',password='Secreta-Ficticia-1')['level'],'green')
        self.assertEqual(check(username='otra@example.invalid',password='x',license_code='cod 1')['entries'][0]['fields']['license_code']['level'],'amber')
        # Guardar sin justificación: 409 con el detalle; con justificación: se registra y queda en el historial (sin la contraseña).
        blocked=self.post('/api/licenses/units',product_id=str(pid),username='compartida@example.invalid',password='Otra-Ficticia-2')
        self.assertEqual((blocked['status'],blocked['body']['reason_required']),(409,True));self.assertIn('duplicate_reason',blocked['body']['fields'])
        short=self.post('/api/licenses/units',product_id=str(pid),username='compartida@example.invalid',password='Otra-Ficticia-2',duplicate_reason='corto')
        self.assertEqual(short['status'],409)
        made=self.post('/api/licenses/units',product_id=str(pid),username='compartida@example.invalid',password='Otra-Ficticia-2',duplicate_reason='La cuenta del cliente tiene dos suscripciones compradas.')
        self.assertEqual(made['status'],201,made['body'])
        logged=self.events('duplicado_autorizado')[-1];self.assertIn('Usuario o correo de activación con LIC-',logged['detail']);self.assertIn('dos suscripciones',logged['detail'])
        self.assertNotIn('Otra-Ficticia-2',logged['detail']);self.assertNotIn('compartida@',logged['detail']);self.assertTrue(logged['actor_id'])
        self.assertEqual(len(self.units_of(pid)),2)
        # Un serial repetido es rojo y no se puede saltar ni con justificación.
        keyed=self.product('clave','Windows 11 Pro ficticio',line='sistema',key='WIN11-FICT-0001')
        red=self.post('/api/licenses/units',product_id=str(keyed),key='win11 fict 0001',duplicate_reason='Quiero registrarla otra vez de todas formas.')
        self.assertEqual((red['status'],red['body']['duplicates']['level']),(409,'red'));self.assertIn('ya se encuentra registrado',red['body']['error'])
        self.assertEqual(len(self.units_of(keyed)),1)
        # Clave compartida: verde mientras haya puestos.
        shared=self.product('clave','Clave compartida ficticia',key='SHARE-FICT-0001',shared_seats='3')
        self.assertEqual(self.post('/api/licenses/check',product_id=str(shared),rows=[{'key':'SHARE-FICT-0001'}])['body']['level'],'green')

    def test_second_delivery_of_the_same_serial_is_blocked_even_for_historical_duplicates(self):
        self.admin();pid=self.product('clave','Avast ficticio',key='AVAST-FICT-0001');client=self.client_id()
        # Duplicado histórico (anterior a la protección): otra licencia con el mismo serial y otra huella.
        with app.connect() as c:
            row=dict(c.execute('SELECT * FROM license_units WHERE product_id=?',(pid,)).fetchone())
            c.execute("INSERT INTO license_units(product_id,batch_id,kind,secret,fingerprint,seat,status,created_at,updated_at) VALUES (?,?,?,?,?,1,'disponible',?,?)",(pid,row['batch_id'],row['kind'],row['secret'],'historico-'+row['fingerprint'][:20],row['created_at'],row['created_at']))
        first=self.post('/api/licenses/sales',client_id=str(client),items=[{'product_id':pid,'quantity':1}],deliver=True,accept_balance=True);self.assertEqual(first['status'],201,first['body'])
        second=self.post('/api/licenses/sales',client_id=str(client),items=[{'product_id':pid,'quantity':1}],deliver=True,accept_balance=True)
        self.assertEqual(second['status'],409);self.assertIn('ya fue entregado',second['body']['error'])
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM license_units WHERE product_id=? AND status='entregada'",(pid,)).fetchone()[0],1)
        # El informe lo detecta sin modificar nada ni mostrar la clave.
        before=self.units_snapshot()
        report=self.get('/api/licenses/duplicates')['body']
        self.assertEqual(len(report['serials']),1);self.assertEqual({i['product'] for i in report['serials'][0]},{'Avast ficticio'})
        self.assertNotIn('AVAST-FICT',json.dumps(report));self.assertEqual(self.units_snapshot(),before)

    def units_snapshot(self):
        with app.connect() as c:return [tuple(r) for r in c.execute('SELECT id,status,secret,fingerprint,client_id FROM license_units ORDER BY id')]

    def test_edit_updates_only_typed_fields_and_checks_duplicates(self):
        self.admin();pid=self.product('cuenta','Cuenta editable ficticia',key='',username='editar@example.invalid',password='Antes-Ficticia-1',license_code='COD-ED')
        unit=self.units_of(pid)[0]
        self.assertEqual(self.post('/api/licenses/units/%d'%unit,action='edit',password='Despues-Ficticia-2')['status'],200)
        self.assertEqual(self.secrets_of(unit),{'username':'editar@example.invalid','password':'Despues-Ficticia-2','license_code':'COD-ED'})
        other=self.post('/api/licenses/units',product_id=str(pid),username='otro@example.invalid',password='Otro-Ficticio-3')['body']['id']
        clash=self.post('/api/licenses/units/%d'%other,action='edit',username='editar@example.invalid')
        self.assertEqual(clash['status'],409);self.assertTrue(clash['body']['reason_required'])

    def test_legacy_products_without_method_keep_working(self):
        self.admin();made=self.new_product(name='Producto anterior ficticio',key='OLD-FICT-0001')
        with app.connect() as c:c.execute("UPDATE license_products SET activation_method='' WHERE item_id=?",(made['product_id'],))
        self.assertEqual(self.post('/api/licenses/units/bulk',product_id=str(made['product_id']),lines='OLD-FICT-0002\nOLD-FICT-0003')['status'],201)
        listed={p['id']:p for p in self.get('/api/licenses')['body']['products']}[made['product_id']]
        self.assertEqual((listed['activation_method'],listed['activation_label']),('','Según los datos guardados'))


if __name__=='__main__':unittest.main()
