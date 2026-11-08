"""Mail Pro 1.5.259 (sin red, datos ficticios): adjuntos ejecutables bloqueados al enviar y marcados al recibir, nombres largos que conservan
la extensión y el sanitizador frente a vectores de XSS habituales."""
import base64
import unittest
from email.message import EmailMessage
from unittest.mock import patch

import mail_pro

CFG = {'imap_host': 'imap.example.invalid', 'imap_port': 993, 'smtp_host': 'smtp.example.invalid', 'smtp_port': 465, 'username': 'taller@example.invalid', 'password': 'x'}


class MailSafetyTests(unittest.TestCase):
    def test_executables_are_not_sent(self):
        data = {'to': 'cliente@example.invalid', 'subject': 'Prueba', 'body': 'Hola',
                'attachments': [{'name': 'factura.pdf.exe', 'type': 'application/octet-stream', 'data': base64.b64encode(b'MZ').decode()}]}
        with self.assertRaises(mail_pro.MailError) as caught:
            mail_pro.build_message(CFG, data)
        self.assertIn('ejecutables', str(caught.exception))
        ok = dict(data, attachments=[{'name': 'informe.pdf', 'type': 'application/pdf', 'data': base64.b64encode(b'%PDF-1.4').decode()}])
        message, recipients = mail_pro.build_message(CFG, ok)
        self.assertEqual(recipients, ['cliente@example.invalid'])
        for name, risky in (('a.EXE', True), ('x.js', True), ('foto.jpg', False), ('informe.pdf', False), ('sinextension', False), ('', False)):
            self.assertEqual(mail_pro.dangerous(name), risky, name)

    def test_received_executables_are_marked(self):
        e = EmailMessage();e['Subject'] = 'Factura';e['From'] = 'x@example.invalid';e.set_content('Adjunto')
        e.add_attachment(b'MZ', maintype='application', subtype='octet-stream', filename='factura.pdf.exe')
        e.add_attachment(b'%PDF', maintype='application', subtype='pdf', filename='informe.pdf')
        with patch.object(mail_pro, 'fetch_message', return_value=(e, '\\\\seen')):
            got = mail_pro.read_message(object(), 'INBOX', 7, mark_seen=False)
        self.assertEqual([(a['name'], a['dangerous']) for a in got['attachments']], [('factura.pdf.exe', True), ('informe.pdf', False)])

    def test_long_names_keep_their_extension_and_html_is_sanitized(self):
        name = mail_pro.safe_filename('x' * 300 + '.pdf')
        self.assertEqual((len(name), name[-4:]), (120, '.pdf'))
        self.assertEqual(mail_pro.safe_filename('../../etc/passwd'), '_.._etc_passwd')
        for vector in ('<img src=x onerror=alert(1)>', '<a href="jav&#x61;script:alert(1)">x</a>', '<svg onload=alert(1)>', '<iframe src=//evil></iframe>',
                       '<div style="position:fixed">x</div>', '<a href="java\tscript:alert(1)">x</a>', '<meta http-equiv=refresh content=0>'):
            out, _ = mail_pro.sanitize_html(vector)
            for bad in ('onerror', 'javascript', 'onload', '<iframe', 'position:fixed', '<meta', 'java\t'):
                self.assertNotIn(bad, out.lower(), vector)


if __name__ == '__main__':
    unittest.main()
