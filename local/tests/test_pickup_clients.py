"""Citas: servicio «Retiro de Equipos» con orden verificada, datos obligatorios en la reserva pública y registro de clientes desde citas."""
import re
import unittest
from datetime import timedelta
from unittest.mock import patch
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
                   'notes':'','document_type':'cedula','privacy_consent':True,'terms_accept':True,'id_last4':'4065','communications_consent':False,'request_key':'pickup-clients-request-'+key},**extra)
        # Los 4 dígitos que escribe el cliente: los últimos de su cédula (o de la cédula contenida en un RUC de persona natural).
        if 'id_last4' not in extra:number=str(body['identification']);body['id_last4']=re.sub(r'\D','',number)[-4:] if body.get('document_type')=='pasaporte' else number[6:10] if len(number)==13 else number[-4:]
        return self.request('/api/public/appointments',body)

    def test_public_form_requires_name_identification_and_phone_but_not_email(self):
        # El límite de solicitudes por IP (12 cada 15 minutos) tiene su propia prueba; aquí se aparta para recorrer todas las combinaciones.
        with test_app.open_requests(),patch.object(app,'limited',return_value=False):
            empty=self.book('0001',name='',identification='',phone='')
            self.assertEqual(empty['status'],400);self.assertEqual({k:empty['body']['fields'][k] for k in ('name','identification','phone')},{'name':'Ingresa tu nombre y apellidos.','identification':'Ingresa tu número de identificación para continuar.','phone':'Ingresa un número de contacto válido.'})
            ten,thirteen='La cédula debe contener exactamente 10 dígitos.','El RUC debe contener exactamente 13 dígitos.';bad='El número de cédula no es válido. Revisa los dígitos ingresados.';bad_ruc='Los diez primeros dígitos del RUC no forman una cédula válida. Revisa los dígitos ingresados.';branch='El RUC debe terminar en su número de establecimiento (por ejemplo, 001).'
            # Cédula con 9, 10 y 11 dígitos; RUC con 12, 13 y 14; letras y símbolos; dígito verificador incorrecto; tipo que no corresponde al número.
            for kind,number,text in (('cedula','171003406',ten),('cedula','17100340655',ten),('cedula','1710034066',bad),('cedula','17100A4065',ten),('cedula','1710-03406',ten),('cedula','1710034065001',ten),
                                     ('ruc','171003406500',thirteen),('ruc','17100340650011',thirteen),('ruc','1710034065',thirteen),('ruc','1710034066001',bad_ruc),('ruc','1710034065000',branch),('','1710034065',None)):
                result=self.book('0002',document_type=kind,identification=number);self.assertEqual(result['status'],400,(kind,number))
                if text:self.assertEqual(result['body']['fields'].get('identification'),text,(kind,number))
                else:self.assertEqual(result['body']['fields'].get('document_type'),'Selecciona el tipo de identificación.')
            for wrong,field,text in (({'name':'Solonombre'},'name','Ingresa tu nombre y apellidos.'),
                                     ({'phone':'12345'},'phone','Ingresa un número de contacto válido.'),({'email':'correo@mal'},'email','Ingresa un correo electrónico válido.')):
                result=self.book('0002',**wrong);self.assertEqual((result['status'],result['body']['fields'].get(field)),(400,text),wrong)
            with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],0)
            # Nombre con tildes, ñ y compuesto; teléfono internacional; correo vacío.
            ok=self.book('0003',name='María José Ñáñez de la Peña',phone='+34 612 345 678',email='')
            self.assertEqual(ok['status'],201,ok['body']);self.assertEqual({'client_id','client_new','client_review'}&set(ok['body']),set())
            with app.connect() as c:
                client=c.execute('SELECT name,phone,email,identification,origin FROM clients WHERE identification=?',('1710034065',)).fetchone()
                self.assertEqual(tuple(client),('María José Ñáñez de la Peña','+34 612 345 678','','1710034065','cita'));self.assertEqual((c.execute('SELECT document_type FROM clients WHERE identification=?',('1710034065',)).fetchone()[0],c.execute('SELECT document_type,identification FROM appointments').fetchone()[0]),('cedula','cedula'))
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
            staff=self.request('/api/appointments/new',{'client_id':'','terms_accept':True,'id_last4':'4065','name':'Cliente Del Personal','identification':'','phone':'0972223344','email':'','device_type':'portatil','brand':'HP','model':'X','service':'diagnostico','description':'Revisión ficticia',
                               'date':self.day(),'time':'13:00','notes':'','communications_consent':False,'maintenance_id':'','request_key':'pickup-clients-staff-000001'},cookie=cookie,csrf=csrf)
            self.assertEqual((staff['status'],staff['body']['client_new'],staff['body']['client_review']),(201,True,False))
            linked=self.request('/api/appointments/new',{'client_id':str(known['id']),'terms_accept':True,'id_last4':'4065','name':known['name'],'identification':'','phone':known['phone'],'email':'','device_type':'portatil','brand':'HP','model':'X','service':'diagnostico','description':'Revisión ficticia',
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

    def test_closed_appointment_can_be_reactivated_without_duplicates_or_mail(self):
        import mail_pro,appointments
        from unittest.mock import patch
        with test_app.open_requests():
            made=self.book('0501');self.assertEqual(made['status'],201,made['body'])
            with app.connect() as c:aid=c.execute('SELECT id FROM appointments ORDER BY id DESC LIMIT 1').fetchone()[0]
            cookie,csrf=self.login();act=lambda action,ident=aid:self.request('/api/appointments/%d'%ident,{'action':action},cookie=cookie,csrf=csrf)
            self.assertEqual(act('confirmada')['status'],200);self.assertEqual(act('reactivar')['status'],409)             # no está cerrada
            self.assertEqual(act('no_asistio')['status'],200)
            with app.connect() as c:before=dict(c.execute('SELECT * FROM appointments WHERE id=?',(aid,)).fetchone());total=c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0]
            with patch.object(mail_pro,'deliver',side_effect=AssertionError('no debe enviar correos')):
                done=act('reactivar');self.assertEqual((done['status'],done['body'].get('status')),(200,'confirmada'),done['body'])
            with app.connect() as c:
                after=dict(c.execute('SELECT * FROM appointments WHERE id=?',(aid,)).fetchone());self.assertEqual(c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],total)
                self.assertEqual({k:after[k] for k in after if k not in ('status','updated_at')},{k:before[k] for k in before if k not in ('status','updated_at')})   # misma cita, mismos datos
                events=[tuple(r) for r in c.execute('SELECT event,old_status,new_status,detail FROM appointment_events WHERE appointment_id=? ORDER BY id',(aid,))]
                self.assertEqual(events[-1],('reactivated','no_asistio','confirmada',appointments.REACTIVATE_NOTE));self.assertGreaterEqual(len(events),3)   # el historial anterior se conserva
                self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='appointment_reactivated'").fetchone()[0],1)
            # «En atención» marcado por error: vuelve a su estado anterior sin revisar el horario (ya es suyo) y sin correos.
            self.assertEqual(act('presente')['status'],200)
            with patch.object(mail_pro,'deliver',side_effect=AssertionError('no debe enviar correos')):back=act('reactivar')
            self.assertEqual((back['status'],back['body'].get('status')),(200,'confirmada'),back['body'])
            with app.connect() as c:self.assertEqual(tuple(c.execute('SELECT event,old_status,new_status FROM appointment_events WHERE appointment_id=? ORDER BY id DESC LIMIT 1',(aid,)).fetchone()),('reactivated','presente','confirmada'))
            # Si otra cita ocupó ese horario mientras estaba cerrada, no se reactiva encima.
            self.assertEqual(act('cancelada')['status'],200)
            other=self.book('0502',identification='0100000017',phone='0976500002');self.assertEqual(other['status'],201,other['body'])
            clash=act('reactivar');self.assertEqual((clash['status'],clash['body'].get('conflict')),(409,True))
            with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
            self.assertEqual(act('reactivar')['status'],403)

    def test_passport_is_accepted_for_people_without_cedula(self):
        with test_app.open_requests():
            for bad in ('AB','ABCDEFGH','A1 2','A'*21+'1','<AB12345>'):
                refused=self.book('0401',document_type='pasaporte',identification=bad);self.assertEqual(refused['status'],400,bad);self.assertIn('pasaporte',refused['body']['fields']['identification'])
            made=self.book('0402',document_type='pasaporte',identification=' ab-123456 ',phone='0976543299',name='Persona Extranjera Ficticia');self.assertEqual(made['status'],201,made['body'])
            with app.connect() as c:
                row=c.execute("SELECT a.identification number,a.document_type kind,cl.identification,cl.document_type FROM appointments a JOIN clients cl ON cl.id=a.client_id ORDER BY a.id DESC LIMIT 1").fetchone()
                self.assertEqual(tuple(row),('AB-123456','pasaporte','AB-123456','pasaporte'))
                clients=c.execute('SELECT COUNT(*) FROM clients').fetchone()[0]
            # El mismo pasaporte, escrito en minúsculas, vincula al mismo cliente.
            again=self.book('0403','11:00',document_type='pasaporte',identification='ab-123456',phone='0976543299',name='Persona Extranjera Ficticia');self.assertEqual(again['status'],201,again['body'])
            with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM clients').fetchone()[0],clients)

    def test_ruc_with_leading_zero_is_kept_and_links_the_same_client(self):
        with test_app.open_requests():
            first=self.book('0301',document_type='ruc',identification='0100000017001',phone='0976543210');self.assertEqual(first['status'],201,first['body'])
            with app.connect() as c:
                row=c.execute('SELECT c.id,c.identification,c.document_type,a.document_type kind,a.identification number FROM appointments a JOIN clients c ON c.id=a.client_id WHERE a.id=?',(first['body']['id'],)).fetchone()
                self.assertEqual((row['identification'],row['document_type'],row['kind'],row['number']),('0100000017001','ruc','ruc','0100000017001'))
            # El mismo RUC en otra reserva vincula al mismo cliente; no se crea otro.
            again=self.book('0302','11:00',document_type='ruc',identification='0100000017001',phone='0976543210',name='Otra Forma De Escribirlo')
            with app.connect() as c:self.assertEqual((c.execute('SELECT client_id FROM appointments WHERE id=?',(again['body']['id'],)).fetchone()[0],c.execute('SELECT COUNT(*) FROM clients').fetchone()[0]),(row['id'],1))
            # La respuesta pública no devuelve la identificación.
            self.assertNotIn('0100000017001',str(again['body']))

