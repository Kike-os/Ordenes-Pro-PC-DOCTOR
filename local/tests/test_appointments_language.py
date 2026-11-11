"""1.5.277 · Agenda de Citas pública bilingüe: la página carga i18n.js antes de sus scripts, los horarios oficiales llegan también en inglés
(mismos datos y zona horaria), la reserva guarda el idioma validado en el servidor sin tocar la autorización ni los estados, y i18n.js
traduce las cuatro etapas, validaciones y mensajes del servidor sin tocar datos del cliente. Base temporal y datos ficticios."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
import test_app
import test_appointment_authorization as authorization
import app,appointments,business_hours

STATIC=Path(__file__).resolve().parents[1]/'static'
SPANISH=re.compile(r'\b(lunes|martes|sábado|domingo|Abierto|Cerrado|abre|hasta las|Atención|a\. m\.|p\. m\.)\b')


class AppointmentLanguageTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login
    _base=vars(authorization.AppointmentAuthorizationTests);day=_base['day'];slots=_base['slots'];booking=_base['booking']

    def test_page_loads_i18n_before_its_scripts_and_opts_in(self):
        page=self.request('/citas')['body']
        page=page if isinstance(page,str) else page.decode()
        self.assertIn('data-i18n-public',page)
        self.assertLess(page.index('/static/i18n.js'),page.index('/static/appointments.js'))
        self.assertNotRegex(page,r'<script[^>]+defer[^>]+/static/i18n\.js')  # sin defer: el idioma se aplica antes de mostrar el formulario
        self.assertIn('id="booking-terms-lang"',page)

    def test_public_hours_include_english_with_the_same_schedule(self):
        info=self.request('/api/public/hours')['body'];en=info['en']
        self.assertTrue(en['presencial'] and en['status']['label'])
        self.assertEqual(en['status']['open'],info['status']['open'])  # el mismo estado real
        for text in (en['presencial'],en['status']['label'],en['request_limits'],en['virtual_message']):self.assertIsNone(SPANISH.search(text),text)
        self.assertIn('Monday to Friday from 7:45 AM to 8:30 PM',en['presencial'])  # horarios oficiales sin cambios
        self.assertIn('lunes a viernes de 7:45 a. m. a 8:30 p. m.',info['presencial'])
        self.assertEqual(info['timezone'],'America/Guayaquil')

    def test_booking_stores_the_validated_language_without_touching_the_authorization(self):
        hours=self.slots()
        for index,(locale,expected) in enumerate((('en-US','en-US'),(None,'es-EC'),('fr-FR','es-EC'),('en-US; DROP TABLE','es-EC'))):
            extra={} if locale is None else {'locale':locale}
            result=self.request('/api/public/appointments',self.booking(hours[index*8],'lang-%04d-000000'%index,**extra))
            self.assertEqual(result['status'],201,result['body'])
            self.assertEqual(result['body']['message'],appointments.AUTHORIZED_MESSAGE)  # el servidor no cambia sus mensajes: los traduce la página
            with app.connect() as c:
                row=c.execute('SELECT language,status FROM appointments WHERE public_code=?',(result['body']['code'],)).fetchone()
                auth=c.execute('SELECT terms_version,express_consent,channel FROM appointment_authorizations a JOIN appointments p ON p.id=a.appointment_id WHERE p.public_code=?',(result['body']['code'],)).fetchone()
            self.assertEqual((row['language'],row['status']),(expected,'confirmada'),locale)
            self.assertEqual((auth['express_consent'],auth['channel']),(1,'en_linea'))
        cookie,csrf=self.login()
        detail=self.request('/api/appointments',cookie=cookie)
        self.assertEqual(detail['status'],200)

    @unittest.skipUnless(shutil.which('node'),'node no disponible')
    def test_booking_texts_translate_and_customer_data_stays_intact(self):
        harness=r"""
const store={'ordenes-pro:idioma':'en-US'};globalThis.localStorage={getItem:k=>store[k]??null,setItem:(k,v)=>{store[k]=String(v)},removeItem:k=>{delete store[k]}};
globalThis.document={documentElement:{lang:'',dataset:{},classList:{add(){},remove(){}}},readyState:'complete',querySelectorAll:()=>[],addEventListener(){},dispatchEvent(){}};globalThis.window=globalThis;globalThis.CustomEvent=class{};
require(process.argv[1]);const i=window.i18n,t=x=>i.tr(x);
console.log(JSON.stringify({table:['Agendamiento de Citas Técnicas','Selecciona el servicio, el equipo y el horario que mejor se adapte a tus necesidades.','Tus datos','Tu equipo','Fecha y hora','Confirmación','Nombre y apellidos','Tipo de identificación','Cédula','RUC','Pasaporte','Número de cédula','Teléfono / WhatsApp','Correo electrónico (opcional)','Cancelar','Anterior','Siguiente','Confirmar cita','Tu cita técnica se ha agendado correctamente'].map(t),
 checks:[t('Los campos marcados con * son obligatorios.'),t('El número de cédula no es válido. Revisa los dígitos ingresados.'),t('10 dígitos, sin guiones ni espacios.'),
  t('Ese espacio no está disponible. Próximo espacio libre: 13/11 3:30 p. m..'),t('Ese día es feriado (Día de los Difuntos) y el taller no atiende. Elige otra fecha.'),
  t('Número válido · Ecuador · celular'),t('2 servicios · duración estimada 1 h 30 min'),t('Si el número corresponde a una orden con correo registrado, acabamos de enviar un código de 6 dígitos a ese correo. Caduca en 15 minutos.')],
 data:[t('María José Pérez'),t('Lenovo'),t('PCD-20261111-0001'),t('Mi portátil no enciende')],
 known:[i.known('Tu equipo'),i.known('María José Pérez')],english:(i.set('es-EC'),[i.english('Diagnóstico técnico'),t('Tu equipo')])}));"""
        result=subprocess.run(['node','-e',harness,str(STATIC/'i18n.js')],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr);out=json.loads(result.stdout)
        self.assertEqual(out['table'],['Technical Service Appointment Booking','Select the service, device, and appointment time that best suits your needs.','Your Information','Your Device','Date & Time','Confirmation',
                                       'Full Name','Identification Type','National ID','Tax ID (RUC)','Passport','National ID Number','Phone / WhatsApp','Email Address (Optional)','Cancel','Previous','Next','Confirm Appointment','Appointment Successfully Booked'])
        self.assertEqual(out['checks'],['Fields marked with * are required.','Please enter a valid Ecuadorian national ID number. Check the digits entered.','10 digits, without hyphens or spaces.',
                                        'That time is not available. Next open time: 11/13 3:30 PM.','That day is a holiday (Día de los Difuntos) and the shop is closed. Choose another date.',
                                        'Valid number · Ecuador · mobile','2 services · estimated duration 1 h 30 min',
                                        'If the number matches an order with a registered email, we just sent a 6-digit code to that email. It expires in 15 minutes.'])
        self.assertEqual(out['data'],['María José Pérez','Lenovo','PCD-20261111-0001','Mi portátil no enciende'])  # datos del cliente intactos
        self.assertEqual(out['known'],[True,False])
        self.assertEqual(out['english'],['Technical diagnosis','Tu equipo'])  # english() no cambia el idioma activo


if __name__=='__main__':
    unittest.main()
