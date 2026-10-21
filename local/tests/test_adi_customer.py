"""ADI Customer Intelligence: ADI consulta el catálogo real (licencias y servicios) y la agenda con herramientas de solo lectura,
mantiene el contexto de la conversación, propone la reserva sin crearla, no niega productos cuando una consulta falla y nunca entrega
costos ni credenciales. OpenAI simulado como la API Responses (llamada a herramienta → respuesta). Base temporal y datos ficticios."""
import json
import unittest
from unittest.mock import patch
import test_app,test_licenses
import app,adi,licenses

KEY={'OPENAI_API_KEY':'sk-prueba-ficticia-123'}


class FakeModel:
    """Primera petición: pide la herramienta indicada. Segunda: responde con lo que devolvió la herramienta (o con un texto fijo)."""
    def __init__(self,tool=None,args=None,answer=None):
        self.tool,self.args,self.answer,self.calls=tool,args or {},answer,[]
    def __call__(self,api_key,payload):
        self.calls.append(payload)
        if self.tool and 'previous_response_id' not in payload:
            return {'id':'resp_1','output':[{'type':'function_call','call_id':'call_1','name':self.tool,'arguments':json.dumps(self.args)}]}
        self.tool_output=json.loads(payload['input'][0]['output']) if 'previous_response_id' in payload else None
        text=self.answer(self.tool_output) if callable(self.answer) else (self.answer or 'Respuesta ficticia.')
        return {'id':'resp_2','output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}


class AdiCustomerTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data
    _b=vars(test_licenses.LicenseProTests);admin=_b['admin'];new_product=_b['new_product'];client_id=_b['client_id'];today=_b['today']

    def catalog(self):
        self.admin()
        eset=self.new_product(name='ESET NOD32 Antivirus ficticio',key='ESET-FICT-0001',devices='1',purchase_price='9,50',supplier='Mayorista secreto')
        self.new_product(name='Microsoft 365 Familia ficticio',line='microsoft',key='',username='m365@example.invalid',password='Clave-Secreta-1',activation_method='cuenta',devices='6')
        self.new_product(name='Microsoft 365 Personal ficticio',line='microsoft',key='',username='m365b@example.invalid',password='Clave-Secreta-2',activation_method='cuenta',devices='1')
        return eset

    def say(self,text,fake,cookie=''):
        with patch.dict(app.os.environ,KEY),patch.object(adi,'_post',side_effect=fake):
            sent=self.request('/api/public/adi/message',{'message':text},cookie=cookie)
        self.assertEqual(sent['status'],201,sent['body']);return sent,(cookie or (sent['cookie'] or '').split(';')[0])

    def test_licenses_question_uses_the_real_catalog_and_no_internal_data(self):
        self.catalog()
        fake=FakeModel('consultar_catalogo',{'tipo':'licencias','busqueda':'','dispositivos':None},lambda out:'¡Claro! Tenemos '+', '.join(x['nombre'] for x in out['licencias'])+'.')
        sent,_=self.say('¿Venden licencias?',fake)
        out=fake.tool_output;names={x['nombre'] for x in out['licencias']}
        self.assertTrue({'ESET NOD32 Antivirus ficticio','Microsoft 365 Familia ficticio','Microsoft 365 Personal ficticio'}<=names)
        dump=json.dumps(out,ensure_ascii=False)
        for secret in ('ESET-FICT-0001','Clave-Secreta-1','m365@example','Mayorista secreto','9,50','18,50'):self.assertNotIn(secret,dump)
        self.assertTrue(all(x['precio'].startswith('$') and x['disponibilidad'] in ('disponible','agotado por el momento') for x in out['licencias']))
        self.assertIn('¡Claro!',sent['body']['messages'][-1]['content']);self.assertEqual(sent['body']['suggestions'],['licencias','cita','asesor'])
        instructions=fake.calls[0]['instructions'];self.assertIn('"se_venden": true',instructions);self.assertIn('nunca digas que no se venden licencias',instructions)
        self.assertEqual([t['name'] for t in fake.calls[0]['tools']],['consultar_catalogo','consultar_disponibilidad_citas','ofrecer_reserva'])

    def test_availability_price_versions_and_devices_follow_up(self):
        self.catalog()
        with app.connect() as c:pid=c.execute("SELECT id FROM catalog_items WHERE name='ESET NOD32 Antivirus ficticio'").fetchone()[0];c.execute("UPDATE license_units SET status='anulada' WHERE product_id=?",(pid,))
        eset=FakeModel('consultar_catalogo',{'tipo':'licencias','busqueda':'ESET NOD32','dispositivos':None},lambda out:json.dumps(out['licencias'],ensure_ascii=False))
        self.say('¿Tienen ESET NOD32?',eset);self.assertEqual([(x['nombre'],x['disponibilidad']) for x in eset.tool_output['licencias']],[('ESET NOD32 Antivirus ficticio','agotado por el momento')])
        m365=FakeModel('consultar_catalogo',{'tipo':'licencias','busqueda':'Microsoft 365','dispositivos':None},lambda out:'ok')
        sent,cookie=self.say('¿Cuánto cuesta Microsoft 365?',m365);self.assertEqual(sorted(x['nombre'] for x in m365.tool_output['licencias']),['Microsoft 365 Familia ficticio','Microsoft 365 Personal ficticio'])
        self.assertTrue(all(x['activacion']=='Usuario y contraseña' for x in m365.tool_output['licencias']))
        # Continuidad: «para tres equipos» llega con la conversación previa y la herramienta filtra por dispositivos.
        follow=FakeModel('consultar_catalogo',{'tipo':'licencias','busqueda':'Microsoft 365','dispositivos':3},lambda out:'ok')
        self.say('Para tres equipos',follow,cookie)
        history=follow.calls[0]['input'];self.assertEqual(history[0],{'role':'user','content':'¿Cuánto cuesta Microsoft 365?'});self.assertEqual(history[-1],{'role':'user','content':'Para tres equipos'})
        self.assertEqual([x['nombre'] for x in follow.tool_output['licencias']],['Microsoft 365 Familia ficticio'])
        self.assertIn('no vuelvas a saludar',follow.calls[0]['instructions'])

    def test_booking_is_offered_with_real_slots_and_never_created_by_the_model(self):
        before=self.count_appointments()
        slots=FakeModel('consultar_disponibilidad_citas',{'servicio':'mantenimiento','fecha':None},lambda out:'ok');self.say('Quiero una cita para mantenimiento',slots)
        self.assertIn('proximos_espacios',slots.tool_output)
        offer=FakeModel('ofrecer_reserva',{'servicio':'mantenimiento','fecha':None,'hora':None},lambda out:'Te muestro el formulario.')
        sent,_=self.say('Sí, resérvala',offer)
        self.assertEqual(sent['body']['action']['type'],'booking');self.assertTrue(sent['body']['action']['service'])
        self.assertEqual(self.count_appointments(),before)  # proponer no crea ninguna cita

    def count_appointments(self):
        with app.connect() as c:return c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0]

    def test_catalog_failure_never_denies_products(self):
        self.catalog()
        with patch.object(licenses,'products',side_effect=RuntimeError('caída simulada')):
            fake=FakeModel('consultar_catalogo',{'tipo':'licencias','busqueda':'','dispositivos':None},lambda out:out.get('mensaje','') or 'x')
            self.say('¿Venden licencias?',fake);self.assertEqual(fake.tool_output['error'],'consulta_no_disponible')
            sent=self.request('/api/public/adi/message',{'message':'¿Venden licencias de antivirus?'})  # sin clave de OpenAI: respaldo
        answer=sent['body']['messages'][-1]['content'];self.assertIn('no puedo comprobar',answer);self.assertNotIn('no vendemos',answer.lower())

    def test_fallback_without_ai_lists_real_licenses_and_does_not_repeat_greeting(self):
        self.catalog()
        first=self.request('/api/public/adi/message',{'message':'¿Venden licencias?'});answer=first['body']['messages'][-1]['content']
        self.assertTrue(answer.startswith('¡Claro!'));self.assertIn('ESET NOD32 Antivirus ficticio',answer);self.assertIn('$',answer)
        cookie=first['cookie'].split(';')[0]
        eset=self.request('/api/public/adi/message',{'message':'¿Tienen ESET NOD32?'},cookie=cookie)['body']['messages'][-1]['content']
        self.assertIn('ESET NOD32 Antivirus ficticio',eset);self.assertNotIn('Microsoft 365 Familia',eset)
        hello=self.request('/api/public/adi/message',{'message':'hola'},cookie=cookie)['body']['messages'][-1]['content']
        self.assertFalse(hello.startswith('Hola, soy ADI'))

    def test_repair_question_orients_and_suggests_diagnosis(self):
        fake=FakeModel(answer='Revisa el cargador y la batería; te recomiendo un diagnóstico técnico.')
        sent,_=self.say('Mi portátil no enciende',fake)
        self.assertEqual(sent['body']['suggestions'],['servicios','cita','asesor']);self.assertIn('no prometas diagnósticos',fake.calls[0]['instructions'].replace('sin prometer diagnósticos','no prometas diagnósticos'))


    def test_agenda_service_prefers_exact_code_and_licenses_never_get_appointment_slots(self):
        with app.connect() as c:
            services=adi.appointments.services(c)
            for s in services:self.assertEqual(adi._agenda_service(c,s['code'])['code'],s['code'])  # el código exacto gana a un nombre que lo contenga
            self.catalog()
            seen={}
            with patch.object(adi,'ask',side_effect=lambda text,admin=False,context=None:seen.update(context or {}) or 'Tenemos licencias.'):
                answer=adi.reply(c,'¿Qué licencias tienen disponibles?')
        self.assertNotIn('proximos_espacios_libres_en_la_agenda',seen);self.assertNotIn('Próximos horarios',answer)
        self.assertTrue(seen['conocimiento_comercial']['licencias']['se_venden'])


if __name__=='__main__':unittest.main()
