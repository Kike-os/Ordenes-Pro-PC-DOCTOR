"""Respaldos automáticos en Microsoft OneDrive (Microsoft 365) — 1.5.309.

Lo usan dos lados que nunca comparten el archivo de respaldo:
  · La aplicación (Vercel): vincula la cuenta con OAuth 2.0 + PKCE, guarda el token de actualización CIFRADO en la base, muestra el
    estado y pide respaldos o verificaciones al generador (GitHub Actions) con el botón del panel.
  · El generador (maintenance/backup-cloud.py en GitHub Actions o en este equipo): copia la base, la cifra, la sube, la descarga de
    nuevo, comprueba el SHA-256, la descifra y la restaura en una base aislada antes de darla por válida.

Permisos de Microsoft Graph (delegados, de la cuenta que se vincula): offline_access, User.Read y Files.ReadWrite. En cuentas de
Microsoft 365 empresa no existe un permiso menor que funcione (Files.ReadWrite.AppFolder es solo para cuentas personales). El código
solo toca la carpeta de respaldos.

Secretos (variables de entorno, nunca en el navegador ni en la base en claro):
  MS_CLIENT_ID, MS_CLIENT_SECRET, MS_TENANT_ID   registro de la aplicación en Microsoft Entra ID
  ONEDRIVE_TOKEN_KEY                            32 bytes en base64: cifra el token de actualización guardado en la base
  BACKUP_ENCRYPTION_KEY                         32 bytes en base64: cifra cada respaldo (solo el generador; nunca en Vercel)
  GITHUB_BACKUP_TOKEN                           token de GitHub con permiso Actions (escritura) solo de este repositorio
"""
import base64
import hashlib
import hmac
import json
import os
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


def tenant():
    return os.getenv('MS_TENANT_ID', '').strip() or 'organizations'


def configured():
    """La aplicación de Microsoft está registrada y hay clave para guardar el token cifrado."""
    return bool(os.getenv('MS_CLIENT_ID', '').strip() and os.getenv('MS_CLIENT_SECRET', '').strip() and _token_key(optional=True))


def dispatch_configured():
    return bool(os.getenv('GITHUB_BACKUP_TOKEN', '').strip())


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
    if not configured():
        raise BackupError('Falta registrar la aplicación de Microsoft en el servidor (MS_CLIENT_ID, MS_CLIENT_SECRET y ONEDRIVE_TOKEN_KEY).', 409)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    set_state(c, 'onedrive_oauth', {'state': hashlib.sha256(state.encode()).hexdigest(), 'verifier': seal(verifier), 'user_id': user_id,
                                    'expires': (now() + timedelta(minutes=10)).isoformat(timespec='seconds')})
    c.commit()
    query = urllib.parse.urlencode({'client_id': os.environ['MS_CLIENT_ID'].strip(), 'response_type': 'code', 'redirect_uri': redirect_uri(),
                                    'response_mode': 'query', 'scope': SCOPES, 'state': state, 'code_challenge': challenge,
                                    'code_challenge_method': 'S256', 'prompt': 'select_account'})
    return login_base() + '/' + tenant() + '/oauth2/v2.0/authorize?' + query


def _token_request(fields):
    body = urllib.parse.urlencode(dict(fields, client_id=os.environ['MS_CLIENT_ID'].strip(), client_secret=os.environ['MS_CLIENT_SECRET'].strip(), scope=SCOPES)).encode()
    return _json(http('POST', login_base() + '/' + tenant() + '/oauth2/v2.0/token', body, {'Content-Type': 'application/x-www-form-urlencoded'}, attempts=3))


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
    tokens = _token_request({'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri(), 'code_verifier': unseal(pending['verifier'])})
    access, refresh = tokens.get('access_token'), tokens.get('refresh_token')
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
        tokens = _token_request({'grant_type': 'refresh_token', 'refresh_token': unseal(link['refresh'])})
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


# ---------------------------------------------------------------- pedir trabajo al generador (GitHub Actions)
def dispatch(mode, run_id, file=''):
    token = os.getenv('GITHUB_BACKUP_TOKEN', '').strip()
    if not token:
        raise BackupError('Falta GITHUB_BACKUP_TOKEN en el servidor para pedir el respaldo al generador.', 409)
    repo = os.getenv('GITHUB_BACKUP_REPO', 'Kike-os/Ordenes-Pro-PC-DOCTOR').strip()
    workflow = os.getenv('GITHUB_BACKUP_WORKFLOW', 'respaldo.yml').strip()
    api = os.getenv('GITHUB_API', 'https://api.github.com').rstrip('/')
    body = json.dumps({'ref': os.getenv('GITHUB_BACKUP_REF', 'main'), 'inputs': {'modo': mode, 'archivo': file, 'solicitud': run_id}}).encode()
    http('POST', api + '/repos/' + repo + '/actions/workflows/' + workflow + '/dispatches', body,
         {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'}, token=token, attempts=2, expect=(204,))


def request_run(c, user_id, kind, file=''):
    if kind not in RUN_KINDS:
        raise BackupError('Operación de respaldo no válida.', 400)
    if kind != 'respaldo' and not any(item.get('file') == file and item.get('status') == 'correcto' and item.get('destination') == 'onedrive' for item in runs(c)):
        raise BackupError('Elige un respaldo correcto de OneDrive del historial.', 400)
    if not get_state(c, 'onedrive_link'):
        raise BackupError('Vincula primero la cuenta de OneDrive.', 409)
    if busy(c):
        raise BackupError('Ya hay un respaldo o una verificación en curso. Espera a que termine.', 409)
    run = save_run(c, new_run(kind, 'manual', 'onedrive', user_id, file))
    try:
        dispatch({'respaldo': 'respaldo', 'verificacion': 'verificar', 'restauracion': 'restaurar'}[kind], run['id'], file)
    except BackupError as error:
        run.update(status='error', finished_at=stamp(), error=str(error))
        save_run(c, run)
        raise
    return run


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


def overview(c, admin):
    link = get_state(c, 'onedrive_link') or {}
    items = runs(c)
    public_link = {key: link.get(key) for key in ('status', 'account', 'name', 'linked_at', 'checked_at', 'error', 'folder')} if link else None
    good = last_good(c)
    onedrive_ok = next((item for item in items if item.get('destination') == 'onedrive' and item.get('kind') == 'respaldo' and item.get('status') == 'correcto' and item.get('verified')), None)
    return {'configured': configured(), 'dispatch': dispatch_configured(), 'link': public_link, 'folder': FOLDER, 'scopes': SCOPES.split(),
            'last_good': good, 'last_onedrive': onedrive_ok, 'next_run': next_run().isoformat(timespec='seconds'), 'late_hours': LATE_HOURS,
            'busy': busy(c), 'keep': KEEP, 'runs': items[:60], 'can_manage': bool(admin), 'redirect_uri': redirect_uri() if admin else ''}


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
    elif not link and configured():
        out.append({'key': 'backup:unlinked', 'kind': 'info', 'title': 'Respaldos sin copia en OneDrive',
                    'detail': 'Vincula la cuenta de Microsoft 365 en Configuración → Respaldos.'})
    return out
