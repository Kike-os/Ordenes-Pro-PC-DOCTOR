"""Mail Pro 1.5.260 (datos ficticios, base temporal, buzón SIMULADO y ADI SIMULADO: nada sale a internet).
Conversaciones por asunto, pendientes de respuesta sin automáticos ni propios, etiquetas por Message-ID con permisos, asunto propuesto (con y sin
ADI, sin inventar) y resumen que oculta datos personales antes de llegar al proveedor."""
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import adi_ai
import mail_features as mf
import mail_pro
import test_app
import app

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone(timedelta(hours=-5)))


def row(uid, subject, sender='cliente@example.invalid', name='Cliente Ficticio', answered=False, seen=True, hours=1, report=False):
    return {'uid': uid, 'subject': subject, 'from': [{'name': name, 'address': sender}], 'to': [], 'date': (NOW - timedelta(hours=hours)).isoformat(),
            'message_id': '<m%d@example.invalid>' % uid, 'seen': seen, 'flagged': False, 'answered': answered, 'draft': False, 'size': 1, 'attachments': False,
            'preview': '', 'report': report}


class MailFeatureRules(unittest.TestCase):
    def test_thread_keys_and_grouping(self):
        for text in ('Re: Pantalla rota', 'RE: RV: pantalla   rota', 'Fwd: [Externo] Pantalla rota', 'Re[2]: Pantálla rota', 'AW: Pantalla rota'):
            self.assertEqual(mf.thread_key(text), 'pantalla rota', text)
        self.assertEqual(mf.thread_key('(sin asunto)'), '')
        groups = mf.group_threads([row(9, 'Re: Pantalla rota', seen=False), row(8, 'Otro tema'), row(7, 'Pantalla rota', name='Taller'), row(6, '(sin asunto)'), row(5, '(sin asunto)')])
        self.assertEqual([(g['uid'], g['thread']['count']) for g in groups], [(9, 2), (8, 1), (6, 1), (5, 1)])  # los mensajes sin asunto no se agrupan
        self.assertEqual((groups[0]['thread']['uids'], groups[0]['thread']['unread'], groups[0]['seen']), ([9, 7], 1, False))
        self.assertEqual([i['uid'] for i in groups[0]['thread']['items']], [9, 7])

    def test_pending_excludes_answered_own_and_automated(self):
        rows = [row(1, 'Consulta', hours=80), row(2, 'Respondido', answered=True), row(3, 'Propio', sender='taller@example.invalid'),
                row(4, 'Aviso', sender='no-reply@banco.example'), row(5, 'Rebote', sender='mailer-daemon@example.invalid'), row(6, 'Informe', report=True),
                row(7, 'Boletín', sender='newsletter@tienda.example'), row(8, 'Pregunta')]
        got = mf.pending(rows, 'taller@example.invalid', NOW)
        self.assertEqual([(r['uid'], r['waiting_days']) for r in got], [(1, 3), (8, 0)])
        self.assertEqual(mf.since(NOW), '8-Oct-2026')

    def test_subject_fallback_never_invents(self):
        body = 'Estimado cliente:\nLe informamos que su portátil ya fue revisado y estamos cambiando la batería. Saludos.'
        self.assertEqual(mf.subject_fallback(body, 'PCD-20261107-0001'), 'Orden PCD-20261107-0001 · Le informamos que su portátil ya fue revisado y estamos')
        self.assertEqual(mf.strip_quotes('Hola\n> cita\n\nEl 7 nov, Juan escribió:\nviejo'), 'Hola')


class MailFeatureRoutes(test_app.SecurityTests):
    """Rutas con un buzón simulado en memoria (sin IMAP ni SMTP)."""

    def setUp(self):
        super().setUp()
        self.msgs = {1: row(1, 'Consulta de pantalla', hours=100), 2: row(2, 'Re: Consulta de pantalla', sender='taller@example.invalid', name='Taller', answered=True),
                     3: row(3, 'RE: Consulta de pantalla', hours=2), 4: row(4, 'Aviso automático', sender='no-reply@example.invalid')}
        self.msgs[3]['text'] = 'Hola, mi teléfono es 0991234567 y mi correo es ana@example.invalid. ¿Ya está lista la pantalla? Clave: Secreta123'
        self.msgs[1]['text'] = 'Les dejo la portátil con la pantalla parpadeando.'
        folders = [{'id': 'INBOX', 'role': 'inbox', 'special': False, 'label': 'Bandeja de entrada', 'duplicate': False}]
        stack = ExitStack();self.addCleanup(stack.close)
        fake = {'configured': lambda env=None: True, 'settings': lambda env=None: {'username': 'taller@example.invalid', 'password': 'x', 'imap_host': 'i', 'imap_port': 993, 'smtp_host': 's', 'smtp_port': 465},
                'open_imap': lambda config=None: object(), 'close_imap': lambda client: None, 'resolve': lambda client, folder: (dict(folders[0]), folders),
                'search': lambda client, folder, query='', flagged=False, unread=False, unanswered=False, since='', exclude_from='':
                    [u for u in sorted(self.msgs, reverse=True) if (not unanswered or not self.msgs[u]['answered']) and (not exclude_from or self.msgs[u]['from'][0]['address'] != exclude_from)],
                'summaries': lambda client, uids, previews=True: [dict(self.msgs[u]) for u in uids if u in self.msgs],
                'read_message': lambda client, folder, uid, mark_seen=True: dict(self.msgs[int(uid)], text=self.msgs[int(uid)].get('text', 'Texto'))}
        for name, value in fake.items():
            stack.enter_context(patch.object(mail_pro, name, value))
        stack.enter_context(patch.object(app, 'reception_now', lambda: NOW))  # días de espera calculados con una fecha fija (no la del reloj)
        self.cookie, self.csrf = self.login()

    def get(self, path):
        return self.request(path, cookie=self.cookie)

    def post(self, path, **body):
        return self.request(path, body, cookie=self.cookie, csrf=self.csrf)

    def test_pending_threads_and_labels_through_the_routes(self):
        got = self.get('/api/mail/messages?folder=INBOX&pendientes=1')['body']
        self.assertEqual(([r['uid'] for r in got['rows']], got['total']), ([3, 1], 2))  # sin el propio ni el automático
        self.assertEqual([r['waiting_days'] for r in got['rows']], [0, 4])
        got = self.get('/api/mail/messages?folder=INBOX&threads=1')['body']
        self.assertEqual([(r['uid'], r['thread']['count']) for r in got['rows']], [(4, 1), (3, 3)])
        labels = self.get('/api/mail/labels')['body']['labels']
        self.assertEqual(sorted(l['name'] for l in labels), ['Cliente', 'Facturación', 'Proveedor', 'Urgente'])
        urgent = next(l['id'] for l in labels if l['name'] == 'Urgente')
        tagged = self.post('/api/mail/label', message_id='<m3@example.invalid>', label_id=str(urgent))
        self.assertEqual((tagged['status'], tagged['body']['labels']), (200, [urgent]))
        self.assertEqual(self.post('/api/mail/label', message_id='sin-formato', label_id=str(urgent))['status'], 400)
        got = self.get('/api/mail/messages?folder=INBOX&label=%d' % urgent)['body']
        self.assertEqual(([r['uid'] for r in got['rows']], got['rows'][0]['labels']), ([3], [urgent]))
        made = self.post('/api/mail/labels', action='create', name='Garantía', color='ambar')
        self.assertEqual(made['status'], 200);self.assertEqual(self.post('/api/mail/labels', action='create', name='garantía', color='ambar')['status'], 409)
        self.assertEqual(self.post('/api/mail/labels', action='create', name='X', color='azul')['status'], 400)
        # 1.5.264: editar nombre y color conserva las asociaciones; el nombre no puede repetirse y el identificador debe existir.
        edited = self.post('/api/mail/labels', action='update', id=str(urgent), name='Urgente cliente', color='violeta')
        self.assertEqual(edited['status'], 200, edited['body'])
        after = {l['id']: l for l in self.get('/api/mail/labels')['body']['labels']}
        self.assertEqual((after[urgent]['name'], after[urgent]['color'], after[urgent]['total']), ('Urgente cliente', 'violeta', 1))
        self.assertEqual(self.get('/api/mail/messages?folder=INBOX&label=%d' % urgent)['body']['rows'][0]['labels'], [urgent])
        self.assertEqual(self.post('/api/mail/labels', action='update', id=str(urgent), name='garantía', color='rojo')['status'], 409)
        self.assertEqual(self.post('/api/mail/labels', action='update', id=str(urgent), name='URGENTE CLIENTE', color='rojo')['status'], 200)  # su propio nombre sí
        self.assertEqual(self.post('/api/mail/labels', action='update', id='99999', name='Otra', color='azul')['status'], 404)
        self.assertEqual(self.post('/api/mail/labels', action='update', id='abc', name='Otra', color='azul')['status'], 404)
        self.assertEqual(self.post('/api/mail/labels', action='update', id=str(urgent), name='Y', color='azul')['status'], 400)
        self.assertEqual(self.post('/api/mail/labels', action='delete', id=str(urgent))['status'], 200)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mail_message_labels WHERE label_id=?', (urgent,)).fetchone()[0], 0)

    def test_subject_and_summary_with_simulated_adi(self):
        body = 'Estimado cliente: su portátil ya fue revisada y estamos cambiando la batería.'
        plain = self.post('/api/mail/subject', body=body, order_code='PCD-20261107-0001')['body']  # sin proveedor: primera frase, sin inventar
        self.assertEqual(plain['source'], 'plantilla');self.assertIn('PCD-20261107-0001', plain['subject'])
        self.assertEqual(self.post('/api/mail/subject', body='corto')['status'], 400)
        self.assertEqual(self.post('/api/mail/summary', folder='INBOX', uids='3,1')['status'], 503)  # sin ADI no se inventa un resumen
        seen = {}

        def fake(system, user, long=False):
            seen.setdefault('calls', []).append(user)
            return ('Cambio de batería de la portátil' if 'asunto' in system.lower() else
                    'Resumen: El cliente pregunta si la pantalla está lista.\nPuntos clave:\n- Dejó la portátil con la pantalla parpadeando.\nPendiente: Responder sobre la pantalla.'), 100, 20
        with patch.object(adi_ai, 'provider', lambda: 'openai'), patch.object(adi_ai, '_complete', fake):
            sub = self.post('/api/mail/subject', body=body)['body']
            summary = self.post('/api/mail/summary', folder='INBOX', uids='3,1')
        self.assertEqual((sub['source'], sub['subject']), ('adi', 'Cambio de batería de la portátil'))
        self.assertEqual(summary['status'], 200, summary['body']);self.assertIn('Pendiente:', summary['body']['summary']);self.assertEqual(summary['body']['messages'], 2)
        sent = seen['calls'][-1]
        for private in ('0991234567', 'ana@example.invalid', 'Secreta123', 'Cliente Ficticio'):
            self.assertNotIn(private, sent, private)  # nada personal llega al proveedor
        self.assertLess(sent.index('pantalla parpadeando'), sent.index('lista la pantalla'))  # del más antiguo al más reciente

    def test_labels_are_managed_only_by_administration(self):
        with app.connect() as c:
            c.execute("UPDATE users SET role='tecnico' WHERE id=(SELECT id FROM users ORDER BY id LIMIT 1)");c.commit()
        self.assertEqual(self.post('/api/mail/labels', action='create', name='Técnica', color='azul')['status'], 403)
        self.assertEqual(self.post('/api/mail/labels', action='update', id='1', name='Técnica', color='azul')['status'], 403)


for name in [name for name in dir(test_app.SecurityTests) if name.startswith('test_')]:
    setattr(MailFeatureRoutes, name, None)

if __name__ == '__main__':
    unittest.main()
