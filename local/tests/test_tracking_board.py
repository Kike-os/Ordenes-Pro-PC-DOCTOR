"""Seguimiento de Órdenes agrupado por orden: sin duplicados, contadores reales y etapas con evidencia."""
import unittest
import test_app
import app,tracking_board
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class TrackingBoardTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def order(self,cookie,csrf,key,**extra):
        return self.request('/api/orders',self.order_data(dict({'email':key+'@example.invalid','brand':'HP','model':'Modelo '+key,'request_key':'tracking-order-'+key.rjust(6,'0')},**extra)),cookie=cookie,csrf=csrf)['body']['id']

    def test_one_card_per_order_with_counters_stages_and_history(self):
        self.assertEqual(self.request('/api/tracking')['status'],401)
        cookie,csrf=self.login();a=self.order(cookie,csrf,'a');b=self.order(cookie,csrf,'b',brand='Lenovo');quiet=self.order(cookie,csrf,'c')
        status=lambda oid,value,comment='':self.request('/api/order-status',{'id':str(oid),'status':value,'comment':comment},cookie=cookie,csrf=csrf)
        for value in ('reparacion','esperando_cliente','reparacion','listo'):status(a,value)
        status(b,'entregado','Entrega directa')
        with app.connect() as c:before=c.execute('SELECT COUNT(*) FROM order_history').fetchone()[0]
        board=self.request('/api/tracking',cookie=cookie)['body']
        # Una sola tarjeta por orden, primero la de actividad más reciente; cada una con su último movimiento real.
        self.assertEqual([row['id'] for row in board['rows']],[b,a,quiet]);self.assertEqual(board['total'],3)
        first=board['rows'][1];self.assertEqual((first['status_code'],first['status_label'],first['previous_label'],first['client'],first['brand']),('listo','Listo para entregar','Procesando','Cliente ficticio','HP'))
        self.assertGreaterEqual(first['events'],5);self.assertTrue(first['actor'])
        # Contadores calculados con los registros reales.
        self.assertEqual({item['key']:item['total'] for item in board['counters']},{'pending':1,'process':0,'waiting':0,'ready':1,'done':1})
        # Etapas: la orden A pasó por «En proceso» (hay evidencia); la B saltó directo a Entregado, así que las intermedias quedan sin registro, no completadas.
        self.assertEqual([stage['state'] for stage in first['stages']],['done','done','current','pending'])
        self.assertEqual([stage['state'] for stage in board['rows'][0]['stages']],['done','unrecorded','unrecorded','current'])
        self.assertEqual([stage['state'] for stage in board['rows'][2]['stages']],['current','pending','pending','pending'])
        # Historial completo y cronológico al expandir; no se pierde ningún evento ni se modifica la base.
        full=self.request('/api/tracking/'+str(a),cookie=cookie)['body']['rows']
        self.assertEqual(len(full),first['events']);self.assertEqual([row['id'] for row in full],sorted(row['id'] for row in full))
        self.assertEqual(self.request('/api/tracking/999999',cookie=cookie)['status'],404)
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM order_history').fetchone()[0],before)

    def test_group_rows_carry_the_order_code_the_unit_and_the_real_overall_state(self):
        # Orden con dos equipos: cada fila es un equipo, con el código de la orden, su número y el estado general calculado con todos.
        cookie,csrf=self.login();main=self.order(cookie,csrf,'g1');solo=self.order(cookie,csrf,'g3')
        second=self.request('/api/orders',self.order_data({'email':'g1@example.invalid','brand':'HP','model':'Modelo g2','request_key':'tracking-order-0000g2','group_order_id':str(main),'new_unit':'1'}),cookie=cookie,csrf=csrf)['body']['id']
        self.request('/api/order-status',{'id':str(main),'status':'entregado'},cookie=cookie,csrf=csrf)
        rows={row['id']:row for row in self.request('/api/tracking',cookie=cookie)['body']['rows']}
        self.assertIsNone(rows[solo]['group']);self.assertNotIn('group_id',rows[solo]);self.assertNotIn('unit_no',rows[solo])
        first,other=rows[main]['group'],rows[second]['group']
        self.assertEqual((first['unit_no'],first['units'],other['unit_no'],other['units']),(1,2,2,2))
        self.assertEqual(first['main_code'],other['main_code']);self.assertEqual(first['main_code'],rows[main]['code']);self.assertTrue(rows[second]['code'].endswith('-E02'))
        # Un equipo entregado y otro en proceso: el equipo figura entregado, la orden NO figura completada.
        self.assertEqual(rows[main]['status_code'],'entregado');self.assertEqual(first['overall']['code'],'parcial');self.assertEqual(other['overall']['label'],'Entrega parcial')
        self.assertIn('2 equipos',first['overall']['summary'])
        self.request('/api/order-status',{'id':str(second),'status':'entregado'},cookie=cookie,csrf=csrf)
        rows={row['id']:row for row in self.request('/api/tracking',cookie=cookie)['body']['rows']}
        self.assertEqual(rows[second]['group']['overall']['code'],'completada')

    def test_search_filters_and_pagination(self):
        cookie,csrf=self.login();ids=[self.order(cookie,csrf,'p%02d'%index,brand='Dell' if index%2 else 'Asus') for index in range(10)]
        self.request('/api/order-status',{'id':str(ids[0]),'status':'reparacion'},cookie=cookie,csrf=csrf)
        get=lambda query:self.request('/api/tracking?'+query,cookie=cookie)
        page=get('page=1')['body'];self.assertEqual((page['total'],page['pages'],len(page['rows']),page['rows'][0]['id']),(10,2,tracking_board.PAGE,ids[0]))
        second=get('page=2')['body'];self.assertEqual(len(second['rows']),2);self.assertFalse({row['id'] for row in page['rows']}&{row['id'] for row in second['rows']})
        self.assertEqual(get('q=dell')['body']['total'],5);self.assertEqual(get('q=Modelo%20p03')['body']['total'],1)
        self.assertEqual([row['id'] for row in get('status=reparacion')['body']['rows']],[ids[0]])
        self.assertEqual(get('technician=none')['body']['total']+get('technician=%d'%self.uid)['body']['total'],10)
        today=app.reception_now().date().isoformat();self.assertEqual(get('from='+today+'&to='+today)['body']['total'],10);self.assertEqual(get('to=2020-01-01')['body']['total'],0)
        for bad in ('status=inventado','from=ayer','from=2026-02-01&to=2026-01-01','technician=x','page=x'):self.assertEqual(get(bad)['status'],400,bad)


if __name__=='__main__':unittest.main()


class TrackingCarouselPagesTests(unittest.TestCase):
    """Carrusel del inicio: bloques pequeños por consulta, búsqueda por estado y tamaño de página del listado completo."""
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def test_chunks_status_search_and_order_page_sizes(self):
        cookie,csrf=self.login();ids=[]
        for index in range(14):
            ids.append(self.request('/api/orders',self.order_data({'brand':'Lenovo' if index%2 else 'HP','serial':'CAR-%02d'%index,'request_key':'carousel-request-key-%04d'%index}),cookie=cookie,csrf=csrf)['body']['id'])
        self.assertEqual(self.request('/api/order-status',{'id':str(ids[0]),'status':'listo'},cookie=cookie,csrf=csrf)['status'],200)
        get=lambda query:self.request('/api/tracking?'+query,cookie=cookie)
        first=get('size=12&page=1')['body'];second=get('size=12&page=2')['body']
        self.assertEqual((len(first['rows']),len(second['rows']),first['total'],first['pages'],first['page_size']),(12,2,14,2,12))
        self.assertEqual(len({row['id'] for row in first['rows']+second['rows']}),14)
        self.assertEqual(len(get('')['body']['rows']),8)  # tamaño de siempre cuando no se indica
        for bad in ('size=2','size=51','size=x'):self.assertEqual(get(bad)['status'],400)
        # Se encuentra por estado, marca y número de orden.
        self.assertEqual([row['id'] for row in get('q=listo+para')['body']['rows']],[ids[0]])
        self.assertEqual(get('q=lenovo&size=50')['body']['total'],7)
        self.assertEqual(get('q='+first['rows'][0]['code'])['body']['total'],1)
        orders=lambda query:self.request('/api/orders?'+query,cookie=cookie)
        self.assertEqual([(len(orders('size=%s'%size)['body']['rows']),orders('size=%s'%size)['body']['pages']) for size in ('10','20','50')],[(10,2),(14,1),(14,1)])
        self.assertEqual((len(orders('size=10&page=2')['body']['rows']),orders('')['body']['size']),(4,50))
        self.assertEqual(orders('size=7')['status'],400)

    def test_sort_by_last_movement_phone_and_serial_search(self):
        cookie,csrf=self.login();ids=[TrackingBoardTests.order(self,cookie,csrf,'s%02d'%index,serial='SERIE-%03d'%index) for index in range(4)]
        self.request('/api/order-status',{'id':str(ids[1]),'status':'reparacion'},cookie=cookie,csrf=csrf)
        get=lambda query:self.request('/api/tracking?'+query,cookie=cookie)
        recent=get('page=1')['body'];old=get('page=1&sort=antiguo')['body']
        # El último movimiento registrado manda: la orden recién actualizada va primera (o última, al invertir el orden).
        self.assertEqual((recent['rows'][0]['id'],old['rows'][-1]['id'],recent['filters']['sort'],old['filters']['sort']),(ids[1],ids[1],'reciente','antiguo'))
        self.assertEqual([row['id'] for row in old['rows']],[row['id'] for row in reversed(recent['rows'])])
        self.assertEqual(get('sort=cualquiera')['status'],400)
        # Teléfono del cliente y número de serie viajan con la fila; se puede buscar por serie.
        row=recent['rows'][0];self.assertEqual((row['phone'],row['serial']),('0991234567','SERIE-001'))
        found=get('q=serie-002')['body'];self.assertEqual((found['total'],found['rows'][0]['id']),(1,ids[2]))
        # Las etapas reflejan solo el estado real: una orden en espera no aparenta estar en reparación, y revertir el estado revierte la etapa.
        waiting=next(r for r in recent['rows'] if r['id']==ids[0]);self.assertEqual([stage['state'] for stage in waiting['stages']],['current','pending','pending','pending'])
        self.assertEqual([stage['state'] for stage in row['stages']],['done','current','pending','pending'])
        self.request('/api/order-status',{'id':str(ids[1]),'status':'pendiente'},cookie=cookie,csrf=csrf)
        back=next(r for r in get('page=1')['body']['rows'] if r['id']==ids[1]);self.assertEqual([stage['state'] for stage in back['stages']],['current','pending','pending','pending'])

