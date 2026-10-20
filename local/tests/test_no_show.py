"""Inasistencias y reagendamiento: detección con tolerancia, idempotencia, avisos, enlace privado, disponibilidad real, simultaneidad,
límites, enlace vencido, restauración y rectificación. Reloj controlado y correos simulados: nunca se envía nada real."""
import concurrent.futures
import unittest
from datetime import timedelta
from unittest.mock import patch
import test_app
import app,appointments,no_show
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class NoShowTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request

    def day(self,offset=1):
        day=appointments.now().date()+timedelta(days=offset)
        while day.weekday()>=5:day+=timedelta(days=1)
        return day.isoformat()

    def book(self,key,email='cliente@example.invalid',consent=True,time=None,day=None):
        free=lambda d:[s['time'] for s in self.request('/api/public/appointments/availability?date=%s&service=diagnostico'%d)['body'].get('slots',[])]
        if day:slots=free(day)
        else:
            # Un solo técnico en las pruebas: si el día se llena, se usa el siguiente día laborable con horarios libres.
            for offset in range(1,40):
                day=self.day(offset);slots=free(day)
                if slots:break
        made=self.request('/api/public/appointments',{'name':'Cliente Ficticio Prueba','identification':'1710034065','document_type':'cedula','phone':'0991234567','email':email,'device_type':'portatil','brand':'HP',
                          'model':'Ficticio','service':'diagnostico','description':'Revisión ficticia','date':day,'time':time or slots[0],'notes':'','privacy_consent':True,'communications_consent':consent,
                          'terms_accept':True,'id_last4':'4065','request_key':'no-show-request-'+key})
        self.assertEqual(made['status'],201,made['body']);return made['body']['id']

    def past(self,aid,minutes):
        """Mueve la cita a «hace N minutos» (sin cambiar su estado) para simular el paso del tiempo."""
        start=appointments.now()-timedelta(minutes=minutes)
        with app.connect() as c:c.execute('UPDATE appointments SET starts_at=? WHERE id=?',(appointments.stamp(start),aid))

    def enable(self,**extra):
        with app.connect() as c:no_show.save_settings(c,dict({'auto':True,'grace':'15'},**extra),appointments.now()-timedelta(hours=6))

    def status(self,aid):
        with app.connect() as c:return c.execute('SELECT status FROM appointments WHERE id=?',(aid,)).fetchone()[0]

    def sweep(self,notify=None):
        with app.connect() as c:return no_show.sweep(c,appointments.now(),notify)

    def test_detection_respects_tolerance_attention_cancellation_orders_and_activation(self):
        ids={name:self.book(name) for name in ('puntual','tolerancia','ausente','atendida','cancelada','orden','antigua')}
        for name in ids:self.past(ids[name],10 if name=='tolerancia' else 40)
        with app.connect() as c:
            c.execute("UPDATE appointments SET status='presente' WHERE id=?",(ids['atendida'],))
            c.execute("UPDATE appointments SET status='completada' WHERE id=?",(ids['puntual'],))
            c.execute("UPDATE appointments SET status='cancelada' WHERE id=?",(ids['cancelada'],))
            client=c.execute('SELECT client_id FROM appointments WHERE id=?',(ids['orden'],)).fetchone()[0]
            device=c.execute("INSERT INTO devices(client_id,type,category,kind,brand,model) VALUES (?,'portatil','portatil','portatil','HP','Ficticio')",(client,)).lastrowid
            order=c.execute("INSERT INTO orders(device_id,status,problem,created_by,created_at,code,received_at) VALUES (?,'pendiente','Ficticia',?,0,'PCD-20990101-0001','2099-01-01T00:00:00-05:00')",(device,self.uid)).lastrowid
            c.execute('UPDATE appointments SET converted_order_id=? WHERE id=?',(order,ids['orden']))
        self.assertEqual(self.sweep()['marked'],0)                         # desactivado: nada cambia
        self.enable()
        # Una cita anterior a la activación nunca se toca (no hay cambios masivos sobre el historial).
        with app.connect() as c:c.execute('UPDATE appointments SET starts_at=? WHERE id=?',(appointments.stamp(appointments.now()-timedelta(hours=10)),ids['antigua']))
        self.assertEqual(self.sweep()['marked'],1)
        states={name:self.status(aid) for name,aid in ids.items()}
        self.assertEqual(states,{'puntual':'completada','tolerancia':'confirmada','ausente':'no_asistio','atendida':'presente','cancelada':'cancelada','orden':'confirmada','antigua':'confirmada'})
        self.assertEqual(self.sweep()['marked'],0)                         # idempotente
        with app.connect() as c:
            event=c.execute("SELECT detail,old_status,new_status FROM appointment_events WHERE appointment_id=? AND event='no_show_auto'",(ids['ausente'],)).fetchall()
        self.assertEqual(len(event),1);self.assertEqual((event[0]['old_status'],event[0]['new_status']),('confirmada','no_asistio'));self.assertIn('15 minutos',event[0]['detail'])

    def test_notices_without_mail_errors_retries_and_no_duplicates(self):
        self.enable()
        with_mail=self.book('con-correo');no_mail=self.book('sin-correo',email='');no_consent=self.book('sin-permiso',consent=False)
        for aid in (with_mail,no_mail,no_consent):self.past(aid,30)
        calls=[]
        def failing(c,row,token):calls.append(row['id']);raise app.mail_pro.MailError('conexion','Servidor no disponible (ficticio).')
        summary=self.sweep(failing);self.assertEqual((summary['marked'],summary['failed'],summary['skipped']),(3,1,2))
        for _ in range(4):self.sweep(failing)                              # reintentos controlados: como máximo 3 intentos
        self.assertEqual(calls.count(with_mail),no_show.MAIL_ATTEMPTS);self.assertNotIn(no_mail,calls);self.assertNotIn(no_consent,calls)
        with app.connect() as c:
            states={r['appointment_id']:r['mail_status'] for r in c.execute('SELECT appointment_id,mail_status FROM appointment_reschedule_links WHERE id IN (SELECT MAX(id) FROM appointment_reschedule_links GROUP BY appointment_id)')}
        self.assertEqual((states[no_mail],states[no_consent],states[with_mail]),('sin_correo','sin_autorizacion','error'))
        # Con el correo funcionando, el aviso sale una sola vez aunque la tarea se ejecute varias veces.
        other=self.book('otra');self.past(other,30);sent=[]
        for _ in range(3):self.sweep(lambda c,row,token:(sent.append(row['id']),('enviado','ok'))[1])
        self.assertEqual(sent.count(other),1)

    def token_for(self,aid):
        self.enable();self.past(aid,30);tokens={}
        self.sweep(lambda c,row,token:(tokens.__setitem__(row['id'],token),('enviado','ok'))[1])
        return tokens[aid]

    def test_client_reschedules_with_real_availability(self):
        aid=self.book('reagenda');token=self.token_for(aid)
        info=self.request('/api/public/reschedule/'+token)['body']
        self.assertEqual(info['state'],'ok');self.assertNotIn('0991234567',str(info));self.assertNotIn('cliente@example.invalid',str(info))
        day=next(d['date'] for d in info['days'] if d['slots']);slots=self.request('/api/public/reschedule/'+token+'?date='+day)['body']['slots']
        sunday=next((appointments.now().date()+timedelta(days=n)).isoformat() for n in range(1,9) if (appointments.now().date()+timedelta(days=n)).weekday()==6)
        self.assertEqual(self.request('/api/public/reschedule/'+token+'?date='+sunday)['body']['slots'],[])          # día no laborable
        self.assertEqual(self.request('/api/public/reschedule',{'token':token,'date':sunday,'time':'10:00'})['status'],409)
        with patch.object(app.appointment_mail,'send',return_value='sent'):
            done=self.request('/api/public/reschedule',{'token':token,'date':day,'time':slots[0]})
        self.assertEqual(done['status'],200,done['body']);self.assertEqual(done['body']['message'],'Tu cita técnica fue reagendada correctamente.')
        with app.connect() as c:row=c.execute('SELECT status,reschedules,reschedule_origin FROM appointments WHERE id=?',(aid,)).fetchone()
        self.assertEqual(tuple(row),('reprogramada',1,'cliente'))
        self.assertEqual(self.request('/api/public/reschedule/'+token)['body']['state'],'used')                        # no se reutiliza
        self.assertEqual(self.request('/api/public/reschedule',{'token':token,'date':day,'time':slots[-1]})['status'],409)
        cookie,_=self.login();detail=self.request('/api/appointments/%d'%aid,cookie=cookie)['body']['appointment']
        events=[e['event'] for e in detail['events']];self.assertIn('no_show_auto',events);self.assertIn('rescheduled',events)
        self.assertTrue(any('Cliente reagendó' in (e['detail'] or '') for e in detail['events']))

    def test_busy_slot_closed_holiday_and_simultaneous_requests(self):
        first=self.book('primera');second=self.book('segunda')
        self.enable();self.past(first,30);self.past(second,30);tokens={}
        self.sweep(lambda c,row,token:(tokens.__setitem__(row['id'],token),('enviado','ok'))[1])
        day=self.day(3);slots=self.request('/api/public/reschedule/'+tokens[first]+'?date='+day)['body']['slots'];target=slots[0]
        # Se llena el horario elegido con otras reservas: ya no se ofrece y confirmar devuelve alternativas.
        n=0
        while target in self.request('/api/public/reschedule/'+tokens[first]+'?date='+day)['body']['slots']:self.book('ocupa-%d'%n,day=day,time=target);n+=1
        busy=self.request('/api/public/reschedule',{'token':tokens[first],'date':day,'time':target})
        self.assertEqual(busy['status'],409);self.assertEqual(busy['body']['error'],'Este horario ya no está disponible. Selecciona otra opción.')
        # Feriado cerrado: el día no ofrece horarios.
        closed=self.day(5)
        with app.connect() as c:c.execute("INSERT INTO appointment_holidays(day,label) VALUES (?,'Feriado ficticio')",(closed,))
        self.assertEqual(self.request('/api/public/reschedule/'+tokens[first]+'?date='+closed)['body']['slots'],[])
        # Dos clientes eligen a la vez el último puesto libre de un horario: solo uno lo obtiene.
        # Un día hábil distinto del ya lleno y del feriado (según el día de la semana, day(4) y day(5) pueden caer en el mismo lunes).
        other=next(d for d in (self.day(n) for n in range(1,20)) if d not in (day,closed));free=self.request('/api/public/reschedule/'+tokens[first]+'?date='+other)['body']['slots'][0]
        while True:
            left=[s for s in [free] if s in self.request('/api/public/reschedule/'+tokens[first]+'?date='+other)['body']['slots']]
            with app.connect() as c:capacity=len(appointments.technicians(c,appointments.parse_start(other+'T'+free+':00-05:00'),60))
            if capacity<=1:break
            self.book('llena-%s'%capacity,day=other,time=free)
        with patch.object(app.appointment_mail,'send',return_value='sent'):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda t:self.request('/api/public/reschedule',{'token':t,'date':other,'time':free}),[tokens[first],tokens[second]]))
        self.assertEqual(sorted(r['status'] for r in results),[200,409],[r['body'] for r in results])

    def test_expired_link_renewal_limit_and_admin_restore_with_rectification(self):
        aid=self.book('vence');token=self.token_for(aid)
        with app.connect() as c:c.execute("UPDATE appointment_reschedule_links SET expires_at='2000-01-01T00:00:00-05:00'")
        expired=self.request('/api/public/reschedule/'+token);self.assertEqual(expired['status'],410);self.assertIn('caducado',expired['body']['error'])
        with app.connect() as c:code=c.execute('SELECT public_code FROM appointments WHERE id=?',(aid,)).fetchone()[0]
        renewed={}
        with patch.object(app,'no_show_notify',side_effect=lambda c,row,token:(renewed.__setitem__('token',token),('enviado','ok'))[1]):
            wrong=self.request('/api/public/reschedule/renew',{'code':code,'identification':'0999999999'})
            self.assertEqual(renewed,{})
            right=self.request('/api/public/reschedule/renew',{'code':code,'identification':'1710034065'})
        self.assertEqual(wrong['body'],right['body']);self.assertEqual(self.request('/api/public/reschedule/'+renewed['token'])['body']['state'],'ok')
        self.assertEqual(self.request('/api/public/reschedule/'+token)['status'],404)                                   # el anterior queda anulado
        # Límite de reagendamientos por cita.
        with app.connect() as c:c.execute('UPDATE appointments SET reschedules=2 WHERE id=?',(aid,))
        self.assertEqual(self.request('/api/public/reschedule/'+renewed['token'])['body']['state'],'limit')
        with app.connect() as c:c.execute('UPDATE appointments SET reschedules=0 WHERE id=?',(aid,))
        # Restauración administrativa de una inasistencia registrada por error, con rectificación al cliente.
        cookie,csrf=self.login()
        later=self.day(6);slot=[x['time'] for x in self.request('/api/public/appointments/availability?date=%s&service=diagnostico'%later)['body']['slots']][0]
        with app.connect() as c:c.execute("UPDATE appointments SET starts_at=? WHERE id=?",(later+'T'+slot+':00-05:00',aid))
        restored=self.request('/api/appointments/%d'%aid,{'action':'reactivar'},cookie=cookie,csrf=csrf);self.assertEqual(restored['status'],200,restored['body'])
        self.assertEqual(self.status(aid),'confirmada')
        self.assertEqual(self.request('/api/public/reschedule/'+renewed['token'])['status'],404)                       # enlaces anulados al restaurar
        sent=[]
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_institutional',side_effect=lambda *a,**k:sent.append((a,k))):
            rect=self.request('/api/appointments/%d'%aid,{'action':'rectify'},cookie=cookie,csrf=csrf)
        self.assertEqual(rect['status'],200,rect['body']);self.assertIn('Rectificación',sent[0][0][4]);self.assertIn('sigue vigente',sent[0][0][5])
        with app.connect() as c:self.assertIn('no_show_auto',[r[0] for r in c.execute('SELECT event FROM appointment_events WHERE appointment_id=?',(aid,))])   # historial conservado

    def test_mail_template_settings_and_permissions(self):
        aid=self.book('plantilla');self.enable();self.past(aid,30)
        sent=[]
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_institutional',side_effect=lambda *a,**k:sent.append((a,k))):
            with app.connect() as c:app.no_show_tick(c,appointments.now(),force=True)
        args,kwargs=sent[0];subject,body=args[4],args[5]
        self.assertEqual(subject,'PC-DOCTOR S.A. | Reagenda tu cita técnica')
        for text in ('Cliente Ficticio Prueba','Número de cita','Diagnóstico técnico','Fecha y hora reservadas','[Reagendar mi cita](','+593 98 746 0591'):self.assertIn(text,body)
        self.assertTrue(kwargs['private'][0].startswith('http'));self.assertIs(kwargs['review'],False)
        import mailing
        html=mailing.html(body,'Reagenda tu cita técnica');self.assertIn('>Reagendar mi cita</a>',html);self.assertNotIn('[Reagendar mi cita]',html)
        cookie,csrf=self.login()
        self.assertEqual(self.request('/api/appointments/no-show',{'grace':'2'},cookie=cookie,csrf=csrf)['status'],400)
        saved=self.request('/api/appointments/no-show',{'auto':True,'grace':'20','link_days':'5','max_reschedules':'3','mail':True},cookie=cookie,csrf=csrf)['body']['settings']
        self.assertEqual((saved['grace'],saved['link_days'],saved['max_reschedules']),(20,5,3))
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        self.assertEqual(self.request('/api/appointments/no-show',{'auto':False},cookie=cookie,csrf=csrf)['status'],403)
        self.assertEqual(self.request('/api/appointments/%d'%aid,{'action':'send_reschedule'},cookie=cookie,csrf=csrf)['status'],403)
        self.assertEqual(self.request('/reagendar/'+'x'*40)['status'],200)                                                # la página no revela nada por sí sola


if __name__=='__main__':unittest.main()
