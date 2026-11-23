"""Verificación de identidad por WhatsApp antes de que ADI informe sobre una orden (docs/WHATSAPP-IDENTIDAD.md).

Conocer el número de orden, el nombre, la cédula o el teléfono NO basta. ADI pide el número de orden, ofrece enviar un código de 6 dígitos
al teléfono autorizado de esa orden (titular o contacto registrado por administración) mostrando solo sus dos últimas cifras, y solo con
el código correcto abre una sesión verificada para ESA orden, que caduca a los 15 minutos sin actividad.

Reglas: código con `secrets` (criptográficamente seguro), 5 minutos de vigencia, 3 intentos, un solo uso, guardado solo como HMAC;
límites de consultas y de envíos por conversación y por orden; el código nunca se entrega en el chat que lo pide salvo que ese número sea
el autorizado (va siempre al teléfono autorizado mediante la plantilla de autenticación aprobada en Meta); sin verificación ADI no revela
nada de la orden (ni titular, ni equipo, ni fechas, ni importes, ni enlaces). Cambiar los contactos autorizados (o el teléfono del
titular) invalida las sesiones y los códigos pendientes. ADI nunca cambia un teléfono: la recuperación es una revisión humana."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

import whatsapp_business as wa

CODE_MINUTES = 5
MAX_ATTEMPTS = 3
IDLE_MINUTES = 15
MAX_SESSION_MINUTES = 60          # tope absoluto de una sesión verificada, aunque haya actividad
LOOKUPS_PER_HOUR = 5              # números de orden consultados por conversación (evita recorrer órdenes)
CODES_PER_HOUR_CONVERSATION = 3   # envíos y reenvíos por conversación
CODES_PER_HOUR_ORDER = 3          # envíos por orden, venga de donde venga
CODES_PER_DAY_ORDER = 6
ORDER_CODE = re.compile(r'\b[A-Z]{2,4}-\d{4,8}(?:-\d{3,6})?(?:-E\d{2})?\b')
YES = re.compile(r'^(si|sí|s|ok|okay|dale|claro|de acuerdo|enviar|envialo|envíalo|envia|envía|quiero recibirlo|por favor|si por favor|sí por favor)[.! ]*$', re.I)
NO = re.compile(r'^(no|no gracias|cancelar|cancela|ahora no)[.! ]*$', re.I)
CANCEL = re.compile(r'^(cancelar|cancela|salir|terminar|cerrar|cerrar sesion|cerrar sesión)[.! ]*$', re.I)
RESEND = re.compile(r'^(reenviar|reenvia|reenvía|reenviar codigo|reenviar código|otro codigo|otro código|no me llego|no me llegó)[.! ]*$', re.I)
SIX = re.compile(r'^\D{0,3}(\d{3})\s?-?\s?(\d{3})\D{0,3}$')
RECOVERY = re.compile(r'(cambi[eé] (de )?(numero|número|celular|telefono|teléfono)|nuevo (numero|número|celular)|ya no tengo (ese|el) (numero|número|celular)|perd[ií] (mi )?(celular|telefono|teléfono|chip)|no tengo acceso al (numero|número|celular|telefono|teléfono))', re.I)
ORDER_INTENT = re.compile(r'(\b(pcd|op)-\d|mi orden|estado de mi|como va mi|como va el arreglo|ya esta list[oa] mi|ya estan list[oa]s? mi|'
                          r'seguimiento de mi|novedades? de mi|avance de mi|mi reparacion|mi equipo ya|cuando (me )?entregan mi|cuando esta list[oa] mi|'
                          r'order status|repair status|my order)', re.I)  # se aplica al texto sin tildes; «mi equipo» solo no basta (p. ej., precios)
ALERT_KINDS = ('codigo_bloqueado', 'limite_consultas', 'limite_codigos', 'recuperacion_solicitada')
FAILED_KINDS = ('codigo_incorrecto', 'codigo_bloqueado', 'codigo_caducado', 'envio_fallido', 'limite_consultas', 'limite_codigos', 'sin_contacto')
AUDIT_KINDS = ('contacto_agregado', 'contacto_revocado', 'sesiones_revocadas', 'contactos_modificados')
EVENT_LABELS = {'consulta_orden': 'Consulta de una orden', 'sin_contacto': 'Orden sin teléfono autorizado (no se envió código)', 'codigo_enviado': 'Código enviado',
                'envio_fallido': 'No se pudo enviar el código', 'codigo_incorrecto': 'Código incorrecto', 'codigo_bloqueado': 'Código bloqueado por intentos fallidos',
                'codigo_caducado': 'Código caducado o anulado', 'verificado': 'Identidad verificada', 'limite_consultas': 'Límite de consultas alcanzado',
                'limite_codigos': 'Límite de envíos de código alcanzado', 'recuperacion_solicitada': 'Solicitud de recuperación de acceso (cambio de número)',
                'contacto_agregado': 'Contacto autorizado agregado', 'contacto_revocado': 'Contacto autorizado revocado', 'sesiones_revocadas': 'Acceso revocado por administración',
                'contactos_modificados': 'Contactos de la orden modificados: sesiones y códigos anulados', 'sesion_cerrada': 'Sesión cerrada'}
DENIED = ('Por protección de datos, no puedo verificar esa orden por este medio. Revisa el número en tu comprobante de servicio. '
          'Si no tienes acceso al medio de contacto registrado, puedo solicitar la intervención de nuestro personal: escribe ASESOR.')
THIRD_PARTY = ('Por protección de datos, necesito verificar que eres una persona autorizada antes de consultar información de esta orden. '
               'Si no tienes acceso al medio de contacto registrado, puedo solicitar la intervención de nuestro personal: escribe ASESOR.')


class IdentityError(Exception):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


# ---- utilidades -------------------------------------------------------------------------------------------------------------------
def _iso(now):
    return wa.stamp(now)


def _ago(now, **delta):
    return wa.stamp(now - timedelta(**delta))


def _key(env=None):
    secret = wa.config(env)['secret']
    if not secret:
        raise IdentityError('Falta la clave de la aplicación de WhatsApp en el servidor.', 503)
    return secret.encode()


def _mac(env, *parts):
    return hmac.new(_key(env), '\x1f'.join(parts).encode(), hashlib.sha256).hexdigest()


def tail(number):
    digits = re.sub(r'\D', '', str(number or ''))
    return digits[-2:] if len(digits) >= 2 else ''


def fold(text):
    import unicodedata
    return ''.join(ch for ch in unicodedata.normalize('NFD', str(text or '').casefold()) if not unicodedata.combining(ch)).strip()


def find_order_code(text):
    found = ORDER_CODE.search(str(text or '').upper())
    return found.group(0) if found else ''


def event(c, kind, order_id=None, conversation='', detail='', now=None):
    c.execute('INSERT INTO wa_identity_events(order_id,conversation_hash,kind,detail,created_at) VALUES (?,?,?,?,?)',
              (order_id, conversation or '', kind, str(detail or '')[:200], _iso(now or datetime.now(wa_tz()))))


def wa_tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo('America/Guayaquil')


# ---- contactos autorizados ----------------------------------------------------------------------------------------------------------
def _order(c, order_id):
    return c.execute('SELECT o.id,o.code,o.status,cl.id client_id,cl.phone FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id '
                     'WHERE o.id=?', (order_id,)).fetchone()


def recipients(c, order_id):
    """Teléfonos autorizados de la orden: el del titular (si sirve para WhatsApp) y los contactos vigentes registrados por administración."""
    row = _order(c, order_id)
    if not row:
        return []
    out = []
    titular = wa.number_for(row['phone'] or '')
    if titular:
        out.append({'kind': 'titular', 'number': titular, 'contact_id': None})
    for contact in c.execute("SELECT id,phone FROM order_authorized_contacts WHERE order_id=? AND revoked_at='' ORDER BY id", (order_id,)):
        if contact['phone'] and all(contact['phone'] != item['number'] for item in out):
            out.append({'kind': 'contacto', 'number': contact['phone'], 'contact_id': contact['id']})
    return out


def fingerprint(c, order_id, env=None):
    return _mac(env, 'contactos', str(order_id), *sorted(item['kind'] + ':' + item['number'] for item in recipients(c, order_id)))


def _choose(c, order_id, sender):
    found = recipients(c, order_id)
    for item in found:
        if item['number'] == sender:
            return item
    return found[0] if found else None


# ---- estado de la conversación -------------------------------------------------------------------------------------------------
def _state(c, conv):
    return c.execute('SELECT * FROM wa_identity_state WHERE conversation_hash=?', (conv,)).fetchone()


def _set_state(c, conv, step, now, order_id=None, challenge_id=None):
    c.execute('INSERT INTO wa_identity_state(conversation_hash,step,order_id,challenge_id,updated_at) VALUES (?,?,?,?,?) '
              'ON CONFLICT(conversation_hash) DO UPDATE SET step=excluded.step,order_id=excluded.order_id,challenge_id=excluded.challenge_id,updated_at=excluded.updated_at',
              (conv, step, order_id, challenge_id, _iso(now)))


def _clear_state(c, conv):
    c.execute('DELETE FROM wa_identity_state WHERE conversation_hash=?', (conv,))


def _end_session(c, session_id, reason, now, user_id=None):
    c.execute("UPDATE wa_identity_sessions SET ended_at=?,end_reason=?,revoked_by=COALESCE(?,revoked_by) WHERE id=? AND ended_at=''",
              (_iso(now), reason, user_id, session_id))


def active_session(c, conv, now, env=None):
    """La sesión verificada vigente de la conversación, o None. Cierra la que caducó (inactividad, tope o cambio de contactos)."""
    row = c.execute("SELECT * FROM wa_identity_sessions WHERE conversation_hash=? AND ended_at='' ORDER BY id DESC LIMIT 1", (conv,)).fetchone()
    if not row:
        return None
    reason = ''
    if row['last_activity'] < _ago(now, minutes=IDLE_MINUTES):
        reason = 'inactividad'
    elif row['created_at'] < _ago(now, minutes=MAX_SESSION_MINUTES):
        reason = 'tiempo_maximo'
    elif not hmac.compare_digest(row['contacts_fingerprint'], fingerprint(c, row['order_id'], env)):
        reason = 'contactos_modificados'
        event(c, 'contactos_modificados', row['order_id'], conv, 'Cambió el teléfono del titular o un contacto autorizado.', now)
    if reason:
        _end_session(c, row['id'], reason, now)
        return None
    return row


# ---- información autorizada -----------------------------------------------------------------------------------------------------
def _when(value):
    try:
        moment = datetime.fromisoformat(str(value))
        if moment.tzinfo:
            moment = moment.astimezone(wa_tz())
        return moment.strftime('%d/%m/%Y %H:%M') if 'T' in str(value) or ' ' in str(value) else moment.strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return ''


def facts(c, order_id):
    """Solo lo autorizado para el titular verificado: estado, equipo, última actualización, observación visible para el cliente y la
    entrega estimada. Nunca importes, series, fotos, documentos, enlaces privados ni notas internas."""
    from reception import DEVICE_TYPES
    order = c.execute('SELECT o.id,o.code,o.status,s.label,o.estimated_delivery,COALESCE(NULLIF(d.kind,\'\'),d.category) type,d.brand,d.model '
                      'FROM orders o JOIN statuses s ON s.code=o.status JOIN devices d ON d.id=o.device_id WHERE o.id=?', (order_id,)).fetchone()
    if not order:
        return None
    last = c.execute('SELECT MAX(occurred_at) FROM order_history WHERE order_id=?', (order_id,)).fetchone()[0]
    note = c.execute("SELECT client_message FROM order_followups WHERE order_id=? AND client_visible=1 AND trim(client_message)!='' ORDER BY id DESC LIMIT 1",
                     (order_id,)).fetchone()
    device = ' '.join(x for x in (DEVICE_TYPES.get(order['type'], ''), order['brand'] or '', order['model'] or '') if x)
    lines = ['Orden: ' + order['code'], 'Estado: ' + order['label']]
    if device:
        lines.append('Equipo: ' + device)
    if last:
        lines.append('Última actualización: ' + (_when(last) or str(last)[:16]))
    if note:
        lines.append('Observaciones: ' + re.sub(r'\s+', ' ', note['client_message']).strip()[:400])
    if order['estimated_delivery'] and order['status'] != 'entregado':
        lines.append('Entrega estimada: ' + (_when(order['estimated_delivery']) or order['estimated_delivery']))
    return '\n'.join(lines)


# ---- flujo de la conversación -----------------------------------------------------------------------------------------------------
def _reply(answer, log_client=None, log_answer=None):
    """`log_*`: lo que se guarda en el historial de la conversación (nunca el código ni los datos de la orden, que también viajarían a la IA)."""
    return {'answer': answer, 'log_client': log_client, 'log_answer': log_answer if log_answer is not None else answer}


def _count(c, sql, args):
    return int(c.execute(sql, args).fetchone()[0] or 0)


def _lookup(c, conv, sender, code, now, env):
    if _count(c, "SELECT COUNT(*) FROM wa_identity_events WHERE conversation_hash=? AND kind='consulta_orden' AND created_at>=?", (conv, _ago(now, hours=1))) >= LOOKUPS_PER_HOUR:
        event(c, 'limite_consultas', None, conv, 'Más de %d números de orden en una hora.' % LOOKUPS_PER_HOUR, now)
        _clear_state(c, conv)
        return _reply('Por seguridad, alcanzaste el límite de consultas por ahora. Inténtalo más tarde o escribe ASESOR para que te atienda nuestro personal.')
    import reception
    row = c.execute('SELECT id FROM orders WHERE upper(code)=?', (reception.current_order_code(c, code).upper(),)).fetchone()
    event(c, 'consulta_orden', row['id'] if row else None, conv, '' if row else 'Número sin coincidencia.', now)
    target = _choose(c, row['id'], sender) if row else None
    if not target:
        if row:
            event(c, 'sin_contacto', row['id'], conv, 'La orden no tiene un celular autorizado para WhatsApp.', now)
        _clear_state(c, conv)
        return _reply(DENIED)
    _set_state(c, conv, 'esperando_confirmacion', now, row['id'])
    return _reply('Gracias. Para proteger la información de nuestros clientes, necesitamos confirmar tu identidad.\n\n'
                  'Podemos enviar un código de verificación al teléfono autorizado que termina en ••%s.\n\n¿Deseas recibir el código? Responde SÍ o NO.' % tail(target['number']))


def _send(c, conv, sender, order_id, now, env):
    hour = _ago(now, hours=1)
    if (_count(c, "SELECT COUNT(*) FROM wa_identity_challenges WHERE conversation_hash=? AND created_at>=?", (conv, hour)) >= CODES_PER_HOUR_CONVERSATION
            or _count(c, "SELECT COUNT(*) FROM wa_identity_challenges WHERE order_id=? AND created_at>=?", (order_id, hour)) >= CODES_PER_HOUR_ORDER
            or _count(c, "SELECT COUNT(*) FROM wa_identity_challenges WHERE order_id=? AND created_at>=?", (order_id, _ago(now, days=1))) >= CODES_PER_DAY_ORDER):
        event(c, 'limite_codigos', order_id, conv, 'Se alcanzó el límite de envíos de código.', now)
        _clear_state(c, conv)
        return _reply('Por seguridad, ya se enviaron varios códigos para esta orden. Espera un momento antes de solicitar otro, o escribe ASESOR para que te atienda nuestro personal.')
    target = _choose(c, order_id, sender)
    if not target:
        _clear_state(c, conv)
        return _reply(DENIED)
    cfg = wa.settings(c)
    c.execute("UPDATE wa_identity_challenges SET status='anulado' WHERE conversation_hash=? AND status='pendiente'", (conv,))
    code = '%06d' % secrets.randbelow(1000000)
    nonce = secrets.token_hex(16)
    cid = c.execute('INSERT INTO wa_identity_challenges(conversation_hash,order_id,recipient_hash,recipient_tail,recipient_kind,contact_id,nonce,code_hash,status,created_at,expires_at) '
                    "VALUES (?,?,?,?,?,?,?,?,'pendiente',?,?)",
                    (conv, order_id, _mac(env, 'destinatario', target['number']), tail(target['number']), target['kind'], target['contact_id'], nonce,
                     _mac(env, 'codigo', nonce, code), _iso(now), _iso(now + timedelta(minutes=CODE_MINUTES)))).lastrowid
    problem = ''
    if not cfg.get('otp_template'):
        problem = 'Falta configurar la plantilla de autenticación de WhatsApp.'
    elif wa.monthly_outbound_count(c, now) > wa.MAX_MONTHLY_WA_MESSAGES:
        problem = 'Se alcanzó el límite mensual de seguridad de WhatsApp.'
    provider = ''
    if not problem:
        c.commit()  # el reto queda registrado antes de llamar a Meta; la llamada no retiene la base
        status, result = wa.call('POST', '%s/messages' % wa.config(env)['phone_id'], env, {
            'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': target['number'], 'type': 'template',
            'template': {'name': cfg['otp_template'], 'language': {'code': cfg.get('otp_lang') or 'es'}, 'components': [
                {'type': 'body', 'parameters': [{'type': 'text', 'text': code}]},
                {'type': 'button', 'sub_type': 'url', 'index': '0', 'parameters': [{'type': 'text', 'text': code}]}]}})
        code = ''  # el código no se conserva en memoria más de lo necesario
        if status == 200 and isinstance(result, dict) and result.get('messages'):
            provider = str(result['messages'][0].get('id', '') or '')
        else:
            problem = wa.classify(status, result)[3]
    if not provider:
        c.execute("UPDATE wa_identity_challenges SET status='envio_fallido',send_detail=? WHERE id=?", ((problem or 'Meta no aceptó el mensaje.')[:300], cid))
        event(c, 'envio_fallido', order_id, conv, (problem or 'Meta no aceptó el mensaje.')[:200], now)
        _clear_state(c, conv)
        return _reply('No pudimos enviar el código de verificación en este momento. Por seguridad, no compartiremos información de la orden sin verificar tu identidad. '
                      'Inténtalo más tarde o escribe ASESOR para que te atienda nuestro personal.')
    c.execute('UPDATE wa_identity_challenges SET send_detail=? WHERE id=?', ('Aceptado por Meta (' + provider[:60] + ').', cid))
    event(c, 'codigo_enviado', order_id, conv, ('Al titular' if target['kind'] == 'titular' else 'A un contacto autorizado') + ' ••' + tail(target['number']), now)
    _set_state(c, conv, 'esperando_codigo', now, order_id, cid)
    other = '' if target['number'] == sender else '\n\nEl código llega al teléfono autorizado, no a este chat: si ese teléfono no es el tuyo, pídeselo a su titular.'
    return _reply('Hemos solicitado el envío de un código de seguridad de 6 dígitos al teléfono autorizado que termina en ••%s.\n\n'
                  'Cuando lo recibas, escríbelo aquí. El código caducará en %d minutos. Escribe REENVIAR si no te llega o CANCELAR para salir.%s' % (tail(target['number']), CODE_MINUTES, other))


def _verify(c, conv, sender, state, digits, now, env):
    ch = c.execute('SELECT * FROM wa_identity_challenges WHERE id=? AND conversation_hash=?', (state['challenge_id'], conv)).fetchone()
    if not ch or ch['status'] != 'pendiente' or ch['expires_at'] < _iso(now):
        if ch and ch['status'] == 'pendiente':
            c.execute("UPDATE wa_identity_challenges SET status='caducado' WHERE id=?", (ch['id'],))
        event(c, 'codigo_caducado', state['order_id'], conv, '', now)
        return _reply('El código ya no es válido (caducó o fue reemplazado). Escribe REENVIAR para solicitar uno nuevo o CANCELAR para salir.', '[código de verificación]')
    # El destinatario debe seguir autorizado: si administración cambió los contactos, el código pendiente queda anulado.
    if all(_mac(env, 'destinatario', item['number']) != ch['recipient_hash'] for item in recipients(c, ch['order_id'])):
        c.execute("UPDATE wa_identity_challenges SET status='anulado' WHERE id=?", (ch['id'],))
        event(c, 'codigo_caducado', ch['order_id'], conv, 'El destinatario dejó de estar autorizado.', now)
        _clear_state(c, conv)
        return _reply(THIRD_PARTY, '[código de verificación]')
    attempts = ch['attempts'] + 1
    c.execute('UPDATE wa_identity_challenges SET attempts=? WHERE id=?', (attempts, ch['id']))
    if not hmac.compare_digest(ch['code_hash'], _mac(env, 'codigo', ch['nonce'], digits)):
        if attempts >= MAX_ATTEMPTS:
            c.execute("UPDATE wa_identity_challenges SET status='bloqueado' WHERE id=?", (ch['id'],))
            event(c, 'codigo_bloqueado', ch['order_id'], conv, '%d intentos fallidos.' % attempts, now)
            _clear_state(c, conv)
            return _reply('Superaste el número de intentos permitidos. Por seguridad, el código quedó anulado y no se mostró ninguna información. '
                          'Puedes solicitar un código nuevo más tarde o escribir ASESOR.', '[código de verificación]')
        event(c, 'codigo_incorrecto', ch['order_id'], conv, 'Intento %d de %d.' % (attempts, MAX_ATTEMPTS), now)
        left = MAX_ATTEMPTS - attempts
        return _reply('El código no es correcto. Te queda%s %d intento%s.' % ('' if left == 1 else 'n', left, '' if left == 1 else 's'), '[código de verificación]')
    c.execute("UPDATE wa_identity_challenges SET status='verificado',consumed_at=? WHERE id=?", (_iso(now), ch['id']))
    for old in c.execute("SELECT id FROM wa_identity_sessions WHERE conversation_hash=? AND ended_at=''", (conv,)).fetchall():
        _end_session(c, old['id'], 'nueva_verificacion', now)
    c.execute('INSERT INTO wa_identity_sessions(conversation_hash,order_id,challenge_id,recipient_kind,recipient_tail,contacts_fingerprint,created_at,last_activity) VALUES (?,?,?,?,?,?,?,?)',
              (conv, ch['order_id'], ch['id'], ch['recipient_kind'], ch['recipient_tail'], fingerprint(c, ch['order_id'], env), _iso(now), _iso(now)))
    event(c, 'verificado', ch['order_id'], conv, ('Titular' if ch['recipient_kind'] == 'titular' else 'Contacto autorizado') + ' ••' + ch['recipient_tail'], now)
    _clear_state(c, conv)
    code_row = c.execute('SELECT code FROM orders WHERE id=?', (ch['order_id'],)).fetchone()
    body = facts(c, ch['order_id']) or ''
    return _reply('✅ Identidad verificada correctamente.\n\nAhora puedo ayudarte con la información autorizada de tu orden.\n\n' + body +
                  '\n\nSi necesitas atención personalizada, escribe ASESOR. La verificación vence tras %d minutos sin actividad.' % IDLE_MINUTES,
                  '[código de verificación]', '[ADI entregó la información autorizada de la orden %s tras verificar la identidad]' % (code_row['code'] if code_row else ''))


def respond(c, conv, sender, text, now, env=None):
    """Turno de verificación. Devuelve {'answer','log_client','log_answer'} si el mensaje pertenece a este flujo, o None para que
    responda ADI normalmente. `conv` es el identificador HMAC de la conversación y `sender` el número que escribe (solo cifras)."""
    raw = re.sub(r'\s+', ' ', str(text or '')).strip()
    q = fold(raw)
    code = find_order_code(raw)
    state = _state(c, conv)
    if state and state['updated_at'] < _ago(now, minutes=30):  # una verificación a medias no queda abierta indefinidamente
        _clear_state(c, conv)
        state = None
    if RECOVERY.search(q):
        _clear_state(c, conv)
        event(c, 'recuperacion_solicitada', None, conv, 'El cliente indica que cambió de número o no tiene acceso al registrado.', now)
        return _reply('Entendido. Por seguridad, no puedo cambiar el teléfono registrado de una orden por este chat. '
                      'La actualización requiere comprobar tu identidad con nuestro personal (por ejemplo, en el local con tu documento y el comprobante de servicio). '
                      'Dejé registrada tu solicitud; escribe ASESOR si deseas que te contacte una persona.')
    session = active_session(c, conv, now, env)
    if state and state['step'] == 'esperando_codigo':
        six = SIX.match(raw)
        if six:
            return _verify(c, conv, sender, state, six.group(1) + six.group(2), now, env)
        if RESEND.match(q):
            return _send(c, conv, sender, state['order_id'], now, env)
        if CANCEL.match(q) or NO.match(q):
            c.execute("UPDATE wa_identity_challenges SET status='anulado' WHERE id=? AND status='pendiente'", (state['challenge_id'],))
            _clear_state(c, conv)
            return _reply('Listo, cancelé la verificación. No se mostró información de la orden.')
        if code:
            _clear_state(c, conv)
            return _lookup(c, conv, sender, code, now, env)
        return _reply('Escribe el código de 6 dígitos que recibiste en el teléfono autorizado, REENVIAR para solicitar otro o CANCELAR para salir.')
    if state and state['step'] == 'esperando_confirmacion':
        if YES.match(q):
            return _send(c, conv, sender, state['order_id'], now, env)
        if NO.match(q) or CANCEL.match(q):
            _clear_state(c, conv)
            return _reply('De acuerdo, no enviaré el código. Sin verificación no puedo compartir información de la orden. Escribe ASESOR si necesitas ayuda de nuestro personal.')
        if code:
            return _lookup(c, conv, sender, code, now, env)
        return _reply('¿Deseas recibir el código de verificación en el teléfono autorizado? Responde SÍ o NO.')
    if state and state['step'] == 'esperando_orden':
        if code:
            return _lookup(c, conv, sender, code, now, env)
        if CANCEL.match(q) or NO.match(q):
            _clear_state(c, conv)
            return _reply('De acuerdo. Si necesitas algo más, aquí estoy.')
        if ORDER_INTENT.search(q):
            return _reply('Por favor, indícame tu número de orden de servicio tal como aparece en tu comprobante (por ejemplo, PCD-…). Escribe CANCELAR para salir.')
        _clear_state(c, conv)
        return None
    if session:
        if code and c.execute('SELECT 1 FROM orders WHERE id=? AND upper(code)=?', (session['order_id'], __import__('reception').current_order_code(c, code).upper())).fetchone() is None:
            # Otra orden durante una sesión válida: no se revela nada; se verifica por separado.
            return _lookup(c, conv, sender, code, now, env)
        if CANCEL.match(q):
            _end_session(c, session['id'], 'cerrada_por_cliente', now)
            event(c, 'sesion_cerrada', session['order_id'], conv, 'Cerrada por el cliente.', now)
            return _reply('Cerré la sesión verificada. Para volver a consultar tu orden tendrás que verificar tu identidad de nuevo.')
        if code or ORDER_INTENT.search(q):
            c.execute('UPDATE wa_identity_sessions SET last_activity=? WHERE id=?', (_iso(now), session['id']))
            order_code = c.execute('SELECT code FROM orders WHERE id=?', (session['order_id'],)).fetchone()
            return _reply((facts(c, session['order_id']) or 'No encontré la orden verificada.') + '\n\nSi necesitas atención personalizada, escribe ASESOR.',
                          log_answer='[ADI entregó la información autorizada de la orden %s a la sesión verificada]' % (order_code['code'] if order_code else ''))
        return None
    if code:
        return _lookup(c, conv, sender, code, now, env)
    if ORDER_INTENT.search(q):
        _set_state(c, conv, 'esperando_orden', now)
        return _reply('¡Hola! Bienvenido a PC-DOCTOR S.A. 👋\n\nCon gusto te ayudaré a consultar el estado de tu equipo.\n\n'
                      '🔐 Por seguridad, primero necesito verificar que eres el titular de la orden o una persona autorizada.\n\n'
                      'Por favor, indícame tu número de orden de servicio.')
    return None


# ---- administración ----------------------------------------------------------------------------------------------------------------
def _admin(user):
    if not user or wa._role(user) != 'administrador':
        raise IdentityError('Solo administración gestiona la verificación de identidad.', 403)


def _expired(row, now):
    if row['ended_at']:
        return row['end_reason'] or 'cerrada'
    if row['last_activity'] < _ago(now, minutes=IDLE_MINUTES):
        return 'inactividad'
    if row['created_at'] < _ago(now, minutes=MAX_SESSION_MINUTES):
        return 'tiempo_maximo'
    return ''


END_LABELS = {'inactividad': 'Vencida por inactividad', 'tiempo_maximo': 'Vencida (tiempo máximo)', 'contactos_modificados': 'Anulada: cambiaron los contactos',
              'revocada': 'Revocada por administración', 'cerrada_por_cliente': 'Cerrada por el cliente', 'nueva_verificacion': 'Reemplazada por otra verificación', 'cerrada': 'Cerrada'}


def overview(c, order_id, user, now, env=None):
    _admin(user)
    row = _order(c, order_id)
    if not row:
        raise IdentityError('Orden no encontrada.', 404)
    titular = wa.number_for(row['phone'] or '')
    names = {r['id']: r['name'] for r in c.execute('SELECT id,name FROM users')}
    contacts = [{'id': r['id'], 'name': r['name'], 'tail': tail(r['phone']), 'relation': r['relation'], 'evidence': r['evidence'], 'created_at': r['created_at'],
                 'created_by': names.get(r['created_by'], ''), 'revoked_at': r['revoked_at'], 'revoked_by': names.get(r['revoked_by'], ''), 'revoke_reason': r['revoke_reason']}
                for r in c.execute('SELECT * FROM order_authorized_contacts WHERE order_id=? ORDER BY revoked_at!=\'\', id DESC', (order_id,))]
    sessions = []
    for r in c.execute('SELECT * FROM wa_identity_sessions WHERE order_id=? ORDER BY id DESC LIMIT 20', (order_id,)):
        why = _expired(r, now)
        sessions.append({'id': r['id'], 'active': not why, 'state': 'Activa' if not why else END_LABELS.get(why, why), 'who': ('Titular' if r['recipient_kind'] == 'titular' else 'Contacto autorizado') + ' ••' + r['recipient_tail'],
                         'created_at': r['created_at'], 'last_activity': r['last_activity'], 'ended_at': r['ended_at'], 'revoked_by': names.get(r['revoked_by'], '')})
    events = [dict(r, label=EVENT_LABELS.get(r['kind'], r['kind'])) for r in c.execute('SELECT id,kind,detail,created_at FROM wa_identity_events WHERE order_id=? ORDER BY id DESC LIMIT 60', (order_id,))]
    day = _ago(now, days=1)
    last = c.execute("SELECT MAX(created_at) FROM wa_identity_sessions WHERE order_id=?", (order_id,)).fetchone()[0]
    alerts = [e for e in events if e['kind'] in ALERT_KINDS and e['created_at'] >= day]
    if _count(c, "SELECT COUNT(*) FROM wa_identity_events WHERE order_id=? AND kind='codigo_incorrecto' AND created_at>=?", (order_id, day)) >= 3:
        alerts.insert(0, {'kind': 'intentos', 'label': 'Varios códigos incorrectos en las últimas 24 horas', 'detail': 'Posible intento de adivinar el código.', 'created_at': ''})
    return {'order': row['code'], 'enabled': bool(wa.ready(env)), 'otp_template': bool(wa.settings(c).get('otp_template')),
            'titular': {'tail': tail(titular), 'valid': bool(titular)}, 'contacts': contacts, 'last_verification': last or '',
            'state': 'verificada' if any(s['active'] for s in sessions) else ('verificada_antes' if last else 'sin_verificar'),
            'sessions': sessions, 'failed': [e for e in events if e['kind'] in FAILED_KINDS][:20], 'alerts': alerts[:10],
            'audit': [e for e in events if e['kind'] in AUDIT_KINDS][:20],
            'rules': {'code_minutes': CODE_MINUTES, 'attempts': MAX_ATTEMPTS, 'idle_minutes': IDLE_MINUTES, 'max_session_minutes': MAX_SESSION_MINUTES}}


def invalidate(c, order_id, reason, now, user_id=None, kind='contactos_modificados'):
    """Anula las sesiones abiertas y los códigos pendientes de la orden (cambio de contactos o revocación)."""
    ended = 0
    for r in c.execute("SELECT id FROM wa_identity_sessions WHERE order_id=? AND ended_at=''", (order_id,)).fetchall():
        _end_session(c, r['id'], 'revocada' if kind == 'sesiones_revocadas' else 'contactos_modificados', now, user_id)
        ended += 1
    c.execute("UPDATE wa_identity_challenges SET status='anulado' WHERE order_id=? AND status='pendiente'", (order_id,))
    c.execute('DELETE FROM wa_identity_state WHERE order_id=?', (order_id,))
    event(c, kind, order_id, '', reason[:200], now)
    return ended


def add_contact(c, order_id, data, user, now, env=None):
    _admin(user)
    row = _order(c, order_id)
    if not row:
        raise IdentityError('Orden no encontrada.', 404)
    name = re.sub(r'\s+', ' ', str(data.get('name', '') or '')).strip()
    relation = re.sub(r'\s+', ' ', str(data.get('relation', '') or '')).strip()[:60]
    evidence = re.sub(r'\s+', ' ', str(data.get('evidence', '') or '')).strip()
    number = wa.number_for(str(data.get('phone', '') or '').strip())
    errors = {}
    if not 3 <= len(name) <= 120:
        errors['name'] = 'Escribe el nombre completo de la persona autorizada.'
    if not number:
        errors['phone'] = 'Escribe un celular válido para WhatsApp (con código de país si no es de Ecuador).'
    elif number in [item['number'] for item in recipients(c, order_id)]:
        errors['phone'] = 'Ese número ya está autorizado en esta orden.'
    if not 5 <= len(evidence) <= 300:
        errors['evidence'] = 'Indica cómo se comprobó la identidad y la autorización del titular (procedimiento aprobado).'
    if data.get('confirm') is not True:
        errors['confirm'] = 'Confirma que la autorización se comprobó siguiendo el procedimiento aprobado.'
    if errors:
        raise IdentityError('Revisa los datos marcados.', 400, errors)
    cid = c.execute('INSERT INTO order_authorized_contacts(order_id,name,phone,relation,evidence,created_by,created_at) VALUES (?,?,?,?,?,?,?)',
                    (order_id, name[:120], number, relation, evidence[:300], user['id'], _iso(now))).lastrowid
    invalidate(c, order_id, 'Se agregó un contacto autorizado ••' + tail(number) + '.', now, user['id'])
    event(c, 'contacto_agregado', order_id, '', name[:60] + ' ••' + tail(number) + (' (' + relation + ')' if relation else ''), now)
    return cid


def revoke_contact(c, order_id, contact_id, data, user, now):
    _admin(user)
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()
    if not 3 <= len(reason) <= 200:
        raise IdentityError('Indica el motivo de la revocación.', 400, {'reason': 'Indica el motivo de la revocación.'})
    row = c.execute("SELECT * FROM order_authorized_contacts WHERE id=? AND order_id=? AND revoked_at=''", (contact_id, order_id)).fetchone()
    if not row:
        raise IdentityError('El contacto no existe o ya fue revocado.', 404)
    c.execute('UPDATE order_authorized_contacts SET revoked_at=?,revoked_by=?,revoke_reason=? WHERE id=?', (_iso(now), user['id'], reason, contact_id))
    invalidate(c, order_id, 'Se revocó un contacto autorizado ••' + tail(row['phone']) + '.', now, user['id'])
    event(c, 'contacto_revocado', order_id, '', row['name'][:60] + ' ••' + tail(row['phone']) + ' · ' + reason[:100], now)


def revoke_sessions(c, order_id, user, now):
    _admin(user)
    if not _order(c, order_id):
        raise IdentityError('Orden no encontrada.', 404)
    return invalidate(c, order_id, 'Administración revocó el acceso verificado por WhatsApp.', now, user['id'], kind='sesiones_revocadas')
