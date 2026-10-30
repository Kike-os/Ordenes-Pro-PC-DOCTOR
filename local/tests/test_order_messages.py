"""Ventana «Comunicación con el cliente» (datos ficticios, base temporal, sin WhatsApp ni correo reales): recuperación del último seguimiento
comunicable sin notas internas, selección de varios seguimientos sin repetir frases, registros técnicos anteriores solo por elección expresa,
reglas del costo, espacios por completar, fuentes registradas, número correcto de WhatsApp, reintentos de correo y plantilla aprobada."""
import json
import unittest
from datetime import datetime
from unittest.mock import patch

import test_invoicing
import app
import mail_pro
import order_followups
import order_workspace

CONFIG = {'username': 'taller@example.invalid', 'password': 'x'}
WA = {'WHATSAPP_TOKEN': 'token-ficticio', 'WHATSAPP_PHONE_NUMBER_ID': '123456', 'WHATSAPP_TEMPLATE_NAME': 'novedad_orden'}


class OrderMessageTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order = Base.form, Base.prepare, Base.paid_order

    def followup(self, post, oid, **extra):
        body = dict(kind='diagnostico', internal_note='', client_message='', priority='normal')
        body.update(extra)
        made = post('/api/orders/%d/followups' % oid, **body)
        self.assertEqual(made['status'], 201, made['body'])
        return made['body']['id']

    def compose(self, post, oid, **extra):
        r = post('/api/orders/%d/messages' % oid, action='compose', **extra)
        self.assertEqual(r['status'], 200, r['body'])
        return r['body']

    def test_recovers_latest_communicable_followup_without_internal_notes(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False, key='msg1')
        oid = order['id']
        # Historial anterior: un comentario técnico (interno) y uno del sistema; ninguno se usa solo.
        post('/api/orders/%d/follow-up' % oid, comment='Cambio de batería realizado y respaldo de información (registro anterior).')
        with app.connect() as c:
            order_workspace.event(c, oid, self.uid, datetime.now().astimezone(), 'follow_up', 'Comprobante de recepción enviado por correo a cliente@example.invalid.')
            c.commit()
        first = self.followup(post, oid, kind='diagnostico', client_message='Detectamos fallas en la unidad de almacenamiento.', internal_note='SMART 197=48 (solo taller).',
                              recommendation='Recomendamos reemplazar la unidad de almacenamiento.')
        payment = self.followup(post, oid, kind='pago', client_message='Registramos su anticipo.')
        internal = self.followup(post, oid, kind='novedad', internal_note='Cliente difícil de contactar (solo taller).')
        data = self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']
        src = {(s['type'], s['id']): s for s in data['sources']}
        self.assertFalse(src[('followup', internal)]['communicable'])
        self.assertFalse(src[('followup', payment)]['auto'])  # un pago no se elige automáticamente
        self.assertTrue(src[('followup', first)]['auto'])
        history = [s for s in data['sources'] if s['type'] == 'history']
        self.assertEqual([h['summary'][:15] for h in history], ['Cambio de bater'])  # sin el aviso del sistema ni los eventos de los seguimientos nuevos
        self.assertFalse(history[0]['auto'])
        self.assertNotIn('SMART', json.dumps(data['sources']))
        r = self.compose(post, oid, template='diagnostico', selection='auto')
        self.assertIn('unidad de almacenamiento', r['body'])
        self.assertIn('Recomendamos reemplazar', r['body'])
        self.assertIn(order['code'], r['body'])
        for secret in ('SMART', 'difícil de contactar', 'batería', 'anticipo'):
            self.assertNotIn(secret, r['body'])
        self.assertEqual(r['sources'], [{'type': 'followup', 'id': first}])
        self.assertTrue(r['subject'].startswith('PC-DOCTOR · Orden %s' % order['code']))
        # Un seguimiento solo interno no se puede comunicar ni pidiéndolo.
        self.assertEqual(post('/api/orders/%d/messages' % oid, action='compose', template='novedad', selection='ids', followup_ids=str(internal))['status'], 400)
        # El registro anterior solo entra si se elige expresamente, con aviso.
        r = self.compose(post, oid, template='autorizacion', selection='ids', followup_ids=str(first), history_ids=str(history[0]['id']))
        self.assertLess(r['body'].index('Cambio de batería'), r['body'].index('unidad de almacenamiento'))  # orden cronológico
        self.assertTrue(any('internos' in w for w in r['warnings']))
        # Otra orden no puede usar estos seguimientos.
        _, _, post2, order2 = self.paid_order(5000, pay=False, key='msg1b')
        self.assertEqual(post2('/api/orders/%d/messages' % order2['id'], action='compose', template='novedad', selection='ids', followup_ids=str(first))['status'], 404)

    def test_several_news_without_repetition_and_cost_rules(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False, key='msg2')  # presupuesto aprobado de $105,00
        oid = order['id']
        a = self.followup(post, oid, kind='reparacion', client_message='Realizamos el cambio de batería. Hicimos el respaldo de su información.')
        b = self.followup(post, oid, kind='pruebas', client_message='Hicimos el respaldo de su información. Las pruebas de carga fueron correctas.')
        r = self.compose(post, oid, template='pruebas', selection='ids', followup_ids='%d,%d' % (a, b))
        self.assertEqual(r['body'].count('Hicimos el respaldo de su información'), 1)
        self.assertIn('Las pruebas de carga fueron correctas', r['body'])
        self.assertFalse(r['cost_included'])  # en «pruebas» el costo no va por defecto
        self.assertEqual((r['cost']['label'], r['cost']['amount']), ('Valor autorizado', '$105,00'))
        r = self.compose(post, oid, template='pruebas', selection='ids', followup_ids=str(a), cost='1')
        self.assertIn('Valor autorizado: $105,00.', r['body'])
        self.assertIn('Quedamos atentos a su respuesta.', r['body'])
        # Manual: sin seguimientos, con un espacio por completar que impide registrar o enviar.
        r = self.compose(post, oid, template='novedad', selection='manual')
        self.assertIn(order_followups.PLACEHOLDER, r['body'])
        self.assertEqual(r['sources'], [])
        bad = post('/api/orders/%d/messages' % oid, action='prepare', channel='copia', body=r['body'], request_key='mensaje-placeholder-01')
        self.assertEqual(bad['status'], 400)
        # Presupuesto en borrador: el valor no va salvo decisión expresa, y no se adjunta al correo.
        _, _, post3, order3 = self.paid_order(5000, pay=False, key='msg2b')
        oid3 = order3['id']
        quote = post3('/api/orders/%d/quote' % oid3)['body']['id']
        post3('/api/quotes/%d' % quote, action='save', items=[{'description': 'Disco ficticio', 'category': 'repuesto', 'quantity': 1, 'unit_cents': 7000, 'taxed': True}])
        f = self.followup(post3, oid3, kind='esperando_autorizacion', client_message='La unidad de almacenamiento presenta fallas.', quote_id=str(quote))
        r = self.compose(post3, oid3, template='autorizacion', selection='ids', followup_ids=str(f))
        self.assertTrue(r['cost']['draft'])
        self.assertFalse(r['cost_included'])
        self.assertNotIn('$70,00', r['body'])
        r = self.compose(post3, oid3, template='autorizacion', selection='ids', followup_ids=str(f), cost='1')
        self.assertIn('Costo propuesto: $70,00.', r['body'])
        self.assertTrue(any('borrador' in w for w in r['warnings']))
        with patch.object(mail_pro, 'configured', return_value=True):
            refused = post3('/api/orders/%d/messages' % oid3, action='email', body=r['body'], recipient='cliente@example.invalid', quote_id=str(quote), request_key='mensaje-borrador-0001')
        self.assertEqual(refused['status'], 400)

    def test_records_sources_recipient_and_real_results(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False, key='msg3')
        oid = order['id']
        f = self.followup(post, oid, kind='listo_entrega', client_message='Su equipo superó todas las pruebas.')
        text = self.compose(post, oid, template='listo', selection='auto')['body']
        used = json.dumps([{'type': 'followup', 'id': f}])
        manual = post('/api/orders/%d/messages' % oid, action='prepare', channel='whatsapp_manual', body=text, sources=used, recipient='099 123 4567', request_key='mensaje-manual-msg3-1')
        self.assertEqual(manual['status'], 200, manual['body'])
        self.assertEqual((manual['body']['message']['status'], manual['body']['message']['recipient']), ('preparado', '593991234567'))
        self.assertEqual(post('/api/orders/%d/messages' % oid, action='prepare', channel='whatsapp_manual', body=text, recipient='022345678', request_key='mensaje-manual-msg3-2')['status'], 400)  # fijo
        self.assertEqual(post('/api/orders/%d/messages' % oid, action='prepare', channel='copia', body=text, sources=json.dumps([{'type': 'followup', 'id': 999999}]), request_key='mensaje-manual-msg3-3')['status'], 404)
        messages = self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['messages']
        self.assertEqual((messages[0]['sources'], messages[0]['status_label'], messages[0]['followup_id']), ([{'type': 'followup', 'id': f}], 'Abierto en WhatsApp (manual, sin confirmación)', f))
        with app.connect() as c, self.assertRaises(Exception):
            c.execute("UPDATE order_messages SET sources='[]' WHERE id=?", (messages[0]['id'],))
        # Correo: el primer intento falla (queda fallido); el reintento con la misma clave sale y se registra como enviado, sin duplicar.
        calls = []

        def deliver(config, message, recipients):
            calls.append(message['Subject'])
            if len(calls) == 1:
                raise mail_pro.MailError('red', 'Sin conexión (ficticio)')
        with app.connect() as c:
            quote = order_followups._cost(c, oid)['quote_id']
        with patch.object(mail_pro, 'configured', return_value=True), patch.object(mail_pro, 'settings', return_value=CONFIG), patch.object(mail_pro, 'deliver', side_effect=deliver):
            args = dict(action='email', body=text, subject='Su equipo está listo · ' + order['code'], recipient='cliente@example.invalid', sources=used, quote_id=str(quote), request_key='mensaje-correo-msg3-1')
            first = post('/api/orders/%d/messages' % oid, **args)
            self.assertEqual((first['status'], first['body']['message']['status']), (502, 'error'))
            again = post('/api/orders/%d/messages' % oid, **args)
            self.assertEqual((again['status'], again['body']['message']['status'], again['body']['message']['attempts']), (200, 'enviado', 2))
            self.assertEqual(post('/api/orders/%d/messages' % oid, **args)['body']['duplicate'], True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(again['body']['message']['subject'], 'Su equipo está listo · ' + order['code'])
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM order_messages WHERE order_id=? AND channel='correo'", (oid,)).fetchone()[0], 1)

    def test_a_note_written_as_a_full_letter_keeps_only_its_content(self):
        letter = ('Estimado cliente:\nReciba un cordial saludo de parte del Departamento de Servicio Técnico de PC-DOCTOR S.A.\n'
                  'Detectamos fallas en la unidad de almacenamiento.\nRecomendamos reemplazarla.\nAgradecemos su confianza en nuestros servicios.\nPC-DOCTOR S.A.')
        self.assertEqual(order_followups._strip_letter(letter), 'Detectamos fallas en la unidad de almacenamiento.\nRecomendamos reemplazarla.')
        self.assertEqual(order_followups._strip_letter('Cambio de batería realizado.'), 'Cambio de batería realizado.')

    def test_whatsapp_numbers_template_and_status_never_regresses(self):
        for raw, expected in (('0991234567', '593991234567'), ('991234567', '593991234567'), ('+593 99 123 4567', '593991234567'), ('59309912345678', ''),
                              ('022345678', ''), ('5932234567', ''), ('+34 612 345 678', '34612345678'), ('', '')):
            self.assertEqual(order_followups.ecuador_number(raw), expected, raw)
        cookie, csrf, post, order = self.paid_order(10500, pay=False, key='msg4')
        oid = order['id']
        calls = []

        def fake(url, headers, payload):
            calls.append(payload)
            return 200, {'messages': [{'id': 'wamid.PLANTILLA1'}]}
        with patch.dict(app.os.environ, WA), patch.object(order_followups, 'TRANSPORT', fake):
            self.assertEqual(self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['whatsapp']['template'], 'novedad_orden')
            r = post('/api/orders/%d/messages' % oid, action='whatsapp', mode='template', recipient='0991234567', request_key='mensaje-plantilla-0001')
            self.assertEqual((r['status'], r['body']['message']['status'], r['body']['message']['provider_id']), (200, 'enviado', 'wamid.PLANTILLA1'))
        self.assertEqual(calls[0]['type'], 'template')
        self.assertEqual([p['text'] for p in calls[0]['template']['components'][0]['parameters']][1], order['code'])
        self.assertIn('novedad_orden', r['body']['message']['body'])
        with app.connect() as c:
            c.execute("UPDATE order_messages SET status='leido' WHERE provider_id='wamid.PLANTILLA1'")
            raw = json.dumps({'entry': [{'changes': [{'value': {'statuses': [{'id': 'wamid.PLANTILLA1', 'status': 'failed'}]}}]}]}).encode()
            import hashlib
            import hmac
            sign = 'sha256=' + hmac.new(b'secreto-ficticio', raw, hashlib.sha256).hexdigest()
            self.assertEqual(order_followups.webhook_status(c, raw, sign, datetime.now().astimezone(), env={'WHATSAPP_APP_SECRET': 'secreto-ficticio'}), 0)


if __name__ == '__main__':
    unittest.main()
