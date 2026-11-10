"""Original firmado electrónicamente de una versión de las condiciones (1.5.271).

- El PDF se guarda EXACTAMENTE como se recibió (nunca se modifica, regenera ni vuelve a firmar), con su SHA-256.
- Solo se acepta si contiene una firma PAdES y corresponde a esa versión exacta: su texto debe incluir el número de versión y la huella
  SHA-256 del texto publicado (los primeros 32 caracteres que imprime el documento oficial).
- Se registra el resultado de la verificación (válida, inválida o no verificable) con firmante, emisor, vigencia del certificado y fecha.
  Una firma inválida no se guarda. La cadena de confianza hasta la autoridad raíz no se comprueba aquí (se indica siempre).
- Estados documentales (no confundir con la versión de la aplicación): borrador → aprobado/publicado → firmado electrónicamente →
  vigente → sustituido. Publicar y firmar son pasos distintos: una versión publicada sin original firmado se muestra como tal."""
import base64
import hashlib
import re

import pdf_signature

MAX_BYTES = 3_000_000
LABELS = {'valida': 'Firma verificada', 'invalida': 'Firma no válida', 'no_verificable': 'Firma no verificable aquí'}


class SignedError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _terms(c, terms_id):
    row = c.execute('SELECT id,version,content_hash FROM service_terms WHERE id=?', (terms_id,)).fetchone()
    if not row:
        raise SignedError('Versión de condiciones no encontrada.', 404)
    return row


def upload(c, terms_id, filename, content, user, now):
    """Guarda el original firmado de una versión publicada. Devuelve su ficha (sin el archivo)."""
    if user['role'] != 'administrador':
        raise SignedError('Solo administración puede cargar el original firmado.', 403)
    terms = _terms(c, terms_id)
    try:
        data = base64.b64decode(str(content or ''), validate=True)
    except (ValueError, TypeError):
        raise SignedError('El archivo no se pudo leer.')
    if not data or len(data) > MAX_BYTES:
        raise SignedError('Carga un PDF firmado de hasta 3 MB.')
    if not data.startswith(b'%PDF-'):
        raise SignedError('El archivo no es un PDF.')
    try:
        result = pdf_signature.verify(data)
    except pdf_signature.SignatureError as error:
        raise SignedError(str(error))
    if result['verified'] == 'invalida':
        raise SignedError('La firma del PDF no es válida: ' + result['detail'], 409)
    text = pdf_signature.page_text(data)
    if terms['version'].encode() not in text or terms['content_hash'][:32].encode() not in text:
        raise SignedError('Este PDF no corresponde a la versión %s: no contiene su número de versión y su huella. Carga el original firmado de esa versión.' % terms['version'], 409)
    sha = hashlib.sha256(data).hexdigest()
    same = c.execute('SELECT id FROM service_terms_signed WHERE terms_id=? AND sha256=?', (terms_id, sha)).fetchone()
    if same:
        return dict(record(c, same['id']), duplicate=True)
    name = re.sub(r'[^\w .()-]+', '', str(filename or ''))[:120] or 'condiciones-firmado.pdf'
    rid = c.execute('INSERT INTO service_terms_signed(terms_id,filename,data,size,sha256,sub_filter,signer,signer_id,issuer,cert_from,cert_until,signed_at,timestamped,verified,verify_detail,uploaded_by,uploaded_at) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (terms_id, name, data, len(data), sha, result['sub_filter'], result['signer'], result['signer_id'], result['issuer'], result['cert_from'], result['cert_until'],
                     result['signed_at'], 1 if result['timestamped'] else 0, result['verified'], result['detail'][:500], user['id'], now.isoformat(timespec='seconds'))).lastrowid
    return dict(record(c, rid), duplicate=False)


COLUMNS = 'id,terms_id,filename,size,sha256,sub_filter,signer,signer_id,issuer,cert_from,cert_until,signed_at,timestamped,verified,verify_detail,uploaded_at'


def record(c, rid):
    row = c.execute('SELECT ' + ','.join('s.' + k for k in COLUMNS.split(',')) + ",COALESCE(u.name,'') uploader FROM service_terms_signed s LEFT JOIN users u ON u.id=s.uploaded_by WHERE s.id=?", (rid,)).fetchone()
    if not row:
        return None
    out = dict(row)
    out['timestamped'] = bool(out['timestamped'])
    out['verified_label'] = LABELS.get(out['verified'], out['verified'])
    return out


def latest(c, terms_id):
    row = c.execute('SELECT id FROM service_terms_signed WHERE terms_id=? ORDER BY id DESC LIMIT 1', (terms_id,)).fetchone()
    return record(c, row['id']) if row else None


def history(c, terms_id):
    return [record(c, r['id']) for r in c.execute('SELECT id FROM service_terms_signed WHERE terms_id=? ORDER BY id DESC', (terms_id,))]


def file(c, rid=None, terms_id=None):
    """(nombre, datos) del original firmado: por su id o el último de una versión."""
    if rid is not None:
        row = c.execute('SELECT filename,data FROM service_terms_signed WHERE id=?', (rid,)).fetchone()
    else:
        row = c.execute('SELECT filename,data FROM service_terms_signed WHERE terms_id=? ORDER BY id DESC LIMIT 1', (terms_id,)).fetchone()
    return (row['filename'], bytes(row['data'])) if row else None


def reverify(c, rid):
    """Vuelve a verificar el archivo guardado (no modifica el registro): integridad del archivo y de su firma."""
    row = c.execute('SELECT data,sha256 FROM service_terms_signed WHERE id=?', (rid,)).fetchone()
    if not row:
        raise SignedError('Original firmado no encontrado.', 404)
    data = bytes(row['data'])
    result = pdf_signature.verify(data)
    result['file_intact'] = hashlib.sha256(data).hexdigest() == row['sha256']
    return result


def state(meta, signed):
    """Estado documental de una versión (fila de overview) con su original firmado."""
    if meta.get('current'):
        base = 'vigente'
    elif meta.get('scheduled'):
        base = 'aprobado'
    else:
        base = 'sustituido'
    return {'state': base, 'state_label': {'vigente': 'Vigente', 'aprobado': 'Aprobado (vigencia futura)', 'sustituido': 'Sustituido'}[base],
            'signed': bool(signed and signed['verified'] in ('valida', 'no_verificable')), 'signature': signed}
