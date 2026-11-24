"""ADI Live Support Center 4.0 · Smart Session Timeout con RELOJ SIMULADO (las horas se pasan explícitamente). Base temporal y
conversaciones ficticias: nada sale por WhatsApp ni por correo. Cubre activa, advertencia, aviso al minuto 7, cierre al minuto 8, respuesta a
los 7:59, mensaje durante el cierre, reapertura automática y manual, esperando asesor, asesor activo, ADI procesando, sin nadie conectado,
mensajes duplicados, reinicio, conversaciones simultáneas, activación con simulación y cierre silencioso de lo antiguo."""
import unittest
from datetime import timedelta

import test_app
import app
import support_sessions as ss

T0 = app.reception_now().replace(microsecond=0)


def at(seconds):
    return T0 + timedelta(seconds=seconds)


class LiveSupportTimeoutTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login

    def admin(self):
        with app.connect() as c:
            return c.execute('SELECT * FROM users WHERE id=?', (self.uid,)).fetchone()

    def conv(self, mode='adi'):
        with app.connect() as c:
            cid = c.execute("INSERT INTO adi_conversations(token_hash,mode,created_at,updated_at) VALUES (?,?,?,?)", (__import__('secrets').token_hex(8), mode, at(0).isoformat(), at(0).isoformat())).lastrowid
            c.commit()
        return cid

    def enable(self):
        with app.connect() as c:
            ss.activate(c, self.admin(), at(0), 'ACTIVAR');c.commit()

    def msg(self, cid, who, seconds, mid=None):
        author = {'client': 'client', 'adi': 'adi', 'human': 'operator'}[who]
        with app.connect() as c:
            rid = c.execute('INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,?,?,?)', (cid, author, 'texto ficticio', at(seconds).isoformat())).lastrowid
            result = ss.activity(c, cid, who, at(seconds), mid or rid)
            c.commit()
        return result

    def sweep(self, cid, seconds):
        with app.connect() as c:
            out = ss.sweep_one(c, cid, at(seconds));c.commit()
            return out, ss.timer(c, cid, at(seconds)), c.execute('SELECT mode FROM adi_conversations WHERE id=?', (cid,)).fetchone()[0]

    def public(self, cid):
        with app.connect() as c:
            return [r[0] for r in c.execute("SELECT content FROM adi_messages WHERE conversation_id=? AND author='adi' ORDER BY id", (cid,))]

    def test_disabled_by_default_and_simulation_before_activation(self):
        cid = self.conv()
        self.msg(cid, 'client', -3600)
        with app.connect() as c:
            self.assertFalse(ss.settings(c)['enabled'])
            sim = ss.simulate_activation(c, at(0))
            self.assertEqual(sim['would_close'], 1)
            self.assertEqual(c.execute('SELECT mode FROM adi_conversations WHERE id=?', (cid,)).fetchone()[0], 'adi')   # simular no cambia nada

    def test_activation_closes_old_conversations_silently(self):
        old = self.conv()
        with app.connect() as c:
            c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'adi',?,?)", (old, 'hola', (T0 - timedelta(days=3)).isoformat()));c.commit()
        before = self.public(old)
        self.enable()
        out, timer, mode = self.sweep(old, 1)
        self.assertEqual(mode, 'closed')
        self.assertEqual(self.public(old), before)                                     # sin avisos masivos a clientes antiguos
        with app.connect() as c:
            self.assertEqual(ss.session(c, old)['close_reason'], 'inactividad_previa_activacion')

    def test_warning_at_5_notice_at_7_close_at_8_exactly(self):
        self.enable()
        cid = self.conv()
        self.msg(cid, 'client', 0)
        self.msg(cid, 'adi', 1)
        _, t, _ = self.sweep(cid, 1 + 299)
        self.assertEqual(t['tone'], 'verde')
        _, t, _ = self.sweep(cid, 1 + 300)
        self.assertEqual((t['tone'], t['remaining_seconds']), ('amarillo', 180))       # advertencia visual al minuto 5
        out, t, _ = self.sweep(cid, 1 + 420)
        self.assertEqual((out, t['tone']), ('aviso', 'rojo'))                            # aviso previo al minuto 7
        self.assertIn('próxima a finalizar', self.public(cid)[-1])
        self.sweep(cid, 1 + 430)
        self.assertEqual(sum('próxima a finalizar' in m for m in self.public(cid)), 1)   # el aviso no se duplica
        out, t, mode = self.sweep(cid, 1 + 479)
        self.assertEqual((out, mode), ('activa', 'adi'))                                  # ya avisada: sigue activa hasta el segundo 480
        out, t, mode = self.sweep(cid, 1 + 480)
        self.assertEqual((out, mode, t['status'], t['closed_at']), ('cerrada', 'closed', 'cerrada', at(481).isoformat()))
        self.assertIn('finalizado esta sesión', self.public(cid)[-1])

    def test_client_answers_at_7_59_keeps_conversation(self):
        self.enable()
        cid = self.conv()
        self.msg(cid, 'adi', 0)
        self.msg(cid, 'client', 479)
        self.msg(cid, 'adi', 480)
        out, t, mode = self.sweep(cid, 481)
        self.assertEqual((mode, t['status'], t['remaining_seconds']), ('adi', 'activa', 479))

    def test_message_after_expiry_closes_at_exact_time_then_reopens_once(self):
        self.enable()
        cid = self.conv()
        self.msg(cid, 'adi', 0)
        result = self.msg(cid, 'client', 900, mid='wamid-1')                         # nadie barrió: llega un mensaje tarde
        self.assertTrue(result['reopened'])
        with app.connect() as c:
            kinds = [e['kind'] for e in ss.events(c, cid)]
            self.assertEqual(kinds[:2], ['reapertura', 'cierre_automatico'])
            again = ss.activity(c, cid, 'client', at(901), 'wamid-1');c.commit()      # mismo mensaje repetido por el proveedor
            self.assertFalse(again['reopened'])
            self.assertEqual(ss.session(c, cid)['reopened_count'], 1)

    def test_waiting_for_staff_is_never_closed_for_client_inactivity(self):
        self.enable()
        cid = self.conv('human')
        self.msg(cid, 'client', 0)
        out, t, mode = self.sweep(cid, 3600)
        self.assertEqual((out, mode, t['tone'], t['waiting_staff']), ('esperando_personal', 'human', 'amarillo', True))
        with app.connect() as c:
            self.assertTrue(any(e['kind'] == 'esperando_personal' for e in ss.events(c, cid)))

    def test_human_attention_and_adi_processing_and_pause(self):
        self.enable()
        cid = self.conv('human')
        self.msg(cid, 'human', 0)
        out, t, mode = self.sweep(cid, 481)
        self.assertEqual(mode, 'closed')                                               # el asesor respondió y el cliente no volvió
        cid2 = self.conv()
        self.msg(cid2, 'adi', 0)
        with app.connect() as c:
            ss.processing(c, cid2, at(470));c.commit()
        self.assertEqual(self.sweep(cid2, 500)[0], 'procesando')
        self.assertEqual(self.sweep(cid2, 470 + 91)[0], 'cerrada')                     # nunca se bloquea indefinidamente
        cid3 = self.conv()
        self.msg(cid3, 'adi', 0)
        with app.connect() as c:
            with self.assertRaises(ss.SupportError):
                ss.pause(c, cid3, self.admin(), 30, 'corto', at(10))
            ss.pause(c, cid3, self.admin(), 30, 'Gestión con el proveedor en curso.', at(10));c.commit()
        self.assertEqual(self.sweep(cid3, 600)[0], 'pausada')
        self.assertEqual(self.sweep(cid3, 10 + 1801)[0], 'cerrada')

    def test_manual_close_reopen_and_simultaneous_conversations(self):
        self.enable()
        a, b = self.conv(), self.conv()
        self.msg(a, 'adi', 0)
        self.msg(b, 'adi', 200)
        with app.connect() as c:
            got = ss.sweep(c, at(481), force=True);c.commit()
            self.assertEqual(got['closed'], 1)
            self.assertEqual(ss.session(c, b)['status'], 'activa')
            again = ss.sweep(c, at(482), force=True);c.commit()
            self.assertEqual(again['closed'], 0)                                       # cierre idempotente
            ss.reopen_manual(c, a, self.admin(), at(490));ss.close_manual(c, a, self.admin(), at(495));c.commit()
            self.assertEqual(ss.session(c, a)['close_kind'], 'manual')
            m = ss.metrics(c, at(500))
            self.assertEqual((m['closed_auto'], m['closed_manual'], m['reopened']), (1, 1, 1))

    def test_polling_does_not_reset_the_timer(self):
        self.enable()
        cid = self.conv()
        self.msg(cid, 'adi', 0)
        for s in (60, 120, 300):
            self.sweep(cid, s)                                                          # consultas periódicas
        with app.connect() as c:
            self.assertEqual(ss.session(c, cid)['expires_at'], at(480).isoformat())

    def test_restart_keeps_state(self):
        self.enable()
        cid = self.conv()
        self.msg(cid, 'adi', 0)
        with app.connect() as c:                                                        # conexión nueva = servidor reiniciado
            self.assertEqual(ss.timer(c, cid, at(100))['remaining_seconds'], 380)

    def test_routes_settings_and_only_admin(self):
        cookie, csrf = self.login()
        got = self.request('/api/adi/live/settings', cookie=cookie)
        self.assertEqual(got['status'], 200, got['body'])
        self.assertEqual(got['body']['settings']['idle_seconds'], 480)
        bad = self.request('/api/adi/live/settings', {'action': 'save', 'idle_seconds': '480', 'client_warning_seconds': '500'}, cookie=cookie, csrf=csrf)
        self.assertEqual(bad['status'], 400)
        self.assertEqual(self.request('/api/adi/live/settings', {'action': 'activate', 'confirm': 'no'}, cookie=cookie, csrf=csrf)['status'], 400)
        self.assertEqual(self.request('/api/adi/live/settings', {'action': 'activate', 'confirm': 'ACTIVAR'}, cookie=cookie, csrf=csrf)['status'], 200)
        listing = self.request('/api/adi/live?filter=proximas_cerrar&channel=web', cookie=cookie)
        self.assertEqual(listing['status'], 200, listing['body'])
        self.assertIn('metrics', listing['body'])
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.request('/api/adi/live/settings', cookie=cookie)['status'], 403)


if __name__ == '__main__':
    unittest.main()
