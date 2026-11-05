"""Evidencias de los seguimientos (fotografías y PDF de hasta 10 MiB) guardadas en la base por partes.

- Vercel no admite más de 4,5 MB por petición: el navegador sube cada archivo en partes de 2,5 MiB (start → part → finish) y el original se
  lee igual, por partes. Nada se reduce: el original conserva su resolución y su SHA-256. La miniatura la genera el navegador aparte.
- Al terminar la carga se verifica el tamaño declarado, el SHA-256 y el tipo real por sus primeros bytes (no por el nombre ni el navegador).
- Una evidencia no se modifica ni se borra: mostrarla u ocultarla al cliente, o retirarla, queda en order_followup_file_changes.
- El enlace público solo entrega evidencias visibles y no retiradas de la orden de ese enlace; las demás responden «no disponible».
- Una carga abandonada (sin usar en 24 h) se limpia sola; reintentar una parte no la duplica."""
import base64
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta

MAX_BYTES = 10 * 1024 * 1024  # 10 MiB = 10.485.760 bytes
PART_BYTES = 2_621_440  # 2,5 MiB por parte: en base64 cabe en una petición de Vercel
MAX_PARTS = 4
THUMB_BYTES = 300_000
DEFAULT_MAX_FILES = 3
MIMES = {b'\xff\xd8\xff': 'image/jpeg', b'\x89PNG\r\n\x1a\n': 'image/png', b'%PDF-': 'application/pdf'}
EXTENSIONS = {'image/jpeg': ('jpg', 'jpeg'), 'image/png': ('png',), 'image/webp': ('webp',), 'application/pdf': ('pdf',)}


class EvidenceError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def stamp(now):
    return now.isoformat(timespec='seconds')


def sniff(raw):
    """Tipo real por los primeros bytes (JPG, PNG, WEBP o PDF); vacío si no es ninguno."""
    for magic, mime in MIMES.items():
        if raw.startswith(magic):
            return mime
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return 'image/webp'
    return ''


def max_files(c):
    """Máximo de evidencias por seguimiento: 3 por defecto; administración puede cambiarlo (1 a 10)."""
    row = c.execute("SELECT value FROM system_state WHERE key='followup_max_files'").fetchone()
    try:
        value = int(row[0]) if row else DEFAULT_MAX_FILES
    except (TypeError, ValueError):
        value = DEFAULT_MAX_FILES
    return value if 1 <= value <= 10 else DEFAULT_MAX_FILES


def set_max_files(c, value, user):
    if user['role'] != 'administrador':
        raise EvidenceError('Solo administración cambia el límite de evidencias.', 403)
    try:
        value = int(str(value))
    except ValueError:
        value = 0
    if not 1 <= value <= 10:
        raise EvidenceError('El límite debe estar entre 1 y 10 archivos.', 400, {'max_files': 'Entre 1 y 10.'})
    c.execute("INSERT INTO system_state(key,value) VALUES ('followup_max_files',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(value),))
    return value


def limits(c):
    return {'max_files': max_files(c), 'max_bytes': MAX_BYTES, 'part_bytes': PART_BYTES, 'types': ['image/jpeg', 'image/png', 'image/webp', 'application/pdf']}


def _name(value):
    name = re.sub(r'[^\w .()-]', '', str(value or ''))[:80].strip()
    return name or 'evidencia'


def _cleanup(c, now):
    """Cargas abandonadas: lo que no llegó a ser evidencia en 24 h se borra (nunca una evidencia guardada)."""
    limit = stamp(now - timedelta(hours=24))
    stale = [r[0] for r in c.execute("SELECT id FROM order_uploads WHERE status!='usada' AND created_at<?", (limit,))]
    for uid in stale:
        c.execute('DELETE FROM order_upload_parts WHERE upload_id=?', (uid,))
        c.execute('DELETE FROM order_uploads WHERE id=?', (uid,))


def _upload(c, oid, token, user):
    row = c.execute('SELECT * FROM order_uploads WHERE token=? AND order_id=?', (str(token or ''), oid)).fetchone() if re.fullmatch(r'[A-Za-z0-9_-]{22,43}', str(token or '')) else None
    if not row:
        raise EvidenceError('La carga no existe o expiró. Vuelve a adjuntar el archivo.', 404)
    return row


def start(c, oid, data, user, now):
    """Abre una carga: nombre, tamaño y SHA-256 que el navegador calculó del archivo original."""
    if user['role'] not in ('administrador', 'tecnico'):
        raise EvidenceError('Acceso no permitido.', 403)
    _cleanup(c, now)
    try:
        size = int(str(data.get('size', '')))
    except ValueError:
        size = 0
    if size <= 0:
        raise EvidenceError('El archivo está vacío.', 400, {'files': 'Archivo vacío.'})
    if size > MAX_BYTES:
        raise EvidenceError('Cada archivo puede pesar como máximo 10 MB (10.485.760 bytes).', 400, {'files': 'Archivo demasiado grande.'})
    digest = str(data.get('sha256', '')).lower()
    if not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise EvidenceError('Carga no válida. Vuelve a adjuntar el archivo.', 400)
    parts = -(-size // PART_BYTES)
    token = secrets.token_urlsafe(24)
    c.execute('INSERT INTO order_uploads(order_id,token,name,size,sha256,parts,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
              (oid, token, _name(data.get('name')), size, digest, parts, user['id'], stamp(now)))
    return {'token': token, 'parts': parts, 'part_bytes': PART_BYTES}


def put_part(c, oid, data, user):
    """Guarda una parte. Reintentar la misma parte no la duplica (si ya está, se acepta igual)."""
    row = _upload(c, oid, data.get('token'), user)
    if row['status'] != 'subiendo':
        raise EvidenceError('Esta carga ya terminó.', 409)
    try:
        idx = int(str(data.get('index', '')))
    except ValueError:
        idx = -1
    if not 0 <= idx < row['parts']:
        raise EvidenceError('Parte no válida.', 400)
    try:
        raw = base64.b64decode(str(data.get('data', '')), validate=True)
    except (ValueError, TypeError):
        raise EvidenceError('Una parte del archivo llegó dañada. Reintenta.', 400)
    expected = PART_BYTES if idx < row['parts'] - 1 else row['size'] - PART_BYTES * (row['parts'] - 1)
    if len(raw) != expected:
        raise EvidenceError('Una parte del archivo llegó incompleta. Reintenta.', 400)
    c.execute('INSERT OR IGNORE INTO order_upload_parts(upload_id,idx,data) VALUES (?,?,?)', (row['id'], idx, base64.b64encode(raw).decode()))
    return {'index': idx, 'received': c.execute('SELECT COUNT(*) FROM order_upload_parts WHERE upload_id=?', (row['id'],)).fetchone()[0]}


def _bytes(c, upload_id):
    """Une las partes leyéndolas de una en una: ninguna consulta a la base devuelve más que una parte."""
    out = []
    for (idx,) in c.execute('SELECT idx FROM order_upload_parts WHERE upload_id=? ORDER BY idx', (upload_id,)).fetchall():
        out.append(base64.b64decode(c.execute('SELECT data FROM order_upload_parts WHERE upload_id=? AND idx=?', (upload_id, idx)).fetchone()[0]))
    return b''.join(out)


def finish(c, oid, data, user):
    """Verifica el archivo completo (tamaño, SHA-256 y tipo real) y su miniatura. Si algo no coincide, la carga se descarta."""
    row = _upload(c, oid, data.get('token'), user)
    if row['status'] == 'lista':
        return {'token': row['token'], 'mime': row['mime'], 'size': row['size'], 'sha256': row['sha256']}
    if row['status'] != 'subiendo':
        raise EvidenceError('Esta carga ya se usó.', 409)
    have = c.execute('SELECT COUNT(*) FROM order_upload_parts WHERE upload_id=?', (row['id'],)).fetchone()[0]
    if have != row['parts']:
        raise EvidenceError('Faltan partes del archivo (%d de %d). Reintenta.' % (have, row['parts']), 409)
    raw = _bytes(c, row['id'])
    mime = sniff(raw)
    problem = ('El archivo no coincide con lo que se envió.' if len(raw) != row['size'] or hashlib.sha256(raw).hexdigest() != row['sha256']
               else 'Solo se admiten fotografías (JPG, PNG, WEBP) e informes PDF.' if not mime else '')
    if problem:
        c.execute('DELETE FROM order_upload_parts WHERE upload_id=?', (row['id'],))
        c.execute('DELETE FROM order_uploads WHERE id=?', (row['id'],))
        raise EvidenceError(problem, 400, {'files': problem})
    thumb = ''
    if mime != 'application/pdf' and data.get('thumb'):
        try:
            small = base64.b64decode(str(data.get('thumb')).split(',')[-1], validate=True)
        except (ValueError, TypeError):
            small = b''
        if small and len(small) <= THUMB_BYTES and sniff(small) in ('image/jpeg', 'image/webp', 'image/png'):
            thumb = base64.b64encode(small).decode()
    c.execute("UPDATE order_uploads SET status='lista',mime=?,thumb=? WHERE id=?", (mime, thumb, row['id']))
    return {'token': row['token'], 'mime': mime, 'size': row['size'], 'sha256': row['sha256']}


def cancel(c, oid, data, user):
    """Quita un archivo de la ventana antes de guardar: la carga (sin usar) se descarta."""
    row = _upload(c, oid, data.get('token'), user)
    if row['status'] == 'usada':
        raise EvidenceError('Ese archivo ya es una evidencia guardada: para quitarlo, retíralo con un motivo.', 409)
    c.execute('DELETE FROM order_upload_parts WHERE upload_id=?', (row['id'],))
    c.execute('DELETE FROM order_uploads WHERE id=?', (row['id'],))
    return {'cancelled': True}


def attach(c, oid, fid, items, user, now):
    """Convierte cargas verificadas en evidencias del seguimiento `fid` (en la misma transacción que el seguimiento)."""
    for item in items:
        row = _upload(c, oid, item['upload'], user)
        if row['status'] != 'lista':
            raise EvidenceError('Un archivo todavía no terminó de subir o ya se usó.', 409, {'files': 'Carga incompleta.'})
        file_id = c.execute('INSERT INTO order_followup_files(followup_id,order_id,name,mime,size,sha256,visible_to_client,data,created_by,created_at,storage,upload_id,thumb) '
                            "VALUES (?,?,?,?,?,?,?,'',?,?,'partes',?,?)",
                            (fid, oid, row['name'], row['mime'], row['size'], row['sha256'], item['visible'], user['id'], stamp(now), row['id'], row['thumb'])).lastrowid
        c.execute("UPDATE order_uploads SET status='usada',file_id=? WHERE id=?", (file_id, row['id']))


def uploads_in(items):
    """Elementos de `files` que vienen como carga por partes ({upload, visible})."""
    out = []
    for item in items:
        if isinstance(item, dict) and item.get('upload'):
            out.append({'upload': str(item['upload']), 'visible': 1 if str(item.get('visible', '')) in ('1', 'true') else 0})
    return out


# ---- Estado vigente, lectura y cambios -----------------------------------------------------------------------------------------

def states(c, oid):
    """Visibilidad y retiro vigentes de cada evidencia de la orden (el último cambio manda; sin cambios, lo que se guardó)."""
    out = {r['id']: {'visible': r['visible_to_client'], 'retired': 0, 'reason': '', 'changed_at': '', 'changed_by': ''}
           for r in c.execute('SELECT id,visible_to_client FROM order_followup_files WHERE order_id=?', (oid,))}
    for r in c.execute("SELECT x.file_id,x.visible,x.retired,x.reason,x.created_at,COALESCE(u.name,'') actor FROM order_followup_file_changes x "
                       'JOIN order_followup_files f ON f.id=x.file_id LEFT JOIN users u ON u.id=x.created_by WHERE f.order_id=? ORDER BY x.id', (oid,)):
        out[r['file_id']] = {'visible': r['visible'], 'retired': r['retired'], 'reason': r['reason'], 'changed_at': r['created_at'], 'changed_by': r['actor']}
    return out


def _file(c, oid, file_id):
    row = c.execute('SELECT * FROM order_followup_files WHERE id=? AND order_id=?', (file_id, oid)).fetchone()
    if not row:
        raise EvidenceError('Archivo no disponible.', 404)
    return row


def meta(c, oid, file_id, public=False):
    row = _file(c, oid, file_id)
    state = states(c, oid)[row['id']]
    if public and (not state['visible'] or state['retired']):
        raise EvidenceError('Archivo no disponible.', 404)
    parts = 1 if row['storage'] != 'partes' else c.execute('SELECT parts FROM order_uploads WHERE id=?', (row['upload_id'],)).fetchone()[0]
    return {'id': row['id'], 'name': row['name'], 'mime': row['mime'], 'size': row['size'], 'sha256': row['sha256'], 'parts': parts, 'thumb': bool(row['thumb']),
            'visible': bool(state['visible']), 'retired': bool(state['retired'])}


def part(c, oid, file_id, idx, public=False):
    """Una parte del original (o el archivo entero si se guardó de una vez). Público: solo si está visible y no retirada."""
    info = meta(c, oid, file_id, public)
    row = _file(c, oid, file_id)
    if not 0 <= idx < info['parts']:
        raise EvidenceError('Parte no válida.', 404)
    if row['storage'] != 'partes':
        return info['name'], info['mime'], base64.b64decode(row['data'])
    found = c.execute('SELECT data FROM order_upload_parts WHERE upload_id=? AND idx=?', (row['upload_id'], idx)).fetchone()
    if not found:
        raise EvidenceError('Archivo no disponible.', 404)
    return info['name'], 'application/octet-stream' if info['parts'] > 1 else info['mime'], base64.b64decode(found[0])


def whole(c, oid, file_id):
    """Archivo completo (para adjuntarlo a un correo autorizado). Solo en el servidor; nunca se responde entero si supera una petición."""
    row = _file(c, oid, file_id)
    return row['name'], row['mime'], (base64.b64decode(row['data']) if row['storage'] != 'partes' else _bytes(c, row['upload_id']))


def thumb(c, oid, file_id, public=False):
    meta(c, oid, file_id, public)
    row = _file(c, oid, file_id)
    if not row['thumb']:
        raise EvidenceError('Sin miniatura.', 404)
    raw = base64.b64decode(row['thumb'])
    return 'miniatura', sniff(raw) or 'image/jpeg', raw


def change(c, oid, file_id, data, user, now):
    """Mostrar u ocultar al cliente, o retirar (con motivo). La evidencia no se modifica: se registra el cambio."""
    if user['role'] not in ('administrador', 'tecnico'):
        raise EvidenceError('Acceso no permitido.', 403)
    row = _file(c, oid, file_id)
    state = states(c, oid)[row['id']]
    if state['retired']:
        raise EvidenceError('Esta evidencia ya fue retirada.', 409)
    action = str(data.get('action', ''))
    reason = re.sub(r'\s+', ' ', str(data.get('reason', '') or '')).strip()[:300]
    if action == 'retire':
        if len(reason) < 5:
            raise EvidenceError('Indica por qué se retira la evidencia (al menos 5 caracteres).', 400, {'reason': 'Motivo obligatorio.'})
        values = (0, 1, reason)
    elif action == 'visibility':
        visible = 1 if str(data.get('visible', '')) in ('1', 'true') else 0
        if visible == state['visible']:
            return {'unchanged': True}
        values = (visible, 0, reason)
    else:
        raise EvidenceError('Acción no válida.', 400)
    c.execute('INSERT INTO order_followup_file_changes(file_id,visible,retired,reason,created_by,created_at) VALUES (?,?,?,?,?,?)', (row['id'], *values, user['id'], stamp(now)))
    return {'file_id': row['id'], 'visible': bool(values[0]), 'retired': bool(values[1])}


def public_files(c, oid):
    """Evidencias que el cliente puede ver: visibles y no retiradas (sin nombres internos más allá del nombre del archivo)."""
    st = states(c, oid)
    rows = c.execute("SELECT f.id,f.name,f.mime,f.size,f.thumb!='' has_thumb,f.created_at,f.storage,COALESCE(u.parts,1) parts FROM order_followup_files f "
                     'LEFT JOIN order_uploads u ON u.id=f.upload_id WHERE f.order_id=? ORDER BY f.id', (oid,)).fetchall()
    # Una evidencia anterior (guardada entera, sin miniatura) se muestra con la imagen misma: cabe en una sola respuesta.
    return [{'id': r['id'], 'name': r['name'], 'mime': r['mime'], 'size': r['size'], 'thumb': bool(r['has_thumb']), 'parts': r['parts'], 'created_at': r['created_at'],
             'preview': 'thumb' if r['has_thumb'] else 'original' if r['mime'] != 'application/pdf' and r['parts'] == 1 else ''}
            for r in rows if st[r['id']]['visible'] and not st[r['id']]['retired']]


# ---- Borrador del seguimiento -------------------------------------------------------------------------------------------------

DRAFT_FIELDS = ('kind', 'priority', 'quote_id', 'internal_note', 'observations', 'diagnosis', 'client_message', 'recommendation', 'client_visible',
                'next_action', 'next_date', 'next_owner_id', 'next_reminder')


def draft_get(c, oid, user):
    row = c.execute('SELECT data,updated_at FROM order_followup_drafts WHERE order_id=? AND user_id=?', (oid, user['id'])).fetchone()
    if not row:
        return None
    try:
        return {'data': json.loads(row['data']), 'updated_at': row['updated_at']}
    except ValueError:
        return None


def draft_save(c, oid, data, user, now):
    clean = {k: str(data.get(k, '') or '')[:2000] for k in DRAFT_FIELDS if str(data.get(k, '') or '').strip()}
    if not clean:
        raise EvidenceError('El borrador está vacío.', 400)
    c.execute('INSERT INTO order_followup_drafts(order_id,user_id,data,updated_at) VALUES (?,?,?,?) ON CONFLICT(order_id,user_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at',
              (oid, user['id'], json.dumps(clean, ensure_ascii=False), stamp(now)))
    return {'saved_at': stamp(now)}


def draft_discard(c, oid, user):
    c.execute('DELETE FROM order_followup_drafts WHERE order_id=? AND user_id=?', (oid, user['id']))
