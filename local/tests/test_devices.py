"""Módulo Equipos: lista con historial resumido, ficha con historial técnico y series repetidas. Solo lectura."""
import unittest
from urllib.parse import quote
import test_app
import app
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class DevicesTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data

    def test_list_history_filters_and_duplicates(self):
        cookie,csrf=self.login();ids=[]
        for n,(kind,serial) in enumerate([('portatil','HIST-0001'),('impresora','HIST-0002'),('portatil','HIST-0001')]):
            data=self.order_data({'type':kind,'brand':'HP','model':'Equipo %d'%n,'serial':serial,'problem':'Falla %d'%n,'request_key':'devices-history-order-%03d'%n})
            if n==2:data.update({'client':'Otro Cliente','identification':'0100000025'})
            created=self.request('/api/orders',data,cookie=cookie,csrf=csrf);self.assertEqual(created['status'],201,created);ids.append(created['body']['id'])
        with app.connect() as c:devices=[r[0] for r in c.execute('SELECT device_id FROM orders ORDER BY id')]
        rows=self.request('/api/devices',cookie=cookie)['body']['rows'];by={row['id']:row for row in rows}
        self.assertEqual((by[devices[0]]['orders'],by[devices[0]]['last_status'],by[devices[0]]['type']),(1,'pendiente','portatil'))
        # La misma serie en dos equipos distintos se señala en ambos; la serie única no.
        if devices[0]!=devices[2]:
            self.assertEqual((by[devices[0]]['duplicates'],by[devices[2]]['duplicates'],by[devices[1]]['duplicates']),(1,1,0))
            self.assertEqual({row['id'] for row in self.request('/api/devices?duplicates=1',cookie=cookie)['body']['rows']},{devices[0],devices[2]})
        printers=self.request('/api/devices?type=impresora',cookie=cookie)['body'];self.assertEqual([row['id'] for row in printers['rows']],[devices[1]])
        self.assertEqual(self.request('/api/devices?type=x',cookie=cookie)['status'],400)
        self.assertEqual(self.request('/api/devices?q='+quote('HIST-0002')+'&type=impresora',cookie=cookie)['body']['total'],1)
        # Ficha: datos del equipo y todas sus órdenes, de la más reciente a la más antigua.
        again=self.request('/api/orders',self.order_data({'type':'portatil','brand':'HP','model':'Equipo 0','serial':'HIST-0001','problem':'Segunda visita','request_key':'devices-history-order-004'}),cookie=cookie,csrf=csrf)
        self.assertEqual(again['status'],201,again)
        with app.connect() as c:target=c.execute('SELECT device_id FROM orders WHERE id=?',(again['body']['id'],)).fetchone()[0]
        card=self.request('/api/devices/%d'%target,cookie=cookie)['body']
        self.assertEqual(card['device']['serial'],'HIST-0001');self.assertEqual(card['summary']['orders'],len(card['history']))
        self.assertEqual(card['history'][0]['id'],again['body']['id']);self.assertEqual(card['history'][0]['problem'],'Segunda visita')
        self.assertTrue(all(a['id']>b['id'] for a,b in zip(card['history'],card['history'][1:])))
        self.assertNotIn('budget',str(card));self.assertEqual(self.request('/api/devices/999999',cookie=cookie)['status'],404)
        self.assertEqual(self.request('/api/devices/%d'%target)['status'],401)


if __name__=='__main__':
    unittest.main()
