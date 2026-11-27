"""Diagnóstico privado y versionado de una unidad de la orden, con datos ficticios."""
import base64
import unittest

import test_app
import app

PHOTO = base64.b64encode(bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000a49444154789c636000000002000148afa4710000000049454e44ae426082'
)).decode()


class OrderBatteryTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data

    def receive(self, kind, cookie, csrf, main=None):
        payload = {'type': kind, 'request_key': 'battery-order-fixture-' + kind}
        if main:
            payload.update(group_order_id=str(main), new_unit='1')
        result = self.request('/api/orders', self.order_data(payload), cookie=cookie, csrf=csrf)
        self.assertIn(result['status'], (200, 201), result['body'])
        return result['body']['id']

    def test_unit_visibility_independence_history_and_private_evidence(self):
        cookie, csrf = self.login()
        first = self.receive('portatil', cookie, csrf)
        second = self.receive('gaming', cookie, csrf, first)
        desktop = self.receive('escritorio', cookie, csrf, first)
        console = self.receive('consola', cookie, csrf, first)
        notebook = self.receive('notebook', cookie, csrf, first)
        route = lambda oid: f'/api/orders/{oid}/battery'
        get = lambda oid: self.request(route(oid), cookie=cookie)['body']
        post = lambda oid, revision, **fields: self.request(
            route(oid), {'revision': str(revision), **fields}, cookie=cookie, csrf=csrf)
        order = self.request(f'/api/orders/{first}', cookie=cookie)['body']['order']
        units = {row['id']: row for row in order['group']['units']}
        self.assertEqual({oid for oid, row in units.items() if 'battery' in row}, {first, second})
        self.assertIsNone(units[first]['battery']['percent'])
        for oid in (desktop, console, notebook):
            self.assertEqual(self.request(route(oid), cookie=cookie)['status'], 404)
            self.assertEqual(post(oid, 0, status='evaluada', percent='100')['status'], 404)
        self.assertEqual(self.request(route(first))['status'], 401)
        self.assertEqual(self.request(route(first), {'revision':'0','status':'pendiente'}, cookie=cookie)['status'], 403)
        self.assertEqual(post(first, 0, status='no_evaluada')['status'], 400)
        bad = post(first, 0, status='no_evaluada', percent='0', reason='El equipo no enciende')['body']['battery']
        self.assertIsNone(bad['percent'])
        self.assertEqual(bad['status'], 'no_evaluada')
        for value in ('', '-1', '100.01', '1.001', 'NaN'):
            self.assertEqual(post(first, bad['id'], status='evaluada', percent=value)['status'], 400)
        self.assertEqual(post(first, bad['id'], status='evaluada', percent='80', image='abcd')['status'], 400)
        first_assessed = post(first, bad['id'], status='evaluada', percent='0', notes='Revisión ficticia',
                              source='Informe del sistema', image=PHOTO)['body']['battery']
        self.assertEqual(first_assessed['percent'], 0)
        self.assertEqual(post(first, bad['id'], status='evaluada', percent='100')['status'], 409)
        self.assertEqual(get(second)['battery']['status'], 'pendiente')
        self.assertIsNone(get(second)['battery']['percent'])
        second_assessed = post(second, 0, status='evaluada', percent='79,99')['body']['battery']
        self.assertEqual(second_assessed['percent'], 79.99)
        updated = post(first, first_assessed['id'], status='evaluada', percent='100', remove_image=True)['body']['battery']
        self.assertIsNone(updated['image_id'])
        history = get(first)['history']
        self.assertEqual([row['percent'] for row in history], [100, 0, None])
        self.assertEqual(history[0]['previous']['percent'], 0)
        self.assertEqual(history[1]['previous']['reason'], 'El equipo no enciende')
        self.assertTrue(all(row['actor'] and row['created_at'] for row in history))
        image_url = f'/image/{first_assessed["image_id"]}'
        self.assertEqual(self.request(route(first)+image_url, cookie=cookie)['body'], base64.b64decode(PHOTO))
        self.assertEqual(self.request(route(second)+image_url, cookie=cookie)['status'], 404)
        self.assertEqual(self.request(route(first)+image_url)['status'], 401)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,))
        self.assertEqual(self.request(route(first), cookie=cookie)['status'], 200)
        self.assertEqual(post(first, updated['id'], status='pendiente')['status'], 403)

    def test_order_remains_readable_when_migration_is_pending(self):
        cookie, csrf = self.login()
        oid = self.receive('portatil', cookie, csrf)
        saved = self.request(f'/api/orders/{oid}/battery', {'revision':'0','status':'pendiente'},
                             cookie=cookie, csrf=csrf)['body']['battery']
        self.assertGreater(saved['id'], 0)
        self.assertTrue(saved['actor'] and saved['created_at'])
        self.assertIsNone(saved['percent'])
        with app.connect() as c:
            c.execute('DROP TABLE order_battery_revisions')
        route = f'/api/orders/{oid}'
        detail = self.request(route, cookie=cookie)['body']['order']['group']['units'][0]
        self.assertFalse(detail['battery']['available'])
        self.assertIsNone(detail['battery']['percent'])
        self.assertFalse(self.request(route+'/battery', cookie=cookie)['body']['available'])
        self.assertEqual(self.request(route+'/battery', {'revision':'0','status':'pendiente'},
                                      cookie=cookie, csrf=csrf)['status'], 503)
