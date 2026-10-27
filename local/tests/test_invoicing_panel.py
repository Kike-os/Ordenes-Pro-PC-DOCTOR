"""Panel general de Facturación: indicadores separados por ambiente (pruebas y producción), facturación mensual solo con datos,
actividad reciente y documentos que requieren atención. Solo lectura. Base temporal y datos ficticios."""
import unittest

import app
import test_invoicing


class InvoicingPanelTests(unittest.TestCase):
    # Ayudas de las pruebas de facturación como atributos de clase (un alias a nivel de módulo volvería a ejecutar esas pruebas).
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure

    def test_dashboard_separates_test_documents_and_only_counts_what_is_registered(self):
        self.assertEqual(self.request('/api/invoicing/dashboard')['status'], 401)
        cookie, csrf, post, order = self.paid_order(14535)
        empty = self.request('/api/invoicing/dashboard', cookie=cookie)['body']
        self.assertFalse(empty['has_monthly']);self.assertEqual(len(empty['monthly']), 12)
        self.assertEqual((empty['recent'], empty['attention'], empty['environments']['1']['documents'], empty['environments']['2']['documents']), ([], [], 0, 0))
        self.assertTrue(empty['settings']['test_mode'])
        draft = post('/api/invoicing/draft', kind='orden', id=str(order['id']))['body']['invoice']
        d = self.request('/api/invoicing/dashboard', cookie=cookie)['body']
        self.assertEqual([(a['id'], a['status']) for a in d['attention']], [(draft['id'], 'borrador')])
        self.assertEqual(d['summary']['drafts'], 1);self.assertFalse(d['has_monthly'])  # un borrador no es facturación
        self.assertEqual([r['label'] for r in d['recent']], ['Borrador creado'])
        self.configure(post)
        self.assertEqual(post('/api/invoicing/%d' % draft['id'], action='emit', confirm='1')['status'], 200)
        d = self.request('/api/invoicing/dashboard', cookie=cookie)['body']
        self.assertTrue(d['has_monthly'])
        self.assertEqual((d['monthly'][-1]['test_cents'], d['monthly'][-1]['real_cents'], sum(m['test_cents'] for m in d['monthly'][:-1])), (14535, 0, 0))
        self.assertEqual((d['environments']['1']['documents'], d['environments']['1']['billed_cents'], d['environments']['2']['documents'], d['environments']['2']['billed_cents']), (1, 14535, 0, 0))
        self.assertEqual((d['summary']['emitted'], d['summary']['to_send'], d['summary']['authorized']), (1, 1, 0))
        self.assertEqual(d['attention'][0]['status'], 'pendiente');self.assertIn('pendiente de firma', d['attention'][0]['reason'])
        self.assertEqual(d['recent'][0]['label'], 'Emitida en pruebas')
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.request('/api/invoicing/dashboard', cookie=cookie)['status'], 403)


if __name__ == '__main__':
    unittest.main()
