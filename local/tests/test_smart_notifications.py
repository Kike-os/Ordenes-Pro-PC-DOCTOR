"""ADI Smart Notifications Premium 3.0: diagnóstico de ADI a partir de la respuesta REAL del proveedor, nombres legibles, historial de
intentos (migración 129), estados históricos intactos y permisos. Base temporal y datos ficticios; WhatsApp no configurado: no se envía nada."""
import unittest

import test_app
import app
import whatsapp_business as wa


class SmartNotificationsTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login

    def outbox(self, c, status, kind='', code='', detail='', key='x'):
        return c.execute("INSERT INTO whatsapp_outbox(dedupe_key,event,source,recipient,template,template_lang,params,preview,status,detail,reason_kind,error_code,attempts,created_at,updated_at) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)", ('prueba-' + key, 'equipo_listo', 'auto', '593991234567', '', '', '[]', '', status, detail, kind, code,
                                                                     '2026-11-26T09:00:00-05:00', '2026-11-26T09:00:00-05:00')).lastrowid

    def test_diagnosis_uses_provider_response_and_keeps_history(self):
        with app.connect() as c:
            failed = self.outbox(c, 'fallido', '', '131026', '(#131026) Message undeliverable', 'a')
            skipped = self.outbox(c, 'omitido', 'plantilla', '', 'Sin plantilla aprobada.', 'b')
            ok = self.outbox(c, 'entregado', key='c')
            c.commit()
            rows = {r['id']: r for r in c.execute('SELECT * FROM whatsapp_outbox WHERE id IN (?,?,?)', (failed, skipped, ok))}
            d1, d2 = wa.diagnose(rows[failed]), wa.diagnose(rows[skipped])
            self.assertEqual((d1['category'], d1['title'], d1['code']), ('telefono', 'Número del cliente', '131026'))   # deducido del código de Meta
            self.assertIn('(#131026)', d1['cause'])                                                                    # la causa es la respuesta real
            self.assertEqual(d2['category'], 'plantilla');self.assertIn('no se reenvía automáticamente', d2['note'])
            self.assertIsNone(wa.diagnose(rows[ok]))
            self.assertEqual(wa.item(c, rows[failed])['label'], 'Equipo listo')                                         # nombre legible, nunca el código
            wa._attempt(c, failed, 'envio', 'fallido', 'Error ficticio', '400', '131026')
            c.commit()
            self.assertEqual([(a['status'], a['error_code']) for a in wa.attempts_of(c, failed)], [('fallido', '131026')])
            self.assertEqual(c.execute('SELECT status FROM whatsapp_outbox WHERE id=?', (skipped,)).fetchone()[0], 'omitido')   # el histórico no cambia
        cookie, csrf = self.login()
        out = self.request('/api/whatsapp/outbox/%d/attempts' % failed, cookie=cookie)
        self.assertEqual(out['status'], 200);self.assertTrue(out['body']['logged']);self.assertEqual(len(out['body']['attempts']), 1)
        self.assertEqual(self.request('/api/whatsapp/outbox/%d/attempts' % failed)['status'], 401)
        self.assertEqual(self.request('/api/whatsapp/outbox/999999/attempts', cookie=cookie)['status'], 404)


if __name__ == '__main__':
    unittest.main()
