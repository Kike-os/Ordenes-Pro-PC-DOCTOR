"""Offline lab workflow with temporary SQLite data and no integrations."""
import base64
import hashlib
import unittest

import adi_lab
import app
import test_invoicing


class AdiLabTests(unittest.TestCase):
    Base = test_invoicing.InvoiceFlowTests
    setUpClass = classmethod(Base.setUpClass.__func__)
    setUp, tearDown = Base.setUp, Base.tearDown
    request, login, order_data = Base.request, Base.login, Base.order_data

    def test_order_measurements_and_firmware_remain_internal_and_reviewable(self):
        cookie, csrf = self.login()
        post = lambda path, body: self.request(path, body, cookie=cookie, csrf=csrf)
        order = post('/api/orders', self.order_data({'request_key': 'adi-lab-fictitious-order'}))['body']
        path = '/api/orders/%d/adi-lab' % order['id']
        self.assertIn(self.request(path)['status'], (401, 403))
        measurement = {'action':'measure', 'point':'Punto ficticio', 'value':'1.25', 'unit':'V',
                       'conditions':'Placa ficticia sin carga', 'request_key':'sample-1'}
        self.assertEqual(post(path, dict(measurement, value='NaN'))['status'], 400)
        first = post(path, measurement)
        self.assertEqual(first['status'], 201, first['body'])
        self.assertEqual(post(path, measurement)['body'], {'id':first['body']['id'], 'created':False})
        self.assertEqual(post(path, dict(measurement, value='2'))['status'], 409)
        draft = self.request(path + '?category=firmware', cookie=cookie)['body']
        self.assertEqual(draft['kind'], 'borrador')
        self.assertEqual(len(draft['measurements']), 1)
        self.assertTrue(draft['checks'])
        self.assertNotIn('client', draft['order'])
        self.assertFalse(post(path, {'action':'firmware'})['body']['write_authorized'])
        complete = {key:'documentación de prueba' for key in adi_lab.FIRMWARE_FIELDS}
        complete.update(action='firmware', backup_sha256='a'*64, image_sha256='b'*64)
        result = post(path, complete)['body']
        self.assertEqual(result['status'], 'revision_tecnica_pendiente')
        self.assertFalse(result['write_authorized'])
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='adi_lab_measurement'").fetchone()[0], 1)

    def test_knowledge_requires_review_and_respects_visibility(self):
        cookie, csrf = self.login()
        body = {'title':'Medición térmica ficticia','source':'Manual ficticio pág. 1','source_date':'2026-01-01',
                'version':'1','category':'alimentacion','content':'Texto de prueba fuera de producción.','visibility':'administrador'}
        path = '/api/adi/lab/knowledge'
        result = self.request(path, body, cookie=cookie, csrf=csrf)
        self.assertEqual(result['status'], 201, result['body'])
        did = result['body']['id']
        self.assertEqual(self.request(path, cookie=cookie)['body']['rows'], [])
        self.assertEqual(self.request(path + '?review=1', cookie=cookie)['body']['rows'][0]['id'], did)
        denied = self.request(path + '/' + str(did), {'status':'aprobado','review_note':'Revisión ficticia'}, cookie=cookie, csrf=csrf)
        self.assertEqual(denied['status'], 403)
        with app.connect() as c:
            admin = {'id':self.uid,'role':'administrador'}
            technician = {'id':self.uid,'role':'tecnico'}
            self.assertEqual(adi_lab.search(c, technician, review=True), [])
            with self.assertRaises(adi_lab.LabError):
                adi_lab.submit(c, body, technician, app.reception_now())
            reviewer_id = c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES "
                                    "('reviewer','reviewer@example.invalid','Revisor','test','administrador',1)").lastrowid
            reviewer = {'id':reviewer_id,'role':'administrador'}
            choice = {'status':'aprobado','review_note':'Fuente ficticia revisada'}
            adi_lab.review(c, did, choice, reviewer, app.reception_now())
            self.assertEqual(adi_lab.search(c, admin, 'termica')[0]['id'], did)
            self.assertEqual(adi_lab.search(c, technician, 'termica'), [])

            revision = adi_lab.submit(c, dict(body, version='2', supersedes=str(did)), admin, app.reception_now())
            adi_lab.review(c, revision, choice, reviewer, app.reception_now())
            self.assertEqual([item['id'] for item in adi_lab.search(c, admin, 'termica')], [revision])
            self.assertEqual(c.execute('SELECT status FROM adi_lab_knowledge WHERE id=?',(did,)).fetchone()[0], 'sustituido')

    def test_original_pdf_follows_source_permissions_and_review(self):
        cookie, csrf = self.login()
        path = '/api/adi/lab/knowledge'
        raw = b'%PDF-1.7\nFuente ficticia para pruebas\n%%EOF\n'
        body = {'title':'Fuente ficticia', 'source':'Manual ficticio', 'source_date':'2026-01-01',
                'version':'1', 'category':'post', 'content':'Extracto ficticio aprobado posteriormente.',
                'visibility':'administrador', 'original_name':'manual-ficticio.pdf',
                'original_pdf':base64.b64encode(raw).decode()}
        post = lambda payload: self.request(path, payload, cookie=cookie, csrf=csrf)
        self.assertEqual(post(dict(body, original_pdf='YQ=='))['status'], 400)
        self.assertEqual(post(dict(body, original_name='archivo.svg'))['status'], 400)
        result = post(body)
        self.assertEqual(result['status'], 201, result['body'])
        source_id = result['body']['id']
        download = path + f'/{source_id}/original'
        self.assertEqual(self.request(download)['status'], 401)
        self.assertEqual(self.request(download, cookie=cookie)['body'], raw)
        self.assertEqual(self.request(path, cookie=cookie)['body']['rows'], [])
        pending = self.request(path+'?review=1', cookie=cookie)['body']['rows'][0]
        self.assertEqual(pending['original']['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertNotIn('data', pending['original'])
        with app.connect() as c:
            technician = {'id':self.uid, 'role':'tecnico'}
            with self.assertRaises(adi_lab.LabError):
                adi_lab.original(c, source_id, technician)
            reviewer_id = c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES "
                                    "('pdf-reviewer','pdf-reviewer@example.invalid','Revisor','test','administrador',1)").lastrowid
            reviewer = {'id':reviewer_id,'role':'administrador'}
            approved = {'status':'aprobado','review_note':'Original y extracto comprobados'}
            adi_lab.review(c, source_id, approved, reviewer, app.reception_now())
        self.assertEqual(self.request(path, cookie=cookie)['body']['rows'][0]['original']['bytes'], len(raw))
        changed = post(dict(body, version='2', supersedes=str(source_id), original_pdf='', original_name=''))
        with app.connect() as c:
            adi_lab.review(c, changed['body']['id'], approved, reviewer, app.reception_now())
            self.assertTrue(c.execute('SELECT 1 FROM adi_lab_source_originals WHERE knowledge_id=?',(source_id,)).fetchone())
        self.assertEqual(self.request(download, cookie=cookie)['status'], 404)
        self.assertNotIn('original', self.request(path,cookie=cookie)['body']['rows'][0])

    def test_diagnosis_requires_another_technician_and_updates_only_internal_findings(self):
        cookie, csrf = self.login()
        order = self.request('/api/orders', self.order_data({'request_key':'adi-diagnosis-fictitious-order'}), cookie=cookie, csrf=csrf)['body']
        oid = order['id']
        path = '/api/orders/%d/adi-lab' % oid
        proposal = {'action':'diagnosis_submit','confirmed':'Hallazgo ficticio medido','conclusion':'Diagnóstico ficticio',
                    'pending_checks':'Verificación pendiente interna','request_key':'diagnosis-fake-1'}
        first = self.request(path, proposal, cookie=cookie, csrf=csrf)
        self.assertEqual(first['status'], 201, first['body'])
        did = first['body']['id']
        self.assertEqual(self.request(path, proposal, cookie=cookie, csrf=csrf)['body'], {'id':did,'created':False})
        self.assertEqual(self.request(path, dict(proposal,conclusion='Otra'), cookie=cookie, csrf=csrf)['status'],409)
        review = {'action':'diagnosis_review','diagnosis_id':str(did),'decision':'aprobado','review_note':'Medición comprobada'}
        self.assertEqual(self.request(path, review, cookie=cookie, csrf=csrf)['status'],403)
        with app.connect() as c:
            before = dict(c.execute('SELECT findings,status,revision FROM orders WHERE id=?',(oid,)).fetchone())
            self.assertNotIn('Diagnóstico ficticio', before['findings'])
            c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES "
                      "('laboratorio','lab@example.invalid','Técnico revisor',?,'tecnico',1)",(self.hash,))
        session = self.request('/api/login', {'login':'laboratorio','password':'contraseña-segura-de-prueba'})
        self.assertEqual(session['status'],200,session['body'])
        reviewer_cookie = session['cookie'].split(';')[0]
        reviewer_csrf = self.request('/api/me',cookie=reviewer_cookie)['body']['user']['csrf']
        submit_review = lambda data: self.request(path,data,cookie=reviewer_cookie,csrf=reviewer_csrf)
        history = self.request(path+'?diagnoses=1',cookie=reviewer_cookie)['body']['rows']
        self.assertTrue(history[0]['can_review'])
        self.assertEqual(submit_review(review)['status'],200)
        self.assertEqual(submit_review(review)['status'],409)
        with app.connect() as c:
            after = c.execute('SELECT findings,status,revision FROM orders WHERE id=?',(oid,)).fetchone()
            self.assertIn('Diagnóstico ficticio', after['findings'])
            self.assertNotIn('Verificación pendiente interna',after['findings'])
            self.assertEqual((after['status'],after['revision']),(before['status'], before['revision']+1))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE action='adi_lab_diagnosis_reviewed'").fetchone()[0],1)
        stale = self.request(path, dict(proposal,request_key='diagnosis-fake-2'),cookie=cookie,csrf=csrf)['body']['id']
        with app.connect() as c:
            c.execute('UPDATE orders SET findings=? WHERE id=?',('Hallazgo actualizado por el taller',oid))
        self.assertEqual(submit_review(dict(review,diagnosis_id=str(stale)))['status'],409)
        self.assertEqual(submit_review(dict(review,diagnosis_id=str(stale),decision='devuelto'))['status'],200)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT findings FROM orders WHERE id=?',(oid,)).fetchone()[0],'Hallazgo actualizado por el taller')

    def test_concept_search_only_retrieves_approved_visible_sources(self):
        with app.connect() as c:
            now = app.reception_now()
            admin = {'id':self.uid,'role':'administrador'}
            tech_id = c.execute("INSERT INTO users(username,email,name,password_hash,role,created_at) VALUES "
                                "('lab-concept','concept@example.invalid','Técnico ficticio','test','tecnico',1)").lastrowid
            tech = {'id':tech_id,'role':'tecnico'}
            source = {'title':'Guía ficticia de retroiluminación','source':'Guía interna ficticia, pág. 2',
                      'source_date':'2026-01-01','version':'1','category':'post','visibility':'tecnico',
                      'content':'Primera nota sin relación.\n\nEl apartado de retroiluminación corresponde a esta evidencia ficticia.'}
            pending = adi_lab.submit(c, source, tech, now)
            self.assertEqual(adi_lab.search(c, tech, 'pantalla negra'), [])
            adi_lab.review(c,pending,{'status':'aprobado','review_note':'Evidencia de prueba revisada'},admin,now)
            adi_lab.submit(c, dict(source,visibility='administrador'), admin, now)
            rows = adi_lab.search(c,tech,'pantalla negra')
            self.assertEqual([row['id'] for row in rows], [pending])
            self.assertEqual(rows[0]['matched_concepts'], ['Pantalla e iluminación'])
            self.assertTrue(rows[0]['excerpt'].startswith('El apartado'))
            self.assertEqual(adi_lab.search(c,tech,'firmware del sistema'),[])

    def test_recurrence_signal_is_evidence_bound_and_order_scoped(self):
        import adi_exec
        from datetime import timedelta
        cookie, csrf = self.login()
        order = self.request('/api/orders', self.order_data({'request_key':'lab-recurrence-fictitious'}), cookie=cookie, csrf=csrf)['body']
        path = '/api/orders/%d/adi-lab' % order['id']
        first = self.request(path, cookie=cookie)['body']
        self.assertFalse(first['recurrences']['repeated'])
        self.assertEqual(first['source_status'],'sin_fuentes')
        now = app.reception_now()
        with app.connect() as c:
            for i,days in enumerate((3,14,91),1):
                c.execute('INSERT INTO order_recurrences(order_id,number,reason,previous_status,created_at) VALUES (?,?,?,?,?)',
                          (order['id'],i,'Revisión ficticia','diagnostico',(now-timedelta(days=days)).isoformat(timespec='seconds')))
            insights = adi_exec.insights(c,now)
        result = self.request(path,cookie=cookie)['body']['recurrences']
        self.assertEqual(result,{'days':90,'n':2,'orders':1,'repeated':True})
        signal = next(item for item in insights['items'] if item['key']=='tecnico_reincidencias')
        self.assertEqual(signal['records'],[])
        self.assertIn('Un equipo registró',signal['reason'])
