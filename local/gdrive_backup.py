"""Respaldos automáticos en Google Drive — 1.5.312 (sustituye a MEGA Cloud y a Microsoft OneDrive).

Todo ocurre en el SERVIDOR (Vercel), sin Podman ni el equipo de la oficina:
  · Tarea programada a las 02:00 de Ecuador (/api/cron/backup) y dos reintentos diarios (04:00 y 07:00) que solo actúan si el respaldo del
    día todavía no quedó verificado. «Realizar respaldo ahora» se ejecuta en el momento. Función propia de hasta 300 s (api/backup.py).
  · Asistente en Configuración → Respaldos: paso 1, datos del cliente OAuth creado en Google Cloud (el secreto se guarda CIFRADO y nunca
    vuelve al navegador); paso 2, «Conectar Google Drive» (OAuth 2.0 + PKCE en la página de Google: Órdenes Pro nunca ve la contraseña);
    paso 3, respaldo de prueba con verificación real.
  · Permiso mínimo: https://www.googleapis.com/auth/drive.file — la aplicación solo ve y modifica los archivos y carpetas que ella crea.

Claves en el servidor (variables de entorno, nunca en el navegador):
  BACKUP_TOKEN_KEY (o ONEDRIVE_TOKEN_KEY, ya existente)  32 bytes en base64: cifra el secreto del cliente OAuth y el token de Google
  BACKUP_ENCRYPTION_KEY                                     32 bytes en base64: cifra cada respaldo (AES-256-GCM); guarda copia offline
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET                    opcionales: si existen, mandan sobre lo guardado desde el asistente
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import backups as bk

SCOPE = 'https://www.googleapis.com/auth/drive.file'
FOLDER = 'PC-DOCTOR S.A./Órdenes Pro/Respaldos Base de Datos'
FOLDER_MIME = 'application/vnd.google-apps.folder'
CHUNK = 256 * 1024 * 32                  # 8 MiB: múltiplo de 256 KiB, como exige la subida reanudable de Google
RETRY_HOURS = (4, 7)                     # reintentos diarios si el respaldo de las 02:00 no quedó verificado
STATUS = {'en_curso': 'En ejecución', 'correcto': 'Correcto', 'error': 'Error', 'pendiente': 'Pendiente'}


class BackupError(bk.BackupError):
    pass


def accounts_base():
    return os.getenv('GOOGLE_ACCOUNTS_BASE', 'https://accounts.google.com').rstrip('/')


def oauth_base():
    return os.getenv('GOOGLE_OAUTH_BASE', 'https://oauth2.googleapis.com').rstrip('/')


def api_base():
    return os.getenv('GOOGLE_API_BASE', 'https://www.googleapis.com').rstrip('/')


def redirect_uri():
    return os.getenv('APP_URL', 'http://127.0.0.1:8010').rstrip('/') + '/api/backups/google/callback'


# ---------------------------------------------------------------- cifrado de secretos guardados (mismo esquema que el resto del sistema)
def _token_key(optional=False):
    raw = (os.getenv('BACKUP_TOKEN_KEY', '') or os.getenv('ONEDRIVE_TOKEN_KEY', '')).strip()
    if raw:
        try:
            key = base64.b64decode(raw + '=' * (-len(raw) % 4))
        except ValueError:
            key = b''
        if len(key) == 32:
            return key
        if optional:
            return None
        raise BackupError('BACKUP_TOKEN_KEY debe ser una clave de 32 bytes en base64.', 500)
    if os.getenv('VERCEL'):
        if optional:
            return None
        raise BackupError('Falta BACKUP_TOKEN_KEY en el servidor (clave que cifra el acceso a Google Drive).', 500)
    import app
    path = Path(app.DATA) / 'backup-token.key'
    if not path.exists():
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(secrets.token_bytes(32))
    return path.read_bytes()[:32]


def _keys():
    key = _token_key()
    return (hmac.new(key, b'ordenes-pro:google:cifrado', hashlib.sha256).digest(), hmac.new(key, b'ordenes-pro:google:autenticacion', hashlib.sha256).digest())


def _stream(key, nonce, length):
    out = b''
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + struct.pack('>Q', counter), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def seal(text):
    enc, mac = _keys()
    nonce = secrets.token_bytes(16)
    plain = text.encode()
    body = bytes(a ^ b for a, b in zip(plain, _stream(enc, nonce, len(plain))))
    return 'gd1:' + base64.urlsafe_b64encode(nonce + body + hmac.new(mac, b'gd1' + nonce + body, hashlib.sha256).digest()).decode().rstrip('=')


def unseal(value):
    value = str(value or '')
    if not value.startswith('gd1:'):
        raise BackupError('El acceso guardado a Google Drive no tiene un formato válido.', 500)
    raw = base64.urlsafe_b64decode(value[4:] + '=' * (-len(value[4:]) % 4))
    nonce, body, tag = raw[:16], raw[16:-32], raw[-32:]
    enc, mac = _keys()
    if not hmac.compare_digest(tag, hmac.new(mac, b'gd1' + nonce + body, hashlib.sha256).digest()):
        raise BackupError('El acceso guardado a Google Drive no se pudo verificar (¿cambió BACKUP_TOKEN_KEY?).', 500)
    return bytes(a ^ b for a, b in zip(body, _stream(enc, nonce, len(body)))).decode()


# ---------------------------------------------------------------- configuración del cliente OAuth (asistente, paso 1)
CLIENT_ID = re.compile(r'[0-9]{6,20}-[a-z0-9]{20,40}\.apps\.googleusercontent\.com')


def app_config(c=None):
    if os.getenv('GOOGLE_CLIENT_ID', '').strip() and os.getenv('GOOGLE_CLIENT_SECRET', '').strip():
        return {'client_id': os.environ['GOOGLE_CLIENT_ID'].strip(), 'secret': os.environ['GOOGLE_CLIENT_SECRET'].strip(), 'source': 'servidor'}
    if c is None:
        return None
    saved = bk.get_state(c, 'gdrive_app')
    if not saved or not saved.get('client_id') or not saved.get('secret'):
        return None
    try:
        secret = unseal(saved['secret'])
    except BackupError:
        return None
    return {'client_id': saved['client_id'], 'secret': secret, 'source': 'panel', 'saved_at': saved.get('saved_at', '')}


def configured(c=None):
    return bool(_token_key(optional=True) and app_config(c))


def save_app_config(c, data, user_id):
    if os.getenv('GOOGLE_CLIENT_ID', '').strip():
        raise BackupError('El cliente de Google está definido en las variables del servidor; no se cambia desde el panel.', 409)
    if not _token_key(optional=True):
        raise BackupError('Falta BACKUP_TOKEN_KEY en el servidor: sin ella no se puede guardar el secreto cifrado.', 500)
    client_id = str(data.get('client_id', '')).strip()
    secret = str(data.get('client_secret', '')).strip()
    errors = {}
    if not CLIENT_ID.fullmatch(client_id):
        errors['client_id'] = 'Copia el «ID de cliente»: termina en .apps.googleusercontent.com'
    previous = bk.get_state(c, 'gdrive_app') or {}
    if not secret and not previous.get('secret'):
        errors['client_secret'] = 'Pega el «Secreto del cliente».'
    elif secret and (not 20 <= len(secret) <= 128 or any(ch.isspace() for ch in secret)):
        errors['client_secret'] = 'El secreto no tiene el formato esperado (suele empezar por GOCSPX-).'
    if errors:
        error = BackupError(next(iter(errors.values())) if len(errors) == 1 else 'Revisa los datos señalados.', 400)
        error.fields = errors
        raise error
    changed = previous.get('client_id') != client_id
    bk.set_state(c, 'gdrive_app', {'client_id': client_id, 'secret': seal(secret) if secret else previous['secret'], 'saved_at': bk.stamp(), 'saved_by': user_id})
    if changed:
        c.execute("DELETE FROM system_state WHERE key IN ('gdrive_link','gdrive_oauth')")
    c.commit()
    return changed


def clear_app_config(c):
    c.execute("DELETE FROM system_state WHERE key IN ('gdrive_app','gdrive_link','gdrive_oauth')")
    c.commit()


def encryption_ready():
    raw = os.getenv('BACKUP_ENCRYPTION_KEY', '').strip()
    try:
        return len(base64.b64decode(raw + '=' * (-len(raw) % 4))) == 32 if raw else False
    except ValueError:
        return False


def not_ready(c):
    """Por qué todavía no se puede respaldar en Google Drive (texto para el panel), o None si está todo listo."""
    if not _token_key(optional=True):
        return 'Falta BACKUP_TOKEN_KEY en el servidor (clave que cifra el acceso a Google Drive).'
    if not app_config(c):
        return 'Falta configurar el cliente OAuth de Google (paso 1 del asistente).'
    link = bk.get_state(c, 'gdrive_link')
    if not link:
        return 'Conecta Google Drive (paso 2 del asistente).'
    if link.get('status') == 'vencida':
        return 'La conexión con Google Drive venció: vuelve a conectarla.'
    if not encryption_ready():
        return 'Falta BACKUP_ENCRYPTION_KEY en el servidor (clave que cifra los respaldos).'
    return None


# ---------------------------------------------------------------- HTTP con reintentos controlados
class GoogleError(BackupError):
    def __init__(self, status, body):
        try:
            detail = json.loads(body or b'{}')
        except ValueError:
            detail = {}
        error = detail.get('error')
        self.code = (error.get('status') or str(error.get('code', ''))) if isinstance(error, dict) else (error or '')
        self.description = (error.get('message') if isinstance(error, dict) else detail.get('error_description')) or ''
        super().__init__('Google respondió %s%s.' % (status, (' (' + self.code + ')') if self.code else ''), 502)
        self.http_status = status


def http(method, url, data=None, headers=None, token=None, timeout=60, attempts=4, expect=(200, 201, 204)):
    last = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=data, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if token:
            request.add_unredirected_header('Authorization', 'Bearer ' + token)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            body = error.read()
            error.close()
            if error.code in expect:
                return error.code, dict(error.headers), body
            if error.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                wait = error.headers.get('Retry-After')
                time.sleep(min(30, float(wait)) if wait and wait.replace('.', '', 1).isdigit() else 2 ** attempt)
                last = error
                continue
            raise GoogleError(error.code, body) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            last = error
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
    raise BackupError('Sin conexión con Google: ' + type(last).__name__ + '.', 502)


def _json(response):
    return json.loads(response[2] or b'{}')


def explain(code, description=''):
    text = (code or '') + ' ' + (description or '')
    if 'invalid_client' in text or 'unauthorized_client' in text:
        return 'Google rechazó el cliente OAuth: revisa el ID de cliente y el secreto del paso 1.'
    if 'redirect_uri_mismatch' in text:
        return 'La URI de redirección no coincide: en Google Cloud debe estar exactamente ' + redirect_uri()
    if 'access_denied' in text:
        return 'No se concedió el permiso en Google. Vuelve a conectar y pulsa «Continuar» / «Permitir».'
    if 'invalid_grant' in text:
        return 'Google dio por vencido el acceso (se revocó, cambió la contraseña o la app sigue en modo «Prueba», que lo caduca a los 7 días). Vuelve a conectar Google Drive.'
    if 'org_internal' in text or 'admin_policy_enforced' in text:
        return 'La organización de Google no permite esta aplicación para esa cuenta.'
    return 'Google respondió: ' + (code or 'error') + ((' — ' + description[:160]) if description else '')


# ---------------------------------------------------------------- OAuth 2.0 con PKCE (asistente, paso 2)
def start_link(c, user_id):
    config = app_config(c)
    if not config or not _token_key(optional=True):
        raise BackupError('Primero completa el paso 1 del asistente: el cliente OAuth de Google.', 409)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    bk.set_state(c, 'gdrive_oauth', {'state': hashlib.sha256(state.encode()).hexdigest(), 'verifier': seal(verifier), 'user_id': user_id,
                                     'expires': (bk.now() + timedelta(minutes=10)).isoformat(timespec='seconds')})
    c.commit()
    query = urllib.parse.urlencode({'client_id': config['client_id'], 'redirect_uri': redirect_uri(), 'response_type': 'code', 'scope': SCOPE,
                                    'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'false', 'state': state,
                                    'code_challenge': challenge, 'code_challenge_method': 'S256'})
    return accounts_base() + '/o/oauth2/v2/auth?' + query


def _token_request(c, fields):
    config = app_config(c)
    if not config:
        raise BackupError('Falta la configuración del cliente OAuth de Google.', 409)
    body = urllib.parse.urlencode(dict(fields, client_id=config['client_id'], client_secret=config['secret'])).encode()
    return _json(http('POST', oauth_base() + '/token', body, {'Content-Type': 'application/x-www-form-urlencoded'}, attempts=3))


def finish_link(c, state, code):
    """Vuelta desde Google. Se autentica con el «state» (aleatorio, de un solo uso, 10 minutos, ligado al administrador)."""
    pending = bk.get_state(c, 'gdrive_oauth')
    c.execute("DELETE FROM system_state WHERE key='gdrive_oauth'")
    c.commit()
    if not pending or not state or not hmac.compare_digest(pending.get('state', ''), hashlib.sha256(state.encode()).hexdigest()):
        raise BackupError('La solicitud de conexión no es válida o ya se usó. Vuelve a intentarlo desde Configuración → Respaldos.', 400)
    if pending.get('expires', '') < bk.stamp():
        raise BackupError('La conexión tardó demasiado (más de 10 minutos). Vuelve a intentarlo.', 400)
    user = c.execute("SELECT id,role FROM users WHERE id=? AND active=1", (pending.get('user_id'),)).fetchone()
    if not user or user['role'] != 'administrador':
        raise BackupError('Solo administración puede conectar Google Drive.', 403)
    try:
        tokens = _token_request(c, {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri(), 'code_verifier': unseal(pending['verifier'])})
    except GoogleError as error:
        raise BackupError(explain(error.code, error.description), 400) from None
    access, refresh = tokens.get('access_token'), tokens.get('refresh_token')
    if not access:
        raise BackupError('Google no entregó el acceso. Revisa el cliente OAuth del paso 1.', 502)
    if not refresh:
        raise BackupError('Google no entregó un acceso permanente. Quita el acceso de «Órdenes Pro» en tu cuenta de Google (Seguridad → Apps con acceso) y vuelve a conectar.', 502)
    granted = set((tokens.get('scope') or SCOPE).split())
    if SCOPE not in granted:
        raise BackupError('No se concedió el permiso de Google Drive. Vuelve a conectar y marca la casilla de Drive.', 400)
    about = drive_about(access)
    folder = ensure_folder(access)
    link = {'status': 'vinculado', 'account': (about.get('user') or {}).get('emailAddress', ''), 'name': (about.get('user') or {}).get('displayName', ''),
            'linked_at': bk.stamp(), 'linked_by': user['id'], 'refresh': seal(refresh), 'folder_id': folder['id'], 'folder': FOLDER,
            'quota': about.get('storageQuota') or {}, 'checked_at': bk.stamp(), 'error': ''}
    bk.set_state(c, 'gdrive_link', link)
    c.commit()
    return link


def unlink(c):
    """Quita el acceso guardado. Los respaldos ya subidos se quedan en Google Drive."""
    c.execute("DELETE FROM system_state WHERE key IN ('gdrive_link','gdrive_oauth')")
    c.commit()


def access_token(c):
    link = bk.get_state(c, 'gdrive_link')
    if not link or not link.get('refresh'):
        raise BackupError('Google Drive no está conectado.', 409)
    try:
        tokens = _token_request(c, {'grant_type': 'refresh_token', 'refresh_token': unseal(link['refresh'])})
    except GoogleError as error:
        if error.code in ('invalid_grant', 'unauthorized_client') or error.http_status in (400, 401):
            link.update(status='vencida', error=explain(error.code, error.description), checked_at=bk.stamp())
            bk.set_state(c, 'gdrive_link', link)
            c.commit()
            raise BackupError('La conexión con Google Drive venció: hay que volver a conectarla en Configuración → Respaldos.', 409) from None
        raise
    if tokens.get('refresh_token'):
        link['refresh'] = seal(tokens['refresh_token'])
    link.update(status='vinculado', error='', checked_at=bk.stamp())
    bk.set_state(c, 'gdrive_link', link)
    c.commit()
    return tokens['access_token']


# ---------------------------------------------------------------- operaciones en Google Drive (solo archivos creados por la aplicación)
def drive_about(token):
    return _json(http('GET', api_base() + '/drive/v3/about?fields=' + urllib.parse.quote('user(emailAddress,displayName),storageQuota(limit,usage)'), token=token))


def _q(text):
    return text.replace('\\', '\\\\').replace("'", "\\'")


def ensure_folder(token):
    """Crea PC-DOCTOR S.A./Órdenes Pro/Respaldos Base de Datos si falta (nivel a nivel) y devuelve la carpeta final."""
    parent = 'root'
    item = None
    for name in FOLDER.split('/'):
        query = "name='%s' and mimeType='%s' and '%s' in parents and trashed=false" % (_q(name), FOLDER_MIME, parent)
        found = _json(http('GET', api_base() + '/drive/v3/files?' + urllib.parse.urlencode({'q': query, 'fields': 'files(id,name)', 'spaces': 'drive'}), token=token)).get('files') or []
        if found:
            item = found[0]
        else:
            item = _json(http('POST', api_base() + '/drive/v3/files?fields=id,name', json.dumps({'name': name, 'mimeType': FOLDER_MIME, 'parents': [parent]}).encode(),
                              {'Content-Type': 'application/json'}, token=token))
        parent = item['id']
    return item


def upload(token, folder_id, name, payload, sha256):
    """Subida reanudable por partes. Devuelve el archivo con el tamaño y el SHA-256 que calcula el propio Google."""
    meta = json.dumps({'name': name, 'parents': [folder_id], 'mimeType': 'application/octet-stream',
                       'description': 'Respaldo cifrado de Órdenes Pro (AES-256-GCM). Se recupera con la clave de respaldos.',
                       'appProperties': {'ordenes_pro': '1', 'sha256': sha256}}).encode()
    status, headers, _ = http('POST', api_base() + '/upload/drive/v3/files?uploadType=resumable&fields=id,name,size,sha256Checksum,md5Checksum', meta,
                              {'Content-Type': 'application/json; charset=UTF-8', 'X-Upload-Content-Type': 'application/octet-stream', 'X-Upload-Content-Length': str(len(payload))}, token=token)
    location = headers.get('Location') or headers.get('location')
    if not location:
        raise BackupError('Google no abrió la sesión de subida.', 502)
    total = len(payload)
    item = None
    for start in range(0, total, CHUNK):
        part = payload[start:start + CHUNK]
        status, _, body = http('PUT', location, part, {'Content-Length': str(len(part)), 'Content-Range': 'bytes %d-%d/%d' % (start, start + len(part) - 1, total)},
                               token=token, timeout=180, expect=(200, 201, 308))
        if status in (200, 201):
            item = json.loads(body)
    if not item or int(item.get('size', -1)) != total:
        raise BackupError('Google Drive no confirmó la subida completa del respaldo.', 502)
    return item


def file_info(token, file_id):
    return _json(http('GET', api_base() + '/drive/v3/files/' + urllib.parse.quote(file_id) + '?fields=id,name,size,sha256Checksum,trashed', token=token))


def list_backups(token, folder_id):
    items, page = [], None
    while True:
        params = {'q': "'%s' in parents and trashed=false" % folder_id, 'fields': 'nextPageToken,files(id,name,size,createdTime)', 'pageSize': '200', 'spaces': 'drive'}
        if page:
            params['pageToken'] = page
        data = _json(http('GET', api_base() + '/drive/v3/files?' + urllib.parse.urlencode(params), token=token))
        items += [f for f in data.get('files', []) if f.get('name', '').startswith(bk.PREFIX) and f['name'].endswith(bk.SUFFIXES)]
        page = data.get('nextPageToken')
        if not page:
            return sorted(items, key=lambda f: f['name'])


def download(token, file_id):
    return http('GET', api_base() + '/drive/v3/files/' + urllib.parse.quote(file_id) + '?alt=media', token=token, timeout=180)[2]


def trash(token, file_id):
    """A la papelera de Google Drive (recuperable allí 30 días), nunca borrado definitivo."""
    http('PATCH', api_base() + '/drive/v3/files/' + urllib.parse.quote(file_id) + '?fields=id', json.dumps({'trashed': True}).encode(), {'Content-Type': 'application/json'}, token=token)


# ---------------------------------------------------------------- operaciones del panel y de la tarea programada (en el servidor)
def check_connection(c):
    """«Verificar conexión»: cuenta, espacio y carpeta, consultados en Google en este momento."""
    token = access_token(c)
    about = drive_about(token)
    link = bk.get_state(c, 'gdrive_link') or {}
    link.update(quota=about.get('storageQuota') or {}, account=(about.get('user') or {}).get('emailAddress', link.get('account', '')), checked_at=bk.stamp())
    bk.set_state(c, 'gdrive_link', link)
    c.commit()
    return link


def create_folder(c):
    token = access_token(c)
    folder = ensure_folder(token)
    link = bk.get_state(c, 'gdrive_link') or {}
    link.update(folder_id=folder['id'], folder=FOLDER, checked_at=bk.stamp())
    bk.set_state(c, 'gdrive_link', link)
    c.commit()
    return link


def request_run(c, user_id, kind, file=''):
    """Respaldo, verificación de integridad o restauración de prueba, ejecutados en el servidor (función de hasta 300 s)."""
    if kind not in bk.RUN_KINDS:
        raise BackupError('Operación de respaldo no válida.', 400)
    if kind != 'respaldo' and not any(item.get('file') == file and item.get('status') in ('correcto', 'incompleto') and item.get('destination') == 'gdrive' for item in bk.runs(c)):
        raise BackupError('Elige un respaldo de Google Drive verificado del historial.', 400)
    problem = not_ready(c)
    if problem:
        raise BackupError(problem, 409)
    lock = bk.get_state(c, 'backup_lock')
    if lock and lock.get('until', '') > bk.stamp():
        raise BackupError('Ya hay un respaldo o una verificación en curso. Espera a que termine.', 409)
    import backup_runner
    try:
        if kind == 'respaldo':
            return backup_runner.drive_backup('manual', user_id)
        return backup_runner.drive_verify(kind, file, 'manual', user_id)
    except backup_runner.KeyMissing as error:
        raise BackupError(str(error), 409) from None
    except BackupError:
        raise
    except Exception as error:
        raise BackupError('El respaldo falló: ' + type(error).__name__ + ': ' + str(error)[:200], 502) from None


def verified_today(c, moment=None):
    moment = moment or bk.now()
    return any(item.get('destination') == 'gdrive' and item.get('kind') == 'respaldo' and item.get('status') in ('correcto', 'incompleto') and item.get('verified')
               and (item.get('finished_at') or '')[:10] == moment.date().isoformat() for item in bk.runs(c))


def scheduled(c, attempt=1, moment=None):
    """Tarea programada (02:00) y reintentos (04:00 y 07:00). Los reintentos solo actúan si el respaldo del día no quedó verificado.
    Sin Google Drive listo NO registra un respaldo en la nube: anota por qué no se hizo. Una vez por semana, restauración de prueba."""
    moment = moment or bk.now()
    outcome = {'at': bk.stamp(), 'attempt': attempt}
    problem = not_ready(c)
    if attempt > 1 and verified_today(c, moment):
        outcome.update(status='innecesario', detail='El respaldo de hoy ya está verificado.')
    elif problem:
        outcome.update(status='omitido', detail=problem)
    else:
        import backup_runner
        try:
            run = backup_runner.drive_backup('programado' if attempt == 1 else 'reintento')
            outcome.update(status=run['status'], detail=run.get('file', ''), run=run['id'])
        except Exception as error:
            outcome.update(status='error', detail=(str(error) or type(error).__name__)[:200])
        if outcome['status'] == 'correcto':
            try:
                backup_runner.weekly_restore_test()
            except Exception:
                pass
    bk.set_state(c, 'backup_cron', outcome)
    c.commit()
    return outcome


def next_retry(c, moment=None):
    """Próximo reintento automático si el respaldo de hoy todavía no está verificado (para el indicador de pendientes)."""
    moment = moment or bk.now()
    if verified_today(c, moment) or moment.hour < bk.SCHEDULE_HOUR:
        return None
    for hour in RETRY_HOURS:
        target = moment.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target > moment:
            return target.isoformat(timespec='seconds')
    return None


# ---------------------------------------------------------------- estado para el panel y alertas
def overview(c):
    link = bk.get_state(c, 'gdrive_link') or {}
    # Proveedores retirados (MEGA, OneDrive): lo que quedó «pendiente» ya no se subirá. Se muestra tal cual, sin contarlo como pendiente
    # ni modificar el registro: «No subido (proveedor retirado)», con su copia cifrada todavía en el equipo de la oficina.
    items = [dict(item, status='retirado', error='Proveedor ' + {'mega': 'MEGA', 'onedrive': 'OneDrive'}[item['destination']] + ' retirado antes de subirlo. La copia cifrada sigue en el equipo de la oficina y la copia local está verificada.')
             if item.get('destination') in ('mega', 'onedrive') and item.get('status') in ('pendiente', 'en_curso') else item for item in bk.runs(c)]
    config = app_config(c)
    saved = bk.get_state(c, 'gdrive_app') or {}
    legacy = bk.get_state(c, 'cloud_backup')
    history = list(items)
    local = next((item for item in items if item.get('destination') == 'equipo' and item.get('kind') == 'respaldo' and item.get('status') == 'correcto'), None)
    if legacy and legacy.get('ok') and legacy.get('destination') not in ('onedrive', 'mega', 'gdrive') and not any(item.get('sha256') and item.get('sha256') == legacy.get('sha256') for item in items):
        entry = bk._legacy_entry(legacy)
        history.append(entry)
        history.sort(key=lambda item: item.get('requested_at') or item.get('finished_at') or '', reverse=True)
        if not local or entry['finished_at'] > (local.get('finished_at') or ''):
            local = entry
    drive_ok = next((item for item in items if item.get('destination') == 'gdrive' and item.get('kind') == 'respaldo' and item.get('status') == 'correcto' and item.get('verified') and (item.get('complete') or not item.get('full'))), None)
    full_ok = next((item for item in items if item.get('destination') == 'gdrive' and item.get('kind') == 'respaldo' and item.get('status') == 'correcto' and item.get('complete')), None)
    running = next((item for item in items if item.get('status') == 'en_curso'), None)
    restore = next((item for item in items if item.get('destination') == 'gdrive' and item.get('kind') == 'restauracion' and item.get('status') in ('correcto', 'error')), None)
    last_drive = next((item for item in items if item.get('destination') == 'gdrive' and item.get('kind') == 'respaldo'), None)
    public_link = {key: link.get(key) for key in ('status', 'account', 'name', 'linked_at', 'checked_at', 'error', 'folder', 'quota')} if link else None
    import remote_db
    return {'configured': configured(c), 'ready': not_ready(c), 'link': public_link, 'folder': FOLDER, 'scope': SCOPE,
            'app': {'source': config['source'], 'client_id': config['client_id'], 'saved_at': config.get('saved_at', ''), 'has_secret': True} if config else ({'source': 'panel', 'client_id': saved.get('client_id', ''), 'has_secret': False} if saved else None),
            'central': {'engine': 'Turso (libSQL), base central en la nube' if remote_db.configured() else 'SQLite local de este equipo', 'remote': remote_db.configured()},
            'last_local': local, 'last_drive': drive_ok, 'last_full': full_ok, 'last_attempt': last_drive, 'running': running, 'last_restore': restore,
            'protected': bool(drive_ok), 'complete': bool(full_ok), 'cron': bk.get_state(c, 'backup_cron'),
            'next_run': bk.next_run().isoformat(timespec='seconds'), 'next_retry': next_retry(c), 'retry_hours': list(RETRY_HOURS),
            'busy': bool((bk.get_state(c, 'backup_lock') or {}).get('until', '') > bk.stamp()), 'keep': bk.KEEP, 'runs': history[:60],
            'redirect_uri': redirect_uri()}


def alerts(c, moment=None):
    """Alertas reales y separadas; se retiran solas cuando se corrige la causa."""
    moment = moment or bk.now()
    out = []
    good = bk.last_good(c)
    try:
        age = (moment - datetime.fromisoformat(good['finished_at'])).total_seconds() / 3600 if good and good.get('finished_at') else None
    except ValueError:
        age = None
    if age is None or age > bk.LATE_HOURS:
        out.append({'key': 'backup:late:' + moment.date().isoformat(), 'kind': 'warning', 'title': 'Respaldo de la base central atrasado',
                    'detail': ('El último respaldo correcto y verificado es del ' + good['finished_at'][:10] + '.') if good else 'Todavía no se registra ningún respaldo correcto y verificado.'})
    latest = next((item for item in bk.runs(c) if item.get('destination') == 'gdrive' and item.get('kind') == 'respaldo' and item.get('status') in ('correcto', 'error', 'incompleto')), None)
    if latest and latest['status'] == 'error':
        out.append({'key': 'backup:failed:' + latest['id'], 'kind': 'warning', 'title': 'Falló el último respaldo en Google Drive', 'detail': (latest.get('error') or 'Error sin detalle.')[:180]})
    elif latest and latest['status'] == 'incompleto':
        out.append({'key': 'backup:incomplete:' + latest['id'], 'kind': 'warning', 'title': 'El último respaldo no es completo',
                    'detail': 'La base quedó respaldada y verificada, pero ' + (latest.get('error') or 'falta una parte').replace('Falta: ', 'falta: ')[:170]})
    link = bk.get_state(c, 'gdrive_link')
    if link and link.get('status') == 'vencida':
        out.append({'key': 'backup:expired:' + (link.get('checked_at') or '')[:10], 'kind': 'warning', 'title': 'Conexión con Google Drive vencida',
                    'detail': 'Vuelve a conectar Google Drive en Configuración → Respaldos para reanudar las copias en la nube.'})
    elif not link:
        out.append({'key': 'backup:unlinked', 'kind': 'info', 'title': 'Respaldos sin copia en Google Drive',
                    'detail': 'Conecta Google Drive en Configuración → Respaldos. Hasta entonces solo existe la copia local de la oficina.'})
    quota = (link or {}).get('quota') or {}
    try:
        if quota.get('limit') and int(quota.get('usage', 0)) / int(quota['limit']) >= bk.SPACE_WARN:
            out.append({'key': 'backup:space:' + moment.date().isoformat(), 'kind': 'warning', 'title': 'Espacio en Google Drive casi lleno',
                        'detail': 'Ocupado el %d %% de la cuenta de Google.' % round(100 * int(quota['usage']) / int(quota['limit']))})
    except (TypeError, ValueError):
        pass
    return out
