"""Citas: servicio «Retiro de Equipos» con orden verificada, datos obligatorios en la reserva pública y registro de clientes desde citas."""
import unittest
from datetime import timedelta
import test_app
import app,appointments
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class PickupAndClientsTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def day(self):
        day=appointments.now().date()+timedelta(days=1)
        while day.weekday()>=5:day+=timedelta(days=1)
        return day.isoformat()

    def book(self,key,hour='09:00',**extra):
        body=dict({'name':'Cliente De Prueba','identification':'1710034065','phone':'0987654321','email':'','device_type':'portatil','brand':'HP','model':'X','service':'diagnostico','description':'Revisión ficticia','date':self.day(),'time':hour,
                   'notes':'','privacy_consent':True,'communications_consent':False,'request_key':'pickup-clients-request-'+key},**extra)
        return self.request('/api/public/appointments',body)

    def test_public_form_requires_name_identification_and_phone_but_not_email(self):
        with test_app.open_requests():
            empty=self.book('0001',name='',identification='',phone='')
            self.assertEqual(empty['status'],400);self.assertEqual({k:empty['body']['fields'][k] for k in ('name','identification','phone')},{'name':'Ingresa tu nombre y apellidos.','identification':'Ingresa una cédula o RUC válido.','phone':'Ingresa un número de contacto válido.'})
            for wrong,field,text in (({'name':'Solonombre'},'name','Ingresa tu nombre y apellidos.'),({'identification':'1710034066'},'identification','Ingresa una cédula o RUC válido.'),({'identification':'12345'},'identification','Ingresa una cédula o RUC válido.'),
                                     ({'phone':'12345'},'phone','Ingresa un número de contacto válido.'),({'email':'correo@mal'},'email','Ingresa un correo electrónico válido.')):
                result=self.book('0002',**wrong);self.assertEqual((result['status'],result['body']['fields'].get(field)),(400,text),wrong)
            with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],0)
            # Nombre con tildes, ñ y compuesto; teléfono internacional; correo vacío.
            ok=self.book('0003',name='María José Ñáñez de la Peña',phone='+34 612 345 678',email='')
            self.assertEqual(ok['status'],201,ok['body']);self.assertEqual({'client_id','client_new','client_review'}&set(ok['body']),set())
            with app.connect() as c:
                client=c.execute('SELECT name,phone,email,identification,origin FROM clients WHERE identification=?',('1710034065',)).fetchone()
                self.assertEqual(tuple(client),('María José Ñáñez de la Peña','+34 612 345 678','','1710034065','cita'))
            # La misma solicitud repetida no crea otra cita ni otro cliente.
            again=self.book('0003',name='María José Ñáñez de la Peña',phone='+34 612 345 678',email='');self.assertEqual((again['status'],again['body'].get('duplicate')),(200,True))
            with app.connect() as c:self.assertEqual((c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],c.execute("SELECT COUNT(*) FROM clients WHERE origin='cita'").fetchone()[0]),(1,1))

    def test_existing_client_is_linked_and_ambiguous_contact_is_not_merged(self):
        cookie,csrf=self.login()
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'pickup-clients-order-0001'}),cookie=cookie,csrf=csrf)['body']
        with app.connect() as c:known=dict(c.execute('SELECT * FROM clients').fetchone())
        with test_app.open_requests():
            # Misma cédula: se vincula al cliente existente y no se le cambia ningún dato, aunque el nombre o el teléfono escritos difieran.
            same=self.book('0101',name='Otro Nombre Escrito',identification=known['identification'],phone='0981111111')
            self.assertEqual(same['status'],201,same['body'])
            with app.connect() as c:
                self.assertEqual(c.execute('SELECT client_id FROM appointments WHERE id=?',(same['body']['id'],)).fetchone()[0],known['id'])
                self.assertEqual(dict(c.execute('SELECT * FROM clients WHERE id=?',(known['id'],)).fetchone()),known);self.assertEqual(c.execute('SELECT COUNT(*) FROM clients').fetchone()[0],1)
            # Mismo teléfono (escrito de otra forma) pero otra cédula: no se enlaza ni se fusiona; queda un cliente nuevo señalado para revisión.
            other=self.book('0102','11:00',identification='1710034065',phone='+593 99 123 4567')
            self.assertEqual(other['status'],201,other['body'])
            with app.connect() as c:
                made=c.execute('SELECT c.id,c.origin,c.notes FROM appointments a JOIN clients c ON c.id=a.client_id WHERE a.id=?',(other['body']['id'],)).fetchone()
                self.assertNotEqual(made['id'],known['id']);self.assertEqual(made['origin'],'cita');self.assertIn('revisar posible duplicado',made['notes'])
                self.assertEqual(dict(c.execute('SELECT * FROM clients WHERE id=?',(known['id'],)).fetchone()),known)
                self.assertIn('Revisar posible duplicado',c.execute("SELECT detail FROM appointment_events WHERE appointment_id=? AND event='note'",(other['body']['id'],)).fetchone()[0])
            # El personal sí ve si el cliente era nuevo o existente; el listado de clientes muestra el origen.
            staff=self.request('/api/appointments/new',{'client_id':'','name':'Cliente Del Personal','identification':'','phone':'0972223344','email':'','device_type':'portatil','brand':'HP','model':'X','service':'diagnostico','description':'Revisión ficticia',
                               'date':self.day(),'time':'13:00','notes':'','communications_consent':False,'maintenance_id':'','request_key':'pickup-clients-staff-000001'},cookie=cookie,csrf=csrf)
            self.assertEqual((staff['status'],staff['body']['client_new'],staff['body']['client_review']),(201,True,False))
            linked=self.request('/api/appointments/new',{'client_id':str(known['id']),'name':known['name'],'identification':'','phone':known['phone'],'email':'','device_type':'portatil','brand':'HP','model':'X','service':'diagnostico','description':'Revisión ficticia',
                                'date':self.day(),'time':'15:00','notes':'','communications_consent':False,'maintenance_id':'','request_key':'pickup-clients-staff-000002'},cookie=cookie,csrf=csrf)
            self.assertEqual((linked['status'],linked['body']['client_new'],linked['body']['client_id']),(201,False,known['id']))
        rows={r['id']:r for r in self.request('/api/clients?size=50',cookie=cookie)['body']['rows']};self.assertEqual((rows[known['id']]['origin'],rows[staff['body']['client_id']]['origin']),('','cita'))
        self.assertEqual(len(self.request('/api/clients/%d'%known['id'],cookie=cookie)['body']['appointments']),2)

    def test_pickup_service_checks_the_order_without_leaking_other_clients(self):
        cookie,csrf=self.login()
        mine=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','serial':'RET-1','request_key':'pickup-clients-order-0201'}),cookie=cookie,csrf=csrf)['body']
        services={s['code']:s for s in self.request('/api/public/appointments/services')['body']['services']};self.assertEqual((services['retiro']['label'],services['retiro']['duration_minutes']),('Retiro de Equipos',15))
        unknown='No encontramos una orden con ese número asociada a tus datos. Verifícalo o deja el campo vacío.'
        owner={'identification':'0100000017','phone':'0991234567','service':'retiro','description':''}
        with test_app.open_requests():
            # Orden inexistente y orden de otra persona responden exactamente igual.
            for bad in ({'order_code':'PCD-00000000-9999'},{'order_code':mine['code'],'identification':'1710034065','phone':'0987654321'}):
                result=self.book('0202',**dict(owner,**bad));self.assertEqual((result['status'],result['body']['fields'].get('order_code')),(400,unknown),bad)
            # Equipo todavía no listo: aviso claro y no se agenda.
            early=self.book('0203',order_code=mine['code'],**owner);self.assertEqual(early['status'],400);self.assertIn('todavía no está listo para el retiro',early['body']['fields']['order_code'])
            with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],0)
            # Sin número de orden el retiro se agenda igual (la descripción no es obligatoria en este servicio).
            plain=self.book('0204',**owner);self.assertEqual((plain['status'],plain['body']['duration_minutes'],plain['body']['pickup_order']),(201,15,''))
            # Listo para entregar: se agenda y queda vinculado a la orden; la orden NO se marca como entregada.
            self.request('/api/order-status',{'id':str(mine['id']),'status':'listo'},cookie=cookie,csrf=csrf)
            ready=self.book('0205','11:00',order_code=' '+mine['code'].lower()+' ',**owner);self.assertEqual((ready['status'],ready['body']['pickup_order']),(201,mine['code']))
            detail=self.request('/api/appointments/%d'%ready['body']['id'],cookie=cookie)['body'];detail=detail.get('appointment',detail)
            self.assertEqual((detail['service_label'],detail['pickup_order']['code'],detail['pickup_order']['status'],detail['description']),('Retiro de Equipos',mine['code'],'listo','Retiro de equipo'))
            with app.connect() as c:
                self.assertEqual(c.execute('SELECT status,delivered_at FROM orders WHERE id=?',(mine['id'],)).fetchone()['status'],'listo')
                self.assertIn('La entrega se registra aparte',c.execute("SELECT detail FROM appointment_events WHERE appointment_id=? AND event='note'",(ready['body']['id'],)).fetchone()[0])
            agenda=self.request('/api/agenda?from=%s&to=%s'%(self.day(),self.day()),cookie=cookie)['body']['appointments'];self.assertEqual(sorted(a['pickup_code'] or '' for a in agenda),['',mine['code']])
            # Ya entregada: tampoco se agenda un retiro. Otros servicios ignoran el número de orden.
            with app.connect() as c:c.execute("UPDATE orders SET status='entregado' WHERE id=?",(mine['id'],));c.commit()
            late=self.book('0206','13:00',order_code=mine['code'],**owner);self.assertIn('ya figura como entregada',late['body']['fields']['order_code'])
            other=self.book('0207','15:00',identification='0100000017',phone='0991234567',order_code='cualquier-cosa');self.assertEqual((other['status'],other['body']['pickup_order']),(201,''))
