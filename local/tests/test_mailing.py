"""Correos institucionales: plantilla común, firma, revisión de ADI con datos protegidos, copia exacta, historial y vinculación automática."""
import unittest
from unittest.mock import patch
import test_app
import app,mailing,mail_pro,adi_ai
app.os.environ.setdefault('LOGIN_CAPTCHA','off')
CONFIG={'username':'taller@example.invalid','password':'x'}
BODY=('Estimado/a Juan Pérez:\n\nle confirmamos que su equpo fue recibido correctamente en nuestro centro, orden PCD-20261013-0001 el 13/10/2026 a las 10:30.\n\n'
      'Orden: PCD-20261013-0001\nTotal: $35,00\n\nIngrese al siguiente enlace:\nhttps://example.invalid/presupuesto/abc123\n\nAtentamente,\n\nDepartamento de Servicio Técnico\nPC-DOCTOR S.A.')


class TemplateTests(unittest.TestCase):
    def test_blocks_and_institutional_layout(self):
        kinds=[kind for kind,_ in mailing.blocks(BODY)]
        self.assertEqual(kinds,['greeting','text','facts','text','closing','closing'])
        page=mailing.html(BODY,'Confirmación de recepción','<table id="firma"></table>')
        # Encabezado textual sin logotipo, texto justificado con alternativa para pantallas pequeñas, datos en tabla y firma al final.
        head=page.split('Estimado/a')[0];self.assertIn('PC-DOCTOR S.A.',head);self.assertIn('Confirmación de recepción',head);self.assertNotIn('<img',head)
        for needed in ('text-align:justify','.op-j{text-align:left!important}','max-width:600px','role="presentation"','<td valign="top" width="38%"','$35,00','href="https://example.invalid/presupuesto/abc123"','Atentamente,','id="firma"'):self.assertIn(needed,page)
        self.assertNotIn('Departamento de Servicio Técnico',page)   # la firma institucional sustituye a la despedida escrita a mano
        self.assertLess(page.index('Atentamente,'),page.index('id="firma"'));self.assertNotIn('  ',mailing.html('Hola:\n\nTexto con <b>marcas</b> & símbolos.','T').split('<body')[1].split('Texto')[1][:40])
        self.assertIn('&lt;b&gt;marcas&lt;/b&gt; &amp;',mailing.html('Hola:\n\nTexto con <b>marcas</b> & símbolos.','T'))
        self.assertIn('Departamento de Servicio Técnico',mailing.html(BODY,'T'))  # sin firma configurada se conserva la despedida


class ReviewTests(unittest.TestCase):
    setUpClass=classmethod(test_app.SecurityTests.setUpClass.__func__);setUp=test_app.SecurityTests.setUp;tearDown=test_app.SecurityTests.tearDown;request=test_app.SecurityTests.request;login=test_app.SecurityTests.login;order_data=test_app.SecurityTests.order_data

    def review(self,answer):
        calls=[]
        def fake(system,user):
            calls.append(user);return (answer(user) if callable(answer) else answer,5,5)
        with patch.dict(app.os.environ,{'ANTHROPIC_API_KEY':'','OPENAI_API_KEY':'k'}),patch.object(adi_ai,'_complete',side_effect=fake),app.connect() as c:
            result=mailing.review(c,BODY,app.reception_now());again=mailing.review(c,BODY,app.reception_now());c.commit()
        return result,again,calls

    def test_review_fixes_prose_keeps_data_and_is_cached(self):
        fix=lambda user:user.replace('le confirmamos que su equpo fue recibido','Le confirmamos que su equipo fue recibido').replace('Ingrese al siguiente enlace:','Ingrese al siguiente enlace seguro:')
        (text,state),(again,state2),calls=self.review(fix)
        self.assertEqual((state,state2,len(calls)),('revisado','revisado',1))   # la segunda vez sale de la memoria: no se consulta de nuevo
        self.assertIn('Le confirmamos que su equipo fue recibido',text);self.assertEqual(text,again)
        # A la IA no viajan el nombre, los datos de la tabla, los códigos, importes, fechas ni enlaces.
        for hidden in ('Juan Pérez','PCD-20261013-0001','$35,00','13/10/2026','10:30','example.invalid','Departamento'):self.assertNotIn(hidden,calls[0])
        self.assertIn('⟦1⟧',calls[0])
        for kept in ('Estimado/a Juan Pérez:','orden PCD-20261013-0001 el 13/10/2026 a las 10:30','Orden: PCD-20261013-0001\nTotal: $35,00','https://example.invalid/presupuesto/abc123','Atentamente,\n\nDepartamento de Servicio Técnico'):self.assertIn(kept,text)

    def test_unsafe_or_failed_review_falls_back_to_the_template(self):
        for answer in ('[1] Su equipo fue recibido.\n[2] Ingrese al enlace:',                       # perdió los marcadores de datos
                       '[1] le confirmamos ⟦1⟧ ⟦2⟧ ⟦3⟧ y además le regalamos un descuento del ⟦9⟧',  # inventa un marcador
                       'Texto sin numerar','',                                                        # formato inesperado o vacío
                       lambda user:(_ for _ in ()).throw(adi_ai.AdiError('conexion','caído',504))):   # proveedor caído
            with self.subTest(answer=str(answer)[:30]):
                self.tearDown();self.setUp()
                (text,state),_,_=self.review(answer);self.assertEqual((text,state),(BODY,'plantilla'))
        # Sin proveedor, con la asistencia desactivada o con la revisión de correos desactivada, tampoco se consulta.
        with app.connect() as c:
            self.assertEqual(mailing.review(c,BODY,app.reception_now())[1],'plantilla')
            with patch.dict(app.os.environ,{'ANTHROPIC_API_KEY':'','OPENAI_API_KEY':'k'}),patch.object(adi_ai,'_complete',side_effect=AssertionError('no debe llamarse')):
                adi_ai.save_correction(c,{'mail_review':False});self.assertEqual(mailing.review(c,BODY,app.reception_now())[1],'plantilla')

    def test_send_archives_exact_copy_links_order_and_shows_history(self):
        cookie,csrf=self.login();sent=[]
        order=self.request('/api/orders',self.order_data({'email':'cliente@example.invalid','request_key':'mailing-archive-request-0001'}),cookie=cookie,csrf=csrf)['body']
        fix=lambda user:user.replace('le confirmamos que su equpo','Le confirmamos que su equipo')
        with patch.object(mail_pro,'configured',return_value=True),patch.object(mail_pro,'settings',return_value=CONFIG),patch.object(mail_pro,'deliver',side_effect=lambda config,message,recipients:sent.append(message)),\
             patch.dict(app.os.environ,{'ANTHROPIC_API_KEY':'','OPENAI_API_KEY':'k'}),patch.object(adi_ai,'_complete',side_effect=lambda system,user:(fix(user),5,5)):
            with app.connect() as c:
                done=app.send_institutional(c,'quote','Presupuesto de servicio','cliente@example.invalid','PC-DOCTOR S.A. | Presupuesto',BODY,order['id'],None,private=('https://example.invalid/presupuesto/abc123',))
                with patch.object(mail_pro,'deliver',side_effect=mail_pro.MailError('smtp','El servidor rechazó el mensaje.')):
                    with self.assertRaises(mail_pro.MailError):app.send_institutional(c,'stay','Aviso','cliente@example.invalid','Asunto de prueba','Hola:\n\nTexto breve.',order['id'],None,review=False)
        self.assertEqual(done['adi'],'revisado');page=sent[0].get_body(('html',)).get_content();plain=sent[0].get_body(('plain',)).get_content()
        self.assertIn('Le confirmamos que su equipo',plain);self.assertIn('https://example.invalid/presupuesto/abc123',plain);self.assertIn('Enrique',page)   # firma institucional incorporada una sola vez
        self.assertEqual(page.count('border-bottom:3px solid #e03a3e'),1)
        detail=self.request('/api/orders/%d'%order['id'],cookie=cookie)['body'];detail=detail.get('order',detail)
        history=detail['mail_history'];self.assertEqual([(row['status'],row['adi'],row['kind_label']) for row in history],[('error','plantilla','Aviso de permanencia'),('enviado','revisado','Presupuesto')])
        self.assertIn(done['message_id'],[row['message_id'] for row in app.connect().execute('SELECT message_id FROM mail_links WHERE order_id=?',(order['id'],))])
        copy=self.request('/api/sent-mail/%d'%done['archive_id'],cookie=cookie)['body']['mail']
        # Copia exacta de lo enviado, salvo el enlace privado de un solo uso.
        self.assertEqual(copy['text'],plain.replace('https://example.invalid/presupuesto/abc123','[enlace privado omitido en la copia]'));self.assertEqual((copy['adi'],copy['order_code']),('revisado',order['code']))
        view=self.request(copy['view_url'],cookie=cookie);self.assertEqual(view['status'],200);self.assertIn('Presupuesto de servicio',view['body']);self.assertNotIn('abc123',view['body'])
        self.assertEqual(self.request('/api/sent-mail/%d'%done['archive_id'])['status'],401);self.assertEqual(self.request('/correo/999999',cookie=cookie)['status'],404)
        with app.connect() as c:
            for sql in ("UPDATE mail_archive SET body_text='x'","UPDATE mail_archive SET adi='revisado'","DELETE FROM mail_archive"):
                with self.assertRaises(Exception):c.execute(sql)


if __name__=='__main__':unittest.main()
