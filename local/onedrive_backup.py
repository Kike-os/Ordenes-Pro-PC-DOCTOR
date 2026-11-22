"""Respaldos automáticos en Microsoft OneDrive — 1.5.310.

Todo ocurre en el servidor (Vercel), sin depender del navegador ni del equipo de la oficina:
  · Asistente en Configuración → Respaldos: paso 1, datos de la aplicación registrada en Microsoft (Id. de aplicación, tipo de cuenta y
    secreto, guardado CIFRADO en la base; nunca vuelve al navegador); paso 2, «Conectar Microsoft OneDrive» (OAuth 2.0 + PKCE); paso 3,
    respaldo de prueba con verificación.
  · Tarea programada /api/cron/backup a las 02:00 de Ecuador y «Realizar respaldo ahora»: función propia de hasta 300 s (backup_runner).
  · Admite cuentas personales o familiares (consumers), de empresa (directorio concreto) o ambas (common).

Permisos de Microsoft Graph (delegados, de la cuenta que se conecta): offline_access, User.Read y Files.ReadWrite. El código solo usa la
carpeta PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos.

Claves en el servidor (variables de entorno, nunca en el navegador):
  ONEDRIVE_TOKEN_KEY      32 bytes en base64: cifra el secreto de la aplicación y el token de actualización guardados en la base
  BACKUP_ENCRYPTION_KEY   32 bytes en base64: cifra cada respaldo (AES-256-GCM); guarda una copia offline: sin ella no hay recuperación
  MS_CLIENT_ID, MS_CLIENT_SECRET, MS_TENANT_ID   opcionales: si existen, mandan sobre lo guardado desde el asistente
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

ECUADOR = timezone(timedelta(hours=-5))
SCOPES = 'offline_access User.Read Files.ReadWrite'
FOLDER = 'PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos'
PREFIX = 'ordenes-pro-'
SUFFIX = '.sqlite.gz.enc'
SCHEDULE_HOUR = 2                      # 02:00, hora de Ecuador (07:00 UTC en el flujo de GitHub)
LATE_HOURS = 30                        # un respaldo diario + margen por el retraso habitual de las tareas programadas de GitHub
KEEP = {'diario': 30, 'semanal': 12, 'mensual': 12}
MAX_RUNS = 200
CHUNK = 320 * 1024 * 12                # 3,75 MiB: múltiplo de 320 KiB, como exige la subida por partes de OneDrive
RUN_KINDS = {'respaldo': 'Respaldo', 'verificacion': 'Verificación', 'restauracion': 'Restauración de prueba'}
STATUS = {'solicitado': 'Solicitado', 'en_curso': 'En ejecución', 'correcto': 'Correcto', 'error': 'Error'}


class BackupError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(ECUADOR)


def stamp(moment=None):
    return (moment or now()).isoformat(timespec='seconds')


def graph_base():
    return os.getenv('GRAPH_BASE', 'https://graph.microsoft.com/v1.0').rstrip('/')


def login_base():
    return os.getenv('MS_LOGIN_BASE', 'https://login.microsoftonline.com').rstrip('/')


ACCOUNT_TYPES = {'personal': ('consumers', 'Personal o Familiar (Microsoft 365 Personal/Familia, @outlook, @hotmail)'),
                 'empresa': ('', 'Empresa (cuenta de trabajo de un directorio concreto)'),
                 'ambas': ('common', 'Personal y empresa')}
GUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')


def app_config(c=None):
    """Aplicación de Microsoft: variables del servidor (prioridad) o la configuración guardada CIFRADA desde el asistente del panel.
    El secreto solo se descifra aquí, en memoria del servidor; nunca viaja al navegador."""
    if os.getenv('MS_CLIENT_ID', '').strip() and os.getenv('MS_CLIENT_SECRET', '').strip():
        return {'client_id': os.environ['MS_CLIENT_ID'].strip(), 'secret': os.environ['MS_CLIENT_SECRET'].strip(),
                'tenant': os.getenv('MS_TENANT_ID', '').strip() or 'common', 'source': 'servidor'}
    if c is None:
        return None
    saved = get_state(c, 'onedrive_app')
    if not saved or not saved.get('client_id') or not saved.get('secret'):
        return None
    try:
        secret = unseal(saved['secret'])
    except BackupError:
        return None
    return {'client_id': saved['client_id'], 'secret': secret, 'tenant': saved.get('tenant') or 'common', 'source': 'panel',
            'account_type': saved.get('account_type', ''), 'saved_at': saved.get('saved_at', '')}


def tenant(c=None):
    config = app_config(c)
    return (config or {}).get('tenant') or 'common'


def configured(c=None):
    """La aplicación de Microsoft está registrada y hay clave para guardar el token cifrado."""
    return bool(_token_key(optional=True) and app_config(c))


def save_app_config(c, data, user_id):
    """Paso 1 del asistente. Valida el formato; el secreto se guarda cifrado y, si se deja en blanco, se conserva el anterior."""
    if os.getenv('MS_CLIENT_ID', '').strip():
        raise BackupError('La aplicación de Microsoft está definida en las variables del servidor; no se cambia desde el panel.', 409)
    if not _token_key(optional=True):
        raise BackupError('Falta ONEDRIVE_TOKEN_KEY en el servidor: sin ella no se puede guardar el secreto cifrado.', 500)
    client_id = str(data.get('client_id', '')).strip()
    kind = str(data.get('account_type', '')).strip()
    secret = str(data.get('client_secret', '')).strip()
    errors = {}
    if not GUID.fullmatch(client_id):
        errors['client_id'] = 'Copia el «Id. de aplicación (cliente)»: tiene la forma 12345678-abcd-…'
    if kind not in ACCOUNT_TYPES:
        errors['account_type'] = 'Elige el tipo de cuenta de OneDrive.'
    tenant_value = ACCOUNT_TYPES.get(kind, ('',))[0]
    if kind == 'empresa':
        tenant_value = str(data.get('tenant_id', '')).strip()
        if not (GUID.fullmatch(tenant_value) or re.fullmatch(r'[a-z0-9-]+(\.[a-z0-9-]+)+', tenant_value.lower())):
            errors['tenant_id'] = 'Copia el «Id. de directorio (inquilino)» de tu empresa.'
    previous = get_state(c, 'onedrive_app') or {}
    if not secret and not previous.get('secret'):
        errors['client_secret'] = 'Pega el «Valor» del secreto de cliente.'
    elif secret and not (16 <= len(secret) <= 256) or any(ch.isspace() for ch in secret):
        errors['client_secret'] = 'El secreto no tiene el formato esperado: copia el «Valor», no el «Id. del secreto».'
    if errors:
        error = BackupError(next(iter(errors.values())) if len(errors) == 1 else 'Revisa los datos señalados.', 400)
        error.fields = errors
        raise error
    changed = previous.get('client_id') != client_id or previous.get('tenant') != tenant_value
    set_state(c, 'onedrive_app', {'client_id': client_id, 'tenant': tenant_value, 'account_type': kind,
                                  'secret': seal(secret) if secret else previous['secret'], 'saved_at': stamp(), 'saved_by': user_id})
    if changed:
        # Otra aplicación u otro tipo de cuenta: el acceso anterior deja de valer y hay que volver a conectar.
        c.execute("DELETE FROM system_state WHERE key IN ('onedrive_link','onedrive_oauth')")
    c.commit()
    return changed


def clear_app_config(c):
    c.execute("DELETE FROM system_state WHERE key IN ('onedrive_app','onedrive_link','onedrive_oauth')")
    c.commit()


def not_ready(c):
    """Por qué todavía no se puede respaldar en OneDrive (texto para el panel), o None si está todo listo."""
    if not _token_key(optional=True):
        return 'Falta ONEDRIVE_TOKEN_KEY en el servidor (clave que cifra el acceso a OneDrive).'
    if not app_config(c):
        return 'Falta configurar la aplicación de Microsoft (paso 1 del asistente).'
    link = get_state(c, 'onedrive_link')
    if not link:
        return 'Conecta Microsoft OneDrive (paso 2 del asistente).'
    if link.get('status') == 'vencida':
        return 'La conexión con OneDrive venció: vuelve a conectarla.'
    raw = os.getenv('BACKUP_ENCRYPTION_KEY', '').strip()
    try:
        ok = len(base64.b64decode(raw + '=' * (-len(raw) % 4))) == 32 if raw else False
    except ValueError:
        ok = False
    if not ok:
        return 'Falta BACKUP_ENCRYPTION_KEY en el servidor (clave que cifra los respaldos).'
    return None


def redirect_uri():
    return os.getenv('APP_URL', 'http://127.0.0.1:8010').rstrip('/') + '/api/backups/onedrive/callback'


# ---------------------------------------------------------------- cifrado del token (mismo esquema que los demás secretos del sistema)
def _token_key(optional=False):
    """Clave del token: ONEDRIVE_TOKEN_KEY (obligatoria en Vercel y en el generador); en el servidor local, una clave propia 0600."""
    raw = os.getenv('ONEDRIVE_TOKEN_KEY', '').strip()
    if raw:
        try:
            key = base64.b64decode(raw + '=' * (-len(raw) % 4))
        except ValueError:
            key = b''
        if len(key) == 32:
            return key
        if optional:
            return None
        raise BackupError('ONEDRIVE_TOKEN_KEY debe ser una clave de 32 bytes en base64.', 500)
    if os.getenv('VERCEL') or os.getenv('GITHUB_ACTIONS'):
        if optional:
            return None
        raise BackupError('Falta ONEDRIVE_TOKEN_KEY, la clave que cifra el acceso a OneDrive.', 500)
    return _local_key()


def _local_key():
    """Servidor local o pruebas: clave propia en la carpeta de datos, creada una sola vez con permisos 0600."""
    import app
    path = Path(app.DATA) / 'onedrive.key'
    if not path.exists():
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(secrets.token_bytes(32))
    return path.read_bytes()[:32]


def _keys():
    key = _token_key()
    return (hmac.new(key, b'ordenes-pro:onedrive:cifrado', hashlib.sha256).digest(),
            hmac.new(key, b'ordenes-pro:onedrive:autenticacion', hashlib.sha256).digest())


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
    tag = hmac.new(mac, b'od1' + nonce + body, hashlib.sha256).digest()
    return 'od1:' + base64.urlsafe_b64encode(nonce + body + tag).decode().rstrip('=')


def unseal(value):
    value = str(value or '')
    if not value.startswith('od1:'):
        raise BackupError('El acceso guardado a OneDrive no tiene un formato válido.', 500)
    raw = base64.urlsafe_b64decode(value[4:] + '=' * (-len(value[4:]) % 4))
    nonce, body, tag = raw[:16], raw[16:-32], raw[-32:]
    enc, mac = _keys()
    if not hmac.compare_digest(tag, hmac.new(mac, b'od1' + nonce + body, hashlib.sha256).digest()):
        raise BackupError('El acceso guardado a OneDrive no se pudo verificar (¿cambió ONEDRIVE_TOKEN_KEY?).', 500)
    return bytes(a ^ b for a, b in zip(body, _stream(enc, nonce, len(body)))).decode()


# ---------------------------------------------------------------- estado guardado en system_state
def get_state(c, key, default=None):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except ValueError:
        return default


def set_state(c, key, value):
    c.execute("INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))


def runs(c):
    value = get_state(c, 'backup_runs', [])
    return value if isinstance(value, list) else []


def save_run(c, run):
    """Añade o actualiza un registro del historial (el más reciente primero). Nunca borra respaldos: solo acota el historial visible."""
    items = [item for item in runs(c) if item.get('id') != run['id']]
    items.insert(0, run)
    items.sort(key=lambda item: item.get('requested_at') or item.get('started_at') or '', reverse=True)
    set_state(c, 'backup_runs', items[:MAX_RUNS])
    c.commit()
    return run


def find_run(c, run_id):
    return next((item for item in runs(c) if item.get('id') == run_id), None)


def new_run(kind, trigger, destination, requested_by=None, file=''):
    moment = stamp()
    return {'id': 'r' + now().strftime('%Y%m%d%H%M%S') + secrets.token_hex(3), 'kind': kind, 'trigger': trigger, 'destination': destination,
            'status': 'solicitado', 'requested_at': moment, 'requested_by': requested_by, 'started_at': '', 'finished_at': '', 'file': file,
            'bytes': 0, 'raw_bytes': 0, 'sha256': '', 'remote_id': '', 'tier': '', 'verified': False, 'verify': None, 'error': '', 'runner': ''}


def acquire_lock(c, owner, minutes=45):
    """Impide respaldos simultáneos: un único dueño hasta que termina o vence el plazo (si el proceso murió sin liberarlo)."""
    until = (now() + timedelta(minutes=minutes)).isoformat(timespec='seconds')
    c.execute("INSERT INTO system_state(key,value) VALUES ('backup_lock',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value "
              "WHERE json_extract(system_state.value,'$.until') < ? OR json_extract(system_state.value,'$.owner') = ?",
              (json.dumps({'owner': owner, 'until': until}), stamp(), owner))
    c.commit()
    current = get_state(c, 'backup_lock', {})
    return current.get('owner') == owner


def release_lock(c, owner):
    c.execute("DELETE FROM system_state WHERE key='backup_lock' AND json_extract(value,'$.owner')=?", (owner,))
    c.commit()


def busy(c):
    lock = get_state(c, 'backup_lock')
    if lock and lock.get('until', '') > stamp():
        return True
    limit = (now() - timedelta(minutes=40)).isoformat(timespec='seconds')
    return any(item.get('status') in ('solicitado', 'en_curso') and (item.get('requested_at') or '') > limit for item in runs(c))


# ---------------------------------------------------------------- HTTP con reintentos controlados
def http(method, url, data=None, headers=None, token=None, timeout=60, attempts=4, expect=(200, 201, 202, 204)):
    """Petición con reintentos ante fallos de red, 429 y 5xx (respeta Retry-After). Devuelve (estado, cabeceras, cuerpo)."""
    last = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=data, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if token:
            # «unredirected»: el token nunca viaja a la URL de descarga a la que redirige OneDrive.
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
            raise GraphError(error.code, body) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            last = error
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
                continue
    raise BackupError('Sin conexión con el servicio externo: ' + type(last).__name__ + '.', 502)


class GraphError(BackupError):
    def __init__(self, status, body):
        try:
            detail = json.loads(body or b'{}')
        except ValueError:
            detail = {}
        error = detail.get('error')
        self.code = (error.get('code') if isinstance(error, dict) else error) or ''
        self.description = (error.get('message') if isinstance(error, dict) else detail.get('error_description')) or ''
        super().__init__('Microsoft respondió %s%s.' % (status, (' (' + self.code + ')') if self.code else ''), 502)
        self.http_status = status


def _json(response):
    return json.loads(response[2] or b'{}')


# ---------------------------------------------------------------- OAuth 2.0 con PKCE
def start_link(c, user_id):
    config = app_config(c)
    if not config or not _token_key(optional=True):
        raise BackupError('Primero completa el paso 1 del asistente: los datos de la aplicación registrada en Microsoft.', 409)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    set_state(c, 'onedrive_oauth', {'state': hashlib.sha256(state.encode()).hexdigest(), 'verifier': seal(verifier), 'user_id': user_id,
                                    'expires': (now() + timedelta(minutes=10)).isoformat(timespec='seconds')})
    c.commit()
    query = urllib.parse.urlencode({'client_id': config['client_id'], 'response_type': 'code', 'redirect_uri': redirect_uri(),
                                    'response_mode': 'query', 'scope': SCOPES, 'state': state, 'code_challenge': challenge,
                                    'code_challenge_method': 'S256', 'prompt': 'select_account'})
    return login_base() + '/' + config['tenant'] + '/oauth2/v2.0/authorize?' + query


def _token_request(c, fields):
    config = app_config(c)
    if not config:
        raise BackupError('Falta la configuración de la aplicación de Microsoft.', 409)
    body = urllib.parse.urlencode(dict(fields, client_id=config['client_id'], client_secret=config['secret'], scope=SCOPES)).encode()
    return _json(http('POST', login_base() + '/' + config['tenant'] + '/oauth2/v2.0/token', body, {'Content-Type': 'application/x-www-form-urlencoded'}, attempts=3))


def finish_link(c, state, code):
    """Vuelta desde Microsoft. Se autentica con el «state» (aleatorio, de un solo uso, 10 minutos y ligado a quien inició la
    vinculación): la cookie de sesión es SameSite=Strict y el navegador no la envía en esta redirección entre sitios."""
    pending = get_state(c, 'onedrive_oauth')
    c.execute("DELETE FROM system_state WHERE key='onedrive_oauth'")
    c.commit()
    if not pending or not state or not hmac.compare_digest(pending.get('state', ''), hashlib.sha256(state.encode()).hexdigest()):
        raise BackupError('La solicitud de vinculación no es válida o ya se usó. Vuelve a intentarlo desde Configuración → Respaldos.', 400)
    if pending.get('expires', '') < stamp():
        raise BackupError('La vinculación tardó demasiado (más de 10 minutos). Vuelve a intentarlo.', 400)
    user = c.execute("SELECT id,role FROM users WHERE id=? AND active=1", (pending.get('user_id'),)).fetchone()
    if not user or user['role'] != 'administrador':
        raise BackupError('Solo administración puede vincular OneDrive.', 403)
    try:
        tokens = _token_request(c, {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri(), 'code_verifier': unseal(pending['verifier'])})
    except GraphError as error:
        raise BackupError(explain(error.code, error.description), 400) from None
    access, refresh = tokens.get('access_token'), tokens.get('refresh_token')
    if not access:
        raise BackupError('Microsoft no entregó el acceso. Revisa el Id. de aplicación, el secreto y el tipo de cuenta del paso 1.', 502)
    if not access or not refresh:
        raise BackupError('Microsoft no entregó un acceso permanente (falta offline_access).', 502)
    me = _json(http('GET', graph_base() + '/me?$select=displayName,userPrincipalName,mail', token=access))
    folder = ensure_folder(access)
    link = {'status': 'vinculado', 'account': me.get('mail') or me.get('userPrincipalName') or '', 'name': me.get('displayName') or '',
            'linked_at': stamp(), 'linked_by': user['id'], 'refresh': seal(refresh), 'folder_id': folder.get('id', ''), 'folder': FOLDER,
            'checked_at': stamp(), 'error': ''}
    set_state(c, 'onedrive_link', link)
    c.commit()
    return link


def unlink(c):
    """Quita el acceso guardado. Los respaldos ya subidos se quedan en OneDrive."""
    c.execute("DELETE FROM system_state WHERE key IN ('onedrive_link','onedrive_oauth')")
    c.commit()


def access_token(c):
    """Token de acceso a partir del de actualización guardado; si Microsoft lo rota, se guarda el nuevo (cifrado)."""
    link = get_state(c, 'onedrive_link')
    if not link or not link.get('refresh'):
        raise BackupError('OneDrive no está vinculado.', 409)
    try:
        tokens = _token_request(c, {'grant_type': 'refresh_token', 'refresh_token': unseal(link['refresh'])})
    except GraphError as error:
        if error.code in ('invalid_grant', 'interaction_required', 'consent_required') or error.http_status in (400, 401):
            link.update(status='vencida', error='Microsoft rechazó el acceso guardado (' + (error.code or str(error.http_status)) + '). Vuelve a vincular la cuenta.', checked_at=stamp())
            set_state(c, 'onedrive_link', link)
            c.commit()
            raise BackupError('La conexión con OneDrive venció: hay que volver a vincular la cuenta en Configuración → Respaldos.', 409) from None
        raise
    if tokens.get('refresh_token') and tokens['refresh_token'] != link.get('refresh'):
        link['refresh'] = seal(tokens['refresh_token'])
    link.update(status='vinculado', error='', checked_at=stamp())
    set_state(c, 'onedrive_link', link)
    c.commit()
    return tokens['access_token']


# ---------------------------------------------------------------- operaciones en OneDrive (solo dentro de la carpeta de respaldos)
def _path(*parts):
    return urllib.parse.quote('/'.join(p.strip('/') for p in parts if p), safe='/')


def ensure_folder(token):
    """Crea PC-DOCTOR S.A./Ordenes Pro/Respaldos Base de Datos si falta (nivel a nivel) y devuelve la carpeta final."""
    parent = 'root'
    item = None
    done = []
    for name in FOLDER.split('/'):
        done.append(name)
        status, _, body = http('GET', graph_base() + '/me/drive/root:/' + _path(*done), token=token, expect=(200, 404))
        if status == 200:
            item = json.loads(body)
        else:
            payload = json.dumps({'name': name, 'folder': {}, '@microsoft.graph.conflictBehavior': 'fail'}).encode()
            status, _, body = http('POST', graph_base() + '/me/drive/items/' + parent + '/children', payload, {'Content-Type': 'application/json'}, token=token, expect=(201, 409))
            if status == 409:
                item = _json(http('GET', graph_base() + '/me/drive/root:/' + _path(*done), token=token))
            else:
                item = json.loads(body)
        parent = item['id']
    return item


def upload(token, name, payload):
    """Subida por partes (sesión de carga). Falla si ya existe un archivo con ese nombre: nunca reemplaza un respaldo."""
    session = _json(http('POST', graph_base() + '/me/drive/root:/' + _path(FOLDER, name) + ':/createUploadSession',
                         json.dumps({'item': {'@microsoft.graph.conflictBehavior': 'fail', 'name': name}}).encode(), {'Content-Type': 'application/json'}, token=token))
    url = session['uploadUrl']
    total = len(payload)
    item = None
    for start in range(0, total, CHUNK):
        part = payload[start:start + CHUNK]
        # La URL de la sesión ya está autorizada: no lleva el token.
        status, _, body = http('PUT', url, part, {'Content-Length': str(len(part)), 'Content-Range': 'bytes %d-%d/%d' % (start, start + len(part) - 1, total)}, timeout=120)
        if status in (200, 201):
            item = json.loads(body)
    if not item or int(item.get('size', -1)) != total:
        raise BackupError('OneDrive no confirmó la subida completa del respaldo.', 502)
    return item


def list_backups(token):
    items = []
    url = graph_base() + '/me/drive/root:/' + _path(FOLDER) + ':/children?$select=id,name,size,createdDateTime,file&$top=200'
    while url:
        page = _json(http('GET', url, token=token))
        items += [item for item in page.get('value', []) if item.get('name', '').startswith(PREFIX) and item['name'].endswith(SUFFIX)]
        url = page.get('@odata.nextLink')
    return sorted(items, key=lambda item: item['name'])


def download(token, item_id):
    return http('GET', graph_base() + '/me/drive/items/' + urllib.parse.quote(item_id) + '/content', token=token, timeout=180)[2]


def delete(token, item_id):
    """Va a la papelera de OneDrive (recuperable allí durante el plazo que fije Microsoft 365)."""
    http('DELETE', graph_base() + '/me/drive/items/' + urllib.parse.quote(item_id), token=token, expect=(204, 404))


# ---------------------------------------------------------------- nombres y retención 30 diarios / 12 semanales / 12 mensuales
def tier(moment):
    if moment.day == 1:
        return 'mensual'
    if moment.isoweekday() == 1:
        return 'semanal'
    return 'diario'


def file_name(moment):
    return PREFIX + moment.strftime('%Y%m%d-%H%M%S') + '-' + tier(moment) + SUFFIX


def moment_of(name):
    try:
        return datetime.strptime(name[len(PREFIX):len(PREFIX) + 15], '%Y%m%d-%H%M%S').replace(tzinfo=ECUADOR)
    except ValueError:
        return None


def retention(names):
    """Esquema abuelo-padre-hijo sobre las fechas (no sobre la etiqueta): se conserva el último respaldo de cada uno de los 30 días,
    12 semanas ISO y 12 meses más recientes que tengan respaldo. Devuelve los nombres que sobran; nunca toca archivos ajenos."""
    dated = sorted(((moment_of(n), n) for n in names if n.startswith(PREFIX) and n.endswith(SUFFIX) and moment_of(n)), reverse=True)
    keep = set()
    for key, limit in ((lambda m: m.date(), KEEP['diario']), (lambda m: m.isocalendar()[:2], KEEP['semanal']), (lambda m: (m.year, m.month), KEEP['mensual'])):
        seen = []
        for moment, name in dated:
            k = key(moment)
            if k in seen:
                continue
            seen.append(k)
            if len(seen) > limit:
                break
            keep.add(name)
    return [name for _, name in dated if name not in keep]


def next_run(moment=None):
    moment = moment or now()
    target = moment.replace(hour=SCHEDULE_HOUR, minute=0, second=0, microsecond=0)
    return target if target > moment else target + timedelta(days=1)


# ---------------------------------------------------------------- errores de Microsoft explicados
def explain(code, description=''):
    text = (code or '') + ' ' + (description or '')
    if 'invalid_client' in text or 'AADSTS7000215' in text:
        return 'Microsoft rechazó el secreto de cliente: copia el «Valor» del secreto (no su Id.) o crea uno nuevo, y guárdalo en el paso 1.'
    if 'unauthorized_client' in text or 'AADSTS700016' in text or 'not enabled for consumers' in text:
        return 'La aplicación registrada no admite este tipo de cuenta. En Microsoft, «Tipos de cuenta admitidos» debe coincidir con el tipo elegido en el paso 1.'
    if 'AADSTS50011' in text or 'redirect_uri' in text:
        return 'La dirección de retorno no coincide: en Microsoft debe estar exactamente ' + redirect_uri()
    if 'AADSTS50020' in text:
        return 'La cuenta no pertenece al directorio indicado: revisa el tipo de cuenta del paso 1 (para cuentas @outlook o @hotmail elige «Personal o Familiar»).'
    if 'invalid_grant' in text:
        return 'La autorización caducó o ya se usó. Vuelve a pulsar «Conectar Microsoft OneDrive».'
    if 'access_denied' in text or 'consent' in text:
        return 'No se concedió el permiso en Microsoft. Vuelve a conectar y pulsa «Aceptar».'
    return 'Microsoft respondió: ' + (code or 'error') + ((' — ' + description[:160]) if description else '')


# ---------------------------------------------------------------- respaldo, verificación o restauración aislada, en el servidor
def request_run(c, user_id, kind, file=''):
    """Se ejecuta en el propio servidor (función de hasta 300 s): no depende del navegador ni del equipo de la oficina."""
    if kind not in RUN_KINDS:
        raise BackupError('Operación de respaldo no válida.', 400)
    if kind != 'respaldo' and not any(item.get('file') == file and item.get('status') == 'correcto' and item.get('destination') == 'onedrive' for item in runs(c)):
        raise BackupError('Elige un respaldo correcto de OneDrive del historial.', 400)
    problem = not_ready(c)
    if problem:
        raise BackupError(problem, 409)
    if busy(c):
        raise BackupError('Ya hay un respaldo o una verificación en curso. Espera a que termine.', 409)
    import backup_runner
    try:
        if kind == 'respaldo':
            return backup_runner.onedrive_backup('manual', user_id)
        return backup_runner.onedrive_verify(kind, file, 'manual', user_id)
    except backup_runner.KeyMissing as error:
        raise BackupError(str(error), 409) from None
    except BackupError:
        raise
    except Exception as error:
        raise BackupError('El respaldo falló: ' + type(error).__name__ + ': ' + str(error)[:200], 502) from None


def scheduled(c):
    """Tarea programada de las 02:00. Sin OneDrive listo NO registra un respaldo en la nube: anota por qué no se hizo."""
    problem = not_ready(c)
    outcome = {'at': stamp()}
    if problem:
        outcome.update(status='omitido', detail=problem)
    elif busy(c):
        outcome.update(status='omitido', detail='Ya había un respaldo en curso.')
    else:
        import backup_runner
        try:
            run = backup_runner.onedrive_backup('programado')
            outcome.update(status=run['status'], detail=run.get('file', ''), run=run['id'])
        except Exception as error:
            outcome.update(status='error', detail=(str(error) or type(error).__name__)[:200])
    set_state(c, 'backup_cron', outcome)
    c.commit()
    return outcome


# ---------------------------------------------------------------- estado para el panel y alertas
def last_good(c):
    """Último respaldo CORRECTO Y VERIFICADO (restaurado en una base aislada), de OneDrive o de la copia del equipo."""
    good = [item for item in runs(c) if item.get('kind') == 'respaldo' and item.get('status') == 'correcto' and item.get('verified')]
    if good:
        return max(good, key=lambda item: item.get('finished_at') or '')
    legacy = get_state(c, 'cloud_backup')
    if legacy and legacy.get('ok'):
        # Respaldos de versiones anteriores (copia del equipo): también se verificaban restaurándolos antes de anotarlos.
        return {'kind': 'respaldo', 'status': 'correcto', 'verified': True, 'destination': 'equipo', 'finished_at': legacy.get('at', ''), 'bytes': legacy.get('bytes', 0), 'file': ''}
    return None


def _legacy_entry(legacy):
    return {'id': 'legado-' + (legacy.get('at') or ''), 'kind': 'respaldo', 'trigger': 'programado', 'destination': 'equipo', 'status': 'correcto', 'verified': True,
            'finished_at': legacy.get('at', ''), 'started_at': legacy.get('at', ''), 'requested_at': legacy.get('at', ''), 'bytes': legacy.get('bytes', 0),
            'sha256': legacy.get('sha256', ''), 'file': '', 'legacy': True,
            'verify': {'integrity': 'ok', 'foreign_key_errors': 0, 'clients': legacy.get('clients', 0), 'orders': legacy.get('orders', 0)}}


def keep_legacy(c):
    """Antes de sobrescribir el resumen anterior (cloud_backup), conserva en el historial la copia de la oficina que solo constaba allí,
    con sus datos reales. Así el historial unificado nunca pierde un respaldo ni inventa ninguno."""
    legacy = get_state(c, 'cloud_backup')
    if legacy and legacy.get('ok') and legacy.get('destination') != 'onedrive' and legacy.get('sha256') and not any(item.get('sha256') == legacy['sha256'] for item in runs(c)):
        save_run(c, _legacy_entry(legacy))


def office_copy(c):
    """Última copia del equipo de la oficina: del historial o, si es anterior al historial, del resumen real que dejó el guion."""
    office = next((item for item in runs(c) if item.get('destination') == 'equipo' and item.get('status') == 'correcto'), None)
    legacy = get_state(c, 'cloud_backup')
    if legacy and legacy.get('ok') and legacy.get('destination') != 'onedrive' and (not office or (legacy.get('at') or '') > (office.get('finished_at') or '')):
        office = _legacy_entry(legacy)
    return office


def overview(c, admin):
    link = get_state(c, 'onedrive_link') or {}
    items = runs(c)
    office = office_copy(c)
    # Historial unificado: la copia anterior al nuevo historial aparece con sus datos reales (resumen del guion), marcada como tal.
    history = list(items)
    if office and office.get('legacy') and not any(item.get('sha256') and item.get('sha256') == office.get('sha256') for item in items):
        history.append(office)
        history.sort(key=lambda item: item.get('requested_at') or item.get('finished_at') or '', reverse=True)
    config = app_config(c)
    saved = get_state(c, 'onedrive_app') or {}
    public_link = {key: link.get(key) for key in ('status', 'account', 'name', 'linked_at', 'checked_at', 'error', 'folder')} if link else None
    onedrive_ok = next((item for item in items if item.get('destination') == 'onedrive' and item.get('kind') == 'respaldo' and item.get('status') == 'correcto' and item.get('verified')), None)
    import remote_db
    return {'configured': configured(c), 'ready': not_ready(c), 'link': public_link, 'folder': FOLDER, 'scopes': SCOPES.split(),
            'app': {'source': config['source'], 'client_id': config['client_id'], 'tenant': config['tenant'], 'account_type': config.get('account_type', ''),
                    'saved_at': config.get('saved_at', ''), 'has_secret': True} if config else ({'source': 'panel', 'client_id': saved.get('client_id', ''), 'has_secret': False} if saved else None),
            'account_types': {key: label for key, (_, label) in ACCOUNT_TYPES.items()},
            'central': {'engine': 'Turso (libSQL), base central en la nube' if remote_db.configured() else 'SQLite local de este equipo', 'remote': remote_db.configured(), 'ok': True},
            'office': office, 'last_good': last_good(c), 'last_onedrive': onedrive_ok, 'cron': get_state(c, 'backup_cron'),
            'next_run': next_run().isoformat(timespec='seconds'), 'late_hours': LATE_HOURS, 'busy': busy(c), 'keep': KEEP,
            'runs': history[:60], 'can_manage': bool(admin), 'redirect_uri': redirect_uri()}


def alerts(c, moment=None):
    """Alertas reales y separadas: respaldo atrasado, último respaldo fallido y conexión con OneDrive vencida."""
    moment = moment or now()
    out = []
    good = last_good(c)
    try:
        age = (moment - datetime.fromisoformat(good['finished_at'])).total_seconds() / 3600 if good and good.get('finished_at') else None
    except ValueError:
        age = None
    if age is None or age > LATE_HOURS:
        out.append({'key': 'backup:late:' + moment.date().isoformat(), 'kind': 'warning', 'title': 'Respaldo de la base central atrasado',
                    'detail': ('El último respaldo correcto y verificado es del ' + good['finished_at'][:10] + '.') if good else 'Todavía no se registra ningún respaldo correcto y verificado.'})
    items = runs(c)
    latest = next((item for item in items if item.get('destination') == 'onedrive' and item.get('kind') == 'respaldo' and item.get('status') in ('correcto', 'error')), None)
    if latest and latest['status'] == 'error':
        out.append({'key': 'backup:failed:' + latest['id'], 'kind': 'warning', 'title': 'Falló el último respaldo en OneDrive',
                    'detail': (latest.get('error') or 'Error sin detalle.')[:180]})
    link = get_state(c, 'onedrive_link')
    if link and link.get('status') == 'vencida':
        out.append({'key': 'backup:expired:' + (link.get('checked_at') or '')[:10], 'kind': 'warning', 'title': 'Conexión con OneDrive vencida',
                    'detail': 'Vuelve a vincular la cuenta en Configuración → Respaldos para reanudar las copias en la nube.'})
    elif not link and configured(c):
        out.append({'key': 'backup:unlinked', 'kind': 'info', 'title': 'Respaldos sin copia en OneDrive',
                    'detail': 'Vincula la cuenta de Microsoft 365 en Configuración → Respaldos.'})
    return out
