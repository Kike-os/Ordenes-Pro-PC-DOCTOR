"""Varios equipos por orden: identificadores por equipo, equipos idénticos, reingresos, pagos separados y entregas individuales."""
import unittest
import test_app
import app,equipment
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class EquipmentTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def receive(self,cookie,csrf,key,**extra):
        return self.request('/api/orders',self.order_data(dict({'type':'escritorio','brand':'Genérica','model':'Clon','request_key':'equipment-request-key-'+key},**extra)),cookie=cookie,csrf=csrf)

    def test_identical_units_share_an_order_with_own_identifiers(self):
        cookie,csrf=self.login()
        main=self.receive(cookie,csrf,'0001')['body']
        with app.connect() as c:sequences=c.execute('SELECT SUM(value) FROM daily_order_sequences').fetchone()[0]
        second=self.receive(cookie,csrf,'0002',group_order_id=str(main['id']),new_unit='1')
        third=self.receive(cookie,csrf,'0003',group_order_id=str(second['body']['id']),new_unit='1')
        self.assertEqual((second['status'],third['status']),(200,200) if second['status']==200 else (201,201))
        self.assertEqual(second['body']['code'],main['code']+'-E02');self.assertEqual(third['body']['code'],main['code']+'-E03')
        # Reintentar el mismo envío no crea otra unidad.
        self.assertEqual(self.receive(cookie,csrf,'0003',group_order_id=str(main['id']),new_unit='1')['body']['id'],third['body']['id'])
        detail=self.request('/api/orders/'+str(third['body']['id']),cookie=cookie)['body']
        order=detail.get('order',detail);group=order['group']
        self.assertEqual([unit['unit_code'] for unit in group['units']],[main['code']+'-E0%d'%n for n in (1,2,3)])
        self.assertEqual(order['unit_code'],main['code']+'-E03');self.assertTrue(group['multiple'])
        # Tres equipos idénticos sin serie: tres identidades permanentes distintas.
        codes=[unit['device_code'] for unit in group['units']]
        self.assertEqual(len(set(codes)),3);self.assertTrue(all(code.startswith('EQ-') for code in codes))
        with app.connect() as c:
            # Los equipos adicionales no consumen números de orden y el identificador del equipo es permanente.
            self.assertEqual(c.execute('SELECT SUM(value) FROM daily_order_sequences').fetchone()[0],sequences)
            with self.assertRaises(Exception):c.execute("UPDATE devices SET code='EQ-9999' WHERE code=?",(codes[0],))
        # Una orden de otro cliente no admite el equipo.
        other=self.receive(cookie,csrf,'0004',client='Otra Persona Ficticia',identification='0100000314',phone='0987654321',group_order_id=str(main['id']))
        self.assertEqual(other['status'],409)
        self.assertEqual(self.receive(cookie,csrf,'0005',group_order_id='999999')['status'],404)

    def test_existing_device_keeps_history_and_blocks_double_entry(self):
        cookie,csrf=self.login()
        first=self.receive(cookie,csrf,'0101',serial='SN-REINGRESO-1')['body']
        device=self.request('/api/orders/'+str(first['id']),cookie=cookie)['body'];device=device.get('order',device)
        # Con un ingreso abierto no se registra otro del mismo equipo.
        again=self.receive(cookie,csrf,'0102',device_id=str(device['device_id']))
        self.assertEqual(again['status'],409);self.assertIn('ingreso abierto',again['body']['error'])
        self.assertEqual(self.request('/api/order-status',{'id':str(first['id']),'status':'entregado'},cookie=cookie,csrf=csrf)['status'],200)
        # Reingreso meses después: orden nueva, mismo equipo; las características salen del registro aunque el formulario diga otra cosa.
        back=self.receive(cookie,csrf,'0103',device_id=str(device['device_id']),brand='Otra',serial='')
        self.assertIn(back['status'],(200,201));self.assertNotIn('-E',back['body']['code'])
        returned=self.request('/api/orders/'+str(back['body']['id']),cookie=cookie)['body'];returned=returned.get('order',returned)
        self.assertEqual((returned['device_id'],returned['device_code'],returned['serial'],returned['brand']),(device['device_id'],device['device_code'],'SN-REINGRESO-1','Genérica'))
        # «Equipo similar» con una serie ya registrada se rechaza: sería el mismo equipo físico.
        self.assertEqual(self.receive(cookie,csrf,'0104',new_unit='1',serial='sn-reingreso-1')['status'],409)
        self.assertEqual(self.receive(cookie,csrf,'0105',device_id='999999')['status'],404)
        history=self.request('/api/clients/'+str(returned['client_id']),cookie=cookie)['body']['equipment']
        mine=next(item for item in history if item['id']==device['device_id'])
        self.assertEqual([visit['id'] for visit in mine['orders']],[back['body']['id'],first['id']]);self.assertEqual(mine['open'],1)

    def test_payments_are_per_unit_and_delivery_requires_no_balance(self):
        cookie,csrf=self.login()
        main=self.receive(cookie,csrf,'0201')['body'];second=self.receive(cookie,csrf,'0202',group_order_id=str(main['id']),new_unit='1')['body']
        with app.connect() as c:
            c.execute('INSERT INTO order_budget(order_id,labor_cents) VALUES (?,3000)',(main['id'],));c.execute('INSERT INTO order_budget(order_id,labor_cents,parts_cents) VALUES (?,2000,500)',(second['id'],))
        pay=lambda oid,**body:self.request('/api/orders/'+str(oid)+'/payments',body,cookie=cookie,csrf=csrf)
        deliver=lambda oid:self.request('/api/order-status',{'id':str(oid),'status':'entregado'},cookie=cookie,csrf=csrf)
        blocked=deliver(main['id']);self.assertEqual(blocked['status'],409);self.assertIn('$30,00',blocked['body']['error'])
        for body in ({'amount':'0','method':'efectivo'},{'amount':'10.999','method':'efectivo'},{'amount':'10','method':'cheque'},{'amount':'30.01','method':'efectivo'}):
            self.assertEqual(pay(main['id'],**body)['status'],400)
        self.assertEqual(pay(main['id'],amount='10',method='efectivo')['status'],201)
        paid=pay(main['id'],amount='20.00',method='transferencia',note='Comprobante ficticio 123')
        self.assertEqual((paid['status'],paid['body']['balance_cents']),(201,0))
        # Se entrega el primero mientras el segundo sigue en reparación con su propio saldo.
        self.assertEqual(deliver(main['id'])['status'],200);self.assertEqual(deliver(second['id'])['status'],409)
        order=self.request('/api/orders/'+str(second['id']),cookie=cookie)['body'];order=order.get('order',order)
        self.assertEqual({key:order['group']['totals'][key] for key in ('budget_cents','paid_cents','balance_cents','delivered','units','state')},{'budget_cents':5500,'paid_cents':3000,'balance_cents':2500,'delivered':1,'units':2,'state':'parcial'})
        self.assertEqual([(unit['status_code'],unit['balance_cents']) for unit in order['group']['units']],[('entregado',0),('pendiente',2500)])
        # Anular exige motivo, no borra el pago y no se permite sobre un equipo ya entregado.
        first_payment=pay(second['id'],amount='25',method='tarjeta')['body']['id']
        void=lambda oid,**body:self.request('/api/orders/'+str(oid)+'/payments/void',body,cookie=cookie,csrf=csrf)
        self.assertEqual(void(second['id'],payment_id=str(first_payment),reason='')['status'],400)
        self.assertEqual(void(second['id'],payment_id=str(first_payment),reason='Importe digitado por error')['body']['balance_cents'],2500)
        self.assertEqual(void(second['id'],payment_id=str(first_payment),reason='Importe digitado por error')['status'],409)
        delivered_payment=self.request('/api/orders/'+str(main['id']),cookie=cookie)['body'];delivered_payment=delivered_payment.get('order',delivered_payment)['payments'][0]['id']
        self.assertEqual(void(main['id'],payment_id=str(delivered_payment),reason='No corresponde anular')['status'],409)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_payments').fetchone()[0],3)
            with self.assertRaises(Exception):c.execute('DELETE FROM order_payments')
        # La edición completa de la orden aplica la misma política de entrega.
        payload={'problem':'No enciende','status':'entregado','priority':'normal','assigned_to':'','estimated_delivery':'','internal_notes':'','recommendations':'','findings':'','comment':'','labor':'20','parts':'5','services':'0','digital':'0','revision':order['revision']}
        self.assertEqual(self.request('/api/orders/'+str(second['id'])+'/workspace',payload,cookie=cookie,csrf=csrf)['status'],409)
        self.assertEqual(pay(second['id'],amount='25',method='efectivo')['status'],201)
        self.assertEqual(self.request('/api/orders/'+str(second['id'])+'/workspace',payload,cookie=cookie,csrf=csrf)['status'],200)


if __name__=='__main__':unittest.main()


class SerialIdentificationTests(unittest.TestCase):
    """Identificación por serie: reconoce equipos ya registrados con su identidad e historial y guarda los resultados verificados del fabricante."""
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def test_known_serial_returns_identity_history_and_open_entry(self):
        cookie,csrf=self.login()
        first=self.request('/api/orders',self.order_data({'type':'portatil','brand':'Dell','model':'Latitude Ficticia','serial':'snficticia77','request_key':'serial-identify-request-0001'}),cookie=cookie,csrf=csrf)['body']
        find=lambda serial,brand='':self.request('/api/devices/identify?serial='+serial+'&brand='+brand,cookie=cookie)['body']
        found=find('SNFICTICIA77');match=found['matches'][0]
        self.assertEqual((len(found['matches']),found['conflict'],match['brand'],match['model'],match['orders'],match['open_order']),(1,False,'Dell','Latitude Ficticia',1,first['code']))
        self.assertTrue(match['device_code'].startswith('EQ-'));self.assertEqual([item['code'] for item in match['history']],[first['code']])
        self.assertEqual(found['manufacturer']['state'],'unavailable')  # sin credenciales no hay consulta externa ni datos inventados
        self.request('/api/order-status',{'id':str(first['id']),'status':'entregado'},cookie=cookie,csrf=csrf)
        self.assertEqual(find('snficticia77')['matches'][0]['open_order'],'')
        # Nueva orden del mismo equipo: mismo registro, sin duplicarlo.
        again=self.request('/api/orders',self.order_data({'type':'portatil','device_id':str(match['device_id']),'request_key':'serial-identify-request-0002'}),cookie=cookie,csrf=csrf)['body']
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM devices WHERE upper(replace(serial,' ',''))='SNFICTICIA77'").fetchone()[0],1)
        self.assertEqual([item['code'] for item in find('SNFICTICIA77')['matches'][0]['history']],[again['code'],first['code']])
        self.assertEqual(find('NO-EXISTE-0001')['matches'],[]);self.assertEqual(self.request('/api/devices/identify?serial=ab',cookie=cookie)['status'],400)
        self.assertEqual(self.request('/api/devices/identify?serial=SNFICTICIA77')['status'],401)

    def test_manufacturer_result_is_cached_and_failures_do_not_block(self):
        import device_lookup,device_manufacturers
        from unittest.mock import patch
        cookie,_=self.login();device_lookup._verified.clear()
        answer={'brand':'Dell','model':'Modelo De Prueba','type':'','factory':{}}
        with patch.object(device_manufacturers,'configured',return_value=('dell',)),patch.object(device_manufacturers,'lookup',return_value=answer) as call:
            get=lambda:self.request('/api/devices/identify?serial=ABC1234&brand=Dell',cookie=cookie)['body']['manufacturer']
            one=get();two=get()
            self.assertEqual((one['state'],one['result']['model'],one['result']['source'],two['state'],two.get('cached')),('found','Modelo De Prueba','fabricante:dell','found',True))
            self.assertEqual(call.call_count,1)  # la segunda consulta de la misma serie no vuelve a salir al fabricante
        device_lookup._verified.clear()
        with patch.object(device_manufacturers,'configured',return_value=('dell',)),patch.object(device_manufacturers,'lookup',side_effect=device_manufacturers.ProviderError('conexion','sin respuesta')):
            failed=self.request('/api/devices/identify?serial=ABC1234&brand=Dell',cookie=cookie)
            self.assertEqual((failed['status'],failed['body']['manufacturer']['state'],failed['body']['manufacturer']['result']),(200,'error',None))

    def test_overall_state_never_closes_the_order_while_a_unit_is_pending(self):
        rows=lambda *statuses:[{'status_code':code} for code in statuses]
        cases=((('pendiente','pendiente'),'recibidos','Equipos recibidos','2 equipos · 2 recibidos'),(('pendiente','reparacion'),'curso','Atención en curso','2 equipos · 1 en proceso · 1 recibido'),
               (('listo','pendiente'),'curso','Atención en curso','2 equipos · 1 listo para entregar · 1 recibido'),(('listo','espera_entrega'),'listos','Listos para entrega','2 equipos · 2 listos para entregar'),
               (('entregado','reparacion'),'parcial','Entrega parcial','2 equipos · 1 entregado · 1 en proceso'),(('entregado','listo','presupuesto'),'parcial','Entrega parcial','3 equipos · 1 entregado · 1 listo para entregar · 1 en proceso'),
               (('entregado','entregado'),'completada','Orden completada','2 equipos · 2 entregados'),(('esperando_cliente',),'curso','Atención en curso','1 equipo · 1 en proceso'))
        for statuses,code,label,summary in cases:
            got=equipment.overall(rows(*statuses));self.assertEqual((got['code'],got['label'],got['summary']),(code,label,summary),statuses)
        # En el sistema real: entregar E01 no cambia E02, y el estado general queda en «Entrega parcial».
        cookie,csrf=self.login();main=EquipmentTests.receive(self,cookie,csrf,'ov01')['body'];second=EquipmentTests.receive(self,cookie,csrf,'ov02',group_order_id=str(main['id']),new_unit='1')['body']
        self.assertEqual(self.request('/api/order-status',{'id':str(second['id']),'status':'reparacion'},cookie=cookie,csrf=csrf)['status'],200)
        self.assertEqual(self.request('/api/order-status',{'id':str(main['id']),'status':'entregado'},cookie=cookie,csrf=csrf)['status'],200)
        for seen in (main['id'],second['id']):
            detail=self.request('/api/orders/%d'%seen,cookie=cookie)['body'];group=detail.get('order',detail)['group']
            self.assertEqual(([(u['status_code'],u['phase']) for u in group['units']],group['overall']['code'],group['overall']['summary']),([('entregado','entregado'),('reparacion','proceso')],'parcial','2 equipos · 1 entregado · 1 en proceso'))
            self.assertTrue(all(u['updated_at'] for u in group['units']))

