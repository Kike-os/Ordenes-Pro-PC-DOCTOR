"""Feriados de Ecuador: cálculo con traslados, modos de atención, ajustes de administración, conflictos con citas y aviso de ADI."""
import unittest
from datetime import date,datetime
from unittest.mock import patch
import test_app
import app,appointments,holidays
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class HolidayRulesTests(unittest.TestCase):
    def test_national_calendar_matches_the_published_2026_dates_and_transfer_rules(self):
        self.assertEqual(holidays.easter(2026),date(2026,4,5));self.assertEqual(holidays.easter(2027),date(2027,3,28))
        got={item['label']:item['day'] for item in holidays.national(2026)}
        # Calendario publicado para 2026: 24 de mayo (domingo) pasa al lunes 25; 2 y 3 de noviembre (lunes y martes) no se mueven.
        self.assertEqual(got,{'Año Nuevo':date(2026,1,1),'Carnaval (lunes)':date(2026,2,16),'Carnaval (martes)':date(2026,2,17),'Viernes Santo':date(2026,4,3),'Día del Trabajo':date(2026,5,1),'Batalla de Pichincha':date(2026,5,25),
                              'Primer Grito de Independencia':date(2026,8,10),'Independencia de Guayaquil':date(2026,10,9),'Día de Difuntos':date(2026,11,2),'Independencia de Cuenca':date(2026,11,3),'Navidad':date(2026,12,25)})
        # Reglas: sábado → viernes; domingo → lunes; martes → lunes; miércoles y jueves → viernes; Año Nuevo y Navidad no se mueven entre semana.
        self.assertEqual([holidays.observed(date(2027,5,d)).isoformat() for d in (1,2,4,5,6,7)],['2027-04-30','2027-05-03','2027-05-03','2027-05-07','2027-05-07','2027-05-07'])
        self.assertEqual((holidays.observed(date(2026,1,1),False),holidays.observed(date(2029,12,25),False)),(date(2026,1,1),date(2029,12,25)))
        for year in range(2026,2032):
            days=[item['day'] for item in holidays.national(year)];self.assertEqual((len(days),len(set(days))),(11,11),year)


class HolidayAgendaTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def test_modes_special_hours_conflicts_notice_and_permissions(self):
        cookie,csrf=self.login();post=lambda **body:self.request('/api/holidays',body,cookie=cookie,csrf=csrf)
        fixed=datetime(2026,10,13,9,0,tzinfo=appointments.TZ)
        with patch.object(appointments,'now',return_value=fixed),test_app.open_requests():
            service=appointments.services(app.connect())[0]['code']
            slots=lambda day:[s['time'] for s in self.request('/api/appointments/availability?date=%s&service=%s'%(day,service),cookie=cookie)['body']['slots']]
            listing=self.request('/api/holidays?year=2026',cookie=cookie)['body']
            self.assertEqual(len(listing['rows']),11);self.assertTrue(all(not r['decided'] and r['mode']=='normal' and r['scope']=='nacional' for r in listing['rows']))
            pichincha=next(r for r in listing['rows'] if r['label']=='Batalla de Pichincha');self.assertEqual((pichincha['day'],pichincha['moved_from']),('2026-05-25','2026-05-24'))
            # Un feriado calculado sin decisión se atiende con normalidad: los horarios existentes no cambian.
            normal=slots('2026-11-02');self.assertTrue(normal)
            # Cerrado: sin horarios y la página pública nombra el feriado.
            self.assertEqual(post(action='save',day='2026-11-02',label='Día de Difuntos',scope='nacional',mode='cerrado')['status'],200);self.assertEqual(slots('2026-11-02'),[])
            public=self.request('/api/public/appointments/availability?date=2026-11-02&service='+service)['body'];self.assertEqual((public['slots'],public['holiday']),([],{'label':'Día de Difuntos','mode':'cerrado','scope':'nacional'}))
            # Horario especial: solo esas horas, aunque el día de la semana tenga otro horario.
            self.assertEqual(post(action='save',day='2026-11-02',label='Día de Difuntos',scope='nacional',mode='especial',open_time='10:00',close_time='12:00')['status'],200)
            special=slots('2026-11-02');self.assertTrue(special and all('10:00'<=t<'12:00' for t in special));self.assertIn('10:00',special)
            for bad in ({'mode':'especial','open_time':'12:00','close_time':'10:00'},{'mode':'especial','open_time':'10:07','close_time':'12:00'},{'mode':'abierto'},{'scope':'local','mode':'cerrado','place':''},{'label':'x','mode':'cerrado'}):
                self.assertEqual(post(**dict({'action':'save','day':'2026-11-02','label':'Día de Difuntos','scope':'nacional'},**bad))['status'],400)
            # Feriado local con su cantón. «Quitar» en un feriado oficial solo borra su configuración: el feriado permanece en el calendario.
            self.assertEqual(post(action='save',day='2026-12-01',label='Fundación ficticia',scope='local',place='Otavalo',mode='cerrado')['status'],200)
            self.assertEqual(post(action='save',day='2026-12-25',label='Navidad',scope='nacional',mode='especial',open_time='09:00',close_time='13:00')['status'],200)
            self.assertEqual(post(action='remove',day='2026-12-25')['status'],200)
            rows={r['day']:r for r in self.request('/api/holidays?year=2026',cookie=cookie)['body']['rows']}
            self.assertEqual((rows['2026-12-25']['decided'],rows['2026-12-25']['calculated'],rows['2026-12-25']['mode'],rows['2026-12-25']['version']),(False,True,'normal',''))
            self.assertEqual((rows['2026-12-01']['scope_label'],rows['2026-12-01']['calculated'],rows['2026-11-02']['decided']),('Feriado local · Otavalo',False,True))
            self.assertEqual(self.request('/api/holidays?year=2026',cookie=cookie)['body']['hidden'],[])
            # Un día añadido a mano sí se elimina; y un feriado que quedó oculto con la versión anterior se puede restaurar.
            self.assertEqual(post(action='remove',day='2026-12-01')['status'],200);self.assertNotIn('2026-12-01',{r['day'] for r in self.request('/api/holidays?year=2026',cookie=cookie)['body']['rows']})
            with app.connect() as c:c.execute("INSERT INTO appointment_holidays(day,label,mode,scope,hidden) VALUES ('2026-08-10','Primer Grito de Independencia','normal','nacional',1)");c.commit()
            listed=self.request('/api/holidays?year=2026',cookie=cookie)['body'];self.assertEqual([h['day'] for h in listed['hidden']],['2026-08-10']);self.assertNotIn('2026-08-10',{r['day'] for r in listed['rows']})
            post(action='restore',day='2026-08-10');self.assertIn('2026-08-10',{r['day'] for r in self.request('/api/holidays?year=2026',cookie=cookie)['body']['rows']})
            # Dos administradores: guardar o quitar con una versión antigua no pisa el cambio del otro.
            post(action='save',day='2026-05-01',label='Día del Trabajo',scope='nacional',mode='especial',open_time='09:00',close_time='13:00')
            version=next(r for r in self.request('/api/holidays?year=2026',cookie=cookie)['body']['rows'] if r['day']=='2026-05-01')['version'];self.assertTrue(version)
            self.assertEqual(post(action='save',day='2026-05-01',label='Día del Trabajo',scope='nacional',mode='normal',version=version)['status'],200)
            stale=post(action='save',day='2026-05-01',label='Día del Trabajo',scope='nacional',mode='cerrado',version=version);self.assertEqual((stale['status'],stale['body'].get('stale')),(409,True))
            self.assertEqual(post(action='remove',day='2026-05-01',version=version)['status'],409)
            with app.connect() as c:self.assertEqual(c.execute("SELECT mode FROM appointment_holidays WHERE day='2026-05-01'").fetchone()[0],'normal')
            with app.connect() as c:self.assertEqual([r[0] for r in c.execute("SELECT action FROM audit WHERE action IN ('holiday_config_removed','holiday_removed') ORDER BY id")],['holiday_config_removed','holiday_removed'])
            # Una cita existente no se cancela al cerrar el día: se avisa del conflicto.
            day='2026-10-20';time=slots(day)[0]
            made=self.request('/api/appointments/new',{'name':'Cliente Ficticio','identification':'0100000017','terms_accept':True,'id_last4':'0017','phone':'0991234567','email':'cita@example.invalid','device_type':'portatil','brand':'HP','model':'Ficticio','service':service,'date':day,'time':time,'description':'Revisión ficticia','notes':'','request_key':'holiday-appointment-request-1'},cookie=cookie,csrf=csrf)
            self.assertEqual(made['status'],201,made['body'])
            closed=post(action='save',day=day,label='Feriado decretado ficticio',scope='otro',mode='cerrado')['body'];self.assertEqual([c['code'] for c in closed['conflicts']],[made['body']['code']])
            with app.connect() as c:self.assertEqual(c.execute('SELECT status FROM appointments WHERE id=?',(made['body']['id'],)).fetchone()[0],made['body']['status'])
            self.assertEqual(len(self.request('/api/holidays?year=2026',cookie=cookie)['body']['conflicts']),1)
            # Aviso de ADI: aparece el día del feriado aunque no haya citas, con el modo vigente.
            self.assertIsNone(self.request('/api/holidays/today',cookie=cookie)['body']['notice'])
        with patch.object(appointments,'now',return_value=datetime(2026,11,2,9,0,tzinfo=appointments.TZ)):
            today=self.request('/api/holidays/today',cookie=cookie)['body']['notice'];self.assertEqual((today['label'],today['mode'],today['decided']),('Día de Difuntos','especial',True));self.assertIn('ADI informa: Hoy es feriado nacional',today['text']);self.assertIn('10:00 a 12:00',today['text'])
            agenda=self.request('/api/agenda?from=2026-11-01&to=2026-11-30',cookie=cookie)['body'];self.assertEqual([h['label'] for h in agenda['holidays']],['Día de Difuntos','Independencia de Cuenca']);self.assertEqual(agenda['holiday_notice']['day'],'2026-11-02')
        with patch.object(appointments,'now',return_value=datetime(2026,11,3,9,0,tzinfo=appointments.TZ)):
            self.assertIn('Verifica el horario especial de atención de PC-DOCTOR S.A.',self.request('/api/holidays/today',cookie=cookie)['body']['notice']['text'])
        # Solo administración configura; sin sesión no se consulta.
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
        self.assertEqual(post(action='save',day='2026-12-08',label='Otro',scope='otro',mode='cerrado')['status'],403);self.assertEqual(self.request('/api/holidays?year=2026',cookie=cookie)['status'],200)
        self.assertEqual(self.request('/api/holidays')['status'],401)

    def test_duplicates_short_special_hours_and_affected_appointments_are_checked_before_saving(self):
        cookie,csrf=self.login();post=lambda **body:self.request('/api/holidays',body,cookie=cookie,csrf=csrf)
        base={'action':'save','label':'Inventario ficticio','scope':'otro','place':'','mode':'cerrado','open_time':'09:00','close_time':'13:00'}
        # Alta desde el formulario: no pisa una fecha ya registrada ni un feriado calculado; editar la existente sigue permitido.
        self.assertEqual(post(**base,day='2030-07-15',new=True)['status'],200)
        again=post(**base,day='2030-07-15',new=True);self.assertEqual(again['status'],400);self.assertIn('ya está registrado',again['body']['error'])
        official=post(**base,day='2030-12-25',new=True);self.assertEqual(official['status'],400);self.assertIn('Navidad',official['body']['error'])
        self.assertEqual(post(**dict(base,label='Inventario y capacitación'),day='2030-07-15')['status'],200)
        with app.connect() as c:self.assertEqual(tuple(c.execute("SELECT label,COUNT(*) FROM appointment_holidays WHERE day='2030-07-15'").fetchone()),('Inventario y capacitación',1))
        # Horario especial: cierre posterior a la apertura y con sitio para la cita más corta.
        with app.connect() as c:shortest=c.execute('SELECT MIN(duration_minutes) FROM appointment_services WHERE active=1').fetchone()[0]
        special=dict(base,mode='especial',day='2030-07-16')
        self.assertEqual(post(**dict(special,open_time='14:00',close_time='10:00'))['status'],400)
        if shortest>15:
            short=post(**dict(special,open_time='10:00',close_time='10:15'));self.assertEqual(short['status'],400);self.assertIn('%d minutos'%shortest,short['body']['error'])
        self.assertEqual(post(**dict(special,open_time='09:00',close_time='13:00'))['status'],200)
        # «check» informa de las citas que quedarían fuera, sin guardar nada ni tocar la cita.
        import holidays
        from datetime import date
        with app.connect() as c:
            client=c.execute("INSERT INTO clients(name,phone) VALUES ('Cliente Ficticio','0990000000')").lastrowid
            c.execute("INSERT INTO appointments(public_code,manage_token_hash,client_id,customer_name,phone,email,device_type,brand,model,service_code,description,notes,starts_at,duration_minutes,status,privacy_consent,communications_consent,created_at,updated_at) VALUES ('CIT-FICTICIA-01','x',?,'Cliente Ficticio','0990000000','','portatil','HP','','diagnostico','Prueba','','2030-08-05T10:00:00-05:00',60,'confirmada',1,0,'2030-01-01T00:00:00-05:00','2030-01-01T00:00:00-05:00')",(client,));c.commit()
            before=c.execute('SELECT COUNT(*) FROM appointment_holidays').fetchone()[0]
        check=lambda **body:post(**dict(base,**body,action='check'))['body']['affected']
        self.assertEqual([item['code'] for item in check(day='2030-08-05')],['CIT-FICTICIA-01']);self.assertEqual(check(day='2030-08-05',mode='normal'),[])
        self.assertEqual(check(day='2030-08-05',mode='especial',open_time='09:00',close_time='13:00'),[]);self.assertEqual(len(check(day='2030-08-05',mode='especial',open_time='12:00',close_time='16:00')),1)
        self.assertEqual(check(day='2030-08-06'),[]);self.assertEqual(check(day='mal'),[])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM appointment_holidays').fetchone()[0],before);self.assertEqual(c.execute("SELECT status,starts_at FROM appointments WHERE public_code='CIT-FICTICIA-01'").fetchone()[:],('confirmada','2030-08-05T10:00:00-05:00'))
        # Guardar tampoco cancela ni mueve la cita: queda señalada como conflicto para resolverla a mano.
        saved=post(**base,day='2030-08-05');self.assertEqual((saved['status'],[item['code'] for item in saved['body']['conflicts']]),(200,['CIT-FICTICIA-01']))
        with app.connect() as c:self.assertEqual(c.execute("SELECT status FROM appointments WHERE public_code='CIT-FICTICIA-01'").fetchone()[0],'confirmada')
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
        self.assertEqual(post(**dict(base,day='2030-09-01',action='check'))['status'],403)

    def test_adi_reminds_admin_of_upcoming_undecided_holidays(self):
        cookie,csrf=self.login();post=lambda **body:self.request('/api/holidays',body,cookie=cookie,csrf=csrf)
        today=lambda:self.request('/api/holidays/today',cookie=cookie)['body']
        # Diez días antes no se avisa; desde siete días antes sí, con el día de la semana, y «Mañana» la víspera.
        with patch.object(appointments,'now',return_value=datetime(2026,10,23,9,0,tzinfo=appointments.TZ)):self.assertEqual(today()['reminders'],[])
        with patch.object(appointments,'now',return_value=datetime(2026,10,27,9,0,tzinfo=appointments.TZ)):
            found=today()['reminders'];self.assertEqual([(r['day'],r['days_left']) for r in found],[('2026-11-02',6),('2026-11-03',7)])
            self.assertEqual(found[0]['text'],'ADI informa: El lunes 2 de noviembre es feriado nacional (Día de Difuntos) y aún no se ha definido la atención. Revisa el decreto oficial y elige atención normal, horario especial o cerrado.')
            self.assertEqual(len(self.request('/api/agenda?from=2026-10-27&to=2026-11-30',cookie=cookie)['body']['holiday_reminders']),2)
            # Al decidir la atención (cualquier modo), el recordatorio de ese día desaparece; al quitar esa configuración, vuelve.
            post(action='save',day='2026-11-02',label='Día de Difuntos',scope='nacional',mode='normal');self.assertEqual([r['day'] for r in today()['reminders']],['2026-11-03'])
            post(action='save',day='2026-11-03',label='Independencia de Cuenca',scope='nacional',mode='cerrado');self.assertEqual(today()['reminders'],[])
            post(action='remove',day='2026-11-03');self.assertEqual([r['day'] for r in today()['reminders']],['2026-11-03'])
        with patch.object(appointments,'now',return_value=datetime(2026,11,2,9,0,tzinfo=appointments.TZ)):
            body=today();self.assertTrue(body['reminders'][0]['text'].startswith('ADI informa: Mañana es feriado nacional (Independencia de Cuenca)'));self.assertEqual(body['notice']['label'],'Día de Difuntos')
            # Solo administración recibe el recordatorio.
            with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE username='demo'");c.commit()
            self.assertEqual(today()['reminders'],[]);self.assertEqual(self.request('/api/agenda?from=2026-11-01&to=2026-11-30',cookie=cookie)['body']['holiday_reminders'],[])

