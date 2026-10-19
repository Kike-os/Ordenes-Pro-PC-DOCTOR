"""Autorización digital de citas: casilla de condiciones y 4 dígitos obligatorios, evidencia inmutable y ninguna cita confirmada sin ella."""
import concurrent.futures
import re
import sqlite3
import unittest
from datetime import timedelta
import test_app
import app,appointments
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class AppointmentAuthorizationTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request

    def day(self,offset=1):
        day=appointments.now().date()+timedelta(days=offset)
        while day.weekday()>=5:day+=timedelta(days=1)
        return day.isoformat()

    def slots(self,day=None):
        return [s['time'] for s in self.request('/api/public/appointments/availability?date=%s&service=diagnostico'%(day or self.day()))['body']['slots']]

    def booking(self,time,key,**extra):
        return dict({'name':'Cliente Ficticio Prueba','identification':'1710034065','document_type':'cedula','phone':'0991234567','email':'','device_type':'portatil',
                     'brand':'HP','model':'Ficticio','service':'diagnostico','description':'Revisión ficticia','date':self.day(),'time':time,'notes':'',
                     'privacy_consent':True,'communications_consent':False,'terms_accept':True,'id_last4':'4065','request_key':'authorization-request-'+key},**extra)

    def count(self,table):
        with app.connect() as c:return c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]

    def test_checkbox_and_four_digits_are_required(self):
        hour=self.slots()[0]
        cases=((dict(terms_accept=False),'terms_accept'),(dict(terms_accept='true'),'terms_accept'),(dict(id_last4=''),'id_last4'),(dict(id_last4='406'),'id_last4'),
               (dict(id_last4='40655'),'id_last4'),(dict(id_last4='40a5'),'id_last4'),(dict(id_last4=' 4065'),'id_last4'),(dict(id_last4='١٢٣٤'),'id_last4'),
               (dict(id_last4='1234'),'id_last4'),(dict(terms_id='otra-version'),'terms_accept'))
        for index,(extra,field) in enumerate(cases):
            result=self.request('/api/public/appointments',self.booking(hour,'bad-%04d-0000'%index,**extra))
            self.assertEqual(result['status'],400,(extra,result));self.assertIn(field,result['body']['fields'],extra)
        self.assertEqual(self.count('appointments'),0);self.assertEqual(self.count('appointment_authorizations'),0)
        self.assertEqual(appointments.last4_error('4065','1710034065','cedula'),'')
        self.assertEqual(appointments.last4_error('0017','0100000017001','ruc'),'')
        self.assertEqual(appointments.last4_error('3456','AB-123456','pasaporte'),'')
        self.assertTrue(appointments.last4_error('0000','0100000017','cedula'))

    def test_valid_booking_records_complete_evidence(self):
        result=self.request('/api/public/appointments',self.booking(self.slots()[0],'valid-000000001'))
        self.assertEqual(result['status'],201,result['body']);body=result['body']
        self.assertEqual(body['status'],'confirmada')
        self.assertEqual(body['message'],'Cita confirmada correctamente. Su aceptación ha sido registrada con fecha, hora e identificador de autorización.')
        self.assertRegex(body['authorization']['authorization_id'],r'^AUT-[0-9A-F]{8}-[0-9A-F]{4}-4[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$')
        self.assertNotIn('id_last4',body['authorization'])
        with app.connect() as c:
            row=dict(c.execute('SELECT * FROM appointment_authorizations').fetchone())
            appointment=c.execute('SELECT id,client_id,public_code FROM appointments').fetchone()
            terms=app.service_terms.current(c,app.reception_now())
        self.assertEqual((row['appointment_id'],row['client_id'],row['timezone'],row['express_consent'],row['id_last4'],row['channel'],row['recorded_by']),
                         (appointment['id'],appointment['client_id'],'America/Guayaquil',1,'4065','en_linea',None))
        self.assertEqual((row['terms_id'],row['terms_version'],row['terms_hash']),(terms['id'],terms['version'],terms['content_hash']))
        self.assertTrue(row['accepted_at'].endswith('-05:00'))
        self.assertIn(appointment['public_code'],row['snapshot'])
        # Una repetición de la misma solicitud no crea otra cita ni otra autorización.
        again=self.request('/api/public/appointments',self.booking(self.slots()[0] if self.slots() else '09:00','valid-000000001'))
        self.assertTrue(again['body'].get('duplicate'));self.assertEqual(self.count('appointment_authorizations'),1)

    def test_evidence_is_immutable_and_survives_changes(self):
        made=self.request('/api/public/appointments',self.booking(self.slots()[0],'immutable-000001'))['body']
        cookie,csrf=self.login()
        with app.connect() as c:
            original=c.execute('SELECT * FROM appointment_authorizations').fetchone()
            for sql in ("UPDATE appointment_authorizations SET id_last4='0000'","UPDATE appointment_authorizations SET terms_version='X'","DELETE FROM appointment_authorizations"):
                with self.assertRaises(sqlite3.IntegrityError):c.execute(sql)
        later=self.day(3);hour=self.slots(later)[1]
        moved=self.request('/api/appointments/%d'%made['id'],{'action':'reschedule','starts_at':later+'T'+hour+':00-05:00'},cookie=cookie,csrf=csrf)
        self.assertEqual(moved['status'],200,moved['body'])
        with app.connect() as c:
            self.assertEqual(tuple(c.execute('SELECT * FROM appointment_authorizations').fetchone()),tuple(original))
            self.assertNotEqual(c.execute('SELECT starts_at FROM appointments WHERE id=?',(made['id'],)).fetchone()[0],made['starts_at'])
        detail=self.request('/api/appointments/%d'%made['id'],cookie=cookie)['body']['appointment']['authorization']
        self.assertEqual((detail['authorization_id'],detail['snapshot']['starts_at'],detail['id_last4']),(made['authorization']['authorization_id'],made['starts_at'],'4065'))

    def test_no_confirmed_appointment_without_authorization(self):
        cookie,csrf=self.login()
        self.request('/api/appointments/config',{'confirmation':'manual'},cookie=cookie,csrf=csrf)
        with app.connect() as c:
            # Cita anterior a la autorización digital (sin evidencia): la base de datos impide confirmarla directamente.
            client=c.execute("INSERT INTO clients(name,phone,identification) VALUES ('Cliente Antiguo Ficticio','0990000000','0100000017')").lastrowid
            legacy=c.execute("INSERT INTO appointments(public_code,manage_token_hash,client_id,customer_name,identification,phone,device_type,service_code,description,starts_at,duration_minutes,status,privacy_consent,created_at,updated_at) VALUES ('CIT-ANTIGUA-01','h1',?,'Cliente Antiguo Ficticio','0100000017','0990000000','portatil','diagnostico','Prueba',?,60,'solicitada',1,'x','x')",(client,self.day(2)+'T10:00:00-05:00')).lastrowid
            with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE appointments SET status='confirmada' WHERE id=?",(legacy,))
        refused=self.request('/api/appointments/%d'%legacy,{'action':'confirmada'},cookie=cookie,csrf=csrf)
        self.assertEqual((refused['status'],refused['body']['needs_authorization']),(409,True))
        wrong=self.request('/api/appointments/%d'%legacy,{'action':'confirmada','terms_accept':True,'id_last4':'9999'},cookie=cookie,csrf=csrf)
        self.assertIn('fields',wrong['body'],wrong)
        self.assertEqual((wrong['status'],list(wrong['body']['fields'])),(409,['id_last4']))
        self.assertEqual(self.count('appointment_authorizations'),0)
        ok=self.request('/api/appointments/%d'%legacy,{'action':'confirmada','terms_accept':True,'id_last4':'0017'},cookie=cookie,csrf=csrf)
        self.assertEqual(ok['status'],200,ok['body'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM appointments WHERE id=?',(legacy,)).fetchone()[0],'confirmada')
            evidence=c.execute('SELECT channel,recorded_by FROM appointment_authorizations WHERE appointment_id=?',(legacy,)).fetchone()
            self.assertEqual((evidence['channel'],evidence['recorded_by']),('personal',self.uid))
            # Una cita confirmada antes de existir la autorización no recibe una retroactiva: al reactivarla vuelve como solicitud.
            old=c.execute("INSERT INTO appointments(public_code,manage_token_hash,client_id,customer_name,phone,device_type,service_code,description,starts_at,duration_minutes,status,privacy_consent,created_at,updated_at) VALUES ('CIT-ANTIGUA-02','h2',?,'Cliente Antiguo Ficticio','0990000000','portatil','diagnostico','Prueba',?,60,'cancelada',1,'x','x')",(client,self.day(4)+'T11:00:00-05:00')).lastrowid
        back=self.request('/api/appointments/%d'%old,{'action':'reactivar'},cookie=cookie,csrf=csrf)
        self.assertEqual((back['status'],back['body']['status']),(200,'solicitada'))
        self.assertEqual(self.count('appointment_authorizations'),1)

    def test_staff_booking_requires_authorization_and_technicians_do_not_see_digits(self):
        cookie,csrf=self.login()
        data=self.booking(self.slots()[0],'staff-0000000001')
        refused=self.request('/api/appointments/new',dict(data,terms_accept=False,id_last4=''),cookie=cookie,csrf=csrf)
        self.assertEqual(refused['status'],400);self.assertEqual(set(refused['body']['fields']),{'terms_accept','id_last4'})
        made=self.request('/api/appointments/new',data,cookie=cookie,csrf=csrf)['body']
        self.assertEqual(made['status'],'confirmada')
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        seen=self.request('/api/appointments/%d'%made['id'],cookie=cookie)['body']['appointment']['authorization']
        self.assertEqual(seen['channel'],'personal');self.assertNotIn('id_last4',seen);self.assertNotIn('snapshot',seen)
        self.assertEqual(self.request('/api/appointments/%d'%made['id'])['status'],401)

    def test_without_published_terms_nothing_is_authorized(self):
        from unittest.mock import patch
        with patch.object(appointments,'current_terms',return_value=None):
            result=self.request('/api/public/appointments',self.booking(self.slots()[0],'noterms-00000001'))
        self.assertEqual(result['status'],400);self.assertIn('No hay condiciones',result['body']['fields']['terms_accept'])
        self.assertEqual(self.count('appointments'),0)

    def test_simultaneous_bookings_keep_one_authorization_each(self):
        hour=self.slots()[0]
        with app.connect() as c:capacity=len(appointments.technicians(c,appointments.parse_start(self.day()+'T'+hour+':00-05:00'),60))
        def book(index):return self.request('/api/public/appointments',self.booking(hour,'parallel-%08d'%index,phone='09912345%02d'%index))
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(book,range(6)))
        created=[r for r in results if r['status']==201]
        self.assertEqual(len(created),capacity,[r['status'] for r in results]);self.assertTrue(all(r['status'] in (201,409) for r in results))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],capacity)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM appointment_authorizations').fetchone()[0],capacity)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM appointments a WHERE NOT EXISTS (SELECT 1 FROM appointment_authorizations z WHERE z.appointment_id=a.id)').fetchone()[0],0)
        self.assertEqual(len({r['body']['authorization']['authorization_id'] for r in created}),capacity)


if __name__=='__main__':unittest.main()
