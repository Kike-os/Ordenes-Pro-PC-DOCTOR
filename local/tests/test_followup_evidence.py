"""Evidencias de hasta 10 MiB por partes (datos ficticios, base temporal): límites exactos, tipo real por sus primeros bytes, original con
su SHA-256 intacto y miniatura aparte, privacidad en el enlace público y en la API, visibilidad y retiro con registro, reintentos sin
duplicar, cargas incompletas que no producen evidencias, borrador del seguimiento, límite configurable, permisos y evidencias anteriores."""
import base64
import hashlib
import json
import os
import unittest
from datetime import datetime

import test_order_followups as base
import app
import order_evidence

MIB = 1024 * 1024
JPEG = b'\xff\xd8\xff\xe0' + b'JFIF'
PNG = b'\x89PNG\r\n\x1a\n'
WEBP = b'RIFF\x00\x00\x00\x00WEBPVP8 '
PDF = b'%PDF-1.7\n'
THUMB = base64.b64encode(b'\xff\xd8\xff\xdb' + b'\x01' * 2000).decode()


def blob(head, size):
    return head + os.urandom(size - len(head))


class FollowupEvidenceTests(unittest.TestCase):
    Base = base.OrderFollowupTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown, request, login, order_data = Base.setUp, Base.tearDown, Base.request, Base.login, Base.order_data
    form, prepare, paid_order, configure = Base.form, Base.prepare, Base.paid_order, Base.configure

    def upload(self, post, oid, raw, name='placa.jpg', thumb=THUMB, skip=None):
        """Sube como el navegador: abre, envía cada parte y cierra. Devuelve (respuesta de finish, token)."""
        start = post('/api/orders/%d/uploads' % oid, action='start', name=name, size=str(len(raw)), sha256=hashlib.sha256(raw).hexdigest())
        if start['status'] != 200:
            return start, None
        token, size = start['body']['token'], start['body']['part_bytes']
        for i in range(start['body']['parts']):
            if i == skip:
                continue
            r = post('/api/orders/%d/uploads' % oid, action='part', token=token, index=str(i), data=base64.b64encode(raw[i * size:(i + 1) * size]).decode())
            self.assertEqual(r['status'], 200, r['body'])
        return post('/api/orders/%d/uploads' % oid, action='finish', token=token, thumb=thumb), token

    def original(self, oid, fid, cookie='', public=''):
        root = ('/s/%s/files/%d' % (public, fid)) if public else ('/api/orders/%d/followups/files/%d' % (oid, fid))
        meta = self.request(root + '/meta', cookie=cookie)
        if meta['status'] != 200:
            return meta['status'], b''
        return 200, b''.join(self.request(root + '?part=%d' % i, cookie=cookie)['body'] for i in range(meta['body']['parts']))

    def save(self, post, oid, files, key):
        return post('/api/orders/%d/followups' % oid, kind='novedad', internal_note='Pista dañada junto al conector (solo taller).', client_message='Adjuntamos fotografías de la placa.',
                    client_visible='1', request_key=key, files=json.dumps(files))

    def test_size_limits_and_real_type(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        for head, size, name in ((JPEG, 900 * 1024, 'a.jpg'), (PNG, 5 * MIB, 'b.png'), (WEBP, 1000, 'c.webp'), (PDF, 2000, 'd.pdf'), (JPEG, 10 * MIB, 'exacto.jpeg')):
            done, _ = self.upload(post, oid, blob(head, size), name)
            self.assertEqual(done['status'], 200, (name, done['body']))
        self.assertEqual(done['body']['mime'], 'image/jpeg')
        over = post('/api/orders/%d/uploads' % oid, action='start', name='grande.jpg', size=str(10 * MIB + 1), sha256='0' * 64)
        self.assertEqual(over['status'], 400);self.assertIn('10 MB', over['body']['error'])
        fake, token = self.upload(post, oid, b'MZ' + os.urandom(3000), 'virus.jpg')  # el nombre dice JPG; el contenido, no
        self.assertEqual(fake['status'], 400);self.assertIn('Solo se admiten', fake['body']['error'])
        with app.connect() as c:
            self.assertFalse(c.execute('SELECT 1 FROM order_uploads WHERE token=?', (token,)).fetchone())  # descartada, sin restos
        # Contenido distinto del declarado (SHA-256): se rechaza.
        raw = blob(JPEG, 4000)
        start = post('/api/orders/%d/uploads' % oid, action='start', name='x.jpg', size=str(len(raw)), sha256=hashlib.sha256(b'otro').hexdigest())
        post('/api/orders/%d/uploads' % oid, action='part', token=start['body']['token'], index='0', data=base64.b64encode(raw).decode())
        self.assertEqual(post('/api/orders/%d/uploads' % oid, action='finish', token=start['body']['token'])['status'], 400)

    def test_original_keeps_its_hash_and_thumbnail_is_separate(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        raw = blob(JPEG, 10 * MIB)  # placa electrónica de 10 MiB: 4 partes
        done, token = self.upload(post, oid, raw)
        made = self.save(post, oid, [{'upload': token, 'visible': '1'}], 'evidencia-hash-000001')
        self.assertEqual(made['status'], 201, made['body'])
        f = self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['followups'][0]['files'][0]
        self.assertEqual((f['storage'], f['size'], f['sha256'], f['has_thumb']), ('partes', 10 * MIB, hashlib.sha256(raw).hexdigest(), True))
        status, back = self.original(oid, f['id'], cookie)
        self.assertEqual((status, hashlib.sha256(back).hexdigest()), (200, hashlib.sha256(raw).hexdigest()))  # el original, sin reducir
        small = self.request('/api/orders/%d/followups/files/%d/thumb' % (oid, f['id']), cookie=cookie)['body']
        self.assertEqual(small, base64.b64decode(THUMB))
        self.assertEqual(self.request('/api/orders/%d/followups/files/%d?part=4' % (oid, f['id']), cookie=cookie)['status'], 404)

    def test_public_link_only_serves_authorized_evidence(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        _, pub = self.upload(post, oid, blob(JPEG, 3 * MIB), 'publica.jpg')
        _, priv = self.upload(post, oid, blob(PNG, 1000), 'privada.png')
        _, gone = self.upload(post, oid, blob(PDF, 3000), 'informe.pdf')
        made = self.save(post, oid, [{'upload': pub, 'visible': '1'}, {'upload': priv, 'visible': ''}, {'upload': gone, 'visible': '1'}], 'evidencia-publica-0001')
        self.assertEqual(made['status'], 201, made['body'])
        files = {f['name']: f for f in self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['followups'][0]['files']}
        retire = post('/api/orders/%d/followups/files/%d' % (oid, files['informe.pdf']['id']), action='retire', reason='Informe equivocado (ficticio)')
        self.assertEqual(retire['status'], 200, retire['body'])
        with app.connect() as c:
            import order_tracking
            order_tracking.create(c, oid, self.uid, datetime.now().astimezone())
            token = c.execute("SELECT token FROM order_tracking_links WHERE order_id=? AND revoked_at=''", (oid,)).fetchone()[0]
            c.commit()
        page = self.request('/s/' + token)['body']
        self.assertEqual(page.count('class="ticket-ev"'), 1)  # solo la autorizada
        for name in ('publica.jpg', 'privada.png', 'informe.pdf'):
            self.assertNotIn(name, page)  # el cliente no ve nombres de archivo
        self.assertEqual(self.original(oid, files['publica.jpg']['id'], public=token)[0], 200)
        for name in ('privada.png', 'informe.pdf'):  # ni por enlace directo
            self.assertEqual(self.original(oid, files[name]['id'], public=token)[0], 404)
            self.assertEqual(self.request('/s/%s/files/%d/thumb' % (token, files[name]['id']))['status'], 404)
        self.assertEqual(self.request('/api/orders/%d/followups/files/%d/meta' % (oid, files['privada.png']['id']))['status'], 401)  # API sin sesión
        # Otra orden no se alcanza con este enlace.
        other = self.paid_order(10500, pay=False, key='0002')[3]['id']
        self.assertNotEqual(other, oid)
        _, t2 = self.upload(post, other, blob(JPEG, 2000), 'ajena.jpg')
        self.save(post, other, [{'upload': t2, 'visible': '1'}], 'evidencia-ajena-00001')
        foreign = self.request('/api/orders/%d/followups' % other, cookie=cookie)['body']['followups'][0]['files'][0]['id']
        self.assertEqual(self.original(oid, foreign, public=token)[0], 404)
        # Ocultar después de guardar: deja de verse en el enlace; el registro conserva quién y cuándo.
        hide = post('/api/orders/%d/followups/files/%d' % (oid, files['publica.jpg']['id']), action='visibility', visible='')
        self.assertEqual(hide['status'], 200)
        self.assertEqual(self.original(oid, files['publica.jpg']['id'], public=token)[0], 404)
        # Ver muchas evidencias no agota el límite de la página de seguimiento (contadores separados).
        for _ in range(45):
            self.request('/s/%s/files/%d/meta' % (token, files['privada.png']['id']))
        self.assertEqual(self.request('/s/' + token)['status'], 200)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_followup_file_changes').fetchone()[0], 2)
            for sql in ('UPDATE order_followup_file_changes SET visible=1', 'DELETE FROM order_followup_file_changes', 'DELETE FROM order_upload_parts'):
                with self.assertRaises(Exception):
                    c.execute(sql)

    def test_retries_and_incomplete_uploads_never_create_partial_evidence(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        raw = blob(JPEG, 6 * MIB)
        missing, token = self.upload(post, oid, raw, skip=1)  # se cortó la conexión en la parte 2
        self.assertEqual(missing['status'], 409);self.assertIn('Faltan partes', missing['body']['error'])
        refused = self.save(post, oid, [{'upload': token, 'visible': '1'}], 'evidencia-corte-00001')
        self.assertEqual(refused['status'], 409)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_followups WHERE order_id=?', (oid,)).fetchone()[0], 0)  # nada a medias
        part = base64.b64encode(raw[order_evidence.PART_BYTES:2 * order_evidence.PART_BYTES]).decode()
        for _ in range(2):  # reintento de la misma parte: no se duplica
            self.assertEqual(post('/api/orders/%d/uploads' % oid, action='part', token=token, index='1', data=part)['status'], 200)
        self.assertEqual(post('/api/orders/%d/uploads' % oid, action='finish', token=token)['status'], 200)
        first = self.save(post, oid, [{'upload': token, 'visible': '1'}], 'evidencia-corte-00001')
        again = self.save(post, oid, [{'upload': token, 'visible': '1'}], 'evidencia-corte-00001')  # reintento del guardado
        self.assertEqual((first['status'], again['body']['id']), (201, first['body']['id']))
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM order_followup_files WHERE order_id=?', (oid,)).fetchone()[0], 1)
        status, back = self.original(oid, self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['followups'][0]['files'][0]['id'], cookie)
        self.assertEqual(back, raw)
        # Quitar un archivo antes de guardar descarta la carga; una ya usada no se quita así.
        _, extra = self.upload(post, oid, blob(PNG, 1000), 'extra.png')
        self.assertEqual(post('/api/orders/%d/uploads' % oid, action='cancel', token=extra)['status'], 200)
        self.assertEqual(post('/api/orders/%d/uploads' % oid, action='cancel', token=token)['status'], 409)

    def test_limit_draft_permissions_and_previous_evidence(self):
        cookie, csrf, post, order = self.paid_order(10500, pay=False)
        oid = order['id']
        tokens = [self.upload(post, oid, blob(JPEG, 1000), 'f%d.jpg' % i)[1] for i in range(4)]
        four = self.save(post, oid, [{'upload': t, 'visible': ''} for t in tokens], 'evidencia-cuatro-0001')
        self.assertEqual(four['status'], 400);self.assertIn('como máximo 3', four['body']['error'])
        for wrong in ('0', '11', 'tres'):
            self.assertEqual(post('/api/followups/settings', max_files=wrong)['status'], 400, wrong)
        self.assertEqual(post('/api/followups/settings', max_files='4')['status'], 200)
        self.assertEqual(self.save(post, oid, [{'upload': t, 'visible': ''} for t in tokens], 'evidencia-cuatro-0002')['status'], 201)
        self.assertEqual(self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['limits']['max_files'], 4)
        # Borrador: se guarda, se recupera y desaparece al registrar el seguimiento.
        self.assertEqual(post('/api/orders/%d/followups/draft' % oid, kind='novedad', diagnosis='Pista abierta (borrador)')['status'], 200)
        self.assertEqual(self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['followup_draft']['data']['diagnosis'], 'Pista abierta (borrador)')
        made = post('/api/orders/%d/followups' % oid, kind='novedad', diagnosis='Pista abierta junto al conector', observations='Cliente indica golpe', request_key='evidencia-borrador-001')
        self.assertEqual(made['status'], 201, made['body'])
        data = self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']
        self.assertIsNone(data['followup_draft'])
        self.assertEqual((data['followups'][0]['diagnosis'], data['followups'][0]['observations']), ('Pista abierta junto al conector', 'Cliente indica golpe'))
        # Lo interno (diagnóstico, observaciones) no llega al enlace público.
        with app.connect() as c:
            import order_tracking
            order_tracking.create(c, oid, self.uid, datetime.now().astimezone())
            link = c.execute("SELECT token FROM order_tracking_links WHERE order_id=? AND revoked_at=''", (oid,)).fetchone()[0]
            c.commit()
        page = self.request('/s/' + link)['body']
        self.assertNotIn('Pista abierta', page);self.assertNotIn('golpe', page)
        # Evidencia anterior (guardada entera, 1.5.236 y antes): se sigue leyendo igual.
        legacy = post('/api/orders/%d/followups' % oid, kind='novedad', internal_note='Foto anterior', request_key='evidencia-anterior-001',
                      files=json.dumps([{'name': 'vieja.png', 'data': base64.b64encode(PNG + b'\x00' * 64).decode(), 'visible': ''}]))
        self.assertEqual(legacy['status'], 201, legacy['body'])
        old = self.request('/api/orders/%d/followups' % oid, cookie=cookie)['body']['followups'][0]['files'][0]
        self.assertEqual((old['storage'], self.original(oid, old['id'], cookie)[1]), ('inline', PNG + b'\x00' * 64))
        # Permisos (los roles son administrador y técnico): sin sesión nada se sube, se cambia ni se configura.
        for path, body in (('/api/orders/%d/uploads' % oid, dict(action='start', name='x.jpg', size='10', sha256='0' * 64)),
                           ('/api/orders/%d/followups/files/%d' % (oid, old['id']), dict(action='retire', reason='Sin permiso')), ('/api/followups/settings', dict(max_files='5'))):
            self.assertIn(self.request(path, body)['status'], (401, 403), path)
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=?", (self.uid,));c.commit()
        self.assertEqual(post('/api/orders/%d/uploads' % oid, action='start', name='t.jpg', size='10', sha256='0' * 64)['status'], 200)  # el técnico sí sube
        self.assertEqual(post('/api/followups/settings', max_files='5')['status'], 403)  # el límite, solo administración


if __name__ == '__main__':
    unittest.main()
