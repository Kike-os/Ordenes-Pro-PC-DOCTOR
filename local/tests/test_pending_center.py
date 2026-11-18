"""1.5.287 · Centro de notificaciones y pendientes 2.0.
Los contadores salen de condiciones reales (no de avisos): una cita cuenta solo mientras está «solicitada»; un presupuesto, mientras
espera decisión o pide cambios; una orden, hasta entregarse. Leído, oculto, estado y prioridad son independientes: marcar como visto u
ocultar no resuelve nada, y un pendiente desaparece solo cuando su módulo de origen cambia. Cada técnico ve lo suyo y lo sin asignar."""
import re
import time
import unittest
from datetime import timedelta

import test_app  # primero: ruta de importación y base temporal
import app
import appointments
import notifications
import pending_center

ROUTES = re.compile(r'#(orders\?id=\d+|appointments\?appointment=\d+|deliveries|pqrs\?id=\d+|live|licenses|maintenance\?order=\d+|system(\?autocare=1)?|settings\?tab=\w+|mail.*|invoicing.*)$')


class PendingCenterTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login

    # ---- datos ficticios ----
    def client(self, c, name):
        cid = c.execute('INSERT INTO clients(name,phone) VALUES (?,?)', (name, '0990000000')).lastrowid
        return c.execute("INSERT INTO devices(client_id,type,category,kind,brand,model) VALUES (?,'portatil','portatil','portatil','HP','Ficticio')", (cid,)).lastrowid

    def order(self, c, status, code, assigned=None, due='', priority='normal', name='Cliente ficticio'):
        device = self.client(c, name)
        return c.execute("INSERT INTO orders(device_id,status,problem,created_by,created_at,code,received_at,assigned_to,estimated_delivery,priority,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (device, status, 'Falla ficticia', self.uid, int(time.time()), code, appointments.stamp(appointments.now()), assigned, due, priority, appointments.stamp(appointments.now()))).lastrowid

    def appointment(self, c, status, hours, deleted=False, created=None, tech=None):
        now = appointments.now()
        n = c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0] + 1
        return c.execute("INSERT INTO appointments(public_code,manage_token_hash,customer_name,phone,device_type,service_code,description,starts_at,duration_minutes,status,privacy_consent,created_at,updated_at,deleted_at,technician_id) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)", ('CITA-F%03d' % n, 'hash-ficticio-%d' % n, 'Cliente de cita %d' % n, '0990000000', 'portatil', 'diagnostico', 'Prueba ficticia',
                                                                    appointments.stamp(now + timedelta(hours=hours)), 60, status, created or appointments.stamp(now), appointments.stamp(now),
                                                                    appointments.stamp(now) if deleted else None, tech)).lastrowid

    def quote(self, c, order, status, code, valid='', deleted=''):
        now = appointments.stamp(appointments.now())
        version = c.execute('SELECT COUNT(*) FROM quotes WHERE order_id=?', (order,)).fetchone()[0] + 1
        return c.execute("INSERT INTO quotes(order_id,version,code,status,tax_rate_bp,valid_until,created_at,updated_at,sent_at,deleted_at) VALUES (?,?,?,?,1500,?,?,?,?,?)",
                         (order, version, code, status, valid, now, now, now, deleted)).lastrowid

    def part(self, c, order, stage, situation='normal', eta=''):
        now = appointments.stamp(appointments.now())
        return c.execute("INSERT INTO order_part_requests(order_id,name,stage,situation,eta,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                         (order, 'Repuesto ficticio', stage, situation, eta, self.uid, now, now)).lastrowid

    def pending(self, cookie, since=''):
        result = self.request('/api/pending' + ('?since=' + since if since else ''), cookie=cookie)
        self.assertEqual(result['status'], 200, result['body'])
        return result['body']

    # ---- pruebas ----
    def test_counters_come_from_real_conditions(self):
        today = appointments.now().date()
        with app.connect() as c:
            # Citas: solo cuentan las «solicitada» vigentes (no confirmadas, canceladas, cerradas ni eliminadas).
            asked = [self.appointment(c, 'solicitada', h) for h in (5, 30, 100, 200, 300)] + [self.appointment(c, 'solicitada', -3)]
            for status in ('confirmada', 'reprogramada', 'cancelada', 'completada', 'no_asistio', 'presente'):
                self.appointment(c, status, 50)
            self.appointment(c, 'solicitada', 60, deleted=True)
            # Órdenes: todas las no entregadas; la vencida es urgente.
            late = self.order(c, 'reparacion', 'OP-F1', due=(today - timedelta(days=2)).isoformat())
            ready = self.order(c, 'listo', 'OP-F2')
            waiting = self.order(c, 'presupuesto', 'OP-F3')
            self.order(c, 'entregado', 'OP-F4')
            # Presupuestos: enviados y con pedido de cambios; no los aprobados, cancelados, borradores ni eliminados.
            self.quote(c, waiting, 'enviado', 'PCD-F-P1', valid=(today - timedelta(days=1)).isoformat())
            self.quote(c, ready, 'modificacion', 'PCD-F-P2')
            for status in ('aprobado', 'cancelado', 'borrador', 'rechazado', 'parcial'):
                self.quote(c, late, status, 'PCD-F-X' + status)
            self.quote(c, late, 'enviado', 'PCD-F-DEL', deleted=appointments.stamp(appointments.now()))
            # Repuestos: en camino o recibidos; no los instalados ni los cancelados.
            self.part(c, late, 'transito', eta=(today - timedelta(days=1)).isoformat())
            self.part(c, late, 'recibido')
            self.part(c, late, 'instalado')
            self.part(c, late, 'solicitado', situation='cancelado')
        cookie, csrf = self.login()
        data = self.pending(cookie)
        s = data['summary']
        self.assertEqual(s['appointments']['count'], 6)
        self.assertEqual((s['appointments']['overdue'], s['appointments']['urgent']), (1, 2))  # la de fecha pasada y la de dentro de 5 h
        self.assertEqual(s['orders']['count'], 3)
        self.assertEqual(s['orders']['overdue'], 1)
        self.assertEqual(s['quotes']['count'], 2)
        self.assertEqual(s['parts']['count'], 2)
        for module, box in s.items():  # cada contador coincide con lo que se lista
            self.assertEqual(box['count'], sum(1 for i in data['items'] if i['module'] == module), module)
        mine = {i['key'] for i in data['items'] if i['module'] == 'appointments'}
        self.assertEqual(mine, {'pending:appointments:%d' % a for a in asked})
        self.assertEqual(len(data['items']), len({i['key'] for i in data['items']}))  # sin duplicados
        for item in data['items']:
            self.assertIn(item['state'], tuple(pending_center.STATES))
            self.assertIn(item['priority'], ('normal', 'importante', 'urgente', 'critico'))
            for target in [item['href']] + [a['href'] for a in item['actions']]:
                self.assertRegex(target, ROUTES)
        quote = next(i for i in data['items'] if i['title'].endswith('PCD-F-P1'))
        self.assertEqual((quote['priority'], quote['overdue'], quote['href']), ('urgente', True, '#orders?id=%d' % waiting))
        self.assertEqual(next(i for i in data['items'] if i['key'] == 'pending:orders:%d:reparacion' % late)['state'], 'en_proceso')
        # Lo crítico (fallos del sistema) va primero; después, lo urgente y vencido.
        self.assertIn(data['items'][0]['priority'], ('critico', 'urgente'))
        self.assertTrue(all(i['module'] == 'alerts' for i in data['items'] if i['priority'] == 'critico'))
        self.assertEqual(next(i for i in data['items'] if i['priority'] != 'critico')['priority'], 'urgente')
        # Las solicitudes coinciden con el contador del inicio (que solo cuenta las futuras) más la vencida, que se marca aparte.
        self.assertEqual(self.request('/api/dashboard', cookie=cookie)['body']['pending_appointments'], 5)

    def test_read_hidden_state_and_resolution_are_separate(self):
        with app.connect() as c:
            aid = self.appointment(c, 'solicitada', 48)
            order = self.order(c, 'diagnostico', 'OP-F9')
        cookie, csrf = self.login()
        key = 'pending:appointments:%d' % aid
        data = self.pending(cookie)
        item = next(i for i in data['items'] if i['key'] == key)
        self.assertFalse(item['read'])
        # Marcar como visto no lo resuelve: sigue en la lista, ahora leído.
        self.assertEqual(self.request('/api/notifications/read', {'keys': key}, cookie=cookie, csrf=csrf)['status'], 200)
        item = next(i for i in self.pending(cookie)['items'] if i['key'] == key)
        self.assertTrue(item['read'])
        # Un pendiente no se puede ocultar: la petición no lo registra y sigue visible.
        self.request('/api/notifications/hide', {'keys': key}, cookie=cookie, csrf=csrf)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM notification_hidden WHERE key=?', (key,)).fetchone()[0], 0)
        self.assertIn(key, {i['key'] for i in self.pending(cookie)['items']})
        # Se resuelve en su módulo: al cancelar la cita en la Agenda deja de ser pendiente (la cita se conserva).
        self.assertEqual(self.request('/api/appointments/%d' % aid, {'action': 'cancelada'}, cookie=cookie, csrf=csrf)['status'], 200)
        self.assertNotIn(key, {i['key'] for i in self.pending(cookie)['items']})
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM appointments WHERE id=?', (aid,)).fetchone()[0], 'cancelada')
        # Un cambio de estado de la orden es un pendiente nuevo (vuelve a aparecer como no visto) y la entrega lo quita.
        self.request('/api/notifications/read', {'keys': 'pending:orders:%d:diagnostico' % order}, cookie=cookie, csrf=csrf)
        with app.connect() as c:
            c.execute("UPDATE orders SET status='listo' WHERE id=?", (order,))
        item = next(i for i in self.pending(cookie)['items'] if i['module'] == 'orders')
        self.assertEqual((item['key'], item['read'], item['state']), ('pending:orders:%d:listo' % order, False, 'pendiente'))
        with app.connect() as c:
            c.execute("UPDATE orders SET status='entregado' WHERE id=?", (order,))
        self.assertEqual(self.pending(cookie)['summary']['orders']['count'], 0)

    def test_system_alerts_survive_hiding_the_notice(self):
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at,approval) VALUES ('nuevo','nuevo@example.invalid','Solicitud ficticia','x','tecnico',0,'pending')")
        cookie, csrf = self.login()
        alerts = [i for i in self.pending(cookie)['items'] if i['module'] == 'alerts']
        key = next(i['key'] for i in alerts if i['key'].startswith('alert:accounts:'))
        self.assertEqual(self.request('/api/notifications/hide', {'keys': key}, cookie=cookie, csrf=csrf)['status'], 200)
        self.assertNotIn(key, {i['key'] for i in self.request('/api/notifications', cookie=cookie)['body']['items']})  # oculta en Notificaciones
        self.assertIn(key, {i['key'] for i in self.pending(cookie)['items']})  # pero la condición sigue pendiente
        with app.connect() as c:
            c.execute("UPDATE users SET approval='approved' WHERE username='nuevo'")
        self.assertNotIn(key, {i['key'] for i in self.pending(cookie)['items']})

    def test_technician_sees_own_and_unassigned_only(self):
        with app.connect() as c:
            tech = c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tec','tec@example.invalid','Técnico ficticio',?,'tecnico',?)", (self.hash, int(time.time()))).lastrowid
            other = c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('otro','otro@example.invalid','Otro técnico',?,'tecnico',?)", (self.hash, int(time.time()))).lastrowid
            own = self.order(c, 'reparacion', 'OP-T1', assigned=tech)
            free = self.order(c, 'pendiente', 'OP-T2')
            foreign = self.order(c, 'reparacion', 'OP-T3', assigned=other, name='Cliente ajeno')
            self.quote(c, foreign, 'enviado', 'PCD-T-P1')
            self.part(c, foreign, 'recibido')
            self.appointment(c, 'solicitada', 40, tech=other)
            mine = self.appointment(c, 'solicitada', 40, tech=tech)
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at,approval) VALUES ('nuevo','nuevo@example.invalid','Solicitud ficticia','x','tecnico',0,'pending')")
        login = self.request('/api/login', {'login': 'tec', 'password': 'contraseña-segura-de-prueba'})
        cookie = login['cookie'].split(';')[0]
        data = self.pending(cookie)
        self.assertEqual(data['modules'], ['orders', 'appointments', 'quotes', 'parts', 'messages'])  # sin licencias ni alertas del sistema
        keys = {i['key'] for i in data['items']}
        self.assertEqual(keys, {'pending:orders:%d:reparacion' % own, 'pending:orders:%d:pendiente' % free, 'pending:appointments:%d' % mine})
        self.assertNotIn('Cliente ajeno', str(data))
        self.assertEqual(self.request('/api/pending')['status'], 401)

    def test_unchanged_revision_is_cheap(self):
        with app.connect() as c:
            self.appointment(c, 'solicitada', 30)
        cookie, csrf = self.login()
        first = self.pending(cookie)
        same = self.pending(cookie, since=first['rev'])
        self.assertEqual((same.get('unchanged'), same['rev'], 'items' in same), (True, first['rev'], False))
        with app.connect() as c:
            self.appointment(c, 'solicitada', 60)
        changed = self.pending(cookie, since=first['rev'])
        self.assertNotEqual(changed['rev'], first['rev'])
        self.assertEqual(changed['summary']['appointments']['count'], 2)

    def test_notifications_list_every_request_and_only_recent_confirmations(self):
        old = appointments.stamp(appointments.now() - timedelta(days=5))
        with app.connect() as c:
            asked = [self.appointment(c, 'solicitada', 24 + h) for h in range(9)]
            stale = [self.appointment(c, 'confirmada', 30, created=old) for _ in range(3)]
            fresh = self.appointment(c, 'confirmada', 30)
            for n in range(45):  # muchos avisos: marcar y ocultar deben funcionar más allá de los 40 que se muestran
                c.execute("INSERT INTO order_history(order_id,event,status_label,comment,occurred_at) VALUES (?,?,?,?,?)",
                          (self.order(c, 'reparacion', 'OP-N%02d' % n), 'follow_up', '', 'Seguimiento ficticio', appointments.stamp(appointments.now() - timedelta(days=3))))
        cookie, csrf = self.login()
        with app.connect() as c:
            items = notifications.build(c, {'id': self.uid, 'role': 'administrador'}, app.reception_now(), limit=None)['items']
        listed = {i['key'] for i in items if i['key'].startswith('appointment:')}
        self.assertEqual(listed, {'appointment:%d' % a for a in asked + [fresh]})
        self.assertFalse(listed & {'appointment:%d' % a for a in stale})
        last = [i['key'] for i in items if i['key'].startswith('event:')][-1]
        self.assertEqual(self.request('/api/notifications/read', {'keys': last}, cookie=cookie, csrf=csrf)['status'], 200)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM notification_reads WHERE key=?', (last,)).fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
