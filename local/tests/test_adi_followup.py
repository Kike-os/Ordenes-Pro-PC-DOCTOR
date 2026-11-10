"""ADI Smart Follow-Up 4.0 (1.5.267): mensaje de seguimiento con estado técnico y financiero REAL. Datos ficticios, base temporal y
proveedor de IA simulado (nada sale a internet; nada se envía).

Cubre: sin pagos, anticipo, pagos parciales, pagado, sin cargos, finanzas no verificables, saldo que cambia después de generar,
diagnóstico, reparación, pruebas, listo, WhatsApp y correo, anotaciones (notas internas fuera, omisiones reales) y contradicciones."""
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_part_requests as parts  # primero: prepara la ruta de importación y la base temporal
import adi_ai
import app
import status_messages

BODY = 'Su equipo avanza según lo registrado por el técnico.'


class SmartFollowUpTests(unittest.TestCase):
    Base = parts.PartRequestTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link

    def order(self, cents=10500, key='0001'):
        cookie, csrf, post, order = self.paid_order(cents, pay=False) if cents else self.fresh(key)
        self.post = post
        return order['id'], order

    def fresh(self, key):
        cookie, csrf = self.login()
        post = lambda path, **body: self.request(path, body, cookie=cookie, csrf=csrf)
        order = post('/api/orders', **self.order_data({'email': 'cliente@example.invalid', 'request_key': 'smart-follow-' + key}))['body']
        return cookie, csrf, post, order

    def pay(self, oid, amount, **extra):
        got = self.post('/api/orders/%d/payments' % oid, amount=amount, method=extra.pop('method', 'efectivo'), **extra)
        self.assertEqual(got['status'], 201, got['body'])

    def set_status(self, oid, status, **fields):
        with app.connect() as c:
            c.execute('UPDATE orders SET status=?' + ''.join(',%s=?' % k for k in fields) + ' WHERE id=?', (status, *fields.values(), oid));c.commit()

    def message(self, oid, channel='whatsapp', **body):
        got = self.post('/api/orders/%d/status-message' % oid, channel=channel, **body)
        self.assertEqual(got['status'], 200, got['body'])
        return got['body']

    def with_ai(self, oid, reply=BODY, **body):
        seen = {}

        def fake(system, user, long=False):
            seen['user'] = user
            return reply, 300, 60
        with patch.object(adi_ai, 'provider', lambda: 'openai'), patch.object(adi_ai, '_complete', fake):
            got = self.message(oid, **body)
        return got, seen.get('user', '')

    # ---- 1-6: estado financiero ------------------------------------------------------------------------------------------------------

    def test_no_payments_reports_exact_balance(self):
        oid, _ = self.order(10500)
        got = self.message(oid)
        self.assertEqual((got['finance']['state'], got['finance']['balance']), ('pendiente', '$105,00'))
        self.assertTrue(got['options']['payment'])
        self.assertIn('Adicionalmente, le informamos que su orden registra un saldo pendiente de $105,00. Agradecemos su colaboración para completar el pago correspondiente antes del retiro de su equipo.', got['body'])
        self.assertNotIn('abonos', got['body'])

    def test_advance_and_partial_payments_are_discounted(self):
        oid, _ = self.order(10500)
        self.pay(oid, '40,00')
        got = self.message(oid)
        self.assertEqual((got['finance']['paid'], got['finance']['balance'], got['finance']['payments']), ('$40,00', '$65,00', 1))
        self.assertIn('considerando los abonos registrados por $40,00, su orden registra un saldo pendiente de $65,00', got['body'])
        self.pay(oid, '25,50')
        got = self.message(oid)
        self.assertEqual((got['finance']['paid'], got['finance']['balance'], got['finance']['payments'], got['finance']['state']), ('$65,50', '$39,50', 2, 'parcial'))
        self.assertIn('saldo pendiente de $39,50', got['body'])
        with app.connect() as c:  # los valores son exactamente los de la tarjeta financiera (única fuente)
            import equipment
            self.assertEqual(equipment.money(c, oid)['balance_cents'], 3950)

    def test_fully_paid_and_zero_charges_do_not_mention_money(self):
        oid, _ = self.order(10500)
        self.pay(oid, '105,00')
        got = self.message(oid)
        self.assertEqual((got['finance']['state'], got['options']['payment'], got['options']['payment_available'], got['payment_text']), ('pagado', False, False, ''))
        self.assertNotRegex(got['body'], r'(?i)saldo|pago|\$')
        self.assertIn('sin saldo pendiente', ' '.join(n['text'] for n in got['finance_notes']))
        # Forzar la opción no inventa un saldo.
        self.assertNotIn('saldo', self.message(oid, include_payment=True)['body'].lower())
        empty, _ = self.order(0, key='0002')
        got = self.message(empty)
        self.assertEqual((got['finance']['state'], got['finance']['balance_cents'], got['payment_text']), ('sin_cargos', 0, ''))
        self.assertNotRegex(got['body'], r'(?i)saldo|\$')

    def test_unverifiable_finance_never_states_amounts(self):
        oid, _ = self.order(10500)
        import equipment
        with patch.object(equipment, 'finance', side_effect=RuntimeError('fallo simulado')):
            got = self.message(oid)
        self.assertIsNone(got['finance']);self.assertFalse(got['options']['payment'])
        self.assertIn('No se pudo verificar el estado financiero de esta orden.', got['finance_notes'][0]['text'])
        self.assertNotRegex(got['body'], r'(?i)saldo|\$');self.assertIn('Estado actual', got['body'])

    def test_balance_change_after_generation_blocks_sending(self):
        oid, _ = self.order(10500)
        got = self.message(oid)
        verify = lambda **b: self.post('/api/orders/%d/status-message' % oid, action='verify', **b)['body']
        self.assertTrue(verify(fingerprint=got['finance']['fingerprint'], text=got['body'])['ok'])
        self.pay(oid, '50,00')
        stale = verify(fingerprint=got['finance']['fingerprint'], text=got['body'])
        self.assertFalse(stale['ok']);self.assertIn('cambió', stale['problems'][0]);self.assertEqual(stale['finance']['balance'], '$55,00')
        # Con la huella nueva pero el importe viejo en el texto, también se detiene.
        self.assertFalse(verify(fingerprint=stale['finance']['fingerprint'], text=got['body'])['ok'])
        fresh = self.message(oid)
        self.assertTrue(verify(fingerprint=fresh['finance']['fingerprint'], text=fresh['body'])['ok'])
        with app.connect() as c:  # generar y verificar no envía ni registra mensajes, ni toca pagos
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_messages WHERE order_id=?', (oid,)).fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_payments WHERE order_id=?', (oid,)).fetchone()[0], 1)

    def test_pending_transfer_is_not_included_by_default(self):
        oid, _ = self.order(10500)
        with app.connect() as c:
            account = c.execute("INSERT INTO bank_accounts(bank,account_type,number,holder,holder_id,created_at,updated_at) VALUES ('Banco Ficticio','ahorros','5555000033','TITULAR FICTICIO','0100000017','x','x')").lastrowid;c.commit()
        self.pay(oid, '30,00', method='transferencia', note='Comprobante ficticio', bank_account_id=str(account), reference='TRX-SF-0001')
        got = self.message(oid)
        self.assertEqual(got['finance']['pending_transfers'], 1);self.assertFalse(got['options']['payment']);self.assertNotIn('saldo pendiente', got['body'])
        self.assertIn('transferencia por confirmar', ' '.join(n['text'] for n in got['finance_notes']))
        self.assertIn('saldo pendiente de $75,00', self.message(oid, include_payment=True)['body'])

    def test_recent_payment_reminder_is_flagged(self):
        oid, _ = self.order(10500)
        with app.connect() as c:
            now = app.reception_now().isoformat(timespec='seconds')
            c.execute("INSERT INTO order_messages(order_id,channel,template,body,status,created_by,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?)", (oid, 'whatsapp', 'pago', 'Recordatorio ficticio', 'preparado', now, now));c.commit()
        got = self.message(oid)
        self.assertIn('recordatorio de pago', ' '.join(r['text'] for r in got['review']))

    # ---- 8-12: estado técnico y canales ---------------------------------------------------------------------------------------------

    def test_status_rules_reach_adi_and_money_never_does(self):
        oid, _ = self.order(10500)
        future = (app.reception_now().date() + timedelta(days=3)).isoformat()
        for status, rule in (('diagnostico', 'El diagnóstico está en curso'), ('reparacion', 'no digas que terminó'), ('pruebas', 'no digas que está listo'), ('listo', 'listo para retirar')):
            self.set_status(oid, status, findings='Ventilador obstruido (ficticio)', estimated_delivery=future, estimated_confirmed=1)
            got, prompt = self.with_ai(oid)
            self.assertEqual(got['source'], 'adi', status);self.assertIn(rule, prompt, status)
            self.assertNotIn('$', prompt, status);self.assertNotIn('105', prompt, status)
            self.assertIn('saldo pendiente de $105,00', got['body'], status)
            if status == 'listo':
                self.assertNotIn('Fecha estimada', prompt);self.assertFalse(got['options']['date_available'])
            else:
                self.assertIn('Fecha estimada confirmada', prompt, status);self.assertTrue(got['options']['date'])
        self.set_status(oid, 'reparacion')
        _, prompt = self.with_ai(oid, include_date=False)
        self.assertNotIn('Fecha estimada', prompt)
        _, prompt = self.with_ai(oid, tone='formal')
        self.assertIn('Tono formal', prompt)
        self.assertEqual(self.post('/api/orders/%d/status-message' % oid, channel='whatsapp', tone='grosero')['status'], 400)

    def test_whatsapp_and_email_formats(self):
        oid, order = self.order(10500)
        wa = self.message(oid, 'whatsapp');mail = self.message(oid, 'correo')
        self.assertTrue(wa['body'].startswith('Hola, '));self.assertIn('PC-DOCTOR | Servicio Técnico', wa['body'])
        self.assertTrue(mail['body'].startswith('Estimado/a '));self.assertIn('Orden de servicio: ' + order['code'], mail['body'])
        for got in (wa, mail):
            self.assertEqual(got['body'].count('saldo pendiente de $105,00'), 1)
        self.assertTrue(mail['subject'].startswith('PC-DOCTOR · Orden ' + order['code']))

    # ---- 13: anotaciones técnicas -----------------------------------------------------------------------------------------------------

    def test_internal_notes_stay_out_and_omissions_are_real(self):
        oid, _ = self.order(10500)
        self.set_status(oid, 'reparacion', findings='Pasta térmica seca (ficticio)')
        got = self.post('/api/orders/%d/followups' % oid, kind='reparacion', internal_note='Proveedor ficticio cobra caro, no comentar',
                        client_message='Limpiamos el ventilador del equipo.', client_visible='1')
        self.assertEqual(got['status'], 201, got['body'])
        msg, prompt = self.with_ai(oid, note='mencionar la limpieza')
        self.assertIn('Limpiamos el ventilador', prompt);self.assertNotIn('Proveedor ficticio', prompt)
        self.assertIn('1 nota interna', ' '.join(r['text'] for r in msg['review']))
        # Antes la tarea («Máximo 70 palabras») se tomaba por anotación y siempre aparecía como «omitida».
        self.assertFalse([w for w in msg['warnings'] if 'omitió' in w], msg['warnings'])
        msg, _ = self.with_ai(oid, note='indicar que la fuente entrega 19V')
        self.assertTrue([w for w in msg['warnings'] if 'omitió' in w and '19V' in w], msg['warnings'])

    def test_contradictions_and_missing_data_are_reported(self):
        oid, _ = self.order(10500)
        self.set_status(oid, 'reparacion', findings='')
        got = self.message(oid)
        self.assertIn('Falta el diagnóstico', ' '.join(r['text'] for r in got['review']))
        self.post('/api/orders/%d/followups' % oid, kind='finalizado', internal_note='Terminado (ficticio).', client_message='', client_visible='')
        self.set_status(oid, 'reparacion', findings='Disco dañado (ficticio)')
        got = self.message(oid)
        self.assertIn('servicio terminó', ' '.join(r['text'] for r in got['review']))
        with app.connect() as c:
            c.execute("INSERT INTO order_part_requests(order_id,name,stage,situation,created_by,created_at,updated_at) VALUES (?,?,?,?,1,?,?)",
                      (oid, 'Pantalla ficticia', 'transito', 'normal', app.reception_now().isoformat(), app.reception_now().isoformat()));c.commit()
        self.set_status(oid, 'listo')
        got = self.message(oid)
        self.assertIn('repuestos sin instalar', ' '.join(r['text'] for r in got['review']))

    def test_unsupported_work_claims_are_flagged(self):
        oid, _ = self.order(10500)
        self.set_status(oid, 'pruebas', findings='Batería degradada (ficticio)')
        got, _ = self.with_ai(oid, reply='Reemplazamos la batería y su equipo funciona correctamente.')
        self.assertTrue([w for w in got['warnings'] if 'reemplazamos' in w.lower()], got['warnings'])


class ReadyPhraseTests(unittest.TestCase):
    def test_future_ready_phrase_is_not_a_claim(self):
        import adi_order
        self.assertFalse(adi_order._says_ready('Le notificaremos cuando su equipo esté listo para retirar.'))
        self.assertFalse(adi_order._says_ready('Le avisaremos en cuanto el equipo esté listo para retirar.'))
        self.assertTrue(adi_order._says_ready('Su equipo está listo para retirar.'))
        self.assertTrue(adi_order._says_ready('Cuando pueda, venga: la reparación ha finalizado.'))


if __name__ == '__main__':
    unittest.main()
