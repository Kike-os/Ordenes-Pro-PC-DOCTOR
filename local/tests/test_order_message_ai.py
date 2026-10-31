"""Herramientas del panel ADI con los datos de la orden (proveedor SIMULADO, datos ficticios, base temporal; nada sale a la red).
Comprueba qué viaja a la IA y qué no, el mensaje completo que arma el sistema, los controles contra datos inventados y la relación con WhatsApp."""
import json
import unittest
from unittest.mock import patch

import test_invoicing
import app
import adi_ai
import order_followups

KEY = {'ANTHROPIC_API_KEY': 'clave-ficticia', 'OPENAI_API_KEY': '', 'OPEN_API_KEY': ''}
GOOD = ('Le informamos que su computadora portátil HP presenta daños físicos en el panel de visualización, los cuales afectan su funcionamiento.\n\n'
        'Como solución técnica, recomendamos sustituir la pantalla por un componente compatible con las especificaciones del fabricante.')
NOTE = 'Laptop HP pantalla rota, hay que cambiar, no sirve'


class OrderMessageAiTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order = Base.form, Base.prepare, Base.paid_order

    def ask(self, post, oid, answer=GOOD, **extra):
        sent = []

        def fake(url, payload, headers):
            sent.append(payload)
            return {'content': [{'type': 'text', 'text': answer}], 'usage': {'input_tokens': 10, 'output_tokens': 5}}
        with patch.dict(app.os.environ, KEY), patch.object(adi_ai, '_post', side_effect=fake):
            r = post('/api/adi/write', **dict({'text': NOTE, 'mode': 'mensaje', 'selection': 'manual', 'order_id': str(oid)}, **extra))
        return r, sent

    def test_only_technical_data_reaches_the_provider(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False, key='ai01')
        oid = order['id']
        post('/api/orders/%d/followups' % oid, kind='diagnostico', internal_note='NOTA-INTERNA-SECRETA clave: 1234', client_message='Detectamos fallas en la bisagra.')
        with app.connect() as c:
            c.execute("UPDATE orders SET findings='HALLAZGO-INTERNO con sulfato' WHERE id=?", (oid,))
            c.commit()
            client = order_followups._order(c, oid)['client']
        note = 'Pantalla rota. %s llamó al 0991234567, correo luis@example.invalid, clave: abc123, cédula 1712345678' % client
        r, sent = self.ask(post, oid, text=note, selection='auto')
        self.assertEqual(r['status'], 200, r['body'])
        prompt = json.dumps(sent[0], ensure_ascii=False)
        for secret in ('NOTA-INTERNA-SECRETA', 'HALLAZGO-INTERNO', order['code'], client, '0991234567', 'luis@example.invalid', 'abc123', '1712345678', 'clave-ficticia'):
            self.assertNotIn(secret, prompt, secret)
        self.assertIn('Detectamos fallas en la bisagra', prompt)  # el seguimiento comunicable sí
        self.assertIn('Pantalla rota', prompt)
        self.assertIn('[teléfono omitido]', prompt)
        # El diagnóstico interno solo viaja si el técnico lo marca; las notas internas, nunca.
        r, sent = self.ask(post, oid, findings='1')
        prompt = json.dumps(sent[0], ensure_ascii=False)
        self.assertIn('HALLAZGO-INTERNO', prompt)
        self.assertNotIn('NOTA-INTERNA-SECRETA', prompt)
        with app.connect() as c:
            row = c.execute("SELECT details FROM adi_actions WHERE action='writing_improve' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(json.loads(row['details'])['mode'], 'mensaje')
        self.assertNotIn('Pantalla', row['details'])  # el registro de uso no guarda el texto

    def test_the_system_adds_what_the_ai_cannot_decide(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False, key='ai02')
        oid = order['id']
        r, _ = self.ask(post, oid)
        self.assertEqual(r['status'], 200, r['body'])
        body = r['body']['suggestion']
        self.assertTrue(body.startswith('Estimado/a '))
        self.assertIn('Reciba un cordial saludo de PC-DOCTOR.', body)
        self.assertIn('Orden de servicio: ' + order['code'], body)
        self.assertIn('presenta daños físicos', body)
        self.assertIn(order_followups.AI_CLOSING, body)  # recomienda: se continúa solo con autorización
        self.assertIn('Departamento Técnico – PC-DOCTOR', body)
        self.assertLess(body.index('Reciba'), body.index('presenta'))
        # Sin registrar nada: generar no es comunicar.
        self.assertEqual(self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['messages'], [])
        # Una novedad sin recomendación no pide autorización.
        plain, _ = self.ask(post, oid, answer='Su equipo presenta un conector de carga flojo.', text='pin de carga flojo')
        self.assertNotIn(order_followups.AI_CLOSING, plain['body']['suggestion'])
        # El valor lo pone el sistema según las reglas, no la IA.
        with_cost, sent = self.ask(post, oid, cost='1')
        self.assertIn('Valor autorizado: $105,00.', with_cost['body']['suggestion'])
        self.assertNotIn('105', json.dumps(sent[0]['messages'], ensure_ascii=False))
        # Sin orden: saludo general, sin datos de ninguna orden.
        free, sent = self.ask(post, oid, order_id='')
        self.assertTrue(free['body']['suggestion'].startswith('Estimado/a cliente:'))
        self.assertNotIn('Orden de servicio', free['body']['suggestion'])

    def test_invented_data_is_rejected_or_flagged(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False, key='ai03')
        oid = order['id']
        r, _ = self.ask(post, oid, answer='La reparación cuesta $80,00 y queda lista.')
        self.assertEqual((r['status'], r['body']['kind']), (422, 'inventado'))
        r, _ = self.ask(post, oid, answer='Su equipo requiere una unidad SSD NVMe 980 PRO de 2TB con garantía de 12 meses.')
        self.assertEqual(r['status'], 200)
        warned = ' '.join(r['body']['warnings'])
        self.assertIn('2TB', warned)
        self.assertIn('garantía', warned)
        r, _ = self.ask(post, oid, answer='Hemos reemplazado la pantalla de su equipo.')
        self.assertIn('hemos reemplazado', ' '.join(r['body']['warnings']))  # «hay que cambiar» no es un trabajo hecho
        r, _ = self.ask(post, oid, answer='Se midió 19.5V en el conector.', text='medí 19.5V en el jack, serie 5CD1234ABC')
        self.assertIn('5CD1234ABC', ' '.join(r['body']['warnings']))  # dato omitido de las anotaciones
        self.assertNotIn('19.5V', ' '.join(r['body']['warnings']))
        # Un dato real al final de una frase no cuenta como inventado.
        r, _ = self.ask(post, oid, answer='Se midió 19.5V y el costo anotado es $45.50.', text='medí 19.5V, costo $45.50')
        self.assertEqual((r['status'], r['body'].get('warnings')), (200, None))
        # La redacción técnica profesional pasa por los mismos controles.
        r, _ = self.ask(post, oid, mode='tecnica', answer='Costo final de $99,00.')
        self.assertEqual(r['status'], 422)

    def test_tools_validation_and_permissions(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False, key='ai04')
        oid = order['id']
        with patch.dict(app.os.environ, {'ANTHROPIC_API_KEY': '', 'OPENAI_API_KEY': '', 'OPEN_API_KEY': ''}), patch.object(adi_ai, '_post', side_effect=AssertionError('no debe consultar')):
            none = post('/api/adi/write', text=NOTE, mode='mensaje')
            self.assertEqual((none['status'], none['body']['kind']), (503, 'configuracion'))
        empty, sent = self.ask(post, oid, text='')
        self.assertEqual((empty['status'], sent), (400, []))
        self.assertEqual(self.ask(post, oid, mode='otra')[0]['status'], 400)
        self.assertEqual(self.ask(post, oid, order_id='999999')[0]['status'], 404)
        with patch.dict(app.os.environ, KEY):
            modes = [m['code'] for m in self.request('/api/adi/status', cookie=cookie)['body']['writing']['modes']]
        self.assertEqual(modes[:2], ['mensaje', 'tecnica'])
        # Las herramientas sobre un mensaje completo reescriben solo el cuerpo y conservan saludo, orden y firma.
        draft = self.ask(post, oid)[0]['body']['suggestion']
        with app.connect() as c:
            client = order_followups._order(c, oid)['client']
        for mode, words in (('ampliar', 'Máximo 180'), ('simple', 'Máximo 55'), ('tecnica', 'lenguaje técnico avanzado'), ('cliente', 'sin conocimientos técnicos')):
            r, sent = self.ask(post, oid, mode=mode, text=draft, answer='Su computadora portátil HP presenta daños en el panel de visualización.')
            self.assertEqual(r['status'], 200, r['body'])
            content = sent[0]['messages'][0]['content']
            self.assertIn(words, content)
            self.assertIn('panel de visualización', content)
            for hidden in (order['code'], client.split()[0], 'Departamento Técnico', 'Estimado'):
                self.assertNotIn(hidden, content.split('<texto>')[1], hidden)
            self.assertTrue(r['body']['suggestion'].startswith('Estimado/a '), mode)
            self.assertIn('Departamento Técnico – PC-DOCTOR', r['body']['suggestion'])
        # La glosa técnica acompaña a la redacción técnica profesional, también sin orden.
        r, sent = self.ask(post, oid, mode='tecnica', order_id='', answer='Pantalla con daños físicos.')
        self.assertIn('placa base', sent[0]['system'])
        self.assertEqual(self.request('/api/adi/write', {'text': NOTE, 'mode': 'mensaje'})['status'], 401)

    def test_prepared_for_whatsapp_only_when_the_technician_decides(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False, key='ai05')
        oid = order['id']
        body = self.ask(post, oid)[0]['body']['suggestion']
        edited = body + '\nTexto corregido por el técnico.'
        r = post('/api/orders/%d/messages' % oid, action='prepare', channel='whatsapp_manual', body=edited, template='novedad', recipient='0991234567', request_key='mensaje-ia-whatsapp-01')
        self.assertEqual((r['status'], r['body']['message']['status']), (200, 'preparado'))
        self.assertIn('Texto corregido por el técnico.', r['body']['message']['body'])

    def test_redaction_keeps_technical_identifiers(self):
        text = adi_ai.redact('HP ProBook 440 G8 serie 5CD1234ABC, error 0x0000007B, 19.5V, tel 0991234567, Luis pidió revisar', ['Luis'])
        for keep in ('440 G8', '5CD1234ABC', '0x0000007B', '19.5V'):
            self.assertIn(keep, text)
        self.assertNotIn('0991234567', text)
        self.assertNotIn('Luis', text)


if __name__ == '__main__':
    unittest.main()
