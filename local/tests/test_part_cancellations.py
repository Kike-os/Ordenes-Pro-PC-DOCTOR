"""Seguimiento de repuestos 1.5.246 (datos ficticios, base temporal; correo y WhatsApp simulados, nada real): mapa de ruta nacional e
internacional según el paso real, cancelaciones con revisión de administración (también solicitadas por el cliente desde su enlace), reglas
según el punto del pedido, reembolsos conciliados con devoluciones reales de la orden y avisos automáticos únicos por evento."""
import json
import re
import unittest
from unittest.mock import patch

import test_part_requests as base
import test_cash
import app
import mail_pro
import order_part_requests as parts
import part_notices

MAIL = {'imap_host': 'imap.example.invalid', 'imap_port': 993, 'smtp_host': 'smtp.example.invalid', 'smtp_port': 465, 'username': 'taller@example.invalid', 'password': 'x'}


class PartCancellationTests(unittest.TestCase):
    Base = base.PartRequestTests
    setUpClass = classmethod(Base.Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure
    part, rows, link = Base.part, Base.rows, Base.link
    technician = test_cash.CashTests.technician

    def row(self, cookie, oid, rid):
        return next(r for r in self.rows(cookie, oid) if r['id'] == rid)

    def go(self, post, oid, rid, *steps):
        for step in steps:
            res = post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage=step)
            self.assertEqual(res['status'], 200, (step, res['body']))

    def test_route_map_follows_the_real_step(self):
        # Internacional: avión en el aire (sin país en el público), aduana sin vehículo, camión tras la liberación y llegada con ✓.
        m = parts.route_map('internacional', 'transito_internacional', {'despachado'}, {}, False, 'normal', origin_country='China')
        self.assertEqual((m['vehicle']['kind'], m['vehicle']['segment'], m['vehicle']['motion'], m['vehicle']['animate']), ('plane', 'air', 'moving', True))
        self.assertEqual([n['state'] for n in m['nodes']], ['done', 'pending', 'pending', 'pending'])
        self.assertEqual(m['nodes'][0]['sub'], 'China')
        self.assertEqual(parts.route_map('internacional', 'transito_internacional', set(), {}, False, 'normal', public=True)['nodes'][0]['sub'], 'Envío internacional')
        customs = parts.route_map('internacional', 'aduana_revision', set(), {}, False, 'normal')
        self.assertEqual((customs['vehicle'], customs['customs_active'], customs['nodes'][1]['customs'], customs['nodes'][1]['state']), (None, True, True, 'current'))
        truck = parts.route_map('internacional', 'distribucion_nacional', set(), {}, False, 'normal')['vehicle']
        self.assertEqual((truck['kind'], truck['segment']), ('truck', 'road1'))
        self.assertEqual(parts.route_map('internacional', 'recibido', set(), {}, False, 'normal')['vehicle']['motion'], 'arrived')
        # Una novedad detiene el vehículo (sin animación); cancelado o terminado, no hay vehículo.
        stopped = parts.route_map('nacional', 'transito_nacional', set(), {}, False, 'retrasado')['vehicle']
        self.assertEqual((stopped['motion'], stopped['animate']), ('stopped', False))
        self.assertIsNone(parts.route_map('nacional', 'transito_nacional', set(), {}, False, 'cancelado')['vehicle'])
        self.assertIsNone(parts.route_map('nacional', 'instalado', set(), {}, False, 'normal')['vehicle'])
        # Antes de despachar no hay vehículo: nunca se simula movimiento.
        self.assertIsNone(parts.route_map('nacional', 'confirmado', set(), {}, False, 'normal')['vehicle'])
        self.assertIsNone(parts.route_map('', 'confirmado', set(), {}, False, 'normal'))

    def test_staff_request_admin_decides_with_rules_by_stage(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        url = lambda rid: '/api/orders/%d/part-requests/%d' % (oid, rid)
        rid = self.part(post, oid, shipping='nacional')['body']['id']
        tech_cookie, tech_csrf = self.technician()
        tpost = lambda path, **body: self.request(path, body, cookie=tech_cookie, csrf=tech_csrf)
        # El técnico registra la solicitud del cliente; el pedido no cambia y no puede decidirla.
        self.assertEqual(tpost(url(rid), action='cancel_request', reason='corto')['status'], 400)
        made = tpost(url(rid), action='cancel_request', reason='El cliente ya no desea reparar el equipo (llamada ficticia).', channel='telefono', request_key='cancel-prueba-000001')
        self.assertEqual(made['status'], 200, made['body'])
        cid = made['body']['cancellation_id']
        self.assertEqual(tpost(url(rid), action='cancel_request', reason='El cliente ya no desea reparar el equipo (llamada ficticia).', request_key='cancel-prueba-000001')['body']['cancellation_id'], cid)
        self.assertEqual(tpost(url(rid), action='cancel_request', reason='Otra solicitud mientras hay una abierta.')['status'], 409)
        r = self.row(cookie, oid, rid)
        self.assertEqual((r['situation'], r['cancellations'][0]['status'], r['cancel_context']['phase']), ('normal', 'solicitada', 'sin_compra'))
        self.assertEqual(tpost(url(rid), action='cancel_decide', cancellation_id=str(cid), decision='aprobar', note='Aprobación de prueba ficticia')['status'], 403)
        self.assertEqual(tpost(url(rid), action='cancel_review', cancellation_id=str(cid), note='Consultando al proveedor')['status'], 200)
        # Rechazo: exige justificación; el pedido sigue avanzando.
        self.assertEqual(post(url(rid), action='cancel_decide', cancellation_id=str(cid), decision='rechazar', note='no')['status'], 400)
        self.assertEqual(post(url(rid), action='cancel_decide', cancellation_id=str(cid), decision='rechazar', note='El repuesto es indispensable para la garantía (ficticio).')['status'], 200)
        self.go(post, oid, rid, 'confirmado', 'preparacion')
        # Comprado: aprobar exige confirmar los compromisos con el proveedor.
        cid = post(url(rid), action='cancel_request', reason='El cliente insiste en cancelar el repuesto (ficticio).')['body']['cancellation_id']
        self.assertEqual(self.row(cookie, oid, rid)['cancel_context']['phase'], 'comprado')
        refused = post(url(rid), action='cancel_decide', cancellation_id=str(cid), decision='aprobar', note='Proveedor acepta la devolución (ficticio).')
        self.assertEqual((refused['status'], list(refused['body']['fields'])), (400, ['confirm_supplier']))
        self.assertEqual(post(url(rid), action='cancel_decide', cancellation_id=str(cid), decision='aprobar', note='Proveedor acepta la devolución (ficticio).', confirm_supplier='1')['status'], 200)
        r = self.row(cookie, oid, rid)
        self.assertEqual((r['situation'], r['cancellations'][0]['status'], r['cancellations'][0]['refund_state']), ('cancelado', 'aprobada', 'no_aplica'))
        self.assertTrue(any(e['kind'] == 'situacion' and e['situation'] == 'cancelado' for e in r['events']))
        # Cancelado: ya no avanza ni admite otra cancelación; el historial no se borra ni se modifica.
        self.assertEqual(post(url(rid), action='advance', stage='despachado')['status'], 409)
        self.assertEqual(post(url(rid), action='cancel_request', reason='Una solicitud más sobre un cancelado.')['status'], 409)
        with app.connect() as c:
            for sql in ('DELETE FROM order_part_log', 'UPDATE order_part_log SET note=1', 'DELETE FROM order_part_cancellations'):
                with self.assertRaises(Exception):
                    c.execute(sql)
        # En tránsito: aprobar exige la revisión administrativa del envío; recibido no se cancela por aquí.
        moving = self.part(post, oid, shipping='nacional', name='Batería ficticia')['body']['id']
        self.go(post, oid, moving, 'confirmado', 'preparacion', 'despachado', 'transito_nacional')
        refused = post(url(moving), action='cancel_direct', reason_code='proveedor', note='El proveedor anuló el envío (ficticio).', confirm_supplier='1')
        self.assertEqual((refused['status'], list(refused['body']['fields'])), (400, ['confirm_transit']))
        self.assertEqual(post(url(moving), action='cancel_direct', reason_code='proveedor', note='El proveedor anuló el envío (ficticio).', confirm_supplier='1', confirm_transit='1')['status'], 200)
        done = self.part(post, oid, shipping='nacional', name='Teclado ficticio')['body']['id']
        self.go(post, oid, done, 'confirmado', 'preparacion', 'despachado', 'transito_nacional', 'ruta_otavalo', 'recibido')
        blocked = post(url(done), action='cancel_request', reason='El cliente ya no lo quiere (ficticio).')
        self.assertEqual(blocked['status'], 409)
        self.assertIn('devolución, garantía o reclamo', blocked['body']['error'])
        # Cancelar desde «Novedad» queda reservado a administración y deja su registro de cancelación.
        other = self.part(post, oid, name='Ventilador ficticio')['body']['id']
        self.assertEqual(tpost(url(other), action='situation', situation='cancelado', note='Sin stock en el mercado (ficticio)')['status'], 403)
        self.assertEqual(post(url(other), action='situation', situation='cancelado', note='Sin stock en el mercado (ficticio)')['status'], 200)
        self.assertEqual(self.row(cookie, oid, other)['cancellations'][0]['reason_code'], 'administrativa')

    def test_client_requests_from_tracking_link_and_admin_is_notified(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        rid = self.part(post, oid, shipping='internacional', origin_country='Japón', carrier='Envíos Ficticios')['body']['id']
        token = self.link(oid)
        page = self.request('/s/' + token)['body']
        page = page.decode() if isinstance(page, bytes) else page
        self.assertIn('class="tp-cancel" data-deadline=', page)
        self.assertIn('class="lgx"', page)
        self.assertNotIn('Japón', page)
        action = '/s/%s/repuestos/%d/cancelar' % (token, rid)
        wrong = self.form(action, {'last4': '9999', 'reason': 'Ya no necesito la reparación del equipo.', 'confirm': '1', 'request_key': 'cancel-publico-0001'})
        self.assertEqual(wrong['status'], 400)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_part_cancellations').fetchone()[0], 0)
        ok = self.form(action, {'last4': '0017', 'reason': 'Ya no necesito la reparación del equipo.', 'confirm': '1', 'request_key': 'cancel-publico-0002'})
        self.assertEqual(ok['status'], 200, ok['body'][:300])
        body = ok['body'].decode() if isinstance(ok['body'], bytes) else ok['body']
        self.assertIn('Recibimos su solicitud de cancelación', body)
        self.assertIn('Cancelación solicitada', body)
        self.assertNotIn('class="tp-cancel" data-deadline=', body)  # una sola abierta
        with app.connect() as c:
            x = c.execute('SELECT origin,channel,status,created_by FROM order_part_cancellations').fetchone()
            self.assertEqual(tuple(x), ('cliente', 'enlace', 'solicitada', None))
            self.assertEqual(c.execute('SELECT situation FROM order_part_requests WHERE id=?', (rid,)).fetchone()[0], 'normal')  # no se anula sola
        self.assertEqual(self.form(action, {'last4': '0017', 'reason': 'Otra solicitud con una abierta.', 'confirm': '1'})['status'], 409)
        notices = self.request('/api/notifications', cookie=cookie)['body']['items']
        self.assertTrue(any(n['title'].startswith('Solicitud de cancelación de repuesto del cliente') and n['href'] == '#orders?id=%d' % oid for n in notices))
        # Un repuesto oculto para el cliente no se puede cancelar desde el enlace.
        hidden = self.part(post, oid, name='Disco ficticio', public_visible='0')['body']['id']
        self.assertEqual(self.form('/s/%s/repuestos/%d/cancelar' % (token, hidden), {'last4': '0017', 'reason': 'Cancelar este repuesto oculto.', 'confirm': '1'})['status'], 404)

    def test_refund_is_reconciled_with_real_order_refunds(self):
        cookie, csrf, post, order = self.paid_order(10500)  # $105,00 pagados
        oid = order['id']
        url = lambda rid: '/api/orders/%d/part-requests/%d' % (oid, rid)
        rid = self.part(post, oid)['body']['id']
        cid = post(url(rid), action='cancel_request', reason='El cliente desiste y pide la devolución (ficticio).')['body']['cancellation_id']
        over = post(url(rid), action='cancel_decide', cancellation_id=str(cid), decision='aprobar', note='Sin compra al proveedor (ficticio).', refund_due='200,00')
        self.assertEqual((over['status'], list(over['body']['fields'])), (400, ['refund_due']))
        self.assertEqual(post(url(rid), action='cancel_decide', cancellation_id=str(cid), decision='aprobar', note='Sin compra al proveedor (ficticio).', refund_due='50,00')['status'], 200)
        self.assertEqual(self.row(cookie, oid, rid)['cancellations'][0]['refund_state'], 'pendiente')
        with app.connect() as c:
            before = c.execute("SELECT COUNT(*) FROM order_payments WHERE kind='devolucion'").fetchone()[0]
        first = post(url(rid), action='refund', cancellation_id=str(cid), amount='20,00', method='efectivo', note='Devolución parcial ficticia', request_key='reembolso-prueba-01')
        self.assertEqual((first['status'], first['body']['refund_state']), (200, 'parcial'), first['body'])
        again = post(url(rid), action='refund', cancellation_id=str(cid), amount='20,00', method='efectivo', note='Devolución parcial ficticia', request_key='reembolso-prueba-01')
        self.assertEqual(again['body'].get('duplicate'), True)  # doble clic: una sola devolución
        self.assertEqual(post(url(rid), action='refund', cancellation_id=str(cid), amount='40,00', method='efectivo', note='Supera lo pendiente')['status'], 400)
        # Una devolución ya registrada en la orden se vincula una sola vez.
        made = post('/api/orders/%d/payments' % oid, kind='devolucion', amount='30,00', method='efectivo', note='Devolución ficticia por caja')
        self.assertEqual(made['status'], 201, made['body'])
        second = post(url(rid), action='refund', cancellation_id=str(cid), payment_id=str(made['body']['id']))
        self.assertEqual(second['body']['refund_state'], 'completado', second['body'])
        self.assertEqual(post(url(rid), action='refund', cancellation_id=str(cid), payment_id=str(made['body']['id']))['status'], 409)
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM order_payments WHERE kind='devolucion'").fetchone()[0], before + 2)
            self.assertEqual(c.execute('SELECT SUM(amount_cents) FROM order_part_refunds').fetchone()[0], 5000)
        tech_cookie, tech_csrf = self.technician()
        self.assertEqual(self.request(url(rid), {'action': 'refund', 'cancellation_id': str(cid), 'amount': '1,00'}, cookie=tech_cookie, csrf=tech_csrf)['status'], 403)

    def test_notices_once_per_event_with_real_status(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        self.link(oid)
        rid = self.part(post, oid, shipping='nacional', carrier='Transportes Ficticios', supplier_order='PED-555')['body']['id']
        url = '/api/orders/%d/part-requests/%d' % (oid, rid)
        sent = []
        with patch.object(mail_pro, 'configured', return_value=True), patch.object(mail_pro, 'settings', return_value=MAIL), \
                patch.object(mail_pro, 'deliver', side_effect=lambda config, message, recipients: sent.append(message) or {}):
            self.go(post, oid, rid, 'confirmado', 'preparacion', 'despachado')
            # Corrección hacia atrás y vuelta a avanzar: el mismo evento no se avisa dos veces.
            self.assertEqual(post(url, action='advance', stage='preparacion', note='Corrección de prueba ficticia')['status'], 200)
            self.go(post, oid, rid, 'despachado')
            with app.connect() as c:
                rows = [tuple(r) for r in c.execute('SELECT event,channel,status FROM order_part_notices ORDER BY id')]
            self.assertEqual(rows, [('confirmado', 'correo', 'enviado'), ('confirmado', 'whatsapp', 'omitido'), ('despachado', 'correo', 'enviado'), ('despachado', 'whatsapp', 'omitido')])
            self.assertEqual(len(sent), 2)
            text = sent[-1].get_body(preferencelist=('plain',)).get_content()
            self.assertIn('fue despachado', text)
            for secret in ('Transportes Ficticios', 'PED-555', 'Costo 85'):
                self.assertNotIn(secret, text)
            # Un correo rechazado queda «fallido» y se reintenta de forma controlada (el mismo registro, no otro).
            with patch.object(mail_pro, 'deliver', side_effect=mail_pro.MailError('conexion', 'Sin conexión (ficticio).')):
                self.go(post, oid, rid, 'transito_nacional', 'ruta_otavalo', 'recibido')
            with app.connect() as c:
                failed = c.execute("SELECT id,status,attempts FROM order_part_notices WHERE event='recibido' AND channel='correo'").fetchone()
                self.assertEqual((failed['status'], failed['attempts']), ('fallido', 1))
                self.assertEqual(c.execute("SELECT COUNT(*) FROM order_part_notices WHERE event IN ('transito_nacional','ruta_otavalo')").fetchone()[0], 0)  # pasos menores
            retry = post(url, action='notices_retry')
            self.assertEqual((retry['status'], retry['body']['sent']), (200, 1))
            with app.connect() as c:
                self.assertEqual(c.execute("SELECT status,attempts FROM order_part_notices WHERE id=?", (failed['id'],)).fetchone()[:], ('enviado', 2))
                self.assertEqual(c.execute("SELECT COUNT(*) FROM order_messages WHERE request_key=?", ('part-notice-%d' % failed['id'],)).fetchone()[0], 1)
            # Apagados por administración: no se genera ningún aviso.
            self.assertEqual(post('/api/part-notices/settings', auto=False)['status'], 200)
            self.go(post, oid, rid, 'instalacion', 'instalado', 'listo')
            with app.connect() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM order_part_notices WHERE event='listo'").fetchone()[0], 0)
            # El cliente que pidió no recibir correos no los recibe (queda «omitido» con el motivo).
            self.assertEqual(post('/api/part-notices/settings', auto=True)['status'], 200)
            with app.connect() as c:
                c.execute("INSERT INTO mail_optouts(email,source,created_at) VALUES ('cliente@example.invalid','enlace','2026-11-06T10:00:00-05:00')");c.commit()
            other = self.part(post, oid, shipping='nacional', name='Cargador ficticio')['body']['id']
            self.go(post, oid, other, 'confirmado')
            with app.connect() as c:
                found = c.execute("SELECT status,detail FROM order_part_notices WHERE request_id=? AND channel='correo'", (other,)).fetchone()
            self.assertEqual(tuple(found), ('omitido', 'El cliente pidió no recibir correos.'))
        tech_cookie, tech_csrf = self.technician()
        self.assertEqual(self.request('/api/part-notices/settings', {'auto': False}, cookie=tech_cookie, csrf=tech_csrf)['status'], 403)

    def test_evidence_is_tied_to_the_stage_and_new_fields_are_kept(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        rid = self.part(post, oid, shipping='internacional', origin_country='China', carrier='Aerolínea Ficticia', national_carrier='Camiones Ficticios', national_tracking='GN-1')['body']['id']
        self.go(post, oid, rid, 'confirmado', 'preparacion', 'despachado', 'transito_internacional', 'llegada_pais', 'aduana_revision')
        made = post('/api/orders/%d/followups' % oid, kind='repuesto', internal_note='Foto del paquete en aduana (interno).', client_message='', part_request_id=str(rid))
        self.assertEqual(made['status'], 201, made['body'])
        self.go(post, oid, rid, 'aduana_liberado')
        r = self.row(cookie, oid, rid)
        self.assertEqual(next(d['evidence'] for d in r['detail'] if d['code'] == 'aduana_revision'), 1)
        today = app.reception_now().date().isoformat()
        self.assertEqual((r['customs_in_date'], r['customs_out_date'], r['national_carrier'], r['national_tracking']), (today, today, 'Camiones Ficticios', 'GN-1'))
        self.assertEqual(r['map']['vehicle']['kind'], 'truck')  # liberado: el avión se sustituye por el camión
        self.assertIn('lgx-truck', r['map_html'])
        bad = post('/api/orders/%d/part-requests/%d' % (oid, rid), action='update', customs_in_date='2026-11-05', customs_out_date='2026-11-01')
        self.assertEqual(bad['status'], 400)

    def test_vehicle_never_sits_on_a_checkpoint(self):
        # En cualquier paso, el centro del vehículo queda a una distancia segura de todos los puntos de control (1.5.247).
        for shipping, steps in parts.FLOWS.items():
            for step in steps:
                for situation in ('normal', 'retrasado'):
                    m = parts.route_map(shipping, step, set(steps), {}, False, situation)
                    v = m['vehicle']
                    if not v:
                        continue
                    for x, y in ((v['x'], v['y']), (v['fx'], v['fy'])):
                        for n in m['nodes']:
                            gap = ((x - n['x']) ** 2 + (y - v['lane'] - parts.MAP_Y) ** 2) ** .5  # distancia real sobre el trazo (el arco sube)
                            self.assertGreaterEqual(gap, parts.CLEARANCE[v['kind']] - 1, (shipping, step, n['code'], x))
                            # radio del punto + medio vehículo (1.5.250: furgoneta de 67 y avión de 83 unidades de largo)
                            self.assertGreaterEqual(abs(x - n['x']), 20 + {'truck': 34, 'plane': 40}[v['kind']], (shipping, step, n['code'], x))
                        self.assertTrue(30 <= x <= 970 and 0 <= y <= 158, (shipping, step, x, y))
                    if v['kind'] == 'truck':
                        self.assertEqual(v['y'], parts.MAP_Y + parts.LANE)  # carril propio, sobre la línea

    def test_progress_is_shared_and_counts_only_registered_steps(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        rid = self.part(post, oid, shipping='internacional')['body']['id']
        self.go(post, oid, rid, 'confirmado', 'preparacion', 'despachado', 'transito_internacional')
        r = self.row(cookie, oid, rid)
        with app.connect() as c:
            pub = next(x for x in parts.public(c, oid) if x['id'] == rid)
        # 1.5.249: el avance se cuenta sobre las MISMAS etapas que ve el cliente (8 en internacional); el paso detallado queda aparte.
        self.assertEqual((r['progress']['done'], r['progress']['total'], r['progress']['percent']), (2, 8, 25))
        self.assertEqual((r['progress']['step_number'], r['progress']['step_total'], r['progress']['next_label']), (5, 14, 'Proceso de aduana'))
        self.assertEqual(r['progress'], pub['progress'])  # el mismo avance en las dos vistas
        self.assertEqual(r['stages'], pub['steps'])  # las mismas etapas, estados y fechas
        self.assertEqual(r['progress']['done'], sum(1 for d in r['stages'] if d['state'] == 'done'))
        self.assertEqual(pub['done_count'], r['progress']['done'])
        self.assertEqual((pub['step_label'], pub['updated']), ('En tránsito internacional', r['progress']['updated']))
        # Una corrección de administración que salta pasos no los cuenta como completados.
        self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage='aduana_liberado', note='Corrección de prueba ficticia')['status'], 200)
        r = self.row(cookie, oid, rid)
        self.assertEqual((r['progress']['done'], r['progress']['percent']), (3, 38))  # el envío aéreo tiene su evento; la aduana queda en curso
        self.assertEqual(r['progress']['done'], sum(1 for d in r['stages'] if d['state'] == 'done'))

    def test_part_milestones_are_reflected_in_the_order_history(self):
        """1.5.249: recepción, instalación, fin del proceso y cancelación quedan en el historial de la orden (con usuario y fecha), sin cambiar
        el estado de la orden; un avance rechazado no deja huella."""
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        rid = self.part(post, oid, name='Teclado ficticio', shipping='nacional')['body']['id']
        with app.connect() as c:
            status = c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()[0]
            base_count = c.execute("SELECT COUNT(*) FROM order_history WHERE order_id=?", (oid,)).fetchone()[0]
        self.go(post, oid, rid, 'confirmado', 'preparacion', 'despachado', 'transito_nacional', 'ruta_otavalo', 'recibido', 'instalacion', 'instalado', 'listo')
        self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage='listo')['status'], 409)
        with app.connect() as c:
            rows = c.execute("SELECT event,comment,actor_id FROM order_history WHERE order_id=? ORDER BY id", (oid,)).fetchall()[base_count:]
            self.assertEqual(c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()[0], status)
        texts = [r['comment'] for r in rows]
        self.assertEqual(len(texts), 4, texts)
        self.assertTrue(texts[0].startswith('Repuesto «Teclado ficticio» recibido en el taller.') and 'Fecha de recepción:' in texts[0])
        self.assertIn('instalación y las pruebas', texts[1]);self.assertIn('finalizadas', texts[2]);self.assertIn('proceso finalizado', texts[3])
        self.assertTrue(all(r['event'] == 'follow_up' and r['actor_id'] == self.uid for r in rows))
        other = self.part(post, oid, name='Cámara ficticia', shipping='nacional')['body']['id']
        self.go(post, oid, other, 'confirmado')
        self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, other), action='cancel_direct', reason_code='sin_disponibilidad',
                              note='El proveedor no tiene existencias (ficticio).', confirm_supplier='1')['status'], 200)
        with app.connect() as c:
            last = c.execute("SELECT comment FROM order_history WHERE order_id=? ORDER BY id DESC LIMIT 1", (oid,)).fetchone()[0]
        self.assertIn('Pedido del repuesto «Cámara ficticia» cancelado por administración', last)
        self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, other), action='advance', stage='preparacion')['status'], 409)  # cancelado: ya no cambia

    def test_ordinary_requests_only_within_24_hours(self):
        from datetime import timedelta
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        url = lambda rid: '/api/orders/%d/part-requests/%d' % (oid, rid)
        now = app.reception_now().replace(microsecond=0)
        def made(name, age):
            rid = self.part(post, oid, name=name)['body']['id']
            with app.connect() as c:
                c.execute('UPDATE order_part_requests SET created_at=? WHERE id=?', ((now - age).isoformat(timespec='seconds'), rid));c.commit()
            return rid
        early, late, pending = made('Fuente ficticia', timedelta(hours=23, minutes=59)), made('Ventilador ficticio', timedelta(hours=24)), made('Pantalla ficticia', timedelta(hours=20))
        with patch.object(app, 'reception_now', return_value=now):
            # A las 23 h 59 min todavía se puede; al cumplirse exactamente 24 h, no (y no se registra nada).
            self.assertEqual(post(url(early), action='cancel_request', reason='El cliente desiste dentro del plazo (ficticio).')['status'], 200)
            refused = post(url(late), action='cancel_request', reason='El cliente desiste fuera del plazo (ficticio).')
            self.assertEqual(refused['status'], 409)
            self.assertIn('Plazo de cancelación vencido', refused['body']['error'])
            # Una solicitud hecha a tiempo sigue pudiéndose resolver después de las 24 h.
            cid = post(url(pending), action='cancel_request', reason='Solicitud dentro del plazo (ficticio).')['body']['cancellation_id']
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_part_cancellations WHERE request_id=?', (late,)).fetchone()[0], 0)
        with patch.object(app, 'reception_now', return_value=now + timedelta(hours=5)):
            self.assertEqual(post(url(pending), action='cancel_decide', cancellation_id=str(cid), decision='rechazar', note='Revisada después del plazo (ficticio).')['status'], 200)
            # Excepción de administración, aparte del botón del cliente: sin plazo, con justificación obligatoria.
            self.assertEqual(post(url(late), action='cancel_direct', reason_code='administrativa', note='corto')['status'], 400)
            self.assertEqual(post(url(late), action='cancel_direct', reason_code='administrativa', note='Caso excepcional autorizado por gerencia (ficticio).')['status'], 200)
        self.assertEqual(self.row(cookie, oid, late)['situation'], 'cancelado')
        self.assertEqual(self.row(cookie, oid, pending)['cancellations'][0]['status'], 'rechazada')  # historial intacto
        # Enlace público: fuera de plazo se ve el bloqueo con candado y la API rechaza la solicitud.
        token = self.link(oid)
        other = made('Teclado ficticio', timedelta(hours=24, minutes=1))
        page = self.request('/s/' + token)['body']
        page = page.decode() if isinstance(page, bytes) else page
        self.assertIn('Plazo de cancelación vencido', page)
        answer = self.form('/s/%s/repuestos/%d/cancelar' % (token, other), {'last4': '0017', 'reason': 'Fuera del plazo de 24 horas (ficticio).', 'confirm': '1'})
        self.assertEqual(answer['status'], 409)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_part_cancellations WHERE request_id=?', (other,)).fetchone()[0], 0)
        r = self.row(cookie, oid, other)
        self.assertEqual((r['cancel_context']['can_request'], r['cancel_context']['window']['open']), (False, False))


if __name__ == '__main__':
    unittest.main()
