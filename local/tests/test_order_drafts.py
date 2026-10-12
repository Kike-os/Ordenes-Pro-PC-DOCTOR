"""Borradores de Nueva orden guardados en el servidor: uno por usuario, sin crear órdenes y con control de sesiones."""
import json,unittest
import test_app
import app


class OrderDraftTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request

    def test_draft_is_saved_updated_recovered_and_discarded_without_creating_orders(self):
        cookie,csrf=self.login();save=lambda data,**extra:self.request('/api/order-draft',dict({'data':json.dumps(data)},**extra),cookie=cookie,csrf=csrf)
        self.assertEqual(self.request('/api/order-draft')['status'],401)
        self.assertEqual(self.request('/api/order-draft',{'data':'{}'},cookie=cookie)['status'],403)
        self.assertIsNone(self.request('/api/order-draft',cookie=cookie)['body']['draft'])
        # Un formulario incompleto se guarda; las confirmaciones del cliente y las claves nunca se conservan.
        first=save({'fields':{'brand':'HP','problem':'','technical_access':'authorized','device_password':'1234'},'checks':{'access_operating_system':True,'access_confirmed':True},'terms_accept':True,'step':2,'client':None,'summary':'HP'})
        self.assertEqual(first['status'],201);draft=first['body']['draft']
        self.assertEqual((draft['revision'],draft['data']['fields'],draft['data']['checks'],'terms_accept' in draft['data'],draft['data']['step']),(1,{'brand':'HP','problem':'','technical_access':'authorized'},{'access_operating_system':True},False,2))
        # Guardar otra vez actualiza el mismo borrador: no hay duplicados.
        second=save({'fields':{'brand':'HP','model':'ProBook'},'step':3},revision='1')
        self.assertEqual((second['status'],second['body']['draft']['id'],second['body']['draft']['revision']),(200,draft['id'],2))
        read=self.request('/api/order-draft',cookie=cookie)['body']['draft']
        self.assertEqual((read['data']['fields']['model'],read['data']['step'],read['created_at']),('ProBook',3,draft['created_at']))
        # Otra sesión con una revisión antigua no pisa el borrador más reciente, salvo petición expresa.
        stale=save({'fields':{'brand':'Dell'}},revision='1')
        self.assertEqual((stale['status'],stale['body']['conflict'],stale['body']['revision']),(409,True,2))
        self.assertEqual(self.request('/api/order-draft',cookie=cookie)['body']['draft']['data']['fields']['brand'],'HP')
        self.assertEqual(save({'fields':{'brand':'Dell'}},revision='1',force=True)['body']['draft']['revision'],3)
        # Datos no válidos o excesivos se rechazan con su motivo.
        self.assertEqual(self.request('/api/order-draft',{'data':'no-json'},cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request('/api/order-draft',{'data':'[1,2]'},cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(save({'fields':{'x':'a'*70000}})['status'],400)
        with app.connect() as c:
            self.assertEqual((c.execute('SELECT COUNT(*) FROM order_drafts').fetchone()[0],c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]),(1,0))
            # El borrador es de su propietario: otro usuario no lo ve.
            other=c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('otro','otro@example.invalid','Otra persona',?,'tecnico',1)",(self.hash,)).lastrowid
        peer=self.request('/api/login',{'login':'otro','password':'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        self.assertIsNone(self.request('/api/order-draft',cookie=peer)['body']['draft'])
        # Descartar vacía el borrador y deja constancia; no toca nada más. Después se puede empezar uno nuevo.
        gone=self.request('/api/order-draft',{'action':'discard'},cookie=cookie,csrf=csrf)['body']
        self.assertEqual((gone['discarded'],self.request('/api/order-draft',cookie=cookie)['body']['draft'],self.request('/api/order-draft',{'action':'discard'},cookie=cookie,csrf=csrf)['body']['discarded']),(True,None,False))
        again=save({'fields':{'brand':'Lenovo'}})
        self.assertEqual((again['status'],again['body']['draft']['data']['fields']),(200,{'brand':'Lenovo'}))
        with app.connect() as c:self.assertEqual((c.execute('SELECT COUNT(*) FROM order_drafts').fetchone()[0],c.execute("SELECT COUNT(*) FROM audit WHERE action='order_draft_discarded'").fetchone()[0]),(1,1))
