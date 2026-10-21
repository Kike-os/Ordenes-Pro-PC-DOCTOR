"""Configuración de la agenda: eliminar solo servicios sin citas, al menos un servicio activo, mensajes claros por día y técnico, guardado
todo o nada, margen y horarios que se conservan al recargar. Base temporal y datos ficticios."""
import unittest
import test_app
import app,appointments
import test_appointment_services as base_services


class AgendaSettingsTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login;request=test_app.SecurityTests.request
    day=base_services.AppointmentServicesTests.day;booking=base_services.AppointmentServicesTests.booking;slots=base_services.AppointmentServicesTests.slots

    def config(self,**body):
        cookie,csrf=self.session;return self.request('/api/appointments/config',body,cookie=cookie,csrf=csrf)

    def settings(self):
        with app.connect() as c:return appointments.settings(c)

    def test_service_is_deleted_only_when_never_used_and_one_must_stay_active(self):
        self.session=self.login()
        created=self.config(new_service={'label':'Servicio ficticio sin uso','duration_minutes':45})['body']['settings']['services']
        code=next(s['code'] for s in created if s['label']=='Servicio ficticio sin uso')
        self.assertEqual(self.config(remove_service=code)['status'],200)
        self.assertNotIn(code,[s['code'] for s in self.settings()['services']])
        # Un servicio con citas no se elimina: su historial se conserva.
        slot=self.slots('diagnostico')[0]
        self.assertEqual(self.request('/api/public/appointments',self.booking('diagnostico',slot,'agenda-settings-1'))['status'],201)
        used=self.config(remove_service='diagnostico');self.assertEqual(used['status'],409);self.assertIn('Desactívalo',used['body']['error'])
        self.assertIn('diagnostico',[s['code'] for s in self.settings()['services']])
        # No se puede dejar la agenda sin ningún servicio activo.
        everything=[{'code':s['code'],'label':s['label'],'duration_minutes':s['duration_minutes'],'active':False} for s in self.settings()['services']]
        refused=self.config(services=everything);self.assertEqual(refused['status'],400);self.assertIn('al menos un servicio activo',refused['body']['error'])
        self.assertTrue(any(s['active'] for s in self.settings()['services']))

    def test_clear_messages_and_all_or_nothing_save(self):
        self.session=self.login()
        before=self.settings()
        hours=[{'weekday':h['weekday'],'start_time':'08:00','end_time':'18:00','enabled':True} for h in before['hours']]
        bad=[dict(h) for h in hours];bad[1]=dict(bad[1],start_time='19:00',end_time='18:00')
        result=self.config(hours=bad);self.assertEqual(result['status'],400);self.assertIn('martes: la hora de cierre debe ser posterior',result['body']['error'])
        self.assertEqual([h['start_time'] for h in self.settings()['hours']],[h['start_time'] for h in before['hours']])  # nada a medias
        # Horarios válidos + un servicio inválido: tampoco se guardan los horarios.
        broken=self.config(hours=hours,services=[{'code':'diagnostico','label':'Diagnóstico técnico','duration_minutes':17,'active':True}])
        self.assertEqual(broken['status'],400);self.assertEqual([h['start_time'] for h in self.settings()['hours']],[h['start_time'] for h in before['hours']])
        ok=self.config(hours=hours,buffer='20',confirmation='manual');self.assertEqual(ok['status'],200)
        after=self.settings()  # «recargar»: se leen de nuevo desde la base
        self.assertEqual({(h['start_time'],h['end_time']) for h in after['hours']},{('08:00','18:00')});self.assertEqual((after['buffer'],after['confirmation']),(20,'manual'))
        with app.connect() as c:
            tech=c.execute("SELECT id,name FROM users WHERE role IN ('administrador','tecnico') LIMIT 1").fetchone()
        staff=self.config(staff_hours=[{'technician_id':tech['id'],'weekday':6,'start_time':'12:00','end_time':'11:00','enabled':True}])
        self.assertEqual(staff['status'],400);self.assertIn('Horario de '+tech['name']+' del domingo',staff['body']['error'])


if __name__=='__main__':unittest.main()
