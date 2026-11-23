"""Atención humana real desde WhatsApp (docs/WHATSAPP-ATENCION.md).

- «ASESOR», «HUMANO», «quiero hablar con alguien»… crean una solicitud REAL en la base (código ATN-…), dejan la conversación en modo
  humano (ADI deja de responder) y aparece en el Centro de Atención y en las notificaciones del personal. ADI solo confirma la
  transferencia cuando la solicitud quedó guardada; si falla, lo dice y da el teléfono.
- Una sola solicitud abierta por conversación (índice único): los mensajes repetidos no la duplican; solo suben la prioridad.
- Prioridad por urgencia con reglas configurables (viaje, urgencia, espera larga, queja…). Una queja o una espera larga también
  crean la solicitud aunque el cliente no pida un asesor.
- El asesor acepta, responde (sale por WhatsApp), transfiere, resuelve o cierra; al cerrar, ADI vuelve a atender.
Si las tablas de la migración 116 aún no existen, nada de esto se activa y ADI responde como antes, sin prometer transferencias."""
import json
import re

import whatsapp_business as wa

TABLES = ('whatsapp_conversations', 'adi_handoffs', 'whatsapp_operator_sends')
HUMAN = re.compile(r'(\basesor(a|es)?\b|\bhumano\b|\bpersona real\b|\bagente\b|\boperador(a)?\b|hablar con (alguien|una persona|un humano|el personal|un tecnico|el tecnico)|'
                   r'atencion (personal|humana|personalizada)|que me atienda (alguien|una persona)|comunicarme con (alguien|una persona|un asesor)|\bsoporte humano\b|'
                   r'\bhuman\b|\bagent\b|talk to (someone|a person))', re.I)
SETTING = 'whatsapp_handoff_rules'
# Reglas de urgencia: patrón sobre el texto sin tildes, nivel y si basta para crear la solicitud aunque no se pida un asesor.
DEFAULT_RULES = [
    {'label': 'Viaje', 'pattern': r'\b(viaj(o|e|ar|amos)|me voy de viaje|salgo del pais|vuelo)\b', 'level': 'urgente', 'escalate': False},
    {'label': 'Urgencia', 'pattern': r'\b(urgente(mente)?|urge|emergencia|lo necesito (ya|hoy|para hoy|ahora)|necesito mi (equipo|laptop|computadora) (ya|hoy|urgente))', 'level': 'urgente', 'escalate': False},
    {'label': 'No puede esperar', 'pattern': r'no puedo esperar', 'level': 'alta', 'escalate': False},
    {'label': 'Espera larga', 'pattern': r'(llevo (mucho tiempo|semanas|dias|meses) esperando|ya (es|son) (mucho tiempo|demasiado)|nadie me (responde|contesta|atiende))', 'level': 'alta', 'escalate': True},
    {'label': 'Queja', 'pattern': r'\b(queja|reclamo|denuncia|presentar una queja|poner una queja|estoy (muy )?molest[oa]|pesimo servicio|mal servicio|indignad[oa])\b', 'level': 'urgente', 'escalate': True},
]
LEVELS = {'normal': 0, 'alta': 1, 'urgente': 2}
LABELS = {'pendiente': 'Pendiente de asignación', 'asignada': 'En atención', 'resuelta': 'Resuelta', 'cerrada': 'Cerrada'}


class HandoffError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def fold(text):
    import unicodedata
    return ''.join(ch for ch in unicodedata.normalize('NFD', str(text or '').casefold()) if not unicodedata.combining(ch))


def installed(c):
    return c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN (%s)" % ','.join('?' * len(TABLES)), TABLES).fetchone()[0] == len(TABLES)


def rules(c):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (SETTING,)).fetchone()
    try:
        stored = json.loads(row['value']) if row else None
    except (TypeError, ValueError):
        stored = None
    return stored if isinstance(stored, list) and stored else DEFAULT_RULES


def save_rules(c, items, user):
    if not user or user['role'] != 'administrador':
        raise HandoffError('Solo administración configura las reglas de prioridad.', 403)
    if not isinstance(items, list) or not 1 <= len(items) <= 30:
        raise HandoffError('Indica entre 1 y 30 reglas.')
    clean = []
    for item in items:
        if not isinstance(item, dict):
            raise HandoffError('Regla no válida.')
        label, pattern, level = str(item.get('label', '')).strip()[:40], str(item.get('pattern', '')).strip()[:300], str(item.get('level', ''))
        if not label or not pattern or level not in ('alta', 'urgente'):
            raise HandoffError('Cada regla necesita nombre, patrón y nivel (alta o urgente).')
        try:
            re.compile(pattern)
        except re.error:
            raise HandoffError('El patrón de «%s» no es válido.' % label) from None
        clean.append({'label': label, 'pattern': pattern, 'level': level, 'escalate': bool(item.get('escalate'))})
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (SETTING, json.dumps(clean, ensure_ascii=False)))
    return clean


def signals(c, text):
    """(nivel, etiquetas, crea_solicitud) según las reglas configuradas."""
    q, level, found, escalate = fold(text), 'normal', [], False
    for rule in rules(c):
        try:
            if re.search(rule['pattern'], q, re.I):
                found.append(rule['label'])
                escalate = escalate or bool(rule.get('escalate'))
                if LEVELS[rule['level']] > LEVELS[level]:
                    level = rule['level']
        except (re.error, KeyError):
            continue
    return level, found, escalate


def wants_human(text):
    return bool(HUMAN.search(fold(text)))


def open_case(c, conversation_id):
    return c.execute("SELECT * FROM adi_handoffs WHERE conversation_id=? AND status IN ('pendiente','asignada') ORDER BY id DESC LIMIT 1", (conversation_id,)).fetchone()


def _code(c, now):
    day = now.strftime('%Y%m%d')
    n = c.execute("SELECT COUNT(*) FROM adi_handoffs WHERE code LIKE ?", ('ATN-' + day + '-%',)).fetchone()[0] + 1
    while c.execute('SELECT 1 FROM adi_handoffs WHERE code=?', ('ATN-%s-%04d' % (day, n),)).fetchone():
        n += 1
    return 'ATN-%s-%04d' % (day, n)


def request(c, conversation_id, now, reason, level='normal', labels=(), order_id=None, channel='whatsapp', by_client=True):
    """Crea la solicitud (o actualiza la abierta: nunca dos) y deja la conversación en modo humano. Devuelve (fila, creada)."""
    stamp = wa.stamp(now)
    current = open_case(c, conversation_id)
    if current:
        new_level = level if LEVELS[level] > LEVELS[current['priority']] else current['priority']
        merged = ', '.join(dict.fromkeys([s for s in (current['signals'] or '').split(', ') if s] + list(labels)))
        c.execute('UPDATE adi_handoffs SET priority=?,signals=?,updated_at=?,order_id=COALESCE(order_id,?) WHERE id=?', (new_level, merged[:300], stamp, order_id, current['id']))
        return c.execute('SELECT * FROM adi_handoffs WHERE id=?', (current['id'],)).fetchone(), False
    hid = c.execute('INSERT INTO adi_handoffs(code,conversation_id,channel,status,priority,reason,signals,order_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (_code(c, now), conversation_id, channel, 'pendiente', level, reason[:200], ', '.join(labels)[:300], order_id, stamp, stamp)).lastrowid
    c.execute("UPDATE adi_conversations SET mode='human',assigned_to=NULL,updated_at=? WHERE id=?", (stamp, conversation_id))
    if by_client:  # si la abre el personal (tomar o reabrir), su propia acción ya queda en el historial
        c.execute("INSERT INTO adi_actions(conversation_id,user_id,action,created_at,details) VALUES (?,NULL,'handoff_requested',?,?)",
                  (conversation_id, stamp, ('Prioridad ' + level + (' · ' + ', '.join(labels) if labels else ''))[:200]))
    return c.execute('SELECT * FROM adi_handoffs WHERE id=?', (hid,)).fetchone(), True


def confirmation(row, created):
    pr = {'urgente': ' Marqué tu caso como URGENTE.', 'alta': ' Marqué tu caso con prioridad alta.'}.get(row['priority'], '')
    if created:
        return ('Listo. Registré tu solicitud de atención con el código %s.%s\n\nUn asesor de PC-DOCTOR S.A. te responderá por este mismo chat. '
                'Mientras tanto, ADI no responderá automáticamente para no interrumpir la atención.' % (row['code'], pr))
    return 'Tu solicitud %s ya está registrada (%s).%s Un asesor te responderá por este chat.' % (row['code'], LABELS[row['status']].lower(), pr)


# ---- Envío por WhatsApp de lo que escribe el personal -------------------------------------------------------------------------------
def number_of(c, conversation_id):
    if not installed(c):
        return ''
    row = c.execute('SELECT wa_number FROM whatsapp_conversations WHERE conversation_id=?', (conversation_id,)).fetchone()
    return row['wa_number'] if row else ''


def remember(c, conversation_id, number, now):
    if not installed(c) or not number:
        return
    stamp = wa.stamp(now)
    c.execute('INSERT INTO whatsapp_conversations(conversation_id,wa_number,created_at,last_client_at) VALUES (?,?,?,?) '
              'ON CONFLICT(conversation_id) DO UPDATE SET wa_number=excluded.wa_number,last_client_at=excluded.last_client_at', (conversation_id, number, stamp, stamp))


def send_text(c, conversation_id, text, now, env=None, message_id=None):
    """Envía un texto libre por WhatsApp (dentro de la ventana de 24 h que abre el cliente). (ok, detalle)."""
    number = number_of(c, conversation_id)
    if not number:
        return None, ''
    if not wa.ready(env):
        return False, 'WhatsApp Business no está configurado en el servidor.'
    if wa.monthly_outbound_count(c, now) >= wa.MAX_MONTHLY_WA_MESSAGES:
        return False, 'Se alcanzó el límite mensual de seguridad de WhatsApp.'
    c.commit()
    code, result = wa.call('POST', '%s/messages' % wa.config(env)['phone_id'], env, {'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': number,
                                                                                    'type': 'text', 'text': {'preview_url': False, 'body': str(text)[:3000]}})
    provider = str(result['messages'][0].get('id', '') or '') if code == 200 and isinstance(result, dict) and result.get('messages') else ''
    detail = '' if provider else wa.classify(code, result)[3]
    if detail and ('131047' in detail or '24' in detail and 'hour' in detail.lower()):
        detail = 'Pasaron más de 24 horas desde el último mensaje del cliente: WhatsApp solo permite responder con una plantilla aprobada. ' + detail
    if message_id:
        c.execute('INSERT OR REPLACE INTO whatsapp_operator_sends(message_id,conversation_id,status,provider_id,detail,created_at) VALUES (?,?,?,?,?,?)',
                  (message_id, conversation_id, 'enviado' if provider else 'fallido', provider, detail[:300], wa.stamp(now)))
    return bool(provider), detail


# ---- Acciones del personal sobre la solicitud -------------------------------------------------------------------------------------
def on_staff_action(c, conversation_id, action, user, now, env=None, target=None):
    """Sincroniza la solicitud con las acciones del Centro de Atención y avisa al cliente por WhatsApp. Devuelve un texto de estado."""
    if not installed(c):
        return ''
    stamp = wa.stamp(now)
    case = open_case(c, conversation_id)
    note = ''
    if action in ('takeover', 'reply', 'reopen'):
        if case and case['status'] == 'pendiente':
            c.execute("UPDATE adi_handoffs SET status='asignada',accepted_at=?,accepted_by=?,updated_at=? WHERE id=?", (stamp, user['id'], stamp, case['id']))
            if action == 'takeover':
                ok, detail = send_text(c, conversation_id, 'Hola, te atiende %s de PC-DOCTOR S.A. (caso %s). Cuéntame en qué te ayudo.' % ((user['name'] or 'un asesor').split(' ')[0], case['code']), now, env)
                note = '' if ok in (True, None) else 'No se pudo avisar al cliente por WhatsApp: ' + detail
        elif not case and action in ('takeover', 'reopen'):
            row, _ = request(c, conversation_id, now, 'Tomada por el personal', channel='whatsapp' if number_of(c, conversation_id) else 'web', by_client=False)
            c.execute("UPDATE adi_handoffs SET status='asignada',accepted_at=?,accepted_by=?,updated_at=? WHERE id=?", (stamp, user['id'], stamp, row['id']))
    elif action == 'transfer' and case:
        c.execute("UPDATE adi_handoffs SET status='asignada',accepted_by=?,updated_at=? WHERE id=?", (target, stamp, case['id']))
    elif action in ('close', 'resume') and case:
        c.execute("UPDATE adi_handoffs SET status=?,closed_at=?,closed_by=?,updated_at=?,resolution=? WHERE id=?",
                  ('resuelta' if action == 'resume' else 'cerrada', stamp, user['id'], stamp, 'ADI reactivada' if action == 'resume' else 'Atención cerrada', case['id']))
        ok, detail = send_text(c, conversation_id, ('Tu atención %s terminó. Gracias por comunicarte con PC-DOCTOR S.A.; si necesitas algo más, escríbenos y ADI te ayudará.' % case['code']), now, env)
        note = '' if ok in (True, None) else 'No se pudo avisar al cliente por WhatsApp: ' + detail
    return note


def for_conversation(c, conversation_id, now):
    if not installed(c):
        return None
    case = c.execute('SELECT h.*,u.name accepted_name FROM adi_handoffs h LEFT JOIN users u ON u.id=h.accepted_by WHERE h.conversation_id=? ORDER BY h.id DESC LIMIT 1', (conversation_id,)).fetchone()
    channel = 'whatsapp' if number_of(c, conversation_id) else 'web'
    out = {'channel': channel, 'case': None}
    if case:
        out['case'] = {'code': case['code'], 'status': case['status'], 'status_label': LABELS[case['status']], 'priority': case['priority'], 'signals': case['signals'],
                       'reason': case['reason'], 'created_at': case['created_at'], 'accepted_at': case['accepted_at'], 'accepted_by': case['accepted_name'] or '', 'closed_at': case['closed_at']}
    failed = c.execute("SELECT COUNT(*) FROM whatsapp_operator_sends WHERE conversation_id=? AND status='fallido'", (conversation_id,)).fetchone()[0]
    out['failed_sends'] = failed
    return out


def board(c):
    """Resumen para la bandeja: solicitudes abiertas por prioridad y espera."""
    if not installed(c):
        return {'installed': False, 'open': [], 'counts': {}}
    rows = [dict(r) for r in c.execute("SELECT h.id,h.code,h.conversation_id,h.status,h.priority,h.signals,h.created_at,h.accepted_at,u.name accepted_name FROM adi_handoffs h "
                                       "LEFT JOIN users u ON u.id=h.accepted_by WHERE h.status IN ('pendiente','asignada') ORDER BY CASE h.priority WHEN 'urgente' THEN 0 WHEN 'alta' THEN 1 ELSE 2 END, h.created_at")]
    counts = {'pendiente': sum(r['status'] == 'pendiente' for r in rows), 'asignada': sum(r['status'] == 'asignada' for r in rows),
              'urgente': sum(r['priority'] == 'urgente' for r in rows)}
    return {'installed': True, 'open': rows, 'counts': counts}
