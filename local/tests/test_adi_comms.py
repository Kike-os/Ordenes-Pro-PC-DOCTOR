"""ADI Enterprise AI 3.0 · fase 1: análisis integral, mensajes por motivo, control previo al envío y retrasos. Datos ficticios, base temporal,
IA simulada y WhatsApp sin credenciales: nada se envía, no se registran pagos ficticios en producción ni se cambia ningún saldo real."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import test_adi_followup as follow  # prepara la ruta de importación y la base temporal
import adi_ai
import adi_comms
import app
import whatsapp_business as wa
from reception import ECUADOR_TZ

TUESDAY = datetime(2026, 11, 24, 10, 0, tzinfo=ECUADOR_TZ)


class AdiCommsTests(unittest.TestCase):
    Base = follow.SmartFollowUpTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link
    order, fresh, pay, set_status = Base.order, Base.fresh, Base.pay, Base.set_status

    def comms(self, oid, action, expect=200, **body):
        got = self.post('/api/orders/%d/adi-comms' % oid, action=action, **body)
        self.assertEqual(got['status'], expect, got['body'])
        return got['body']

    def consent(self, oid):
        with app.connect() as c:
            phone = c.execute('SELECT cl.phone FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?', (oid,)).fetchone()[0]
            wa.record_consent(c, phone, 'aceptado', 'presencial', app.reception_now())
            c.commit()

    def check(self, oid, purpose, channel='correo', text='', now=TUESDAY, fp=''):
        with app.connect() as c:
            return {i['key']: i for i in adi_comms.precheck(c, oid, purpose, channel, text, fp, now)['items']}

    # ---- Análisis integral -----------------------------------------------------------------------------------------------------------

    def test_analysis_filters_private_data_and_lists_real_values(self):
        oid, _ = self.order(10500)
        with app.connect() as c:
            c.execute("INSERT INTO order_followups(order_id,kind,internal_note,client_message,created_at) VALUES (?,?,?,?,?)",
                      (oid, 'diagnostico', 'Costo de compra 40 USD, margen alto, clave del cliente 1234', 'Se revisó la placa.', app.reception_now().isoformat()))
            c.commit()
        got = self.comms(oid, 'analysis')
        flat = repr(got['sections'])
        self.assertNotIn('Costo de compra', flat)
        self.assertNotIn('1234', flat)
        self.assertIn('notas internas (1 omitidas)', got['excluded'])
        money = {r['label']: r['value'] for s in got['sections'] if s['key'] == 'dinero' for r in s['rows']}
        self.assertEqual(money['Saldo pendiente'], '$105,00')
        self.assertEqual(money['Vencimientos'], 'Sin fecha de vencimiento registrada')
        self.assertNotIn('0991234567', flat)                                         # celular enmascarado
        purposes = {p['key']: p for p in got['purposes']}
        self.assertTrue(purposes['pago_pendiente']['available'])
        self.assertFalse(purposes['aviso_intereses']['available'])
        self.assertFalse(purposes['compromiso_pago']['available'])
        self.assertFalse(purposes['listo_entrega']['available'])

    def test_client_without_debt_has_no_payment_purpose(self):
        oid, _ = self.order(10500)
        self.pay(oid, '105,00')
        purposes = {p['key']: p for p in self.comms(oid, 'analysis')['purposes']}
        self.assertFalse(purposes['pago_pendiente']['available'])
        self.assertTrue(purposes['confirmacion_pago']['available'])
        got = self.comms(oid, 'compose', purpose='confirmacion_pago', channel='correo', ai='0')
        self.assertIn('El saldo de su orden está cubierto.', got['body'])

    # ---- Mensajes por motivo ---------------------------------------------------------------------------------------------------------

    def test_payment_message_is_discreet_without_whatsapp_consent(self):
        oid, _ = self.order(10500)
        got = self.comms(oid, 'compose', purpose='pago_pendiente', channel='whatsapp', ai='0')
        self.assertTrue(got['discreet'])
        self.assertNotIn('$', got['body'])
        self.assertNotIn('Seguimiento:', got['body'])
        self.consent(oid)
        got = self.comms(oid, 'compose', purpose='pago_pendiente', channel='whatsapp', ai='0')
        self.assertFalse(got['discreet'])
        self.assertIn('saldo pendiente de $105,00', got['body'])

    def test_partial_and_cash_payments_give_exact_balance_without_interest(self):
        oid, _ = self.order(10500)
        self.pay(oid, '40,00', method='efectivo')
        got = self.comms(oid, 'compose', purpose='pago_pendiente', channel='correo', ai='0')
        self.assertIn('$65,00', got['body'])
        self.assertNotRegex(got['body'].lower(), 'inter[eé]s|mora|recargo')

    def test_pending_transfer_is_clarified_and_blocks_a_plain_debt_claim(self):
        oid, _ = self.order(10500)
        with app.connect() as c:
            account = c.execute("INSERT INTO bank_accounts(bank,account_type,number,holder,holder_id,created_at,updated_at) VALUES ('Banco Ficticio','ahorros','5555000033','TITULAR FICTICIO','0100000017','x','x')").lastrowid;c.commit()
        self.pay(oid, '50,00', method='transferencia', note='Comprobante ficticio', bank_account_id=str(account), reference='TRX-ADI-0001')
        got = self.comms(oid, 'compose', purpose='pago_pendiente', channel='correo', ai='0')
        self.assertIn('conciliación', got['body'])
        items = self.check(oid, 'pago_pendiente', text='Su orden registra un saldo pendiente de $105,00.', fp=got['fingerprint'])
        self.assertEqual(items['pagos']['level'], 'block')

    def test_interest_and_later_phases_are_never_composed(self):
        oid, _ = self.order(10500)
        for purpose in ('aviso_intereses', 'compromiso_pago', 'estado_cuenta'):
            self.comms(oid, 'compose', 409, purpose=purpose, channel='correo', ai='0')

    def test_ai_cannot_add_amounts_or_unregistered_claims(self):
        oid, _ = self.order(0)
        seen = {}

        def fake(system, user, long=False):
            seen['user'] = user
            return 'Su equipo ya fue reparado y el costo es $50.', 300, 60
        with patch.object(adi_ai, 'provider', lambda: 'openai'), patch.object(adi_ai, '_complete', fake), patch.object(adi_ai, 'enabled', lambda c: True):
            got = self.comms(oid, 'compose', purpose='recepcion', channel='whatsapp')
        self.assertNotIn('$50', got['body'])
        self.assertIn('Confirmamos la recepción', got['body'])
        self.assertEqual(got['source'], 'sistema')
        self.assertNotIn('$', seen.get('user', ''))

    # ---- Control previo al envío -----------------------------------------------------------------------------------------------------

    def test_collection_schedule_weekends_holidays_and_hours(self):
        oid, _ = self.order(10500)
        self.assertEqual(self.check(oid, 'pago_pendiente')['horario']['level'], 'ok')
        self.assertEqual(self.check(oid, 'pago_pendiente', now=TUESDAY.replace(day=28))['horario']['level'], 'block')        # sábado
        self.assertEqual(self.check(oid, 'pago_pendiente', now=datetime(2026, 12, 25, 10, tzinfo=ECUADOR_TZ))['horario']['level'], 'block')  # Navidad
        self.assertEqual(self.check(oid, 'pago_pendiente', now=TUESDAY.replace(hour=19))['horario']['level'], 'block')
        self.assertEqual(self.check(oid, 'pago_pendiente', now=TUESDAY.replace(hour=7, minute=59))['horario']['level'], 'block')
        self.assertEqual(self.check(oid, 'recepcion', now=TUESDAY.replace(day=28))['horario']['level'], 'warn')             # servicio: solo aviso

    def test_duplicates_and_one_collection_per_day(self):
        oid, _ = self.order(10500)
        now = app.reception_now()
        got = self.comms(oid, 'compose', purpose='recepcion', channel='correo', ai='0')
        self.comms(oid, 'record', purpose='recepcion', channel='correo', text=got['body'], fingerprint=got['fingerprint'])
        self.assertEqual(self.check(oid, 'recepcion', now=now)['duplicado']['level'], 'block')
        with app.connect() as c:
            app.audit(c, self.uid, 'adi_msg:pago_pendiente', oid);c.commit()
        self.assertEqual(self.check(oid, 'pago_pendiente', now=now)['consentimiento']['level'], 'block')

    def test_privacy_blocks_credentials_and_identification(self):
        oid, _ = self.order(0)
        self.assertEqual(self.check(oid, 'recepcion', text='Su contraseña es 1234.')['privacidad']['level'], 'block')
        self.assertEqual(self.check(oid, 'recepcion', text='Cliente con cédula 0100000017.')['privacidad']['level'], 'block')
        self.assertEqual(self.check(oid, 'recepcion', text='Confirmamos la recepción de su equipo.')['privacidad']['level'], 'ok')

    def test_amount_changed_after_composing_blocks(self):
        oid, _ = self.order(10500)
        got = self.comms(oid, 'compose', purpose='pago_pendiente', channel='correo', ai='0')
        self.pay(oid, '5,00')
        self.comms(oid, 'record', 409, purpose='pago_pendiente', channel='correo', text=got['body'], fingerprint=got['fingerprint'])

    def test_whatsapp_without_configuration_or_wrong_phone_blocks(self):
        oid, _ = self.order(0)
        items = self.check(oid, 'recepcion', channel='whatsapp')
        self.assertEqual(items['whatsapp']['level'], 'block')                       # sin credenciales de Meta en las pruebas
        with app.connect() as c:
            c.execute("UPDATE clients SET phone='022345678' WHERE id=(SELECT d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?)", (oid,));c.commit()
        self.assertEqual(self.check(oid, 'recepcion', channel='whatsapp')['destinatario']['level'], 'block')

    # ---- Retrasos ---------------------------------------------------------------------------------------------------------------------

    def test_delay_attributable_to_pc_doctor_is_acknowledged_and_registered(self):
        oid, _ = self.order(0)
        past = (app.reception_now() - timedelta(days=5)).date().isoformat()
        self.set_status(oid, 'reparacion', estimated_delivery=past, estimated_confirmed=1)
        got = self.comms(oid, 'analysis')
        self.assertTrue(got['delays'][0]['attributable'])
        msg = self.comms(oid, 'compose', purpose='retraso_reparacion', channel='correo', ai='0')
        self.assertIn('Le ofrecemos una disculpa', msg['body'])
        self.assertIn('una persona de nuestro equipo', msg['body'])
        noted = self.comms(oid, 'delay')
        self.assertTrue(noted['noted'])
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM pending_notes WHERE key LIKE ? AND kind='nota'", ('pending:orders:%d:%%' % oid,)).fetchone()[0], 1)

    def test_delay_waiting_for_client_is_not_attributed(self):
        oid, _ = self.order(0)
        past = (app.reception_now() - timedelta(days=5)).date().isoformat()
        self.set_status(oid, 'esperando_cliente', estimated_delivery=past, estimated_confirmed=1)
        got = self.comms(oid, 'analysis')
        self.assertFalse(got['delays'][0]['attributable'])
        self.comms(oid, 'compose', 409, purpose='retraso_reparacion', channel='correo', ai='0')
        self.comms(oid, 'delay', 409)

    def test_nothing_is_sent_or_changed(self):
        oid, _ = self.order(10500)
        with app.connect() as c:
            before = c.execute('SELECT (SELECT COUNT(*) FROM order_messages),(SELECT COUNT(*) FROM order_payments),(SELECT status FROM orders WHERE id=?)', (oid,)).fetchone()
        got = self.comms(oid, 'compose', purpose='pago_pendiente', channel='correo', ai='0')
        self.comms(oid, 'precheck', purpose='pago_pendiente', channel='correo', text=got['body'], fingerprint=got['fingerprint'])
        with app.connect() as c:
            self.assertEqual(tuple(c.execute('SELECT (SELECT COUNT(*) FROM order_messages),(SELECT COUNT(*) FROM order_payments),(SELECT status FROM orders WHERE id=?)', (oid,)).fetchone()), tuple(before))


if __name__ == '__main__':
    unittest.main()
