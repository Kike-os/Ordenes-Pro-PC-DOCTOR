"""Plantilla de autenticación «pcdoctor_codigo» para los códigos de verificación por WhatsApp. Meta SIMULADO: nada sale a internet.
Crear exige CREAR y administración; en revisión no se conecta; aprobada se conecta sola; nunca se crea dos veces."""
import unittest
from unittest.mock import patch

import test_app
import app
import whatsapp_business as wa


class FakeMeta:
    def __init__(self):
        self.templates, self.posts = [], []

    def __call__(self, method, path, env=None, payload=None, query=None):
        if method == 'GET':
            return 200, {'data': [t for t in self.templates if t['name'] == (query or {}).get('name')]}
        self.posts.append(payload)
        self.templates.append({'name': payload['name'], 'status': 'PENDING', 'language': payload['language'], 'category': payload['category']})
        return 200, {'id': 'TPL_FICTICIA', 'status': 'PENDING', 'category': 'AUTHENTICATION'}


class OtpTemplateTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login

    def test_create_review_approve_and_connect(self):
        cookie, csrf = self.login()
        meta = FakeMeta()
        post = lambda **body: self.request('/api/whatsapp/otp-template', body, cookie=cookie, csrf=csrf)
        with patch.object(wa, 'ready', lambda env=None: True), patch.object(wa, 'call', meta), patch.object(wa, 'config', lambda env=None: {'waba': 'WABA_FICTICIA', 'phone_id': 'P'}):
            self.assertEqual(post(action='create')['status'], 400)                       # sin CREAR
            first = post(action='create', confirm='CREAR')
            self.assertEqual(first['status'], 200, first['body'])
            self.assertEqual((first['body']['created'], first['body']['status'], first['body']['connected']), (True, 'PENDING', False))
            sent = meta.posts[0]
            self.assertEqual((sent['name'], sent['category'], sent['language']), ('pcdoctor_codigo', 'AUTHENTICATION', 'es'))
            self.assertEqual(sent['components'][2]['buttons'][0]['otp_type'], 'COPY_CODE')
            self.assertEqual(sent['components'][1]['code_expiration_minutes'], 5)
            self.assertEqual(post(action='create', confirm='CREAR')['body']['created'], False)   # ya existe: no se duplica
            self.assertEqual(len(meta.posts), 1)
            with app.connect() as c:
                self.assertEqual(wa.settings(c)['otp_template'], '')                      # en revisión: todavía no se usa
            meta.templates[0]['status'] = 'APPROVED'
            done = post(action='status')['body']
            self.assertTrue(done['connected'])
            with app.connect() as c:
                self.assertEqual((wa.settings(c)['otp_template'], wa.settings(c)['otp_lang']), ('pcdoctor_codigo', 'es'))
            with app.connect() as c:
                c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
            self.assertEqual(post(action='status')['status'], 403)


    def test_cancellation_template_created_and_assigned_when_approved(self):
        cookie, csrf = self.login()
        meta = FakeMeta()
        post = lambda **body: self.request('/api/whatsapp/event-template', body, cookie=cookie, csrf=csrf)
        with patch.object(wa, 'ready', lambda env=None: True), patch.object(wa, 'call', meta), patch.object(wa, 'config', lambda env=None: {'waba': 'WABA_FICTICIA', 'phone_id': 'P'}):
            first = post(event='orden_cancelada', action='create', confirm='CREAR')['body']
            self.assertEqual((first['created'], first['status'], first['connected']), (True, 'PENDING', False))
            sent = meta.posts[0]
            self.assertEqual((sent['name'], sent['category'], sent['language']), ('pcdoctor_cancelacion_reparacion', 'UTILITY', 'es_EC'))
            self.assertEqual(sent['components'][0]['text'].count('{{'), 3)
            self.assertEqual(len(sent['components'][0]['example']['body_text'][0]), 3)
            meta.templates[0]['status'] = 'APPROVED'
            self.assertTrue(post(event='orden_cancelada', action='status')['body']['connected'])
            with app.connect() as c:
                self.assertEqual(wa.settings(c)['events']['orden_cancelada']['template'], 'pcdoctor_cancelacion_reparacion')
            self.assertEqual(post(event='desconocido', action='status')['status'], 400)

if __name__ == '__main__':
    unittest.main()
