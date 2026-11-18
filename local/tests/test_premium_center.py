"""1.5.289 · Centro de Notificaciones y Pendientes Premium 3.0: reglas de urgencia configurables, estados operativos, responsable del
seguimiento, posponer, «Solucionadas», agrupación de duplicados y carga progresiva. Datos ficticios en una base temporal: comprueba que
nada de esto resuelve un pendiente, que se respetan los permisos (asignar no amplía el acceso de nadie) y que los contadores salen de
registros reales."""
import time
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_app  # primero: ruta de importación y base temporal
import app
import appointments
import pending_center
import test_pending_center


class PremiumCenterTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login
    _B = test_pending_center.PendingCenterTests  # mismos datos ficticios; la clase no se importa al módulo (no se ejecuta dos veces)
    client, order, appointment, quote, part, pending = _B.client, _B.order, _B.appointment, _B.quote, _B.part, _B.pending
    del _B

    def item(self, cookie, key):
        return next((i for i in self.pending(cookie)['items'] if key in (i['key'], i['entity'])), None)

    def act(self, cookie, csrf, **data):
        return self.request('/api/pending/action', data, cookie=cookie, csrf=csrf)

    def technician(self, c, username='tec'):
        return c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES (?,?,?,?,'tecnico',?)",
                         (username, username + '@example.invalid', 'Técnico ficticio ' + username, self.hash, int(time.time()))).lastrowid

    def login_as(self, username):
        login = self.request('/api/login', {'login': username, 'password': 'contraseña-segura-de-prueba'})
        cookie = login['cookie'].split(';')[0]
        return cookie, self.request('/api/me', cookie=cookie)['body']['user']['csrf']

    def test_rules_change_priority_only_with_valid_admin_values(self):
        with app.connect() as c:
            self.technician(c)
            cita = self.appointment(c, 'solicitada', 30)
        cookie, csrf = self.login()
        entity = 'appointments:%d' % cita
        data = self.pending(cookie)
        self.assertEqual(data['rules'], {k: v[0] for k, v in pending_center.RULES.items()})  # por defecto, los criterios de siempre
        self.assertEqual(self.item(cookie, entity)['priority'], 'importante')               # 30 h: entre 24 y 72
        rules = {k: str(v) for k, v in data['rules'].items()}   # el formulario envía texto
        # Fuera de rango, incoherente o sin permisos: no se guarda nada.
        bad = self.request('/api/pending/rules', dict(rules, appointments_urgent_hours='0'), cookie=cookie, csrf=csrf)
        self.assertEqual((bad['status'], 'appointments_urgent_hours' in bad['body']['fields']), (400, True))
        crossed = self.request('/api/pending/rules', dict(rules, appointments_urgent_hours='100', appointments_important_hours='50'), cookie=cookie, csrf=csrf)
        self.assertEqual(crossed['status'], 400)
        tcookie, tcsrf = self.login_as('tec')
        self.assertEqual(self.request('/api/pending/rules', dict(rules, appointments_urgent_hours='48'), cookie=tcookie, csrf=tcsrf)['status'], 403)
        self.assertNotIn('rules', self.pending(tcookie))
        self.assertEqual(self.item(cookie, entity)['priority'], 'importante')
        saved = self.request('/api/pending/rules', dict(rules, appointments_urgent_hours='48'), cookie=cookie, csrf=csrf)
        self.assertEqual(saved['status'], 200, saved['body'])
        self.assertEqual(self.item(cookie, entity)['priority'], 'urgente')  # ahora 30 h < 48 h
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='pending_rules_updated'").fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT status FROM appointments WHERE id=?', (cita,)).fetchone()[0], 'solicitada')  # el registro no cambia
        self.assertEqual(self.request('/api/pending/rules', {'reset': True}, cookie=cookie, csrf=csrf)['status'], 200)
        self.assertEqual(self.item(cookie, entity)['priority'], 'importante')

    def test_operational_states_come_from_the_source_record(self):
        today = appointments.now().date()
        with app.connect() as c:
            waiting = self.order(c, 'reparacion', 'OP-P1')
            sent = self.quote(c, waiting, 'enviado', 'PRE-P1', (today + timedelta(days=10)).isoformat())
            expired_order = self.order(c, 'reparacion', 'OP-P2')
            expired = self.quote(c, expired_order, 'enviado', 'PRE-P2', (today - timedelta(days=1)).isoformat())
            supplier = self.order(c, 'esperando_repuesto', 'OP-P3')
            transit = self.part(c, supplier, 'transito')
            received = self.part(c, supplier, 'recibido')
        cookie, csrf = self.login()
        data = self.pending(cookie)
        state = lambda entity: next(i for i in data['items'] if i['entity'] == entity)['state']
        self.assertEqual(state('quotes:%d' % sent), 'espera_cliente')
        self.assertEqual(state('quotes:%d' % expired), 'pendiente')   # vencido: ya no se espera, hay que actuar
        self.assertEqual(state('orders:%d' % supplier), 'espera_tercero')
        self.assertEqual(state('parts:%d' % transit), 'espera_tercero')
        self.assertEqual(state('parts:%d' % received), 'pendiente')
        self.assertEqual(state('orders:%d' % waiting), 'en_proceso')
        self.assertTrue(all(i['state'] in pending_center.STATES for i in data['items']))

    def test_postpone_and_resume_are_logged_and_never_resolve(self):
        tomorrow = (appointments.now().date() + timedelta(days=1)).isoformat()
        with app.connect() as c:
            order = self.order(c, 'pendiente', 'OP-P4')
        cookie, csrf = self.login()
        entity = 'orders:%d' % order
        self.assertTrue(self.item(cookie, entity)['mine'])
        self.assertEqual(self.act(cookie, csrf, action='postpone', key=entity, date=appointments.now().date().isoformat(), body='Motivo válido')['status'], 400)
        self.assertEqual(self.act(cookie, csrf, action='postpone', key=entity, date=tomorrow, body='')['status'], 400)
        ok = self.act(cookie, csrf, action='postpone', key=entity, date=tomorrow, body='Cliente viaja hasta mañana')
        self.assertEqual(ok['status'], 200, ok['body'])
        again = self.act(cookie, csrf, action='postpone', key=entity, date=tomorrow, body='Cliente viaja hasta mañana')
        self.assertTrue(again['body'].get('duplicate'))   # doble clic: una sola fila
        data = self.pending(cookie)
        item = next(i for i in data['items'] if i['entity'] == entity)
        self.assertEqual((item['state'], item['postponed']['until'], item['mine']), ('pospuesto', tomorrow, False))
        self.assertEqual(data['totals']['postponed'], 1)
        self.assertEqual(data['items'][-1]['entity'], entity)   # pasa al final: no compite con lo que requiere atención
        self.assertEqual(self.act(cookie, csrf, action='resume', key=entity)['status'], 200)
        self.assertEqual(self.act(cookie, csrf, action='resume', key=entity)['status'], 409)
        self.assertNotEqual(self.item(cookie, entity)['state'], 'pospuesto')
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM orders WHERE id=?', (order,)).fetchone()[0], 'pendiente')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action IN ('pending_postpone','pending_resume')").fetchone()[0], 2)
            # Registro de solo anexado: no se edita ni se borra.
            with self.assertRaises(Exception):
                c.execute("UPDATE pending_tracking SET body='x'")
            with self.assertRaises(Exception):
                c.execute('DELETE FROM pending_tracking')

    def test_critical_failure_cannot_be_postponed(self):
        cookie, csrf = self.login()
        critical = {'key': 'storage:prueba', 'kind': 'error', 'title': 'Almacenamiento ficticio no disponible', 'detail': 'Prueba', 'at': appointments.stamp(appointments.now()), 'href': '#system'}
        tomorrow = (appointments.now().date() + timedelta(days=1)).isoformat()
        with patch.object(app.notifications, 'build', side_effect=lambda *a, **k: {'items': [critical], 'unread': 1}):
            refused = self.act(cookie, csrf, action='postpone', key='storage:prueba', date=tomorrow, body='Intento de aplazar')
            self.assertEqual(refused['status'], 409)
            self.assertEqual(self.item(cookie, 'storage:prueba')['state'], 'pendiente')

    def test_follow_up_owner_respects_access(self):
        with app.connect() as c:
            tech = self.technician(c, 'tec')
            other = self.technician(c, 'tec2')
            free = self.appointment(c, 'solicitada', 50)
            taken = self.appointment(c, 'solicitada', 60, tech=tech)
            order = self.order(c, 'pendiente', 'OP-P5')
        cookie, csrf = self.login()
        tcookie, tcsrf = self.login_as('tec')
        free_e, taken_e = 'appointments:%d' % free, 'appointments:%d' % taken
        # Un técnico no asigna a otros; solo administración.
        self.assertEqual(self.act(tcookie, tcsrf, action='assign', key=free_e, user=str(other))['status'], 403)
        # Asignar a quien no ve el pendiente (la cita es de otro técnico) se rechaza: no amplía el acceso.
        blocked = self.act(cookie, csrf, action='assign', key=taken_e, user=str(other))
        self.assertEqual(blocked['status'], 409, blocked['body'])
        # Las órdenes se asignan en su módulo (con su control de revisión), no aquí.
        self.assertEqual(self.act(cookie, csrf, action='assign', key='orders:%d' % order, user=str(tech))['status'], 400)
        done = self.act(cookie, csrf, action='assign', key=free_e, user=str(other), body='Llamar al cliente hoy')
        self.assertEqual(done['status'], 200, done['body'])
        again = self.act(cookie, csrf, action='assign', key=free_e, user=str(other))
        self.assertTrue(again['body'].get('unchanged'))
        item = self.item(cookie, free_e)
        self.assertEqual((item['responsible'], item['others'], item['mine'], item['assigned']['by']), ('Técnico ficticio tec2', True, False, 'Persona de prueba'))
        # El técnico «tec» sigue viendo la cita libre en el módulo, pero ya tiene responsable: no la puede tomar.
        self.assertEqual(self.act(tcookie, tcsrf, action='take', key=free_e)['status'], 409)
        # Una cita sin responsable sí se puede tomar.
        with app.connect() as c:
            spare = self.appointment(c, 'solicitada', 70)
        took = self.act(tcookie, tcsrf, action='take', key='appointments:%d' % spare)
        self.assertEqual(took['status'], 200, took['body'])
        mine = self.item(tcookie, 'appointments:%d' % spare)
        self.assertEqual((mine['responsible_id'], mine['mine']), (tech, True))
        detail = self.request('/api/pending/item?key=' + free_e, cookie=cookie)['body']
        self.assertTrue(any('Responsable del seguimiento' in e['text'] for e in detail['history']))
        self.assertTrue(detail['context']['follow_owner'] and detail['context']['assignees'])
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='pending_assign'").fetchone()[0], 2)
            self.assertIsNone(c.execute('SELECT technician_id FROM appointments WHERE id=?', (free,)).fetchone()[0])  # el registro de origen no cambia

    def test_order_assignment_records_date_and_author(self):
        with app.connect() as c:
            tech = self.technician(c)
            order = self.order(c, 'diagnostico', 'OP-P6')
        cookie, csrf = self.login()
        out = self.act(cookie, csrf, action='assign', order_id=str(order), technician=str(tech), revision='0')
        self.assertEqual(out['status'], 200, out['body'])
        item = self.item(cookie, 'orders:%d' % order)
        self.assertEqual((item['responsible_id'], item['assigned']['by']), (tech, 'Persona de prueba'))
        with app.connect() as c:   # si cambia después en la orden, manda la orden y no se inventa la fecha
            c.execute('UPDATE orders SET assigned_to=NULL WHERE id=?', (order,))
        item = self.item(cookie, 'orders:%d' % order)
        self.assertEqual((item['responsible_id'], 'assigned' in item), (None, False))

    def test_resolved_feed_and_counter_follow_real_module_actions(self):
        with app.connect() as c:
            tech = self.technician(c)
            order = self.order(c, 'listo', 'OP-P7')
            cita = self.appointment(c, 'solicitada', 40)
        cookie, csrf = self.login()
        self.assertEqual(self.pending(cookie)['totals']['resolved_today'], 0)
        delivered = self.request('/api/order-status', {'id': str(order), 'status': 'entregado', 'comment': '', 'notify': '0'}, cookie=cookie, csrf=csrf)
        self.assertEqual(delivered['status'], 200, delivered['body'])
        cancelled = self.request('/api/appointments/%d' % cita, {'action': 'cancelada', 'reason': 'Cliente ya no lo necesita'}, cookie=cookie, csrf=csrf)
        self.assertEqual(cancelled['status'], 200, cancelled['body'])
        data = self.pending(cookie)
        self.assertIsNone(next((i for i in data['items'] if i['entity'] in ('orders:%d' % order, 'appointments:%d' % cita)), None))
        self.assertEqual(data['totals']['resolved_today'], 2)
        feed = self.request('/api/pending/resolved', cookie=cookie)['body']
        by = {r['entity']: r for r in feed['rows']}
        self.assertEqual((by['orders:%d' % order]['outcome'], by['orders:%d' % order]['actor']), ('resuelto', 'Persona de prueba'))
        self.assertEqual(by['appointments:%d' % cita]['outcome'], 'cancelado')
        self.assertEqual(self.request('/api/pending/resolved?outcome=cancelado', cookie=cookie)['body']['total'], 1)
        self.assertEqual(self.request('/api/pending/resolved?from=2026-13-01', cookie=cookie)['status'], 400)
        # Un técnico solo ve lo que resolvió él.
        tcookie, _ = self.login_as('tec')
        self.assertEqual(self.request('/api/pending/resolved', cookie=tcookie)['body']['total'], 0)
        self.assertEqual(self.pending(tcookie)['totals']['resolved_today'], 0)
        self.assertEqual(self.request('/api/pending/resolved')['status'], 401)

    def test_equivalent_alerts_group_without_losing_originals(self):
        now = appointments.stamp(appointments.now())
        bounce = lambda n, detail='Buzón inexistente': {'key': 'mail:bounce:1:%d' % n, 'kind': 'warning', 'title': 'Correo devuelto · cliente@example.invalid', 'detail': detail, 'at': now, 'href': '#mail'}
        items = pending_center._alerts([bounce(1), bounce(2), bounce(3, 'Otro motivo')])
        self.assertEqual(len(items), 2)
        grouped = next(i for i in items if i['ref']['count'] == 2)
        self.assertEqual((grouped['key'], grouped['ref']['keys']), ('mail:bounce:1:1', ['mail:bounce:1:1', 'mail:bounce:1:2']))
        cookie, csrf = self.login()
        with patch.object(app.notifications, 'build', side_effect=lambda *a, **k: {'items': [bounce(1), bounce(2)], 'unread': 2}):
            data = self.pending(cookie)
            alerts = [i for i in data['items'] if i['module'] == 'alerts' and i['key'].startswith('mail:bounce')]
            self.assertEqual((len(alerts), alerts[0]['read']), (1, False))
            self.request('/api/notifications/read', {'keys': 'mail:bounce:1:1'}, cookie=cookie, csrf=csrf)
            self.assertFalse(next(i for i in self.pending(cookie)['items'] if i['key'] == 'mail:bounce:1:1')['read'])  # falta el segundo aviso

    def test_notifications_share_thread_only_when_equivalent(self):
        with app.connect() as c:
            order = self.order(c, 'diagnostico', 'OP-P8')
            other = self.order(c, 'diagnostico', 'OP-P9')
            for oid in (order, order, other):
                c.execute("INSERT INTO order_history(order_id,actor_id,event,status_label,comment,occurred_at) VALUES (?,NULL,'follow_up','',?,?)",
                          (oid, 'Aviso de autorización enviado al correo administrativo.', appointments.stamp(appointments.now())))
        cookie, csrf = self.login()
        items = [i for i in self.request('/api/notifications', cookie=cookie)['body']['items'] if 'autorización' in (i.get('detail') or '')]
        threads = {}
        for i in items:
            threads.setdefault(i['thread'], []).append(i['key'])
        self.assertEqual(sorted(len(v) for v in threads.values()), [1, 2])   # misma orden y mismo evento: un grupo; otra orden: aparte
        self.assertEqual(len(items), 3)   # no se elimina ninguno

    def test_activity_loads_progressively_and_search_includes_email(self):
        with app.connect() as c:
            order = self.order(c, 'diagnostico', 'OP-P10')
            c.execute("UPDATE clients SET email='buscable@example.invalid' WHERE id=(SELECT d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?)", (order,))
        cookie, csrf = self.login()
        self.assertIn('buscable@example.invalid', self.item(cookie, 'orders:%d' % order)['search'])
        for n in range(105):
            self.act(cookie, csrf, action='note', key='orders:%d' % order, body='Observación ficticia número %d' % n)
        first = self.request('/api/pending/activity?kind=gestion', cookie=cookie)['body']
        self.assertEqual((len(first['rows']), first['more'], first['total']), (100, True, 105))
        second = self.request('/api/pending/activity?kind=gestion&page=2', cookie=cookie)['body']
        self.assertEqual((len(second['rows']), second['more']), (5, False))
        csv = self.request('/api/pending/activity.csv?kind=gestion', cookie=cookie)
        self.assertEqual(csv['status'], 200)

    def test_order_resolution_flow_uses_real_services(self):
        """Flujo de resolución de una orden desde el panel: diagnóstico, seguimiento, cambio de estado con control de concurrencia y
        entrega; marcar como visto u ocultar no cambia la orden; un presupuesto no se aprueba sin decisión registrada del cliente."""
        with app.connect() as c:
            tech = self.technician(c)
            order = self.order(c, 'diagnostico', 'OP-R1', assigned=tech)
            quote = self.quote(c, order, 'enviado', 'PRE-R1')
        cookie, csrf = self.login()
        entity = 'orders:%d' % order
        item = self.item(cookie, entity)
        # Leer el aviso no cambia la orden.
        self.assertEqual(self.request('/api/notifications/read', {'keys': item['key']}, cookie=cookie, csrf=csrf)['status'], 200)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT status,revision FROM orders WHERE id=?', (order,)).fetchone()[:], ('diagnostico', 0))
        detail = self.request('/api/pending/item?key=' + entity, cookie=cookie)['body']
        self.assertEqual((detail['context']['problem'], [q['code'] for q in detail['context']['quotes']]), ('Falla ficticia', ['PRE-R1']))
        # Diagnóstico: solo administración, texto obligatorio, revisión vigente.
        tcookie, tcsrf = self.login_as('tec')
        self.assertEqual(self.act(tcookie, tcsrf, action='diagnosis', order_id=str(order), revision='0', findings='Disco con sectores dañados')['status'], 403)
        self.assertEqual(self.act(cookie, csrf, action='diagnosis', order_id=str(order), revision='0', findings='')['status'], 400)
        self.assertEqual(self.act(cookie, csrf, action='diagnosis', order_id=str(order), revision='7', findings='Disco con sectores dañados')['status'], 409)
        saved = self.act(cookie, csrf, action='diagnosis', order_id=str(order), revision='0', findings='Disco con sectores dañados', recommendations='Reemplazar por SSD')
        self.assertEqual(saved['status'], 200, saved['body'])
        twice = self.act(cookie, csrf, action='diagnosis', order_id=str(order), revision='1', findings='Disco con sectores dañados', recommendations='Reemplazar por SSD')
        self.assertTrue(twice['body'].get('unchanged'))   # doble clic: sin segundo registro
        # Seguimiento técnico (endpoint real del módulo) y cambio de estado con el estado que se estaba viendo.
        self.assertEqual(self.request('/api/orders/%d/follow-up' % order, {'comment': 'Se solicitó el SSD al proveedor.'}, cookie=cookie, csrf=csrf)['status'], 201)
        stale = self.request('/api/order-status', {'id': str(order), 'status': 'reparacion', 'comment': '', 'notify': '0', 'from_status': 'pendiente'}, cookie=cookie, csrf=csrf)
        self.assertEqual(stale['status'], 409)
        moved = self.request('/api/order-status', {'id': str(order), 'status': 'reparacion', 'comment': '', 'notify': '0', 'from_status': 'diagnostico'}, cookie=cookie, csrf=csrf)
        self.assertEqual(moved['status'], 200, moved['body'])
        with app.connect() as c:
            row = c.execute('SELECT status,findings,recommendations FROM orders WHERE id=?', (order,)).fetchone()
            self.assertEqual(tuple(row), ('reparacion', 'Disco con sectores dañados', 'Reemplazar por SSD'))
            self.assertEqual(c.execute('SELECT status FROM quotes WHERE id=?', (quote,)).fetchone()[0], 'enviado')   # nada aprueba el presupuesto
            history = [r[0] for r in c.execute('SELECT comment FROM order_history WHERE order_id=? ORDER BY id', (order,))]
            self.assertTrue(any(h.startswith('Diagnóstico actualizado desde el Centro de Control') for h in history))
            self.assertIn('Se solicitó el SSD al proveedor.', history)
        # El estado operativo del pendiente es independiente del estado de la orden.
        item = self.item(cookie, entity)
        self.assertEqual((item['ref']['status'], item['state']), ('reparacion', 'en_proceso'))
        timeline = self.request('/api/pending/item?key=' + entity, cookie=cookie)['body']['history']
        self.assertTrue(any('Diagnóstico actualizado' in e['text'] for e in timeline))
