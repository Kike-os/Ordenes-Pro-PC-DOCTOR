"""Catálogo de servicios de la Agenda: servicios nuevos sin duplicados, categorías, citas con varios servicios y compra de licencias."""
import pathlib
import sqlite3
import unittest
from datetime import timedelta
import test_app
import app,appointments
app.os.environ.setdefault('LOGIN_CAPTCHA','off')

# Servicios que existían antes del catálogo ampliado: no deben cambiar de nombre, duración ni estado.
PREVIOUS={'diagnostico':('Diagnóstico técnico',60),'portatiles':('Reparación de portátiles',90),'computadoras':('Reparación de computadoras',90),'mantenimiento':('Mantenimiento preventivo',90),
          'bios':('Programación y recuperación de BIOS',90),'electronica':('Reparación electrónica',120),'impresoras':('Servicio para impresoras',90),'otros':('Otros servicios técnicos',60),
          'correctivo':('Mantenimiento correctivo',90),'retiro':('Retiro de Equipos',15),'remota':('Servicio de Administración Remota',60)}
NEW={'licencia':'Compra de licencia de software','bios_desbloqueo':'Desbloqueo de BIOS','bios_clave':'Recuperación de contraseña de BIOS','bios_actualizacion':'Actualización de BIOS',
     'bios_corrupta':'Reparación de BIOS corrupta','sistema_operativo':'Instalación de Windows y otros sistemas operativos','antivirus':'Instalación y configuración de antivirus',
     'bisagras':'Reparación de bisagras','pantallas':'Cambio de pantallas','datos':'Recuperación y respaldo de datos','virus':'Eliminación de virus y malware',
     'playstation':'Mantenimiento de consolas PlayStation','redes':'Configuración de redes y Wi-Fi'}


class AppointmentServicesTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request

    def day(self,offset=1):
        day=appointments.now().date()+timedelta(days=offset)
        while day.weekday()>=5:day+=timedelta(days=1)
        return day.isoformat()

    def slots(self,service,day=None):
        return [s['time'] for s in self.request('/api/public/appointments/availability?date=%s&service=%s'%(day or self.day(),service))['body']['slots']]

    def booking(self,service,time,key,**extra):
        return dict({'name':'Cliente Ficticio Servicios','identification':'1710034065','document_type':'cedula','phone':'0991234567','email':'','device_type':'portatil',
                     'brand':'HP','model':'Ficticio','service':service,'description':'Revisión ficticia','date':self.day(),'time':time,'notes':'','privacy_consent':True,
                     'communications_consent':False,'terms_accept':True,'id_last4':'4065','request_key':'services-request-'+key},**extra)

    def test_catalog_adds_only_missing_services_and_keeps_previous_ones(self):
        with app.connect() as c:rows={r['code']:dict(r) for r in c.execute('SELECT * FROM appointment_services')}
        for code,(label,duration) in PREVIOUS.items():self.assertEqual((rows[code]['label'],rows[code]['duration_minutes'],rows[code]['active']),(label,duration,1),code)
        for code,label in NEW.items():self.assertEqual((rows[code]['label'],rows[code]['active']),(label,1),code)
        labels=[row['label'].lower() for row in rows.values()]
        self.assertEqual(len(labels),len(set(labels)))
        # Equivalentes de servicios existentes: no se crean de nuevo, se encuentran por sus palabras de búsqueda.
        for duplicate in ('asistencia técnica remota','reparación de impresoras','diagnóstico y reparación de placas electrónicas','programación y recuperación de bios'):
            self.assertEqual(sum(label==duplicate for label in labels),1 if duplicate.startswith('programación') else 0,duplicate)
        self.assertIn('asistencia técnica remota',rows['remota']['keywords']);self.assertIn('reparación de impresoras',rows['impresoras']['keywords'])
        public=self.request('/api/public/appointments/services')['body']['services']
        self.assertTrue(all(item['category'] for item in public))
        self.assertEqual({item['category'] for item in public},{'Diagnóstico y reparación','BIOS','Software, sistemas y licencias','Mantenimiento','Redes y asistencia remota','Otros servicios'})

    def test_migration_does_not_duplicate_services_already_created_by_name(self):
        sql=pathlib.Path(app.__file__).with_name('migrations').joinpath('060_appointment_service_catalog.sql').read_text(encoding='utf-8')
        db=sqlite3.connect(':memory:')
        db.executescript("CREATE TABLE appointment_services(code TEXT PRIMARY KEY,label TEXT NOT NULL,duration_minutes INTEGER NOT NULL,active INTEGER NOT NULL DEFAULT 1);"
                         "CREATE TABLE appointments(id INTEGER PRIMARY KEY);CREATE TABLE clients(id INTEGER PRIMARY KEY);"
                         "INSERT INTO appointment_services VALUES ('svc_1a2b3c4d','Reparación de bisagras',45,1),('diagnostico','Diagnóstico técnico',60,0);")
        db.executescript(sql)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM appointment_services WHERE lower(label)=lower('Reparación de bisagras')").fetchone()[0],1)
        self.assertEqual(db.execute("SELECT duration_minutes,active FROM appointment_services WHERE code='svc_1a2b3c4d'").fetchone(),(45,1))
        self.assertEqual(db.execute("SELECT active FROM appointment_services WHERE code='diagnostico'").fetchone()[0],0)
        self.assertIsNone(db.execute("SELECT 1 FROM appointment_services WHERE code='bisagras'").fetchone())

    def test_several_services_in_one_appointment_add_their_durations(self):
        multi=self.slots('diagnostico,bisagras');single=self.slots('diagnostico')
        self.assertTrue(multi);self.assertLess(len(multi),len(single))
        # El último horario ofrecido deja tiempo para los 150 minutos dentro de la jornada.
        with app.connect() as c:close=appointments.day_hours(c,appointments.date.fromisoformat(self.day()))[1]
        last=multi[-1];self.assertLessEqual(int(last[:2])*60+int(last[3:])+150,close.hour*60+close.minute)
        made=self.request('/api/public/appointments',self.booking('diagnostico,bisagras',multi[0],'multi-000000001'))
        self.assertEqual(made['status'],201,made['body']);self.assertEqual(made['body']['duration_minutes'],150)
        cookie,_=self.login()
        detail=self.request('/api/appointments/%d'%made['body']['id'],cookie=cookie)['body']['appointment']
        self.assertEqual((detail['service_code'],detail['duration_minutes'],detail['service_label']),('diagnostico',150,'Diagnóstico técnico + Reparación de bisagras'))
        self.assertEqual([(s['position'],s['service_code'],s['duration_minutes']) for s in detail['services']],[(1,'diagnostico',60),(2,'bisagras',90)])
        # La franja ocupada cubre los 150 minutos: un técnico no queda libre a mitad de la cita.
        with app.connect() as c:
            start=appointments.parse_start(self.day()+'T'+multi[0]+':00-05:00')
            busy=appointments.technicians(c,start+timedelta(minutes=120),30)
            self.assertNotIn(c.execute('SELECT technician_id FROM appointments WHERE id=?',(made['body']['id'],)).fetchone()[0],busy)

    def test_license_purchase_requires_the_license_type(self):
        hour=self.slots('licencia')[0]
        missing=self.request('/api/public/appointments',self.booking('licencia',hour,'license-0000001'))
        self.assertEqual(missing['status'],400);self.assertIn('license_category',missing['body']['fields'])
        bad=self.request('/api/public/appointments',self.booking('licencia',hour,'license-0000002',license_category='inventada'))
        self.assertIn('license_category',bad['body']['fields'])
        made=self.request('/api/public/appointments',self.booking('licencia',hour,'license-0000003',license_category='m365',license_notes='Para 5 equipos ficticios'))
        self.assertEqual(made['status'],201,made['body'])
        with app.connect() as c:
            row=c.execute('SELECT services_summary FROM appointments WHERE id=?',(made['body']['id'],)).fetchone()[0]
            item=c.execute('SELECT detail FROM appointment_service_items WHERE appointment_id=?',(made['body']['id'],)).fetchone()[0]
        self.assertEqual(row,'Compra de licencia de software (Microsoft 365)');self.assertEqual(item,'Microsoft 365 · Para 5 equipos ficticios')

    def test_invalid_combinations_are_rejected(self):
        hour=self.slots('diagnostico')[0]
        for index,service in enumerate(('diagnostico,diagnostico','retiro,diagnostico','diagnostico,portatiles,computadoras,bisagras,pantallas,redes','inexistente','',
                                        'datos,sistema_operativo,bios_corrupta,electronica,portatiles')):
            result=self.request('/api/public/appointments',self.booking(service,hour,'invalid-%07d'%index))
            self.assertEqual(result['status'],400,(service,result));self.assertIn('service',result['body']['fields'],service)
        with app.connect() as c:
            c.execute("UPDATE appointment_services SET active=0 WHERE code='redes'")
            self.assertEqual(c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],0)
        self.assertEqual(self.request('/api/public/appointments',self.booking('redes',hour,'invalid-inactive'))['status'],400)
        self.assertEqual(self.request('/api/public/appointments/availability?date=%s&service=diagnostico,diagnostico'%self.day())['status'],400)

    def test_previous_single_service_appointments_keep_their_label(self):
        made=self.request('/api/public/appointments',self.booking('diagnostico',self.slots('diagnostico')[0],'single-00000001'))['body']
        cookie,_=self.login()
        detail=self.request('/api/appointments/%d'%made['id'],cookie=cookie)['body']['appointment']
        self.assertEqual((detail['service_label'],detail['duration_minutes'],detail['services_summary']),('Diagnóstico técnico',60,''))
        with app.connect() as c:
            # Cita anterior al catálogo ampliado (sin servicios detallados): sigue mostrando su servicio principal.
            c.execute('DELETE FROM appointment_service_items WHERE appointment_id=?',(made['id'],))
        self.assertEqual(self.request('/api/appointments/%d'%made['id'],cookie=cookie)['body']['appointment']['service_label'],'Diagnóstico técnico')


if __name__=='__main__':unittest.main()
