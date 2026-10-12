"""Permanencia en taller: cálculo, niveles, ajustes, alerta interna, informe y reversión de entrega."""
import unittest
from datetime import datetime,timedelta
import test_app
import app,stay
app.os.environ.setdefault('LOGIN_CAPTCHA','off')
from reception import ECUADOR_TZ

CONFIG=dict(stay.DEFAULTS)


class StayComputeTest(unittest.TestCase):
    def at(self,days,**extra):
        now=datetime(2026,6,1,12,0,tzinfo=ECUADOR_TZ)
        return stay.compute(dict({'received_at':(now-timedelta(days=days,hours=3)).isoformat(),'status_code':'reparacion','delivered_at':None},**extra),now,CONFIG)

    def test_levels_follow_the_thresholds(self):
        for days,level in ((0,'ok'),(59,'ok'),(60,'notice'),(74,'notice'),(75,'near'),(89,'near'),(90,'overdue'),(140,'overdue')):
            info=self.at(days);self.assertEqual((info['days'],info['level']),(days,level))
        self.assertEqual((self.at(10)['remaining'],self.at(10)['exceeded'],self.at(10)['hours']),(80,0,3))
        self.assertEqual((self.at(95)['remaining'],self.at(95)['exceeded'],self.at(95)['percent']),(0,5,100))

    def test_counter_stops_only_with_delivery(self):
        now=datetime(2026,6,1,12,0,tzinfo=ECUADOR_TZ);start=(now-timedelta(days=100)).isoformat();end=(now-timedelta(days=8)).isoformat()
        closed=stay.compute({'received_at':start,'status_code':'entregado','delivered_at':end},now,CONFIG)
        self.assertEqual((closed['closed'],closed['days'],closed['exceeded']),(True,92,2))
        # Una fecha de entrega antigua no detiene el contador si la orden ya no está entregada (entrega revertida).
        reopened=stay.compute({'received_at':start,'status_code':'listo','delivered_at':end},now,CONFIG)
        self.assertEqual((reopened['closed'],reopened['days']),(False,100))
        # Sin fecha de ingreso usa la de creación (época); sin ninguna no inventa un valor.
        self.assertEqual(stay.compute({'created_at':int((now-timedelta(days=3)).timestamp()),'status_code':'pendiente'},now,CONFIG)['days'],3)
        self.assertIsNone(stay.compute({'status_code':'pendiente'},now,CONFIG))

    def test_settings_are_validated(self):
        self.assertEqual(stay.validate({'limit':'120','notice':'80','near':'100'},CONFIG)[0]['mail_days'],[80,100,115,120])
        for bad in ({'limit':'10'},{'limit':'x'},{'notice':'80','near':'70'},{'near':'90'},{'limit':'900'}):
            self.assertIsNone(stay.validate(bad,CONFIG)[0],bad)
        self.assertFalse(stay.validate({'limit':'120'},CONFIG)[0]['mail'])


class StayRoutesTest(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def age(self,oid,days):
        with app.connect() as c:
            stamp=(app.reception_now()-timedelta(days=days)).isoformat(timespec='microseconds')
            c.execute('UPDATE orders SET received_at=?,created_at=? WHERE id=?',(stamp,int((app.reception_now()-timedelta(days=days)).timestamp()),oid))

    def order(self,cookie,csrf,key):
        return self.request('/api/orders',self.order_data({'email':key+'@example.invalid','brand':'HP','model':'ProBook','request_key':'stay-order-'+key.rjust(8,'0')}),cookie=cookie,csrf=csrf)['body']['id']

    def test_list_detail_alert_and_report(self):
        cookie,csrf=self.login();old=self.order(cookie,csrf,'stay-a');fresh=self.order(cookie,csrf,'stay-b');self.age(old,93)
        rows={row['id']:row for row in self.request('/api/orders?page=1',cookie=cookie)['body']['rows']}
        self.assertEqual((rows[old]['stay']['level'],rows[old]['stay']['exceeded'],rows[fresh]['stay']['level'],rows[fresh]['stay']['days']),('overdue',3,'ok',0))
        detail=self.request('/api/orders/'+str(old),cookie=cookie)['body']['order']
        self.assertEqual((detail['stay']['days'],detail['stay_settings']['limit'],detail['stay_delivery']),(93,90,None))
        alerts=[item for item in self.request('/api/notifications',cookie=cookie)['body']['items'] if item['key'].startswith('alert:stay-overdue')]
        self.assertEqual(len(alerts),1);self.assertIn('1 equipo superó',alerts[0]['title'])
        report=self.request('/api/orders/'+str(old)+'/stay.pdf',cookie=cookie)
        self.assertEqual(report['status'],200);self.assertTrue(report['body'].startswith(b'%PDF'))
        # Superar el plazo no cambia el estado de la orden.
        with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM orders WHERE id=?',(old,)).fetchone()[0],detail['status'])
        # La entrega detiene el contador, registra quién entregó y retira la alerta.
        self.assertEqual(self.request('/api/order-status',{'id':str(old),'status':'entregado'},cookie=cookie,csrf=csrf)['status'],200)
        detail=self.request('/api/orders/'+str(old),cookie=cookie)['body']['order']
        self.assertEqual((detail['stay']['closed'],detail['stay']['days'],detail['stay']['exceeded']),(True,93,3));self.assertTrue(detail['stay_delivery']['by'])
        self.assertFalse([item for item in self.request('/api/notifications',cookie=cookie)['body']['items'] if item['key'].startswith('alert:stay-overdue')])

    def test_settings_and_delivery_reversal_are_administrative(self):
        cookie,csrf=self.login();oid=self.order(cookie,csrf,'stay-c');self.age(oid,40)
        self.assertEqual(self.request('/api/stay/settings',{'limit':'45','notice':'20','near':'35'},cookie=cookie,csrf=csrf)['status'],200)
        self.assertEqual(self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']['stay']['level'],'near')
        self.assertEqual(self.request('/api/stay/settings',{'limit':'45','notice':'40','near':'35'},cookie=cookie,csrf=csrf)['status'],400)
        self.request('/api/order-status',{'id':str(oid),'status':'entregado'},cookie=cookie,csrf=csrf)
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=(SELECT user_id FROM sessions LIMIT 1)")
        self.assertEqual(self.request('/api/order-status',{'id':str(oid),'status':'listo'},cookie=cookie,csrf=csrf)['status'],403)
        self.assertEqual(self.request('/api/stay/settings',{'limit':'60','notice':'20','near':'35'},cookie=cookie,csrf=csrf)['status'],403)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM orders WHERE id=?',(oid,)).fetchone()[0],'entregado')
            c.execute("UPDATE users SET role='administrador'")
        self.assertEqual(self.request('/api/order-status',{'id':str(oid),'status':'listo'},cookie=cookie,csrf=csrf)['status'],200)
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='delivery_reverted' AND entity_id=?",(oid,)).fetchone()[0],1)
        self.assertFalse(self.request('/api/orders/'+str(oid),cookie=cookie)['body']['order']['stay']['closed'])


if __name__=='__main__':unittest.main()
