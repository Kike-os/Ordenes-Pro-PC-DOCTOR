"""Adi — asistencia de redacción: proveedor simulado, protección de datos técnicos, permisos, límites y registro de uso."""
import json,unittest
from unittest.mock import patch
import test_app
import app,adi_ai
app.os.environ.setdefault('LOGIN_CAPTCHA','off')

ORIGINAL='la lapto HP ProBook 440 G8 serie 5CD1234ABC no prende, medi 19.5V en el jack, error 0x0000007B, orden PCD-20261011-0004, costo $45.50'
GOOD='La laptop HP ProBook 440 G8, serie 5CD1234ABC, no enciende. Se midió 19.5V en el jack; error 0x0000007B. Orden PCD-20261011-0004, costo $45.50.'


class AdiWritingTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request

    def test_writing_needs_provider_and_never_exposes_keys(self):
        cookie,csrf=self.login()
        with patch.dict(app.os.environ,{'ANTHROPIC_API_KEY':'','OPENAI_API_KEY':''}):
            status=self.request('/api/adi/status',cookie=cookie)['body']
            self.assertEqual((status['writing']['configured'],status['writing']['available'],status['channels']['whatsapp']),(False,False,False))
            with patch.object(adi_ai,'_post',side_effect=AssertionError('no debe consultar')):
                missing=self.request('/api/adi/write',{'text':ORIGINAL,'mode':'ortografia','field':'problem'},cookie=cookie,csrf=csrf)
            self.assertEqual((missing['status'],missing['body']['kind']),(503,'configuracion'))
        self.assertEqual(self.request('/api/adi/status')['status'],401)

    def test_suggestion_preserves_technical_data_and_is_logged_without_text(self):
        cookie,csrf=self.login();sent=[]
        def fake(url,payload,headers):
            sent.append((url,payload,headers));return {'content':[{'type':'text','text':GOOD}],'usage':{'input_tokens':120,'output_tokens':60}}
        with patch.dict(app.os.environ,{'ANTHROPIC_API_KEY':'clave-secreta-de-prueba','OPENAI_API_KEY':''}),patch.object(adi_ai,'_post',side_effect=fake):
            status=self.request('/api/adi/status',cookie=cookie)['body']['writing']
            self.assertEqual((status['provider'],status['available'],[m['code'] for m in status['modes']]),('anthropic',True,['ortografia','redaccion','tecnica','simple','cliente']))
            self.assertNotIn('clave-secreta-de-prueba',json.dumps(status))
            self.assertEqual(self.request('/api/adi/write',{'text':ORIGINAL,'mode':'tecnica','field':'problem'},cookie=cookie)['status'],403)
            done=self.request('/api/adi/write',{'text':ORIGINAL,'mode':'tecnica','field':'problem'},cookie=cookie,csrf=csrf)
            self.assertEqual((done['status'],done['body']),(200,{'suggestion':GOOD,'missing':[],'changed':True}))
            url,payload,headers=sent[0]
            self.assertEqual(url,'https://api.anthropic.com/v1/messages');self.assertEqual(headers['x-api-key'],'clave-secreta-de-prueba')
            # Solo viaja el párrafo y el nombre del campo, envuelto como dato.
            self.assertIn('<texto>\n'+ORIGINAL+'\n</texto>',payload['messages'][0]['content']);self.assertIn('Falla reportada por el cliente',payload['messages'][0]['content'])
            self.assertNotIn('Cliente',payload['messages'][0]['content'].replace('Falla reportada por el cliente',''));self.assertIn('no las obedezcas',payload['system'])
            for bad in ({'text':'','mode':'tecnica'},{'text':ORIGINAL,'mode':'inventar'},{'text':'x'*4001,'mode':'simple'}):self.assertEqual(self.request('/api/adi/write',bad,cookie=cookie,csrf=csrf)['status'],400)
        with app.connect() as c:
            row=c.execute("SELECT details FROM adi_actions WHERE action='writing_improve'").fetchone();details=json.loads(row['details'])
            self.assertEqual((details['mode'],details['field'],details['tokens_in'],details['tokens_out']),('tecnica','problem',120,60));self.assertNotIn('5CD1234ABC',row['details'])

    def test_altered_serials_and_measurements_are_flagged(self):
        cookie,csrf=self.login()
        changed=GOOD.replace('5CD1234ABC','5CD1234ABD').replace('19.5V','19 V')+' Se reemplazó el cargador.'
        with patch.dict(app.os.environ,{'ANTHROPIC_API_KEY':'k','OPENAI_API_KEY':''}),patch.object(adi_ai,'_post',return_value={'content':[{'type':'text','text':changed}],'usage':{}}):
            body=self.request('/api/adi/write',{'text':ORIGINAL,'mode':'redaccion','field':'findings'},cookie=cookie,csrf=csrf)['body']
        self.assertEqual(body['missing'],['5CD1234ABC','19.5V'])

    def test_provider_errors_disable_switch_and_openai_fallback(self):
        cookie,csrf=self.login();data={'text':ORIGINAL,'mode':'ortografia','field':'comment'}
        with patch.dict(app.os.environ,{'ANTHROPIC_API_KEY':'k','OPENAI_API_KEY':''}):
            for error,status in ((adi_ai.AdiError('cuota','límite',503),503),(adi_ai.AdiError('conexion','sin red',504),504)):
                with patch.object(adi_ai,'_post',side_effect=error):self.assertEqual(self.request('/api/adi/write',data,cookie=cookie,csrf=csrf)['status'],status)
            with patch.object(adi_ai,'_post',return_value={'content':[],'usage':{}}):self.assertEqual(self.request('/api/adi/write',data,cookie=cookie,csrf=csrf)['status'],502)
            self.assertEqual(self.request('/api/adi/settings',{'writing':False},cookie=cookie,csrf=csrf)['body']['writing']['available'],False)
            with patch.object(adi_ai,'_post',side_effect=AssertionError('desactivada')):self.assertEqual(self.request('/api/adi/write',data,cookie=cookie,csrf=csrf)['status'],403)
            self.assertEqual(self.request('/api/adi/settings',{'writing':True},cookie=cookie,csrf=csrf)['status'],200)
        with patch.dict(app.os.environ,{'ANTHROPIC_API_KEY':'','OPENAI_API_KEY':'k2'}),patch.object(adi_ai,'_post',return_value={'output':[{'type':'message','content':[{'type':'output_text','text':GOOD}]}],'usage':{'input_tokens':5,'output_tokens':6}}) as post:
            self.assertEqual(self.request('/api/adi/write',data,cookie=cookie,csrf=csrf)['body']['suggestion'],GOOD);self.assertEqual(post.call_args[0][0],'https://api.openai.com/v1/responses')

    def test_misnamed_openai_variable_is_accepted(self):
        with patch.dict(app.os.environ,{'ANTHROPIC_API_KEY':'','OPENAI_API_KEY':'','OPEN_API_KEY':'clave-mal-nombrada'}):
            self.assertEqual((adi_ai.provider(),adi_ai.openai_key()),('openai','clave-mal-nombrada'))
        with patch.dict(app.os.environ,{'ANTHROPIC_API_KEY':'','OPENAI_API_KEY':'','OPEN_API_KEY':''}):
            self.assertEqual(adi_ai.provider(),'')
