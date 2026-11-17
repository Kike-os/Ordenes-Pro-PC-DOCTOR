"""1.5.288 · Centro de Control Operativo: «Gestionar pendiente», acciones reales, gestión registrada y actividad.
Datos ficticios en una base temporal. Comprueba que las acciones pasan por los endpoints reales (con sus permisos y validaciones), que
nada de lo que añade el centro resuelve un pendiente, que un fallo activo no se puede silenciar, que un doble clic no duplica registros,
que los contadores siguen a los cambios y que cada técnico solo ve y gestiona lo suyo."""
import sqlite3
import time
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_app  # primero: ruta de importación y base temporal
import app
import appointments
import pending_center
import test_pending_center


class ControlCenterTests(unittest.TestCase):
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

    def warning_alert(self, c):
        """Solicitud de cuenta por revisar: una advertencia real del sistema (alert:accounts), no un fallo activo."""
        c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at,approval) VALUES ('nuevo','nuevo@example.invalid','Solicitud ficticia','x','tecnico',0,'pending')")

    def test_detail_has_history_context_and_respects_scope(self):
        with app.connect() as c:
            tech = self.technician(c)
            own = self.order(c, 'diagnostico', 'OP-C1', assigned=tech)
            other = self.order(c, 'reparacion', 'OP-C2', assigned=self.uid, name='Cliente ajeno')
            c.execute("INSERT INTO order_history(order_id,actor_id,event,status_label,comment,occurred_at) VALUES (?,?,?,?,?,?)",
                      (own, self.uid, 'follow_up', '', 'Revisión inicial ficticia', appointments.stamp(appointments.now())))
        cookie, csrf = self.login()
        found = self.request('/api/pending/item?key=orders:%d' % own, cookie=cookie)
        self.assertEqual(found['status'], 200, found['body'])
        body = found['body']
        self.assertEqual((body['item']['entity'], body['item']['ref']['order_id']), ('orders:%d' % own, own))
        self.assertIn('Revisión inicial ficticia', [e['text'] for e in body['history']])
        self.assertTrue(body['context']['statuses'] and body['context']['staff'])  # administración puede cambiar estado y responsable
        self.assertEqual(body['context']['revision'], 0)
        # El técnico ve su orden, sin los datos de administración, y no la ajena (mismo error que si no existiera).
        tcookie, tcsrf = self.login_as('tec')
        mine = self.request('/api/pending/item?key=orders:%d' % own, cookie=tcookie)['body']
        self.assertNotIn('statuses', mine['context'])
        foreign = self.request('/api/pending/item?key=orders:%d' % other, cookie=tcookie)
        self.assertEqual(foreign['status'], 404)
        self.assertNotIn('Cliente ajeno', str(foreign['body']))
        self.assertEqual(self.request('/api/pending/item?key=orders:%d' % own)['status'], 401)

    def test_notes_reminders_are_logged_but_never_resolve(self):
        with app.connect() as c:
            order = self.order(c, 'diagnostico', 'OP-C3')
        cookie, csrf = self.login()
        entity = 'orders:%d' % order
        first = self.act(cookie, csrf, action='note', key=entity, body='Cliente pidió llamar después de las 15 h.')
        self.assertEqual(first['status'], 200, first['body'])
        again = self.act(cookie, csrf, action='note', key=entity, body='Cliente pidió llamar después de las 15 h.')
        self.assertTrue(again['body']['duplicate'])  # doble clic: no se registra dos veces
        self.assertEqual(self.act(cookie, csrf, action='note', key=entity, body='')['status'], 400)
        tomorrow = (appointments.now().date() + timedelta(days=1)).isoformat()
        self.assertEqual(self.act(cookie, csrf, action='remind', key=entity, date='2020-01-01')['status'], 400)
        self.assertEqual(self.act(cookie, csrf, action='remind', key=entity, date=tomorrow, body='Confirmar repuesto')['status'], 200)
        item = self.item(cookie, entity)
        self.assertEqual((item['notes'], item['reminder'], item['state']), (1, tomorrow, 'en_proceso'))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM pending_notes WHERE key=?', (entity,)).fetchone()[0], 2)
            # La observación sigue con la orden aunque cambie su estado (otra clave de pendiente, mismo registro de origen).
            c.execute("UPDATE orders SET status='listo' WHERE id=?", (order,))
        item = self.item(cookie, entity)
        self.assertEqual((item['key'], item['notes']), ('pending:orders:%d:listo' % order, 1))
        detail = self.request('/api/pending/item?key=' + item['key'], cookie=cookie)['body']
        self.assertEqual([n['body'] for n in detail['notes']], ['Cliente pidió llamar después de las 15 h.'])
        self.assertTrue(any(e['kind'] == 'gestion' and 'Recordatorio' in e['text'] for e in detail['history']))
        # Una acción del centro sobre un pendiente inexistente o ajeno: error genérico.
        self.assertEqual(self.act(cookie, csrf, action='note', key='orders:999999', body='Texto de prueba')['status'], 404)

    def test_alerts_ack_silence_and_resolution(self):
        with app.connect() as c:
            self.warning_alert(c)
            self.technician(c)
        cookie, csrf = self.login()
        alert = next(i for i in self.pending(cookie)['items'] if i['key'].startswith('alert:accounts:'))
        self.assertEqual((alert['priority'], alert['ref']['can_silence']), ('importante', True))
        # Solo administración; y solo para alertas.
        tcookie, tcsrf = self.login_as('tec')
        self.assertIn(self.act(tcookie, tcsrf, action='ack', key=alert['key'])['status'], (403, 404))
        with app.connect() as c:
            order = self.order(c, 'pendiente', 'OP-C4')
        self.assertEqual(self.act(cookie, csrf, action='ack', key='orders:%d' % order)['status'], 400)
        # Reconocer: pasa a «En proceso», sigue en la lista.
        self.assertEqual(self.act(cookie, csrf, action='ack', key=alert['key'], body='Lo reviso hoy')['status'], 200)
        alert = self.item(cookie, alert['key'])
        self.assertEqual((alert['state'], alert['ack']['by']), ('en_proceso', 'Persona de prueba'))
        # Silenciar: duración válida y motivo; queda visible, fuera de los urgentes y de «requieren decisión».
        self.assertEqual(self.act(cookie, csrf, action='silence', key=alert['key'], hours='5', body='Motivo válido')['status'], 400)
        self.assertEqual(self.act(cookie, csrf, action='silence', key=alert['key'], hours='4', body='')['status'], 400)
        self.assertEqual(self.act(cookie, csrf, action='silence', key=alert['key'], hours='4', body='Esperando al proveedor')['status'], 200)
        data = self.pending(cookie)
        alert = next(i for i in data['items'] if i['key'] == alert['key'])
        self.assertTrue(alert['silenced'])
        self.assertEqual(data['summary']['alerts']['silenced'], 1)
        # Registrar la resolución no la quita: desaparece cuando el sistema deja de detectar la condición.
        self.assertEqual(self.act(cookie, csrf, action='resolve', key=alert['key'], body='Corto')['status'], 400)
        self.assertEqual(self.act(cookie, csrf, action='resolve', key=alert['key'], body='Solicitud revisada con el responsable.')['status'], 200)
        self.assertIn('resolution', self.item(cookie, alert['key']))
        with app.connect() as c:
            c.execute("UPDATE users SET approval='approved' WHERE username='nuevo'")
        self.assertIsNone(self.item(cookie, alert['key']))

    def test_active_failure_cannot_be_silenced(self):
        cookie, csrf = self.login()
        critical = {'key': 'storage:prueba', 'kind': 'error', 'title': 'Almacenamiento ficticio no disponible', 'detail': 'Prueba', 'at': appointments.stamp(appointments.now()), 'href': '#system'}
        with patch.object(app.notifications, 'build', side_effect=lambda *a, **k: {'items': [critical], 'unread': 1}):
            data = self.pending(cookie)
            alert = next(i for i in data['items'] if i['key'] == 'storage:prueba')
            self.assertEqual((alert['priority'], alert['ref']['can_silence']), ('critico', False))
            self.assertEqual(data['totals']['critical'], 1)
            refused = self.act(cookie, csrf, action='silence', key='storage:prueba', hours='4', body='Intento de silencio')
            self.assertEqual(refused['status'], 409)
            self.assertEqual(self.act(cookie, csrf, action='ack', key='storage:prueba', body='Revisando el disco')['status'], 200)
            self.assertEqual(self.item(cookie, 'storage:prueba')['priority'], 'critico')  # reconocida, pero sigue siendo crítica

    def test_assign_order_checks_revision_and_role(self):
        with app.connect() as c:
            tech = self.technician(c)
            order = self.order(c, 'diagnostico', 'OP-C5')
        cookie, csrf = self.login()
        stale = self.act(cookie, csrf, action='assign', order_id=str(order), technician=str(tech), revision='7')
        self.assertEqual(stale['status'], 409)
        done = self.act(cookie, csrf, action='assign', order_id=str(order), technician=str(tech), revision='0')
        self.assertEqual(done['status'], 200, done['body'])
        with app.connect() as c:
            row = c.execute('SELECT assigned_to,revision FROM orders WHERE id=?', (order,)).fetchone()
            self.assertEqual((row[0], row[1]), (tech, 1))
            self.assertIn('Responsable: Sin asignar → Técnico ficticio tec', c.execute('SELECT comment FROM order_history WHERE order_id=? ORDER BY id DESC', (order,)).fetchone()[0])
        self.assertEqual(self.item(cookie, 'orders:%d' % order)['responsible'], 'Técnico ficticio tec')
        tcookie, tcsrf = self.login_as('tec')
        self.assertEqual(self.act(tcookie, tcsrf, action='assign', order_id=str(order), technician='', revision='1')['status'], 403)

    def test_real_module_actions_resolve_and_update_counters(self):
        today = appointments.now().date()
        with app.connect() as c:
            aid = self.appointment(c, 'solicitada', 72)
            # Un horario de atención real (mismas reglas que la Agenda), a partir de dentro de 3 días.
            day = today + timedelta(days=3)
            while not appointments.day_hours(c, day):
                day += timedelta(days=1)
            start = appointments.datetime.combine(day, appointments.day_hours(c, day)[0], appointments.TZ)
            c.execute("UPDATE appointments SET identification='1712345678',document_type='cedula',starts_at=? WHERE id=?", (appointments.stamp(start), aid))
            gone = self.appointment(c, 'solicitada', 96)
            order = self.order(c, 'presupuesto', 'OP-C6')
            qid = self.quote(c, order, 'enviado', 'PCD-C-P1', valid=(today + timedelta(days=5)).isoformat())
            item_id = c.execute("INSERT INTO quote_items(quote_id,position,description,category,quantity,unit_cents,taxed) VALUES (?,1,'Servicio ficticio','servicio',1,1000,1)", (qid,)).lastrowid
            rid = self.part(c, order, 'transito', eta=(today + timedelta(days=3)).isoformat())
        cookie, csrf = self.login()
        before = self.pending(cookie)['summary']
        # Cita: confirmar exige la autorización real del cliente (sin ella, el servidor la pide y nada cambia).
        need = self.request('/api/appointments/%d' % aid, {'action': 'confirmada'}, cookie=cookie, csrf=csrf)
        self.assertEqual((need['status'], need['body'].get('needs_authorization')), (409, True))
        terms = self.request('/api/public/appointments/services')['body']['terms']
        ok = self.request('/api/appointments/%d' % aid, {'action': 'confirmada', 'terms_accept': True, 'terms_id': terms['id'], 'id_last4': '5678'}, cookie=cookie, csrf=csrf)
        self.assertEqual(ok['status'], 200, ok['body'])
        # Cancelar con motivo: queda en el historial de la cita.
        self.assertEqual(self.request('/api/appointments/%d' % gone, {'action': 'cancelada', 'reason': 'El cliente viaja esa semana'}, cookie=cookie, csrf=csrf)['status'], 200)
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT detail FROM appointment_events WHERE appointment_id=? AND new_status='cancelada'", (gone,)).fetchone()[0], 'Motivo: El cliente viaja esa semana')
        # Presupuesto: la decisión registrada por el personal exige su nota y quita el pendiente.
        self.assertEqual(self.request('/api/quotes/%d' % qid, {'action': 'decide', 'approved': str(item_id), 'note': ''}, cookie=cookie, csrf=csrf)['status'], 400)
        decided = self.request('/api/quotes/%d' % qid, {'action': 'decide', 'approved': str(item_id), 'rejected': '', 'note': 'Aprobó por teléfono'}, cookie=cookie, csrf=csrf)
        self.assertEqual(decided['status'], 200, decided['body'])
        # Repuesto: avanzar a la etapa siguiente cambia el pendiente (recibido: instalar).
        moved = self.request('/api/orders/%d/part-requests/%d' % (order, rid), {'action': 'advance', 'stage': 'recibido'}, cookie=cookie, csrf=csrf)
        self.assertEqual(moved['status'], 200, moved['body'])
        after = self.pending(cookie)
        self.assertEqual((before['appointments']['count'], after['summary']['appointments']['count']), (2, 0))
        self.assertEqual((before['quotes']['count'], after['summary']['quotes']['count']), (1, 0))
        part = next(i for i in after['items'] if i['module'] == 'parts')
        self.assertEqual((part['ref']['stage'], part['state'], part['decision']), ('recibido', 'pendiente', True))
        detail = self.request('/api/pending/item?key=parts:%d' % rid, cookie=cookie)['body']
        self.assertEqual(detail['context']['next'], 'instalacion')
        # Orden: el cambio de estado real (Órdenes) la mueve; el contador sigue a la lista.
        self.assertEqual(self.request('/api/order-status', {'id': str(order), 'status': 'reparacion', 'comment': ''}, cookie=cookie, csrf=csrf)['status'], 200)
        data = self.pending(cookie)
        self.assertEqual(next(i for i in data['items'] if i['module'] == 'orders')['key'], 'pending:orders:%d:reparacion' % order)
        for module, box in data['summary'].items():
            self.assertEqual(box['count'], sum(1 for i in data['items'] if i['module'] == module), module)

    def test_activity_history_and_csv(self):
        with app.connect() as c:
            order = self.order(c, 'diagnostico', 'OP-C7')
            self.technician(c)
        cookie, csrf = self.login()
        self.act(cookie, csrf, action='note', key='orders:%d' % order, body='=HYPERLINK("http://ejemplo.invalid")')
        self.request('/api/order-status', {'id': str(order), 'status': 'reparacion', 'comment': ''}, cookie=cookie, csrf=csrf)
        self.request('/api/notifications/read', {'keys': 'pending:orders:%d:reparacion' % order}, cookie=cookie, csrf=csrf)
        data = self.request('/api/pending/activity', cookie=cookie)['body']
        kinds = {r['kind'] for r in data['rows']}
        self.assertTrue({'gestion', 'estado', 'lectura', 'accion'} <= kinds, kinds)
        self.assertTrue(any(r['text'].startswith('Orden OP-C7') for r in data['rows']))
        only = self.request('/api/pending/activity?kind=estado', cookie=cookie)['body']['rows']
        self.assertTrue(only and all(r['kind'] == 'estado' for r in only))
        self.assertEqual(self.request('/api/pending/activity?from=2026-13-01', cookie=cookie)['status'], 400)
        csv = self.request('/api/pending/activity.csv', cookie=cookie)
        self.assertEqual(csv['status'], 200)
        text = csv['body'] if isinstance(csv['body'], str) else csv['body'].decode('utf-8') if isinstance(csv['body'], bytes) else str(csv['body'])
        self.assertIn('Fecha y hora,Persona', text)
        self.assertIn("'=HYPERLINK", text)  # una fórmula escrita por alguien no se ejecuta al abrir el archivo
        # Un técnico solo ve lo que hizo él.
        tcookie, tcsrf = self.login_as('tec')
        self.assertEqual(self.request('/api/pending/activity', cookie=tcookie)['body']['rows'], [])

    def test_missing_table_is_reported_not_broken(self):
        c = sqlite3.connect(':memory:')
        c.row_factory = sqlite3.Row
        c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT)')
        self.assertIsNone(pending_center.notes(c, ['orders:1']))
        items = [{'entity': 'orders:1', 'module': 'orders', 'key': 'pending:orders:1:x'}]
        self.assertFalse(pending_center._overlay(c, items, app.reception_now()))


if __name__ == '__main__':
    unittest.main()
