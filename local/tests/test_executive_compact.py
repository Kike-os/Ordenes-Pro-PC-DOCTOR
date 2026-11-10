"""Detalle de la orden — Executive Compact 5.0 (1.5.270). Datos ficticios en base temporal; nada se envía.

El servidor solo AÑADE lecturas: el estado de entrega de cada correo archivado (por su seguimiento vinculado con archive_id: registrado,
enviado al servidor, entregado con confirmación, fallido/rebotado, desconocido) y los mensajes que no son correo (WhatsApp y texto
copiado), sin repetir los correos. Ningún registro cambia al consultarlos."""
import unittest

import test_app  # primero: prepara la ruta de importación y la base temporal
import app
import mailing

app.os.environ.setdefault('LOGIN_CAPTCHA', 'off')


class ExecutiveCompactTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = test_app.SecurityTests.setUp, test_app.SecurityTests.tearDown, test_app.SecurityTests.request, test_app.SecurityTests.login, test_app.SecurityTests.order_data

    def test_delivery_state_rules(self):
        d = lambda *states: [{'status': s} for s in states]
        cases = [('preparado', [], 'registrado'), ('enviado', [], 'servidor'), ('enviado', d('enviado'), 'servidor'), ('enviado', d('entregado'), 'entregado'),
                 ('enviado', d('entregado', 'enviado'), 'servidor'), ('enviado', d('rebotado'), 'fallido'), ('error', [], 'fallido'), ('enviado', d('fallido'), 'fallido'),
                 ('enviado', d('desconocido'), 'desconocido'), ('enviado', d('demorado'), 'servidor'), ('preparado', d('cola'), 'registrado'), ('enviado', d('enviado', 'rebotado'), 'fallido')]
        for archive, deliveries, expected in cases:
            self.assertEqual(mailing.delivery_state(archive, deliveries)[0], expected, (archive, deliveries))
        self.assertEqual(mailing.delivery_state('enviado', d('rebotado'))[1], 'Rebotado')
        self.assertEqual(mailing.delivery_state('enviado', d('demorado'))[1], 'Entrega demorada')

    def test_order_detail_reports_real_delivery_and_non_mail_messages(self):
        cookie, csrf = self.login()
        order = self.request('/api/orders', self.order_data({'email': 'cliente@example.invalid', 'request_key': 'executive-compact-0001'}), cookie=cookie, csrf=csrf)['body']
        oid = order['id']
        now = app.reception_now().isoformat(timespec='seconds')
        with app.connect() as c:
            ids = {}
            for key, status, adi, detail in (('ok', 'enviado', 'revisado', ''), ('rebote', 'enviado', 'plantilla', ''), ('error', 'error', 'plantilla', 'SMTP 535 (ficticio)'), ('prep', 'preparado', 'plantilla', ''), ('legado', 'enviado', 'plantilla', '')):
                ids[key] = c.execute("INSERT INTO mail_archive(kind,order_id,recipient,subject,body_text,body_html,status,adi,detail,created_at,sent_at) VALUES ('manual',?,?,?,'x','x',?,?,?,?,?)",
                                     (oid, 'cliente@example.invalid', 'Asunto ficticio ' + key, status, adi, detail, now, now if status == 'enviado' else '')).lastrowid
            for key, status, code, reason in (('ok', 'entregado', '250', ''), ('rebote', 'rebotado', '550', 'Buzón inexistente (ficticio)'), ('error', 'fallido', '535', 'Credenciales (ficticio)')):
                c.execute("INSERT INTO mail_deliveries(archive_id,recipient,status,code,reason,order_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                          (ids[key], 'cliente@example.invalid', status, code, reason, oid, now, now))
            for channel, status, error in (('whatsapp', 'error', 'Número no válido (ficticio)'), ('whatsapp_manual', 'preparado', ''), ('correo', 'enviado', '')):
                c.execute("INSERT INTO order_messages(order_id,channel,template,recipient,body,status,error,created_at,updated_at) VALUES (?,?,'estado','0991234567','Texto ficticio',?,?,?,?)",
                          (oid, channel, status, error, now, now))
            c.commit()
            before = [c.execute('SELECT COUNT(*),COALESCE(SUM(length(status)),0) FROM ' + t).fetchone()[:] for t in ('mail_archive', 'mail_deliveries', 'order_messages')]
        detail = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']
        by = {r['subject'].split()[-1]: r for r in detail['mail_history']}
        self.assertEqual({k: by[k]['delivery'] for k in ids}, {'ok': 'entregado', 'rebote': 'fallido', 'error': 'fallido', 'prep': 'registrado', 'legado': 'servidor'})
        self.assertEqual(by['rebote']['delivery_label'], 'Rebotado')
        self.assertEqual((by['rebote']['deliveries'][0]['code'], by['rebote']['deliveries'][0]['reason']), ('550', 'Buzón inexistente (ficticio)'))
        self.assertEqual(by['ok']['adi'], 'revisado')
        # Los correos no se repiten como mensajes; WhatsApp conserva su estado real (un texto abierto a mano nunca figura como enviado).
        self.assertEqual(sorted(m['channel'] for m in detail['messages']), ['whatsapp', 'whatsapp_manual'])
        manual = next(m for m in detail['messages'] if m['channel'] == 'whatsapp_manual')
        self.assertIn('sin confirmación', manual['status_label'])
        failed = next(m for m in detail['messages'] if m['channel'] == 'whatsapp')
        self.assertEqual((failed['status'], failed['status_label'], failed['error']), ('error', 'Fallido', 'Número no válido (ficticio)'))
        with app.connect() as c:  # consultar no cambia nada
            self.assertEqual([c.execute('SELECT COUNT(*),COALESCE(SUM(length(status)),0) FROM ' + t).fetchone()[:] for t in ('mail_archive', 'mail_deliveries', 'order_messages')], before)


if __name__ == '__main__':
    unittest.main()
