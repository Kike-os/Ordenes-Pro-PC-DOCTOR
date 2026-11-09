"""Recepción técnica estructurada y evidencia fotográfica (1.5.262, datos ficticios, base temporal).

Inspección por zonas según el tipo de equipo, «Sin daños visibles» excluyente, cargador con estados y daños (y la nota automática cuando no
se entrega), accesorios con cantidad y estado, textos compuestos para el comprobante sin borrar lo escrito, nombres descriptivos de fotos,
categorías y observaciones, marcas sobre una copia (el original no cambia) y eliminación que conserva el historial."""
import base64
import json
import unittest

import reception_details as rd
import test_app
import app

JPEG = b'\xff\xd8\xff\xe0' + bytes(range(256)) * 2 + b'\xff\xd9'
MARKED = b'\xff\xd8\xff\xe1' + bytes(reversed(range(256))) * 2 + b'\xff\xd9'


class ReceptionRules(unittest.TestCase):
    def test_zones_depend_on_device_and_exclusive_no_damage(self):
        laptop, errors = rd.parse({'damages': [{'code': 'bisagra_floja', 'location': 'Izquierda'}, {'code': 'pantalla_pixeles', 'location': 'Zona central'}]}, 'portatil')
        self.assertEqual(([d['code'] for d in laptop['damages']], errors), (['bisagra_floja', 'pantalla_pixeles'], {}))
        desktop, _ = rd.parse({'damages': [{'code': 'bisagra_floja'}, {'code': 'touchpad_danado'}, {'code': 'puerto_usb'}]}, 'escritorio')
        self.assertEqual([d['code'] for d in desktop['damages']], ['puerto_usb'])  # bisagras y touchpad no aplican a un PC de escritorio
        _, errors = rd.parse({'damages': [{'code': 'sin_danos'}, {'code': 'golpes_rayones'}]}, 'portatil')
        self.assertIn('Sin daños visibles', errors['physical_condition'])
        self.assertEqual(rd.parse('{malo', 'portatil')[1].keys(), {'reception_details'})
        self.assertEqual(rd.parse('', 'portatil'), (None, {}))

    def test_charger_and_accessories(self):
        _, errors = rd.parse({'charger': {'status': 'con_danos'}}, 'portatil')
        self.assertEqual(errors['charger'], 'Indica qué daño tiene el cargador.')
        details, errors = rd.parse({'charger': {'status': 'con_danos', 'defects': ['cable', 'punta'], 'brand': 'HP', 'power': '65 W', 'voltage': '19,5 V', 'serial': 'ABC-123'},
                                    'accessories': [{'code': 'mouse_receptor', 'qty': 1, 'state': 'buen_estado'}, {'code': 'otro', 'label': 'Base refrigerante', 'qty': 2, 'state': 'con_danos', 'note': 'Ventilador suelto'},
                                                    {'code': 'inventado', 'qty': 1}]}, 'portatil')
        self.assertEqual(errors, {})
        self.assertEqual(rd.charger_text(details), 'Cargador: recibido con daños (cable pelado, cortado o deteriorado; punta de carga rota, doblada o floja) · marca HP, potencia 65 W, voltaje 19,5 V, S/N ABC-123.')
        self.assertEqual(rd.accessories_text(details), 'Mouse y receptor USB (buen estado aparente), Base refrigerante ×2 (con daños: Ventilador suelto)')
        none, _ = rd.parse({'charger': {'status': 'no_entregado', 'brand': 'HP'}}, 'portatil')
        self.assertEqual(rd.charger_text(none), rd.NO_CHARGER_NOTE)
        self.assertNotIn('brand', none['charger'])  # sin cargador no se guardan sus datos
        self.assertEqual(rd.parse({'charger': {'status': 'buen_estado'}}, 'ssd')[0]['charger'], None)  # una unidad SSD no tiene cargador
        _, errors = rd.parse({'accessories': [{'code': 'funda', 'qty': 40}]}, 'portatil')
        self.assertIn('entre 1 y 20', errors['accessories'])

    def test_texts_keep_what_the_technician_wrote(self):
        details, _ = rd.parse({'damages': [{'code': 'pantalla_rayas', 'location': 'Borde superior'}, {'code': 'pantalla_rota'}, {'code': 'faltan_tornillos'}],
                               'charger': {'status': 'no_entregado'}}, 'portatil')
        self.assertEqual(rd.inspection_text(details), 'Inspección inicial: Pantalla: con rayas (Borde superior), rota; Tornillos, tapas y gomas: Faltan tornillos.')
        merged = rd.merge_condition('Inspección inicial: algo viejo.\nEl cliente indica que se cayó.', details)
        self.assertEqual(merged.split('\n'), [rd.inspection_text(details), rd.NO_CHARGER_NOTE, 'El cliente indica que se cayó.'])
        self.assertEqual(rd.merge_condition(merged, details), merged)  # componer dos veces no duplica
        self.assertEqual(rd.photo_filename('PCD-20261109-0001', 'HP', '240 G7', 'Pantalla', 1), 'PCD-20261109-0001_HP_240-G7_Pantalla_01.jpg')
        self.assertEqual(rd.photo_filename('PCD-20261109-0001', 'Lenovo', 'ThinkPad T14 «Gen 2»', 'Tornillos, tapas y gomas', 12), 'PCD-20261109-0001_Lenovo_ThinkPad-T14-Gen-2_Tornillos-tapas-y-gomas_12.jpg')


class ReceptionRoutes(test_app.SecurityTests):
    def create(self, cookie, csrf, details, key='rx-0001', **extra):
        data = self.order_data(dict({'request_key': 'reception-details-' + key, 'physical_condition': 'El cliente indica que se cayó.', 'accessories': ''}, **extra))
        data['reception_details'] = json.dumps(details)
        return self.request('/api/orders', data, cookie=cookie, csrf=csrf)

    def test_order_keeps_structured_reception_and_composed_texts(self):
        cookie, csrf = self.login()
        details = {'damages': [{'code': 'golpes_rayones', 'location': 'Tapa superior'}], 'charger': {'status': 'no_entregado'},
                   'accessories': [{'code': 'funda', 'qty': 1, 'state': 'con_danos', 'note': 'Cierre roto'}]}
        made = self.create(cookie, csrf, details)
        self.assertIn(made['status'], (200, 201), made['body'])
        oid = made['body']['id']
        order = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']
        self.assertEqual(order['reception']['damages'], [{'code': 'golpes_rayones', 'location': 'Tapa superior'}])
        self.assertTrue(order['physical_condition'].startswith('Inspección inicial: Carcasa: Golpes o rayones (Tapa superior).'))
        self.assertIn(rd.NO_CHARGER_NOTE, order['physical_condition']);self.assertIn('El cliente indica que se cayó.', order['physical_condition'])
        self.assertEqual(order['accessories'], 'Funda (con daños: Cierre roto)')
        bad = self.create(cookie, csrf, {'damages': [{'code': 'sin_danos'}, {'code': 'pantalla_rota'}]}, key='rx-0002')
        self.assertEqual(bad['status'], 400);self.assertIn('physical_condition', bad['body']['fields'])
        options = self.request('/api/reception-options', cookie=cookie)['body']
        self.assertIn('reception_catalog', options);self.assertEqual(options['reception_catalog']['no_charger_note'], rd.NO_CHARGER_NOTE)

    def test_photos_have_metadata_marked_copy_and_deletions_keep_history(self):
        cookie, csrf = self.login()
        oid = self.create(cookie, csrf, {'damages': [{'code': 'sin_danos'}]}, key='rx-0003', brand='HP', model='240 G7')['body']['id']
        post = lambda **body: self.request('/api/orders/%d/photos' % oid, body, cookie=cookie, csrf=csrf)
        first = post(data=base64.b64encode(JPEG).decode(), category='recepcion', subject='Pantalla', note='Rayón vertical', main=True, annotated=base64.b64encode(MARKED).decode())
        self.assertEqual(first['status'], 201, first['body'])
        code = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']['code']
        self.assertEqual(first['body']['filename'], code + '_HP_240-G7_Pantalla_01.jpg')
        second = post(data=base64.b64encode(JPEG).decode(), category='diagnostico', subject='Pantalla')
        self.assertTrue(second['body']['filename'].endswith('_Pantalla_02.jpg'))
        pid = first['body']['id']
        self.assertEqual(self.request('/api/order-photo/%d' % pid, cookie=cookie)['body'], JPEG)  # el original no cambia
        self.assertEqual(self.request('/api/order-photo/%d?marcas=1' % pid, cookie=cookie)['body'], MARKED)  # la copia marcada aparte
        self.assertEqual(post(action='meta', photo_id=str(pid), category='reparacion', subject='Bisagras', note='Ajustada')['status'], 200)
        self.assertEqual(post(action='annotate', photo_id=str(pid), data=base64.b64encode(b'no-jpeg').decode())['status'], 400)
        self.assertEqual(post(action='delete', photo_id=str(pid), reason='x')['status'], 400)  # el motivo es obligatorio
        self.assertEqual(post(action='delete', photo_id=str(pid), reason='Foto repetida (prueba)')['status'], 200)
        order = self.request('/api/orders/%d' % oid, cookie=cookie)['body']['order']
        self.assertEqual([p['id'] for p in order['photos']], [second['body']['id']])
        self.assertEqual(order['photos'][0]['is_main'], 1)  # la principal pasa a la siguiente foto activa
        hist = order['photos_deleted'][0]
        self.assertEqual((hist['id'], hist['delete_reason'], hist['category'], hist['subject']), (pid, 'Foto repetida (prueba)', 'reparacion', 'Bisagras'))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_photos WHERE order_id=?', (oid,)).fetchone()[0], 2)  # nada se borró de la base
        self.assertEqual(self.request('/api/order-photo/%d' % pid, cookie=cookie)['status'], 200)  # administración la sigue viendo


for name in [name for name in dir(test_app.SecurityTests) if name.startswith('test_')]:
    setattr(ReceptionRoutes, name, None)

if __name__ == '__main__':
    unittest.main()
