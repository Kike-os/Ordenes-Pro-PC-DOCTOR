"""ADI para administración: consulta órdenes, estados, presupuestos, citas y licencias reales (solo lectura) y avisa de los trabajos
atrasados. El canal de clientes no recibe datos internos. OpenAI simulado como la API Responses. Base temporal y datos ficticios."""
import json
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_app
import app
import adi
import adi_admin
import quotes

KEY = {'OPENAI_API_KEY': 'sk-prueba-ficticia-123'}


class FakeModel:
    """Pide las herramientas indicadas (una por ronda) y al final responde con el texto que arme `answer` a partir de lo recibido."""
    def __init__(self, tools, answer):
        self.tools, self.answer, self.calls, self.outputs = list(tools), answer, [], []

    def __call__(self, api_key, payload):
        self.calls.append(payload)
        if 'previous_response_id' in payload:
            self.outputs.append(json.loads(payload['input'][0]['output']))
        if self.tools:
            name, args = self.tools.pop(0)
            return {'id': 'resp_%d' % len(self.calls), 'output': [{'type': 'function_call', 'call_id': 'call_%d' % len(self.calls), 'name': name, 'arguments': json.dumps(args)}]}
        return {'id': 'resp_end', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': self.answer(self.outputs)}]}]}


class AdiAdminDataTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    request = test_app.SecurityTests.request
    login = test_app.SecurityTests.login
    order_data = test_app.SecurityTests.order_data

    def workshop(self):
        """Dos órdenes: una con la entrega vencida y otra esperando al cliente con su presupuesto enviado (como la PCD-20261019-0005)."""
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        late = post('/api/orders', **self.order_data({'request_key': 'adi-admin-late-order-0001', 'brand': 'Dell', 'model': 'Ficticio Late', 'email': 'cliente@example.invalid'}))['body']
        waiting = post('/api/orders', **self.order_data({'request_key': 'adi-admin-wait-order-0002', 'brand': 'HP', 'model': 'Ficticio Quote', 'email': 'cliente@example.invalid'}))['body']
        quote = post('/api/orders/%d/quote' % waiting['id'])['body']['id']
        post('/api/quotes/%d' % quote, action='save', items=[{'description': 'Batería ficticia', 'category': 'repuesto', 'quantity': 1, 'unit_cents': 9800, 'taxed': True}])
        self.assertEqual(post('/api/quotes/%d' % quote, action='send')['status'], 200)
        today = app.reception_now().date()
        with app.connect() as c:
            c.execute("UPDATE orders SET estimated_delivery=?,status='reparacion' WHERE id=?", ((today - timedelta(days=3)).isoformat(), late['id']))
            c.execute("UPDATE orders SET status='esperando_cliente' WHERE id=?", (waiting['id'],))
            c.commit()
        return cookie, csrf, late, waiting, quote

    def test_tools_return_real_data_and_validate_arguments(self):
        cookie, csrf, late, waiting, quote = self.workshop()
        now = app.reception_now()
        with app.connect() as c:
            found = adi_admin.run_tool(c, now, 'buscar_ordenes', json.dumps({'estado': 'activas', 'texto': 'dell'}))
            self.assertEqual((found['total'], found['ordenes'][0]['orden'], found['ordenes'][0]['dias_de_atraso']), (1, late['code'], 3))
            detail = adi_admin.run_tool(c, now, 'detalle_orden', json.dumps({'codigo': waiting['code']}))
            self.assertEqual((detail['estado'], detail['presupuestos'][0]['estado'], detail['autorizacion']), ('Esperando respuesta del cliente', 'Esperando aprobación', 'sin partidas aprobadas'))
            self.assertEqual(detail['cobro']['pagado'], '$0,00')
            pending = adi_admin.run_tool(c, now, 'presupuestos', json.dumps({'grupo': 'pendientes'}))
            self.assertEqual([(q['presupuesto'], q['cotizado'], q['enlace_abierto_por_el_cliente']) for q in pending['presupuestos']], [(waiting['code'] + '-P1', '$98,00', 'no')])
            self.assertEqual(adi_admin.run_tool(c, now, 'citas', json.dumps({'desde': None, 'hasta': None}))['total'], 0)
            self.assertEqual(adi_admin.run_tool(c, now, 'citas', json.dumps({'desde': '2026-01-01', 'hasta': '2026-12-31'}))['error'], 'rango_no_valido')
            self.assertEqual(adi_admin.run_tool(c, now, 'licencias', json.dumps({'vista': 'inventario'}))['vista'], 'inventario')
            self.assertEqual(adi_admin.run_tool(c, now, 'detalle_orden', json.dumps({'codigo': 'PCD-20000101-9999'}))['error'], 'orden_no_encontrada')
            self.assertEqual(adi_admin.run_tool(c, now, 'borrar_todo', '{}')['error'], 'herramienta_desconocida')
            self.assertEqual(adi_admin.run_tool(c, now, 'buscar_ordenes', 'no es json')['error'], 'argumentos_no_validos')
            # Un texto con comillas o SQL se busca como texto (consulta parametrizada): no rompe nada ni devuelve todo.
            self.assertEqual(adi_admin.run_tool(c, now, 'buscar_ordenes', json.dumps({'estado': None, 'texto': "' OR 1=1 --"}))['total'], 0)
            before = c.total_changes
            adi_admin.alerts(c, now)
            self.assertEqual(c.total_changes, before)  # solo lectura

    def test_alerts_report_overdue_stale_and_expired_quotes(self):
        cookie, csrf, late, waiting, quote = self.workshop()
        today = app.reception_now().date()
        with app.connect() as c:
            c.execute("UPDATE quotes SET valid_until=? WHERE id=?", ((today - timedelta(days=1)).isoformat(), quote));c.commit()
        data = self.request('/api/adi/admin/alerts', cookie=cookie)['body']
        self.assertEqual([item['tipo'] for item in data['avisos']], ['entrega_vencida', 'presupuesto_vencido'])
        self.assertIn('3 días de atraso', data['avisos'][0]['texto']);self.assertEqual(data['avisos'][0]['enlace'], '#orders?id=%d' % late['id'])
        # El historial es inmutable: «sin movimiento» se comprueba consultando 10 días después (sin eventos nuevos en la orden que espera).
        with app.connect() as c:
            later = adi_admin.alerts(c, app.reception_now() + timedelta(days=10))
        self.assertEqual((later['entregas_vencidas'], later['sin_movimiento'], later['presupuestos_vencidos']), (1, 1, 1))
        self.assertIn('sin movimiento desde hace 10 días', next(i['texto'] for i in later['avisos'] if i['tipo'] == 'sin_movimiento'))
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.request('/api/adi/admin/alerts', cookie=cookie)['status'], 403)
        self.assertEqual(self.request('/api/adi/admin/alerts')['status'], 401)

    def test_without_ai_answers_from_data_including_quotes_of_waiting_orders(self):
        cookie, csrf, late, waiting, quote = self.workshop()
        ask = lambda text: self.request('/api/adi/admin', {'message': text}, cookie=cookie, csrf=csrf)['body']
        # Antes solo miraba órdenes en «Aprobación de presupuesto»: un presupuesto enviado en una orden «Esperando respuesta» no salía.
        self.assertIn(waiting['code'] + '-P1', ask('¿Qué presupuestos están pendientes?')['answer'])
        late_answer = ask('¿Qué trabajos están atrasados?')
        self.assertIn(late['code'], late_answer['answer']);self.assertIn('3 días de atraso', late_answer['answer'])
        self.assertIn('#orders?id=%d' % late['id'], [link['href'] for link in late_answer['links']])
        self.assertEqual(ask('¿Cuál es el inventario de licencias?')['answer'], 'No hay productos de licencias configurados en el inventario.')  # base sin licencias: lo dice, no inventa
        self.assertNotIn('asesor', ask('Dame el resumen del taller').get('answer', '').lower())

    def test_with_ai_uses_read_only_tools_and_keeps_the_conversation(self):
        cookie, csrf, late, waiting, quote = self.workshop()
        fake = FakeModel([('trabajos_atrasados', {}), ('detalle_orden', {'codigo': late['code']})],
                         lambda outs: 'Atrasada: %s (%d días). Estado: %s.' % (outs[1]['orden'], outs[1]['dias_de_atraso'], outs[1]['estado']))
        with patch.dict(app.os.environ, KEY), patch.object(adi, '_post', side_effect=fake):
            first = self.request('/api/adi/admin', {'message': '¿Qué está atrasado?'}, cookie=cookie, csrf=csrf)['body']
        self.assertEqual(first['source'], 'ia')
        self.assertEqual(first['answer'], 'Atrasada: %s (3 días). Estado: Procesando.' % late['code'])
        self.assertEqual(fake.outputs[0]['entregas_vencidas'], 1)
        self.assertIn('Abrir ' + late['code'], [link['label'] for link in first['links']])
        self.assertIn('administrador', fake.calls[0]['instructions']);self.assertIn('No ofrezcas un asesor humano', fake.calls[0]['instructions'])
        self.assertEqual({tool['name'] for tool in fake.calls[0]['tools']}, {'resumen_taller', 'trabajos_atrasados', 'buscar_ordenes', 'detalle_orden', 'presupuestos', 'citas', 'licencias'})
        second = FakeModel([], lambda outs: 'Sigue igual.')
        with patch.dict(app.os.environ, KEY), patch.object(adi, '_post', side_effect=second):
            self.request('/api/adi/admin', {'message': '¿Y esa orden?', 'conversation_id': str(first['conversation']['id'])}, cookie=cookie, csrf=csrf)
        history = second.calls[0]['input']
        self.assertEqual([m['role'] for m in history], ['user', 'assistant', 'user'])  # contexto de la misma conversación
        self.assertEqual(history[1]['content'], first['answer'])

    def test_ai_failure_falls_back_to_data_and_customers_never_get_internal_tools(self):
        cookie, csrf, late, waiting, quote = self.workshop()
        with patch.dict(app.os.environ, KEY), patch.object(adi, '_post', side_effect=OSError('sin red')):
            out = self.request('/api/adi/admin', {'message': '¿Qué trabajos están atrasados?'}, cookie=cookie, csrf=csrf)['body']
        self.assertIn(late['code'], out['answer'])
        # Canal de clientes: sus herramientas no incluyen ninguna de administración y no llama a adi_admin.
        self.assertFalse({tool['name'] for tool in adi.TOOLS} & {tool['name'] for tool in adi_admin.TOOLS})
        with patch.object(adi_admin, 'ask', side_effect=AssertionError('canal de clientes')), patch.object(adi_admin, 'alerts', side_effect=AssertionError('canal de clientes')):
            reply = self.request('/api/public/adi/message', {'message': '¿Qué órdenes están atrasadas?'})
        self.assertIn(reply['status'], (200, 201))
        self.assertNotIn(late['code'], json.dumps(reply['body'], ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
