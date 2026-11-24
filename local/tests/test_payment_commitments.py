"""ADI 3.0 · fase 2: compromisos de pago. Base temporal, datos ficticios y WhatsApp sin credenciales: no se envía nada, no se registran pagos
desde el compromiso y no cambia ningún saldo. Los pagos de las pruebas son ficticios y solo existen en la base temporal."""
import unittest
from datetime import timedelta

import test_adi_comms as comms  # prepara la ruta de importación y la base temporal
import adi_comms
import app
import payment_commitments as pc


class PaymentCommitmentTests(unittest.TestCase):
    Base = comms.AdiCommsTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link
    order, fresh, pay, set_status, comms, check = Base.order, Base.fresh, Base.pay, Base.set_status, Base.comms, Base.check

    def commit(self, oid, expect=200, **body):
        data = dict({'action': 'create', 'amount': '105,00', 'due_date': (app.reception_now() + timedelta(days=10)).date().isoformat(),
                     'method': 'efectivo', 'evidence_source': 'telefono', 'evidence': 'El cliente confirmó por llamada que pagará el saldo.'}, **body)
        got = self.post('/api/orders/%d/commitments' % oid, **data)
        self.assertEqual(got['status'], expect, got['body'])
        return got['body']

    def move_due(self, cid, days):
        with app.connect() as c:
            c.execute('UPDATE payment_commitments SET due_date=? WHERE id=?', ((app.reception_now() + timedelta(days=days)).date().isoformat(), cid));c.commit()

    def snapshot(self, oid):
        with app.connect() as c:
            return tuple(c.execute('SELECT (SELECT COUNT(*) FROM order_payments),(SELECT COUNT(*) FROM order_messages),(SELECT status FROM orders WHERE id=?)', (oid,)).fetchone())

    def test_register_requires_balance_evidence_and_valid_values(self):
        oid, _ = self.order(10500)
        self.commit(oid, 400, evidence='')
        self.commit(oid, 400, amount='200,00')
        self.commit(oid, 400, due_date=(app.reception_now() - timedelta(days=1)).date().isoformat())
        self.commit(oid, 400, evidence_source='')
        before = self.snapshot(oid)
        got = self.commit(oid)
        self.assertEqual((got['current']['state'], got['current']['amount']), ('pendiente', '$105,00'))
        self.assertEqual(self.snapshot(oid), before)                      # no registra pagos ni mensajes ni cambia la orden
        self.commit(oid, 409)                                             # un solo compromiso vigente
        paid, _ = self.order(0)
        self.commit(paid, 409)                                            # sin saldo no corresponde

    def test_long_term_needs_administration(self):
        oid, _ = self.order(10500)
        far = (app.reception_now() + timedelta(days=45)).date().isoformat()
        with app.connect() as c:
            with self.assertRaises(pc.CommitmentError) as raised:
                pc.act(c, oid, {'id': self.uid, 'role': 'tecnico'}, {'action': 'create', 'amount': '50,00', 'due_date': far, 'evidence_source': 'presencial',
                                                                     'evidence': 'Acuerdo en recepción con el cliente.'}, app.reception_now(), app.audit)
            self.assertEqual(raised.exception.status, 403)
        got = self.commit(oid, due_date=far)                              # administración sí
        self.assertTrue(got['current']['approved'])

    def test_states_follow_real_payments(self):
        oid, _ = self.order(10500)
        cid = self.commit(oid, amount='60,00')['current']['id']
        self.move_due(cid, 2)
        self.assertEqual(self.comms(oid, 'analysis')['commitments']['current']['state'], 'proximo')
        self.move_due(cid, -1)
        self.assertEqual(self.comms(oid, 'analysis')['commitments']['current']['state'], 'incumplido')
        self.pay(oid, '20,00')
        cur = self.comms(oid, 'analysis')['commitments']['current']
        self.assertEqual((cur['state'], cur['paid_since']), ('parcial', '$20,00'))
        self.pay(oid, '40,00', method='efectivo')
        self.assertEqual(self.comms(oid, 'analysis')['commitments']['current']['state'], 'cumplido')

    def test_pending_transfer_after_due_is_review_not_breach(self):
        oid, _ = self.order(10500)
        cid = self.commit(oid)['current']['id']
        with app.connect() as c:
            account = c.execute("INSERT INTO bank_accounts(bank,account_type,number,holder,holder_id,created_at,updated_at) VALUES ('Banco Ficticio','ahorros','5555000044','TITULAR FICTICIO','0100000017','x','x')").lastrowid;c.commit()
        self.pay(oid, '105,00', method='transferencia', note='Comprobante ficticio', bank_account_id=str(account), reference='TRX-CMP-0001')
        self.move_due(cid, -3)
        self.assertEqual(self.comms(oid, 'analysis')['commitments']['current']['state'], 'en_revision')
        purposes = {p['key']: p for p in self.comms(oid, 'analysis')['purposes']}
        self.assertFalse(purposes['compromiso_incumplido']['available'])

    def test_reschedule_cancel_and_review(self):
        oid, _ = self.order(10500)
        cid = self.commit(oid)['current']['id']
        self.commit(oid, 400, action='reschedule', id=str(cid), evidence='')                       # exige evidencia
        got = self.commit(oid, action='reschedule', id=str(cid), amount='105,00', due_date=(app.reception_now() + timedelta(days=20)).date().isoformat(),
                          evidence='El cliente pidió por WhatsApp pasar el pago a fin de mes.', evidence_source='whatsapp')
        states = {i['id']: i['state'] for i in got['items']}
        self.assertEqual(states[cid], 'reprogramado')
        new = got['current']['id']
        self.assertEqual(got['current']['replaces_id'], cid)
        got = self.commit(oid, action='review', id=str(new), reason='El cliente indica que el importe no coincide con lo acordado.')
        self.assertEqual(got['current']['state'], 'en_revision')
        with app.connect() as c:
            with self.assertRaises(pc.CommitmentError):
                pc.act(c, oid, {'id': self.uid, 'role': 'tecnico'}, {'action': 'cancel', 'id': new, 'reason': 'Motivo suficientemente largo.'}, app.reception_now(), app.audit)
        got = self.commit(oid, action='cancel', id=str(new), reason='Administración acordó otra forma con el cliente.')
        self.assertIsNone(got['current'])
        with app.connect() as c:
            kinds = [r[0] for r in c.execute('SELECT kind FROM payment_commitment_events ORDER BY id')]
        self.assertEqual(kinds, ['registrado', 'reprogramado', 'registrado', 'en_revision', 'cancelado'])

    def test_adi_messages_and_reminders_respect_the_agreement(self):
        oid, _ = self.order(10500)
        self.commit(oid, amount='105,00')
        purposes = {p['key']: p for p in self.comms(oid, 'analysis')['purposes']}
        self.assertTrue(purposes['compromiso_pago']['available'])
        self.assertFalse(purposes['compromiso_incumplido']['available'])
        got = self.comms(oid, 'compose', purpose='compromiso_pago', channel='correo', ai='0')
        self.assertIn('Confirmamos el compromiso de pago registrado: $105,00 hasta el', got['body'])
        self.assertEqual(self.check(oid, 'pago_pendiente')['consentimiento']['level'], 'block')   # acuerdo vigente: sin recordatorio de saldo
        with app.connect() as c:
            c.execute("UPDATE payment_commitments SET due_date=?", ((app.reception_now() - timedelta(days=2)).date().isoformat(),));c.commit()
        got = self.comms(oid, 'compose', purpose='compromiso_incumplido', channel='correo', ai='0')
        self.assertIn('Todavía no consta el pago.', got['body'])
        self.assertNotRegex(got['body'].lower(), 'inter[eé]s|mora|recargo|demanda|moros')
        wa = self.comms(oid, 'compose', purpose='compromiso_incumplido', channel='whatsapp', ai='0')
        self.assertTrue(wa['discreet'])
        self.assertNotIn('$', wa['body'])

    def test_without_migration_the_module_is_inactive(self):
        oid, _ = self.order(10500)
        with app.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DROP TABLE payment_commitment_events')
            c.execute('DROP TABLE payment_commitments')
            try:
                self.assertFalse(pc.for_order(c, oid, app.reception_now().date())['installed'])
                with self.assertRaises(pc.CommitmentError) as raised:
                    pc.act(c, oid, {'id': self.uid, 'role': 'administrador'}, {'action': 'create'}, app.reception_now(), app.audit)
                self.assertEqual(raised.exception.status, 409)
                ctx = __import__('adi_order').context(c, oid)
                self.assertFalse({p['key']: p for p in adi_comms.purposes(c, oid, ctx, None, app.reception_now())}['compromiso_pago']['available'])
            finally:
                c.rollback()


if __name__ == '__main__':
    unittest.main()
