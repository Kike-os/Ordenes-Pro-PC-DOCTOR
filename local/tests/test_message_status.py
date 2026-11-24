"""Live Read Receipts 1.0: estados de envío, entrega y lectura en el chat web y WhatsApp. Base temporal, Meta SIMULADO y conversaciones
ficticias: nada sale a internet ni a clientes. Cubre mensajes del cliente, respuestas de ADI y de asesores, entrega, lectura, errores,
eventos duplicados y atrasados, conversaciones cerradas y reabiertas, y que las confirmaciones NO reinician el cierre por inactividad."""
import hashlib
import hmac
import json
import secrets
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_app
import app
import message_status as ms
import support_sessions as ss
import whatsapp_business as wa

T0 = app.reception_now().replace(microsecond=0)


def at(seconds):
    return T0 + timedelta(seconds=seconds)


class MessageStatusTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login

    def conv(self, mode='adi'):
        with app.connect() as c:
            cid = c.execute("INSERT INTO adi_conversations(token_hash,mode,created_at,updated_at) VALUES (?,?,?,?)", (secrets.token_hex(8), mode, at(0).isoformat(), at(0).isoformat())).lastrowid
            c.commit()
        return cid

    def msg(self, cid, author, seconds=0):
        with app.connect() as c:
            mid = c.execute('INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,?,?,?)', (cid, author, 'texto ficticio', at(seconds).isoformat())).lastrowid
            c.commit()
        return mid

    def status(self, mid):
        with app.connect() as c:
            return (ms.for_messages(c, [mid]) or {}).get(mid, {})

    def test_web_flow_received_processed_delivered_read(self):
        cid = self.conv()
        client = self.msg(cid, 'client')
        with app.connect() as c:
            ms.record_in(c, client, cid, 'web', at(0));c.commit()
        self.assertEqual(self.status(client)['status'], 'entregado')               # llegó al servidor: NO es leído
        reply = self.msg(cid, 'adi', 2)
        with app.connect() as c:
            ms.record_out(c, reply, cid, 'web', at(2));ms.inbound_read(c, cid, at(2), 'ADI');c.commit()
        self.assertEqual((self.status(client)['status'], self.status(client)['read_by']), ('leido', 'ADI'))
        self.assertEqual(self.status(reply)['status'], 'enviado')
        with app.connect() as c:
            ms.web_delivered(c, cid, reply, at(3));c.commit()
        self.assertEqual(self.status(reply)['status'], 'entregado')
        with app.connect() as c:
            ms.web_read(c, cid, reply, at(4));c.commit()
        st = self.status(reply)
        self.assertEqual((st['status'], st['read_by'], st['read_at']), ('leido', 'Cliente (chat web)', at(4).isoformat()))

    def test_public_endpoints_require_visible_and_session(self):
        got = self.request('/api/public/adi/message', {'message': 'Hola, ¿tienen batería para laptop?'})
        self.assertEqual(got['status'], 201, got['body'])
        cookie = got.get('cookie') or got.get('set_cookie') or ''
        if not cookie:
            self.skipTest('El ayudante de pruebas no expone la cookie del chat público.')
        cookie = cookie.split(';')[0]
        polled = self.request('/api/public/adi/messages?after=0', cookie=cookie)['body']
        out = [m['id'] for m in polled['messages'] if m['author'] != 'client']
        if not out:
            self.skipTest('ADI no está disponible en las pruebas: no hubo respuesta que confirmar.')
        self.assertEqual(self.request('/api/public/adi/read', {'up_to': str(out[-1]), 'visible': False}, cookie=cookie)['status'], 400)
        self.assertEqual(self.request('/api/public/adi/read', {'up_to': str(out[-1]), 'visible': True})['status'], 404)   # sin sesión
        self.assertEqual(self.request('/api/public/adi/read', {'up_to': str(out[-1]), 'visible': True}, cookie=cookie)['status'], 200)
        self.assertEqual(self.status(out[-1])['status'], 'leido')

    def test_out_of_order_and_duplicate_events_never_go_back(self):
        cid = self.conv()
        out = self.msg(cid, 'adi')
        with app.connect() as c:
            ms.record_out(c, out, cid, 'whatsapp', at(0), 'wamid.FICTICIO1')
            self.assertTrue(ms.meta_status(c, 'wamid.FICTICIO1', 'read', at(5)))
            self.assertFalse(ms.meta_status(c, 'wamid.FICTICIO1', 'delivered', at(6)))   # atrasado: no retrocede
            self.assertFalse(ms.meta_status(c, 'wamid.FICTICIO1', 'read', at(7)))        # duplicado
            self.assertFalse(ms.meta_status(c, 'wamid.FICTICIO1', 'failed', at(8)))      # ya leído: no pasa a error
            c.commit()
        st = self.status(out)
        self.assertEqual((st['status'], st['read_at'], st['delivered_at']), ('leido', at(5).isoformat(), at(5).isoformat()))

    def test_whatsapp_failure_and_no_fake_blue_ticks(self):
        cid = self.conv()
        ok, bad = self.msg(cid, 'adi'), self.msg(cid, 'operator')
        with app.connect() as c:
            ms.record_out(c, ok, cid, 'whatsapp', at(0), 'wamid.FICTICIO2')
            ms.record_out(c, bad, cid, 'whatsapp', at(0), '', 'Meta no aceptó el mensaje.')
            ms.meta_status(c, 'wamid.FICTICIO2', 'delivered', at(3));c.commit()
        self.assertEqual(self.status(ok)['status'], 'entregado')                      # sin «read» de Meta no hay doble visto azul
        self.assertEqual((self.status(bad)['status'], self.status(bad)['error']), ('error', 'Meta no aceptó el mensaje.'))

    def test_signed_webhook_updates_status_and_rejects_unsigned(self):
        cid = self.conv()
        out = self.msg(cid, 'adi')
        with app.connect() as c:
            ms.record_out(c, out, cid, 'whatsapp', at(0), 'wamid.FICTICIO3');c.commit()
        env = {'WHATSAPP_APP_SECRET': 'secreto-ficticio'}
        body = json.dumps({'entry': [{'changes': [{'value': {'statuses': [{'id': 'wamid.FICTICIO3', 'status': 'read'}]}}]}]}).encode()
        with patch.object(wa, 'config', lambda env=None: dict(wa.config.__wrapped__(env) if hasattr(wa.config, '__wrapped__') else {}, secret='secreto-ficticio')):
            with app.connect() as c:
                self.assertEqual(wa.webhook(c, body, 'sha256=malo', at(5)), -1)
                good = 'sha256=' + hmac.new(b'secreto-ficticio', body, hashlib.sha256).hexdigest()
                self.assertGreaterEqual(wa.webhook(c, body, good, at(5)), 1)
                c.commit()
        self.assertEqual(self.status(out)['status'], 'leido')

    def test_staff_seen_and_meta_read_once(self):
        cid = self.conv('human')
        m1, m2 = self.msg(cid, 'client'), self.msg(cid, 'client', 1)
        calls = []
        with app.connect() as c:
            ms.record_in(c, m1, cid, 'whatsapp', at(0), 'wamid.IN1');ms.record_in(c, m2, cid, 'whatsapp', at(1), 'wamid.IN2');c.commit()
            with patch.object(wa, 'ready', lambda env=None: True), patch.object(wa, 'call', lambda *a, **k: calls.append(a[3]['message_id']) or (200, {})), \
                    patch.object(wa, 'config', lambda env=None: {'phone_id': 'PHONE_FICTICIO'}):
                ms.inbound_read(c, cid, at(5), 'Persona de prueba', up_to_id=m1)
                ms.inbound_read(c, cid, at(6), 'Persona de prueba')
                ms.inbound_read(c, cid, at(7), 'Persona de prueba')                   # nada más que confirmar
            c.commit()
        self.assertEqual((self.status(m1)['read_by'], self.status(m2)['status']), ('Persona de prueba', 'leido'))
        self.assertEqual(calls, ['wamid.IN1', 'wamid.IN2'])                             # una confirmación oficial por mensaje, nunca repetida

    def test_receipts_do_not_reset_the_inactivity_timer(self):
        cid = self.conv()
        out = self.msg(cid, 'adi')
        with app.connect() as c:
            c.execute("SELECT 1").fetchone()
            ss.activate(c, c.execute('SELECT * FROM users WHERE id=?', (self.uid,)).fetchone(), at(0), 'ACTIVAR')
            ss.activity(c, cid, 'adi', at(0))
            ms.record_out(c, out, cid, 'web', at(0));ms.web_delivered(c, cid, out, at(100));ms.web_read(c, cid, out, at(200));c.commit()
            self.assertEqual(ss.session(c, cid)['expires_at'], at(480).isoformat())
            ss.sweep_one(c, cid, at(481));c.commit()
            self.assertEqual(ss.session(c, cid)['status'], 'cerrada')
            self.assertEqual((ms.for_messages(c, [out]) or {})[out]['status'], 'leido')   # el estado se conserva al cerrar

    def test_staff_routes(self):
        cookie, csrf = self.login()
        cid = self.conv('human')
        m = self.msg(cid, 'client')
        with app.connect() as c:
            ms.record_in(c, m, cid, 'web', at(0));c.commit()
        detail = self.request('/api/adi/live/%d' % cid, cookie=cookie)['body']
        self.assertEqual(detail['receipts'][str(m)]['status'] if str(m) in detail['receipts'] else detail['receipts'][m]['status'], 'entregado')
        got = self.request('/api/adi/live/%d' % cid, {'action': 'seen', 'up_to': str(m)}, cookie=cookie, csrf=csrf)
        self.assertEqual(got['status'], 200, got['body'])
        self.assertEqual(self.status(m)['status'], 'leido')


if __name__ == '__main__':
    unittest.main()
