"""Voz de ADI: solo pronuncia respuestas de ADI de la propia conversación (o el saludo), respeta el tope diario, valida la configuración,
transcribe sin guardar audio, pronuncia bien la empresa y los importes, usa precios del catálogo y nunca expone la clave. OpenAI simulado:
ninguna llamada real. Base temporal y datos ficticios."""
import base64
import json
import unittest
from unittest.mock import patch
import test_app
import app,adi,adi_voice

KEY={'OPENAI_API_KEY':'sk-prueba-ficticia-123'}


class AdiVoiceTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown
    request=test_app.SecurityTests.request;login=test_app.SecurityTests.login

    def chat(self,text,cookie=''):
        with patch.object(adi,'ask',return_value='Con gusto. El mantenimiento preventivo cuesta $45,00 en PC-DOCTOR S.A.'):
            sent=self.request('/api/public/adi/message',{'message':text},cookie=cookie)
        self.assertEqual(sent['status'],201,sent['body'])
        cookie=cookie or sent['cookie'].split(';')[0]
        return cookie,[m for m in sent['body']['messages'] if m['author']=='adi'][-1]['id'],[m for m in sent['body']['messages'] if m['author']=='client'][-1]['id']

    def test_speech_only_for_own_adi_messages_with_daily_cap(self):
        calls=[]
        def fake(url,data,headers,binary=False):
            calls.append((url,json.loads(data)));return b'ID3'+b'\0'*400
        mine,adi_id,client_id=self.chat('¿Cuánto cuesta un mantenimiento?')
        other,other_id,_=self.chat('Hola')
        with patch.dict(app.os.environ,KEY),patch.object(adi_voice,'_request',side_effect=fake):
            self.assertTrue(self.request('/api/public/adi/voice')['body']['premium'])
            ok=self.request('/api/public/adi/speech',{'message_id':str(adi_id)},cookie=mine);self.assertEqual(ok['status'],200,ok['body'])
            self.assertTrue(base64.b64decode(ok['body']['audio']).startswith(b'ID3'));self.assertNotIn('sk-prueba',json.dumps(ok['body']))
            sent=calls[-1][1];self.assertEqual((sent['model'],sent['voice']),('gpt-4o-mini-tts','coral'))
            self.assertIn('Pe ce dóctor, ese a',sent['input']);self.assertIn('45 dólares',sent['input']);self.assertIn('latinoamericano',sent['instructions'])
            for bad in ({'message_id':str(other_id)},{'message_id':str(client_id)},{'message_id':'999999'}):  # de otra conversación, del cliente o inexistente
                self.assertEqual(self.request('/api/public/adi/speech',bad,cookie=mine)['status'],404,bad)
            self.assertEqual(self.request('/api/public/adi/speech',{'kind':'greeting'})['status'],200)
            with app.connect() as c:
                self.assertGreater(adi_voice.usage(c,app.reception_now()),0)
                adi_voice.add_usage(c,app.reception_now(),30*60)
            capped=self.request('/api/public/adi/speech',{'message_id':str(adi_id)},cookie=mine)
            self.assertEqual(capped['status'],503);self.assertTrue(capped['body']['fallback']);self.assertFalse(self.request('/api/public/adi/voice')['body']['premium'])
        self.assertFalse(self.request('/api/public/adi/voice')['body']['premium'])  # sin clave: voz del navegador

    def test_listen_transcribes_without_storing_audio(self):
        captured=[]
        def fake(url,data,headers,binary=False):
            captured.append((url,data,headers));return {'text':'  Quiero   agendar una cita  '}
        cookie,_,_=self.chat('Hola')
        audio=base64.b64encode(b'\x1aE\xdf\xa3'+b'0'*5000).decode()
        with patch.dict(app.os.environ,KEY),patch.object(adi_voice,'_request',side_effect=fake):
            heard=self.request('/api/public/adi/listen',{'audio':audio,'mime':'audio/webm;codecs=opus','duration_ms':'2400'},cookie=cookie)
            self.assertEqual((heard['status'],heard['body']['text']),(200,'Quiero agendar una cita'))
            url,data,headers=captured[-1];self.assertTrue(url.endswith('/audio/transcriptions'));self.assertIn(b'gpt-4o-mini-transcribe',data);self.assertIn(b'name="language"\r\n\r\nes',data)
            self.assertEqual(self.request('/api/public/adi/listen',{'audio':audio,'mime':'audio/webm','duration_ms':'120'},cookie=cookie)['body']['text'],'')  # demasiado corto
            big=base64.b64encode(b'0'*(adi_voice.MAX_AUDIO_BYTES+10)).decode()
            self.assertIn(self.request('/api/public/adi/listen',{'audio':big,'mime':'audio/webm','duration_ms':'5000'},cookie=cookie)['status'],(400,413))
        with app.connect() as c:self.assertFalse(c.execute("SELECT 1 FROM system_state WHERE value LIKE '%GkXf%'").fetchone())

    def test_settings_are_validated_admin_only_and_sample_uses_unsaved_choice(self):
        cookie,csrf=self.login();post=lambda path,**b:self.request(path,b,cookie=cookie,csrf=csrf)
        status=self.request('/api/adi/voice',cookie=cookie)['body'];self.assertEqual((status['settings']['voice'],status['settings']['daily_minutes']),('coral',30))
        self.assertEqual(post('/api/adi/voice',voice='onyx')['status'],400);self.assertEqual(post('/api/adi/voice',speed='3')['status'],400);self.assertEqual(post('/api/adi/voice',greeting='Hola')['status'],400)
        saved=post('/api/adi/voice',voice='nova',style='formal',speed='1,1',silence_ms='1200',sensitivity='alta',continuous=False,daily_minutes='45',greeting='¡Hola! Soy ADI de PC-DOCTOR S.A., ¿en qué te ayudo?')
        self.assertEqual(saved['status'],200,saved['body']);s=saved['body']['settings']
        self.assertEqual((s['voice'],s['style'],s['speed'],s['silence_ms'],s['sensitivity'],s['continuous'],s['daily_minutes']),('nova','formal',1.1,1200,'alta',False,45))
        public=self.request('/api/public/adi/voice')['body'];self.assertEqual((public['continuous'],public['vad']['silence_ms'],public['vad']['threshold']),(False,1200,adi_voice.SENSITIVITY['alta']))
        calls=[]
        with patch.dict(app.os.environ,KEY),patch.object(adi_voice,'_request',side_effect=lambda url,data,headers,binary=False:calls.append(json.loads(data)) or b'ID3'+b'\0'*300):
            sample=post('/api/adi/voice/sample',voice='shimmer',style='calido',speed='0.9');self.assertEqual(sample['status'],200,sample['body'])
            self.assertEqual(calls[-1]['voice'],'shimmer');self.assertEqual(self.request('/api/adi/voice',cookie=cookie)['body']['settings']['voice'],'nova')  # la muestra no guarda
            self.assertEqual(post('/api/adi/speech',text='Hay 3 órdenes listas para entregar.')['status'],200)
        with app.connect() as c:c.execute("UPDATE users SET role='tecnico' WHERE id=?",(self.uid,))
        for path in ('/api/adi/voice',):self.assertEqual(self.request(path,cookie=cookie)['status'],403)
        self.assertEqual(post('/api/adi/voice',voice='coral')['status'],403);self.assertEqual(post('/api/adi/speech',text='hola')['status'],403)

    def test_speech_text_and_catalog_prices(self):
        text=adi_voice.speech_text('Bienvenido a PC-DOCTOR S.A. El servicio cuesta $1.250,50 USD.\nPróximos horarios:\n/citas?fecha=2026-10-21&hora=10:00 · ver https://ejemplo.invalid/x')
        self.assertIn('Pe ce dóctor, ese a',text);self.assertIn('1250 dólares con 50 centavos',text);self.assertNotIn('/citas',text);self.assertNotIn('https',text)
        self.assertLessEqual(len(adi_voice.speech_text('Frase de prueba bastante larga. '*60)),adi_voice.MAX_SPEECH_CHARS+60)
        cookie,csrf=self.login()
        self.request('/api/catalog',{'name':'Mantenimiento preventivo ficticio','category':'servicio','price':'45'},cookie=cookie,csrf=csrf)
        self.request('/api/catalog',{'name':'Servicio retirado ficticio','category':'servicio','price':'99','available':False},cookie=cookie,csrf=csrf)
        seen={}
        with patch.object(adi,'ask',side_effect=lambda text,admin=False,context=None:seen.update(context or {}) or 'Respuesta ficticia.'):
            self.request('/api/public/adi/message',{'message':'¿Cuánto cuesta el mantenimiento?'})
        prices=seen.get('precios_registrados_iva_incluido');self.assertTrue(isinstance(prices,list) and prices[0]['nombre']=='Mantenimiento preventivo ficticio' and prices[0]['precio']=='$45,00',prices)
        self.assertNotIn('Servicio retirado ficticio',json.dumps(prices,ensure_ascii=False))


class CspTests(unittest.TestCase):
    def test_production_and_local_share_the_policy_and_allow_blob_audio(self):
        import wsgi_app
        self.assertIn("media-src 'self' blob:",app.DEFAULT_CSP)
        source=open(wsgi_app.__file__,encoding='utf-8').read()
        self.assertIn('core.DEFAULT_CSP',source);self.assertNotIn("default-src 'self'",source)  # una sola definición


if __name__=='__main__':unittest.main()
