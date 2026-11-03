"""Autorizaciones según el tipo de equipo (1.5.224): solo se piden y se imprimen las que aplican; lo que no aplica figura como
«No aplica» y nunca como autorización; las decisiones registradas no se modifican; el comprobante de una orden anterior se
conserva tal como se emitió y su versión corregida queda registrada en la misma orden. Base temporal y datos ficticios."""
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_app
import test_cash
import test_client_authorization as tca
import app
import device_authorizations
import mail_pro

app.os.environ.setdefault('LOGIN_CAPTCHA', 'off')


def text_of(pdf):
    with tempfile.NamedTemporaryFile(suffix='.pdf') as handle:
        handle.write(pdf)
        handle.flush()
        text = subprocess.run(['pdftotext', '-layout', handle.name, '-'], capture_output=True, text=True, check=True).stdout
        pages = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', handle.name], capture_output=True, text=True, check=True).stdout)[1])
    return ' '.join(text.split()), pages


class DeviceAuthorizationTests(unittest.TestCase):
    setUpClass = classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp = test_app.SecurityTests.setUp
    tearDown = test_app.SecurityTests.tearDown
    login = test_app.SecurityTests.login
    request = test_app.SecurityTests.request
    order_data = test_app.SecurityTests.order_data
    technician = test_cash.CashTests.technician
    form = tca.ClientAuthorizationTests.form

    def setUp(self):
        test_app.SecurityTests.setUp(self)
        if not shutil.which('pdftotext'):
            self.skipTest('pdftotext no disponible')
        self.cookie, self.csrf = self.login()

    def post(self, path, data, cookie=None, csrf=None):
        return self.request(path, data, cookie=cookie or self.cookie, csrf=csrf or self.csrf)

    def create(self, kind, key, **changes):
        made = self.post('/api/orders', self.order_data({'type': kind, 'brand': 'Marca', 'model': 'Modelo ' + key, 'request_key': 'device-auth-' + key, **changes}))
        self.assertEqual(made['status'], 201, made)
        return made['body']['id']

    def detail(self, oid):
        return self.request('/api/orders/%d' % oid, cookie=self.cookie)['body']['order']

    def pdf(self, oid, name='receipt.pdf'):
        return self.request('/api/orders/%d/%s' % (oid, name), cookie=self.cookie)['body']

    def consents(self, oid):
        with app.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM order_access_consents WHERE order_id=? ORDER BY id', (oid,))]

    def test_a_computers_keep_every_authorization(self):
        refused = self.post('/api/orders', {**self.order_data({'request_key': 'device-auth-laptop-0'}), 'technical_access': ''})
        self.assertEqual(refused['status'], 400)
        self.assertIn('technical_access', refused['body']['fields'])
        oid = self.create('portatil', 'laptop-1')
        order = self.detail(oid)
        self.assertEqual((order['authorization_profile']['group'], order['authorization_profile']['sections'], order['receipt_layout']), ('computadoras', ['os', 'files', 'risk'], 'dinamico'))
        text, _ = text_of(self.pdf(oid))
        for expected in ('Acceso al sistema operativo', 'Acceso a archivos personales y respaldos', 'Formateo, reinstalación y eliminación de datos'):
            self.assertIn(expected, text)
        self.assertNotIn('No aplica', text)
        ticket, _ = text_of(self.pdf(oid, 'thermal.pdf'))
        self.assertIn('AUTORIZACIÓN DE ACCESO TÉCNICO', ticket)  # el ticket de una computadora no cambia

    def test_b_printer_hides_computer_permissions(self):
        blocked = self.post('/api/orders', self.order_data({'type': 'impresora', 'request_key': 'device-auth-printer-0', 'technical_access': 'authorized', 'access_operating_system': True}))
        self.assertEqual(blocked['status'], 400)
        self.assertIn('no aplica', blocked['body']['fields']['technical_access'])
        oid = self.create('impresora', 'printer-1', technical_access='', access_confirmed=False)
        self.assertEqual(self.consents(oid), [])  # nada se registra como autorización ni como rechazo
        order = self.detail(oid)
        self.assertEqual((order['authorization_profile']['sections'], order['authorization_profile']['exception_available']), ([], True))
        text, pages = text_of(self.pdf(oid))
        self.assertIn('NO APLICA No aplica a impresora', text)
        for hidden in ('Acceso al sistema operativo', 'Acceso a archivos personales', 'NO AUTORIZADO', 'PENDIENTE'):
            self.assertNotIn(hidden, text)
        ticket, ticket_pages = text_of(self.pdf(oid, 'thermal.pdf'))
        self.assertIn('No aplica a impresora', ticket)
        self.assertNotIn('Acceso técnico', ticket)
        self.assertEqual(ticket_pages, 1)
        # Un formulario anterior que aún envía «No autorizo» no deja un rechazo en lo que no aplica.
        old_form = self.create('impresora', 'printer-2')
        self.assertEqual(self.consents(old_form), [])

    def test_c_mouse_keyboard_and_monitor_never_ask_for_data(self):
        for n, kind in enumerate(('mouse', 'teclado', 'monitor')):
            oid = self.create(kind, 'periph-%d' % n, technical_access='', data_exception=True)
            order = self.detail(oid)
            self.assertEqual((order['authorization_profile']['sections'], order['authorization_profile']['exception']), ([], False))
            self.assertEqual(self.post('/api/orders', self.order_data({'type': kind, 'request_key': 'device-auth-periph-x%d' % n, 'destructive_action': 'authorized', 'destructive_detail': 'Formatear la memoria del equipo', 'destructive_confirmed': True, 'risk_format': True}))['status'], 400)
            text, _ = text_of(self.pdf(oid))
            self.assertNotIn('Formateo', text.replace('formateo', ''))

    def test_d_storage_keeps_data_permissions(self):
        self.assertEqual(self.post('/api/orders', self.order_data({'type': 'ssd', 'request_key': 'device-auth-ssd-0', 'technical_access': 'authorized', 'access_operating_system': True}))['status'], 400)
        oid = self.create('hdd', 'hdd-1', technical_access='authorized', files_access='authorized', access_backup=True, access_detail='Respaldar la carpeta Fotos del disco del cliente',
                          destructive_action='authorized', destructive_detail='Unidad: HDD, 1 TB. Borrado seguro tras el respaldo', destructive_confirmed=True, risk_erase=True)
        self.assertEqual(self.detail(oid)['authorization_profile']['sections'], ['files', 'risk'])
        text, _ = text_of(self.pdf(oid))
        self.assertIn('Acceso a archivos personales y respaldos', text)
        self.assertIn('Formateo, reinstalación y eliminación de datos', text)
        self.assertIn('No aplica a disco duro (hdd)', text)
        self.assertNotIn('Acceso al sistema operativo', text)
        self.assertEqual([r['decision'] for r in self.consents(oid)], ['authorized', 'authorized'])

    def legacy_printer(self, key):
        """Orden anterior a la 1.5.224, como PCD-20261102-0012: impresora con el «No autorizo» que pedía el formulario de entonces."""
        oid = self.create('impresora', key, technical_access='', access_confirmed=False)
        with app.connect() as c:
            c.execute("UPDATE system_state SET value=? WHERE key='authorization_layout_since'", (str(10 ** 10),))
            c.execute("INSERT INTO order_access_consents(order_id,action,decision,permissions,justification,acceptor,recorded_at,actor_id,request_key) VALUES (?,'technical','denied',?,'','Cliente ficticio','2026-11-02T18:36:59.560188-05:00',1,'legacy-consent-0001')",
                      (oid, json.dumps({'backup': False, 'operating_system': False, 'signed_in_tests': False, 'specific_files': False}, sort_keys=True)))
            c.commit()
        return oid

    def test_e_existing_order_is_corrected_in_the_same_order(self):
        oid = self.legacy_printer('legacy-1')
        before = self.detail(oid)
        consents = self.consents(oid)
        original = self.pdf(oid)
        self.assertEqual(hashlib.sha256(original).digest(), hashlib.sha256(self.pdf(oid)).digest())  # determinista: el original se conserva tal cual
        text, _ = text_of(original)
        self.assertIn('Acceso al sistema operativo', text)  # el original no se reescribe en silencio
        self.assertTrue(before['receipt_correctable'])
        tech_cookie, tech_csrf = self.technician()
        self.assertEqual(self.post('/api/orders/%d/receipt-correction' % oid, {'reason': 'corto'})['status'], 400)
        made = self.post('/api/orders/%d/receipt-correction' % oid, {'reason': 'Autorizaciones que no aplican a impresoras.'}, tech_cookie, tech_csrf)
        self.assertEqual(made['status'], 201, made)
        self.assertEqual(made['body']['original_sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(self.post('/api/orders/%d/receipt-correction' % oid, {'reason': 'Autorizaciones que no aplican a impresoras.'})['status'], 409)
        after = self.detail(oid)
        for key in ('id', 'code', 'status', 'client', 'type', 'brand', 'model', 'received_at', 'qr_url', 'terms_acceptance_id'):
            self.assertEqual(after.get(key), before.get(key), key)
        self.assertEqual(self.consents(oid), consents)  # decisiones, fechas y responsables intactos
        self.assertEqual(after['access_authorization']['decision'], 'denied')
        self.assertEqual((after['receipt_layout'], after['receipt_correctable'], after['receipt_corrections'][0]['revision']), ('dinamico', False, 2))
        self.assertTrue(any('Comprobante corregido (revisión 2)' in (h.get('comment') or '') for h in after['history']))
        fixed = self.pdf(oid)
        self.assertEqual(hashlib.sha256(fixed).hexdigest(), made['body']['corrected_sha256'])
        fixed_text, pages = text_of(fixed)
        self.assertIn('COMPROBANTE CORREGIDO · REVISIÓN 2', fixed_text)
        self.assertIn('No aplica a impresora', fixed_text)
        self.assertNotIn('Acceso al sistema operativo', fixed_text)
        self.assertEqual(self.pdf(oid, 'receipt.pdf?original=1'), original)  # el original sigue disponible, idéntico
        ticket, _ = text_of(self.pdf(oid, 'thermal.pdf'))
        self.assertIn('Comprobante corregido · revisión 2', ticket)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0], 1)  # no se creó otra orden

    def test_f_category_change_recalculates_without_inventing_consent(self):
        oid = self.create('portatil', 'change-1', technical_access='authorized', access_operating_system=True)
        consents = self.consents(oid)
        order = self.detail(oid)
        changed = self.post('/api/devices', {'id': str(order['device_id']), 'client_id': str(order['client_id']), 'type': 'impresora', 'brand': 'Epson', 'model': 'L555'})
        self.assertEqual(changed['status'], 200, changed)
        order = self.detail(oid)
        self.assertEqual(order['authorization_profile']['sections'], [])
        self.assertEqual(self.consents(oid), consents)
        text, _ = text_of(self.pdf(oid))
        self.assertIn('Acceso al sistema operativo', text)  # una autorización expresa ya registrada nunca se oculta
        self.assertIn('AUTORIZADO', text)
        # Permiso nuevo: se pide al cliente, no se presume. La excepción de datos queda en el historial.
        missing = self.post('/api/orders/%d/authorizations' % oid, {'request_key': 'device-auth-later-0001', 'access_revision': str(order['access_revision'])})
        self.assertEqual(missing['status'], 400)
        later = self.post('/api/orders/%d/authorizations' % oid, {'request_key': 'device-auth-later-0002', 'access_revision': str(order['access_revision']), 'data_exception': True, 'data_exception_note': 'Multifuncional con escáner y memoria',
                                                                   'technical_access': 'authorized', 'access_confirmed': True, 'files_access': 'authorized', 'access_specific_files': True, 'access_detail': 'Documentos escaneados guardados en la memoria interna'})
        self.assertEqual(later['status'], 201, later)
        order = self.detail(oid)
        self.assertEqual((order['authorization_profile']['exception'], order['authorization_profile']['sections']), (True, ['files', 'risk']))
        self.assertEqual(len(self.consents(oid)), len(consents) + 1)
        self.assertTrue(any('guarda información del cliente' in (h.get('comment') or '') for h in order['history']))

    def test_g_receipts_stay_legible_without_extra_pages(self):
        oid = self.create('impresora', 'pages-1', technical_access='', problem='No imprime. ' * 30)
        _, pages = text_of(self.pdf(oid))
        laptop = self.create('portatil', 'pages-2', problem='No imprime. ' * 30)
        _, laptop_pages = text_of(self.pdf(laptop))
        self.assertLessEqual(pages, laptop_pages)
        for copy, expected in (('cliente', 1), ('ambas', 2)):
            _, count = text_of(self.pdf(oid, 'thermal.pdf?copy=' + copy))
            self.assertEqual(count, expected)

    def test_h_client_link_asks_only_what_applies(self):
        sent = []
        with patch.object(mail_pro, 'configured', return_value=True), patch.object(mail_pro, 'settings', return_value=tca.CONFIG), patch.object(mail_pro, 'deliver', side_effect=lambda config, message, recipients: sent.append(message)):
            oid = self.create('impresora', 'link-1', technical_access='', email='cliente@example.invalid')
            token = self.post('/api/orders/%d/client-authorization' % oid, {'action': 'send'})['body']['url'].rsplit('/', 1)[1]
            self.form(token, {'step': 'identify', 'last4': '0017'})
            code = re.search(r'\b(\d{6})\b', sent[-1].get_body(preferencelist=('plain',)).get_content())[1]
            page = self.form(token, {'step': 'verify', 'code': code})['body']
            self.assertIn('Diagnóstico y servicio técnico solicitado', page)
            for hidden in ('Acceso al sistema operativo', 'Formateo, reinstalación o eliminación de datos'):
                self.assertNotIn(hidden, page)
            passkey = re.search(r'name="pass" value="([^"]+)"', page)[1]
            choices = {'step': 'sign', 'pass': passkey, 'service': 'authorized', 'confirm': '1'}
            with app.connect() as c:
                if app.service_terms.current(c, app.reception_now()):
                    choices['terms_accept'] = '1'
            done = self.form(token, choices)['body']
            self.assertIn('NO APLICA', done)
        evidence = self.detail(oid)['client_authorization']['evidence']
        self.assertEqual(evidence['decisions'], {'service': 'authorized'})
        self.assertEqual(evidence['device']['not_applicable'], ['operating_system', 'files', 'data_operations'])

    def test_i_admin_configuration_is_logged_and_never_rewrites_history(self):
        oid = self.create('portatil', 'config-1')
        consents = self.consents(oid)
        tech_cookie, tech_csrf = self.technician()
        self.assertEqual(self.request('/api/authorization-profiles', cookie=tech_cookie)['status'], 403)
        groups = self.request('/api/authorization-profiles', cookie=self.cookie)['body']['groups']
        for g in groups:
            g['types'] = [t for t in g['types'] if t != 'gaming']
        groups.append({'code': 'gamer', 'label': 'Portátiles gamer', 'sections': ['files'], 'exception': ['risk'], 'types': ['gaming']})
        self.assertEqual(self.post('/api/authorization-profiles', {'groups': json.dumps(groups), 'reason': 'corto'})['status'], 400)
        denied = self.post('/api/authorization-profiles', {'groups': json.dumps(groups), 'reason': 'Prueba ficticia'}, tech_cookie, tech_csrf)
        self.assertEqual(denied['status'], 403, denied)
        bad = [g for g in groups if g['code'] != 'otros']
        self.assertEqual(self.post('/api/authorization-profiles', {'groups': json.dumps(bad), 'reason': 'Retirar otros (ficticio)'})['status'], 400)
        saved = self.post('/api/authorization-profiles', {'groups': json.dumps(groups), 'reason': 'Nueva categoría ficticia para portátiles gamer'})
        self.assertEqual(saved['status'], 200, saved)
        self.assertIn('Nueva categoría «Portátiles gamer»', saved['body']['changes'][0]['summary'])
        catalog = self.request('/api/reception-options', cookie=self.cookie)['body']['authorization_catalog']
        self.assertEqual((catalog['types']['gaming'], catalog['groups']['gamer']['sections']), ('gamer', ['files']))
        self.assertEqual(self.consents(oid), consents)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM authorization_profile_changes').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
