"""Autorización electrónica del cliente por enlace seguro.

El cliente abre un enlace aleatorio enviado a su correo, confirma los últimos cuatro dígitos de su identificación y un
código temporal de seis dígitos, y acepta o rechaza expresamente cada autorización. Se guarda la evidencia con su huella.
No es una firma electrónica certificada ni comprueba la identidad con el mismo alcance; así se indica al cliente y en el
comprobante. Nada se acepta por omisión y el enlace nunca muestra datos personales completos."""
import hashlib
import html
import json
import re
import secrets
from datetime import datetime, timedelta

from corporate import settings
from order_tracking import HEAD
from reception import ECUADOR_TZ, public_base_url

EXPIRES_DAYS, CODE_MINUTES, PASS_MINUTES = 7, 10, 30
MAX_ID_ATTEMPTS, MAX_CODE_ATTEMPTS, MAX_CODE_SENDS = 5, 5, 5
METHOD = 'Enlace seguro enviado al correo registrado, últimos cuatro dígitos de la identificación y código temporal de seis dígitos'
ITEMS = (
    ('service', 'Diagnóstico y servicio técnico solicitado', 'Revisión del equipo y ejecución del servicio descrito en la orden.'),
    ('operating_system', 'Acceso al sistema operativo', 'Ingreso al sistema y pruebas de funcionamiento con la sesión iniciada.'),
    ('files', 'Acceso a archivos personales y respaldos', 'Revisión de archivos específicos o realización de respaldos cuando el servicio lo requiera.'),
    ('data_operations', 'Formateo, reinstalación o eliminación de datos', 'Operaciones que pueden causar pérdida irreversible de información.'),
)
STATUS = {'pending': 'Pendiente de respuesta del cliente', 'signed': 'Firmada por el cliente', 'rejected': 'Servicio no autorizado por el cliente',
          'expired': 'Enlace caducado', 'revoked': 'Enlace reemplazado', 'locked': 'Bloqueada por intentos fallidos'}


class AuthorizationError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def digits(value):
    return re.sub(r'\D', '', str(value or ''))


def masked(identification):
    """Identificación parcialmente oculta: nunca revela los últimos dígitos que se piden como comprobación."""
    number = digits(identification)
    return number[:2] + '*' * max(0, len(number) - 2) if len(number) >= 6 else ''


def ordered(decisions):
    """Decisiones en el orden en que se presentaron al cliente."""
    return [(key, decisions[key]) for key, _, _ in ITEMS if key in decisions]


def link(token):
    return public_base_url().rstrip('/') + '/autorizar/' + token


def create(c, order, user, now):
    """Crea un enlace nuevo para la orden y deja sin efecto los pendientes anteriores. Devuelve el token (solo existe aquí)."""
    email = (order.get('email') or '').strip()
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+', email):
        raise AuthorizationError('El cliente no tiene un correo electrónico válido registrado.')
    if not masked(order.get('identification')):
        raise AuthorizationError('El cliente no tiene una identificación registrada con la que comprobar su identidad.')
    c.execute("UPDATE client_authorizations SET status='revoked' WHERE order_id=? AND status='pending'", (order['id'],))
    token = secrets.token_urlsafe(32)
    c.execute('INSERT INTO client_authorizations(order_id,token_hash,recipient,created_by,created_at,expires_at) VALUES (?,?,?,?,?,?)',
              (order['id'], digest(token), email, user['id'] if user else None, now.isoformat(timespec='seconds'), (now + timedelta(days=EXPIRES_DAYS)).isoformat(timespec='seconds')))
    return token


def lookup(c, token, now):
    row = c.execute('SELECT * FROM client_authorizations WHERE token_hash=?', (digest(token),)).fetchone()
    if not row:
        return None
    row = dict(row)
    if row['status'] == 'pending' and datetime.fromisoformat(row['expires_at']) < now:
        c.execute("UPDATE client_authorizations SET status='expired' WHERE id=?", (row['id'],))
        row['status'] = 'expired'
    return row


def summary(c, order_id):
    """Resumen para el personal: último enlace de la orden con su resultado. Nunca incluye el token ni el código."""
    row = c.execute('SELECT id,status,recipient,created_at,expires_at,verified_at,signed_at,evidence,evidence_hash,mail_result,notice_result FROM client_authorizations WHERE order_id=? ORDER BY id DESC LIMIT 1', (order_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data['status_label'] = STATUS.get(data['status'], data['status'])
    data['evidence'] = json.loads(data['evidence']) if data['evidence'] else None
    data['total'] = c.execute('SELECT COUNT(*) FROM client_authorizations WHERE order_id=?', (order_id,)).fetchone()[0]
    return data


# --- Páginas públicas -------------------------------------------------------------------------------------------------

def _page(title, body):
    company = settings()
    return HEAD % (title, html.escape(company['specialty'])) + body + '<footer><p>WhatsApp: %s</p><p class="tracking-note">Esta página no es una firma electrónica certificada. Sus decisiones quedan registradas con fecha, hora y el método de verificación utilizado.</p></footer></main></body></html>' % html.escape(company['whatsapp'])


def missing_page():
    return _page('Enlace no disponible', '<section class="tracking-card"><h1>Enlace no disponible</h1><p>Este enlace de autorización no existe, caducó o fue reemplazado. Comuníquese con el taller para recibir uno nuevo.</p></section>')


def _order_block(order):
    e = html.escape
    device = ' '.join(part for part in (order.get('brand') or '', order.get('model') or '') if part) or 'Equipo registrado'
    return '<small>AUTORIZACIÓN DE SERVICIO</small><h1>Orden %s</h1><dl><div><dt>Equipo</dt><dd>%s</dd></div><div><dt>Servicio solicitado</dt><dd>%s</dd></div></dl>' % (e(order['code']), e(device), e(order.get('current_problem') or order.get('problem') or 'Servicio técnico'))


def _alert(text):
    return '<p class="auth-alert" role="alert">%s</p>' % html.escape(text) if text else ''


def identify_page(token, order, error=''):
    e = html.escape
    return _page('Autorización de servicio', '<section class="tracking-card auth-card">' + _order_block(order) + _alert(error)
                 + '<form method="post" action="/autorizar/%s" class="auth-form"><input type="hidden" name="step" value="identify"><p class="auth-step">Paso 1 de 3 · Compruebe su identidad</p><p>Identificación registrada: <strong class="auth-mask">%s</strong></p><label for="last4">Escriba los últimos cuatro dígitos de su identificación</label><input id="last4" name="last4" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" minlength="4" autocomplete="off" required><button type="submit">Enviar código a mi correo</button><p class="auth-hint">Le enviaremos un código de seis dígitos al correo registrado en la orden. Caduca en %d minutos.</p></form></section>' % (e(token), e(masked(order.get('identification'))), CODE_MINUTES))


def code_page(token, order, recipient, error=''):
    e = html.escape
    name, _, domain = recipient.partition('@')
    hidden = name[:2] + '***@' + domain
    return _page('Código de verificación', '<section class="tracking-card auth-card">' + _order_block(order) + _alert(error)
                 + '<form method="post" action="/autorizar/%s" class="auth-form"><input type="hidden" name="step" value="verify"><p class="auth-step">Paso 2 de 3 · Código de verificación</p><p>Enviamos un código de seis dígitos a <strong>%s</strong>.</p><label for="code">Código de verificación</label><input id="code" name="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" minlength="6" autocomplete="one-time-code" required><button type="submit">Verificar código</button></form><form method="post" action="/autorizar/%s" class="auth-form auth-again"><input type="hidden" name="step" value="restart"><button type="submit" class="auth-secondary">No recibí el código: volver a empezar</button></form></section>' % (e(token), e(hidden), e(token)))


def decision_page(token, order, terms, passkey, errors=None, chosen=None):
    e = html.escape
    errors, chosen = errors or {}, chosen or {}
    parts = ['<section class="tracking-card auth-card">', _order_block(order), _alert(errors.get('form', '')),
             '<form method="post" action="/autorizar/%s" class="auth-form"><input type="hidden" name="step" value="sign"><input type="hidden" name="pass" value="%s"><p class="auth-step">Paso 3 de 3 · Revise y decida</p>' % (e(token), e(passkey))]
    if terms:
        clauses = ''.join('<p>%s</p>' % e(paragraph).replace('\n', '<br>') for paragraph in re.split(r'\n\s*\n', terms['full_text'].strip()))
        parts.append('<fieldset class="auth-terms"><legend>%s · versión %s</legend><div class="auth-terms-text" tabindex="0">%s</div><label class="auth-check"><input type="checkbox" name="terms_accept" value="1"%s required><span>He leído y acepto las condiciones, versión %s.</span></label>%s</fieldset>'
                     % (e(terms['title']), e(terms['version']), clauses, ' checked' if chosen.get('terms_accept') else '', e(terms['version']), _alert(errors.get('terms_accept', ''))))
    else:
        parts.append('<p class="auth-hint">Todavía no hay condiciones de servicio publicadas: esta autorización no incluye la aceptación de condiciones.</p>')
    for key, title, text in ITEMS:
        value = chosen.get(key, '')
        parts.append('<fieldset class="auth-item"><legend>%s</legend><p>%s</p><div class="auth-options"><label><input type="radio" name="%s" value="authorized"%s required><span>Autorizo</span></label><label><input type="radio" name="%s" value="denied"%s><span>No autorizo</span></label></div>%s</fieldset>'
                     % (e(title), e(text), key, ' checked' if value == 'authorized' else '', key, ' checked' if value == 'denied' else '', _alert(errors.get(key, ''))))
    parts.append('<label for="comment">Observaciones o motivo (opcional)</label><textarea id="comment" name="comment" maxlength="500" rows="3">%s</textarea><label class="auth-check"><input type="checkbox" name="confirm" value="1" required><span>Confirmo que soy el titular de la orden o actúo en su nombre y que estas decisiones son mías.</span></label>%s<button type="submit">Confirmar y firmar autorización</button></form></section>'
                 % (e(chosen.get('comment', '')), _alert(errors.get('confirm', ''))))
    return _page('Autorización de servicio', ''.join(parts))


def result_page(token, row, order):
    e = html.escape
    evidence = json.loads(row['evidence']) if row.get('evidence') else {}
    if row['status'] in ('signed', 'rejected'):
        labels = dict((key, title) for key, title, _ in ITEMS)
        lines = ''.join('<div><dt>%s</dt><dd class="auth-%s">%s</dd></div>' % (e(labels.get(key, key)), e(value), 'AUTORIZADO' if value == 'authorized' else 'NO AUTORIZADO') for key, value in ordered(evidence.get('decisions', {})))
        when = datetime.fromisoformat(row['signed_at']).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')
        # Esta autorización no aprueba presupuestos: si hay uno pendiente, se indica que se decide desde su propio enlace.
        pending = order.get('pending_quotes') or []
        notice = ('<p class="auth-hint"><strong>Presupuesto pendiente: %s.</strong> Esta autorización no aprueba importes. Para aprobar o rechazar los servicios y productos cotizados, abra el enlace del correo «Presupuesto» que recibió o pida al taller que se lo reenvíe.</p>'
                  % e(', '.join(pending))) if pending else ''
        return _page('Autorización registrada', '<section class="tracking-card auth-card"><small>AUTORIZACIÓN REGISTRADA</small><h1>Orden %s</h1><p>Sus decisiones quedaron registradas el %s (Ecuador).</p><dl>%s</dl>%s<p class="auth-hint">Huella de la evidencia: %s</p><p><a class="auth-link" href="/autorizar/%s/comprobante.pdf">Descargar comprobante en PDF</a></p></section>'
                     % (e(order['code']), e(when), lines, notice, e(row['evidence_hash'][:32]) + '…', e(token)))
    text = {'expired': 'Este enlace caducó. Solicite uno nuevo al taller.', 'revoked': 'Este enlace fue reemplazado por otro más reciente. Use el último correo recibido.',
            'locked': 'Por seguridad, este enlace se bloqueó tras varios intentos fallidos. Solicite uno nuevo al taller.'}.get(row['status'], 'Enlace no disponible.')
    return _page('Enlace no disponible', '<section class="tracking-card"><h1>Enlace no disponible</h1><p>%s</p></section>' % e(text))


# --- Pasos -------------------------------------------------------------------------------------------------------------

def start_page(c, token, row, order):
    if row['status'] != 'pending':
        return result_page(token, row, order)
    return identify_page(token, order)


def handle(c, token, row, order, form, now, origin, send_code, terms):
    """Procesa un paso del cliente. Devuelve (html, firmado). «send_code(destinatario, código)» debe lanzar una excepción si falla."""
    if row['status'] != 'pending':
        return result_page(token, row, order), False
    step = form.get('step', '')
    stamp = now.isoformat(timespec='seconds')
    if step == 'restart':
        return identify_page(token, order), False
    if step == 'identify':
        if row['id_attempts'] >= MAX_ID_ATTEMPTS:
            c.execute("UPDATE client_authorizations SET status='locked' WHERE id=?", (row['id'],))
            return result_page(token, dict(row, status='locked'), order), False
        if not secrets.compare_digest(digits(form.get('last4'))[:8], digits(order.get('identification'))[-4:]):
            c.execute('UPDATE client_authorizations SET id_attempts=id_attempts+1 WHERE id=?', (row['id'],))
            left = MAX_ID_ATTEMPTS - row['id_attempts'] - 1
            if left <= 0:
                c.execute("UPDATE client_authorizations SET status='locked' WHERE id=?", (row['id'],))
                return result_page(token, dict(row, status='locked'), order), False
            return identify_page(token, order, 'Los dígitos no coinciden con la identificación registrada. Intentos restantes: %d.' % left), False
        if row['code_sent'] >= MAX_CODE_SENDS:
            return identify_page(token, order, 'Se alcanzó el máximo de códigos para este enlace. Solicite uno nuevo al taller.'), False
        code = '%06d' % secrets.randbelow(1000000)
        c.execute('UPDATE client_authorizations SET code_hash=?,code_expires=?,code_attempts=0,code_sent=code_sent+1 WHERE id=?',
                  (digest(code + row['token_hash']), (now + timedelta(minutes=CODE_MINUTES)).isoformat(timespec='seconds'), row['id']))
        try:
            send_code(row['recipient'], code)
        except Exception:
            return identify_page(token, order, 'No pudimos enviar el código a su correo en este momento. Inténtelo de nuevo en unos minutos.'), False
        return code_page(token, order, row['recipient']), False
    if step == 'verify':
        if not row['code_hash'] or not row['code_expires'] or datetime.fromisoformat(row['code_expires']) < now:
            return identify_page(token, order, 'El código caducó. Solicite uno nuevo.'), False
        if row['code_attempts'] >= MAX_CODE_ATTEMPTS:
            c.execute("UPDATE client_authorizations SET code_hash='' WHERE id=?", (row['id'],))
            return identify_page(token, order, 'Demasiados intentos con ese código. Solicite uno nuevo.'), False
        if not secrets.compare_digest(digest(digits(form.get('code'))[:6] + row['token_hash']), row['code_hash']):
            c.execute('UPDATE client_authorizations SET code_attempts=code_attempts+1 WHERE id=?', (row['id'],))
            return code_page(token, order, row['recipient'], 'El código no es correcto.'), False
        passkey = secrets.token_urlsafe(24)
        c.execute("UPDATE client_authorizations SET code_hash='',pass_hash=?,verified_at=? WHERE id=?", (digest(passkey), stamp, row['id']))
        return decision_page(token, order, terms, passkey), False
    if step == 'sign':
        passkey = form.get('pass', '')
        if not row['pass_hash'] or not row['verified_at'] or not secrets.compare_digest(digest(passkey), row['pass_hash']) or datetime.fromisoformat(row['verified_at']) + timedelta(minutes=PASS_MINUTES) < now:
            return identify_page(token, order, 'La verificación caducó. Compruebe su identidad de nuevo.'), False
        errors, decisions = {}, {}
        for key, title, _ in ITEMS:
            if form.get(key) not in ('authorized', 'denied'):
                errors[key] = 'Elija expresamente «Autorizo» o «No autorizo».'
            else:
                decisions[key] = form[key]
        if terms and form.get('terms_accept') != '1':
            errors['terms_accept'] = 'Para continuar debe aceptar las condiciones.'
        if form.get('confirm') != '1':
            errors['confirm'] = 'Marque la confirmación para firmar.'
        comment = ' '.join(str(form.get('comment', '')).split())[:500]
        if errors:
            errors['form'] = 'Faltan decisiones por completar.'
            return decision_page(token, order, terms, passkey, errors, dict(form, comment=comment)), False
        evidence = {'authorization_id': row['id'], 'order_id': order['id'], 'order_code': order['code'], 'client': order.get('client', ''), 'identification_masked': masked(order.get('identification')),
                    'recipient': row['recipient'], 'method': METHOD, 'verified_at': row['verified_at'], 'signed_at': stamp, 'decisions': decisions, 'comment': comment,
                    'terms': {'id': terms['id'], 'version': terms['version'], 'title': terms['title'], 'content_hash': terms['content_hash']} if terms else None,
                    'origin': origin}
        packed = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        status = 'signed' if decisions['service'] == 'authorized' else 'rejected'
        done = c.execute("UPDATE client_authorizations SET status=?,evidence=?,evidence_hash=?,signed_at=?,pass_hash='' WHERE id=? AND status='pending'", (status, packed, digest(packed), stamp, row['id']))
        if done.rowcount != 1:
            # Doble envío: ya quedó registrada; se muestra el resultado guardado sin repetir avisos.
            saved = c.execute('SELECT * FROM client_authorizations WHERE id=?', (row['id'],)).fetchone()
            return result_page(token, dict(saved), order), False
        signed = dict(row, status=status, evidence=packed, evidence_hash=digest(packed), signed_at=stamp)
        return result_page(token, signed, order), True
    return identify_page(token, order), False


def verify_evidence(row):
    """True si la evidencia guardada coincide con su huella (detecta modificaciones posteriores)."""
    return bool(row.get('evidence')) and digest(row['evidence']) == row.get('evidence_hash')


def render_pdf(row):
    """Comprobante A4 de la autorización firmada, con la huella de la evidencia."""
    from document_canvas import Canvas, BLUE, GRAY, INK
    evidence = json.loads(row['evidence']); company = settings(); pdf = Canvas(595.28, 841.89, 'Autorización electrónica · ' + evidence['order_code']); left, width = 42, 511
    def fill(x, top, w, h, color):
        pdf.stream.set_color_rgb(*color); pdf.stream.rectangle(x, pdf.h - top - h, w, h); pdf.stream.fill()
    pdf.page(); fill(0, 0, pdf.w, 5, BLUE); pdf.logo(left, 26, 60); pdf.text(company['name'], left + 72, 28, 18, True, BLUE); pdf.text(company['specialty'].upper(), left + 72, 52, 8, True, GRAY); pdf.line(left, 86, width)
    pdf.text('COMPROBANTE DE AUTORIZACIÓN ELECTRÓNICA', left, 100, 14, True, BLUE); pdf.text('Orden ' + evidence['order_code'], left, 122, 11, True, INK)
    y = 146
    moment = lambda value: datetime.fromisoformat(value).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M:%S') + ' (Ecuador)'
    for label, value in (('Cliente', evidence.get('client') or '—'), ('Identificación', evidence['identification_masked']), ('Correo verificado', evidence['recipient']), ('Identidad verificada', moment(evidence['verified_at'])), ('Firma registrada', moment(evidence['signed_at']))):
        pdf.text(label, left, y, 8, True, GRAY); pdf.text(value, left + 130, y, 9.5, False, INK); y += 15
    y += 8; fill(left, y, width, 19, (.93, .95, .98)); fill(left, y, 3, 19, BLUE); pdf.text('DECISIONES DEL CLIENTE', left + 11, y + 5, 9.6, True, BLUE); y += 28
    titles = dict((key, title) for key, title, _ in ITEMS)
    for key, value in ordered(evidence['decisions']):
        allowed = value == 'authorized'
        if allowed: fill(left, y - 2, 104, 15, (.05, .40, .25)); pdf.text('AUTORIZADO', left + 18, y + 1.5, 7.6, True, (1, 1, 1))
        else:
            fill(left, y - 2, 104, 15, (.70, .12, .16)); fill(left + 1.2, y - .8, 101.6, 12.6, (1, 1, 1)); pdf.text('NO AUTORIZADO', left + 14, y + 1.5, 7.6, True, (.70, .12, .16))
        pdf.text(titles.get(key, key), left + 116, y, 9.6, True, INK); y += 21
    if evidence.get('comment'):
        y += 4; pdf.text('Observaciones del cliente', left, y, 8, True, GRAY); y += 13
        for line in pdf.wrap(evidence['comment'], width, 9.2): pdf.text(line, left, y, 9.2, False, INK); y += 12.4
    y += 10; fill(left, y, width, 19, (.93, .95, .98)); fill(left, y, 3, 19, BLUE); pdf.text('CONDICIONES Y VERIFICACIÓN', left + 11, y + 5, 9.6, True, BLUE); y += 28
    terms = evidence.get('terms')
    notes = [('Condiciones aceptadas: ' + terms['title'] + ', versión ' + terms['version'] + '. Huella SHA-256: ' + terms['content_hash']) if terms else 'Sin condiciones publicadas en la fecha de la firma: esta autorización no incluye aceptación de condiciones.',
             'Método de verificación: ' + evidence['method'] + '.',
             'Este comprobante no es una firma electrónica certificada. Acredita las decisiones registradas mediante el método indicado.',
             'Huella SHA-256 de la evidencia: ' + row['evidence_hash']]
    for note in notes:
        for line in pdf.wrap(note, width, 8.6): pdf.text(line, left, y, 8.6, False, INK); y += 11.6
        y += 4
    pdf.line(left, 794, width); pdf.text(company['website'] + '  |  WhatsApp: ' + company['whatsapp'] + '  |  ' + company['support_email'], left, 802, 7.5, False, GRAY)
    return pdf.finish()
