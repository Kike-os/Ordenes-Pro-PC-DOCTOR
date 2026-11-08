"""Estados de reparación (1.5.257, datos ficticios, base temporal, correo SIMULADO: nada sale a internet).

Once estados con etiquetas y tipo; compatibilidad con el historial anterior; cambios automáticos solo por eventos reales (seguimiento técnico,
presupuesto enviado y aprobado sin marcar la reparación como iniciada, repuesto pedido, recibido e instalado); duplicados y transiciones
incompatibles; auditoría inmutable con avisos y resultados; avisos al cliente solo en cambios relevantes y sin repetir; vista pública sin
información interna y con la fecha estimada solo si está confirmada; mensaje de seguimiento con ADI simulado y sin datos privados."""
import json
import re
import sqlite3
import unittest
from datetime import timedelta
from unittest.mock import patch

import mail_pro
import repair_status
import test_part_requests as parts
import app

MAIL = {'imap_host': 'imap.example.invalid', 'imap_port': 993, 'smtp_host': 'smtp.example.invalid', 'smtp_port': 465, 'username': 'taller@example.invalid', 'password': 'x'}


class RepairStatusRules(unittest.TestCase):
    def test_catalog_kinds_and_legacy_labels(self):
        cat = repair_status.catalog()
        self.assertEqual([s['code'] for s in cat], list(repair_status.ORDER))
        self.assertEqual(len(cat), 11)
        kinds = {s['code']: s['kind'] for s in cat}
        self.assertEqual({k for k, v in kinds.items() if v == 'espera'}, {'presupuesto', 'esperando_cliente', 'esperando_repuesto'})
        self.assertEqual((kinds['revision_recurrente'], kinds['entregado'], kinds['reparacion']), ('incidencia', 'cierre', 'etapa'))
        self.assertTrue(all(s['icon'] and s['label'] and s['public'] for s in cat))
        for old, code in (('En espera', 'pendiente'), ('Procesando', 'reparacion'), ('Aprobación de presupuesto', 'presupuesto'), ('Reparación en proceso', 'reparacion')):
            self.assertEqual(repair_status.code_for_label(old), code)
        import order_workspace
        self.assertEqual(list(order_workspace.STATUSES), list(repair_status.ORDER))


class RepairStatusFlow(unittest.TestCase):
    Base = parts.PartRequestTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link

    def status(self, oid):
        with app.connect() as c:
            return c.execute('SELECT status FROM orders WHERE id=?', (oid,)).fetchone()[0]

    def log(self, oid):
        with app.connect() as c:
            return [tuple(r) for r in c.execute('SELECT from_status,to_status,source FROM order_status_log WHERE order_id=? ORDER BY id', (oid,))]

    def fresh(self, key):
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        order = post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'request_key': 'repair-status-' + key}))['body']
        return cookie, csrf, post, order

    def follow(self, post, oid, kind):
        got = post('/api/orders/%d/followups' % oid, kind=kind, internal_note='Registro técnico ficticio (%s).' % kind, client_message='', client_visible='')
        self.assertEqual(got['status'], 201, got['body'])

    def test_real_events_drive_the_status_and_approval_does_not_start_the_repair(self):
        cookie, csrf, post, order = self.fresh('flow-0001')
        oid = order['id']
        self.assertEqual((self.status(oid), self.log(oid)), ('pendiente', [('', 'pendiente', 'orden_registrada')]))
        self.follow(post, oid, 'diagnostico')  # inicio de la revisión técnica
        self.assertEqual(self.status(oid), 'diagnostico')
        quote = post('/api/orders/%d/quote' % oid)['body']['id']
        post('/api/quotes/%d' % quote, action='save', items=[{'description': 'Servicio ficticio', 'category': 'servicio', 'quantity': 1, 'unit_cents': 4000, 'taxed': True}])
        post('/api/quotes/%d' % quote, action='send')
        self.assertEqual(self.status(oid), 'presupuesto')
        with app.connect() as c:  # el cliente ya recibe el presupuesto con su enlace: no se envía otro aviso
            notes = [tuple(r) for r in c.execute('SELECT event,status,detail FROM order_status_notices WHERE order_id=?', (oid,))]
        self.assertTrue(notes and all(n[1] == 'omitido' and 'enlace de aprobación' in n[2] for n in notes), notes)
        items = [i['id'] for i in self.request('/api/quotes/%d' % quote, cookie=cookie)['body']['quote']['items']]
        self.assertEqual(post('/api/quotes/%d' % quote, action='decide', approved=','.join(map(str, items)), note='Aprobó por teléfono (ficticio)')['status'], 200)
        self.assertEqual(self.status(oid), 'diagnostico')  # se habilita continuar, pero la reparación NO se marca como iniciada
        rid = self.part(post, oid, shipping='nacional')['body']['id']
        self.assertEqual(self.status(oid), 'esperando_repuesto')
        for step in ('confirmado', 'preparacion', 'despachado', 'transito_nacional', 'ruta_otavalo', 'recibido'):
            self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage=step)['status'], 200, step)
        self.assertEqual(self.status(oid), 'diagnostico')  # recibido: vuelve a la etapa anterior a la espera
        notes = self.request('/api/notifications', cookie=cookie)['body']
        self.assertTrue(any(n['title'].startswith('Repuesto recibido') for n in notes.get('items', notes.get('rows', []))), notes)
        self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage='instalacion')['status'], 200)
        self.assertEqual(self.status(oid), 'reparacion')  # inicio efectivo de la reparación
        self.follow(post, oid, 'finalizado')
        self.assertEqual(self.status(oid), 'pruebas')
        self.assertEqual([s for _, s, _ in self.log(oid)], ['pendiente', 'diagnostico', 'presupuesto', 'diagnostico', 'esperando_repuesto', 'diagnostico', 'reparacion', 'pruebas'])
        self.assertEqual([src for *_, src in self.log(oid)][1:], ['followup:diagnostico', 'quote_sent', 'quote_approved', 'part_requested', 'part_received', 'part_installing', 'followup:finalizado'])
        # Una corrección de seguimiento o un seguimiento de comunicación no mueven nada.
        self.follow(post, oid, 'comunicacion')
        self.assertEqual(self.status(oid), 'pruebas')

    def test_duplicates_incompatible_transitions_and_immutable_audit(self):
        cookie, csrf, post, order = self.fresh('rules-0001')
        oid = order['id']
        same = post('/api/order-status', id=str(oid), status='pendiente')
        self.assertEqual((same['status'], same['body'].get('unchanged')), (200, True))
        self.assertEqual(len(self.log(oid)), 1)  # sin cambio: nada nuevo en la auditoría
        bad = post('/api/order-status', id=str(oid), status='esperando_repuesto')
        self.assertEqual(bad['status'], 400);self.assertIn('pedido de repuesto', bad['body']['fields']['comment'])
        bad = post('/api/order-status', id=str(oid), status='pruebas')
        self.assertEqual(bad['status'], 400)
        ok = post('/api/order-status', id=str(oid), status='esperando_repuesto', comment='Repuesto pedido por el cliente por su cuenta (ficticio).')
        self.assertEqual(ok['status'], 200)
        with app.connect() as c:
            row = c.execute('SELECT from_status,to_status,reason,source,actor_id FROM order_status_log WHERE order_id=? ORDER BY id DESC LIMIT 1', (oid,)).fetchone()
            self.assertEqual(tuple(row)[:4], ('pendiente', 'esperando_repuesto', 'Repuesto pedido por el cliente por su cuenta (ficticio).', 'manual'))
            self.assertIsNotNone(row['actor_id'])
            for sql in ('UPDATE order_status_log SET reason=? WHERE order_id=?', 'DELETE FROM order_status_log WHERE order_id=? AND ?=?'):
                with self.assertRaises(sqlite3.DatabaseError):
                    c.execute(sql, ('x', oid) if sql.startswith('UPDATE') else (oid, 1, 1))
        detail = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']
        self.assertEqual([r['to_status'] for r in detail['status_audit']], ['esperando_repuesto', 'pendiente'])
        self.assertEqual(detail['status_audit'][0]['from_label'], 'En espera de diagnóstico')
        self.assertEqual([s['code'] for s in detail['status_timeline']], ['pendiente', 'esperando_repuesto'])

    def test_client_notices_only_relevant_once_and_with_real_result(self):
        cookie, csrf, post, order = self.fresh('notice-0001')
        oid = order['id']
        self.link(oid)
        sent = []
        with patch.object(mail_pro, 'configured', return_value=True), patch.object(mail_pro, 'settings', return_value=MAIL), \
                patch.object(mail_pro, 'deliver', side_effect=lambda config, message, recipients: sent.append(message) or {}):
            post('/api/order-status', id=str(oid), status='diagnostico')  # cambio menor: sin aviso
            self.assertEqual(sent, [])
            post('/api/order-status', id=str(oid), status='listo')
            self.assertEqual(len(sent), 1)
            body = sent[0].get_body(('plain',)).get_content() if hasattr(sent[0], 'get_body') else str(sent[0])
            self.assertIn('disponible para retiro', body);self.assertIn('/s/', body)
            post('/api/order-status', id=str(oid), status='pruebas', comment='Se repite una prueba de carga (ficticio).')
            post('/api/order-status', id=str(oid), status='listo')  # el mismo aviso dentro de 72 h: no se repite
            self.assertEqual(len(sent), 1)
        with app.connect() as c:
            rows = [tuple(r) for r in c.execute("SELECT event,channel,status FROM order_status_notices WHERE order_id=? AND channel='correo' ORDER BY id", (oid,))]
        self.assertEqual(rows, [('listo', 'correo', 'enviado'), ('listo', 'correo', 'omitido')])
        audit = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']['status_audit']
        # 1.5.259: un segundo aviso dentro de 10 minutos se omite (corrección rápida de un estado = un solo correo).
        self.assertEqual(audit[0]['notices'][0]['status'], 'omitido');self.assertIn('10 minutos', audit[0]['notices'][0]['detail'])
        # Administración puede apagar los avisos automáticos: no se genera ninguno.
        self.assertEqual(post('/api/status-notices/settings', auto=False)['status'], 200)
        post('/api/order-status', id=str(oid), status='esperando_cliente')
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM order_status_notices WHERE order_id=? AND event='esperando_cliente'", (oid,)).fetchone()[0], 0)

    def test_public_view_is_clear_and_never_shows_internal_data(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        token = self.link(oid)
        self.part(post, oid, shipping='internacional', supplier_order='PED-SECRETO-77', carrier='Transportes Ficticios')
        post('/api/order-status', id=str(oid), status='reparacion')
        with app.connect() as c:
            c.execute("UPDATE orders SET estimated_delivery='2030-01-15',estimated_confirmed=0,internal_notes='NOTA-INTERNA-XYZ' WHERE id=?", (oid,));c.commit()
        page = self.request('/s/' + token)['body'].split('<section class="pa4"')[0]
        self.assertIn('Estado actual: <b>Reparación en proceso</b>', page)
        self.assertIn('pruebas de funcionamiento y control de calidad', page)
        self.assertIn('Historial del estado', page);self.assertIn('Equipo recibido', page)
        self.assertNotIn('15/01/2030', page)  # fecha estimada sin confirmar: no se muestra
        for secret in ('NOTA-INTERNA-XYZ', 'PED-SECRETO-77', 'Costo 85 USD', 'Aprobó por teléfono'):
            self.assertNotIn(secret, page, secret)
        with app.connect() as c:
            c.execute('UPDATE orders SET estimated_confirmed=1 WHERE id=?', (oid,));c.commit()
        page = self.request('/s/' + token)['body'].split('<section class="pa4"')[0]
        self.assertIn('Fecha estimada de entrega', page);self.assertIn('15/01/2030', page)
        post('/api/order-status', id=str(oid), status='presupuesto')
        page = self.request('/s/' + token)['body'].split('<section class="pa4"')[0]
        self.assertIn('Revise y apruebe el presupuesto', page);self.assertIn('data-kind="espera"', page)

    def test_workspace_edit_confirms_date_and_audits_the_change(self):
        cookie, csrf, post, order = self.fresh('edit-0001')
        oid = order['id']
        detail = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']
        body = {'revision': detail['revision'], 'problem': detail['problem'], 'status': 'diagnostico', 'priority': 'alta', 'assigned_to': str(detail['assigned_to'] or ''),
                'estimated_delivery': '2030-02-01', 'estimated_confirmed': '1', 'internal_notes': '', 'recommendations': '', 'findings': '', 'comment': ''}
        got = post('/api/orders/%d/workspace' % oid, **body)
        self.assertEqual(got['status'], 200, got['body'])
        with app.connect() as c:
            self.assertEqual(tuple(c.execute('SELECT status,estimated_confirmed FROM orders WHERE id=?', (oid,)).fetchone()), ('diagnostico', 1))
        self.assertEqual(self.log(oid)[-1], ('pendiente', 'diagnostico', 'edicion'))

    def test_adi_status_message_uses_real_data_without_private_details(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        self.link(oid)
        with app.connect() as c:
            client, serial = c.execute('SELECT cl.name,d.serial FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?', (oid,)).fetchone()
            c.execute("UPDATE orders SET findings='Ventilador obstruido y pasta térmica seca (confirmado)' WHERE id=?", (oid,));c.commit()
        post('/api/order-status', id=str(oid), status='reparacion')
        plain = post('/api/orders/%d/status-message' % oid, channel='whatsapp')  # sin proveedor de IA en las pruebas: explicación del estado
        self.assertEqual(plain['status'], 200, plain['body'])
        self.assertEqual(plain['body']['source'], 'plantilla')
        self.assertIn('Reparación en proceso', plain['body']['body']);self.assertIn(order['code'], plain['body']['body'])
        self.assertTrue(plain['body']['warnings'])
        seen = {}

        def fake(system, user, long=False):
            seen['user'] = user
            return 'Estamos limpiando el sistema de enfriamiento de su portátil y reemplazando la pasta térmica.', 300, 60
        import adi_ai
        with patch.object(adi_ai, 'provider', lambda: 'openai'), patch.object(adi_ai, '_complete', fake):
            got = post('/api/orders/%d/status-message' % oid, channel='correo', note='mencionar la limpieza')
        self.assertEqual(got['status'], 200, got['body'])
        self.assertEqual((got['body']['source'], got['body']['channel']), ('adi', 'correo'))
        self.assertIn('Ventilador obstruido', seen['user']);self.assertIn('Reparación en proceso', seen['user'])
        for secret in (client, order['code']) + ((serial,) if serial else ()):
            self.assertNotIn(secret, seen['user'], secret)
        self.assertIn('Estimado/a', got['body']['body']);self.assertIn('Orden de servicio: ' + order['code'], got['body']['body'])
        self.assertEqual(post('/api/orders/%d/status-message' % oid, channel='fax')['status'], 400)
        with app.connect() as c:  # redactar no envía nada
            self.assertEqual(c.execute("SELECT COUNT(*) FROM order_messages WHERE order_id=? AND template='estado'", (oid,)).fetchone()[0], 0)


class RepairStatusNotices259(unittest.TestCase):
    """1.5.259: los avisos deben ser verdaderos y no repetirse. Casos reales de producción: «presupuesto pendiente» con el presupuesto ya
    aprobado, aviso de presupuesto a quien ya lo recibió con su enlace y dos correos en 11 s al corregir un estado."""
    Base = parts.PartRequestTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link

    def notes(self, oid):
        with app.connect() as c:
            return [(r['event'], r['status'], r['detail']) for r in c.execute("SELECT event,status,detail FROM order_status_notices WHERE order_id=? AND channel='correo' ORDER BY id", (oid,))]

    def test_notices_must_be_true_and_not_repeated(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)  # presupuesto ya aprobado
        oid = order['id']
        self.link(oid)
        sent = []
        with patch.object(mail_pro, 'configured', return_value=True), patch.object(mail_pro, 'settings', return_value=MAIL), \
                patch.object(mail_pro, 'deliver', side_effect=lambda config, message, recipients: sent.append(message) or {}):
            post('/api/order-status', id=str(oid), status='presupuesto')  # sin presupuesto pendiente: el aviso no sería cierto
            self.assertEqual(sent, []);self.assertIn('no sería cierto', self.notes(oid)[-1][2])
            post('/api/order-status', id=str(oid), status='esperando_repuesto', comment='El cliente traerá el repuesto (ficticio).')  # sin pedido activo
            self.assertEqual(sent, []);self.assertIn('pedido de repuesto activo', self.notes(oid)[-1][2])
            post('/api/order-status', id=str(oid), status='listo', notify='0')  # el personal elige no avisar
            self.assertEqual(sent, []);self.assertIn('eligió no avisar', self.notes(oid)[-1][2])
            post('/api/order-status', id=str(oid), status='esperando_cliente')
            self.assertEqual(len(sent), 1)
            post('/api/order-status', id=str(oid), status='listo')  # 11 s después: un solo correo
            self.assertEqual(len(sent), 1);self.assertIn('10 minutos', self.notes(oid)[-1][2])
        # Presupuesto realmente pendiente, pero recibido hace poco con su enlace: tampoco se repite.
        with app.connect() as c:
            c.execute("UPDATE quotes SET status='enviado',sent_at=? WHERE order_id=?", (app.reception_now().isoformat(timespec='seconds'), oid));c.commit()
            import repair_status
            self.assertIn('menos de 72 horas', repair_status.skip_reason(c, oid, 'presupuesto', 'manual', app.reception_now() + timedelta(hours=1)))
            self.assertEqual(repair_status.skip_reason(c, oid, 'presupuesto', 'manual', app.reception_now() + timedelta(hours=80)), '')


if __name__ == '__main__':
    unittest.main()
