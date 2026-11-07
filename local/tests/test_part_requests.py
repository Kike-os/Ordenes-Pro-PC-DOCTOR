"""Pedidos de repuestos por orden (datos ficticios, base temporal): ocho etapas sin saltos ni avances solos, historial inalterable, varios
repuestos independientes, situaciones (retraso, incidencia, cancelación) sin completar etapas, enlace público solo con lo autorizado,
línea de compra asociada sin duplicar el pedido y sin movimientos de inventario, evidencias por repuesto y permisos."""
import json
import unittest
from datetime import datetime, timedelta

import test_order_followups as base
import app


class PartRequestTests(unittest.TestCase):
    Base = base.OrderFollowupTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure

    def part(self, post, oid, **extra):
        body = dict(name='Pantalla 15,6" FHD 30 pines', brand='BOE', compatible_model='NV156FHM-N48', reference='PANT-156-30P', quantity='1',
                    internal_note='Costo 85 USD, proveedor mayorista (interno)', public_note='Hemos iniciado la gestión del repuesto.', publish='1')
        body.update(extra)
        return post('/api/orders/%d/part-requests' % oid, **body)

    def rows(self, cookie, oid):
        return self.request('/api/orders/%d/part-requests' % oid, cookie=cookie)['body']['rows']

    def link(self, oid):
        with app.connect() as c:
            import order_tracking
            order_tracking.create(c, oid, self.uid, datetime.now().astimezone())
            token = c.execute("SELECT token FROM order_tracking_links WHERE order_id=? AND revoked_at=''", (oid,)).fetchone()[0]
            c.commit()
        return token

    def test_eight_stages_in_order_with_history(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        made = self.part(post, oid, request_key='repuesto-prueba-000001')
        self.assertEqual(made['status'], 200, made['body'])
        rid = made['body']['id']
        self.assertEqual(self.part(post, oid, request_key='repuesto-prueba-000001')['body']['id'], rid)  # doble clic: no duplica
        url = '/api/orders/%d/part-requests/%d' % (oid, rid)
        self.assertEqual(post(url, action='advance', stage='transito')['status'], 400)  # salto: solo administración y con motivo
        stages = ['confirmado', 'preparacion', 'transito', 'recibido', 'instalacion', 'instalado', 'listo']
        for stage in stages:
            r = post(url, action='advance', stage=stage, note='Avance ficticio', public_note='Novedad: ' + stage, publish='1' if stage == 'recibido' else '')
            self.assertEqual(r['status'], 200, (stage, r['body']))
        row = self.rows(cookie, oid)[0]
        self.assertEqual((row['stage'], row['stage_index'], row['received_at']), ('listo', 7, app.reception_now().date().isoformat()))
        self.assertTrue(all(s['at'] for s in row['steps']))  # cada etapa con su fecha y hora
        self.assertEqual([e['kind'] for e in reversed(row['events'])], ['alta'] + ['etapa'] * 7)
        self.assertTrue(all(e['actor'] and e['created_at'] for e in row['events']))
        self.assertEqual(post(url, action='advance', stage='listo')['status'], 409)
        # Corrección de administración (retroceder) con motivo; el historial conserva todo.
        self.assertEqual(post(url, action='advance', stage='instalacion', note='corto')['status'], 400)
        self.assertEqual(post(url, action='advance', stage='instalacion', note='Corrección: la prueba final falló (ficticio)')['status'], 200)
        self.assertEqual(len(self.rows(cookie, oid)[0]['events']), 9)
        with app.connect() as c:
            for sql in ('UPDATE order_part_events SET note=1', 'DELETE FROM order_part_events', 'DELETE FROM order_part_requests'):
                with self.assertRaises(Exception):
                    c.execute(sql)

    def test_three_parts_are_independent_and_situations_never_complete_stages(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        ids = [self.part(post, oid, name=n, eta=(app.reception_now().date() + timedelta(days=d)).isoformat())['body']['id']
               for n, d in (('Batería 4 celdas', 5), ('Teclado español', -3), ('Bisagra derecha', 10))]
        url = lambda rid: '/api/orders/%d/part-requests/%d' % (oid, rid)
        self.assertEqual(post(url(ids[0]), action='advance', stage='confirmado')['status'], 200)
        rows = {r['id']: r for r in self.rows(cookie, oid)}
        self.assertEqual([rows[i]['stage'] for i in ids], ['confirmado', 'solicitado', 'solicitado'])
        self.assertEqual([rows[i]['overdue'] for i in ids], [False, True, False])  # vencido: solo advertencia interna
        # Retraso con nueva fecha confirmada, incidencia de transporte y cancelación: con motivo; las etapas no se completan solas.
        self.assertEqual(post(url(ids[1]), action='situation', situation='retrasado', note='')['status'], 400)
        late = (app.reception_now().date() + timedelta(days=7)).isoformat()
        self.assertEqual(post(url(ids[1]), action='situation', situation='retrasado', note='Proveedor sin stock (ficticio)', eta=late,
                              public_note='Le informamos que la llegada del repuesto presenta un retraso.', publish='1')['status'], 200)
        self.assertEqual(post(url(ids[0]), action='situation', situation='incidencia_transporte', note='Paquete retenido (ficticio)')['status'], 200)
        self.assertEqual(post(url(ids[2]), action='situation', situation='cancelado', note='Cliente desistió (ficticio)')['status'], 200)
        self.assertEqual(post(url(ids[2]), action='advance', stage='confirmado')['status'], 409)  # cancelado es definitivo
        rows = {r['id']: r for r in self.rows(cookie, oid)}
        self.assertEqual([(rows[i]['stage'], rows[i]['situation'], rows[i]['tone']) for i in ids],
                         [('confirmado', 'incidencia_transporte', 'rojo'), ('solicitado', 'retrasado', 'naranja'), ('solicitado', 'cancelado', 'rojo')])
        self.assertEqual((rows[ids[1]]['eta'], rows[ids[1]]['overdue']), (late, False))
        # Al avanzar, la espera o el retraso anterior quedan resueltos; lo completado se conserva.
        self.assertEqual(post(url(ids[1]), action='advance', stage='confirmado')['status'], 200)
        self.assertEqual(self.rows(cookie, oid)[1]['situation'], 'normal')

    def test_public_link_shows_only_authorized_information(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        rid = self.part(post, oid, supplier_order='PED-998877', carrier='Servientrega', tracking_number='GUIA-112233', tracking_url='https://rastreo.example.invalid/x',
                        eta=(app.reception_now().date() + timedelta(days=4)).isoformat())['body']['id']
        hidden = self.part(post, oid, name='Placa madre de respaldo', public_visible='0')['body']['id']
        post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage='confirmado', note='Confirmó por correo (interno)', public_note='El proveedor confirmó el pedido.', publish='1')
        post('/api/orders/%d/part-requests/%d' % (oid, rid), action='advance', stage='preparacion', note='Sin mensaje público', public_note='Texto no publicado', publish='')
        page = self.request('/s/' + self.link(oid))['body']
        self.assertIn('Seguimiento de repuestos', page);self.assertIn('Pantalla 15,6', page);self.assertIn('El proveedor confirmó el pedido.', page)
        self.assertIn('aria-current="step"', page);self.assertIn('Disponibilidad estimada', page)
        for secret in ('Costo 85', 'PED-998877', 'Servientrega', 'GUIA-112233', 'rastreo.example', 'Confirmó por correo', 'Texto no publicado', 'Placa madre de respaldo'):
            self.assertNotIn(secret, page, secret)
        self.assertNotIn(str(hidden), '')  # el repuesto no visible no aparece (comprobado por su nombre arriba)

    def test_existing_purchase_line_is_linked_once_and_moves_no_stock(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        with app.connect() as c:
            sup = c.execute("INSERT INTO suppliers(name,created_at,updated_at) VALUES ('Proveedor Ficticio','x','x')").lastrowid
            cat = c.execute("INSERT INTO catalog_items(code,name,category,price_cents,taxed,available,created_at,updated_at) VALUES ('REP-1','Teclado ficticio','repuesto',2000,1,1,'x','x')").lastrowid
            item = c.execute("INSERT INTO inventory_items(catalog_id,kind,created_at,updated_at) VALUES (?,'repuesto','x','x')", (cat,)).lastrowid
            pur = c.execute("INSERT INTO purchases(supplier_id,document_number,issue_date,status,created_at) VALUES (?,'001-001-000123','2026-11-01','borrador','x')", (sup,)).lastrowid
            line = c.execute('INSERT INTO purchase_items(purchase_id,item_id,quantity,unit_cost_cents) VALUES (?,?,1,1500)', (pur, item)).lastrowid
            moves = c.execute('SELECT COUNT(*) FROM inventory_movements').fetchone()[0]
            c.commit()
        made = self.part(post, oid, supplier_id=str(sup), purchase_item_id=str(line), inventory_item_id=str(item))
        self.assertEqual(made['status'], 200, made['body'])
        other = self.paid_order(10500, pay=False, key='0002')[3]['id']
        dup = self.part(post, other, purchase_item_id=str(line))
        self.assertEqual(dup['status'], 409);self.assertIn('no se crea otro pedido', dup['body']['error'])
        opts = self.request('/api/orders/%d/part-requests' % oid, cookie=cookie)['body']
        self.assertEqual([l['linked_to'] for l in opts['purchase_lines'] if l['id'] == line], [order['code']])
        for stage in ('confirmado', 'preparacion', 'transito', 'recibido'):
            self.assertEqual(post('/api/orders/%d/part-requests/%d' % (oid, made['body']['id']), action='advance', stage=stage)['status'], 200)
        with app.connect() as c:  # recibir en el seguimiento no mueve el inventario ni cambia la compra
            self.assertEqual(c.execute('SELECT COUNT(*) FROM inventory_movements').fetchone()[0], moves)
            self.assertEqual(c.execute('SELECT status FROM purchases WHERE id=?', (pur,)).fetchone()[0], 'borrador')
        row = self.rows(cookie, oid)[0]
        self.assertEqual((row['supplier'], row['purchase_document'], row['inventory_name']), ('Proveedor Ficticio', '001-001-000123', 'Teclado ficticio'))

    def test_data_changes_evidence_and_permissions(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        rid = self.part(post, oid)['body']['id']
        url = '/api/orders/%d/part-requests/%d' % (oid, rid)
        self.assertEqual(post(url, action='update', tracking_url='http://inseguro.example')['status'], 400)
        upd = post(url, action='update', carrier='Tramaco', tracking_number='TR-55', eta='2026-11-30')
        self.assertEqual((upd['status'], upd['body']['changed']), (200, 3))
        ev = self.rows(cookie, oid)[0]['events'][0]
        self.assertEqual((ev['kind'], ev['changes']['carrier']), ('datos', ['', 'Tramaco']))
        # Evidencia del repuesto: un seguimiento de la orden vinculado (mismas reglas de visibilidad).
        fu = post('/api/orders/%d/followups' % oid, kind='repuesto', client_message='Foto del repuesto recibido', client_visible='1', part_request_id=str(rid),
                  files=json.dumps([{'name': 'repuesto.png', 'data': base.PNG, 'visible': '1'}]))
        self.assertEqual(fu['status'], 201, fu['body'])
        self.assertEqual(self.rows(cookie, oid)[0]['evidence'], 1)
        other = self.paid_order(10500, pay=False, key='0003')[3]['id']
        self.assertEqual(post('/api/orders/%d/followups' % other, kind='repuesto', internal_note='x', part_request_id=str(rid))['status'], 400)  # de otra orden
        # Permisos: sin sesión nada; el técnico avanza pero no salta ni retrocede.
        self.assertEqual(self.request('/api/orders/%d/part-requests' % oid)['status'], 401)
        self.assertEqual(self.request(url, {'action': 'advance', 'stage': 'confirmado'})['status'] in (401, 403), True)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(post(url, action='advance', stage='confirmado')['status'], 200)
        self.assertEqual(post(url, action='advance', stage='solicitado', note='Intento de retroceso del técnico')['status'], 403)

    def test_public_model_shows_only_real_events_and_never_the_supplier(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        with app.connect() as c:
            sup = c.execute("INSERT INTO suppliers(name,created_at,updated_at) VALUES ('Distribuidora Zeta','x','x')").lastrowid
            c.commit()
        rid = self.part(post, oid, supplier_id=str(sup), carrier='Servientrega', tracking_number='GX-778899')['body']['id']
        url = '/api/orders/%d/part-requests/%d' % (oid, rid)
        # Un mensaje público con el mercado, el proveedor, el transporte o la guía se rechaza al guardar.
        for leak in ('Lo compramos en eBay', 'Viene de Mercado Libre', 'Pedido a Distribuidora Zeta', 'Enviado por servientrega', 'Guía GX-778899'):
            r = post(url, action='advance', stage='confirmado', public_note=leak, publish='1')
            self.assertEqual((r['status'], list(r['body'].get('fields', {}))), (400, ['public_note']), leak)
        self.assertEqual(post(url, action='advance', stage='confirmado', public_note='El repuesto fue confirmado.', publish='1')['status'], 200)
        import order_part_requests as parts
        with app.connect() as c:
            p = parts.public(c, oid)[0]
            # Seis etapas siempre visibles; «En traslado» queda pendiente (sin vehículo) hasta que se registre.
            self.assertEqual([s['code'] for s in p['steps']], ['solicitud', 'confirmado', 'traslado', 'recibido', 'instalacion', 'finalizado'])
            self.assertEqual([s['state'] for s in p['steps']], ['done', 'current', 'pending', 'pending', 'pending', 'pending'])
            self.assertEqual((p['vehicle'], p['done_count'], p['total']), ('', 1, 6))
            # Un mensaje antiguo con datos del proveedor (guardado antes de esta revisión) no se muestra.
            c.execute("INSERT INTO order_part_events(request_id,kind,stage,situation,public_note,public,created_at) VALUES (?,'etapa','confirmado','normal','Comprado en Amazon',1,'2026-11-04T10:00:00-05:00')", (rid,))
            c.commit()
        for stage in ('preparacion', 'transito'):
            self.assertEqual(post(url, action='advance', stage=stage)['status'], 200)
        with app.connect() as c:
            p = parts.public(c, oid)[0]
            self.assertEqual([s['code'] for s in p['steps']], ['solicitud', 'confirmado', 'traslado', 'recibido', 'instalacion', 'finalizado'])
            self.assertEqual([s['color'] for s in p['steps']], [0, 1, 2, 3, 4, 5])  # de azul a verde, solo al completarse
            self.assertEqual((p['vehicle'], [s['state'] for s in p['steps']][:3]), ('transit', ['done', 'done', 'current']))
            self.assertFalse(any('Amazon' in (h['text'] or '') for h in p['history']))
        # Con una novedad en el traslado, el vehículo se detiene; al recibir, llega y se detiene; después ya no aparece.
        self.assertEqual(post(url, action='situation', situation='incidencia_transporte', note='Paquete retenido (ficticio)')['status'], 200)
        with app.connect() as c:
            self.assertEqual(parts.public(c, oid)[0]['vehicle'], 'stopped')
        self.assertEqual(post(url, action='advance', stage='recibido')['status'], 200)
        with app.connect() as c:
            p = parts.public(c, oid)[0]
            self.assertEqual((p['vehicle'], p['done_count'], p['steps'][3]['state']), ('arrived', 3, 'current'))
        self.assertEqual(post(url, action='advance', stage='instalacion')['status'], 200)
        with app.connect() as c:
            self.assertEqual(parts.public(c, oid)[0]['vehicle'], '')
        # Si administración corrige y el repuesto llega sin traslado registrado, el traslado queda «no registrado», nunca completado.
        other = self.part(post, oid, name='Ventilador')['body']['id']
        ourl = '/api/orders/%d/part-requests/%d' % (oid, other)
        self.assertEqual(post(ourl, action='advance', stage='recibido', note='Corrección: el cliente trajo el repuesto (ficticio)')['status'], 200)
        with app.connect() as c:
            q = parts.public(c, oid)[1]
            # 1.5.249: ninguna etapa superada sin su evento se pinta como completada (tampoco «Repuesto confirmado»).
            self.assertEqual(([s['state'] for s in q['steps']], q['vehicle']), (['done', 'skipped', 'skipped', 'current', 'pending', 'pending'], ''))
            self.assertEqual((q['done_count'], q['progress']['done'], q['progress']['skipped']), (1, 1, 2))
        page = self.request('/s/' + self.link(oid))['body']
        for secret in ('Distribuidora Zeta', 'Servientrega', 'GX-778899', 'Amazon', 'eBay'):
            self.assertNotIn(secret, page)
        self.assertIn('En traslado hacia PC-DOCTOR', page);self.assertIn('No registrada', page)  # ambos repuestos ya llegaron: ninguno en espera

    def test_order_progress_never_advances_on_waiting_states(self):
        import re
        cookie, csrf, post, order = self.paid_order(10500)  # pagada: el sistema no entrega una orden con saldo pendiente
        oid = order['id']
        token = self.link(oid)
        states = lambda: re.findall(r'<li data-state="(\w+)" data-stage', self.request('/s/' + token)['body'])
        self.assertEqual(states(), ['current', 'pending', 'pending', 'pending'])  # recibida: nada en verde
        self.request('/api/order-status', {'id': str(oid), 'status': 'presupuesto'}, cookie=cookie, csrf=csrf)
        page = self.request('/s/' + token)['body']
        self.assertEqual(states(), ['done', 'current', 'pending', 'pending'])
        self.assertIn('Presupuesto pendiente de su aprobación', page)
        self.request('/api/order-status', {'id': str(oid), 'status': 'listo'}, cookie=cookie, csrf=csrf)
        self.assertEqual(states(), ['done', 'done', 'current', 'pending'])  # listo: aún no es la entrega
        self.request('/api/order-status', {'id': str(oid), 'status': 'entregado'}, cookie=cookie, csrf=csrf)
        self.assertEqual(states(), ['done'] * 4)


if __name__ == '__main__':
    unittest.main()
