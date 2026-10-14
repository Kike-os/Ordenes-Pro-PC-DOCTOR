"""PC-DOCTOR Mail Pro — fase 1: configuración y pruebas reales de conexión IMAP/SMTP.

Las credenciales solo se leen del entorno del servidor; nunca se imprimen, registran ni
envían al navegador. La verificación de certificados TLS no se puede desactivar.
"""
import argparse
import imaplib
import os
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

KEYS = ('MAIL_IMAP_HOST', 'MAIL_IMAP_PORT', 'MAIL_SMTP_HOST', 'MAIL_SMTP_PORT', 'MAIL_USERNAME', 'MAIL_PASSWORD')
TIMEOUT = 15


class MailError(Exception):
    """Fallo clasificado: `kind` es dns, red, tls, credenciales, configuracion o servidor."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def settings(env=None):
    env = os.environ if env is None else env
    try:
        imap_port = int(env.get('MAIL_IMAP_PORT', '993') or 993)
        smtp_port = int(env.get('MAIL_SMTP_PORT', '465') or 465)
    except ValueError:
        raise MailError('configuracion', 'Los puertos de correo deben ser numéricos.')
    config = {'imap_host': env.get('MAIL_IMAP_HOST', '').strip(), 'imap_port': imap_port, 'smtp_host': env.get('MAIL_SMTP_HOST', '').strip(), 'smtp_port': smtp_port,
              'username': env.get('MAIL_USERNAME', '').strip(), 'password': env.get('MAIL_PASSWORD', '')}
    if imap_port != 993:
        raise MailError('configuracion', 'IMAP solo se admite por el puerto 993 con SSL/TLS.')
    if smtp_port not in (465, 587):
        raise MailError('configuracion', 'SMTP solo se admite por 465 (SSL/TLS) o 587 (STARTTLS).')
    return config


def configured(env=None):
    config = settings(env)
    return all(config[key] for key in ('imap_host', 'smtp_host', 'username', 'password'))


def status(env=None):
    """Estado sin secretos, apto para mostrar en la interfaz."""
    try:
        config = settings(env)
    except MailError as error:
        return {'configured': False, 'error': str(error)}
    return {'configured': configured(env), 'imap': config['imap_host'] + ':' + str(config['imap_port']) if config['imap_host'] else '', 'smtp': config['smtp_host'] + ':' + str(config['smtp_port']) if config['smtp_host'] else '',
            'account': config['username'], 'password_set': bool(config['password'])}


def context():
    # Contexto por defecto: verifica cadena de confianza y nombre del servidor; TLS 1.2 como mínimo.
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def classify(error, host, port):
    if isinstance(error, MailError):
        return error
    if isinstance(error, socket.gaierror):
        return MailError('dns', f'No se pudo resolver el nombre «{host}». Revisa el nombre del servidor.')
    if isinstance(error, ssl.SSLCertVerificationError):
        return MailError('tls', f'El certificado de {host}:{port} no es válido para ese nombre. Usa el nombre de servidor que figura en el certificado; la verificación no se desactiva.')
    if isinstance(error, ssl.SSLError):
        return MailError('tls', f'No se pudo negociar TLS con {host}:{port}.')
    if isinstance(error, (socket.timeout, TimeoutError)):
        return MailError('red', f'{host}:{port} no respondió. El puerto puede estar bloqueado o el nombre apunta a otro servidor.')
    if isinstance(error, ConnectionRefusedError):
        return MailError('red', f'{host}:{port} rechazó la conexión: no hay un servicio de correo en ese puerto.')
    if isinstance(error, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)):
        return MailError('credenciales', 'El servidor rechazó el usuario o la contraseña.')
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        codes = sorted({int(value[0]) for value in error.recipients.values() if isinstance(value, tuple)})
        print('mail-smtp destinatario rechazado codigos=' + ','.join(str(code) for code in codes), flush=True)
        names = ', '.join(list(error.recipients)[:5])
        if codes and all(400 <= code < 500 for code in codes):
            return MailError('temporal', 'El servidor no pudo aceptar por ahora a: ' + names + ' (error temporal ' + str(codes[0]) + '). Inténtalo de nuevo en unos minutos.')
        return MailError('destinatario', 'El servidor rechazó a: ' + names + (' (código ' + str(codes[0]) + ')' if codes else '') + '. Revisa que la dirección esté bien escrita.')
    if isinstance(error, (smtplib.SMTPSenderRefused, smtplib.SMTPDataError, smtplib.SMTPResponseException)):
        code = int(getattr(error, 'smtp_code', 0) or 0)
        print('mail-smtp respuesta codigo=' + str(code), flush=True)
        if 400 <= code < 500:
            return MailError('temporal', 'El servidor de correo no pudo aceptar el mensaje por ahora (error temporal ' + str(code) + '). Inténtalo de nuevo en unos minutos.')
        return MailError('rechazo', 'El servidor de correo rechazó el mensaje' + (' (código ' + str(code) + ')' if code else '') + '.')
    if isinstance(error, (smtplib.SMTPException, OSError)):
        return MailError('servidor', f'El servidor de correo {host}:{port} devolvió un error: {type(error).__name__}.')
    return MailError('servidor', f'Fallo inesperado con {host}:{port}: {type(error).__name__}.')


def require(config):
    missing = [name for name, key in (('MAIL_IMAP_HOST', 'imap_host'), ('MAIL_SMTP_HOST', 'smtp_host'), ('MAIL_USERNAME', 'username'), ('MAIL_PASSWORD', 'password')) if not config[key]]
    if missing:
        raise MailError('configuracion', 'Faltan variables de entorno: ' + ', '.join(missing) + '.')


def test_imap(env=None):
    """Conecta, valida el certificado, autentica, lista carpetas y lee los metadatos del mensaje más reciente. No modifica nada."""
    config = settings(env)
    require(config)
    host, port, steps = config['imap_host'], config['imap_port'], []
    client = None
    try:
        steps.append('DNS: ' + ', '.join(sorted({info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})))
        client = imaplib.IMAP4_SSL(host, port, ssl_context=context(), timeout=TIMEOUT)
        steps.append('TLS: ' + client.sock.version() + ' con certificado válido para ' + host)
        client.login(config['username'], config['password'])
        steps.append('Autenticación: aceptada')
        code, folders = client.list()
        names = [line.decode('utf-8', 'replace').rsplit(' ', 1)[-1].strip('"') for line in folders or [] if line]
        steps.append('Carpetas (' + str(len(names)) + '): ' + ', '.join(names[:12]))
        code, data = client.select('INBOX', readonly=True)
        total = int(data[0]) if code == 'OK' and data and data[0] else 0
        steps.append('Bandeja de entrada: ' + str(total) + ' mensajes')
        if total:
            code, parts = client.fetch(str(total), '(BODY.PEEK[HEADER.FIELDS (DATE SUBJECT)] RFC822.SIZE)')
            header = next((part[1] for part in parts if isinstance(part, tuple)), b'')
            date = next((line[5:].strip().decode('utf-8', 'replace') for line in header.splitlines() if line.lower().startswith(b'date:')), 'sin fecha')
            steps.append('Metadatos del mensaje más reciente: leídos (fecha ' + date + '); el contenido no se descargó')
        return steps
    except Exception as error:
        failure = classify(error, host, port)
        failure.steps = steps
        raise failure from None
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass


def smtp_client(config):
    host, port = config['smtp_host'], config['smtp_port']
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=context())
    client = smtplib.SMTP(host, port, timeout=TIMEOUT)
    client.ehlo()
    client.starttls(context=context())
    client.ehlo()
    return client


def test_smtp(env=None, send_to=''):
    """Conecta, valida el certificado y autentica. Solo envía un mensaje si se indica un destinatario confirmado."""
    config = settings(env)
    require(config)
    host, port, steps = config['smtp_host'], config['smtp_port'], []
    client = None
    try:
        client = smtp_client(config)
        steps.append('TLS: ' + client.sock.version() + ' con certificado válido para ' + host)
        client.login(config['username'], config['password'])
        steps.append('Autenticación: aceptada')
        if send_to:
            message = EmailMessage()
            message['From'] = config['username']
            message['To'] = send_to
            message['Subject'] = 'Prueba de conexión · PC-DOCTOR Mail Pro'
            message['Date'] = formatdate(localtime=True)
            message['Message-ID'] = make_msgid(domain=config['username'].split('@')[-1])
            message.set_content('Mensaje de prueba enviado desde Órdenes Pro para verificar la configuración SMTP.')
            refused = client.send_message(message)
            if refused:
                raise MailError('servidor', 'El servidor no aceptó al destinatario de prueba.')
            steps.append('Envío de prueba: aceptado por el servidor para ' + send_to)
        else:
            steps.append('Envío de prueba: no solicitado')
        return steps
    except Exception as error:
        failure = classify(error, host, port)
        failure.steps = steps
        raise failure from None
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                pass


# ---------------------------------------------------------------------------------------------
# Gestor: lectura en vivo por IMAP y envío por SMTP. Nada de esto copia el buzón a la base.
# ---------------------------------------------------------------------------------------------
import base64
import hashlib
import json
import email
import html as html_lib
import quopri
from pathlib import Path
import re
import time
from email import policy
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

PAGE = 25
MAX_MESSAGE = 15_000_000
# La petición completa (adjuntos en Base64 más el mensaje) no puede superar los 4,5 MB que admite Vercel.
MAX_ATTACHMENTS = 3_200_000
MAX_RECIPIENTS = 20
ROLES = {'inbox': 'Bandeja de entrada', 'starred': 'Destacados', 'sent': 'Enviados', 'drafts': 'Borradores', 'junk': 'Spam', 'trash': 'Papelera', 'archive': 'Archivo'}
ADDRESS = re.compile(r'[^\s@<>"(),;:\\]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
ALLOWED = {'p', 'br', 'div', 'span', 'b', 'strong', 'i', 'em', 'u', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'a', 'hr'}
DROPPED = {'script', 'style', 'head', 'title', 'iframe', 'object', 'embed', 'form', 'svg', 'math', 'template', 'noscript'}


SAFE_STYLES = {'color', 'background-color', 'font-weight', 'font-style', 'font-size', 'text-align', 'vertical-align', 'white-space', 'line-height', 'letter-spacing', 'text-decoration', 'width', 'max-width',
               'padding', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left', 'border', 'border-top', 'border-right', 'border-bottom', 'border-left', 'border-collapse'}


def safe_style(attrs):
    """Estilos de presentación inofensivos (colores, bordes, tamaños). Nada que cargue recursos, posicione u oculte contenido."""
    values = dict(attrs)
    rules = [item.split(':', 1) for item in str(values.get('style') or '').split(';') if ':' in item]
    if re.fullmatch(r'#[0-9a-fA-F]{3,8}', str(values.get('bgcolor') or '').strip()):
        rules.append(['background-color', values['bgcolor']])
    kept = []
    for prop, value in rules[:24]:
        prop, value = prop.strip().lower(), value.strip()
        if prop not in SAFE_STYLES or len(value) > 60 or not re.fullmatch(r'[#a-zA-Z0-9 .,%()-]+', value) or re.search(r'(?i)url|expression|var\(|calc\(', value):
            continue
        if prop == 'font-size' and not re.fullmatch(r'(9|1[0-9]|2[0-8])(\.\d)?px', value):
            continue
        if prop in ('width', 'max-width') and not re.fullmatch(r'\d{1,4}(px|%)', value):
            continue
        kept.append(prop + ':' + value)
    return ' data-s="' + html_lib.escape(';'.join(kept), quote=True) + '"' if kept else ''


class _Sanitizer(HTMLParser):
    """Lista blanca estricta: sin scripts ni recursos remotos; solo estilos de presentación validados, enlaces http/https/mailto e imágenes incrustadas en el propio mensaje."""

    def __init__(self, cids=None):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.blocked, self.cids = [], 0, 0, cids or {}

    def handle_starttag(self, tag, attrs):
        if tag in DROPPED:
            self.skip += 1
        elif self.skip:
            return
        elif tag == 'img' and str(dict(attrs).get('src') or '').lower().startswith('cid:') and str(dict(attrs).get('src'))[4:].strip() in self.cids:
            # Imagen que viaja dentro del mensaje (logo de una firma, por ejemplo): se muestra desde el propio servidor de la aplicación.
            values = dict(attrs)
            width = str(values.get('width') or '')
            self.out.append('<img data-part="' + str(self.cids[str(values['src'])[4:].strip()]) + '" alt="' + html_lib.escape(str(values.get('alt') or '')[:120], quote=True) + '"' + (' width="' + width + '"' if re.fullmatch(r'\d{1,3}', width) else '') + '>')
        elif tag == 'img':
            self.blocked += 1
            alt = dict(attrs).get('alt') or ''
            self.out.append('<span class="mail-blocked">[imagen bloqueada' + (': ' + html_lib.escape(alt[:80]) if alt else '') + ']</span>')
        elif tag == 'a':
            href = (dict(attrs).get('href') or '').strip()
            if re.match(r'(?i)^(https?://|mailto:|tel:)[^\s"<>]+$', href) and len(href) < 2000:
                self.out.append('<a href="' + html_lib.escape(href, quote=True) + '" target="_blank" rel="noopener noreferrer nofollow"' + safe_style(attrs) + '>')
            else:
                self.out.append('<a>')
        elif tag in ALLOWED:
            self.out.append('<' + tag + safe_style(attrs) + '>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in DROPPED:
            self.skip -= 1

    def handle_endtag(self, tag):
        if tag in DROPPED:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in ALLOWED and tag not in ('br', 'hr'):
            self.out.append('</' + tag + '>')

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html_lib.escape(data))


def sanitize_html(source, cids=None):
    parser = _Sanitizer(cids)
    try:
        parser.feed(source[:600_000])
        parser.close()
    except Exception:
        return html_lib.escape(re.sub(r'<[^>]*>', ' ', source[:200_000])), 0
    return ''.join(parser.out), parser.blocked


def clean_addresses(value):
    """Lista de direcciones válidas a partir de texto libre; rechaza cualquier entrada que no lo sea."""
    text = str(value or '')
    if re.search(r'[\x00-\x1f\x7f]', text):
        # Saltos de línea o caracteres de control: posible intento de inyectar cabeceras o destinatarios.
        raise MailError('configuracion', 'La lista de destinatarios contiene caracteres no permitidos.')
    found = []
    for _, address in getaddresses([text.replace(';', ',')]):
        address = address.strip()
        if not address:
            continue
        if not ADDRESS.fullmatch(address) or len(address) > 254:
            raise MailError('configuracion', 'Dirección de correo no válida: ' + address[:80])
        if address.lower() not in [item.lower() for item in found]:
            found.append(address)
    return found


def safe_filename(name):
    name = re.sub(r'[\x00-\x1f/\\:*?"<>|]+', '_', str(name or '')).strip(' .')
    return (name or 'adjunto')[:120]


def refresh_capabilities(client):
    """Capacidades reales de la sesión ya autenticada.

    Muchos servidores (Dovecot, cPanel) solo anuncian MOVE y UIDPLUS después de iniciar sesión, y las versiones de
    Python anteriores a 3.14 conservan la lista previa al inicio de sesión. Sin esta consulta el sistema creería que el
    servidor no sabe mover mensajes. Si la consulta falla se conserva la lista anterior: nunca se inventan capacidades.
    """
    try:
        code, data = client.capability()
        if code == 'OK' and data and data[-1]:
            names = tuple(str(data[-1], 'ascii', 'replace').upper().split())
            if names:
                client.capabilities = names
    except Exception:
        pass


def open_imap(config=None):
    config = config or settings()
    require(config)
    try:
        client = imaplib.IMAP4_SSL(config['imap_host'], config['imap_port'], ssl_context=context(), timeout=TIMEOUT)
        client.login(config['username'], config['password'])
        refresh_capabilities(client)
        return client
    except Exception as error:
        raise classify(error, config['imap_host'], config['imap_port']) from None


def close_imap(client):
    try:
        client.logout()
    except Exception:
        pass


def list_folders(client):
    """Carpetas reales del buzón con su función (entrada, enviados, borradores…)."""
    code, lines = client.list()
    folders = []
    for line in lines or []:
        match = re.match(rb'\((?P<flags>[^)]*)\) (?:"(?P<sep>[^"]*)"|NIL) (?P<name>.+)', line or b'')
        if not match:
            continue
        name = match['name'].decode('utf-8', 'replace').strip().strip('"')
        flags = match['flags'].decode('ascii', 'replace').lower()
        if '\\noselect' in flags:
            continue
        leaf = re.split(r'[./]', name)[-1].lower()
        role = 'inbox' if name.upper() == 'INBOX' else 'sent' if '\\sent' in flags or leaf in ('sent', 'enviados', 'sent items', 'sent messages') else 'drafts' if '\\drafts' in flags or leaf in ('drafts', 'borradores') \
            else 'trash' if '\\trash' in flags or leaf in ('trash', 'papelera', 'deleted items') else 'junk' if '\\junk' in flags or leaf in ('junk', 'spam') else 'archive' if '\\archive' in flags or leaf in ('archive', 'archivo') else 'other'
        folders.append({'id': name, 'role': role, 'special': ('\\' + {'junk': 'junk', 'sent': 'sent', 'drafts': 'drafts', 'trash': 'trash', 'archive': 'archive'}.get(role, '-')) in flags})
    order = ['inbox', 'sent', 'drafts', 'archive', 'junk', 'trash', 'other']
    # Entre carpetas con la misma función, primero la que el servidor marca como oficial (atributo SPECIAL-USE).
    folders.sort(key=lambda item: (order.index(item['role']), not item['special'], item['id'].lower()))
    seen = set()
    for item in folders:
        # Si el servidor tiene dos carpetas con la misma función (Junk y spam), solo la primera recibe el nombre estándar.
        leaf = re.split(r'[./]', item['id'])[-1]
        first = item['role'] in ROLES and item['role'] not in seen
        # Dos carpetas reales con la misma función (p. ej. Junk y spam) no se fusionan: la adicional conserva su nombre real en el servidor.
        item['label'] = ROLES[item['role']] if first else leaf
        item['duplicate'] = item['role'] in ROLES and not first
        seen.add(item['role'])
    return folders


def quoted(name):
    return '"' + name.replace('\\', '\\\\').replace('"', '\\"') + '"'


def resolve(client, folder):
    """Solo se aceptan carpetas que el servidor declara: el nombre nunca se usa sin validar."""
    folders = list_folders(client)
    match = next((item for item in folders if item['id'] == folder), None)
    if not match:
        raise MailError('configuracion', 'Carpeta de correo no disponible.')
    return match, folders


def by_role(folders, role):
    return next((item['id'] for item in folders if item['role'] == role), None)


def overview(client):
    folders = list_folders(client)
    for item in folders:
        code, data = client.status(quoted(item['id']), '(MESSAGES UNSEEN UIDNEXT UIDVALIDITY)')
        text = (data[0] or b'').decode('ascii', 'replace') if code == 'OK' and data else ''
        for key, field in (('total', 'MESSAGES'), ('unread', 'UNSEEN'), ('uidnext', 'UIDNEXT'), ('uidvalidity', 'UIDVALIDITY')):
            found = re.search(field + r' (\d+)', text)
            item[key] = int(found[1]) if found else 0
    return folders


def header_text(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def people(message, field):
    return [{'name': header_text(name)[:120], 'address': address[:254]} for name, address in getaddresses([str(value) for value in message.get_all(field, [])]) if address]


def date_iso(message):
    try:
        return parsedate_to_datetime(str(message['date'])).astimezone().isoformat(timespec='seconds')
    except Exception:
        return ''


def parse_bounce(message):
    """Informe de entrega (DSN, RFC 3464) de un mensaje `multipart/report`. None si no es un informe fiable.

    Devuelve destinatario, acción (failed/delayed), estado, diagnóstico y el Message-ID del envío original cuando el
    informe lo incluye. No se guía por el asunto: solo por la estructura del informe.
    """
    if message.get_content_type() != 'multipart/report' or str(message.get_param('report-type') or '').lower() != 'delivery-status':
        return None
    status = next((part for part in message.walk() if part.get_content_type() == 'message/delivery-status'), None)
    if status is None:
        return None
    payload = status.get_payload()
    blocks = [block for block in payload if hasattr(block, 'get')] if isinstance(payload, list) else []
    if not blocks:
        text = status.get_payload(decode=True) or b''
        blocks = [email.message_from_bytes(chunk, policy=policy.default) for chunk in re.split(rb'\r?\n\r?\n', text) if chunk.strip()]
    report = next((block for block in blocks if block.get('Final-Recipient') or block.get('Original-Recipient')), None)
    if report is None:
        return None
    recipient = header_text(str(report.get('Final-Recipient') or report.get('Original-Recipient')).split(';', 1)[-1])[:254]
    action = header_text(report.get('Action')).lower()
    code = header_text(report.get('Status'))[:20]
    if action not in ('failed', 'delayed') or not re.fullmatch(r'[245]\.\d{1,3}\.\d{1,3}', code) or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+', recipient):
        return None
    original = ''
    for part in message.walk():
        if part.get_content_type() in ('message/rfc822', 'text/rfc822-headers'):
            inner = part.get_payload()
            source = inner[0] if isinstance(inner, list) and inner else email.message_from_string(str(part.get_payload(decode=True).decode('utf-8', 'replace') if part.get_content_type() == 'text/rfc822-headers' else ''), policy=policy.default)
            original = header_text(source.get('Message-ID'))[:300]
    diagnostic = header_text(str(report.get('Diagnostic-Code') or '').split(';', 1)[-1])[:240]
    reasons = {'5.1.1': 'La dirección no existe en el servidor de destino.', '5.1.2': 'El dominio del destinatario no existe.', '5.1.10': 'La dirección no existe en el servidor de destino.', '5.2.2': 'El buzón del destinatario está lleno.', '5.2.1': 'El buzón del destinatario está desactivado.', '5.7.1': 'El servidor de destino rechazó el mensaje por sus políticas.', '4.4.1': 'No se pudo contactar al servidor de destino; se seguirá intentando.', '4.4.7': 'La entrega se retrasó demasiado.', '4.2.2': 'El buzón del destinatario está lleno; se seguirá intentando.'}
    return {'recipient': recipient, 'action': action, 'permanent': action == 'failed' and code.startswith('5'), 'status': code, 'diagnostic': diagnostic, 'original_id': original,
            'reason': reasons.get(code) or ('El servidor de destino no aceptó el mensaje.' if action == 'failed' else 'La entrega está retrasada; el servidor seguirá intentándolo.')}


def find_bounces(client, uids):
    """Revisa en la bandeja de entrada los UID indicados y devuelve los que son informes de entrega válidos."""
    found = []
    for uid in list(uids)[:10]:
        try:
            message, _ = fetch_message(client, 'INBOX', uid)
            report = parse_bounce(message)
            if report:
                found.append(dict(report, uid=int(uid)))
        except MailError:
            continue
    return found


def quota_detail(client):
    """Uso y cuota reales según la extensión QUOTA de IMAP: (datos | None, motivo técnico cuando no hay datos)."""
    try:
        code, data = client.getquotaroot('INBOX')
    except Exception as error:
        return None, 'El servidor IMAP rechazó GETQUOTAROOT (' + type(error).__name__ + ').'
    parts = [part for group in (data or []) for part in (group or []) if isinstance(part, bytes)]
    # Algunos servidores entregan la respuesta QUOTA fuera del resultado del comando: se revisa también lo pendiente.
    for extra in (getattr(client, 'untagged_responses', {}) or {}).get('QUOTA', []):
        if isinstance(extra, bytes):
            parts.append(extra)
    text = b' '.join(parts).decode('ascii', 'replace')
    found = re.search(r'STORAGE (\d+) (\d+)', text)
    if code != 'OK':
        return None, 'El servidor IMAP respondió ' + str(code) + ' a GETQUOTAROOT.'
    if not found:
        return None, 'El servidor IMAP no devolvió el recurso STORAGE (' + ('respuesta vacía' if not text.strip() else 'sin cuota de almacenamiento') + ').'
    # El servidor informa en KiB; un límite 0 significa que no hay cuota configurada.
    return {'used': int(found[1]) * 1024, 'limit': int(found[2]) * 1024 or None}, ''


def quota(client):
    return quota_detail(client)[0]


def remove_draft(client, folder, uid):
    """Elimina un borrador que acaba de ser reemplazado o enviado. Solo actúa sobre mensajes marcados como borrador."""
    code, _ = client.select(quoted(folder), readonly=False)
    if code != 'OK':
        return False
    code, data = client.uid('FETCH', str(int(uid)), '(FLAGS)')
    flags = b' '.join(part if isinstance(part, bytes) else part[0] for part in (data or []) if part).lower()
    if code != 'OK' or b'\\draft' not in flags:
        return False
    if client.uid('STORE', str(int(uid)), '+FLAGS', '(\\Deleted)')[0] != 'OK':
        return False
    try:
        # UID EXPUNGE borra únicamente ese mensaje; sin esa extensión se usa EXPUNGE sobre la carpeta de borradores.
        if client.uid('EXPUNGE', str(int(uid)))[0] != 'OK':
            client.expunge()
    except Exception:
        client.expunge()
    return True


def newer(client, last_uid, limit=20):
    """Mensajes de la bandeja de entrada con UID posterior a `last_uid` (identificador persistente de IMAP)."""
    code, data = client.select('INBOX', readonly=True)
    if code != 'OK':
        raise MailError('servidor', 'No se pudo abrir la bandeja de entrada.')
    code, found = client.uid('SEARCH', 'UID', str(int(last_uid) + 1) + ':*')
    if code != 'OK':
        return []
    # «n:*» siempre devuelve al menos el último mensaje: se descartan los que no son posteriores.
    uids = sorted((int(value) for value in (found[0] or b'').split() if int(value) > int(last_uid)), reverse=True)[:limit]
    return summaries(client, uids, previews=False)


def search(client, folder, query='', flagged=False, unread=False):
    code, data = client.select(quoted(folder), readonly=True)
    if code != 'OK':
        raise MailError('servidor', 'No se pudo abrir la carpeta.')
    validity = client.response('UIDVALIDITY')[1]
    search.uidvalidity = int(validity[0]) if validity and validity[0] else 0
    criteria = (['FLAGGED'] if flagged else []) + (['UNSEEN'] if unread else [])
    query = query.strip()[:120]
    if query:
        # El texto de búsqueda viaja como literal: no puede alterar el comando IMAP.
        client.literal = query.encode('utf-8')
        code, found = client.uid('SEARCH', 'CHARSET', 'UTF-8', *criteria, 'TEXT')
    else:
        code, found = client.uid('SEARCH', *(criteria or ['ALL']))
    if code != 'OK':
        raise MailError('servidor', 'El servidor no pudo completar la búsqueda.')
    return sorted((int(value) for value in (found[0] or b'').split()), reverse=True)


def _first_text(structure):
    """Primera parte de texto del mensaje según BODYSTRUCTURE: (sección, subtipo, juego de caracteres, codificación)."""
    start = structure.find('BODYSTRUCTURE ')
    if start < 0:
        return None
    body = structure[start + 14:]
    depth = len(body) - len(body.lstrip('('))
    found = re.match(r'\(*"text" "(plain|html)" (?:\(([^)]*)\)|NIL) (?:"[^"]*"|NIL) (?:"[^"]*"|NIL) "([^"]+)"', body, re.I)
    if not found:
        return None
    charset = re.search(r'"charset" "([^"]+)"', found[2] or '', re.I)
    return '1' + '.1' * max(0, depth - 2), found[1].lower(), charset[1] if charset else 'utf-8', found[3].lower()


def _preview(raw, subtype, charset, encoding):
    try:
        if encoding == 'base64':
            raw = re.sub(rb'[^A-Za-z0-9+/=]', b'', raw)
            raw = base64.b64decode(raw[:len(raw) // 4 * 4])
        elif encoding == 'quoted-printable':
            raw = quopri.decodestring(raw)
        try:
            text = raw.decode(charset, 'replace')
        except LookupError:
            text = raw.decode('utf-8', 'replace')
        if subtype == 'html':
            text = re.sub(r'(?is)<(style|script|head|title)\b.*?(</\1>|$)', ' ', text)
            text = html_lib.unescape(re.sub(r'(?s)<[^>]*(>|$)', ' ', text))
        return re.sub(r'\s+', ' ', text.replace('\ufffd', '')).strip()[:160]
    except Exception:
        return ''


def add_previews(client, rows, parts):
    """Primeras líneas de cada mensaje, sin marcarlo como leído. Si algo falla, la lista se muestra sin vista previa."""
    groups = {}
    for row in rows:
        if parts.get(row['uid']):
            groups.setdefault(parts[row['uid']][0], []).append(row)
    for section, group in groups.items():
        try:
            code, data = client.uid('FETCH', ','.join(str(row['uid']) for row in group), '(UID BODY.PEEK[' + section + ']<0.1500>)')
            if code != 'OK':
                continue
            index = 0
            while index < len(data):
                part = data[index]
                if isinstance(part, tuple):
                    meta = part[0] + b' ' + (data[index + 1] if index + 1 < len(data) and isinstance(data[index + 1], bytes) else b'')
                    uid = re.search(rb'UID (\d+)', meta)
                    row = next((row for row in group if uid and row['uid'] == int(uid[1])), None)
                    if row:
                        row['preview'] = _preview(part[1], *parts[row['uid']][1:])
                index += 1
        except Exception:
            continue


def summaries(client, uids, previews=True):
    if not uids:
        return []
    code, data = client.uid('FETCH', ','.join(str(uid) for uid in uids), '(UID FLAGS RFC822.SIZE BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID CONTENT-TYPE)])')
    if code != 'OK':
        raise MailError('servidor', 'No se pudieron leer los mensajes.')
    rows, parts, index = {}, {}, 0
    while index < len(data):
        part = data[index]
        if isinstance(part, tuple):
            meta = part[0] + b' ' + (data[index + 1] if index + 1 < len(data) and isinstance(data[index + 1], bytes) else b'')
            text = meta.decode('utf-8', 'replace')
            uid = re.search(r'UID (\d+)', text)
            if uid:
                message = email.message_from_bytes(part[1], policy=policy.default)
                flags = (re.search(r'FLAGS \(([^)]*)\)', text) or [None, ''])[1].lower()
                size = re.search(r'RFC822\.SIZE (\d+)', text)
                rows[int(uid[1])] = {'uid': int(uid[1]), 'subject': header_text(message['subject'])[:300] or '(sin asunto)', 'from': people(message, 'from')[:1], 'to': people(message, 'to')[:6], 'date': date_iso(message),
                                     'message_id': header_text(message['message-id'])[:300], 'seen': '\\seen' in flags, 'flagged': '\\flagged' in flags, 'answered': '\\answered' in flags, 'draft': '\\draft' in flags,
                                     'size': int(size[1]) if size else 0, 'attachments': bool(re.search(r'"attachment"|"filename"|"name" "[^"]+\.(pdf|docx?|xlsx?|zip|rar|jpe?g|png)"', text, re.I)), 'preview': '',
                                     'report': message.get_content_type() == 'multipart/report' and str(message.get_param('report-type') or '').lower() == 'delivery-status'}
                parts[int(uid[1])] = _first_text(text)
        index += 1
    ordered = [rows[uid] for uid in uids if uid in rows]
    if previews:
        add_previews(client, ordered, parts)
    return ordered


def fetch_message(client, folder, uid):
    code, data = client.select(quoted(folder), readonly=True)
    if code != 'OK':
        raise MailError('servidor', 'No se pudo abrir la carpeta.')
    code, data = client.uid('FETCH', str(int(uid)), '(RFC822.SIZE)')
    size = re.search(rb'RFC822\.SIZE (\d+)', b' '.join(part if isinstance(part, bytes) else part[0] for part in data if part) if data else b'')
    if code != 'OK' or not size:
        raise MailError('servidor', 'El mensaje ya no está disponible.')
    if int(size[1]) > MAX_MESSAGE:
        raise MailError('servidor', 'El mensaje supera el tamaño máximo que se puede abrir aquí (15 MB). Ábrelo desde Webmail.')
    code, data = client.uid('FETCH', str(int(uid)), '(FLAGS BODY.PEEK[])')
    raw = next((part[1] for part in data if isinstance(part, tuple)), None)
    if code != 'OK' or raw is None:
        raise MailError('servidor', 'El mensaje ya no está disponible.')
    flags = b' '.join(part if isinstance(part, bytes) else part[0] for part in data if part).decode('ascii', 'replace').lower()
    return email.message_from_bytes(raw, policy=policy.default), flags


def read_message(client, folder, uid, mark_seen=True):
    message, flags = fetch_message(client, folder, uid)
    plain, rich, attachments = '', '', []
    for index, part in enumerate(message.walk()):
        if part.is_multipart():
            continue
        disposition, kind, filename = part.get_content_disposition(), part.get_content_type(), part.get_filename()
        if disposition == 'attachment' or filename or not kind.startswith('text/'):
            payload = part.get_payload(decode=True) or b''
            if disposition == 'inline' and kind.startswith('image/') and not filename:
                continue
            attachments.append({'part': index, 'name': safe_filename(filename or 'adjunto'), 'type': kind[:100], 'size': len(payload)})
            continue
        try:
            content = part.get_content()
        except Exception:
            content = (part.get_payload(decode=True) or b'').decode('utf-8', 'replace')
        if kind == 'text/plain' and not plain:
            plain = content
        elif kind == 'text/html' and not rich:
            rich = content
    cids = {str(part['content-id']).strip().strip('<>'): index for index, part in enumerate(message.walk()) if not part.is_multipart() and part['content-id'] and part.get_content_type() in INLINE_IMAGES}
    safe, blocked = sanitize_html(rich, cids) if rich else ('', 0)
    if not plain and rich:
        plain = re.sub(r'\n{3,}', '\n\n', html_lib.unescape(re.sub(r'<[^>]+>', '', re.sub(r'(?i)<(br|/p|/div|/tr|/li)[^>]*>', '\n', re.sub(r'(?is)<(script|style|head).*?</\1>', '', rich))))).strip()
    if mark_seen and '\\seen' not in flags:
        client.select(quoted(folder), readonly=False)
        client.uid('STORE', str(int(uid)), '+FLAGS', '(\\Seen)')
    return {'uid': int(uid), 'folder': folder, 'subject': header_text(message['subject'])[:300] or '(sin asunto)', 'from': people(message, 'from')[:1], 'to': people(message, 'to')[:30], 'cc': people(message, 'cc')[:30], 'bcc': people(message, 'bcc')[:30], 'reply_to': people(message, 'reply-to')[:1],
            'date': date_iso(message), 'message_id': header_text(message['message-id'])[:300], 'references': header_text(message['references'])[:2000], 'text': plain[:400_000], 'html': safe, 'blocked_images': blocked, 'attachments': attachments,
            'flagged': '\\flagged' in flags, 'seen': True if mark_seen else '\\seen' in flags, 'draft': '\\draft' in flags,
            'signature_pref': {'on': True, 'off': False}.get(header_text(message['x-ordenespro-signature']).lower())}


VIEW_STYLE = ("html{overflow-x:auto;background:#fff;color-scheme:light}"
              "body{box-sizing:border-box;max-width:820px;margin:0 auto;padding:22px 26px 28px;background:#fff;color:#1f2937;font:15px/1.6 Arial,Helvetica,sans-serif;overflow-wrap:break-word;word-break:normal}"
              "img{max-width:100%;height:auto}table{max-width:100%}a{color:#1d5fb0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
              "pre.op-plain{margin:0;font:15px/1.65 Arial,Helvetica,sans-serif}blockquote{margin:12px 0 0;padding-left:12px;border-left:3px solid #c9ccd1;color:#555}"
              "@media(max-width:520px){body{padding:14px 14px 20px;font-size:15px}}@media print{body{max-width:none;padding:0}}")
VIEW_ACTIVE = re.compile(r'(?is)<(script|iframe|object|embed|applet|form|frameset|noscript)\b.*?</\1\s*>|<(?:script|iframe|object|embed|applet|form|frame|frameset|base|link|meta)\b[^>]*>|</(?:form|iframe|object|embed)\s*>')
VIEW_EMBED_LIMIT = 6_000_000


def view_policy(nonce, remote=False):
    """Política de contenido del marco aislado en el que se lee un correo: sin scripts del remitente (solo el del visor, con su nonce),
    sin formularios, marcos ni recursos externos; las imágenes remotas solo si la persona lo pide."""
    return ("default-src 'none'; img-src data:" + (' https:' if remote else '') + "; style-src 'unsafe-inline'; script-src 'nonce-" + nonce + "'; "
            "form-action 'none'; frame-ancestors 'self'; sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-modals")


def message_page(message, nonce, remote=False):
    """Documento HTML para leer un mensaje dentro de un marco aislado. Conserva el HTML original (tablas, estilos y firmas tal como
    llegaron); solo retira contenido activo y sustituye las imágenes incrustadas (cid:) por sus propios datos. El texto sin formato
    se muestra respetando sus saltos de línea. El único script es el del visor: avisa de la altura del contenido y permite imprimir."""
    plain, rich, images = '', '', {}
    for part in message.walk():
        if part.is_multipart():
            continue
        kind, name, disposition = part.get_content_type(), part.get_filename(), part.get_content_disposition()
        if kind in INLINE_IMAGES and part['content-id']:
            content = part.get_payload(decode=True) or b''
            if content.startswith(INLINE_IMAGES[kind]) and len(content) <= 3_000_000:
                images[str(part['content-id']).strip().strip('<>')] = (kind, content)
            continue
        if disposition == 'attachment' or name or not kind.startswith('text/'):
            continue
        try:
            content = part.get_content()
        except Exception:
            content = (part.get_payload(decode=True) or b'').decode('utf-8', 'replace')
        if kind == 'text/plain' and not plain:
            plain = content
        elif kind == 'text/html' and not rich:
            rich = content
    if rich:
        body, spent = VIEW_ACTIVE.sub('', rich[:1_500_000]), 0
        body = re.sub(r'(?i)\son[a-z]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', '', body)
        body = re.sub(r'(?i)(href|src)\s*=\s*(["\']?)\s*(?:javascript|vbscript|data:text/html)[^"\'\s>]*\2', r'\1="#"', body)
        def embed(match):
            nonlocal spent
            found = images.get(match.group(2).strip())
            if not found or spent + len(found[1]) > VIEW_EMBED_LIMIT:
                return match.group(0)
            spent += len(found[1])
            return match.group(1) + 'data:' + found[0] + ';base64,' + base64.b64encode(found[1]).decode()
        body = re.sub(r'(?i)(src\s*=\s*["\']?)cid:([^"\'\s>]+)', embed, body)
    else:
        body = '<pre class="op-plain">' + html_lib.escape(plain[:400_000] or '(mensaje sin contenido)') + '</pre>'
    script = ("(function(){var last=0;function tell(){var b=document.body,h=b?Math.ceil(b.offsetHeight+(document.documentElement.scrollWidth>document.documentElement.clientWidth?18:0)):0;"
              "if(h!==last){last=h;parent.postMessage({ordenesProMail:'height',height:h},'*');}}"
              "addEventListener('load',tell);addEventListener('resize',tell);if(window.ResizeObserver&&document.body)new ResizeObserver(tell).observe(document.body);"
              "var n=0,t=setInterval(function(){tell();if(++n>12)clearInterval(t);},400);tell();"
              "addEventListener('message',function(e){if(e.data==='ordenes-pro-mail-print'){try{print();}catch(x){}}});})();")
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light">'
            '<base target="_blank"><style>' + VIEW_STYLE + '</style></head><body>' + body + '<script nonce="' + nonce + '">' + script + '</script></body></html>')


INLINE_IMAGES = {'image/png': b'\x89PNG\r\n\x1a\n', 'image/jpeg': b'\xff\xd8\xff', 'image/gif': b'GIF8', 'image/webp': b'RIFF'}


def inline_image(client, folder, uid, index):
    """Imagen incrustada del propio mensaje, solo si es realmente una imagen del tipo que declara."""
    message, _ = fetch_message(client, folder, uid)
    for position, part in enumerate(message.walk()):
        if position == int(index) and not part.is_multipart():
            kind, content = part.get_content_type(), part.get_payload(decode=True) or b''
            if kind in INLINE_IMAGES and content.startswith(INLINE_IMAGES[kind]) and len(content) <= 3_000_000:
                return kind, content
    raise MailError('servidor', 'Imagen no disponible.')


def attachment(client, folder, uid, index):
    message, _ = fetch_message(client, folder, uid)
    for position, part in enumerate(message.walk()):
        if position == int(index) and not part.is_multipart():
            return safe_filename(part.get_filename() or 'adjunto'), part.get_payload(decode=True) or b''
    raise MailError('servidor', 'Adjunto no disponible.')


def set_flag(client, folder, uid, action):
    change = {'seen': ('+FLAGS', '(\\Seen)'), 'unseen': ('-FLAGS', '(\\Seen)'), 'star': ('+FLAGS', '(\\Flagged)'), 'unstar': ('-FLAGS', '(\\Flagged)')}.get(action)
    if not change:
        raise MailError('configuracion', 'Acción no válida.')
    code, _ = client.select(quoted(folder), readonly=False)
    if code != 'OK' or client.uid('STORE', str(int(uid)), *change)[0] != 'OK':
        raise MailError('servidor', 'No se pudo actualizar el mensaje.')


def batch(client, folder, uids, action, target='', uidvalidity=None):
    """Acción real sobre varios mensajes (por UID) de una carpeta. Devuelve cuántos mensajes se procesaron.

    Marcar usa los indicadores IMAP; archivar, eliminar, restaurar y mover trasladan el mensaje a otra carpeta real.
    «Eliminar» siempre mueve a la Papelera del servidor: si no existe, se rechaza en lugar de borrar definitivamente.
    """
    uids = sorted({int(uid) for uid in uids})[:200]
    if not uids:
        raise MailError('configuracion', 'Selecciona al menos un mensaje.')
    source, folders = resolve(client, folder)
    code, _ = client.select(quoted(source['id']), readonly=False)
    if code != 'OK':
        raise MailError('servidor', 'No se pudo abrir la carpeta.')
    current = client.response('UIDVALIDITY')[1]
    current = int(current[0]) if current and current[0] else None
    if uidvalidity and current and int(uidvalidity) != current:
        # La carpeta cambió de identidad en el servidor: los UID que conoce el navegador ya no son fiables.
        raise MailError('configuracion', 'La carpeta cambió en el servidor. Actualiza la lista e inténtalo de nuevo.')
    code, found = client.uid('SEARCH', 'UID', ','.join(str(uid) for uid in uids))
    present = sorted(int(value) for value in (found[0] or b'').split()) if code == 'OK' else []
    present = [uid for uid in present if uid in uids]
    if not present:
        raise MailError('servidor', 'Los mensajes seleccionados ya no están en esta carpeta.')
    group = ','.join(str(uid) for uid in present)
    flags = {'seen': ('+FLAGS', '(\\Seen)'), 'unseen': ('-FLAGS', '(\\Seen)'), 'star': ('+FLAGS', '(\\Flagged)'), 'unstar': ('-FLAGS', '(\\Flagged)')}
    if action in flags:
        if client.uid('STORE', group, *flags[action])[0] != 'OK':
            raise MailError('servidor', 'El servidor no pudo actualizar los mensajes.')
        return len(present)
    uidplus = any(b'UIDPLUS' in (item if isinstance(item, bytes) else str(item).encode()) for item in client.capabilities)
    if action == 'purge':
        if source['role'] != 'trash':
            raise MailError('configuracion', 'Solo se elimina definitivamente desde la Papelera.')
        if not uidplus:
            raise MailError('servidor', 'El servidor de correo no ofrece una forma segura de eliminar mensajes concretos. El mensaje se conserva en la Papelera.')
        if client.uid('STORE', group, '+FLAGS', '(\\Deleted)')[0] != 'OK' or client.uid('EXPUNGE', group)[0] != 'OK':
            raise MailError('servidor', 'No fue posible eliminar el mensaje. Se conserva en la Papelera.')
        return len(present)
    destination = {'archive': by_role(folders, 'archive'), 'trash': by_role(folders, 'trash'), 'restore': by_role(folders, 'inbox'), 'move': target if any(item['id'] == target for item in folders) else None}.get(action)
    if action not in ('archive', 'trash', 'restore', 'move'):
        raise MailError('configuracion', 'Acción no válida.')
    if not destination:
        raise MailError('configuracion', {'archive': 'El servidor no tiene una carpeta de Archivo identificada.', 'trash': 'El servidor no tiene una Papelera identificada: no se eliminó nada.'}.get(action, 'Carpeta de destino no disponible.'))
    if destination == source['id']:
        raise MailError('configuracion', 'Los mensajes ya están en esa carpeta.')
    if any(b'MOVE' in (item if isinstance(item, bytes) else str(item).encode()).split() for item in client.capabilities):
        if client.uid('MOVE', group, quoted(destination))[0] != 'OK':
            raise MailError('servidor', 'No fue posible mover el mensaje. El correo original permanece en su carpeta.')
        return len(present)
    # Sin MOVE: copiar, comprobar y solo entonces retirar exactamente esos UID del origen (requiere UIDPLUS).
    if not uidplus:
        raise MailError('servidor', 'El servidor de correo no ofrece una forma segura de mover mensajes. El correo original permanece en su carpeta.')
    if client.uid('COPY', group, quoted(destination))[0] != 'OK':
        raise MailError('servidor', 'No fue posible copiar el mensaje a la carpeta de destino. El correo original permanece en su carpeta.')
    if client.uid('STORE', group, '+FLAGS', '(\\Deleted)')[0] != 'OK' or client.uid('EXPUNGE', group)[0] != 'OK':
        raise MailError('servidor', 'Los mensajes se copiaron al destino, pero no se pudieron retirar del origen.')
    return len(present)


def rich_html(body, signature='', wrap=True):
    lines, out, listing = html_lib.escape(body, quote=False).split('\n'), [], False
    for line in lines:
        line = re.sub(r'\*\*(\S(?:.*?\S)?)\*\*', r'<strong>\1</strong>', line)
        line = re.sub(r'(?<![\w/])_(\S(?:.*?\S)?)_(?!\w)', r'<em>\1</em>', line)
        item = re.match(r'\s*- (.+)', line)
        if item and not listing:
            out.append('<ul>')
        if not item and listing:
            out.append('</ul>')
        listing = bool(item)
        out.append('<li>' + item[1] + '</li>' if item else (line + '<br>' if line.strip() else '<br>'))
    if listing:
        out.append('</ul>')
    foot = '<p style="color:#555">-- <br>' + html_lib.escape(signature, quote=False).replace('\n', '<br>') + '</p>' if signature else ''
    inner = '\n'.join(out) + foot
    return '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5">' + inner + '</div>' if wrap else inner


SIGNATURE_FIELDS = ('name', 'role', 'unit', 'phone', 'email', 'web', 'address')
SIGNATURE_DEFAULTS = {'enabled': True, 'on_new': True, 'on_reply': True, 'on_forward': True, 'name': 'Enrique Martínez Gómez', 'role': 'SOPORTECNICO', 'unit': 'Matriz | PC-DOCTOR',
                      'phone': '+593 987460591', 'email': '', 'web': 'www.ecuadorpcdoctor.com', 'address': 'Calle Bolívar, Juan Montalvo'}
SIGNATURE_LOGO = Path(__file__).resolve().parent / 'static' / 'logo-firma.png'
QUOTE_START = re.compile(r'\n+(?=El [^\n]{0,200} escribió:\n|-{5,} Mensaje reenviado -{5,})')


def clean_signature(raw, account=''):
    """Datos de la firma validados: solo texto corto en cada campo; el HTML siempre lo genera el servidor."""
    raw = raw if isinstance(raw, dict) else {}
    result = {key: raw.get(key, SIGNATURE_DEFAULTS[key]) is True if key in raw else SIGNATURE_DEFAULTS[key] for key in ('enabled', 'on_new', 'on_reply', 'on_forward')}
    result['use_image'] = raw.get('use_image') is True
    for key in SIGNATURE_FIELDS:
        value = re.sub(r'\s+', ' ', re.sub(r'[\r\n\t<>]+', ' ', str(raw.get(key, SIGNATURE_DEFAULTS[key]) if key in raw else SIGNATURE_DEFAULTS[key]))).strip()[:120]
        result[key] = value
    if not result['email']:
        result['email'] = account
    return result


SIGNATURE_IMAGE_LIMIT = 400_000
SIGNATURE_IMAGE_WIDTH = (200, 2400)
SIGNATURE_DISPLAY_MAX = 600   # ancho de la plantilla de correo; una imagen mayor se muestra reducida, sin deformarse


def image_size(content):
    """(tipo, ancho, alto) de una imagen PNG o JPEG leída de sus propios bytes; None si no es una de las dos."""
    if content[:8] == b'\x89PNG\r\n\x1a\n' and content[12:16] == b'IHDR' and len(content) > 24:
        return 'png', int.from_bytes(content[16:20], 'big'), int.from_bytes(content[20:24], 'big')
    if content[:3] == b'\xff\xd8\xff':
        at = 2
        while at + 9 < len(content):
            if content[at] != 0xFF:
                return None
            marker = content[at + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                return 'jpeg', int.from_bytes(content[at + 7:at + 9], 'big'), int.from_bytes(content[at + 5:at + 7], 'big')
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                at += 2
                continue
            at += 2 + int.from_bytes(content[at + 2:at + 4], 'big')
    return None


def check_signature_image(content):
    """Valida la firma gráfica subida por administración. Devuelve (datos, '') o (None, motivo)."""
    if not 200 <= len(content) <= SIGNATURE_IMAGE_LIMIT:
        return None, 'La imagen debe pesar como máximo %d KB.' % (SIGNATURE_IMAGE_LIMIT // 1000)
    found = image_size(content)
    if not found:
        return None, 'Usa la firma en formato PNG o JPG.'
    kind, width, height = found
    if not SIGNATURE_IMAGE_WIDTH[0] <= width <= SIGNATURE_IMAGE_WIDTH[1] or not 40 <= height <= 1600:
        return None, 'La imagen debe medir entre %d y %d px de ancho y hasta 1600 px de alto.' % SIGNATURE_IMAGE_WIDTH
    return {'kind': kind, 'width': width, 'height': height, 'data': base64.b64encode(content).decode()}, ''


def load_signature(c, account):
    """Firma del buzón remitente lista para usar en cualquier correo del sistema: los datos validados y, si administración cargó la
    firma gráfica original y la tiene activa, esa imagen (`image` con sus medidas y `_image` con sus bytes, que nunca sale al navegador)."""
    row = c.execute('SELECT value FROM system_state WHERE key=?', ('mail_signature_card:' + account,)).fetchone()
    try:
        raw = json.loads(row['value']) if row else {}
    except ValueError:
        raw = {}
    card = clean_signature(raw, account)
    card['image'] = None
    stored = c.execute('SELECT value FROM system_state WHERE key=?', ('mail_signature_image:' + account,)).fetchone()
    try:
        picture = json.loads(stored['value']) if stored else None
        content = base64.b64decode(picture['data']) if picture else b''
    except (ValueError, KeyError, TypeError):
        picture, content = None, b''
    if picture and image_size(content):
        card['image'] = {key: picture[key] for key in ('kind', 'width', 'height')}
        card['image']['stamp'] = hashlib.sha256(content).hexdigest()[:12]
        if card['use_image']:
            card['_image'] = content
    else:
        card['use_image'] = False
    return card


def public_signature(card):
    """La firma sin los bytes de la imagen, para responder al navegador."""
    return {key: value for key, value in card.items() if not key.startswith('_')}


def signature_part(sign, domain):
    """Único punto que compone la firma de un correo. Devuelve (html, identificador CID, bytes de la imagen embebida, subtipo).
    Con la firma gráfica original activa, la firma es esa imagen tal cual (sin reconstruir nada); si no, la tarjeta con el logotipo."""
    if sign.get('_image'):
        cid = make_msgid(idstring='firma-grafica', domain=domain)
        width = min(sign['image']['width'], SIGNATURE_DISPLAY_MAX)
        alt = ' · '.join(item for item in (sign['name'], sign['role'], sign['phone'], sign['web']) if item)
        page = ('<img src="cid:' + cid[1:-1] + '" width="' + str(width) + '" alt="' + html_lib.escape(alt, quote=True) + '" '
                'style="display:block;width:' + str(width) + 'px;max-width:100%;height:auto;border:0;outline:none;text-decoration:none;">')
        return page, cid, sign['_image'], sign['image']['kind']
    cid = make_msgid(domain=domain)
    logo = SIGNATURE_LOGO.read_bytes() if SIGNATURE_LOGO.exists() else None
    return signature_html(sign, 'cid:' + cid[1:-1] if logo else 'https://ordenes-pro.ecuadorpcdoctor.com/static/logo-firma.png'), cid, logo, 'png'


def signature_text(sign):
    lines = [sign['name'], ' · '.join(item for item in (sign['role'], sign['unit']) if item)]
    lines += [label + ': ' + sign[key] for key, label in (('phone', 'Tel.'), ('email', 'Correo'), ('web', 'Web'), ('address', 'Dirección')) if sign[key]]
    return '\n'.join(line for line in lines if line)


def signature_html(sign, logo_src):
    """Firma corporativa en tablas y estilos en línea, compatible con Gmail, Outlook, Thunderbird, Apple Mail y webmail."""
    esc = lambda value: html_lib.escape(str(value), quote=True)
    font = "font-family:Arial,Helvetica,sans-serif;"
    def row(icon, label, value, href=''):
        if not value:
            return ''
        text = '<a href="' + esc(href) + '" style="color:#1f2937;text-decoration:none;">' + esc(value) + '</a>' if href else esc(value)
        return ('<tr><td width="22" valign="top" style="padding:3px 7px 3px 0;' + font + 'font-size:12px;line-height:18px;color:#e03a3e;" title="' + esc(label) + '">' + icon + '</td>'
                '<td valign="top" style="padding:3px 0;' + font + 'font-size:13px;line-height:18px;color:#1f2937;white-space:nowrap;">' + text + '</td></tr>')
    phone_href = 'tel:' + re.sub(r'[^0-9+]', '', sign['phone'])
    web_href = sign['web'] if re.match(r'https?://', sign['web'], re.I) else 'https://' + sign['web']
    contact = (row('&#128222;', 'Teléfono', sign['phone'], phone_href) + row('&#9993;&#65039;', 'Correo', sign['email'], 'mailto:' + sign['email'])
               + row('&#127760;', 'Sitio web', sign['web'], web_href) + row('&#128205;', 'Dirección', sign['address']))
    return ('<table role="presentation" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff" style="background-color:#ffffff;border-collapse:collapse;border:1px solid #e2e6ee;border-bottom:3px solid #e03a3e;">'
            '<tr><td valign="middle" align="center" style="padding:14px 6px 14px 16px;">'
            '<img src="' + esc(logo_src) + '" width="120" alt="PC-DOCTOR S.A." style="display:block;width:120px;height:auto;border:0;color:#1f2937;font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;"></td>'
            '<td valign="middle" style="padding:14px 18px 14px 10px;">'
            '<div style="' + font + 'font-size:16px;line-height:21px;font-weight:bold;color:#1f2937;white-space:nowrap;">' + esc(sign['name']) + '</div>'
            + ('<div style="' + font + 'font-size:12px;line-height:17px;font-weight:bold;letter-spacing:1px;color:#e03a3e;white-space:nowrap;">' + esc(sign['role']) + '</div>' if sign['role'] else '')
            + ('<div style="' + font + 'font-size:12px;line-height:17px;color:#5b6677;white-space:nowrap;">' + esc(sign['unit']) + '</div>' if sign['unit'] else '')
            + '</td><td width="2" bgcolor="#e03a3e" style="background-color:#e03a3e;font-size:0;line-height:0;width:2px;">&nbsp;</td>'
            '<td valign="middle" style="padding:14px 18px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0">' + contact + '</table></td></tr></table>')


def build_message(config, data, signature=''):
    """Mensaje MIME válido. `data`: to, cc, subject, body, in_reply_to, references, attachments[{name,type,data(base64)}]."""
    to, cc, bcc = clean_addresses(data.get('to')), clean_addresses(data.get('cc')), clean_addresses(data.get('bcc'))
    if not to and not data.get('draft'):
        raise MailError('configuracion', 'Indica al menos un destinatario.')
    if len(to) + len(cc) + len(bcc) > MAX_RECIPIENTS:
        raise MailError('configuracion', 'Demasiados destinatarios: máximo ' + str(MAX_RECIPIENTS) + '.')
    subject = re.sub(r'[\r\n]+', ' ', str(data.get('subject', ''))).strip()[:300]
    body = str(data.get('body', ''))[:200_000]
    if not data.get('draft') and not subject and not body.strip():
        raise MailError('configuracion', 'Escribe un asunto o un mensaje.')
    message = EmailMessage()
    name = re.sub(r'[\r\n"<>]+', ' ', str(data.get('from_name', ''))).strip()[:80]
    message['From'] = (name + ' <' + config['username'] + '>') if name else config['username']
    if to:
        message['To'] = ', '.join(to)
    if cc:
        message['Cc'] = ', '.join(cc)
    if bcc and data.get('draft'):
        # Solo en borradores: la copia oculta se conserva para cuando se reabra. Al enviar nunca figura en las cabeceras.
        message['Bcc'] = ', '.join(bcc)
    message['Subject'] = subject or '(sin asunto)'
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid(domain=config['username'].split('@')[-1])
    if data.get('draft') and data.get('signature_pref') in (True, False):
        # El borrador recuerda si debe llevar firma; la firma en sí se añade una sola vez, al enviar.
        message['X-OrdenesPro-Signature'] = 'on' if data['signature_pref'] else 'off'
    reply = re.sub(r'[\r\n]+', ' ', str(data.get('in_reply_to', ''))).strip()[:300]
    if re.fullmatch(r'<[^<>\s]+>', reply):
        message['In-Reply-To'] = reply
        refs = [item for item in re.findall(r'<[^<>\s]+>', str(data.get('references', '')))[-20:] if item != reply]
        message['References'] = ' '.join(refs + [reply])
    # La firma va después del texto escrito y antes del historial citado (respuestas y reenvíos).
    sign = signature if isinstance(signature, dict) else None
    plain_sign = signature_text(sign) if sign else str(signature or '').strip()[:2000]
    cut = QUOTE_START.search(body) if (sign or plain_sign) else None
    head, tail = (body[:cut.start()], body[cut.start():]) if cut else (body, '')
    message.set_content(head.rstrip() + ('\n\n-- \n' + plain_sign if plain_sign else '') + (tail.rstrip() if tail else '') + '\n')
    layout = data.get('layout') if isinstance(data.get('layout'), dict) else None
    if sign or data.get('rich') or layout:
        # Versión HTML: el texto se escapa por completo; solo se convierten las marcas propias y se añade la firma generada por el servidor.
        page, cid, logo, logo_kind = signature_part(sign, config['username'].split('@')[-1]) if sign else ('', '', None, 'png')
        block = '<br>' + page if sign else ''
        quoted = '<blockquote style="margin:14px 0 0;padding-left:12px;border-left:3px solid #c9ccd1;color:#555555;">' + rich_html(tail.strip(), '', wrap=False) + '</blockquote>' if tail.strip() else ''
        if layout:
            # Plantilla institucional común: encabezado textual, contenido alineado y la firma autorizada al final.
            import mailing
            message.add_alternative(mailing.html(head.rstrip(), str(layout.get('title') or subject), block[4:] if block else '', quoted), subtype='html')
        else:
            message.add_alternative('<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#222222;">' + rich_html(head.rstrip(), '' if sign else plain_sign, wrap=False) + block + quoted + '</div>', subtype='html')
        if logo:
            message.get_payload()[1].add_related(logo, 'image', logo_kind, cid=cid, disposition='inline')
    total = 0
    for item in data.get('attachments') or []:
        try:
            content = base64.b64decode(str(item.get('data', '')), validate=True)
        except Exception:
            raise MailError('configuracion', 'Un adjunto no se pudo leer.')
        total += len(content)
        if total > MAX_ATTACHMENTS:
            raise MailError('configuracion', 'Los adjuntos superan el máximo de 3,1 MB por mensaje.')
        kind = str(item.get('type') or 'application/octet-stream')
        main, _, sub = kind.partition('/')
        if not re.fullmatch(r'[a-z0-9.+-]+', main or '') or not re.fullmatch(r'[a-zA-Z0-9.+-]+', sub or ''):
            main, sub = 'application', 'octet-stream'
        message.add_attachment(content, maintype=main, subtype=sub, filename=safe_filename(item.get('name')))
    # Los destinatarios en copia oculta reciben el mensaje pero nunca figuran en sus cabeceras.
    return message, to + cc + [address for address in bcc if address not in to + cc]


def deliver(config, message, recipients):
    """Entrega por SMTP. Solo vuelve sin error cuando el servidor aceptó el mensaje."""
    client = None
    try:
        client = smtp_client(config)
        client.login(config['username'], config['password'])
        refused = client.send_message(message, from_addr=config['username'], to_addrs=recipients)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    except Exception as error:
        raise classify(error, config['smtp_host'], config['smtp_port']) from None
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                pass


def store(client, folder, message, flags):
    code, _ = client.append(quoted(folder), flags, imaplib.Time2Internaldate(time.time()), message.as_bytes(policy=policy.SMTP))
    return code == 'OK'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Pruebas de conexión de PC-DOCTOR Mail Pro')
    parser.add_argument('command', choices=['estado', 'test-imap', 'test-smtp'])
    parser.add_argument('--enviar-a', default='', help='Destinatario autorizado para el mensaje de prueba SMTP.')
    parser.add_argument('--confirmar', action='store_true', help='Confirma el envío real del mensaje de prueba.')
    args = parser.parse_args(argv)
    try:
        import app
        app.load_env()
    except Exception:
        pass
    if args.command == 'estado':
        info = status()
        print('Configurado:', 'sí' if info.get('configured') else 'no', '| IMAP', info.get('imap') or '—', '| SMTP', info.get('smtp') or '—', '| cuenta', info.get('account') or '—', '| contraseña', 'definida' if info.get('password_set') else 'sin definir')
        return 0
    if args.enviar_a and not args.confirmar:
        raise SystemExit('Para enviar el mensaje de prueba añade --confirmar. No se envió nada.')
    try:
        steps = test_imap() if args.command == 'test-imap' else test_smtp(send_to=args.enviar_a)
        for step in steps:
            print('  ✓', step)
        print('Resultado: correcto.')
        return 0
    except MailError as error:
        for step in getattr(error, 'steps', []):
            print('  ✓', step)
        print('  ✗ [' + error.kind + ']', error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
