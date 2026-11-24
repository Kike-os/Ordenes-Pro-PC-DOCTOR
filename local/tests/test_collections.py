"""ADI 3.0 · fases 4 y 5: cartera, expediente, marcas, estados de cuenta, retiros, auditoría y propuestas. Base temporal y datos
ficticios: nada se envía, no se registran pagos desde la cartera y no cambia ningún saldo."""
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import test_interest_engine as interest  # prepara la ruta de importación y la base temporal
import adi_comms
import app
import collections_center as cc

def insert(c, table, **values):
    """Inserta una fila ficticia rellenando las columnas obligatorias sin valor por defecto."""
    now = app.reception_now().isoformat(timespec='seconds')
    for _, name, kind, notnull, default, pk in c.execute('PRAGMA table_info(%s)' % table).fetchall():
        if notnull and default is None and not pk and name not in values:
            values[name] = now if name.endswith('_at') else 0 if 'INT' in (kind or '').upper() else 'prueba'
    c.execute('INSERT INTO %s(%s) VALUES (%s)' % (table, ','.join(values), ','.join('?' * len(values))), tuple(values.values()))


class CollectionsTests(unittest.TestCase):
    Base = interest.InterestRouteTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure, part, link = Base.form, Base.prepare, Base.paid_order, Base.configure, Base.part, Base.link
    order, fresh, pay, set_status, comms, check, commit, move_due, rates, add = (Base.order, Base.fresh, Base.pay, Base.set_status, Base.comms, Base.check, Base.commit,
                                                                                Base.move_due, Base.rates, Base.add)

    def get(self, path, expect=200):
        got = self.request(path, cookie=self.cookie)
        self.assertEqual(got['status'], expect, got['body'] if isinstance(got['body'], dict) else '')
        return got['body']

    def setup_order(self, cents=10500):
        oid, order = self.order(cents)
        self.cookie = self.login()[0]
        with app.connect() as c:
            client = c.execute('SELECT d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?', (oid,)).fetchone()[0]
        return oid, client

    def deliver(self, oid, days_ago):
        when = (app.reception_now() - timedelta(days=days_ago)).isoformat(timespec='seconds')
        self.set_status(oid, 'entregado', delivered_at=when)

    def snapshot(self):
        with app.connect() as c:
            return tuple(c.execute('SELECT (SELECT COUNT(*) FROM order_payments),(SELECT COALESCE(SUM(amount_cents),0) FROM order_payments),(SELECT COUNT(*) FROM order_messages),'
                                   '(SELECT COUNT(*) FROM invoices)').fetchone())

    def test_portfolio_single_source_and_aging(self):
        oid, client = self.setup_order(10500)
        self.pay(oid, '40,00')
        got = self.get('/api/collections')
        item = next(i for i in got['items'] if i['order_id'] == oid)
        self.assertEqual((item['balance_cents'], item['state'], item['age']), (6500, 'por_vencer', 'por_vencer'))   # en el taller: por vencer
        self.deliver(oid, 40)
        item = next(i for i in self.get('/api/collections')['items'] if i['order_id'] == oid)
        self.assertEqual((item['state'], item['due_basis'], item['age']), ('vencida', 'Entrega del equipo', '31_60'))
        kpis = self.get('/api/collections')['kpis']
        self.assertEqual((kpis['overdue_cents'], kpis['authorized_interest_cents']), (6500, 0))
        self.assertEqual(self.get('/api/collections?age=mas_90')['total'], 0)
        self.assertEqual(self.get('/api/collections?client=ficticio')['total'], 1)

    def test_commitment_defines_due_and_simulated_interest_is_separate(self):
        oid, client = self.setup_order(15000)
        cid = self.commit(oid, amount='150,00')['current']['id']
        rid = self.add()['rates'][0]['id']
        self.rates(action='validate', id=str(rid), note='Validada contra la tabla oficial (prueba ficticia).')
        with app.connect() as c:
            c.execute('UPDATE payment_commitments SET due_date=? WHERE id=?', ((app.reception_now() - timedelta(days=120)).date().isoformat(), cid));c.commit()
        item = next(i for i in self.get('/api/collections')['items'] if i['order_id'] == oid)
        self.assertEqual((item['due_basis'], item['days_overdue'], item['simulated_interest_cents']), ('Compromiso de pago', 120, 85))
        self.assertEqual(item['balance_cents'], 15000)                                  # el interés simulado nunca suma al saldo

    def test_flags_suspend_collection_and_need_reason(self):
        oid, client = self.setup_order(10500)
        post = lambda **b: self.request('/api/collections/client/%d' % client, b, cookie=self.cookie, csrf=self.login()[1] if False else self.csrf_for())
        self.assertEqual(self.flag(client, action='suspension', reason='corto')['status'], 400)
        until = (app.reception_now() + timedelta(days=10)).date().isoformat()
        got = self.flag(client, action='suspension', reason='El cliente pidió esperar a su pago de nómina.', until=until)
        self.assertEqual(got['status'], 200, got['body'])
        self.assertIn('suspendidos', got['body']['suspended'])
        self.assertEqual(self.check(oid, 'pago_pendiente')['consentimiento']['level'], 'block')
        fid = got['body']['flags'][0]['id']
        got = self.flag(client, action='close', id=str(fid), reason='El cliente ya está al día.')
        self.assertEqual(got['body']['suspended'], '')

    def csrf_for(self):
        return self.session[1]

    def flag(self, client, **body):
        if not getattr(self, 'session', None):
            self.session = self.login()
        return self.request('/api/collections/client/%d' % client, body, cookie=self.session[0], csrf=self.session[1])

    def test_client_file_and_statement_pdfs(self):
        oid, client = self.setup_order(10500)
        self.pay(oid, '40,00')
        self.deliver(oid, 10)
        before = self.snapshot()
        f = self.get('/api/collections/client/%d' % client)
        self.assertEqual(f['portfolio']['kpis']['capital_cents'], 6500)
        self.assertNotIn('0991234567', repr(f))
        for fmt in ('a4', '80'):
            got = self.request('/api/collections/statement/%d.pdf?format=%s' % (client, fmt), cookie=self.cookie)
            self.assertEqual(got['status'], 200)
            if shutil.which('pdftotext'):
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / 's.pdf'
                    path.write_bytes(got['raw'] if 'raw' in got else got['body'])
                    txt = subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True).stdout
                self.assertIn('no es una factura', txt)
                self.assertIn('$65,00', txt)
                self.assertIn('Intereses autorizados', txt)
                self.assertNotIn('SIMULACIÓN', txt)
        self.assertEqual(self.snapshot(), before)

    def test_pickups_alerts_and_never_disposal(self):
        oid, client = self.setup_order(10500)
        self.set_status(oid, 'listo')
        with app.connect() as c:
            insert(c, 'order_status_log', order_id=oid, from_status='reparacion', to_status='listo', created_at=app.reception_now().isoformat());c.commit()
        later = app.reception_now() + timedelta(days=95)                      # el registro de estados es inmutable: se evalúa en el futuro
        with app.connect() as c:
            got = cc.pickups(c, later)
            props = cc.proposals(c, later)
        item = next(i for i in got['items'] if i['order_id'] == oid)
        self.assertEqual((item['alert'], item['days']), (90, 95))
        self.assertIn('no se dispone del equipo', item['alert_label'])
        self.assertFalse(props['automatic'])
        self.assertTrue(any(p['kind'] == 'retiro' and p['order_id'] == oid and p['review'] for p in props['items']))
        self.assertEqual(self.get('/api/collections/pickups')['items'][0]['alert'], 0)    # hoy recién quedó listo

    def test_proposals_milestones_and_blockers(self):
        oid, client = self.setup_order(10500)
        self.deliver(oid, 16)
        props = [p for p in self.get('/api/collections/proposals')['items'] if p['order_id'] == oid]
        self.assertEqual((props[0]['event'], props[0]['purpose'], props[0]['ready']), ('15 días de retraso', 'pago_pendiente', True))
        with app.connect() as c:
            insert(c, 'order_messages', order_id=oid, channel='whatsapp', template='pago', body='texto ficticio', status='enviado', created_at=app.reception_now().isoformat(timespec='seconds'));c.commit()
        props = [p for p in self.get('/api/collections/proposals')['items'] if p['order_id'] == oid]
        self.assertFalse(props[0]['ready'])
        self.assertIn('Gestión reciente', ' '.join(props[0]['blocked']))
        self.pay(oid, '105,00')
        self.assertFalse([p for p in self.get('/api/collections/proposals')['items'] if p['order_id'] == oid])   # saldo cancelado: se detiene

    def test_comms_audit_records_motive_reply_and_result(self):
        oid, client = self.setup_order(10500)
        got = self.comms(oid, 'compose', purpose='pago_pendiente', channel='correo', ai='0')
        with app.connect() as c:
            app.audit(c, self.uid, 'adi_msg:pago_pendiente', oid)
            insert(c, 'order_messages', order_id=oid, channel='correo', template='pago', body=got['body'], status='enviado', created_at=app.reception_now().isoformat(timespec='seconds'));c.commit()
        self.pay(oid, '20,00')
        row = next(i for i in self.get('/api/collections/audit')['items'] if i['order_id'] == oid)
        self.assertEqual((row['motive'], row['result']), ('Pago pendiente', 'Pago registrado'))

    def test_only_administration(self):
        oid, client = self.setup_order(0)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.request('/api/collections', cookie=self.cookie)['status'], 403)


if __name__ == '__main__':
    unittest.main()
