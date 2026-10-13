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
            # Feriado local con su cantón; ocultar y restaurar uno calculado.
            self.assertEqual(post(action='save',day='2026-12-01',label='Fundación ficticia',scope='local',place='Otavalo',mode='cerrado')['status'],200)
            self.assertEqual(post(action='remove',day='2026-12-25')['status'],200)
            rows={r['day']:r for r in self.request('/api/holidays?year=2026',cookie=cookie)['body']['rows']}
            self.assertNotIn('2026-12-25',rows);self.assertEqual((rows['2026-12-01']['scope_label'],rows['2026-12-01']['calculated'],rows['2026-11-02']['decided']),('Feriado local · Otavalo',False,True))
            self.assertEqual([h['day'] for h in self.request('/api/holidays?year=2026',cookie=cookie)['body']['hidden']],['2026-12-25'])
            post(action='restore',day='2026-12-25');self.assertIn('2026-12-25',{r['day'] for r in self.request('/api/holidays?year=2026',cookie=cookie)['body']['rows']})
            # Una cita existente no se cancela al cerrar el día: se avisa del conflicto.
            day='2026-10-20';time=slots(day)[0]
            made=self.request('/api/appointments/new',{'name':'Cliente Ficticio','identification':'0100000017','phone':'0991234567','email':'cita@example.invalid','device_type':'portatil','brand':'HP','model':'Ficticio','service':service,'date':day,'time':time,'description':'Revisión ficticia','notes':'','request_key':'holiday-appointment-request-1'},cookie=cookie,csrf=csrf)
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
