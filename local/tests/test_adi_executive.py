"""ADI Executive Intelligence 5.0: herramientas ejecutivas de solo lectura con permiso validado en el servidor, recomendaciones sin
duplicados, metadatos verificables (pasos y fuentes), regenerar sin duplicar la pregunta, calificación, favoritos y archivo, borrado que
limpia sus datos, historial sin credenciales y estado real del servicio. OpenAI SIMULADO; base temporal y datos ficticios."""
import json
import unittest
from unittest.mock import patch

import test_adi_admin_data as base
import app
import adi
import adi_admin
import adi_exec

KEY = base.KEY
FakeModel = base.FakeModel


class AdiExecutiveTests(base.AdiAdminDataTests):
    def run(self, result=None):   # solo las pruebas de este archivo (no repite las heredadas)
        if not self._testMethodName.startswith('test_x'):
            return result
        return super().run(result)

    def ask(self, cookie, csrf, text, **extra):
        got = self.request('/api/adi/admin', dict({'message': text}, **extra), cookie=cookie, csrf=csrf)
        self.assertEqual(got['status'], 200, got['body'])
        return got['body']

    def test_x01_every_executive_tool_answers_read_only_without_private_data(self):
        self.workshop()
        now = app.reception_now()
        with app.connect() as c:
            admin = c.execute('SELECT * FROM users WHERE id=?', (self.uid,)).fetchone()
            before = c.execute('SELECT total_changes()').fetchone()[0]
            for tool in adi_exec.TOOLS:
                args = {'desde': None, 'hasta': None} if tool['name'] == 'facturacion' else {}
                out = adi_exec.run(c, now, tool['name'], args, admin)
                self.assertIsInstance(out, dict, tool['name'])
                self.assertNotIn('error', out, (tool['name'], out))
                text = json.dumps(out, ensure_ascii=False, default=str)
                self.assertNotIn('@example', text)                                        # sin correos de clientes
                self.assertNotIn('sk-', text)                                             # sin claves
            self.assertEqual(c.execute('SELECT total_changes()').fetchone()[0], before)   # nada se escribe
            self.assertIn('no_disponible', adi_exec.finanzas(c, now)['rentabilidad'])    # la rentabilidad no se inventa

    def test_x02_permissions_are_enforced_by_the_server_not_the_prompt(self):
        cookie, csrf, *_ = self.workshop()
        now = app.reception_now()
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
            tech = c.execute('SELECT * FROM users WHERE id=?', (self.uid,)).fetchone()
            for tool in adi_exec.TOOLS:
                self.assertEqual(adi_exec.run(c, now, tool['name'], {}, tech)['error'], 'sin_permiso')
            self.assertEqual(adi_exec.run(c, now, 'finanzas', {}, None)['error'], 'sin_permiso')   # sin usuario: tampoco
        fake = FakeModel([], lambda outs: 'ok')
        with patch.dict(app.os.environ, KEY), patch.object(adi, '_post', side_effect=fake):
            with app.connect() as c:
                adi_admin.ask(c, 'hola', now, (), tech)
        self.assertFalse({t['name'] for t in fake.calls[0]['tools']} & {t['name'] for t in adi_exec.TOOLS})   # ni siquiera se le ofrecen
        for path in ('/api/adi/admin', '/api/adi/admin/insights', '/api/adi/conversations'):
            self.assertEqual(self.request(path, cookie=cookie)['status'], 403)
        self.assertEqual(self.request('/api/adi/admin/feedback', {'message_id': '1', 'rating': '1'}, cookie=cookie, csrf=csrf)['status'], 403)

    def test_x03_steps_and_sources_are_only_the_tools_really_run_and_regenerate_does_not_duplicate(self):
        cookie, csrf, *_ = self.workshop()
        fake = FakeModel([('finanzas', {}), ('cartera', {})], lambda outs: 'Resumen financiero.')
        with patch.dict(app.os.environ, KEY), patch.object(adi, '_post', side_effect=fake):
            first = self.ask(cookie, csrf, '¿Cuánto hemos recibido realmente este mes?')
        self.assertEqual(first['steps'], ['Consultando información financiera', 'Consultando cartera'])
        self.assertIn('ADI Smart Collections', first['sources'])
        self.assertTrue(first['consulted_at'])
        self.assertEqual(fake.outputs[0]['moneda'], 'USD')
        conv = str(first['conversation']['id'])
        again = FakeModel([], lambda outs: 'Otra redacción.')
        with patch.dict(app.os.environ, KEY), patch.object(adi, '_post', side_effect=again):
            second = self.ask(cookie, csrf, 'ignorado', conversation_id=conv, regenerate=True)
        self.assertEqual(again.calls[0]['input'][-1]['content'], '¿Cuánto hemos recibido realmente este mes?')   # repite la MISMA pregunta
        self.assertIsNone(second['user_message_id'])
        detail = self.request('/api/adi/conversations/' + conv, cookie=cookie)['body']
        self.assertEqual([m['role'] for m in detail['messages']], ['user', 'adi', 'adi'])   # la pregunta no se duplica
        self.assertEqual(detail['messages'][1]['steps'], ['Consultando información financiera', 'Consultando cartera'])
        self.assertEqual(self.request('/api/adi/admin', {'message': 'x', 'regenerate': True}, cookie=cookie, csrf=csrf)['status'], 400)

    def test_x04_feedback_favorites_archive_and_delete_cleanup(self):
        cookie, csrf, *_ = self.workshop()
        out = self.ask(cookie, csrf, 'Dame el resumen del taller')
        conv, mid = out['conversation']['id'], out['message_id']
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        self.assertEqual(post('/api/adi/admin/feedback', message_id=str(mid), rating='1')['status'], 200)
        self.assertEqual(post('/api/adi/admin/feedback', message_id=str(out['user_message_id']), rating='1')['status'], 404)   # solo respuestas de ADI
        self.assertEqual(self.request('/api/adi/conversations/%d' % conv, cookie=cookie)['body']['messages'][1]['rating'], 1)
        self.assertEqual(post('/api/adi/conversations/%d' % conv, action='favorite', value=True)['status'], 200)
        lists = lambda view: [r['id'] for r in self.request('/api/adi/conversations?view=' + view, cookie=cookie)['body']['rows']]
        self.assertEqual((lists('favoritas'), lists('archivadas')), ([conv], []))
        post('/api/adi/conversations/%d' % conv, action='archive', value=True)
        self.assertEqual((lists('recientes'), lists('favoritas'), lists('archivadas')), ([], [], [conv]))
        self.assertEqual(post('/api/adi/conversations/%d' % conv, action='archive', value='si')['status'], 400)
        self.assertEqual(post('/api/adi/conversations/%d' % conv, action='delete')['status'], 200)
        with app.connect() as c:
            for table in ('adi_admin_meta', 'adi_admin_feedback', 'adi_admin_flags', 'adi_admin_messages'):
                self.assertEqual(c.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0, table)
            other = c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('otro','otro@example.invalid','Otra persona',?, 'administrador',0)", (self.hash,)).lastrowid
            foreign = c.execute("INSERT INTO adi_admin_conversations(user_id,title,created_at,updated_at) VALUES (?,'privada','x','x')", (other,)).lastrowid
            c.commit()
        self.assertEqual(self.request('/api/adi/conversations/%d' % foreign, cookie=cookie)['status'], 404)        # privada de otro usuario
        self.assertEqual(post('/api/adi/conversations/%d' % foreign, action='favorite', value=True)['status'], 404)

    def test_x05_history_never_keeps_credentials(self):
        cookie, csrf, *_ = self.workshop()
        fake = FakeModel([], lambda outs: 'Entendido.')
        with patch.dict(app.os.environ, KEY), patch.object(adi, '_post', side_effect=fake):
            out = self.ask(cookie, csrf, 'Mi contraseña es Secreta2026* y el token: sk-abcdefghijklmnopqrstuvwx, ¿qué órdenes hay?')
        self.assertNotIn('Secreta2026*', json.dumps(fake.calls[0]['input'], ensure_ascii=False))       # no llega a la IA
        with app.connect() as c:
            stored = c.execute("SELECT content FROM adi_admin_messages WHERE role='user'").fetchone()[0]
        self.assertNotIn('Secreta2026*', stored)
        self.assertNotIn('sk-abcdefghijklmnopqrstuvwx', stored)
        self.assertIn('[dato sensible omitido]', stored)
        self.assertIn('qué órdenes hay', stored)
        self.assertEqual(adi_exec.redact('La orden PCD-20261124-0001 está lista'), 'La orden PCD-20261124-0001 está lista')   # lo normal no se toca

    def test_x06_insights_are_verifiable_unique_and_service_state_is_real(self):
        cookie, csrf, late, *_ = self.workshop()
        data = self.request('/api/adi/admin/insights', cookie=cookie)['body']
        keys = [i['key'] for i in data['items']]
        self.assertEqual(len(keys), len(set(keys)))                                                # sin duplicados
        overdue = next(i for i in data['items'] if i['key'] == 'ordenes_vencidas')
        self.assertIn(late['code'], overdue['records'])
        self.assertEqual((overdue['priority'], overdue['level_label'], overdue['department']), ('alta', 'Alta', 'Operaciones técnicas'))
        self.assertTrue(all(i['priority'] in ('critica', 'alta', 'media', 'informativa') for i in data['items']))
        self.assertEqual([i['priority'] for i in data['items']], sorted((i['priority'] for i in data['items']), key=['critica', 'alta', 'media', 'informativa'].index))
        for field in ('reason', 'priority', 'detected_at', 'data', 'action', 'href'):
            self.assertTrue(overdue[field], field)
        state = self.request('/api/adi/admin', cookie=cookie)['body']['service']
        self.assertEqual(state['level'], 'gris')                                                   # sin IA configurada: nunca «en línea»
        with patch.dict(app.os.environ, KEY), patch.object(adi, '_post', side_effect=OSError('sin red')):
            self.ask(cookie, csrf, 'Resumen')
            self.assertEqual(self.request('/api/adi/admin', cookie=cookie)['body']['service']['level'], 'rojo')
        with patch.dict(app.os.environ, KEY), patch.object(adi, '_post', side_effect=FakeModel([], lambda o: 'Listo.')):
            self.ask(cookie, csrf, 'Resumen')
            self.assertEqual(self.request('/api/adi/admin', cookie=cookie)['body']['service']['level'], 'verde')


if __name__ == '__main__':
    unittest.main()
