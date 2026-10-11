"""Flujo completo: reserva en línea → Agenda de Mantenimientos de Clientes → notificación → confirmación del taller."""
import unittest
from datetime import timedelta
import test_app
import app,appointments
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class AgendaTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data

    def day(self):
        day=appointments.now().date()+timedelta(days=1)
        while day.weekday()>=5:day+=timedelta(days=1)
        return day.isoformat()

    def booking(self,time,**extra):
        return dict({'name':'Cliente De Agenda','identification':'','phone':'0991234567','email':'agenda@example.invalid','device_type':'consola','brand':'Sony','model':'PS5','service':'mantenimiento',
                     'description':'Limpieza interna y cambio de pasta térmica','date':self.day(),'time':time,'notes':'','privacy_consent':True,'communications_consent':True,'request_key':'agenda-request-'+time.replace(':','')+'-0001'},**extra)

    def test_online_booking_reaches_agenda_notifications_and_staff_confirmation(self):
        cookie,csrf=self.login()
        catalog=self.request('/api/public/appointments/services')['body']
        self.assertIn('correctivo',{s['code'] for s in catalog['services']});self.assertIn('consola',catalog['device_types'])
        slots=self.request('/api/public/appointments/availability?date=%s&service=mantenimiento'%self.day())['body']['slots']
        self.assertTrue(slots);first_slot=slots[0]['time']
        # Modo original: disponibilidad verificada en el servidor y confirmación automática.
        auto=self.request('/api/public/appointments',self.booking(first_slot))
        self.assertEqual((auto['status'],auto['body']['status']),(201,'confirmada'))
        self.assertEqual(self.request('/api/public/appointments',self.booking(first_slot,request_key='agenda-request-otro-000001'))['status'],409)
        # Modo manual: la solicitud queda pendiente y el cliente no recibe confirmación todavía.
        self.assertEqual(self.request('/api/appointments/config',{'confirmation':'manual'},cookie=cookie,csrf=csrf)['status'],200)
        free=[s['time'] for s in self.request('/api/public/appointments/availability?date=%s&service=correctivo'%self.day())['body']['slots']]
        self.assertNotIn(first_slot,free)
        pending=self.request('/api/public/appointments',self.booking(free[-1],service='correctivo',device_type='portatil',brand='HP',model=''))
        self.assertEqual((pending['status'],pending['body']['status']),(201,'solicitada'));aid=pending['body']['id']
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM appointment_notifications WHERE appointment_id=?",(aid,)).fetchone()[0],0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM orders").fetchone()[0],0)
        # Agenda administrativa: misma fuente de datos, solo para personal.
        self.assertEqual(self.request('/api/agenda')['status'],401)
        agenda=self.request('/api/agenda',cookie=cookie)['body']
        self.assertEqual({a['status'] for a in agenda['appointments']},{'confirmada','solicitada'})
        self.assertEqual((agenda['summary']['pending'],agenda['summary']['confirmed'],agenda['confirmation']),(1,1,'manual'))
        row=next(a for a in agenda['appointments'] if a['id']==aid)
        self.assertEqual((row['service_label'],row['device_type'],row['brand'],row['customer_name']),('Mantenimiento correctivo','portatil','HP','Cliente De Agenda'))
        self.assertNotIn('manage_token_hash',row);self.assertTrue(row['client_id'])
        self.assertEqual(self.request('/api/agenda?from=2026-01-01&to=2027-12-31',cookie=cookie)['status'],400)
        # Notificación persistente y sin duplicados, con acceso directo a la cita.
        for _ in range(2):items=[i for i in self.request('/api/notifications',cookie=cookie)['body']['items'] if i['key']=='appointment:%d'%aid]
        self.assertEqual(len(items),1)
        self.assertEqual((items[0]['href'],items[0]['title'].split(' · ')[0]),('#appointments?appointment=%d'%aid,'Solicitud de cita por confirmar'))
        self.assertIn('Cliente De Agenda · Mantenimiento correctivo · ',items[0]['detail'])
        # El taller confirma: cambia el estado, queda en el historial y se encola el aviso al cliente.
        self.assertEqual(self.request('/api/appointments/%d'%aid,{'action':'confirmada'},cookie=cookie)['status'],403)
        self.assertEqual(self.request('/api/appointments/%d'%aid,{'action':'confirmada'},cookie=cookie,csrf=csrf)['status'],200)
        self.assertEqual(self.request('/api/appointments/%d'%aid,{'action':'confirmada'},cookie=cookie,csrf=csrf)['status'],200)
        detail=self.request('/api/appointments/%d'%aid,cookie=cookie)['body']['appointment']
        self.assertEqual((detail['status'],[(e['event'],e['old_status'],e['new_status'],bool(e['actor'])) for e in detail['events']]),('confirmada',[('status','solicitada','confirmada',True),('created','','solicitada',False)]))
        self.assertEqual([(n['event'],n['result']) for n in detail['notices']],[('confirmation','pending')])
        self.assertEqual(self.request('/api/appointments/999999',cookie=cookie)['status'],404)
        # Cancelar libera el espacio y avisa al cliente.
        self.assertEqual(self.request('/api/appointments/%d'%aid,{'action':'cancelada'},cookie=cookie,csrf=csrf)['status'],200)
        self.assertIn(free[-1],[s['time'] for s in self.request('/api/public/appointments/availability?date=%s&service=correctivo'%self.day())['body']['slots']])
        self.assertEqual(sorted(n['event'] for n in self.request('/api/appointments/%d'%aid,cookie=cookie)['body']['appointment']['notices']),['cancelled','confirmation'])

    def test_workshop_is_emailed_once_per_new_online_request(self):
        from unittest.mock import patch
        import appointments_cron
        with patch.object(appointments_cron,'DB',app.DB),patch.object(appointments_cron,'send'),patch.object(appointments_cron,'send_staff') as staff:
            appointments_cron.run();self.assertEqual(staff.call_count,0)
            slot=self.request('/api/public/appointments/availability?date=%s&service=mantenimiento'%self.day())['body']['slots'][0]['time']
            code=self.request('/api/public/appointments',self.booking(slot))['body']['code']
            appointments_cron.run();appointments_cron.run()
            self.assertEqual(staff.call_count,1);self.assertEqual(staff.call_args[0][0]['public_code'],code)
        # Si el correo falla, se reintenta en la siguiente pasada y la reserva no se ve afectada.
        slot2=self.request('/api/public/appointments/availability?date=%s&service=mantenimiento'%self.day())['body']['slots'][0]['time']
        self.assertEqual(self.request('/api/public/appointments',self.booking(slot2,request_key='agenda-request-fallo-00001'))['status'],201)
        with patch.object(appointments_cron,'DB',app.DB),patch.object(appointments_cron,'send'),patch.object(appointments_cron,'send_staff',side_effect=RuntimeError('SMTP no configurado')) as failing:
            appointments_cron.run();self.assertEqual(failing.call_count,1)
        with patch.object(appointments_cron,'DB',app.DB),patch.object(appointments_cron,'send'),patch.object(appointments_cron,'send_staff') as retry:
            appointments_cron.run();self.assertEqual(retry.call_count,1)

    def test_staff_books_for_a_client_chosen_from_the_database(self):
        cookie,csrf=self.login()
        import client_registry
        self.request('/api/orders',self.order_data({'client':'Cliente De Base','problem':'Prueba','request_key':'agenda-staff-order-000001'}),cookie=cookie,csrf=csrf)
        found=self.request('/api/clients?q=Cliente%20De%20Base',cookie=cookie)['body']['rows'][0]
        slot=self.request('/api/public/appointments/availability?date=%s&service=mantenimiento'%self.day())['body']['slots'][0]['time']
        data=self.booking(slot,client_id=str(found['id']),name=found['name'],phone=found['phone'],email='',request_key='agenda-staff-request-0001')
        self.assertEqual(self.request('/api/appointments/new',data,cookie=cookie)['status'],403)
        with app.connect() as c:before=c.execute('SELECT COUNT(*) FROM clients').fetchone()[0]
        created=self.request('/api/appointments/new',data,cookie=cookie,csrf=csrf)
        self.assertEqual((created['status'],created['body']['status']),(201,'confirmada'));self.assertNotIn('manage_token',created['body'])
        with app.connect() as c:
            row=c.execute('SELECT client_id,customer_name FROM appointments WHERE id=?',(created['body']['id'],)).fetchone()
            self.assertEqual((row['client_id'],c.execute('SELECT COUNT(*) FROM clients').fetchone()[0]),(found['id'],before))
        self.assertEqual(self.request('/api/appointments/new',dict(data,request_key='agenda-staff-request-0002'),cookie=cookie,csrf=csrf)['status'],409)
        self.assertEqual(self.request('/api/appointments/new',dict(data,client_id='999999',time=slot,request_key='agenda-staff-request-0003'),cookie=cookie,csrf=csrf)['status'] in (404,409),True)
        # La página pública no acepta elegir un cliente por id.
        other=self.request('/api/public/appointments/availability?date=%s&service=mantenimiento'%self.day())['body']['slots'][0]['time']
        public=self.request('/api/public/appointments',self.booking(other,client_id=str(found['id']),name='Otra Persona',phone='0987654321',email='otra@example.invalid',request_key='agenda-public-request-01'))
        with app.connect() as c:self.assertNotEqual(c.execute('SELECT client_id FROM appointments WHERE id=?',(public['body']['id'],)).fetchone()[0],found['id'])

    def test_delivery_creates_one_six_month_forecast_and_links_the_later_appointment(self):
        import maintenance
        from datetime import date
        self.assertEqual([maintenance.six_months(date(*d)).isoformat() for d in ((2026,10,15),(2026,8,31),(2026,12,31),(2027,3,31))],['2027-04-15','2027-02-28','2027-06-30','2027-09-30'])
        cookie,csrf=self.login()
        oid=self.request('/api/orders',self.order_data({'client':'Cliente De Entrega','problem':'Prueba','brand':'HP','model':'ProBook','serial':'ENT-0001','request_key':'maintenance-flow-order-0001'}),cookie=cookie,csrf=csrf)['body']['id']
        post=lambda status:self.request('/api/order-status',{'id':str(oid),'status':status},cookie=cookie,csrf=csrf)
        # «Listo para entregar» no genera nada; la entrega real sí, y devuelve la previsión en la misma respuesta.
        ready=post('listo');self.assertNotIn('maintenance',ready['body'])
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM maintenance').fetchone()[0],0)
        delivered=post('entregado');due=delivered['body']['maintenance']['due_date']
        self.assertEqual(due,maintenance.six_months(appointments.now().date()).isoformat())
        # Guardar otra vez, o repetir la solicitud, no duplica.
        self.assertNotIn('maintenance',post('entregado')['body'])
        rows=self.request('/api/maintenance',cookie=cookie)['body']['rows']
        self.assertEqual(len(rows),1);row=rows[0]
        self.assertEqual((row['order_id'],row['client'],row['brand'],row['serial'],row['due_date'],bool(row['client_id']),bool(row['device_id'])),(oid,'Cliente De Entrega','HP','ENT-0001',due,True,True))
        self.assertEqual((row['proximity'],row['progress'],row['days_left']>150),('far',0,True))
        # La entrega crea sola la cita del mantenimiento: una, pendiente de confirmación, en día laborable desde la fecha prevista y vinculada.
        auto=delivered['body']['maintenance']['appointment']
        with app.connect() as c:
            saved=[dict(r) for r in c.execute('SELECT * FROM appointments')];hours=c.execute('SELECT * FROM appointment_hours WHERE weekday=?',(date.fromisoformat(auto['starts_at'][:10]).weekday(),)).fetchone()
        self.assertEqual(len(saved),1);appt=saved[0]
        self.assertEqual((appt['id'],appt['status'],appt['service_code'],appt['client_id'],appt['customer_name'],appt['communications_consent'],appt['starts_at'][11:16]),(auto['id'],'solicitada','mantenimiento',row['client_id'],'Cliente De Entrega',0,hours['start_time']))
        self.assertTrue(hours['enabled'] and due<=appt['starts_at'][:10]<=(date.fromisoformat(due)+timedelta(days=4)).isoformat())
        self.assertEqual((row['state'],row['appointment_id'],row['appointment_status'],row['appointment_code'],row['due_date']),('appointment',auto['id'],'solicitada',auto['public_code'],due))
        far=self.request('/api/agenda?from=%s&to=%s'%(appt['starts_at'][:10],appt['starts_at'][:10]),cookie=cookie)['body']
        self.assertEqual([a['public_code'] for a in far['appointments']],[auto['public_code']])
        notes=[i for i in self.request('/api/notifications',cookie=cookie)['body']['items'] if i['key'].startswith(('maintenance:','appointment:'))]
        self.assertEqual(sorted(n['title'].split(' · ')[0] for n in notes),['Próximo mantenimiento programado','Solicitud de cita por confirmar'])
        # Revertir la entrega cancela la previsión y su cita automática sin borrarlas; volver a entregar reactiva el registro con una cita nueva.
        post('listo');self.assertEqual(self.request('/api/maintenance',cookie=cookie)['body']['rows'][0]['state'],'cancelled')
        second=post('entregado')['body']['maintenance']['appointment']
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM maintenance').fetchone()[0],1)
            self.assertEqual([(r['id'],r['status']) for r in c.execute('SELECT id,status FROM appointments ORDER BY id')],[(auto['id'],'cancelada'),(second['id'],'solicitada')])
        # El taller confirma la cita propuesta: no se envía correo (no hay consentimiento registrado) y la previsión sigue vinculada.
        confirmed=self.request('/api/appointments/%d'%second['id'],{'action':'confirmada'},cookie=cookie,csrf=csrf)
        self.assertEqual(confirmed['status'],200)
        linked=self.request('/api/maintenance',cookie=cookie)['body']['rows'][0]
        self.assertEqual((linked['state'],linked['appointment_status'],linked['appointment_code']),('appointment','confirmada',second['public_code']))
        created={'body':{'id':second['id']}}
        slot=self.request('/api/public/appointments/availability?date=%s&service=mantenimiento'%self.day())['body']['slots'][0]['time']
        # Cancelar la cita devuelve la previsión a «programado»; completar otra la cierra.
        self.request('/api/appointments/%d'%created['body']['id'],{'action':'cancelada'},cookie=cookie,csrf=csrf)
        self.assertEqual((lambda r:(r['state'],r['appointment_start']))(self.request('/api/maintenance',cookie=cookie)['body']['rows'][0]),('scheduled',None))
        again=self.request('/api/appointments/new',self.booking(slot,client_id=str(row['client_id']),name=row['client'],phone=row['phone'],email='',maintenance_id=str(row['id']),request_key='maintenance-flow-appt-00002'),cookie=cookie,csrf=csrf)['body']
        for action in ('presente','completada'):self.request('/api/appointments/%d'%again['id'],{'action':action},cookie=cookie,csrf=csrf)
        self.assertEqual(self.request('/api/maintenance',cookie=cookie)['body']['rows'][0]['state'],'completed')
        history=[h['comment'] for h in self.request('/api/orders/%d'%oid,cookie=cookie)['body']['order']['history']]
        self.assertEqual((history.count('Cita de mantenimiento preventivo registrada.'),sum(h.startswith('Cita de mantenimiento preventivo generada automáticamente') for h in history)),(1,2))

    def test_edit_cancel_and_logical_delete_keep_orders_and_maintenance(self):
        import maintenance
        cookie,csrf=self.login();act=lambda aid,**data:self.request('/api/appointments/%d'%aid,data,cookie=cookie,csrf=csrf)
        slots=[s['time'] for s in self.request('/api/public/appointments/availability?date=%s&service=mantenimiento'%self.day())['body']['slots']]
        normal=self.request('/api/appointments/new',self.booking(slots[0],email='',request_key='agenda-delete-appt-0001'),cookie=cookie,csrf=csrf)['body']
        # Editar: valida en el servidor, guarda y deja constancia de qué cambió.
        self.assertEqual(act(normal['id'],action='edit',name='X',phone='123',email='',device_type='consola',brand='',model='',description='ok',notes='')['status'],400)
        edited=act(normal['id'],action='edit',name='Cliente Corregido',phone='0991234567',email='',device_type='consola',brand='Sony',model='PS5 Slim',description='Limpieza interna y cambio de pasta térmica',notes='Trae el control')
        self.assertEqual((edited['status'],sorted(edited['body']['changed'])),(200,['model','name','notes']))
        detail=self.request('/api/appointments/%d'%normal['id'],cookie=cookie)['body']['appointment']
        self.assertEqual((detail['customer_name'],detail['model'],detail['events'][0]['event'],detail['events'][0]['detail']),('Cliente Corregido','PS5 Slim','edited','Datos modificados: nombre, modelo, observaciones'))
        # Cancelar conserva la cita visible como cancelada y libera el horario.
        self.assertEqual(act(normal['id'],action='cancelada')['status'],200)
        agenda=lambda:self.request('/api/agenda',cookie=cookie)['body']
        self.assertEqual([(a['id'],a['status']) for a in agenda()['appointments']],[(normal['id'],'cancelada')])
        # Eliminar: solo administración; la cita sale de la agenda, del detalle y de los avisos, pero la fila queda con su auditoría.
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        self.assertEqual(act(normal['id'],action='delete')['status'],403)
        with app.connect() as c:c.execute("UPDATE users SET role='administrador' WHERE id=?",(self.uid,))
        self.assertEqual(act(normal['id'],action='delete',reason='Registrada por error')['status'],200)
        self.assertEqual((agenda()['appointments'],self.request('/api/appointments/%d'%normal['id'],cookie=cookie)['status'],act(normal['id'],action='delete')['status']),([],404,404))
        with app.connect() as c:
            kept=c.execute('SELECT status,deleted_by,delete_reason,deleted_at IS NOT NULL gone FROM appointments WHERE id=?',(normal['id'],)).fetchone()
            self.assertEqual((kept['status'],kept['deleted_by'],kept['delete_reason'],kept['gone']),('cancelada',self.uid,'Registrada por error',1))
            self.assertEqual(c.execute("SELECT detail FROM appointment_events WHERE appointment_id=? AND event='deleted'",(normal['id'],)).fetchone()[0],'Registrada por error')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='appointment_delete'").fetchone()[0],1)
        # Cita automática de un mantenimiento: al eliminarla se conservan la orden y la previsión, el horario queda libre y no se regenera sola.
        oid=self.request('/api/orders',self.order_data({'serial':'DEL-0001','request_key':'agenda-delete-order-0001'}),cookie=cookie,csrf=csrf)['body']['id']
        auto=self.request('/api/order-status',{'id':str(oid),'status':'entregado'},cookie=cookie,csrf=csrf)['body']['maintenance']
        detail=self.request('/api/appointments/%d'%auto['appointment']['id'],cookie=cookie)['body']['appointment']
        self.assertEqual((detail['maintenance']['id'],detail['maintenance']['order_id']),(auto['id'],oid))
        gone=act(auto['appointment']['id'],action='delete');self.assertEqual((gone['status'],gone['body']['maintenance_id']),(200,auto['id']))
        row=self.request('/api/maintenance',cookie=cookie)['body']['rows'][0]
        self.assertEqual((row['state'],row['appointment_id'],row['auto_appointment_blocked'],row['due_date']),('scheduled',None,1,auto['due_date']))
        with app.connect() as c:
            self.assertIsNone(appointments.create_for_maintenance(c,auto['id'],None))
            self.assertEqual((c.execute('SELECT status FROM orders WHERE id=?',(oid,)).fetchone()[0],c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],c.execute('SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL').fetchone()[0]),('entregado',2,0))
            start=appointments.datetime.fromisoformat(auto['appointment']['starts_at']);self.assertTrue(appointments.technicians(c,start,90))
        self.assertEqual([n for n in self.request('/api/notifications',cookie=cookie)['body']['items'] if n['key'].startswith('appointment:')],[])
        # El personal puede volver a agendarla a mano; una entrega nueva levanta la exclusión.
        self.request('/api/order-status',{'id':str(oid),'status':'listo'},cookie=cookie,csrf=csrf)
        self.assertIn('appointment',self.request('/api/order-status',{'id':str(oid),'status':'entregado'},cookie=cookie,csrf=csrf)['body']['maintenance'])

    def test_staff_can_book_today_while_public_booking_starts_tomorrow(self):
        cookie,csrf=self.login();today=appointments.now().date()
        with app.connect() as c:c.execute("UPDATE appointment_hours SET start_time='00:00',end_time='23:59',enabled=1 WHERE weekday=?",(today.weekday(),))
        public=self.request('/api/public/appointments/availability?date=%s&service=diagnostico'%today.isoformat())
        self.assertEqual(public['status'],400)
        staff=self.request('/api/appointments/availability?date=%s&service=diagnostico'%today.isoformat(),cookie=cookie)
        self.assertEqual(staff['status'],200)
        limit=(appointments.now()+timedelta(minutes=10)).strftime('%H:%M')
        self.assertTrue(all(s['time']>limit for s in staff['body']['slots']))
        self.assertEqual(self.request('/api/appointments/availability?date=%s&service=diagnostico'%today.isoformat())['status'],401)
        if staff['body']['slots']:
            made=self.request('/api/appointments/new',self.booking(staff['body']['slots'][0]['time'],date=today.isoformat(),service='diagnostico',email='',request_key='same-day-booking-00001'),cookie=cookie,csrf=csrf)
            self.assertEqual(made['status'],201)
            todays=self.request('/api/agenda?from=%s&to=%s'%(today.isoformat(),today.isoformat()),cookie=cookie)['body']
            self.assertEqual(([a['public_code'] for a in todays['appointments']],todays['summary']['today']),([made['body']['code']],1))

    def test_client_is_emailed_with_saved_data_once_per_event(self):
        from unittest.mock import patch
        import mail_pro
        cookie,csrf=self.login();sent=[]
        config={'imap_host':'i','imap_port':993,'smtp_host':'s','smtp_port':465,'username':'taller@example.invalid','password':'x'}
        with patch.object(mail_pro,'configured',return_value=True),patch.object(mail_pro,'settings',return_value=config),patch.object(mail_pro,'deliver',side_effect=lambda cfg,message,to:sent.append((message,to))):
            self.request('/api/appointments/config',{'confirmation':'manual'},cookie=cookie,csrf=csrf)
            slots=[s['time'] for s in self.request('/api/public/appointments/availability?date=%s&service=mantenimiento'%self.day())['body']['slots']]
            pending=self.request('/api/public/appointments',self.booking(slots[0]))['body']
            self.assertEqual((pending['status'],pending['mail'],len(sent)),('solicitada','sent',1))
            message,to=sent[0];self.assertEqual(to,['agenda@example.invalid'])
            self.assertEqual(message['Subject'],'Solicitud de cita recibida — '+pending['code']+' | PC-DOCTOR S.A.')
            plain=message.get_body(preferencelist=('plain',)).get_content();page=message.get_body(preferencelist=('html',)).get_content()
            for expected in ('pendiente de confirmación',pending['code'],'Cliente De Agenda','Consolas · Sony · PS5','Mantenimiento preventivo',slots[0]+' (hora de Ecuador)'):self.assertIn(expected,plain)
            self.assertNotIn('confirmada para',plain);self.assertIn('cid:logo-pcdoctor',page);self.assertIn(pending['code'],page)
            # El taller confirma: ahora sí sale la confirmación, una sola vez.
            self.request('/api/appointments/%d'%pending['id'],{'action':'confirmada'},cookie=cookie,csrf=csrf)
            self.request('/api/appointments/%d'%pending['id'],{'action':'confirmada'},cookie=cookie,csrf=csrf)
            self.assertEqual([m['Subject'].split(' — ')[0] for m,_ in sent],['Solicitud de cita recibida','Cita técnica confirmada'])
            self.assertIn('está confirmada para',sent[1][0].get_body(preferencelist=('plain',)).get_content())
            # Reprogramar conserva el código y avisa con la nueva hora; cancelar avisa y libera.
            moved=self.request('/api/appointments/%d'%pending['id'],{'action':'reschedule','starts_at':self.day()+'T'+slots[-1]+':00-05:00'},cookie=cookie,csrf=csrf)
            self.assertEqual((moved['status'],moved['body']['mail']),(200,'sent'))
            self.assertIn(slots[-1]+' (hora de Ecuador)',sent[2][0].get_body(preferencelist=('plain',)).get_content());self.assertIn(pending['code'],sent[2][0]['Subject'])
            self.request('/api/appointments/%d'%pending['id'],{'action':'cancelada'},cookie=cookie,csrf=csrf)
            self.assertEqual([m['Subject'].split(' — ')[0] for m,_ in sent],['Solicitud de cita recibida','Cita técnica confirmada','Cita técnica reprogramada','Cita técnica cancelada'])
            detail=self.request('/api/appointments/%d'%pending['id'],cookie=cookie)['body']['appointment']
            self.assertEqual([(m['kind'],m['result']) for m in detail['mails']],[('cancelled','sent'),('rescheduled','sent'),('confirmation','sent'),('request','sent')])
            # Sin autorización o sin correo no se envía nada; un fallo de SMTP no pierde la cita y se puede reintentar.
            quiet=self.request('/api/public/appointments',self.booking(slots[3],communications_consent=False,request_key='agenda-request-sinaviso-01'))['body']
            nomail=self.request('/api/public/appointments',self.booking(slots[6],email='',request_key='agenda-request-sincorreo-1'))['body']
            self.assertEqual((quiet['mail'],nomail['mail'],len(sent)),('no_consent','no_email',4))
            with patch.object(mail_pro,'deliver',side_effect=mail_pro.MailError('conexion','sin conexión')):
                failed=self.request('/api/public/appointments',self.booking(slots[9],request_key='agenda-request-fallo-smtp1'))
            self.assertEqual((failed['status'],failed['body']['mail']),(201,'failed'))
            self.assertEqual(self.request('/api/appointments/%d'%failed['body']['id'],{'action':'resend_mail'},cookie=cookie,csrf=csrf)['body']['mail'],'sent')
            self.assertEqual(self.request('/api/appointments/%d'%failed['body']['id'],{'action':'resend_mail'},cookie=cookie,csrf=csrf)['body']['mail'],'sent')
            self.assertEqual(len(sent),5)

    def test_services_are_managed_from_configuration(self):
        cookie,csrf=self.login();url='/api/appointments/config'
        created=self.request(url,{'new_service':{'label':'Mantenimiento de consola','duration_minutes':60}},cookie=cookie,csrf=csrf)
        self.assertEqual(created['status'],200)
        services={s['label']:s for s in created['body']['settings']['services']};self.assertEqual(services['Mantenimiento de consola']['duration_minutes'],60)
        self.assertEqual(self.request(url,{'new_service':{'label':'mantenimiento de consola','duration_minutes':60}},cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request(url,{'new_service':{'label':'X','duration_minutes':50}},cookie=cookie,csrf=csrf)['status'],400)
        code=services['Mantenimiento de consola']['code']
        renamed=self.request(url,{'services':[{'code':code,'label':'Mantenimiento de consolas','duration_minutes':75,'active':True}]},cookie=cookie,csrf=csrf)['body']['settings']['services']
        self.assertEqual(next(s for s in renamed if s['code']==code)['label'],'Mantenimiento de consolas')
        self.assertIn('Mantenimiento de consolas',{s['label'] for s in self.request('/api/public/appointments/services')['body']['services']})
