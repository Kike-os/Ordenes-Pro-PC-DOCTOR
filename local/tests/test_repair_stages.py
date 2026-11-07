"""Seguimiento de reparación en 6 etapas (1.5.252, datos ficticios, base temporal): cada estado real muestra la etapa e icono correctos, sin
avances falsos ni por tiempo; presupuesto, respuesta, repuesto y falla recurrente en ámbar; panel, cliente y hoja A4 con la misma fuente; la
huella de sincronización cambia solo con un cambio registrado; el cliente nunca ve notas internas."""
import re
import unittest
from datetime import timedelta

import repair_stages
import test_operations as base
import app


class RepairStageTests(unittest.TestCase):
    Base = base.OperationsTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, create, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.create, Base.order_data

    def follow(self, oid, kind, note='Nota interna ficticia de taller', at=None):
        with app.connect() as c:
            c.execute("INSERT INTO order_followups(order_id,kind,internal_note,client_message,client_visible,status_code,next_action,next_date,priority,request_key,created_by,created_at) "
                      "VALUES (?,?,?,'',0,'','','','normal',?,?,?)", (oid, kind, note, 'rs-%s-%d-%s' % (kind, oid, 'a' if at else 'b'), self.uid, (at or app.reception_now()).isoformat(timespec='seconds')))
            c.commit()

    def status(self, cookie, csrf, oid, code):
        body = {'id': str(oid), 'status': code}
        if code == 'revision_recurrente':
            body['comment'] = 'El cliente reporta la misma falla nuevamente (ficticio).'
        got = self.request('/api/order-status', body, cookie=cookie, csrf=csrf)
        self.assertEqual(got['status'], 200, (code, got['body']))

    def view(self, oid):
        with app.connect() as c:
            d = repair_stages.compute(c, oid)
        return [s['state'] for s in d['stages']], d

    def test_every_state_shows_the_right_stage_without_false_progress(self):
        cookie, csrf, data, order = self.create()
        oid = order['id']
        states, d = self.view(oid)  # 1. recién recibida
        self.assertEqual(states, ['current', 'pending', 'pending', 'pending', 'pending', 'pending'])
        self.assertTrue(d['stages'][0]['at'])
        self.assertEqual([s['icon'] for s in d['stages']], ['clipboard-check', 'scan-search', 'wrench', 'shield-check', 'package-check', 'handshake'])
        self.status(cookie, csrf, oid, 'reparacion')  # 2. en proceso, sin seguimiento técnico: diagnóstico
        self.assertEqual(self.view(oid)[0], ['done', 'current', 'pending', 'pending', 'pending', 'pending'])
        self.follow(oid, 'diagnostico')
        states, d = self.view(oid)
        self.assertEqual(states[:2], ['done', 'current']);self.assertTrue(d['stages'][1]['at'])
        self.follow(oid, 'reparacion')  # 3. reparación
        self.assertEqual(self.view(oid)[0], ['done', 'done', 'current', 'pending', 'pending', 'pending'])
        self.status(cookie, csrf, oid, 'presupuesto')  # 4. esperando presupuesto: ámbar, la reparación NO se completa
        states, d = self.view(oid)
        self.assertEqual(states, ['done', 'done', 'warn', 'pending', 'pending', 'pending'])
        self.assertEqual(d['alerts'][0]['title'], 'Presupuesto pendiente de aprobación')
        self.status(cookie, csrf, oid, 'reparacion')
        self.follow(oid, 'finalizado')  # un seguimiento que dice más de lo que permite el estado no adelanta nada
        self.assertEqual(self.view(oid)[0], ['done', 'done', 'done', 'current', 'pending', 'pending'])
        self.follow(oid, 'pruebas')  # 6. pruebas técnicas
        self.assertEqual(self.view(oid)[0], ['done', 'done', 'done', 'current', 'pending', 'pending'])
        self.status(cookie, csrf, oid, 'listo')  # 7. listo para retirar
        states, d = self.view(oid)
        self.assertEqual(states, ['done', 'done', 'done', 'done', 'current', 'pending']);self.assertTrue(d['stages'][4]['at'])
        self.status(cookie, csrf, oid, 'espera_entrega')
        self.assertEqual(self.view(oid)[0][4], 'current')

    def test_waiting_part_recurrent_failure_and_delivery(self):
        cookie, csrf, data, order = self.create()
        oid = order['id']
        earlier = app.reception_now() - timedelta(hours=2)  # trabajo anterior a la reapertura (en la prueba todo ocurre en segundos)
        self.status(cookie, csrf, oid, 'reparacion');self.follow(oid, 'diagnostico', at=earlier);self.follow(oid, 'repuesto', at=earlier)
        with app.connect() as c:  # 5. esperando repuesto
            c.execute("INSERT INTO order_part_requests(order_id,name,brand,compatible_model,reference,quantity,eta,supplier_order,carrier,tracking_number,tracking_url,received_at,internal_note,"
                      "stage,situation,public_visible,request_key,created_at,updated_at) VALUES (?,'Pantalla ficticia','','','',1,'','','','','','','','solicitado','normal',1,'rs-part',?,?)",
                      (oid, app.reception_now().isoformat(timespec='seconds'), app.reception_now().isoformat(timespec='seconds')))
            c.commit()
        states, d = self.view(oid)
        self.assertEqual(states, ['done', 'done', 'warn', 'pending', 'pending', 'pending'])
        self.assertEqual(d['alerts'][-1]['title'], 'Esperando repuesto')
        with app.connect() as c:
            c.execute("UPDATE order_part_requests SET stage='recibido' WHERE order_id=?", (oid,));c.commit()
        self.assertEqual(self.view(oid)[0][2], 'current')
        self.status(cookie, csrf, oid, 'listo');self.status(cookie, csrf, oid, 'entregado')  # 8. entregada
        states, d = self.view(oid)
        self.assertEqual(states, ['done'] * 6);self.assertTrue(d['finished']);self.assertEqual(d['percent'], 100)
        self.status(cookie, csrf, oid, 'revision_recurrente')  # 9. vuelve por falla recurrente: diagnóstico en ámbar, el historial se conserva
        states, d = self.view(oid)
        self.assertEqual(states, ['done', 'warn', 'pending', 'pending', 'pending', 'pending'])
        self.assertEqual(d['alerts'][0]['title'], 'Revisión por falla recurrente')
        with app.connect() as c:
            self.assertGreaterEqual(c.execute('SELECT COUNT(*) FROM order_followups WHERE order_id=?', (oid,)).fetchone()[0], 2)
        self.follow(oid, 'reparacion')
        self.assertEqual(self.view(oid)[0][:3], ['done', 'done', 'warn'])  # avanza con lo registrado después de reabrir, siempre en ámbar

    def test_no_time_based_progress_and_sync_signature(self):
        cookie, csrf, data, order = self.create()
        oid = order['id']
        with app.connect() as c:
            before, sig = repair_stages.compute(c, oid), repair_stages.signature(c, oid)
            later = app.reception_now() + timedelta(days=30)
            c.execute('UPDATE orders SET received_at=? WHERE id=?', ((app.reception_now() - timedelta(days=30)).isoformat(), oid));c.commit()
            self.assertEqual([s['state'] for s in repair_stages.compute(c, oid)['stages']], [s['state'] for s in before['stages']])  # el tiempo no avanza nada
        # 10. sincronización: la huella del cliente y del panel cambia solo cuando cambia algo registrado.
        token = self.request('/api/orders/%d/tracking-card' % oid, cookie=cookie)['body']['public_url'].rsplit('/', 1)[1]
        v1 = self.request('/s/%s/estado' % token)['body']['v']
        self.assertEqual(self.request('/s/%s/estado' % token)['body']['v'], v1)
        panel = self.request('/api/orders/%d/stages' % oid, cookie=cookie)['body']
        self.assertEqual(panel['signature'], v1);self.assertEqual(len(panel['stages']), 6)
        self.status(cookie, csrf, oid, 'reparacion')
        v2 = self.request('/s/%s/estado' % token)['body']['v']
        self.assertNotEqual(v1, v2)
        self.assertEqual(self.request('/api/orders/%d/stages' % oid, cookie=cookie)['body']['signature'], v2)
        self.assertEqual(set(self.request('/s/%s/estado' % token)['body']), {'v'})  # solo la huella: ningún dato de la orden
        self.assertEqual(self.request('/s/AAAAAAAAAAAAAAAAAAAAAA/estado')['status'], 404)
        self.assertIn(self.request('/api/orders/%d/stages' % oid)['status'], (401, 403))

    def test_public_page_panel_and_a4_share_the_same_stages_without_internal_notes(self):
        cookie, csrf, data, order = self.create()
        oid = order['id']
        self.status(cookie, csrf, oid, 'reparacion');self.follow(oid, 'diagnostico', 'NOTA-INTERNA-SECRETA')
        token = self.request('/api/orders/%d/tracking-card' % oid, cookie=cookie)['body']['public_url'].rsplit('/', 1)[1]
        page = self.request('/s/' + token)['body']
        screen = page.split('<section class="pa4"')[0]
        self.assertEqual(re.findall(r'<li class="rp-step" data-state="(\w+)" data-stage="(\w+)"', screen),
                         [('done', 'recepcion'), ('current', 'diagnostico'), ('pending', 'reparacion'), ('pending', 'pruebas'), ('pending', 'listo'), ('pending', 'entregado')])
        self.assertIn('Etapa actual:</span> <b>Diagnóstico</b>', screen);self.assertIn('Estado actual', screen)
        self.assertNotIn('NOTA-INTERNA-SECRETA', page)
        self.assertIn('<noscript><meta http-equiv="refresh" content="180"></noscript>', page)
        detail = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']
        self.assertEqual([s['state'] for s in detail['repair_stages']['stages']], ['done', 'current', 'pending', 'pending', 'pending', 'pending'])
        a4 = page.split('<section class="pa4"')[1]
        self.assertEqual(len(re.findall(r'<li data-state="\w+"><i>', a4.split('pa4-parts')[0])), 6)
        self.assertIn('Diagnóstico', a4);self.assertIn('Pruebas técnicas', a4)


if __name__ == '__main__':
    unittest.main()
