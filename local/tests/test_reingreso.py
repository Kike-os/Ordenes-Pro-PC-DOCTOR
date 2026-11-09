"""Reingreso de un equipo ya entregado y pagado (1.5.267): orden nueva vinculada al mismo equipo, sin tocar la anterior.

Datos ficticios en una base temporal (la de test_app). Cubre: reconocimiento por serie, historial, registro maestro único,
independencia de pagos/presupuesto/diagnóstico, fechas originales intactas, número nuevo y búsqueda meses después.
"""
import unittest
from datetime import datetime,timedelta
import test_app
import app,equipment
app.os.environ.setdefault('LOGIN_CAPTCHA','off')

SERIAL='5CD-REING-0001'


class ReentryTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def receive(self,key,**extra):
        base={'type':'portatil','brand':'HP','model':'ProBook 450','color':'Gris','serial':SERIAL,'request_key':'reentry-request-key-'+key}
        return self.request('/api/orders',self.order_data(dict(base,**extra)),cookie=self.cookie,csrf=self.csrf)

    def detail(self,oid):
        body=self.request('/api/orders/'+str(oid),cookie=self.cookie)['body'];return body.get('order',body)

    def delivered_and_paid(self,key='0001',months=0):
        """Orden anterior: diagnóstico, presupuesto, pago completo y entrega. Con months>0 sus fechas se llevan al pasado."""
        first=self.receive(key)['body'];oid=first['id']
        with app.connect() as c:
            c.execute("UPDATE orders SET findings='Disco dañado (ficticio)',recommendations='Respaldar datos' WHERE id=?",(oid,))
            c.execute('INSERT INTO order_budget(order_id,labor_cents,parts_cents) VALUES (?,2500,4000)',(oid,));c.commit()
        paid=self.request('/api/orders/'+str(oid)+'/payments',{'amount':'65','method':'efectivo'},cookie=self.cookie,csrf=self.csrf)
        self.assertEqual((paid['status'],paid['body']['balance_cents']),(201,0))
        self.assertEqual(self.request('/api/order-status',{'id':str(oid),'status':'entregado'},cookie=self.cookie,csrf=self.csrf)['status'],200)
        with app.connect() as c:
            if months:
                back=timedelta(days=30*months)
                row=c.execute('SELECT created_at,received_at,delivered_at FROM orders WHERE id=?',(oid,)).fetchone()
                shift=lambda iso:(datetime.fromisoformat(iso)-back).isoformat(timespec='microseconds')
                c.execute('UPDATE orders SET created_at=?,received_at=?,delivered_at=? WHERE id=?',(row['created_at']-int(back.total_seconds()),shift(row['received_at']),shift(row['delivered_at']),oid));c.commit()
            before=dict(c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone())
            payments=[dict(r) for r in c.execute('SELECT * FROM order_payments WHERE order_id=? ORDER BY id',(oid,))]
            budget=dict(c.execute('SELECT * FROM order_budget WHERE order_id=?',(oid,)).fetchone())
        return oid,before,payments,budget

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        self.cookie,self.csrf=self.login()

    def test_reentry_of_delivered_paid_order_creates_new_linked_order(self):
        old,before,payments,budget=self.delivered_and_paid('0001',months=5)
        device_id=before['device_id']
        # 2-3. La serie (escrita con minúsculas y espacios) reconoce el equipo y su última orden, sin ingreso abierto.
        found=self.request('/api/devices/identify?serial='+' 5cd-reing-0001 '.replace(' ','%20'),cookie=self.cookie)['body']
        self.assertEqual(len(found['matches']),1);match=found['matches'][0]
        self.assertEqual((match['device_id'],match['open_order'],match['orders'],match['last_order']['id']),(device_id,'',1,old))
        # 4. Historial técnico con la orden anterior y su diagnóstico.
        card=self.request('/api/devices/'+str(device_id),cookie=self.cookie)['body']
        self.assertEqual([h['id'] for h in card['history']],[old]);self.assertEqual(card['history'][0]['findings'],'Disco dañado (ficticio)')
        self.assertTrue(card['device']['code'].startswith('EQ-'))
        # 5 y 8. Nueva orden con el mismo equipo: número nuevo (no una unidad -E0N) y el mismo registro maestro.
        new=self.receive('0002',device_id=str(device_id),problem='Vuelve a calentarse')
        self.assertIn(new['status'],(200,201));nid=new['body']['id']
        self.assertNotEqual(nid,old);self.assertNotEqual(new['body']['code'],before['code']);self.assertNotIn('-E',new['body']['code'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM devices WHERE upper(replace(serial,\' \',\'\'))=?',(SERIAL,)).fetchone()[0],1)
            self.assertEqual(c.execute('SELECT device_id FROM orders WHERE id=?',(nid,)).fetchone()[0],device_id)
            self.assertIsNone(c.execute('SELECT group_id FROM orders WHERE id=?',(nid,)).fetchone()[0])
            # 6. Pagos, presupuesto y diagnóstico de la orden anterior intactos e independientes.
            self.assertEqual([dict(r) for r in c.execute('SELECT * FROM order_payments WHERE order_id=? ORDER BY id',(old,))],payments)
            self.assertEqual(dict(c.execute('SELECT * FROM order_budget WHERE order_id=?',(old,)).fetchone()),budget)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_payments WHERE order_id=?',(nid,)).fetchone()[0],0)
            self.assertIsNone(c.execute('SELECT 1 FROM order_budget WHERE order_id=?',(nid,)).fetchone())
            self.assertEqual({k:v for k,v in equipment.money(c,nid).items() if k.endswith('_cents')},{k:0 for k in equipment.money(c,nid) if k.endswith('_cents')})
            self.assertEqual((equipment.money(c,old)['paid_cents'],equipment.money(c,old)['balance_cents']),(6500,0))
            newrow=dict(c.execute('SELECT * FROM orders WHERE id=?',(nid,)).fetchone())
            self.assertEqual((newrow['findings'] or '',newrow['recommendations'] or '',newrow['delivered_at'] or '',newrow['status']),('','','','pendiente'))
            for table in ('order_photos','order_followup_files','quotes'):
                self.assertEqual(c.execute('SELECT COUNT(*) FROM '+table+' WHERE order_id=?',(nid,)).fetchone()[0],0,table)
            # 7. La orden anterior no se reabre ni cambia: estado, número y fechas originales de ingreso y entrega.
            after=dict(c.execute('SELECT * FROM orders WHERE id=?',(old,)).fetchone())
        self.assertEqual(after,before)
        old_detail=self.detail(old)
        self.assertEqual((old_detail['status'],old_detail['balance_cents'] if 'balance_cents' in old_detail else 0),('entregado',0))
        # 9. Ambas atenciones en el historial del equipo y en el del cliente.
        card=self.request('/api/devices/'+str(device_id),cookie=self.cookie)['body']
        self.assertEqual([h['id'] for h in card['history']],[nid,old])
        self.assertEqual((card['summary']['orders'],card['summary']['delivered'],card['summary']['open']),(2,1,1))
        mine=next(i for i in self.request('/api/clients/'+str(self.detail(nid)['client_id']),cookie=self.cookie)['body']['equipment'] if i['id']==device_id)
        self.assertEqual([v['id'] for v in mine['orders']],[nid,old])
        # El detalle de la nueva orden señala el reingreso y la atención anterior.
        visits=self.detail(nid)['device_visits']
        self.assertEqual((visits['count'],visits['previous']['id'],visits['previous']['code']),(2,old,before['code']))
        self.assertEqual(self.detail(old)['device_visits']['previous'],None)

    def test_reentry_by_serial_without_selecting_the_device_reuses_master_record(self):
        old,before,_,_=self.delivered_and_paid('0101',months=3)
        # El recepcionista escribe la serie a mano, con otro color y el modelo abreviado: el equipo es el mismo (misma serie y cliente).
        new=self.receive('0102',serial='5cd reing 0001'.replace(' ','-').upper(),color='Plata',model='ProBook',problem='Teclado falla')
        self.assertIn(new['status'],(200,201))
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM devices WHERE upper(replace(serial,' ',''))=?",(SERIAL,)).fetchone()[0],1)
            row=c.execute('SELECT o.device_id,d.color,d.model FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?',(new['body']['id'],)).fetchone()
            # El registro maestro no se reescribe con lo tecleado.
            self.assertEqual((row['device_id'],row['color'],row['model']),(before['device_id'],'Gris','ProBook 450'))
            self.assertEqual(dict(c.execute('SELECT * FROM orders WHERE id=?',(old,)).fetchone()),before)
        self.assertIn('linked_device',new['body']);self.assertTrue(new['body']['linked_device'].startswith('EQ-'))

    def test_serial_with_open_order_is_not_received_twice(self):
        first=self.receive('0201')['body']
        again=self.receive('0202',color='Negro')
        self.assertEqual(again['status'],409);self.assertIn('ingreso abierto',again['body']['error']);self.assertIn(first['code'],again['body']['error'])
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)

    def test_same_serial_with_another_brand_asks_to_verify(self):
        self.delivered_and_paid('0301')
        clash=self.receive('0302',brand='Lenovo',model='ThinkPad')
        self.assertEqual(clash['status'],409);self.assertIn('serial',clash['body']['fields'])
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM devices').fetchone()[0],1)

    def test_same_serial_for_another_client_stays_separate(self):
        old,before,payments,_=self.delivered_and_paid('0401')
        other=self.receive('0402',client='Otra Persona Ficticia',identification='0100000314',phone='0987654321')
        self.assertIn(other['status'],(200,201))
        with app.connect() as c:
            self.assertNotEqual(c.execute('SELECT device_id FROM orders WHERE id=?',(other['body']['id'],)).fetchone()[0],before['device_id'])
            self.assertEqual([dict(r) for r in c.execute('SELECT * FROM order_payments WHERE order_id=? ORDER BY id',(old,))],payments)

    def test_search_finds_the_device_months_later(self):
        old,before,_,_=self.delivered_and_paid('0501',months=8)
        device_id=before['device_id']
        with app.connect() as c:code=c.execute('SELECT code FROM devices WHERE id=?',(device_id,)).fetchone()[0]
        for term in (SERIAL,SERIAL.lower(),'0991234567','099 123 4567','+593991234567','0100000017',code,'ProBook'):
            rows=self.request('/api/devices?q='+term,cookie=self.cookie)['body']['rows']
            self.assertEqual([r['id'] for r in rows],[device_id],term)
        for term in (SERIAL,'0991234567','099 123 4567',before['code']):
            rows=self.request('/api/orders?q='+term,cookie=self.cookie)['body']['rows']
            self.assertIn(old,[r['id'] for r in rows],term)
        new=self.receive('0502',device_id=str(device_id))['body']
        rows=self.request('/api/orders?q='+SERIAL,cookie=self.cookie)['body']['rows']
        self.assertEqual(sorted(r['id'] for r in rows),sorted([old,new['id']]))


if __name__=='__main__':unittest.main()
