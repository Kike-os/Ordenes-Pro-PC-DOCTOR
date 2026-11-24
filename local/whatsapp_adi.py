"""Respuestas entrantes de WhatsApp con ADI, idempotentes y con límites mensuales."""
import hashlib
import hmac
import json
import os
import re

import adi
import whatsapp_business as wa
import whatsapp_identity
import whatsapp_handoff


def enabled(env=None):
    env = os.environ if env is None else env
    return str(env.get('WHATSAPP_ADI_AUTO_REPLY', '')).strip().lower() in ('1', 'true', 'yes', 'on')


def _text(msg):
    if not isinstance(msg, dict):
        return ''
    value = ((msg.get('text') or {}).get('body') or
             (msg.get('button') or {}).get('text') or
             ((msg.get('interactive') or {}).get('button_reply') or {}).get('title') or
             ((msg.get('interactive') or {}).get('list_reply') or {}).get('title') or '')
    return re.sub(r'\s+', ' ', str(value)).strip()[:3000]


def _signature_ok(raw, signature, secret):
    if not secret:
        return False
    expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or '')


def _conversation(c, number, secret, now):
    # Identificador derivado con HMAC: no expone ni permite adivinar el número del cliente.
    token_hash = hmac.new(secret.encode(), ('whatsapp-adi:' + number).encode(), hashlib.sha256).hexdigest()
    row = c.execute('SELECT * FROM adi_conversations WHERE token_hash=?', (token_hash,)).fetchone()
    if row:
        if row['mode'] == 'closed':
            c.execute("UPDATE adi_conversations SET mode='adi',assigned_to=NULL,updated_at=? WHERE id=?", (wa.stamp(now), row['id']))
            row = c.execute('SELECT * FROM adi_conversations WHERE id=?', (row['id'],)).fetchone()
        return row
    stamp = wa.stamp(now)
    cid = c.execute("INSERT INTO adi_conversations(token_hash,mode,created_at,updated_at,last_seen_client) VALUES (?,'adi',?,?,?)",
                    (token_hash, stamp, stamp, stamp)).lastrowid
    return c.execute('SELECT * FROM adi_conversations WHERE id=?', (cid,)).fetchone()


def handle(c, raw, signature, now, env=None):
    """Procesa mensajes entrantes solo con la función activada y una firma Meta válida."""
    cfg = wa.config(env)
    if not enabled(env) or not wa.ready(env) or not _signature_ok(raw, signature, cfg['secret']):
        return {'processed': 0, 'sent': 0}
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return {'processed': 0, 'sent': 0}

    processed = sent = 0
    for entry in payload.get('entry', []) or []:
        for change in entry.get('changes', []) or []:
            value = change.get('value', {}) or {}
            for msg in value.get('messages', []) or []:
                if not isinstance(msg, dict):
                    continue
                text = _text(msg)
                number = re.sub(r'\D', '', str(msg.get('from', '')))
                message_id = str(msg.get('id', '')).strip()
                if not text or not number or not message_id:
                    continue
                # «BAJA/STOP» se registra en el webhook normal y no genera respuesta automática.
                if wa.OPT_OUT.match(text):
                    continue

                c.execute('BEGIN IMMEDIATE')
                c.execute("INSERT OR IGNORE INTO whatsapp_adi_inbound(wa_message_id,sender,status,received_at) VALUES (?,?,'recibido',?)",
                          (message_id, number, wa.stamp(now)))
                if c.execute('SELECT changes()').fetchone()[0] != 1:
                    c.commit()
                    continue
                processed += 1
                if wa.monthly_outbound_count(c, now) >= wa.MAX_MONTHLY_WA_MESSAGES:
                    c.execute("UPDATE whatsapp_adi_inbound SET status='omitido',detail=? WHERE wa_message_id=?",
                              ('Límite mensual de seguridad de WhatsApp alcanzado.', message_id))
                    c.commit()
                    continue
                if wa.monthly_adi_reply_count(c, now) >= wa.MAX_MONTHLY_ADI_REPLIES:
                    c.execute("UPDATE whatsapp_adi_inbound SET status='omitido',detail=? WHERE wa_message_id=?",
                              ('Límite mensual de seguridad de respuestas ADI alcanzado.', message_id))
                    c.commit()
                    continue

                conv = _conversation(c, number, cfg['secret'], now)
                staff = whatsapp_handoff.installed(c)
                if staff:
                    whatsapp_handoff.remember(c, conv['id'], number, now)  # para que la respuesta del asesor salga por WhatsApp
                if conv['mode'] == 'human':
                    # Con un asesor ADI no responde, pero el mensaje SÍ se guarda para que el personal lo vea; la urgencia sube la prioridad.
                    if staff:
                        stamp_in = wa.stamp(now)
                        c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'client',?,?)", (conv['id'], text, stamp_in))
                        c.execute('UPDATE adi_conversations SET last_seen_client=?,updated_at=? WHERE id=?', (stamp_in, stamp_in, conv['id']))
                        _ss_activity(c, conv['id'], 'client', now, message_id)
                        level, labels, _ = whatsapp_handoff.signals(c, text)
                        whatsapp_handoff.request(c, conv['id'], now, 'Mensaje del cliente con un asesor', level, labels)
                    c.execute("UPDATE whatsapp_adi_inbound SET status='omitido',conversation_id=?,detail=? WHERE wa_message_id=?",
                              (conv['id'], 'La conversación está con un asesor: el mensaje queda para el personal.', message_id))
                    c.commit()
                    continue

                # Consultas sobre una orden: primero la verificación de identidad (whatsapp_identity). Sin ella ADI no revela nada de la orden.
                # El historial guarda «[código de verificación]» y un resumen neutro, nunca el código ni los datos de la orden (también viaja a la IA).
                turn = None
                c.commit()  # la conversación y el registro de idempotencia quedan guardados: un fallo posterior solo deshace la solicitud
                if staff:
                    # Atención humana REAL: se confirma al cliente solo después de guardar la solicitud. Una queja o una espera larga también la crean.
                    level, labels, escalate = whatsapp_handoff.signals(c, text)
                    update_order = None
                    if whatsapp_identity.UPDATE_REQUEST.match(whatsapp_identity.fold(text)):
                        try:
                            update_order = whatsapp_identity.active_order(c, conv['token_hash'], now, env)
                        except Exception:
                            update_order = None
                    if update_order:
                        try:
                            row, created = whatsapp_handoff.request(c, conv['id'], now, 'Solicitud de actualización técnica', level, labels, order_id=update_order)
                            c.commit()
                            turn = {'answer': 'Listo. Pedí al técnico una actualización de tu orden (solicitud %s). Te responderemos por este chat en cuanto la publique.' % row['code'],
                                    'log_client': None, 'log_answer': None}
                        except Exception as error:
                            c.rollback()
                            print('whatsapp-handoff', type(error).__name__, flush=True)
                            turn = {'answer': 'No pude registrar la solicitud de actualización en este momento. Inténtalo de nuevo en unos minutos.', 'log_client': None, 'log_answer': None}
                    elif whatsapp_handoff.wants_human(text) or escalate:
                        try:
                            row, created = whatsapp_handoff.request(c, conv['id'], now, 'Solicitud del cliente' if whatsapp_handoff.wants_human(text) else 'Escalada por ' + ', '.join(labels),
                                                                    level, labels)
                            c.commit()
                            turn = {'answer': whatsapp_handoff.confirmation(row, created), 'log_client': None, 'log_answer': None}
                        except Exception as error:
                            c.rollback()
                            print('whatsapp-handoff', type(error).__name__, flush=True)
                            turn = {'answer': 'No pude registrar tu solicitud de atención en este momento. Por favor, inténtalo de nuevo en unos minutos o llámanos; '
                                              'no quiero decirte que te transferí sin haberlo hecho.', 'log_client': None, 'log_answer': None}
                elif whatsapp_handoff.wants_human(text):
                    # Sin la migración 116 no hay transferencia real: se dice con claridad, nunca se deja que la IA la «confirme».
                    turn = {'answer': 'En este momento no puedo transferirte a un asesor por este chat. Por favor, comunícate con PC-DOCTOR S.A. por teléfono '
                                      'o visítanos en el local; disculpa las molestias.', 'log_client': None, 'log_answer': None}
                if turn is None:
                    try:
                        turn = whatsapp_identity.respond(c, conv['token_hash'], number, text, now, env)
                    except Exception as error:
                        print('whatsapp-identity', type(error).__name__, flush=True)
                        turn = {'answer': whatsapp_identity.THIRD_PARTY, 'log_client': None, 'log_answer': None}
                now_text = wa.stamp(now)
                c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'client',?,?)",
                          (conv['id'], (turn['log_client'] if turn and turn['log_client'] else text), now_text))
                c.execute("UPDATE adi_conversations SET last_seen_client=?,updated_at=? WHERE id=?",
                          (now_text, now_text, conv['id']))
                _ss_activity(c, conv['id'], 'client', now, message_id)
                c.execute("UPDATE whatsapp_adi_inbound SET status='generando',conversation_id=? WHERE wa_message_id=?",
                          (conv['id'], message_id))
                c.commit()

                if turn:
                    answer = str(turn['answer'])[:3000]
                    logged = str(turn['log_answer'] if turn['log_answer'] is not None else turn['answer'])[:3000]
                else:
                    try:
                        answer = str(adi.reply(c, text, conversation_id=conv['id'], session={}, lang='es-EC') or '').strip()[:3000]
                        if not answer:
                            raise RuntimeError('adi_empty_reply')
                    except Exception as error:
                        c.execute("UPDATE whatsapp_adi_inbound SET status='fallido',detail=? WHERE wa_message_id=?",
                                  ('ADI no pudo preparar una respuesta (' + type(error).__name__ + ').', message_id))
                        c.commit()
                        continue
                    logged = answer

                c.execute('BEGIN IMMEDIATE')
                if wa.monthly_outbound_count(c, now) >= wa.MAX_MONTHLY_WA_MESSAGES:
                    c.execute("UPDATE whatsapp_adi_inbound SET status='omitido',detail=? WHERE wa_message_id=?",
                              ('Límite mensual de seguridad de WhatsApp alcanzado.', message_id))
                    c.commit()
                    continue
                c.execute("UPDATE whatsapp_adi_inbound SET status='enviando' WHERE wa_message_id=?", (message_id,))
                c.commit()

                code, result = wa.call('POST', '%s/messages' % cfg['phone_id'], env, {
                    'messaging_product': 'whatsapp',
                    'recipient_type': 'individual',
                    'to': number,
                    'type': 'text',
                    'text': {'preview_url': False, 'body': answer},
                })
                provider = ''
                if code == 200 and isinstance(result, dict) and result.get('messages'):
                    provider = str(result['messages'][0].get('id', '') or '')
                c.execute('BEGIN IMMEDIATE')
                if provider:
                    stamp = wa.stamp(now)
                    c.execute("INSERT INTO adi_messages(conversation_id,author,content,created_at) VALUES (?,'adi',?,?)",
                              (conv['id'], logged, stamp))
                    c.execute('UPDATE adi_conversations SET updated_at=? WHERE id=?', (stamp, conv['id']))
                    _ss_activity(c, conv['id'], 'adi', now, 'adi-' + str(message_id))
                    c.execute("UPDATE whatsapp_adi_inbound SET status='enviado',provider_id=?,replied_at=?,detail='' WHERE wa_message_id=?",
                              (provider, stamp, message_id))
                    sent += 1
                else:
                    permanent, kind, meta_code, detail = wa.classify(code, result)
                    c.execute("UPDATE whatsapp_adi_inbound SET status='fallido',detail=? WHERE wa_message_id=?",
                              ((detail or 'Meta no aceptó la respuesta de ADI.')[:300], message_id))
                c.commit()
    return {'processed': processed, 'sent': sent}


def _ss_activity(c, conv_id, who, now, message_id=None):
    """ADI Live Support 4.0: actividad válida para el cierre por inactividad. Nunca interrumpe la atención si falla."""
    try:
        import support_sessions
        support_sessions.activity(c, conv_id, who, now, message_id)
    except Exception as error:
        print('support-session', type(error).__name__, flush=True)
