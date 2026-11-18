"""1.5.294 · Prórrogas del plazo de retiro. Datos ficticios en una base temporal; ningún correo real (el envío se simula).
Comprueba el plazo original y vigente en America/Guayaquil, el día límite completo, otorgar y reemplazar sin sobrescribir, duplicados,
concurrencia, permisos, órdenes entregadas, revocación, avisos al cliente con reintento seguro, aviso interno, recordatorios, que los
avisos de permanencia no contradigan la prórroga y su presencia en el Centro de Control."""
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import test_app
import app
import appointments
import order_extensions
import stay
import stay_reminders
import test_pending_center
from reception import ECUADOR_TZ


class OrderExtensionTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login
    _B = test_pending_center.PendingCenterTests
    client, order = _B.client, _B.order
    del _B

    def make(self, days_ago, status='reparacion', email='cliente.prorroga@example.invalid'):
        with app.connect() as c:
            oid = self.order(c, status, 'OP-PR%03d' % (days_ago % 1000))
            received = appointments.now() - timedelta(days=days_ago)
            c.execute('UPDATE orders SET received_at=? WHERE id=?', (received.isoformat(), oid))
            c.execute('UPDATE clients SET email=? WHERE id=(SELECT d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?)', (email, oid))
        return oid

    def ext(self, oid, cookie, csrf, **data):
        return self.request('/api/orders/%d/extension' % oid, data, cookie=cookie, csrf=csrf)

    def info(self, oid, cookie):
        out = self.request('/api/orders/%d/extension' % oid, cookie=cookie)
        self.assertEqual(out['status'], 200, out['body'])
        return out['body']

    def tech(self):
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tec','tec@example.invalid','Técnico ficticio',?,'tecnico',?)", (self.hash, int(time.time())))
        login = self.request('/api/login', {'login': 'tec', 'password': 'contraseña-segura-de-prueba'})
        cookie = login['cookie'].split(';')[0]
        return cookie, self.request('/api/me', cookie=cookie)['body']['user']['csrf']

    def test_due_dates_use_ecuador_dates(self):
        # Ingreso a las 23:30 de Ecuador (04:30 UTC del día siguiente): el plazo cuenta desde la fecha de Ecuador.
        moment = datetime(2026, 10, 1, 23, 30, tzinfo=ECUADOR_TZ)
        order = {'received_at': moment.astimezone(__import__('datetime').timezone.utc).isoformat(), 'status': 'reparacion'}
        self.assertEqual(order_extensions.original_due(order, {'limit': 90}).isoformat(), '2026-12-30')
        # Con prórroga hasta el 05/01: el último segundo del día 5 sigue en plazo; el día 6 a las 00:00 ya venció.
        config = {'limit': 90, 'notice': 60, 'near': 75}
        before = stay.compute(dict(order, status_code='reparacion'), datetime(2027, 1, 5, 23, 59, 59, tzinfo=ECUADOR_TZ), config, '2027-01-05')
        after = stay.compute(dict(order, status_code='reparacion'), datetime(2027, 1, 6, 0, 0, 1, tzinfo=ECUADOR_TZ), config, '2027-01-05')
        self.assertEqual((before['level'] != 'overdue', before['label'], after['level'], after['exceeded']), (True, 'Prórroga vigente hasta 05/01/2027', 'overdue', 1))   # el 06/01 ya venció hace 1 día

    def test_grant_replace_and_never_overwrite(self):
        oid = self.make(100)   # plazo original (90 días) ya vencido
        cookie, csrf = self.login()
        first = self.info(oid, cookie)
        today = first['today']
        self.assertTrue(first['eligible'] and first['overdue'])
        self.assertEqual(first['base'], today)   # vencida: la prórroga cuenta desde hoy, nunca queda en el pasado
        # Validaciones: opción, motivo, responsable, fecha posterior.
        self.assertEqual(self.ext(oid, cookie, csrf, action='grant', expected_due=first['due'], days='5', reason_code='cliente_solicita', authorized_by='Gerencia')['status'], 400)
        self.assertEqual(self.ext(oid, cookie, csrf, action='grant', expected_due=first['due'], days='7', reason_code='otro', authorized_by='Gerencia')['status'], 400)
        self.assertEqual(self.ext(oid, cookie, csrf, action='grant', expected_due=first['due'], date=today, reason_code='cliente_solicita', authorized_by='Gerencia')['status'], 400)
        ok = self.ext(oid, cookie, csrf, action='grant', expected_due=first['due'], days='7', reason_code='viaje_cliente', reason='Vuelve el lunes', authorized_by='Gerencia general')
        self.assertEqual(ok['status'], 200, ok['body'])
        due7 = (datetime.fromisoformat(today) + timedelta(days=7)).date().isoformat()
        self.assertEqual((ok['body']['extension']['new_due'], ok['body']['extension']['days'], ok['body']['extension']['previous_due']), (due7, 7, first['due']))
        again = self.ext(oid, cookie, csrf, action='grant', expected_due=first['due'], days='7', reason_code='viaje_cliente', authorized_by='Gerencia general')
        self.assertEqual(again['status'], 409)   # el plazo ya cambió: la petición repetida con el plazo viejo no se aplica
        same = self.ext(oid, cookie, csrf, action='grant', expected_due=due7, days='0', date=due7, reason_code='viaje_cliente', authorized_by='Gerencia general')
        self.assertEqual(same['status'], 400)   # la nueva fecha debe ser posterior al plazo vigente
        second = self.ext(oid, cookie, csrf, action='grant', expected_due=due7, days='15', reason_code='espera_pago', authorized_by='Gerencia general')
        self.assertEqual(second['status'], 200, second['body'])
        dup = self.ext(oid, cookie, csrf, action='grant', expected_due=second['body']['extension']['new_due'], date=second['body']['extension']['new_due'], reason_code='espera_pago', authorized_by='Gerencia general')
        self.assertIn(dup['status'], (200, 400))
        info = self.info(oid, cookie)
        self.assertEqual([h['status'] for h in info['history']], ['vigente', 'reemplazada'])   # nada se sobrescribe
        self.assertFalse(info['overdue'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()[0], 'reparacion')   # el estado operativo no cambia
            with self.assertRaises(Exception):
                c.execute('UPDATE order_extensions SET new_due=?', ('2030-01-01',))
            with self.assertRaises(Exception):
                c.execute('DELETE FROM order_extensions')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='order_extension_granted'").fetchone()[0], 2)
            history = [r[0] for r in c.execute("SELECT comment FROM order_history WHERE order_id=? ORDER BY id", (oid,))]
        self.assertTrue(any(h.startswith('Prórroga del plazo de retiro otorgada') for h in history))
        # Revocar devuelve el plazo anterior (la prórroga de 7 días) con una fila nueva; la revocada queda en el historial.
        rev = self.ext(oid, cookie, csrf, action='revoke', extension=str(info['extension']['id']), reason='Se otorgó por error')
        self.assertEqual((rev['status'], rev['body'].get('due')), (200, due7), rev['body'])
        statuses = [h['status'] for h in self.info(oid, cookie)['history']]
        self.assertEqual(statuses, ['vigente', 'revocada', 'reemplazada'])

    def test_permissions_and_delivered_orders(self):
        oid = self.make(80)
        done = self.make(95, status='entregado')
        cookie, csrf = self.login()
        tcookie, tcsrf = self.tech()
        due = self.info(oid, cookie)['due']
        self.assertTrue(self.info(oid, tcookie)['can_manage'] is False)   # el técnico consulta, no autoriza
        self.assertEqual(self.ext(oid, tcookie, tcsrf, action='grant', expected_due=due, days='7', reason_code='cliente_solicita', authorized_by='Yo')['status'], 403)
        closed = self.info(done, cookie)
        self.assertFalse(closed['eligible'])
        self.assertEqual(self.ext(done, cookie, csrf, action='grant', expected_due=closed['due'], days='7', reason_code='cliente_solicita', authorized_by='Gerencia')['status'], 409)
        self.assertEqual(self.request('/api/orders/%d/extension' % oid)['status'], 401)

    def test_client_notice_retry_and_internal_notification(self):
        oid = self.make(85)
        cookie, csrf = self.login()
        due = self.info(oid, cookie)['due']
        calls = []

        def failing(to, subject, body, order_id=None):
            calls.append(subject)
            raise RuntimeError('servidor de correo ficticio caído')
        with patch('mail_pro.configured', return_value=True), patch.object(app, 'extension_deliver', side_effect=failing):
            out = self.ext(oid, cookie, csrf, action='grant', expected_due=due, days='15', reason_code='coordinacion_retiro', authorized_by='Gerencia')
        self.assertEqual((out['status'], out['body']['mail']), (200, ['error']), out['body'])
        notices = self.info(oid, cookie)['history'][0]['notices']
        mail = next(n for n in notices if n['channel'] == 'correo')
        wa = next(n for n in notices if n['channel'] == 'whatsapp')
        self.assertEqual((mail['status'], wa['status']), ('error', 'omitido'))   # WhatsApp no configurado: se registra el motivo, no se finge
        self.assertTrue(wa['detail'])
        with patch.object(app, 'extension_deliver', return_value='<id-ficticio@example.invalid>'):
            retried = self.ext(oid, cookie, csrf, action='retry', notice=str(mail['id']))
            self.assertEqual((retried['status'], retried['body'].get('result')), (200, 'enviado'), retried['body'])
            twice = self.ext(oid, cookie, csrf, action='retry', notice=str(mail['id']))
        self.assertEqual(twice['status'], 409)   # ya enviado: no se repite
        self.assertEqual(len(calls), 1)
        self.assertIn('Prórroga del plazo de retiro', calls[0])
        # Aviso interno: otra persona del equipo lo ve en sus notificaciones (no quien lo otorgó).
        tcookie, _ = self.tech()
        items = self.request('/api/notifications', cookie=tcookie)['body']['items']
        self.assertTrue(any('Prórroga del plazo de retiro otorgada' in (i.get('detail') or '') for i in items))
        # Sin avisar al cliente: el aviso queda «omitido» con su motivo y no se envía nada.
        oid2 = self.make(86)
        due2 = self.info(oid2, cookie)['due']
        with patch('mail_pro.configured', return_value=True), patch.object(app, 'extension_deliver', side_effect=failing):
            self.ext(oid2, cookie, csrf, action='grant', expected_due=due2, days='3', reason_code='cliente_solicita', authorized_by='Gerencia', notify_client=False)
        self.assertEqual({n['status'] for n in self.info(oid2, cookie)['history'][0]['notices']}, {'omitido'})
        self.assertEqual(len(calls), 1)

    def test_reminders_stay_notices_and_control_center(self):
        oid = self.make(88)
        cookie, csrf = self.login()
        info = self.info(oid, cookie)
        target = (datetime.fromisoformat(info['today']) + timedelta(days=3)).date().isoformat()
        with patch('mail_pro.configured', return_value=False):
            granted = self.ext(oid, cookie, csrf, action='grant', expected_due=info['due'], date=target, reason_code='cliente_solicita', authorized_by='Gerencia')
        self.assertEqual(granted['status'], 200, granted['body'])
        now = appointments.now()
        with app.connect() as c:
            self.assertEqual(order_extensions.plan_reminders(c, now), [])   # desactivados por defecto
            order_extensions.save_settings(c, {'reminders': True, 'reminder_days': '3,1'})
            with patch('mail_pro.configured', return_value=True):
                first = order_extensions.plan_reminders(c, now)
                second = order_extensions.plan_reminders(c, now)
            self.assertEqual((len(first), second), (1, []))   # una vez por prórroga y anticipación
            # Con prórroga vigente no salen los avisos de permanencia («plazo vencido») de esa orden.
            self.assertFalse([item for item, _info, _stage in stay_reminders.pending(c, now, dict(stay.settings(c), mail=True)) if item['id'] == oid])
            self.assertFalse([o for o in stay.overdue(c, now, stay.settings(c)) if o['id'] == oid])
        items = self.request('/api/pending', cookie=cookie)['body']['items']
        item = next(i for i in items if i['key'].startswith('pending:orders:prorroga:'))
        self.assertEqual((item['href'], item['title'].startswith('Prórroga por vencer')), ('#orders?id=%d' % oid, True))
        bad = self.request('/api/extensions/settings', {'reminders': True, 'reminder_days': '45'}, cookie=cookie, csrf=csrf)
        self.assertEqual(bad['status'], 400)
