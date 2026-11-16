"""1.5.286 · Clientes con cédula o RUC y sus citas (datos ficticios, base temporal, sin correo real).

La misma persona puede estar registrada con su cédula (10 dígitos) o con su RUC de persona natural (cédula + establecimiento, 13 dígitos).
Antes, al agendar con el otro documento, la cita no se enlazaba a su ficha y se creaba un cliente duplicado, y el retiro con número de
orden respondía «No encontramos una orden». Un RUC ya registrado que no cumple la regla de la cédula bloqueaba citas y recepciones.
Escenarios: orden con cédula y con RUC; varias órdenes y citas; cita ya confirmada y enlace de mantenimiento; identificación incorrecta o
inexistente; documento ya registrado; clientes anteriores a la corrección. Un RUC de sociedad nunca se confunde con una cédula."""
import re
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_app
import app
import appointments
import reception
import test_maintenance_reminders
import test_pickup_clients

CEDULA = '1710034065'
RUC = CEDULA + '001'
COMPANY_RUC = '1790012345001'  # sociedad (tercer dígito 9): no contiene una cédula


class IdentityAppointmentsTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login, test_app.SecurityTests.order_data
    day = test_pickup_clients.PickupAndClientsTests.day
    book = test_pickup_clients.PickupAndClientsTests.book
    form = test_maintenance_reminders.MaintenanceReminderTests.form

    def order_for(self, identification, kind, key, status=None):
        cookie, csrf = self.login()
        made = self.request('/api/orders', self.order_data({'identification': identification, 'document_type': kind, 'email': 'cliente@example.invalid', 'request_key': 'identity-order-' + key}), cookie=cookie, csrf=csrf)
        self.assertEqual(made['status'], 201, made['body'])
        with app.connect() as c:
            if status:
                c.execute('UPDATE orders SET status=? WHERE id=?', (status, made['body']['id']))
                c.commit()
            client = c.execute('SELECT d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?', (made['body']['id'],)).fetchone()[0]
        return made['body'], client, cookie, csrf

    def appointment_client(self, aid):
        with app.connect() as c:
            return c.execute('SELECT client_id FROM appointments WHERE id=?', (aid,)).fetchone()[0]

    def clients(self):
        with app.connect() as c:
            return c.execute('SELECT COUNT(*) FROM clients').fetchone()[0]

    def test_identity_rules(self):
        self.assertTrue(reception.same_identity(CEDULA, RUC))
        self.assertTrue(reception.same_identity(RUC, CEDULA))
        self.assertTrue(reception.same_identity(CEDULA + '002', RUC))  # otro establecimiento, misma persona
        self.assertFalse(reception.same_identity(CEDULA, '0100000017'))
        self.assertFalse(reception.same_identity(COMPANY_RUC, COMPANY_RUC[:10]))  # sociedad: no hay cédula
        self.assertFalse(reception.same_identity(CEDULA + '000', CEDULA))  # sin establecimiento no es un RUC
        self.assertFalse(reception.same_identity('', CEDULA))
        # 4 dígitos: con RUC de persona natural valen los de su cédula o los del RUC; con cédula, solo los suyos.
        self.assertEqual(appointments.last4_error(CEDULA[-4:], RUC, 'ruc'), '')
        self.assertEqual(appointments.last4_error(RUC[-4:], RUC, 'ruc'), '')
        self.assertIn('cédula o de tu RUC', appointments.last4_error('9999', RUC, 'ruc'))
        self.assertEqual(appointments.last4_error(CEDULA[-4:], CEDULA, 'cedula'), '')
        self.assertTrue(appointments.last4_error(RUC[-4:], CEDULA, 'cedula'))

    def test_order_with_cedula_then_appointments_with_cedula_or_ruc(self):
        order, client, cookie, csrf = self.order_for(CEDULA, 'cedula', 'c001', 'listo')
        before = self.clients()
        with test_app.open_requests(), patch.object(app, 'limited', return_value=False):
            same = self.book('id-c-1', '09:00', identification=CEDULA, document_type='cedula', service='mantenimiento')
            self.assertEqual(same['status'], 201, same['body'])
            other_doc = self.book('id-c-2', '11:00', identification=RUC, document_type='ruc', service='mantenimiento', id_last4=RUC[-4:])
            self.assertEqual(other_doc['status'], 201, other_doc['body'])
            pickup = self.book('id-c-3', '14:00', identification=RUC, document_type='ruc', service='retiro', order_code=order['code'])
            self.assertEqual((pickup['status'], pickup['body'].get('pickup_order')), (201, order['code']), pickup['body'])
        self.assertEqual({self.appointment_client(a['body']['id']) for a in (same, other_doc, pickup)}, {client})  # todas en su ficha
        self.assertEqual(self.clients(), before)  # ningún cliente duplicado
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT identification FROM clients WHERE id=?', (client,)).fetchone()[0], CEDULA)  # su ficha no cambia

    def test_order_with_ruc_then_appointments_with_ruc_or_cedula(self):
        order, client, cookie, csrf = self.order_for(RUC, 'ruc', 'r001', 'espera_entrega')
        before = self.clients()
        with test_app.open_requests(), patch.object(app, 'limited', return_value=False):
            ruc_tail = self.book('id-r-1', '09:00', identification=RUC, document_type='ruc', service='mantenimiento', id_last4=RUC[-4:])
            ruc_cedula_tail = self.book('id-r-2', '11:00', identification=RUC, document_type='ruc', service='mantenimiento', id_last4=CEDULA[-4:])
            cedula = self.book('id-r-3', '15:00', identification=CEDULA, document_type='cedula', service='mantenimiento')
            pickup = self.book('id-r-4', '14:00', identification=CEDULA, document_type='cedula', service='retiro', order_code=order['code'])
        for result in (ruc_tail, ruc_cedula_tail, cedula, pickup):
            self.assertEqual(result['status'], 201, result['body'])
        self.assertEqual(pickup['body'].get('pickup_order'), order['code'])
        self.assertEqual({self.appointment_client(a['body']['id']) for a in (ruc_tail, ruc_cedula_tail, cedula, pickup)}, {client})
        self.assertEqual(self.clients(), before)
        listing = self.request('/api/clients/%d' % client, cookie=cookie)['body']
        self.assertEqual(len(listing['appointments']), 4)  # la ficha muestra todas sus citas

    def test_several_orders_wrong_and_unknown_identification(self):
        first, client, cookie, csrf = self.order_for(CEDULA, 'cedula', 'm001', 'listo')
        second, client2, _, _ = self.order_for(CEDULA, 'cedula', 'm002', 'listo')
        self.assertEqual(client, client2)
        other, stranger, _, _ = self.order_for('0100000017', 'cedula', 'm003', 'listo')
        with test_app.open_requests(), patch.object(app, 'limited', return_value=False):
            for code, hour in ((first['code'], '09:00'), (second['code'], '10:00')):
                ok = self.book('id-m-' + code[-4:], hour, identification=RUC, document_type='ruc', service='retiro', order_code=code)
                self.assertEqual((ok['status'], ok['body'].get('pickup_order')), (201, code), ok['body'])
            # Orden de otra persona: el mismo mensaje que una inexistente; nunca se revela nada de ese cliente.
            unknown = 'No encontramos una orden con ese número asociada a tus datos. Verifícalo o deja el campo vacío.'
            for code in (other['code'], 'PCD-20990101-9999'):
                denied = self.book('id-m-x' + code[-4:], '11:00', identification=RUC, document_type='ruc', service='retiro', order_code=code)
                self.assertEqual((denied['status'], denied['body']['fields'].get('order_code')), (400, unknown))
                self.assertNotIn('0100000017', str(denied['body']))
            bad = self.book('id-m-b', '11:00', identification='1710034066', document_type='cedula', service='mantenimiento')
            self.assertEqual((bad['status'], bad['body']['fields'].get('identification')), (400, 'El número de cédula no es válido. Revisa los dígitos ingresados.'))
            wrong4 = self.book('id-m-w', '11:00', identification=RUC, document_type='ruc', service='mantenimiento', id_last4='9999')
            self.assertEqual(wrong4['status'], 400)
            self.assertIn('cédula o de tu RUC', wrong4['body']['fields'].get('id_last4', ''))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM appointments WHERE client_id=?', (stranger,)).fetchone()[0], 0)

    def test_already_confirmed_appointment_and_maintenance_link(self):
        order, client, cookie, csrf = self.order_for(RUC, 'ruc', 'k001')
        with test_app.open_requests(), patch.object(app, 'limited', return_value=False):
            first = self.book('id-k-1', '09:00', identification=CEDULA, document_type='cedula', service='mantenimiento')
            again = self.book('id-k-1', '09:00', identification=CEDULA, document_type='cedula', service='mantenimiento')
        self.assertEqual((first['status'], again['status'], again['body'].get('duplicate')), (201, 200, True))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM appointment_authorizations WHERE appointment_id=?', (first['body']['id'],)).fetchone()[0], 1)
        # Enlace seguro del mantenimiento (sin pedir cédula ni RUC): confirmar dos veces registra una sola respuesta y muestra el estado real.
        self.assertEqual(self.request('/api/order-status', {'id': str(order['id']), 'status': 'entregado'}, cookie=cookie, csrf=csrf)['status'], 200)
        with app.connect() as c:
            c.execute('UPDATE maintenance SET due_date=? WHERE order_id=?', ((app.reception_now().date() + timedelta(days=10)).isoformat(), order['id']))
            c.commit()
            token = c.execute('SELECT unsubscribe_token FROM maintenance WHERE order_id=?', (order['id'],)).fetchone()[0]
        page = self.request('/mantenimiento/' + token)['body']
        self.assertIn('Confirmar esta fecha', page)
        for private in (RUC, CEDULA, 'cliente@example.invalid'):
            self.assertNotIn(private, page)
        self.assertIn('Registramos su confirmación', self.form(token, {'action': 'confirm'})['body'])
        self.form(token, {'action': 'confirm'})
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM maintenance_responses WHERE action='confirm'").fetchone()[0], 1)
        reopened = self.request('/mantenimiento/' + token)['body']
        self.assertIn('Ya confirmó esta fecha', reopened)
        self.assertNotIn('Confirmar esta fecha', reopened)
        self.assertIn('Solicitar otro horario', reopened)

    def test_registered_document_and_legacy_clients(self):
        order, client, cookie, csrf = self.order_for(CEDULA, 'cedula', 'd001')
        # Registrar la misma persona con su RUC: se avisa y se ofrece su ficha; no se crea un duplicado.
        payload = dict(self.order_data({'identification': '0100000017'}), name='Otra Ficha Ficticia', identification=RUC, document_type='ruc')
        twin = self.request('/api/client-registry', payload, cookie=cookie, csrf=csrf)
        self.assertEqual((twin['status'], twin['body'].get('existing_id')), (409, client), twin['body'])
        self.assertIn('ya está registrada con su cédula', twin['body']['error'])
        company = self.request('/api/client-registry', dict(payload, identification=COMPANY_RUC), cookie=cookie, csrf=csrf)
        self.assertIn(company['status'], (200, 201), company['body'])  # una sociedad es otra persona
        # Cliente anterior a la corrección con un RUC que no cumple la regla de la cédula (como uno real de producción).
        legacy = '1710034066001'
        self.assertTrue(reception.document_error(legacy, 'ruc'))
        with app.connect() as c:
            fields = dict(c.execute('SELECT * FROM clients WHERE id=?', (client,)).fetchone())
            cols = [k for k in fields if k not in ('id',) and fields[k] is not None]
            values = dict(fields, identification=legacy, document_type='ruc', identity_key='ruc:' + legacy, name='Cliente Antiguo Ficticio', email='antiguo@example.invalid')
            old_id = c.execute('INSERT INTO clients(%s) VALUES (%s)' % (','.join(cols), ','.join('?' * len(cols))), [values[k] for k in cols]).lastrowid
            c.commit()
        before = self.clients()
        with test_app.open_requests(), patch.object(app, 'limited', return_value=False):
            booked = self.book('id-d-1', '09:00', identification=legacy, document_type='ruc', service='mantenimiento', id_last4=legacy[-4:])
            self.assertEqual(booked['status'], 201, booked['body'])
            new_bad = self.book('id-d-2', '10:00', identification='1710034067001', document_type='ruc', service='mantenimiento')
            self.assertEqual(new_bad['status'], 400)  # un documento nuevo sí debe ser válido
        self.assertEqual((self.appointment_client(booked['body']['id']), self.clients()), (old_id, before))
        received = self.request('/api/orders', dict(self.order_data({'identification': '0100000017'}), client_id=str(old_id), request_key='identity-order-legacy'), cookie=cookie, csrf=csrf)
        self.assertEqual(received['status'], 201, received['body'])  # su equipo se recibe con el documento con el que fue registrado


if __name__ == '__main__':
    unittest.main()
