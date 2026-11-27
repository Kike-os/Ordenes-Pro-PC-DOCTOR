"""Portal seguro del cliente: enlace de seguimiento activo + últimos 4 dígitos de la identificación, sesión de 15 minutos solo para esa
orden, intentos limitados, permisos por acción, descargas solo de lo propio, cierre del acceso, enlace revocado y nada modificado.
Base temporal y datos ficticios."""
import io
from datetime import timedelta
from unittest.mock import patch
import unittest
from email.message import Message
from urllib.parse import urlencode

import test_invoicing
import app
import order_tracking


class ClientPortalTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure

    def post_form(self, path, fields, cookie='', ip='127.0.0.1'):
        handler = object.__new__(app.Handler);handler.path = path;handler.client_address = (ip, 5555);handler.headers = Message();body = urlencode(fields).encode()
        handler.headers['Content-Type'] = 'application/x-www-form-urlencoded';handler.headers['Content-Length'] = str(len(body));handler.headers['Origin'] = 'http://127.0.0.1:8010'
        if cookie:
            handler.headers['Cookie'] = cookie
        handler.rfile = io.BytesIO(body);result = {}
        handler.reply = lambda status, content, content_type='application/json; charset=utf-8', cookie=None, filename=None: result.update(status=status, body=content, cookie=cookie, type=content_type)
        handler.do_POST();return result

    def get(self, path, cookie=''):
        handler = object.__new__(app.Handler);handler.path = path;handler.client_address = ('127.0.0.1', 5555);handler.headers = Message()
        if cookie:
            handler.headers['Cookie'] = cookie
        result = {}
        handler.reply = lambda status, content, content_type='application/json; charset=utf-8', cookie=None, filename=None: result.update(status=status, body=content, type=content_type)
        handler.do_GET();return result

    def setup_portal(self):
        cookie, csrf, post, order = self.paid_order(3500, key='portal-1')
        with app.connect() as c:
            token = order_tracking.active(c, order['id'])['url'].rsplit('/', 1)[1]
            pid = c.execute('SELECT id FROM order_payments WHERE order_id=?', (order['id'],)).fetchone()[0]
        return cookie, csrf, post, order, token, pid

    def snapshot(self):
        with app.connect() as c:
            return tuple(c.execute('SELECT (SELECT COUNT(*) FROM order_payments),(SELECT COALESCE(SUM(amount_cents),0) FROM order_payments),(SELECT COUNT(*) FROM invoices),'
                                   '(SELECT group_concat(status) FROM orders)').fetchone())

    def test_verification_session_documents_and_exit(self):
        cookie, csrf, post, order, token, pid = self.setup_portal()
        base = '/s/%s/cuenta' % token
        page = self.get('/s/' + token)
        self.assertIn(base, page['body'])                                               # el seguimiento enlaza al portal
        form = self.get(base)
        self.assertEqual(form['status'], 200);self.assertIn('Ingresa los últimos 4 dígitos de tu cédula registrada', form['body'])
        self.assertNotIn('$35,00', form['body'])                                       # sin verificar no hay datos
        self.assertEqual(self.get(base + '/recibo/%d.pdf' % pid)['status'], 403)
        bad = self.post_form(base, {'last4': '9999'})
        self.assertEqual(bad['status'], 400);self.assertIsNone(bad['cookie'])
        before = self.snapshot()
        good = self.post_form(base, {'last4': '0017'})
        self.assertEqual(good['status'], 200, good['body'][:300])
        self.assertIn('$35,00', good['body']);self.assertIn('Recibo REC-', good['body']);self.assertIn('Estado de cuenta', good['body'])
        jar = good['cookie']
        self.assertIn('HttpOnly', jar);self.assertIn('SameSite=Strict', jar);self.assertIn('Path=%s;' % base, jar);self.assertIn('Max-Age=900', jar)
        session = jar.split(';')[0]
        self.assertEqual(self.get(base, session)['status'], 200)
        receipt = self.get(base + '/recibo/%d.pdf' % pid, session)
        self.assertEqual(receipt['status'], 200);self.assertTrue(receipt['body'].startswith(b'%PDF'))
        statement = self.get(base + '/estado.pdf', session)
        self.assertEqual(statement['status'], 200);self.assertTrue(statement['body'].startswith(b'%PDF'))
        self.assertEqual(self.get(base + '/entrega.pdf', session)['status'], 404)        # aún no entregada
        self.assertEqual(self.get(base + '/recibo/%d.pdf' % (pid + 999), session)['status'], 404)
        # Otra orden: la sesión de esta orden no abre la otra (aunque se use su enlace).
        other = self.paid_order(1200, key='portal-2')[3]
        with app.connect() as c:
            other_token = order_tracking.active(c, other['id'])['url'].rsplit('/', 1)[1]
        self.assertNotEqual(self.get('/s/%s/cuenta' % other_token, session)['body'].count('$12,00'), 1)
        before = self.snapshot()
        self.get(base + '/recibo/%d.pdf' % pid, session);self.get(base + '/estado.pdf', session);self.get(base, session)
        self.assertEqual(self.snapshot(), before)                                        # consultar no cambia pagos, facturas ni órdenes
        with app.connect() as c:
            actions = [r[0] for r in c.execute("SELECT action FROM audit WHERE action LIKE 'portal_%'")]
        for action in ('portal_failed', 'portal_verified', 'portal_view', 'portal_download_recibo', 'portal_download_estado'):
            self.assertIn(action, actions)
        out = self.post_form(base + '/salir', {}, session)
        self.assertIn('Max-Age=0', out['cookie'])
        self.assertEqual(self.get(base + '/recibo/%d.pdf' % pid, session)['status'], 403)   # la sesión ya no vale
        # Enlace revocado: el portal deja de existir para ese QR.
        again = self.post_form(base, {'last4': '0017'})['cookie'].split(';')[0]
        with app.connect() as c:
            order_tracking.revoke(c, order['id'], self.uid, app.reception_now());c.commit()
        self.assertEqual(self.get(base, again)['status'], 404)

    def test_countdown_uses_fixed_server_expiry_and_sessions_expire_on_download(self):
        _, _, _, _, token, pid = self.setup_portal()
        base = '/s/%s/cuenta' % token
        start = app.reception_now().replace(microsecond=0)
        expires = start + timedelta(minutes=15)
        with patch.object(app, 'reception_now', return_value=start):
            opened = self.post_form(base, {'last4': '0017'})
        self.assertEqual(opened['status'],200)
        self.assertIn('data-portal-expires="%s"' % expires.isoformat(), opened['body'])
        self.assertIn('15:00', opened['body'])
        cookie = opened['cookie'].split(';')[0]
        with patch.object(app, 'reception_now', return_value=start + timedelta(minutes=10)):
            refreshed = self.get(base, cookie)
            self.assertIn('data-portal-expires="%s"' % expires.isoformat(), refreshed['body'])
            self.assertIn('05:00', refreshed['body'])
        with patch.object(app, 'reception_now', return_value=expires):
            expired = self.get(base, cookie)
            self.assertIn('Tu acceso venció', expired['body'])
            self.assertNotIn('data-portal-countdown', expired['body'])
            self.assertNotIn('$35,00', expired['body'])
            self.assertEqual(self.get(base+'/recibo/%d.pdf' % pid, cookie)['status'],403)
            self.assertEqual(self.get(base+'/estado.pdf', cookie)['status'],403)

    def test_permissions_by_action_rate_limit_and_admin_only_settings(self):
        cookie, csrf, post, order, token, pid = self.setup_portal()
        base = '/s/%s/cuenta' % token
        session = self.post_form(base, {'last4': '0017'})['cookie'].split(';')[0]
        self.assertEqual(post('/api/portal/settings', receipts=False, statement=False)['status'], 200)
        page = self.get(base, session)['body']
        self.assertNotIn('Recibo REC-', page);self.assertNotIn('Estado de cuenta', page)
        self.assertEqual(self.get(base + '/recibo/%d.pdf' % pid, session)['status'], 403)
        self.assertEqual(self.get(base + '/estado.pdf', session)['status'], 403)
        self.assertEqual(post('/api/portal/settings', receipts='si')['status'], 400)
        self.assertEqual(post('/api/portal/settings', enabled=False)['status'], 200)
        self.assertEqual(self.get(base, session)['status'], 503)                        # portal apagado
        self.assertNotIn(base, self.get('/s/' + token)['body'])                          # y el seguimiento ya no lo ofrece
        post('/api/portal/settings', enabled=True)
        for _ in range(6):
            self.post_form(base, {'last4': '1111'}, ip='10.0.0.9')
        self.assertEqual(self.post_form(base, {'last4': '0017'}, ip='10.0.0.9')['status'], 429)   # intentos limitados por enlace
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(self.request('/api/portal/settings', cookie=cookie)['status'], 403)


    def test_client_requests_cancellation_from_portal_and_tracking_shows_it(self):
        cookie, csrf, post, order, token, pid = self.setup_portal()
        base = '/s/%s/cuenta' % token
        self.assertEqual(self.post_form(base + '/cancelar', {'reason': 'costo', 'detail': 'No deseo continuar con la reparación.'})['status'], 403)   # sin sesión
        session = self.post_form(base, {'last4': '0017'})['cookie'].split(';')[0]
        self.assertIn('Solicitar la cancelación', self.get(base, session)['body'])
        sent = self.post_form(base + '/cancelar', {'reason': 'costo', 'detail': 'No deseo continuar con la reparación.'}, session)
        self.assertEqual(sent['status'], 200, sent['body'][:300])
        self.assertIn('Recibimos su solicitud de cancelación', sent['body'])
        import order_cancellations
        with app.connect() as c:
            row = order_cancellations.current(c, order['id'])
        self.assertEqual((row['state'], row['via'], row['identity_method']), ('solicitada', 'portal', 'portal_seguro'))
        keys = [i['key'] for i in self.request('/api/adi/admin/insights', cookie=cookie)['body']['items']]
        self.assertIn('cancelaciones_por_confirmar', keys)
        self.assertEqual(post('/api/orders/%d/cancellation' % order['id'], action='confirm', confirm='CANCELAR')['status'], 200)
        self.assertIn('Reparación cancelada a solicitud del cliente', self.get('/s/' + token)['body'])

if __name__ == '__main__':
    unittest.main()
