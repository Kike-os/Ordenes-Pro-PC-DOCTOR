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
import email
import html as html_lib
import quopri
import re
import time
from email import policy
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

PAGE = 25
MAX_MESSAGE = 15_000_000
MAX_ATTACHMENTS = 3_500_000
MAX_RECIPIENTS = 20
ROLES = {'inbox': 'Bandeja de entrada', 'starred': 'Destacados', 'sent': 'Enviados', 'drafts': 'Borradores', 'junk': 'Spam', 'trash': 'Papelera', 'archive': 'Archivo'}
ADDRESS = re.compile(r'[^\s@<>"(),;:\\]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
ALLOWED = {'p', 'br', 'div', 'span', 'b', 'strong', 'i', 'em', 'u', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'a', 'hr'}
DROPPED = {'script', 'style', 'head', 'title', 'iframe', 'object', 'embed', 'form', 'svg', 'math', 'template', 'noscript'}


class _Sanitizer(HTMLParser):
    """Lista blanca estricta: sin estilos, sin atributos (salvo enlaces http/https/mailto) y sin recursos remotos."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.blocked = [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in DROPPED:
            self.skip += 1
        elif self.skip:
            return
        elif tag == 'img':
            self.blocked += 1
            alt = dict(attrs).get('alt') or ''
            self.out.append('<span class="mail-blocked">[imagen bloqueada' + (': ' + html_lib.escape(alt[:80]) if alt else '') + ']</span>')
        elif tag == 'a':
            href = (dict(attrs).get('href') or '').strip()
            if re.match(r'(?i)^(https?://|mailto:)[^\s"<>]+$', href) and len(href) < 2000:
                self.out.append('<a href="' + html_lib.escape(href, quote=True) + '" target="_blank" rel="noopener noreferrer nofollow">')
            else:
                self.out.append('<a>')
        elif tag in ALLOWED:
            self.out.append('<' + tag + '>')

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


def sanitize_html(source):
    parser = _Sanitizer()
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


def open_imap(config=None):
    config = config or settings()
    require(config)
    try:
        client = imaplib.IMAP4_SSL(config['imap_host'], config['imap_port'], ssl_context=context(), timeout=TIMEOUT)
        client.login(config['username'], config['password'])
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
    code, data = client.uid('FETCH', ','.join(str(uid) for uid in uids), '(UID FLAGS RFC822.SIZE BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)])')
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
                                     'size': int(size[1]) if size else 0, 'attachments': bool(re.search(r'"attachment"|"filename"|"name" "[^"]+\.(pdf|docx?|xlsx?|zip|rar|jpe?g|png)"', text, re.I)), 'preview': ''}
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
    safe, blocked = sanitize_html(rich) if rich else ('', 0)
    if not plain and rich:
        plain = re.sub(r'\n{3,}', '\n\n', html_lib.unescape(re.sub(r'<[^>]+>', '', re.sub(r'(?i)<(br|/p|/div|/tr|/li)[^>]*>', '\n', re.sub(r'(?is)<(script|style|head).*?</\1>', '', rich))))).strip()
    if mark_seen and '\\seen' not in flags:
        client.select(quoted(folder), readonly=False)
        client.uid('STORE', str(int(uid)), '+FLAGS', '(\\Seen)')
    return {'uid': int(uid), 'folder': folder, 'subject': header_text(message['subject'])[:300] or '(sin asunto)', 'from': people(message, 'from')[:1], 'to': people(message, 'to')[:30], 'cc': people(message, 'cc')[:30], 'reply_to': people(message, 'reply-to')[:1],
            'date': date_iso(message), 'message_id': header_text(message['message-id'])[:300], 'references': header_text(message['references'])[:2000], 'text': plain[:400_000], 'html': safe, 'blocked_images': blocked, 'attachments': attachments,
            'flagged': '\\flagged' in flags, 'seen': True if mark_seen else '\\seen' in flags, 'draft': '\\draft' in flags}


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


def rich_html(body, signature=''):
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
    return '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5">' + '\n'.join(out) + foot + '</div>'


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
    message['Subject'] = subject or '(sin asunto)'
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid(domain=config['username'].split('@')[-1])
    reply = re.sub(r'[\r\n]+', ' ', str(data.get('in_reply_to', ''))).strip()[:300]
    if re.fullmatch(r'<[^<>\s]+>', reply):
        message['In-Reply-To'] = reply
        refs = [item for item in re.findall(r'<[^<>\s]+>', str(data.get('references', '')))[-20:] if item != reply]
        message['References'] = ' '.join(refs + [reply])
    signature = str(signature or '').strip()[:2000]
    message.set_content(body.rstrip() + ('\n\n-- \n' + signature if signature else '') + '\n')
    if data.get('rich'):
        # Formato básico: el texto se escapa por completo y solo después se convierten las marcas propias (**negrita**, _cursiva_, listas con «- »).
        message.add_alternative(rich_html(body.rstrip(), signature), subtype='html')
    total = 0
    for item in data.get('attachments') or []:
        try:
            content = base64.b64decode(str(item.get('data', '')), validate=True)
        except Exception:
            raise MailError('configuracion', 'Un adjunto no se pudo leer.')
        total += len(content)
        if total > MAX_ATTACHMENTS:
            raise MailError('configuracion', 'Los adjuntos superan el máximo de 3,5 MB por mensaje.')
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
            raise MailError('servidor', 'El servidor no aceptó a: ' + ', '.join(list(refused)[:5]))
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
