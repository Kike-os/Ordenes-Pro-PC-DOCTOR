"""Comprobante A4 con las Políticas de Reparaciones y su envío por correo (SMTP simulado: no se envía nada real)."""
import base64,unittest
from unittest.mock import patch
import test_app
import app,mail_pro,repair_policies
app.os.environ.setdefault('LOGIN_CAPTCHA','off')

CONFIG={'imap_host':'imap.example.invalid','imap_port':993,'smtp_host':'smtp.example.invalid','smtp_port':465,'username':'taller@example.invalid','password':'x'}


class ReceiptMailTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data

    def test_policies_are_literal_and_complete(self):
        policies=repair_policies.load();text=policies['text']
        self.assertEqual(policies['title'],'POLITICAS DE REPARACIONES')
        for literal in ('5.1- Productos con evidencias claras de mal uso inoperancia o rayones','5.2 - Muestras claras de intento de desarme del producto.','5.3 - Cables y lo conectores rotos',
                        'Los clientes tienen un máximo de 3 meses para recoger su producto','se reserva el derecho de retener o rematar el producto','5.9 - El daño fuese causado por instalación de otro software diferente al instalado de fábrica (virus informáticos, software pirata, etc.)'):
            self.assertIn(literal,text)
        self.assertEqual([p[:3] for p in policies['paragraphs'] if p[:2]=='5.'],['5.1','5.2','5.3','5.4','5.5','5.6','5.7','5.8','5.9'])
        self.assertEqual(len(policies['sha256']),64)

    def test_receipt_is_mailed_once_logged_and_never_blocks_the_order(self):
        cookie,csrf=self.login();sent=[]
        oid=self.request('/api/orders',self.order_data({'client':'Cliente Con Correo','email':'cliente@example.invalid','problem':'No enciende','brand':'HP','model':'ProBook','request_key':'receipt-mail-order-00001'}),cookie=cookie,csrf=csrf)['body']['id']
        url='/api/orders/%d/receipt-mail'%oid
        pdf=self.request('/api/orders/%d/receipt.pdf'%oid,cookie=cookie)['body']
        self.assertTrue(pdf.startswith(b'%PDF'));self.assertGreaterEqual(pdf.count(b'/Type /Page/'),2)
        self.assertEqual(self.request(url,{'mode':'auto'},cookie=cookie)['status'],403)
        # Sin correo del sistema configurado: la orden sigue y queda constancia.
        with patch.object(mail_pro,'configured',return_value=False):
            self.assertEqual(self.request(url,{'mode':'manual'},cookie=cookie,csrf=csrf)['body']['result'],'not_configured')
        def deliver(config,message,recipients):sent.append((message,recipients))
        with patch.object(mail_pro,'configured',return_value=True),patch.object(mail_pro,'settings',return_value=CONFIG),patch.object(mail_pro,'deliver',side_effect=deliver):
            self.assertEqual(self.request(url,{'mode':'auto'},cookie=cookie,csrf=csrf)['body']['result'],'already')
            first=self.request(url,{'mode':'manual'},cookie=cookie,csrf=csrf)['body']
            self.assertEqual((first['result'],first['recipient'],len(sent)),('sent','cliente@example.invalid',1))
            message,recipients=sent[0];self.assertEqual(recipients,['cliente@example.invalid'])
            code=self.request('/api/orders/%d'%oid,cookie=cookie)['body']['order']['code']
            self.assertEqual(message['Subject'],'Confirmación de recepción — Orden '+code+' | PC-DOCTOR S.A.')
            attachment=[part for part in message.iter_attachments()]
            self.assertEqual([(a.get_filename(),a.get_content_type()) for a in attachment],[('Comprobante-'+code+'.pdf','application/pdf')])
            self.assertTrue(attachment[0].get_payload(decode=True).startswith(b'%PDF'))
            body=message.get_body(preferencelist=('plain',)).get_content()
            self.assertIn('Estimado/a Cliente Con Correo:',body);self.assertIn('nuestras Políticas de Reparaciones',body)
            # Fallo de SMTP: se registra y la orden no se pierde ni se duplica.
            with patch.object(mail_pro,'deliver',side_effect=mail_pro.MailError('conexion','sin conexión')):
                self.assertEqual(self.request(url,{'mode':'manual'},cookie=cookie,csrf=csrf)['body']['result'],'failed')
        detail=self.request('/api/orders/%d'%oid,cookie=cookie)['body']['order']
        self.assertEqual([(r['mode'],r['result']) for r in detail['receipt_mail']['history']],[('manual','failed'),('manual','sent'),('manual','not_configured')])
        self.assertTrue(detail['receipt_mail']['sent']);self.assertIn('Comprobante de recepción enviado por correo a cliente@example.invalid.',[h['comment'] for h in detail['history']])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
            row=c.execute("SELECT document_sha256,policies_version FROM order_receipt_mail WHERE result='sent'").fetchone()
            self.assertEqual((len(row['document_sha256']),row['policies_version']),(64,repair_policies.load()['version']))

    def test_auto_send_respects_missing_email_and_the_switch(self):
        cookie,csrf=self.login();calls=[]
        with patch.object(mail_pro,'configured',return_value=True),patch.object(mail_pro,'settings',return_value=CONFIG),patch.object(mail_pro,'deliver',side_effect=lambda *a:calls.append(a)):
            no_mail=self.request('/api/orders',self.order_data({'client':'Cliente Sin Correo','email':'','problem':'Prueba','request_key':'receipt-mail-order-00002'}),cookie=cookie,csrf=csrf)['body']['id']
            self.assertEqual(self.request('/api/orders/%d/receipt-mail'%no_mail,{'mode':'auto'},cookie=cookie,csrf=csrf)['body']['result'],'no_email')
            self.assertEqual(self.request('/api/receipt-mail/settings',{'auto':False},cookie=cookie,csrf=csrf)['status'],200)
            off=self.request('/api/orders',self.order_data({'client':'Cliente Dos','email':'dos@example.invalid','identification':'0100000025','problem':'Prueba','request_key':'receipt-mail-order-00003'}),cookie=cookie,csrf=csrf)['body']['id']
            self.assertEqual(self.request('/api/orders/%d/receipt-mail'%off,{'mode':'auto'},cookie=cookie,csrf=csrf)['body']['result'],'disabled')
            self.request('/api/receipt-mail/settings',{'auto':True},cookie=cookie,csrf=csrf)
            self.assertEqual(self.request('/api/orders/%d/receipt-mail'%off,{'mode':'auto'},cookie=cookie,csrf=csrf)['body']['result'],'sent')
            self.assertEqual(self.request('/api/orders/%d/receipt-mail'%off,{'mode':'auto'},cookie=cookie,csrf=csrf)['body']['result'],'already')
        self.assertEqual(len(calls),1)
        self.assertEqual(self.request('/api/orders/999999/receipt-mail',{'mode':'manual'},cookie=cookie,csrf=csrf)['status'],404)
