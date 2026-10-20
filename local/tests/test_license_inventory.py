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


class LicenseReviewTests(LicenseInventoryTests):
    def test_manual_correction_requires_reason_admin_and_is_logged(self):
        self.admin();today=self.today().isoformat();made=self.new_product(key='REV-KEY-00001');uid=made['unit_id']
        with app.connect() as c:c.execute("UPDATE license_units SET activated=1,activated_at=?,expires_at=? WHERE id=?",(today,(self.today()+timedelta(days=365)).isoformat(),uid))
        path='/api/licenses/units/%d'%uid
        self.assertEqual(self.post(path,action='retire_activation',reason='x')['status'],400)
        with app.connect() as c:self.assertEqual(c.execute('SELECT activated FROM license_units WHERE id=?',(uid,)).fetchone()[0],1)  # nada cambia sin motivo
        done=self.post(path,action='retire_activation',reason='Fecha cargada por error al registrar el lote');self.assertEqual(done['status'],200,done['body'])
        unit=self.unit(uid);self.assertEqual((unit['status'],unit['activated'],unit['activated_at'],unit['expires_at']),('disponible',0,'',''))
        last=self.get('/api/licenses/history?unit=%d'%uid)['body']['rows'][0]
        self.assertEqual(last['event'],'correccion');self.assertIn(today,last['detail']);self.assertIn('Fecha cargada por error',last['detail']);self.assertTrue(last['actor'])
        self.assertEqual(self.post(path,action='retire_activation',reason='Segundo intento ficticio')['status'],409)
        # Una licencia vendida no se corrige así (su activación es real).
        sold=self.post('/api/licenses/sales',client_id=str(self.client_id()),items=[{'product_id':str(made['product_id']),'quantity':'1'}],deliver=True,accept_balance=True,activated=True,activated_at=today)['body']
        sold_unit=self.get('/api/licenses/sales/%d'%sold['sale'])['body']['units'][0]['id']
        self.assertEqual(self.post('/api/licenses/units/%d'%sold_unit,action='retire_activation',reason='Intento sobre vendida')['status'],409)
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        self.assertEqual(self.post(path,action='retire_activation',reason='Intento de técnico')['status'],403)

    def test_dashboard_counts_match_records(self):
        self.admin();client=self.client_id();made=self.new_product(key='CNT-KEY-00001');pid=made['product_id']
        self.assertEqual(self.post('/api/licenses/units/bulk',product_id=str(pid),lines='CNT-KEY-00002\nCNT-KEY-00003\nCNT-KEY-00004')['status'],201)
        self.post('/api/licenses/sales',client_id=str(client),items=[{'product_id':str(pid),'quantity':'1'}],deliver=True,accept_balance=True,activated=True,activated_at=(self.today()-timedelta(days=350)).isoformat())
        self.post('/api/licenses/sales',client_id=str(client),items=[{'product_id':str(pid),'quantity':'1'}])
        meta=self.get('/api/licenses')['body'];d=meta['dashboard'];rows=self.get('/api/licenses/units')['body']['rows']
        count=lambda state:sum(1 for r in rows if r['state']==state)
        for key,state in (('disponibles','disponible'),('reservadas','reservada'),('activas','activa'),('por_vencer','por_vencer'),('vencidas','vencida'),('pendientes_activacion','pendiente_activacion')):
            self.assertEqual(d[key],count(state),key)
        self.assertEqual((d['disponibles'],d['reservadas'],d['por_vencer']),(2,1,1))


class LicenseStockAdjustTests(LicenseInventoryTests):
    def test_decrease_retires_chosen_units_keeps_sold_and_history(self):
        self.admin();client=self.client_id()
        made=self.new_product(name='Office 365 Empresarial 5 dispositivos ficticio',key='OFF-KEY-00001');pid=made['product_id']
        self.assertEqual(self.post('/api/licenses/units/bulk',product_id=str(pid),lines='OFF-KEY-00002\nOFF-KEY-00003\nOFF-KEY-00004')['status'],201)
        for _ in range(2):self.post('/api/licenses/sales',client_id=str(client),items=[{'product_id':str(pid),'quantity':'1'}],deliver=True,accept_balance=True)
        stock=self.get('/api/licenses/products/%d/stock'%pid)['body'];available=stock['available']
        self.assertEqual((len(available),stock['counts']['entregada']),(2,2));self.assertTrue(all(u['hint'].startswith('•••• ') for u in available));self.assertNotIn('OFF-KEY',str(stock))
        with app.connect() as c:sold=[dict(r) for r in c.execute("SELECT * FROM license_units WHERE status='entregada' ORDER BY id")]
        post=lambda **body:self.post('/api/licenses/products/adjust',item_id=str(pid),**body)
        self.assertEqual(post(real_quantity='-1',reason='duplicada',unit_ids=[])['status'],400)  # sin negativos
        self.assertEqual(post(real_quantity='3',reason='duplicada',unit_ids=[])['status'],409)   # aumentar: registrar licencias reales
        self.assertEqual(post(real_quantity='2',reason='duplicada',unit_ids=[])['status'],409)   # sin diferencia
        self.assertEqual(post(real_quantity='1',reason='',unit_ids=[available[0]['id']])['status'],400)
        self.assertEqual(post(real_quantity='1',reason='duplicada',unit_ids=[])['status'],400)  # hay que elegir cuál
        self.assertEqual(post(real_quantity='1',reason='otro',notes='',unit_ids=[available[0]['id']])['status'],400)
        sold_id=sold[0]['id'];self.assertEqual(post(real_quantity='1',reason='duplicada',unit_ids=[sold_id])['status'],409)  # una vendida no se retira
        done=post(real_quantity='1',reason='duplicada',notes='Cargada dos veces',unit_ids=[available[0]['id']])
        self.assertEqual(done['status'],200,done['body']);self.assertEqual((done['body']['before'],done['body']['after'],done['body']['retired']),(2,1,[available[0]['code']]))
        retired=self.unit(available[0]['id']);self.assertEqual(retired['status'],'anulada');self.assertTrue(retired['secret'].startswith('lic1:'))
        with app.connect() as c:self.assertEqual([dict(r) for r in c.execute("SELECT * FROM license_units WHERE status='entregada' ORDER BY id")],sold)
        product=next(p for p in self.get('/api/licenses')['body']['products'] if p['id']==pid);self.assertEqual(product['stock']['disponible'],1)
        history=self.get('/api/licenses/history')['body']['rows'];kinds=[r['event'] for r in history[:2]]
        self.assertEqual(set(kinds),{'retirada','ajuste_stock'});summary=next(r for r in history if r['event']=='ajuste_stock')
        self.assertIn('2 → 1',summary['detail']);self.assertIn('Registro duplicado',summary['detail']);self.assertIn('Persona de prueba',summary['detail']);self.assertEqual(summary['actor'],'Persona de prueba')
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        self.assertEqual(post(real_quantity='0',reason='duplicada',unit_ids=[available[1]['id']])['status'],403)


if __name__=='__main__':unittest.main()
