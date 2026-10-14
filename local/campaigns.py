"""Libreta de direcciones y comunicados a clientes de Mail Pro.

- Los contactos salen del registro de clientes (no hay otra base): solo los que tienen un correo válido, sin direcciones repetidas.
- Cada comunicado se envía como un mensaje individual por destinatario (nadie ve los correos de otros clientes), con la
  plantilla institucional, la firma con el logotipo y un enlace para darse de baja de los comunicados.
- Nada sale sin la confirmación expresa de administración. El envío se procesa por lotes (cola) y cada destinatario se envía
  una sola vez: si un envío queda en duda no se repite. El estado de entrega es el del seguimiento real de Mail Pro.
- Las bajas solo excluyen de los comunicados; nunca de los correos de servicio (comprobantes, citas, presupuestos).
"""
import hashlib
import re
import secrets
import time
from datetime import timedelta

import mail_pro

TEMPLATES = {
    'agenda': ('Nuevo sistema de agendamiento de citas | PC-DOCTOR S.A.',
               'Estimado/a {nombre}:\n\nNos complace informarle que ya puede agendar su cita de servicio técnico en línea, de forma rápida y sin llamadas.\n\n'
               'Elija el servicio, la fecha y la hora disponibles, y reciba la confirmación en su correo:\n{enlace_citas}\n\n'
               'Si tiene alguna consulta, responda a este mensaje o escríbanos por WhatsApp.\n\nAtentamente,'),
    'general': ('Comunicado | PC-DOCTOR S.A.', 'Estimado/a {nombre}:\n\n\n\nAtentamente,'),
}
BATCH = 10
BUDGET_SECONDS = 18
PAUSE_SECONDS = 0.4
STUCK_MINUTES = 10


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def stamp(now):
    return now.isoformat(timespec='seconds')


def opted_out(c):
    return {row['email'].lower() for row in c.execute('SELECT email FROM mail_optouts')}


def contacts(c):
    """Contactos elegibles del registro de clientes: uno por dirección (el registro más antiguo da el nombre), con avisos de duplicados."""
    rows, seen, stats = [], {}, {'clients': 0, 'with_email': 0, 'duplicates': 0, 'invalid': 0, 'opted_out': 0}
    blocked = opted_out(c)
    for row in c.execute("SELECT id,name,email,trade_name FROM clients ORDER BY id"):
        stats['clients'] += 1
        email = str(row['email'] or '').strip()
        if not email:
            continue
        stats['with_email'] += 1
        if not mail_pro.ADDRESS.fullmatch(email) or len(email) > 254:
            stats['invalid'] += 1
            continue
        key = email.lower()
        if key in seen:
            stats['duplicates'] += 1
            seen[key]['also'].append(row['name'])
            continue
        item = {'id': row['id'], 'name': row['name'], 'email': email, 'trade_name': row['trade_name'] or '', 'also': [], 'opted_out': key in blocked}
        stats['opted_out'] += 1 if item['opted_out'] else 0
        seen[key] = item
        rows.append(item)
    rows.sort(key=lambda item: item['name'].lower())
    return rows, stats


def personalize(text, name, links):
    first = (name or '').strip()
    out = text.replace('{nombre}', first or 'cliente')
    for key, value in links.items():
        out = out.replace('{' + key + '}', value)
    return out


def clean(subject, body):
    subject = re.sub(r'[\r\n]+', ' ', str(subject or '')).strip()[:200]
    body = str(body or '').replace('\r\n', '\n').strip()[:20000]
    errors = {}
    if len(subject) < 4:
        errors['subject'] = 'Escribe un asunto.'
    if len(body) < 20:
        errors['body'] = 'Escribe el mensaje del comunicado.'
    if '{nombre}' not in body and len(body) >= 20:
        pass
    return subject, body, errors


def create(c, user, data, now):
    """Borrador de comunicado con sus destinatarios ya depurados. Devuelve (estado HTTP, respuesta). No envía nada."""
    subject, body, errors = clean(data.get('subject'), data.get('body'))
    if errors:
        return 400, {'error': 'Revisa el comunicado.', 'fields': errors}
    audience = 'all' if data.get('audience') == 'all' else 'selected'
    template = data.get('template') if data.get('template') in TEMPLATES else 'general'
    rows, stats = contacts(c)
    eligible = [row for row in rows if not row['opted_out']]
    if audience == 'selected':
        wanted = {int(value) for value in data.get('client_ids', []) if str(value).isdigit()}
        eligible = [row for row in eligible if row['id'] in wanted]
    if not eligible:
        return 400, {'error': 'No hay destinatarios elegibles: elige clientes con correo que no se hayan dado de baja.'}
    if len(eligible) > 2000:
        return 400, {'error': 'Un comunicado admite hasta 2000 destinatarios.'}
    campaign = c.execute('INSERT INTO mail_campaigns(subject,body,template,audience,status,created_by,created_at) VALUES (?,?,?,?,?,?,?)',
                         (subject, body, template, audience, 'draft', user['id'], stamp(now))).lastrowid
    for row in eligible:
        c.execute('INSERT OR IGNORE INTO mail_campaign_recipients(campaign_id,client_id,email,name,updated_at) VALUES (?,?,?,?,?)', (campaign, row['id'], row['email'], row['name'], stamp(now)))
    return 201, {'campaign': summary(c, campaign), 'excluded': {'opted_out': stats['opted_out'], 'duplicates': stats['duplicates'], 'invalid': stats['invalid'],
                                                               'without_email': stats['clients'] - stats['with_email']}}


def summary(c, campaign):
    row = c.execute("SELECT m.*,COALESCE(u.name,'') author FROM mail_campaigns m LEFT JOIN users u ON u.id=m.created_by WHERE m.id=?", (campaign,)).fetchone()
    if not row:
        return None
    item = dict(row)
    counts = {status: 0 for status in ('pending', 'sending', 'sent', 'failed', 'skipped')}
    for entry in c.execute('SELECT status,COUNT(*) total FROM mail_campaign_recipients WHERE campaign_id=? GROUP BY status', (campaign,)):
        counts[entry['status']] = entry['total']
    delivery = {}
    for entry in c.execute('SELECT d.status,COUNT(*) total FROM mail_campaign_recipients r JOIN mail_deliveries d ON d.id=r.delivery_id WHERE r.campaign_id=? GROUP BY d.status', (campaign,)):
        delivery[entry['status']] = entry['total']
    item.update(counts=counts, total=sum(counts.values()), delivery=delivery)
    return item


def history(c):
    return [summary(c, row['id']) for row in c.execute('SELECT id FROM mail_campaigns ORDER BY id DESC LIMIT 30')]


def detail(c, campaign):
    item = summary(c, campaign)
    if not item:
        return None
    item['recipients'] = [dict(row) for row in c.execute(
        "SELECT r.id,r.name,r.email,r.status,r.detail,r.updated_at,COALESCE(d.status,'') delivery,COALESCE(d.reason,'') reason FROM mail_campaign_recipients r "
        "LEFT JOIN mail_deliveries d ON d.id=r.delivery_id WHERE r.campaign_id=? ORDER BY r.name COLLATE NOCASE", (campaign,))]
    return item


def message_parts(c, campaign, name, unsubscribe):
    """Asunto, texto y título del mensaje de un destinatario (con su nombre y su enlace de baja)."""
    from reception import public_base_url
    base = public_base_url().rstrip('/')
    text = personalize(campaign['body'], name, {'enlace_citas': base + '/citas'})
    text += '\n\nSi no desea recibir más comunicados de PC-DOCTOR S.A., puede darse de baja aquí: ' + unsubscribe
    return campaign['subject'], text, campaign['subject']


def confirm(c, campaign, user, now):
    row = c.execute('SELECT status FROM mail_campaigns WHERE id=?', (campaign,)).fetchone()
    if not row:
        return 404, {'error': 'Comunicado no encontrado.'}
    if row['status'] != 'draft':
        return 409, {'error': 'Este comunicado ya fue confirmado.'}
    c.execute("UPDATE mail_campaigns SET status='queued',confirmed_by=?,confirmed_at=? WHERE id=?", (user['id'], stamp(now), campaign))
    return 200, {'campaign': summary(c, campaign)}


def cancel(c, campaign, now):
    row = c.execute('SELECT status FROM mail_campaigns WHERE id=?', (campaign,)).fetchone()
    if not row:
        return 404, {'error': 'Comunicado no encontrado.'}
    if row['status'] in ('done', 'cancelled'):
        return 409, {'error': 'Este comunicado ya terminó.'}
    c.execute("UPDATE mail_campaigns SET status='cancelled',finished_at=? WHERE id=?", (stamp(now), campaign))
    c.execute("UPDATE mail_campaign_recipients SET status='skipped',detail='Comunicado cancelado antes del envío.',updated_at=? WHERE campaign_id=? AND status='pending'", (stamp(now), campaign))
    return 200, {'campaign': summary(c, campaign)}


def process(c, campaign, now, actor, send, budget=BUDGET_SECONDS):
    """Envía el siguiente lote de un comunicado confirmado. `send(c,subject,text,title,email,actor,private)` es el envío institucional
    (devuelve su archive_id o lanza MailError). Devuelve el resumen. Cada destinatario se envía como mucho una vez."""
    import mail_tracking
    row = c.execute('SELECT * FROM mail_campaigns WHERE id=?', (campaign,)).fetchone()
    if not row or row['status'] not in ('queued', 'sending'):
        return summary(c, campaign)
    # Un envío que quedó «enviando» (proceso interrumpido) no se repite: no consta si salió.
    c.execute("UPDATE mail_campaign_recipients SET status='failed',detail='Sin confirmación del servidor; no se reintenta para evitar duplicados.',updated_at=? "
              "WHERE campaign_id=? AND status='sending' AND updated_at<?", (stamp(now), campaign, stamp(now - timedelta(minutes=STUCK_MINUTES))))
    c.execute("UPDATE mail_campaigns SET status='sending' WHERE id=?", (campaign,))
    c.commit()
    began, blocked = time.monotonic(), opted_out(c)
    for item in c.execute("SELECT * FROM mail_campaign_recipients WHERE campaign_id=? AND status='pending' ORDER BY id LIMIT ?", (campaign, BATCH)).fetchall():
        if time.monotonic() - began > budget:
            break
        moment = stamp(now)
        if item['email'].lower() in blocked:
            c.execute("UPDATE mail_campaign_recipients SET status='skipped',detail='El cliente se dio de baja de los comunicados.',updated_at=? WHERE id=?", (moment, item['id']));c.commit()
            continue
        refusal = mail_tracking.blocked(c, item['email'])
        if refusal:
            c.execute("UPDATE mail_campaign_recipients SET status='skipped',detail=?,updated_at=? WHERE id=?", (refusal[:300], moment, item['id']));c.commit()
            continue
        # Mismo correo ya enviado en este comunicado (otro registro): nunca dos veces.
        twice = c.execute("SELECT 1 FROM mail_campaign_recipients WHERE campaign_id=? AND email=? COLLATE NOCASE AND status IN ('sending','sent') AND id!=?", (campaign, item['email'], item['id'])).fetchone()
        if twice:
            c.execute("UPDATE mail_campaign_recipients SET status='skipped',detail='Dirección repetida en el comunicado.',updated_at=? WHERE id=?", (moment, item['id']));c.commit()
            continue
        token = secrets.token_urlsafe(18)
        claimed = c.execute("UPDATE mail_campaign_recipients SET status='sending',token_hash=?,updated_at=? WHERE id=? AND status='pending'", (digest(token), moment, item['id'])).rowcount
        c.commit()
        if not claimed:
            continue
        from reception import public_base_url
        link = public_base_url().rstrip('/') + '/baja/' + token
        subject, text, title = message_parts(c, row, item['name'], link)
        try:
            archive = send(c, subject, text, title, item['email'], actor, (link,))
            delivery = c.execute('SELECT id FROM mail_deliveries WHERE archive_id=? ORDER BY id DESC LIMIT 1', (archive,)).fetchone() if archive else None
            c.execute("UPDATE mail_campaign_recipients SET status='sent',delivery_id=?,detail='Aceptado por el servidor de correo.',updated_at=? WHERE id=?",
                      (delivery['id'] if delivery else None, stamp(now), item['id']))
        except mail_pro.MailError as error:
            archive = c.execute("SELECT id FROM mail_archive WHERE recipient=? AND kind='campaign' ORDER BY id DESC LIMIT 1", (item['email'],)).fetchone()
            delivery = c.execute('SELECT id FROM mail_deliveries WHERE archive_id=? ORDER BY id DESC LIMIT 1', (archive['id'],)).fetchone() if archive else None
            c.execute("UPDATE mail_campaign_recipients SET status='failed',delivery_id=?,detail=?,updated_at=? WHERE id=?",
                      (delivery['id'] if delivery else None, str(error)[:300], stamp(now), item['id']))
        c.commit()
        time.sleep(PAUSE_SECONDS)
    left = c.execute("SELECT COUNT(*) FROM mail_campaign_recipients WHERE campaign_id=? AND status IN ('pending','sending')", (campaign,)).fetchone()[0]
    if not left:
        c.execute("UPDATE mail_campaigns SET status='done',finished_at=? WHERE id=? AND status='sending'", (stamp(now), campaign))
        c.commit()
    return summary(c, campaign)


def queued(c):
    return [row['id'] for row in c.execute("SELECT id FROM mail_campaigns WHERE status IN ('queued','sending') ORDER BY id")]


def unsubscribe_lookup(c, token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', token or ''):
        return None
    return c.execute('SELECT r.email,r.name FROM mail_campaign_recipients r WHERE r.token_hash=?', (digest(token),)).fetchone()


def unsubscribe(c, token, now):
    found = unsubscribe_lookup(c, token)
    if not found:
        return False
    c.execute("INSERT INTO mail_optouts(email,source,created_at) VALUES (?,?,?) ON CONFLICT(email) DO NOTHING", (found['email'], 'enlace', stamp(now)))
    return True


def page(found, done=False, error=''):
    """Página pública de baja: sin datos más allá de la dirección enmascarada."""
    import html
    masked = ''
    if found:
        user, _, domain = found['email'].partition('@')
        masked = user[:2] + '•' * max(1, len(user) - 2) + '@' + domain
    body = ('<p>Listo: <strong>' + html.escape(masked) + '</strong> ya no recibirá comunicados de PC-DOCTOR S.A. Seguirá recibiendo los correos de sus servicios (comprobantes, citas y presupuestos).</p>' if done else
            ('<p>¿Desea dejar de recibir comunicados de PC-DOCTOR S.A. en <strong>' + html.escape(masked) + '</strong>?</p><form method="post"><button type="submit">Darme de baja</button></form>'
             '<p class="note">Los correos de sus servicios (comprobantes, citas y presupuestos) no se ven afectados.</p>') if found else
            '<p>El enlace no es válido o ya no está disponible.</p>')
    if error:
        body = '<p>' + html.escape(error) + '</p>' + body
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Comunicados | PC-DOCTOR S.A.</title>'
            '<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0a1424;color:#dbe8fb;font:15px/1.5 system-ui,Segoe UI,Arial,sans-serif}'
            'main{max-width:440px;margin:24px;padding:24px;border:1px solid #22385a;border-radius:16px;background:#0f1d33}h1{margin:0 0 12px;font-size:18px;color:#fff}'
            'button{min-height:42px;padding:0 18px;border:0;border-radius:10px;background:#2359ac;color:#fff;font-weight:700;font-size:15px;cursor:pointer}.note{font-size:13px;color:#9db1cf}</style>'
            '</head><body><main><h1>PC-DOCTOR S.A. · Comunicados</h1>' + body + '</main></body></html>')
