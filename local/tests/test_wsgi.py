import io
import json
import unittest
from wsgiref.util import setup_testing_defaults
from wsgiref.validate import validator

from unittest.mock import patch

import test_app
import app
# wsgi_app carga local/.env al importarse. En las pruebas no debe entrar ninguna credencial real (correo, IA…).
with patch.object(app,'load_env'):
    import wsgi_app


class WSGITests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown

    def call_wsgi(self, path, method='GET', body=None, cookie=''):
        env = {}
        setup_testing_defaults(env)
        raw = json.dumps(body or {}).encode()
        route,_,query=path.partition('?')
        env.update(PATH_INFO=route, REQUEST_METHOD=method, CONTENT_TYPE='application/json',
                   CONTENT_LENGTH=str(len(raw)), HTTP_ORIGIN='http://127.0.0.1:8010',
                   HTTP_COOKIE=cookie, QUERY_STRING=query, **{'wsgi.input': io.BytesIO(raw)})
        result = {}
        def start(status, headers, exc_info=None):
            result.update(status=status, headers=dict(headers))
        response = validator(wsgi_app.app)(env, start)
        try:
            result['body'] = b''.join(response)
        finally:
            response.close()
        return result

    def test_wsgi_login_and_private_route(self):
        response = self.call_wsgi('/api/me')
        self.assertTrue(response['status'].startswith('401'))
        response = self.call_wsgi('/api/login', 'POST', {'login':'demo', 'password':'contraseña-segura-de-prueba'})
        self.assertTrue(response['status'].startswith('200'))
        cookie = response['headers']['Set-Cookie'].split(';')[0]
        self.assertTrue(self.call_wsgi('/api/me', cookie=cookie)['status'].startswith('200'))

    def test_wsgi_page_static_and_method(self):
        self.assertIn(b'<!', self.call_wsgi('/')['body'])
        self.assertTrue(self.call_wsgi('/static/app.js')['status'].startswith('200'))
        self.assertTrue(self.call_wsgi('/.env')['status'].startswith('401'))
        self.assertTrue(self.call_wsgi('/', 'DELETE')['status'].startswith('405'))
        self.assertEqual(self.call_wsgi('/', 'HEAD')['body'], b'')

    def test_wsgi_reception_catalogs_and_complete_order(self):
        login=self.call_wsgi('/api/login','POST',{'login':'demo','password':'contraseña-segura-de-prueba'})
        cookie=login['headers']['Set-Cookie'].split(';')[0]
        for path,size in [('/api/reception-options',None),('/api/geo/provinces',24),('/api/geo/cantons?province=01',15),('/api/geo/parishes?province=01&canton=0101',None),('/api/geo/localities?canton=0101&parish=010101',None)]:
            response=self.call_wsgi(path,cookie=cookie)
            self.assertTrue(response['status'].startswith('200'),(path,response))
            data=json.loads(response['body'])
            if size is not None:self.assertEqual(len(data['rows']),size)
            if path=='/api/reception-options':
                self.assertEqual(len(data['device_types']),12)
                self.assertGreater(len(data['brands']),70)
            else:self.assertIsInstance(data['rows'],list)
        # POST through Passenger with the same CSRF and session protection.
        csrf=json.loads(self.call_wsgi('/api/me',cookie=cookie)['body'])['user']['csrf']
        # The helper adds the token to every request below, without changing production behavior.
        import io
        from wsgiref.util import setup_testing_defaults
        env={};setup_testing_defaults(env)
        raw=json.dumps(test_app.SecurityTests.order_data(self)).encode()
        env.update(PATH_INFO='/api/orders',REQUEST_METHOD='POST',HTTP_COOKIE=cookie,
                   HTTP_ORIGIN='http://127.0.0.1:8010',HTTP_X_CSRF_TOKEN=csrf,
                   CONTENT_TYPE='application/json',CONTENT_LENGTH=str(len(raw)),
                   **{'wsgi.input':io.BytesIO(raw)})
        result={}
        response=wsgi_app.application(env,lambda status,headers:result.update(status=status))
        order=json.loads(b''.join(response));self.assertTrue(result['status'].startswith('201'),order)
        self.assertRegex(order['code'],r'^PCD-[0-9]{8}-0001$')
        for suffix in ['', '/qr.png','/receipt.pdf']:
            response=self.call_wsgi('/api/orders/'+str(order['id'])+suffix,cookie=cookie)
            self.assertTrue(response['status'].startswith('200'),response)
        self.assertTrue(self.call_wsgi('/api/order-by-code/'+order['code'],cookie=cookie)['status'].startswith('200'))
