"""Envío de un enlace privado de proforma mediante el servicio de WhatsApp Business."""
import os
import re
from datetime import timedelta

import phones
import proformas
import public_identity
import whatsapp_business as wa

EVENT = wa.PROFORMA_EVENT
NAME = 'pcdoctor_envio_proforma_v1'
IDENTITY_NAME = 'pcdoctor_envio_proforma_v2'
HEADER = 'PROFORMA DISPONIBLE'
BODY = 'Hola {{1}}, tu proforma {{2}} de PC-DOCTOR S.A. está disponible. Usa el botón para revisarla y registrar tu decisión.'
BUTTON = 'Ver mi proforma'


def template_definition(base, *, typed=False):
    path = base.rstrip('/') + '/proforma/'
    body = BODY + ' Ingresa los últimos 4 dígitos de tu {{3}} para verificar tu identidad.' if typed else BODY
    example = ['Ana Pérez', 'PF-000123'] + (['cédula registrada'] if typed else [])
    return {'name': IDENTITY_NAME if typed else NAME, 'category': 'UTILITY', 'language': 'es', 'parameter_format': 'POSITIONAL', 'components': [
        {'type': 'HEADER', 'format': 'TEXT', 'text': HEADER},
        {'type': 'BODY', 'text': body, 'example': {'body_text': [example]}},
        {'type': 'BUTTONS', 'buttons': [{'type': 'URL', 'text': BUTTON, 'url': path + '{{1}}',
                                       'example': [path + 'ejemplo_ficticio_de_token_privado_0001']}]},
    ]}


def compatible(template, base):
    components = template.get('components') or []
    if (template.get('category') != 'UTILITY' or template.get('parameter_format', 'POSITIONAL') != 'POSITIONAL'
            or not re.fullmatch(r'es(?:_[A-Z]{2})?', template.get('language', ''))
            or sorted(p['type'] for p in components) != ['BODY', 'BUTTONS', 'HEADER']):
        return False
    parts = {p['type']: p for p in components}
    header, body = parts['HEADER'], parts['BODY'].get('text', '')
    buttons = parts['BUTTONS'].get('buttons') or []
    typed = template.get('name') == IDENTITY_NAME
    if typed and body != template_definition(base, typed=True)['components'][1]['text']:
        return False
    return (header.get('format') == 'TEXT' and '{{' not in header.get('text', '')
            and re.findall(r'{{(.*?)}}', body) == (['1', '2', '3'] if typed else ['1', '2'])
            and re.search(r'\b(?:hola|estimad[oa])[^{}\n]{0,30}\{\{1\}\}', body, re.IGNORECASE) is not None
            and re.search(r'\bproforma[^{}\n]{0,30}\{\{2\}\}', body, re.IGNORECASE) is not None
            and len(buttons) == 1 and buttons[0].get('type') == 'URL'
            and buttons[0].get('url') == base.rstrip('/') + '/proforma/{{1}}')


def audit_template(base, env=None, submit=False, *, typed=False):
    env = os.environ if env is None else env
    cfg = wa.config(env)
    if not (wa.ready(env) and cfg['waba']):
        return 'sin_configuracion', None, 'Falta configurar la cuenta de WhatsApp Business en el servidor.'
    preferred = env.get('WHATSAPP_PROFORMA_TEMPLATE', '').strip() or IDENTITY_NAME
    path = cfg['waba'] + '/message_templates'
    query = {'fields': 'name,status,language,category,components,parameter_format', 'limit': 100}
    matches, cursors = [], set()
    while True:
        code, result = wa.call('GET', path, env, query=query)
        if code != 200 or not isinstance(result.get('data'), list):
            return 'sin_verificar', None, 'No se pudo consultar la aprobación de la plantilla en Meta.'
        for template in result['data']:
            text = ' '.join(p.get('text', '') for p in template.get('components') or [])
            name = template.get('name', '')
            if name in (NAME, IDENTITY_NAME, preferred) or 'proforma' in (name + ' ' + text).lower():
                matches.append(template)
        paging = result.get('paging') or {}
        if not paging.get('next'):
            break
        cursor = (paging.get('cursors') or {}).get('after')
        if not cursor or cursor in cursors:
            return 'sin_verificar', None, 'Meta no devolvió el catálogo completo de plantillas.'
        cursors.add(cursor)
        query['after'] = cursor
    if typed:
        matches = [t for t in matches if t.get('name') == IDENTITY_NAME]
    approved = [t for t in matches if t.get('status') == 'APPROVED' and compatible(t, base)]
    if approved:
        approved.sort(key=lambda t: (t['name'] != preferred, t['name'], t['language'] != 'es', t['language']))
        return 'aprobada', approved[0], 'Plantilla aprobada por Meta.'
    if any(t.get('status') == 'PENDING' and compatible(t, base) for t in matches):
        return 'pendiente', None, 'La plantilla de proformas está pendiente de aprobación por Meta.'
    if matches:
        statuses = ', '.join(sorted({str(t.get('status') or 'SIN ESTADO') for t in matches}))
        return 'no_disponible', None, 'No hay una plantilla de proforma aprobada y compatible. Estado en Meta: ' + statuses + '.'
    if submit:
        code, result = wa.call('POST', path, env, template_definition(base, typed=typed))
        if 200 <= code < 300 and result.get('id'):
            return 'presentada', None, 'Plantilla presentada a Meta. Estado: %s.' % (result.get('status') or 'por verificar')
        return 'sin_verificar', None, 'Meta no confirmó el registro de la plantilla (HTTP %d).' % code
    return 'no_disponible', None, 'Meta no tiene registrada una plantilla para proformas.'


def _recipient(c, row):
    phone = phones.whatsapp(row['client_phone'])
    if row['client_id']:
        client = c.execute('SELECT phone,identification FROM clients WHERE id=?', (row['client_id'],)).fetchone()
        if (not client or phones.whatsapp(client['phone']) != phone
                or re.sub(r'\s', '', client['identification'] or '') != row['client_identification']):
            return '', 'Los datos de la ficha del cliente cambiaron. Verifica la identidad y el celular en la proforma.'
    if not phone:
        return '', 'El cliente necesita un celular válido para WhatsApp.'
    decision = c.execute('SELECT decision,client_id FROM whatsapp_consents WHERE phone=? ORDER BY id DESC LIMIT 1', (phone,)).fetchone()
    if (not decision or decision['decision'] != 'aceptado'
            or (decision['client_id'] is not None and decision['client_id'] != row['client_id'])):
        return phone, 'Se requiere la autorización vigente de este cliente para recibir mensajes en este número.'
    return phone, ''


def _key(pid, link_id):
    return 'proforma:%d:%d' % (pid, link_id)


def history(c, pid):
    return [dict(row) for row in c.execute(
        "SELECT w.status,w.detail,w.error_code,w.attempts,w.recipient,w.template,w.template_lang,"
        "w.provider_id,w.created_at,w.sent_at,w.delivered_at,w.read_at,"
        "json_extract(w.params,'$[0]') client_name,json_extract(w.params,'$[1]') proforma_code,"
        "COALESCE(u.name,'') actor FROM whatsapp_outbox w LEFT JOIN users u ON u.id=w.created_by "
        "WHERE w.event=? AND w.dedupe_key LIKE ? ORDER BY w.id DESC", (EVENT, 'proforma:%d:%%' % pid))]


def _delivery(row):
    if not row:
        return None
    return {'status': row['status'], 'label': wa.STATE_LABELS[row['status']], 'detail': row['detail'],
            'retry': row['status'] == 'fallido' and not row['permanent'] and row['attempts'] < wa.MAX_TOTAL}


def _link(c, pid, token, now):
    row, link = proformas.lookup(c, token, now)
    if not row or row['id'] != pid or not link['usable']:
        raise proformas.ProformaError('El enlace ya no está vigente. Abre la proforma para comprobar su estado.', 409)
    return row, link


def _preview(row, template):
    params = [' '.join(row['client_name'].split())[:300], row['code']]
    if template.get('name') == IDENTITY_NAME:
        kind = public_identity.kind(row['client_identification'], row['client_document_type'])
        params.append(public_identity.LABELS.get(kind, 'identificación registrada'))
    parts = {p['type']: p for p in template['components']}
    body = re.sub(r'{{([123])}}', lambda match: params[int(match[1]) - 1], parts['BODY']['text'])
    return params, {'header': parts['HEADER']['text'], 'body': body, 'button': parts['BUTTONS']['buttons'][0]['text']}


def prepare(c, pid, token, now, base, env=None):
    row, link = _link(c, pid, token, now)
    phone, reason = _recipient(c, row)
    state, template, template_detail = audit_template(base, env)
    delivery = _delivery(c.execute('SELECT * FROM whatsapp_outbox WHERE dedupe_key=?', (_key(pid, link['id']),)).fetchone())
    return {'recipient': '+' + phone if phone else '', 'reason': reason, 'template_state': state, 'template_detail': template_detail,
            'template': template['name'] if template else '', 'language': template['language'] if template else '',
            'preview': _preview(row, template or template_definition(base))[1], 'delivery': delivery}


def send(c, pid, token, data, user, now, base, env=None):
    state, template, detail = audit_template(base, env)
    c.commit()
    c.execute('BEGIN IMMEDIATE')
    row, link = _link(c, pid, token, now)
    key = _key(pid, link['id'])
    existing = c.execute('SELECT * FROM whatsapp_outbox WHERE dedupe_key=?', (key,)).fetchone()
    if existing and not _delivery(existing)['retry']:
        return _delivery(existing)
    phone, reason = _recipient(c, row)
    if reason:
        raise proformas.ProformaError(reason, 409)
    if state != 'aprobada':
        raise proformas.ProformaError(detail, 409)
    if (data.get('recipient'), data.get('template'), data.get('language')) != ('+' + phone, template['name'], template['language']):
        raise proformas.ProformaError('El destinatario o la plantilla cambió. Actualiza la vista previa antes de enviar.', 409)
    if existing and existing['recipient'] != phone:
        raise proformas.ProformaError('El número cambió desde el primer intento. Genera un enlace nuevo después de verificar al cliente.', 409)
    if c.execute("SELECT 1 FROM whatsapp_outbox WHERE event=? AND dedupe_key LIKE ? AND dedupe_key<>? "
                 "AND (status IN ('pendiente','enviando') OR reason_kind='incierto')", (EVENT, 'proforma:%d:%%' % pid, key)).fetchone():
        raise proformas.ProformaError('Hay un envío anterior sin confirmación. Revisa el historial antes de enviar otro enlace.', 409)
    if wa.monthly_outbound_count(c, now) >= wa.MAX_MONTHLY_WA_MESSAGES:
        raise proformas.ProformaError('Se alcanzó el límite mensual de mensajes de WhatsApp.', 409)
    params, preview = _preview(row, template)
    outbox = wa.reserve_proforma(c, key, phone, row, template, params, preview, user, now, existing)
    c.commit()
    return _delivery(wa.send_proforma(c, outbox, token, now, env))


if __name__ == '__main__':
    import argparse
    from reception import public_base_url

    parser = argparse.ArgumentParser(description='Audita la plantilla de proformas en Meta.')
    parser.add_argument('--presentar', action='store_true', help='Presenta la plantilla solo si la auditoría no encuentra una equivalente.')
    parser.add_argument('--identidad', action='store_true', help='Revisa la plantilla con instrucción por tipo de documento.')
    args = parser.parse_args()
    state, template, detail = audit_template(public_base_url(), submit=args.presentar, typed=args.identidad)
    print(detail, ('%s (%s)' % (template['name'], template['language'])) if template else '')
    raise SystemExit(0 if state in ('aprobada', 'presentada') else 1)
