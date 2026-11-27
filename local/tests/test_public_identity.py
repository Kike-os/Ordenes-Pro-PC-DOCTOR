import unittest
from unittest.mock import patch

import appointments
import proforma_whatsapp
import public_identity
import quote_page


class PublicIdentityTests(unittest.TestCase):
    def test_stored_kind_takes_priority_and_legacy_values_require_validation(self):
        self.assertEqual(public_identity.kind('1234567890', 'cedula'), 'cedula')
        self.assertEqual(public_identity.kind('1710034065'), 'cedula')
        self.assertEqual(public_identity.kind('1790016919001'), 'ruc')
        self.assertEqual(public_identity.kind('1710034066'), '')
        self.assertEqual(public_identity.kind('0000000000001'), '')
        self.assertEqual(public_identity.kind('AB123456', 'pasaporte'), 'pasaporte')
        self.assertEqual(public_identity.kind('AB123456'), '')

    def test_public_quote_only_displays_the_document_kind(self):
        page = quote_page.identify_page('fictitious', {'code': 'P-001', 'status': 'enviado'},
                                       {'identification': '1790016919001', 'document_type': 'ruc'})
        self.assertIn('Ingresa los últimos 4 dígitos de tu RUC registrado', page)
        self.assertNotIn('1790016919001', page)
        self.assertNotIn('9001', page)

    def test_ascii_only_and_full_ruc_suffix(self):
        self.assertTrue(public_identity.matches('9001', '1790016919001'))
        for submitted in ('0000', '90 01', '90012', '٩٠٠١', '', None):
            self.assertFalse(public_identity.matches(submitted, '1790016919001'))
        self.assertFalse(public_identity.matches('1234', '123'))
        self.assertEqual(appointments.last4_error('9001', '1790016919001', 'ruc'), '')
        self.assertIn('no coinciden', appointments.last4_error('0000', '1790016919001', 'ruc'))

    def test_typed_whatsapp_copy_never_includes_the_document_number(self):
        base = 'https://example.invalid'
        template = proforma_whatsapp.template_definition(base, typed=True)
        self.assertTrue(proforma_whatsapp.compatible(template, base))
        params, preview = proforma_whatsapp._preview(
            {'client_name': 'Cliente ficticio', 'code': 'PF-1',
             'client_identification': '1790016919001', 'client_document_type': 'ruc'}, template)
        self.assertEqual(params[2], 'RUC registrado')
        self.assertIn('Ingresa los últimos 4 dígitos de tu RUC registrado', preview['body'])
        self.assertNotIn('9001', preview['body'])

    def test_whatsapp_uses_the_approved_fallback_while_the_new_template_is_pending(self):
        base = 'https://example.invalid'
        original = dict(proforma_whatsapp.template_definition(base), status='APPROVED')
        typed = dict(proforma_whatsapp.template_definition(base, typed=True), status='PENDING')
        catalogue = (200, {'data': [original, typed]})
        with patch.object(proforma_whatsapp.wa, 'ready', return_value=True), \
             patch.object(proforma_whatsapp.wa, 'config', return_value={'waba': 'test'}), \
             patch.object(proforma_whatsapp.wa, 'call', return_value=catalogue) as call:
            self.assertEqual(proforma_whatsapp.audit_template(base, {})[1], original)
            self.assertEqual(proforma_whatsapp.audit_template(base, {}, submit=True, typed=True)[0], 'pendiente')
            self.assertTrue(all(request.args[0] == 'GET' for request in call.call_args_list))
            typed['status'] = 'APPROVED'
            self.assertEqual(proforma_whatsapp.audit_template(base, {})[1], typed)
