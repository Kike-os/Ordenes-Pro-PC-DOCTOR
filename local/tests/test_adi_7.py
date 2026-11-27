"""ADI 7 workflows using the real HTTP handlers and synthetic provider responses."""
import base64
from datetime import date, datetime
import unittest
from unittest.mock import patch

import adi_forecast
import adi_lab
import app
import test_invoicing


class AdiSevenTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown = Base.setUp, Base.tearDown
    request, login, order_data = Base.request, Base.login, Base.order_data

    def login_as(self, role):
        with app.connect() as c:
            c.execute('UPDATE users SET role=? WHERE id=?', (role, self.uid))
        return self.login()

    def test_visual_requires_confirmation_and_sends_only_image(self):
        cookie, csrf = self.login()
        order = self.request('/api/orders', self.order_data({'request_key': 'adi-visual-order'}),
                             cookie=cookie, csrf=csrf)['body']
        path = '/api/orders/%s/adi-visual' % order['id']
        image = base64.b64encode(b'\x89PNG\r\n\x1a\nimage-fixture').decode()
        with patch('adi_ai.openai_key', return_value='fake'), patch('adi_ai._post', return_value={
            'status': 'completed', 'output': [{'type': 'message', 'content': [
                {'type': 'output_text', 'text': 'Observación de prueba'}]}],
        }) as transport:
            self.assertIn(self.request(path, {'image': image, 'confirmed': True})['status'], (401, 403))
            self.assertEqual(self.request(path, {'image': image}, cookie=cookie, csrf=csrf)['status'], 400)
            self.assertEqual(self.request(path, {'image': '!', 'confirmed': True}, cookie=cookie, csrf=csrf)['status'], 400)
            transport.assert_not_called()
            response = self.request(path, {'image': image, 'confirmed': True}, cookie=cookie, csrf=csrf)
            self.assertEqual(response['body'], {'analysis': 'Observación de prueba'})
            payload = transport.call_args.args[1]
            self.assertFalse(payload['store'])
            self.assertNotIn(order['code'], str(payload))

    def test_semantic_uses_only_approved_nonreserved_excerpts(self):
        with app.connect() as c:
            admin = {'id': self.uid, 'role': 'administrador'}
            reviewer_id = c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES "
                                    "('reviewer','reviewer@example.invalid','Revisor','test','administrador',1)").lastrowid
            reviewer = {'id': reviewer_id, 'role': 'administrador'}
            template = {'source': 'Manual ficticio', 'source_date': '2026-01-01', 'version': '1',
                        'category': 'post'}
            for title, visibility, approved in [('Abrir revisión', 'tecnico', True),
                                                 ('Extracto reservado', 'administrador', True),
                                                 ('Pendiente de revisión', 'tecnico', False)]:
                source = adi_lab.submit(c, dict(template, title=title, content=title, visibility=visibility),
                                        admin, datetime(2026, 1, 2))
                if approved:
                    adi_lab.review(c, source, {'status': 'aprobado', 'review_note': 'Revisión de prueba'},
                                   reviewer, datetime(2026, 1, 3))
        path = '/api/adi/lab/semantic'
        data = {'q': 'arranque', 'category': 'post', 'confirmed': True}
        cookie, csrf = self.login_as('tecnico')
        self.assertEqual(self.request(path, data, cookie=cookie, csrf=csrf)['status'], 403)
        cookie, csrf = self.login_as('administrador')
        with patch('adi_ai.openai_key', return_value='fake'), patch('adi_ai._post', return_value={
            'data': [{'index': i, 'embedding': [1] + [0] * 255} for i in (1, 0)],
        }) as transport:
            response = self.request(path, data, cookie=cookie, csrf=csrf)
            self.assertEqual(response['status'], 200, response['body'])
            self.assertEqual([row['title'] for row in response['body']['rows']], ['Abrir revisión'])
            self.assertEqual(transport.call_args.args[1]['input'], ['arranque', 'Abrir revisión\nAbrir revisión'])

    def test_forecast_http_permissions_and_autocare_undo(self):
        cookie, csrf = self.login_as('tecnico')
        path = '/api/adi/admin/operational-brief'
        self.assertEqual(self.request(path, cookie=cookie)['status'], 403)
        cookie, csrf = self.login_as('administrador')
        brief = self.request(path, cookie=cookie)
        self.assertEqual(brief['status'], 200, brief['body'])
        self.assertEqual(brief['body']['pronostico']['status'], 'insufficient')
        self.assertTrue(brief['body']['laboratorio']['instalado'])
        action = '/api/autocare/action'
        for change in ('pause_adi', 'restore_adi'):
            result = self.request(action, {'action': change, 'confirm': '1'}, cookie=cookie, csrf=csrf)
            self.assertEqual(result['status'], 200, result['body'])
            self.assertEqual(result['body']['verification']['status'], 'ok')
        with app.connect() as c:
            self.assertIsNone(c.execute("SELECT value FROM system_state WHERE key='adi_writing'").fetchone())
        self.assertEqual(self.request(action, {'action': 'restore_adi', 'confirm': '1'},
                                      cookie=cookie, csrf=csrf)['status'], 409)

    def test_forecast_selects_weekdays_using_holdout(self):
        result = adi_forecast.estimate([1, 3, 10, 6, 2, 1, 0] * 6, date(2026, 11, 27))
        self.assertEqual(result['method'], adi_forecast.METHOD_NAMES['weekday'])
        self.assertEqual(result['mae'], 0)
        self.assertEqual([point['estimate'] for point in result['days']], [1, 3, 10, 6, 2, 1, 0])
