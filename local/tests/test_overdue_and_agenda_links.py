"""Entrega vencida: un equipo en espera de entrega (cliente ya avisado; rige el plazo de permanencia) no cuenta como atrasado; una reparación en curso
con la fecha pasada sí. Enlaces de la agenda que envía ADI: dominio real, WhatsApp legible y «facebook» no activa horarios.
Base temporal y datos ficticios; no se envía nada."""
import unittest

import test_invoicing
import app
import adi


class OverdueDeliveryTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure

    def overdue_titles(self, cookie):
        return [i['title'] for i in self.request('/api/notifications', cookie=cookie)['body']['items'] if i['key'].startswith('alert:overdue:')]

    def test_orders_waiting_for_pickup_are_not_overdue(self):
        cookie, csrf, post, order = self.paid_order(1000, key='overdue-1')
        oid = order['id']
        with app.connect() as c:
            c.execute("UPDATE orders SET status='espera_entrega',estimated_delivery='2020-01-10' WHERE id=?", (oid,));c.commit()
        self.assertEqual(self.overdue_titles(cookie), [])
        rows = {r['id']: r for r in self.request('/api/deliveries', cookie=cookie)['body']['rows']}
        self.assertEqual(rows[oid]['delivery'], 'pickup')
        with app.connect() as c:
            c.execute("UPDATE orders SET status='listo' WHERE id=?", (oid,));c.commit()
        self.assertEqual(self.overdue_titles(cookie), ['1 orden con entrega vencida'])        # lista pero sin avisar ni entregar: sigue atrasada
        with app.connect() as c:
            c.execute("UPDATE orders SET status='reparacion' WHERE id=?", (oid,));c.commit()
        self.assertEqual(self.overdue_titles(cookie), ['1 orden con entrega vencida'])        # en curso y con la fecha pasada: sí está atrasada


class AgendaLinkTests(unittest.TestCase):
    def setUp(self):
        self.saved = adi.agenda_url
        adi.agenda_url = lambda: 'https://ordenes.example.test/citas'

    def tearDown(self):
        adi.agenda_url = self.saved

    def test_links_use_the_real_address_and_whatsapp_is_readable(self):
        text = ('Reserva en https://pcdoctor.invalid/citas o en /citas.\n/citas?fecha=2026-11-26&hora=14:30&servicio=diagnostico\n'
                'Otro enlace https://social.example/pcdoctor/citas-x')
        web = adi.agenda_links(text, 'web')
        self.assertNotIn('pcdoctor.invalid', web)
        self.assertIn('https://ordenes.example.test/citas?fecha=2026-11-26&hora=14:30&servicio=diagnostico', web)
        self.assertIn('https://social.example/pcdoctor/citas-x', web)                              # enlaces ajenos intactos
        wa = adi.agenda_links(text, 'whatsapp')
        self.assertIn('• Reservar Jueves 26/11 · 2:30 p. m.\n  https://ordenes.example.test/citas?fecha=2026-11-26', wa)

    def test_generated_booking_link_uses_the_public_portal(self):
        adi.agenda_url = self.saved
        self.assertEqual(
            adi.booking_link('2026-11-26', '14:30', 'diagnostico'),
            'https://ordenes-pro.ecuadorpcdoctor.com/citas?fecha=2026-11-26&hora=14:30&servicio=diagnostico',
        )

    def test_only_whole_words_ask_for_slots(self):
        self.assertFalse(adi.wants_slots('https://www.facebook.com/share/p/abc'))
        self.assertFalse(adi.wants_slots('Vi su página de Facebook'))
        for text in ('Quiero agendar una cita', '¿Tienen disponibilidad mañana?', 'I want to book an appointment'):
            self.assertTrue(adi.wants_slots(text), text)


if __name__ == '__main__':
    unittest.main()
