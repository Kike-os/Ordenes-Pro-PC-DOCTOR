"""Compose a proforma email for the authorized Mail Pro sender."""
import re

import corporate
import document_style
import mail_pro
import proformas
import public_identity
from reception import public_base_url

KIND = 'proforma'


def outbox_prefix(pid):
    return 'proforma-mail:%d:' % pid


def outbox_key(pid, link_id):
    return outbox_prefix(pid) + str(link_id)


def history(c, pid):
    return [dict(row) for row in c.execute(
        "SELECT d.id,d.status,d.code,d.reason,d.recipient,d.message_id,d.created_at,d.event_at,d.subject,"
        "a.attachments,COALESCE(u.name,'') actor,COALESCE((SELECT e.detail FROM mail_delivery_events e "
        "WHERE e.delivery_id=d.id AND e.event='remitente' LIMIT 1),'') sender "
        "FROM mail_deliveries d JOIN mail_archive a ON a.id=d.archive_id "
        "LEFT JOIN users u ON u.id=d.actor_id WHERE d.kind=? AND d.outbox_key LIKE ? ORDER BY d.id DESC LIMIT 20",
        (KIND, outbox_prefix(pid) + '%'))]


def recipient_address(value):
    address = str(value or '').strip()
    if len(address) > 254 or not mail_pro.ADDRESS.fullmatch(address) or re.search(r'[\x00-\x1f\x7f]', address):
        raise proformas.ProformaError('Escribe una sola dirección de correo válida.', 400, {'recipient': 'Correo inválido.'})
    return address


def prepare(c, pid, token, now):
    row, link = proformas.lookup(c, token, now)
    if not row or row['id'] != pid or not link['usable']:
        raise proformas.ProformaError('El enlace de la proforma ya no está vigente.', 409)
    if not proformas.identity_installed(c):
        raise proformas.ProformaError('Aplica la migración 130 antes de enviar el enlace al cliente.', 503)
    recipient = row['client_email'] or ''
    if row['client_id']:
        client = c.execute('SELECT email,identification FROM clients WHERE id=?', (row['client_id'],)).fetchone()
        if not client or re.sub(r'\s', '', client['identification'] or '') != row['client_identification']:
            raise proformas.ProformaError('La identificación de la ficha del cliente cambió. Revisa la proforma antes de enviar.', 409)
        recipient = client['email'] or ''
    kind = public_identity.kind(row['client_identification'], row['client_document_type'])
    base = public_base_url().rstrip('/')
    filename = document_style.filename('PROFORMA', row['code'])
    sender = mail_pro.settings()['username']
    key = outbox_key(pid, link['id'])
    previous = c.execute('SELECT status,message_id FROM mail_outbox WHERE request_key=?', (key,)).fetchone()
    return row, key, {
        'recipient': recipient, 'sender': sender, 'company': corporate.settings()['name'],
        'subject': 'Proforma ' + row['code'] + ' | PC-DOCTOR S.A.',
        'body': ('Hola ' + row['client_name'] + ':\n\nAdjuntamos la proforma ' + row['code'] +
                 '. Puedes revisar su contenido y registrar tu decisión desde el enlace privado incluido al final del mensaje.\n\n'
                 'Gracias por confiar en PC-DOCTOR S.A.'),
        'link': base + '/proforma/' + token, 'instruction': public_identity.instruction(kind),
        'filename': filename, 'status': previous['status'] if previous else 'pending',
        'message_id': previous['message_id'] if previous else '',
    }
