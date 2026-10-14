"""Estado «En revisión por falla recurrente»: misma orden, motivo obligatorio, conteo, reingreso trazable y equipos independientes."""
import unittest

import test_app
import app
import equipment
import tracking_board


class RecurrenceTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data

    def status(self, oid, value, **extra):
        return self.request('/api/order-status', dict({'id': str(oid), 'status': value}, **extra), cookie=self.cookie, csrf=self.csrf)

    def new_order(self, key, **extra):
        return self.request('/api/orders', self.order_data(dict({'request_key': 'recurrence-request-' + key}, **extra)), cookie=self.cookie, csrf=self.csrf)['body']['id']

    def test_same_order_requires_reason_and_counts_each_review(self):
        self.cookie, self.csrf = self.login()
        oid = self.new_order('000001')
        with app.connect() as c:
            code = c.execute('SELECT code FROM orders WHERE id=?', (oid,)).fetchone()[0]
            orders = c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        self.status(oid, 'reparacion')
        self.assertEqual(self.status(oid, 'revision_recurrente')['status'], 400)
        self.assertEqual(self.status(oid, 'revision_recurrente', comment='corto')['status'], 400)
        self.assertEqual(self.status(oid, 'revision_recurrente', comment='La pantalla vuelve a parpadear tras la reparación.', technician=str(self.uid))['status'], 200)
        self.status(oid, 'reparacion', comment='Se reemplaza el cable flex de la pantalla.')
        self.assertEqual(self.status(oid, 'revision_recurrente', comment='El parpadeo regresó a los tres días de uso.')['status'], 200)
        detail = self.request('/api/orders/%d' % oid, cookie=self.cookie)['body']['order']
        self.assertEqual((detail['code'], detail['status'], len(detail['recurrences'])), (code, 'revision_recurrente', 2))
        self.assertEqual([r['number'] for r in detail['recurrences']], [1, 2])
        self.assertTrue(detail['recurrences'][0]['technician'])
        comments = [h['comment'] for h in detail['history']]
        self.assertTrue(any('Revisión por falla recurrente n.º 2' in text and 'Motivo: El parpadeo regresó' in text for text in comments))
        self.assertTrue(any('Se reemplaza el cable flex' in text for text in comments))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0], orders)
            with self.assertRaises(Exception):
                c.execute('DELETE FROM order_recurrences')
        row = next(r for r in self.request('/api/tracking', cookie=self.cookie)['body']['rows'] if r['id'] == oid)
        self.assertEqual((row['recurrences'], row['status'], [s['state'] for s in row['stages']][1]), (2, 'En revisión por falla recurrente', 'current'))
        # Continúa con los estados normales hasta la entrega.
        for value in ('reparacion', 'listo', 'entregado'):
            self.assertEqual(self.status(oid, value)['status'], 200)

    def test_delivered_equipment_reentry_keeps_the_original_delivery(self):
        self.cookie, self.csrf = self.login()
        oid = self.new_order('000002')
        self.status(oid, 'entregado')
        with app.connect() as c:
            delivered = c.execute('SELECT delivered_at FROM orders WHERE id=?', (oid,)).fetchone()[0]
        self.assertTrue(delivered)
        self.assertEqual(self.status(oid, 'revision_recurrente', comment='El equipo no enciende de nuevo después de la entrega.')['status'], 200)
        detail = self.request('/api/orders/%d' % oid, cookie=self.cookie)['body']['order']
        record = detail['recurrences'][0]
        self.assertEqual((record['reentry'], record['delivered_at'], record['previous_status']), (1, delivered, 'entregado'))
        labels = [h['status_label'] for h in detail['history']]
        self.assertIn('Entregado', labels)
        self.assertTrue(any('Reingreso del equipo tras la entrega' in h['comment'] for h in detail['history']))

    def test_only_the_affected_unit_of_a_multi_unit_order_changes(self):
        self.cookie, self.csrf = self.login()
        main = self.new_order('000003', email='grupo@example.invalid')
        second = self.request('/api/orders', self.order_data({'request_key': 'recurrence-request-000004', 'email': 'grupo@example.invalid', 'group_order_id': str(main), 'new_unit': '1'}), cookie=self.cookie, csrf=self.csrf)['body']['id']
        for oid in (main, second):
            self.status(oid, 'entregado')
        self.status(second, 'revision_recurrente', comment='El segundo equipo repite la falla del teclado.')
        with app.connect() as c:
            states = dict(c.execute('SELECT id,status FROM orders WHERE id IN (?,?)', (main, second)).fetchall())
            group = equipment.group(c, main)
        self.assertEqual((states[main], states[second]), ('entregado', 'revision_recurrente'))
        self.assertEqual(group['overall']['code'], 'parcial')

    def test_full_edit_also_requires_the_reason(self):
        self.cookie, self.csrf = self.login()
        oid = self.new_order('000005')
        detail = self.request('/api/orders/%d' % oid, cookie=self.cookie)['body']['order']
        base = {'problem': detail['problem'], 'status': 'revision_recurrente', 'priority': 'normal', 'assigned_to': str(self.uid), 'estimated_delivery': '', 'internal_notes': '', 'recommendations': '', 'findings': '', 'revision': detail['revision']}
        refused = self.request('/api/orders/%d/workspace' % oid, dict(base, comment=''), cookie=self.cookie, csrf=self.csrf)
        self.assertEqual(refused['status'], 400)
        self.assertIn('comment', refused['body']['fields'])
        ok = self.request('/api/orders/%d/workspace' % oid, dict(base, comment='Vuelve a calentarse con carga alta.'), cookie=self.cookie, csrf=self.csrf)
        self.assertEqual(ok['status'], 200)
        self.assertEqual(len(self.request('/api/orders/%d' % oid, cookie=self.cookie)['body']['order']['recurrences']), 1)


if __name__ == '__main__':
    unittest.main()
