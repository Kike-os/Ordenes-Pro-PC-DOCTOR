"""Aviso al correo administrativo cuando se registra una autorización (SMTP simulado: no se envía nada real)."""
import unittest
from unittest.mock import patch
import test_app
import app,mail_pro
app.os.environ.setdefault('LOGIN_CAPTCHA','off')

CONFIG={'imap_host':'imap.example.invalid','imap_port':993,'smtp_host':'smtp.example.invalid','smtp_port':465,'username':'taller@example.invalid','password':'x'}


class AuthorizationMailTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__)
    setUp=test_app.SecurityTests.setUp
    tearDown=test_app.SecurityTests.tearDown
    login=test_app.SecurityTests.login
    request=test_app.SecurityTests.request
    order_data=test_app.SecurityTests.order_data

    def rows(self,oid):
        with app.connect() as c:return [dict(r) for r in c.execute('SELECT consent_id,recipient,result,detail FROM order_authorization_mail WHERE order_id=? ORDER BY id',(oid,))]

    def test_notice_is_sent_once_per_decision_with_real_states_and_logged(self):
        cookie,csrf=self.login();sent=[]
        def deliver(config,message,recipients):sent.append((message,recipients))
        data=self.order_data({'client':'Cliente Aviso','brand':'HP','model':'ProBook','serial':'AVISO-1','technical_access':'authorized','access_operating_system':True,'files_access':'denied','destructive_action':'denied','request_key':'authorization-mail-order-01'})
        with patch.object(mail_pro,'configured',return_value=True),patch.object(mail_pro,'settings',return_value=CONFIG),patch.object(mail_pro,'deliver',side_effect=deliver):
            created=self.request('/api/orders',data,cookie=cookie,csrf=csrf)
            self.assertEqual(created['status'],201,created);oid=created['body']['id']
            self.assertEqual(created['body']['authorization_mail'],{'result':'sent','recipient':'taller@example.invalid'})
            notices=[(m,r) for m,r in sent if 'Autorización registrada' in str(m['Subject'])];self.assertEqual(len(notices),1)
            message,recipients=notices[0];text=message.get_body(preferencelist=('plain',)).get_content()
            self.assertEqual(recipients,['taller@example.invalid']);self.assertIn(created['body']['code'],str(message['Subject']))
            for expected in ('Cliente: Cliente Aviso','HP ProBook','Serie AVISO-1','Acceso al sistema operativo: AUTORIZADO','Acceso a archivos personales y respaldos: NO AUTORIZADO','Formateo, reinstalación y eliminación de datos: NO AUTORIZADO','Estado: Con operaciones NO AUTORIZADAS','/#orders?id=%d'%oid,'no es una firma del cliente'):
                self.assertIn(expected,text)
            # Sin duplicados para la misma decisión; una decisión nueva genera su propio aviso.
            with app.connect() as c:
                user=dict(c.execute('SELECT * FROM users WHERE id=?',(self.uid,)).fetchone());self.assertEqual(app.send_authorization_mail(c,oid,user),{'result':'already'})
            self.assertEqual(len([m for m,_ in sent if 'Autorización registrada' in str(m['Subject'])]),1)
            order=self.request('/api/orders/%d'%oid,cookie=cookie)['body']['order']
            again=self.request('/api/orders/%d/authorizations'%oid,{'technical_access':'denied','access_confirmed':True,'access_revision':str(order['access_revision']),'request_key':'authorization-mail-decision-02'},cookie=cookie,csrf=csrf)
            self.assertEqual(again['status'],201,again)
            self.assertEqual(again['body']['authorization_mail']['result'],'sent');self.assertEqual(len([m for m,_ in sent if 'Autorización registrada' in str(m['Subject'])]),2)
            self.assertIn('Acceso al sistema operativo: NO AUTORIZADO',sent[-1][0].get_body(preferencelist=('plain',)).get_content())
        log=self.rows(oid);self.assertEqual(log[0]['result'],'sent');self.assertEqual(log[0]['recipient'],'taller@example.invalid')
        self.assertEqual(self.request('/api/orders/%d'%oid,cookie=cookie)['body']['order']['authorization_mail']['result'],'sent')

    def test_failures_never_block_the_order_and_are_recorded(self):
        cookie,csrf=self.login()
        # Correo del sistema sin configurar: la orden se crea y queda constancia.
        with patch.object(mail_pro,'configured',return_value=False):
            first=self.request('/api/orders',self.order_data({'request_key':'authorization-mail-order-02'}),cookie=cookie,csrf=csrf)
        self.assertEqual(first['status'],201);self.assertEqual(first['body']['authorization_mail'],{'result':'not_configured'});self.assertEqual(self.rows(first['body']['id'])[0]['result'],'not_configured')
        def broken(config,message,recipients):raise mail_pro.MailError('red','El servidor de correo no respondió.')
        with patch.object(mail_pro,'configured',return_value=True),patch.object(mail_pro,'settings',return_value=CONFIG),patch.object(mail_pro,'deliver',side_effect=broken):
            second=self.request('/api/orders',self.order_data({'request_key':'authorization-mail-order-03'}),cookie=cookie,csrf=csrf)
        self.assertEqual(second['status'],201);self.assertEqual(second['body']['authorization_mail']['result'],'failed')
        log=self.rows(second['body']['id']);self.assertEqual((log[0]['result'],log[0]['recipient']),('failed',''));self.assertIn('no respondió',log[0]['detail'])


if __name__=='__main__':
    unittest.main()
