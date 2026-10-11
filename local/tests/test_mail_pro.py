import smtplib
import socket
import ssl
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mail_pro
import test_app
import app

ENV={'MAIL_IMAP_HOST':'mail.example.invalid','MAIL_IMAP_PORT':'993','MAIL_SMTP_HOST':'mail.example.invalid','MAIL_SMTP_PORT':'465','MAIL_USERNAME':'buzon@example.invalid','MAIL_PASSWORD':'secreto-ficticio-123'}


class MailProTests(unittest.TestCase):
    def test_status_never_exposes_the_password(self):
        info=mail_pro.status(ENV)
        self.assertEqual((info['configured'],info['password_set'],info['account']),(True,True,'buzon@example.invalid'))
        self.assertNotIn('secreto-ficticio-123',repr(info))
        self.assertFalse(mail_pro.status({})['configured'])

    def test_only_tls_ports_are_accepted_and_verification_stays_on(self):
        for bad in ({'MAIL_IMAP_PORT':'143'},{'MAIL_SMTP_PORT':'25'},{'MAIL_SMTP_PORT':'abc'}):
            with self.assertRaises(mail_pro.MailError):mail_pro.settings({**ENV,**bad})
        self.assertEqual(mail_pro.settings({**ENV,'MAIL_SMTP_PORT':'587'})['smtp_port'],587)
        ctx=mail_pro.context()
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)

    def test_failures_are_classified_without_secrets(self):
        cases=[(socket.gaierror(),'dns'),(ssl.SSLCertVerificationError(),'tls'),(socket.timeout(),'red'),(ConnectionRefusedError(),'red'),(smtplib.SMTPAuthenticationError(535,b'auth'),'credenciales'),(mail_pro.imaplib.IMAP4.error('LOGIN failed secreto-ficticio-123'),'credenciales')]
        for error,kind in cases:
            failure=mail_pro.classify(error,'mail.example.invalid',993)
            self.assertEqual(failure.kind,kind)
            self.assertNotIn('secreto',str(failure))

    def test_tests_require_configuration_and_report_network_failure(self):
        with self.assertRaises(mail_pro.MailError) as missing:mail_pro.test_imap({})
        self.assertEqual(missing.exception.kind,'configuracion')
        with patch.object(mail_pro.socket,'getaddrinfo',side_effect=socket.gaierror()):
            with self.assertRaises(mail_pro.MailError) as dns:mail_pro.test_imap(ENV)
        self.assertEqual(dns.exception.kind,'dns')
        with patch.object(mail_pro.smtplib,'SMTP_SSL',side_effect=socket.timeout()):
            with self.assertRaises(mail_pro.MailError) as net:mail_pro.test_smtp(ENV)
        self.assertEqual(net.exception.kind,'red')

    def test_html_is_sanitized_and_remote_content_blocked(self):
        dirty='<p onclick="x()">Hola <b>mundo</b></p><script>alert(1)</script><style>p{}</style><img src="https://rastreo.invalid/p.gif" alt="logo"><a href="javascript:alert(1)">malo</a><a href="https://example.invalid/a?b=1&c=2">bueno</a><iframe src="x"></iframe><svg><script>1</script></svg>'
        clean,blocked=mail_pro.sanitize_html(dirty)
        self.assertEqual(blocked,1)
        for bad in ('script','onclick','javascript:','<img','iframe','rastreo.invalid','<style','svg','alert'):
            self.assertNotIn(bad,clean)
        self.assertIn('<p>Hola <b>mundo</b></p>',clean)
        self.assertIn('<a href="https://example.invalid/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer nofollow">bueno</a>',clean)
        self.assertIn('<a>malo</a>',clean)

    def test_addresses_filenames_and_message_building(self):
        self.assertEqual(mail_pro.clean_addresses('Ana <ana@example.invalid>; luis@example.invalid, ANA@example.invalid'),['ana@example.invalid','luis@example.invalid'])
        for bad in ('sin-arroba','a@b','x@example.invalid\nBcc: z@example.invalid'):
            with self.assertRaises(mail_pro.MailError):mail_pro.clean_addresses(bad)
        self.assertEqual(mail_pro.safe_filename('../../etc/pas:swd\x00.pdf'),'_.._etc_pas_swd_.pdf')
        config=mail_pro.settings(ENV)
        message,recipients=mail_pro.build_message(config,{'to':'cliente@example.invalid','cc':'otro@example.invalid','subject':'Asunto\r\nBcc: intruso@example.invalid','body':'Texto','from_name':'PC-DOCTOR S.A.','in_reply_to':'<abc@example.invalid>','references':'<uno@example.invalid> <abc@example.invalid>','attachments':[{'name':'informe.pdf','type':'application/pdf','data':'JVBERi0='}]},'Firma ficticia')
        self.assertEqual(recipients,['cliente@example.invalid','otro@example.invalid'])
        self.assertEqual(str(message['From']),'"PC-DOCTOR S.A." <buzon@example.invalid>')
        self.assertNotIn('\n',str(message['Subject']));self.assertIsNone(message['Bcc'])
        self.assertEqual((str(message['In-Reply-To']),str(message['References'])),('<abc@example.invalid>','<uno@example.invalid> <abc@example.invalid>'))
        self.assertTrue(str(message['Message-ID']).endswith('@example.invalid>'))
        self.assertIn('Firma ficticia',message.get_body(('plain',)).get_content())
        self.assertEqual([part.get_filename() for part in message.iter_attachments()],['informe.pdf'])
        with self.assertRaises(mail_pro.MailError):mail_pro.build_message(config,{'to':'','subject':'x','body':'y'})
        with self.assertRaises(mail_pro.MailError):mail_pro.build_message(config,{'to':'a@example.invalid','subject':'x','body':'y','attachments':[{'name':'g.bin','data':'A'*5_000_000}]})


class MailRouteTests(test_app.SecurityTests):
    KEY='clave-de-solicitud-0001'

    def test_mail_routes_require_permission_and_send_is_not_duplicated(self):
        cookie,csrf=self.login()
        with app.connect() as c:
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES ('tecnico','tec@example.invalid','Técnico de prueba',?,'tecnico',1)",(self.hash,))
        tech=self.request('/api/login',{'login':'tecnico','password':'contraseña-segura-de-prueba'})['cookie'].split(';')[0]
        tech_csrf=self.request('/api/me',cookie=tech)['body']['user']['csrf']
        body={'to':'cliente@example.invalid','cc':'','subject':'Prueba','body':'Texto','attachments':'[]','request_key':self.KEY,'order_code':''}
        self.assertEqual(self.request('/api/mail/overview')['status'],401)
        # Sin configurar, nadie accede.
        with patch.dict(app.os.environ,{k:'' for k in ENV}):
            self.assertEqual(self.request('/api/mail/overview',cookie=cookie)['status'],403)
            self.assertFalse(self.request('/api/me',cookie=cookie)['body']['user']['mail'])
        with patch.dict(app.os.environ,ENV):
            self.assertTrue(self.request('/api/me',cookie=cookie)['body']['user']['mail'])
            self.assertEqual(self.request('/api/mail/overview',cookie=tech)['status'],403)
            self.assertEqual(self.request('/api/mail/send',body,cookie=tech,csrf=tech_csrf)['status'],403)
            self.assertEqual(self.request('/api/mail/send',body,cookie=cookie)['status'],403)
            settings=self.request('/api/settings',cookie=cookie)['body']
            self.assertTrue(settings['mail']['configured']);self.assertNotIn('secreto-ficticio-123',repr(settings))
            sent=[]
            with patch.object(mail_pro,'deliver',side_effect=lambda config,message,recipients:sent.append((str(message['Subject']),recipients))),patch.object(mail_pro,'open_imap',side_effect=mail_pro.MailError('red','sin red')):
                first=self.request('/api/mail/send',body,cookie=cookie,csrf=csrf)
                self.assertEqual((first['status'],first['body']['saved_in_sent']),(201,False))
                again=self.request('/api/mail/send',body,cookie=cookie,csrf=csrf)
                self.assertEqual((again['status'],again['body'].get('duplicate')),(200,True))
                self.assertEqual(sent,[('Prueba',['cliente@example.invalid'])])
                self.assertEqual(self.request('/api/mail/send',dict(body,to='no-valido',request_key='clave-de-solicitud-0002'),cookie=cookie,csrf=csrf)['status'],400)
            with patch.object(mail_pro,'deliver',side_effect=mail_pro.MailError('red','El servidor no respondió.')):
                failed=self.request('/api/mail/send',dict(body,request_key='clave-de-solicitud-0003'),cookie=cookie,csrf=csrf)
                self.assertEqual(failed['status'],502)
            with app.connect() as c:
                self.assertEqual({r['request_key']:r['status'] for r in c.execute('SELECT request_key,status FROM mail_outbox')},{self.KEY:'sent','clave-de-solicitud-0003':'failed'})
            # Un envío fallido se puede reintentar con la misma clave.
            with patch.object(mail_pro,'deliver',return_value=None),patch.object(mail_pro,'open_imap',side_effect=mail_pro.MailError('red','sin red')):
                self.assertEqual(self.request('/api/mail/send',dict(body,request_key='clave-de-solicitud-0003'),cookie=cookie,csrf=csrf)['status'],201)
            with patch.object(mail_pro,'test_imap',side_effect=mail_pro.MailError('credenciales','El servidor rechazó el usuario o la contraseña.')):
                result=self.request('/api/mail/test',{'kind':'imap'},cookie=cookie,csrf=csrf)['body']
                self.assertEqual((result['ok'],result['kind']),(False,'credenciales'))
            self.assertEqual(self.request('/api/mail/test',{'kind':'imap'},cookie=tech,csrf=tech_csrf)['status'],403)
            self.assertEqual(self.request('/api/mail/signature',{'signature':'Firma de prueba'},cookie=cookie,csrf=csrf)['status'],200)
            self.assertEqual(self.request('/api/settings',cookie=cookie)['body']['mail_signature'],'Firma de prueba')


for name in [name for name in dir(test_app.SecurityTests) if name.startswith('test_')]:
    setattr(MailRouteTests,name,None)
del test_app
