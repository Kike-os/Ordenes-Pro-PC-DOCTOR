"""Consulta pública de una reparación con código temporal (SMTP simulado: no se envía nada real)."""
import re,unittest
from datetime import timedelta
from unittest.mock import patch
import test_app
import app,order_check
app.os.environ.setdefault('LOGIN_CAPTCHA','off')


class OrderCheckTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def order(self):
        cookie,csrf=self.login()
        oid=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','brand':'HP','model':'ProBook','request_key':'order-check-0001'}),cookie=cookie,csrf=csrf)['body']['id']
        with app.connect() as c:return oid,c.execute('SELECT code FROM orders WHERE id=?',(oid,)).fetchone()[0]

    def ask(self,code,sent):
        with patch.object(app.mail_pro,'configured',return_value=True),patch.object(app,'send_verification_code',side_effect=lambda *mail:sent.append(mail)),patch.object(app.time,'sleep'):
            return self.request('/api/public/adi/order/request',{'order':code})

    def test_code_goes_only_to_the_registered_mail(self):
        oid,code=self.order();sent=[]
        real=self.ask(code.lower(),sent);ghost=self.ask('PCD-20200101-9999',sent)
        # Misma respuesta exista o no la orden; solo la real genera un correo, y la respuesta no contiene datos de la orden.
        self.assertEqual((real['status'],ghost['status'],real['body']['message']),(200,200,ghost['body']['message']))
        self.assertEqual(set(real['body']),set(ghost['body']));self.assertEqual(len(sent),1);self.assertEqual(sent[0][0],'cliente@example.invalid')
        self.assertNotIn('cliente@',str(real['body']));self.assertNotIn('HP',str(real['body']))
        secret=sent[0][1];self.assertRegex(secret,r'^\d{6}$');self.assertEqual(sent[0][2],order_check.CODE_MINUTES)
        verify=lambda token,value:self.request('/api/public/adi/order/verify',{'token':token,'code':value})
        self.assertEqual(verify(ghost['body']['token'],secret)['status'],400)
        self.assertEqual(verify(real['body']['token'],'000000' if secret!='000000' else '111111')['status'],400)
        found=verify(real['body']['token'],secret)
        self.assertEqual((found['status'],found['body']['order']['code'],found['body']['order']['status']),(200,code,'En espera'))
        # Sin datos personales en la respuesta, y el código es de un solo uso.
        self.assertFalse({'client','name','email','phone','identification','id'}&set(found['body']['order']));self.assertNotIn('Cliente ficticio',str(found['body']))
        self.assertEqual(verify(real['body']['token'],secret)['status'],400)
        with app.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='order_checked_by_client' AND entity_id=?",(oid,)).fetchone()[0],1)
        # El envío queda registrado sin el código, y en la base solo hay su huella.
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='verification_code_sent' AND entity_id=?",(oid,)).fetchone()[0],1)
            self.assertFalse([row for row in c.execute('SELECT code_hash FROM order_checks') if secret in row[0]])

    def test_corporate_template(self):
        import verification_mail
        config={'username':'seguridad@example.invalid'}
        message=verification_mail.build(config,'cliente@example.invalid','048213',10,'en el chat de ADI donde lo solicitaste','Consulta de la orden N.º PCD-20260101-0001')
        self.assertEqual((message['Subject'],message['From'],message['To']),('Tu código de verificación | PC-DOCTOR S.A.','"PC-DOCTOR S.A. · Seguridad" <seguridad@example.invalid>','cliente@example.invalid'))
        text=message.get_body(('plain',)).get_content();page=message.get_body(('html',)).get_content()
        self.assertIn('    048213',text);self.assertIn('Caduca en 10 minutos',text)
        for digit in '048213':self.assertIn('>'+digit+'</td>',page)
        for needed in ('Verifica tu correo electrónico','Caduca en 10 minutos','https://','/static/logo-firma.png','role="presentation"'):self.assertIn(needed,page)
        for banned in ('<script','<style','javascript:','http://','123456','password','contraseña:'):self.assertNotIn(banned,page.lower())
        with self.assertRaises(ValueError):verification_mail.build(config,'cliente@example.invalid','12345',10,'aquí')

    def test_attempts_expiry_and_limits(self):
        oid,code=self.order();sent=[]
        token=self.ask(code,sent)['body']['token'];secret=sent[0][1]
        with app.connect() as c:
            now=app.reception_now()
            for _ in range(order_check.MAX_ATTEMPTS):self.assertIsNone(order_check.verify(c,token,'12345x',now))
            # Agotados los intentos, ni el código correcto sirve.
            self.assertIsNone(order_check.verify(c,token,secret,now))
            fresh,mail=order_check.start(c,code,now);value=mail['code']
            self.assertIsNone(order_check.verify(c,fresh,value,now+timedelta(minutes=order_check.CODE_MINUTES+1)))
            self.assertEqual(order_check.verify(c,fresh,value,now+timedelta(minutes=order_check.CODE_MINUTES-1))['code'],code)
            # Sin correo válido en la orden no se envía nada, pero la respuesta es la misma.
            c.execute("UPDATE clients SET email=''");self.assertIsNone(order_check.start(c,code,now)[1])
        # Límite por orden: tres códigos cada media hora (ya se pidió uno por la ruta).
        self.assertEqual([self.ask(code,sent)['status'] for _ in range(3)],[200,200,429])
        # El chat ya no entrega el estado con número y cédula: remite a la verificación.
        with patch.object(app.adi,'reply',return_value='respuesta'):
            said=self.request('/api/public/adi/message',{'message':'estado de '+code+' cédula 0100000017'})['body']['messages'][-1]['content']
        self.assertIn('código temporal',said);self.assertNotIn('En espera',said)

    def test_unavailable_without_mail(self):
        with patch.object(app.mail_pro,'configured',return_value=False):
            self.assertEqual(self.request('/api/public/adi/order/request',{'order':'PCD-20200101-0001'})['status'],503)
        self.assertEqual(self.request('/api/public/adi/order/request',{'order':''})['status'],400)


if __name__=='__main__':unittest.main()
