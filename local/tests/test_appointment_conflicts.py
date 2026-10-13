"""Agenda sin solapamientos: margen entre citas, alternativas, reprogramación, cancelación y reservas simultáneas."""
import unittest
from datetime import timedelta
import test_app
import app,appointments
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class AppointmentConflictTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def day(self):
        """Primer día laborable (lunes a viernes) a partir de pasado mañana."""
        current=appointments.now().date()+timedelta(days=2)
        while current.weekday()>4:current+=timedelta(days=1)
        return current.isoformat()

    def book(self,day,hour,key,service='diagnostico',**extra):
        body=dict({'name':'Cliente ficticio '+key,'phone':'0991234567','email':'','identification':'1710034065','document_type':'cedula','device_type':'portatil','brand':'HP','model':'X','service':service,'description':'Revisión de prueba','date':day,'time':hour,'notes':'','privacy_consent':True,'communications_consent':False,'request_key':'conflict-request-key-000-'+key},**extra)
        return self.request('/api/public/appointments',body)

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        with app.connect() as c:
            # Bloque de 60 minutos: 45 de atención y 15 de margen (el margen por defecto).
            c.execute("UPDATE appointment_services SET duration_minutes=45 WHERE code='diagnostico'")
            self.assertEqual(appointments.buffer_minutes(c),15)

    def slots(self,day,service='diagnostico'):
        return [item['time'] for item in self.request('/api/public/appointments/availability?date='+day+'&service='+service)['body']['slots']]

    def test_block_of_sixty_minutes_with_alternatives(self):
        day=self.day();before=self.request('/api/public/appointments/pulse')['body']['pulse']
        self.assertIn('10:00',self.slots(day));self.assertIn('10:30',self.slots(day))
        first=self.book(day,'10:00','a');self.assertEqual(first['status'],201)
        # 10:00–10:45 con margen hasta las 11:00: el mismo técnico no recibe 10:30 ni 09:30 (que terminaría a las 10:15 más margen).
        free=self.slots(day);self.assertNotIn('10:00',free);self.assertNotIn('10:30',free);self.assertNotIn('09:30',free);self.assertIn('11:00',free);self.assertIn('09:00',free)
        self.assertNotEqual(self.request('/api/public/appointments/pulse')['body']['pulse'],before)
        clash=self.book(day,'10:30','b')
        self.assertEqual(clash['status'],409);self.assertEqual(clash['body']['alternatives'][0],{'date':day,'time':'11:00','label':'11:00 a. m.'})
        self.assertEqual(clash['body']['error'],'El horario seleccionado ya no está disponible. Puede agendar su cita a las 11:00 a. m. o seleccionar otro horario.')
        # 10:15 y 10:45 caen dentro del bloque de la primera cita: tampoco están libres. Una hora fuera de la rejilla (10:10) nunca se acepta.
        self.assertNotIn('10:15',free);self.assertNotIn('10:45',free)
        self.assertEqual(self.book(day,'10:10','c')['status'],400)
        self.assertEqual(self.book(day,'11:00','d')['status'],201)
        # La misma solicitud repetida no crea otra cita.
        again=self.book(day,'10:00','a');self.assertEqual((again['status'],again['body'].get('duplicate')),(200,True))
        with app.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],2)

    def test_simultaneous_requests_only_one_wins(self):
        day=self.day();results=[self.book(day,'15:00','s%d'%index)['status'] for index in range(4)]
        self.assertEqual(sorted(results),[201,409,409,409])
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM appointments WHERE starts_at LIKE ?",(day+'T15:00%',)).fetchone()[0],1)

    def test_second_technician_adds_capacity_and_durations_differ(self):
        day=self.day();self.assertEqual(self.book(day,'10:00','t1')['status'],201)
        with app.connect() as c:
            other=c.execute("INSERT INTO users(username,email,name,password_hash,role,active,created_at,approval) VALUES ('tec2','tec2@example.invalid','Técnica Dos','x','tecnico',1,0,'approved')").lastrowid
            appointments.ensure_staff_hours(c,other)
        # Con dos técnicos hay capacidad real para una segunda cita a la misma hora, y no para una tercera.
        second=self.book(day,'10:00','t2');self.assertEqual(second['status'],201);self.assertEqual(self.book(day,'10:00','t3')['status'],409)
        with app.connect() as c:self.assertEqual(len({row[0] for row in c.execute("SELECT technician_id FROM appointments WHERE starts_at LIKE ?",(day+'T10:00%',))}),2)
        # Un servicio más largo (90 min) bloquea más: 13:00–14:30 con margen hasta 14:45 deja libre 15:00 pero no 14:30 para ese técnico.
        with app.connect() as c:c.execute("UPDATE users SET active=0 WHERE id=?",(other,))
        self.assertEqual(self.book(day,'13:00','long',service='portatiles')['status'],201)
        free=self.slots(day);self.assertNotIn('13:30',free);self.assertNotIn('14:00',free);self.assertNotIn('14:30',free);self.assertIn('15:00',free)
        # Cerca del cierre (17:00): un servicio de 45 minutos cabe a las 16:00 pero no a las 16:30.
        self.assertIn('16:00',free);self.assertNotIn('16:30',free)

    def test_reschedule_cancel_and_margin_setting(self):
        cookie,csrf=self.login();day=self.day()
        one=self.book(day,'10:00','r1')['body'];two=self.book(day,'12:00','r2')['body']
        manage=lambda item,body:self.request('/api/public/appointments/manage',dict(body,code=item['code'],token=item['manage_token']))
        # Reprogramar sobre una franja ocupada: aviso claro (no un error interno) y la cita no se mueve.
        blocked=manage(two,{'action':'reschedule','starts_at':day+'T10:30:00-05:00'})
        self.assertEqual(blocked['status'],409);self.assertIn('no está disponible',blocked['body']['error']);self.assertTrue(blocked['body']['alternatives'])
        with app.connect() as c:self.assertEqual(c.execute('SELECT starts_at FROM appointments WHERE id=?',(two['id'],)).fetchone()[0][:16],day+'T12:00')
        # Reprogramar a una franja libre libera la anterior.
        self.assertEqual(manage(two,{'action':'reschedule','starts_at':day+'T14:00:00-05:00'})['status'],200)
        free=self.slots(day);self.assertIn('12:00',free);self.assertNotIn('14:00',free)
        # Cancelar libera el espacio y conserva el historial.
        self.assertEqual(manage(one,{'action':'cancel'})['status'],200);self.assertIn('10:00',self.slots(day))
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT status FROM appointments WHERE id=?",(one['id'],)).fetchone()[0],'cancelada')
            self.assertGreaterEqual(c.execute('SELECT COUNT(*) FROM appointment_events WHERE appointment_id=?',(one['id'],)).fetchone()[0],2)
        # El margen es configurable por administración; con margen 0 vuelve a quedar libre la media hora contigua.
        self.assertEqual(self.book(day,'10:00','r3')['status'],201);self.assertNotIn('10:30',self.slots(day))
        self.assertEqual(self.request('/api/appointments/config',{'buffer':'7'},cookie=cookie,csrf=csrf)['status'],400)
        self.assertEqual(self.request('/api/appointments/config',{'buffer':'0'},cookie=cookie,csrf=csrf)['status'],200)
        self.assertNotIn('10:30',self.slots(day))  # 10:00–10:45 sigue ocupando 10:30
        self.assertIn('11:00',self.slots(day))
        with app.connect() as c:self.assertEqual(appointments.settings(c)['buffer'],0)


if __name__=='__main__':unittest.main()


class OfficialHoursAgendaTests(unittest.TestCase):
    """Agenda con el horario oficial: primera cita a las 7:45 y hora límite diaria para solicitar citas en línea."""
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login
    day=AppointmentConflictTests.day;book=AppointmentConflictTests.book;slots=AppointmentConflictTests.slots
    def setUp(self):
        AppointmentConflictTests.setUp(self)
        with app.connect() as c:
            for weekday,(start,end) in enumerate([('07:45','20:30')]*5+[('09:00','21:00'),('10:00','17:00')]):
                c.execute('UPDATE appointment_hours SET start_time=?,end_time=?,enabled=1 WHERE weekday=?',(start,end,weekday));c.execute('UPDATE appointment_staff_hours SET start_time=?,end_time=?,enabled=1 WHERE weekday=?',(start,end,weekday))

    def test_slots_follow_official_hours_and_request_deadline(self):
        from datetime import datetime
        from unittest.mock import patch
        import business_hours
        day=self.day();free=self.slots(day)
        self.assertEqual((free[0],free[1],free[-1]),('07:45','08:00','19:45'))  # 45 minutos caben hasta las 20:30
        self.assertEqual(self.book(day,'07:45','early')['status'],201);self.assertNotIn('08:30',self.slots(day));self.assertIn('08:45',self.slots(day))
        # Pasada la hora límite del día (23:00 de lunes a viernes) no se aceptan solicitudes en línea; antes sí.
        late=datetime(2026,10,12,23,5,tzinfo=business_hours.ECUADOR_TZ)
        with patch.object(app,'reception_now',return_value=late):
            closed=self.book(day,'12:00','late')
        self.assertEqual((closed['status'],closed['body'].get('requests_closed')),(409,True));self.assertIn('11:00 p. m.',closed['body']['error'])
        self.assertEqual(self.book(day,'12:00','ontime')['status'],201)
        public=self.request('/api/public/hours')['body'];self.assertIn('lunes a viernes hasta las 11:00 p. m.',public['request_limits'])
