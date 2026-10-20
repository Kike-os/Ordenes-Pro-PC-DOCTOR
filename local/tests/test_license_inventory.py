"""Inventario profesional de Licencias Pro: la activación no se inventa en inventario, revisión de datos inconsistentes (sin
corregirlos), umbral configurable de «Por vencer», vigencia según la duración del producto, filtro por tipo de fecha y exportación sin
claves. Datos ficticios en una base temporal."""
import unittest
from datetime import timedelta
import test_app,test_licenses
import app,licenses
from test_licenses import SERIAL


class LicenseInventoryTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request
    login=test_app.SecurityTests.login
    order_data=test_app.SecurityTests.order_data
    _base=vars(test_licenses.LicenseProTests)
    admin=_base['admin'];new_product=_base['new_product'];client_id=_base['client_id'];unit=_base['unit'];today=_base['today']

    def test_stock_activation_is_not_invented_and_inconsistencies_are_flagged_not_fixed(self):
        self.admin();today=self.today().isoformat()
        bad=self.post('/api/licenses/new',name='Con activación inventada',line='antivirus',duration='anual',price='20',key='INV-KEY-00001',activated_at=today)
        self.assertEqual(bad['status'],400);self.assertIn('activated_at',bad['body']['fields'])
        made=self.new_product(key='INV-KEY-00002');uid=made['unit_id']
        with app.connect() as c:
            # Dato histórico inconsistente (como los registrados antes de esta corrección).
            c.execute("UPDATE license_units SET activated=1,activated_at=?,expires_at=? WHERE id=?",(today,(self.today()+timedelta(days=365)).isoformat(),uid))
            before=dict(c.execute('SELECT * FROM license_units WHERE id=?',(uid,)).fetchone())
        rows=self.get('/api/licenses/units?state=revision')['body']['rows'];self.assertEqual([r['id'] for r in rows],[uid]);self.assertTrue(rows[0]['issues'])
        self.assertEqual(self.get('/api/licenses')['body']['dashboard']['revision'],1)
        self.assertEqual(self.unit(uid),before)  # consultar no corrige nada
        # Editar: no se puede guardar una activación en inventario; dejarla vacía la retira y queda en el historial.
        self.assertEqual(self.post('/api/licenses/units/%d'%uid,action='edit',activated_at=today)['status'],400)
        self.assertEqual(self.post('/api/licenses/units/%d'%uid,action='edit',activated_at='')['status'],200)
        fixed=self.unit(uid);self.assertEqual((fixed['activated'],fixed['activated_at'],fixed['expires_at']),(0,'',''))
        self.assertIn('activación retirada',self.get('/api/licenses/history?unit=%d'%uid)['body']['rows'][0]['detail'])
        self.assertEqual(self.get('/api/licenses/units?state=revision')['body']['rows'],[])

    def test_soon_threshold_term_days_date_field_and_export_without_keys(self):
        self.admin();client=self.client_id()
        anual=self.new_product(key=SERIAL)['product_id'];mensual=self.new_product(name='Mensual ficticio',key='MENS-KEY-0001',duration='mensual')['product_id']
        start=(self.today()-timedelta(days=320)).isoformat()
        for pid in (anual,mensual):
            done=self.post('/api/licenses/sales',client_id=str(client),items=[{'product_id':str(pid),'quantity':'1'}],deliver=True,accept_balance=True,activated=True,activated_at=start if pid==anual else self.today().isoformat())
            self.assertEqual(done['status'],201,done['body'])
        rows={r['product_id']:r for r in self.get('/api/licenses/units')['body']['rows']}
        self.assertIn(rows[anual]['term_days'],(365,366));self.assertIn(rows[mensual]['term_days'],(28,29,30,31))
        days=rows[anual]['days_left'];self.assertTrue(30<days<=60,days);self.assertEqual(rows[anual]['state'],'activa')
        self.assertEqual(self.post('/api/licenses/settings',soon_days='0')['status'],400)
        self.assertEqual(self.post('/api/licenses/settings',soon_days='60')['body']['display'],{'soon_days':60})
        self.assertEqual({r['product_id']:r for r in self.get('/api/licenses/units')['body']['rows']}[anual]['state'],'por_vencer')
        self.assertEqual(self.get('/api/licenses')['body']['display']['soon_days'],60)
        on=lambda field,day:{r['product_id'] for r in self.get('/api/licenses/units?field=%s&from=%s&to=%s'%(field,day,day))['body']['rows']}
        self.assertEqual(on('activacion',start),{anual});self.assertEqual(on('entrega',start),set())
        csv=self.get('/api/licenses/units/export.csv')
        self.assertEqual(csv['status'],200);text=csv['body'].decode() if isinstance(csv['body'],bytes) else csv['body']
        self.assertIn('Código',text);self.assertIn(rows[anual]['code'],text);self.assertNotIn(SERIAL,text);self.assertNotIn('MENS-KEY',text)
        only=self.get('/api/licenses/units/export.csv?ids=%d'%rows[mensual]['id'])['body'];only=only.decode() if isinstance(only,bytes) else only
        self.assertIn(rows[mensual]['code'],only);self.assertNotIn(rows[anual]['code'],only)
        self.assertEqual(licenses.export_csv([dict(rows[anual],client='=HYPERLINK("x")')]).count("'=HYPERLINK"),1)


if __name__=='__main__':unittest.main()
