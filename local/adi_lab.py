"""Private laboratory records and evidence-based checklists. No model calls or firmware operations."""
from datetime import date
from decimal import Decimal, InvalidOperation
import re
import unicodedata

STAFF = ('tecnico', 'administrador')
CATEGORIES = {
    'alimentacion': 'Alimentación y carga',
    'post': 'Encendido, POST y vídeo',
    'firmware': 'BIOS, UEFI y firmware',
    'impresoras': 'Impresoras',
    'consolas': 'Consolas',
}
CHECKS = {
    'alimentacion': ('Identifica placa y revisión. Consulta el esquema aplicable antes de identificar puntos de medida.',
                     'Registra la condición del equipo, referencia de tierra y medición. Compara con la fuente validada.'),
    'post': ('Distingue falta de encendido, ausencia de POST y ausencia de imagen.',
             'Registra indicaciones y pruebas reproducibles. Contrasta los códigos con el manual del modelo.'),
    'firmware': ('Registra modelo exacto, placa, revisión, chip y voltaje documentado.',
                 'Identifica el firmware oficial y conserva lecturas originales verificadas antes de solicitar autorización técnica.'),
    'impresoras': ('Registra modelo, código de error y condiciones de reproducción.',
                   'Consulta el manual del modelo antes de intervenir sensores, cabezal o tarjeta.'),
    'consolas': ('Registra modelo, síntoma, historial térmico y condiciones de reproducción.',
                 'Comprueba las indicaciones del fabricante antes de intervenir la refrigeración.'),
}
UNITS = ('V', 'mV', 'A', 'mA', 'Ω', 'kΩ', 'MΩ', 'MHz', '°C', 'W')
KNOWLEDGE_FIELDS = ('title', 'source', 'source_date', 'version', 'category', 'content', 'visibility')
FIRMWARE_FIELDS = {
    'model': 'Modelo exacto', 'board': 'Código de placa', 'revision': 'Revisión', 'chip': 'Identificación del chip',
    'voltage': 'Voltaje documentado', 'source': 'Fuente oficial', 'compatibility': 'Referencia de compatibilidad',
    'backup_sha256': 'SHA-256 del respaldo original', 'image_sha256': 'SHA-256 de la imagen',
}


class LabError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def require_staff(user):
    if not user or user['role'] not in STAFF:
        raise LabError('Acceso reservado a personal técnico autorizado.', 403)


def installed(c):
    return c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                     "('adi_lab_knowledge','adi_lab_measurements')").fetchone()[0] == 2


def require_storage(c):
    if not installed(c):
        raise LabError('Aplica la migración 131 para habilitar los registros de laboratorio.', 503)


def text_field(data, key, maximum):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum or '\x00' in value:
        raise LabError('Completa el campo %s (máximo %d caracteres).' % (key, maximum))
    return value.strip()


def tokens(text):
    normalized = unicodedata.normalize('NFKD', text.casefold())
    return set(re.findall(r'[^\W_]{2,}', ''.join(x for x in normalized if not unicodedata.combining(x))))


def search(c, user, query='', category='', review=False):
    require_staff(user)
    require_storage(c)
    if category and category not in CATEGORIES:
        raise LabError('Categoría no válida.')
    status = 'pendiente' if review else 'aprobado'
    where = "status=? AND (visibility='tecnico' OR ?='administrador') AND (?='' OR category=?)"
    args = (status, user['role'], category, category)
    terms = tokens(query[:180])
    matches = []
    for row in c.execute('SELECT * FROM adi_lab_knowledge WHERE ' + where + ' ORDER BY id DESC LIMIT 300', args):
        title_hits = terms & tokens(row['title'])
        all_hits = terms & tokens(row['title'] + ' ' + row['source'] + ' ' + row['content'])
        if not terms or all_hits:
            matches.append((len(all_hits) + 3 * len(title_hits), dict(row)))
    matches.sort(key=lambda item: (-item[0], -item[1]['id']))
    return [row for _, row in matches[:15]]


def submit(c, data, user, now):
    require_staff(user)
    require_storage(c)
    values = tuple(text_field(data, key, size) for key, size in zip(KNOWLEDGE_FIELDS, (160, 400, 10, 60, 30, 6000, 20)))
    try:
        if date.fromisoformat(values[2]).isoformat() != values[2]:
            raise ValueError
    except ValueError:
        raise LabError('La fecha de la fuente debe tener el formato AAAA-MM-DD.') from None
    if values[4] not in CATEGORIES or values[6] not in STAFF:
        raise LabError('Categoría o permisos no válidos.')
    if values[6] == 'administrador' and user['role'] != 'administrador':
        raise LabError('Solo administración registra material reservado.', 403)
    supersedes = data.get('supersedes') or ''
    previous_id = None
    if supersedes:
        if not isinstance(supersedes, str) or not re.fullmatch(r'[0-9]{1,9}', supersedes):
            raise LabError('Referencia de corrección inválida.')
        previous = c.execute("SELECT visibility,category,version FROM adi_lab_knowledge WHERE id=? AND status='aprobado'",
                             (int(supersedes),)).fetchone()
        if not previous or previous['visibility'] != values[6] or previous['category'] != values[4]:
            raise LabError('La corrección debe conservar la categoría y los permisos de la fuente aprobada.', 409)
        if previous['version'] == values[3]:
            raise LabError('Indica la nueva versión de la fuente corregida.')
        previous_id = int(supersedes)
    return c.execute('INSERT INTO adi_lab_knowledge(title,source,source_date,version,category,content,visibility,supersedes,created_by,created_at) '
                     'VALUES (?,?,?,?,?,?,?,?,?,?)', values + (previous_id, user['id'], now.isoformat(timespec='seconds'))).lastrowid


def review(c, document_id, data, user, now):
    require_staff(user)
    require_storage(c)
    choice = data.get('status')
    if choice not in ('aprobado', 'descartado'):
        raise LabError('Selecciona aprobar o descartar.')
    note = text_field(data, 'review_note', 600)
    row = c.execute('SELECT created_by,visibility,supersedes,status FROM adi_lab_knowledge WHERE id=?', (document_id,)).fetchone()
    if not row or (row['visibility'] == 'administrador' and user['role'] != 'administrador'):
        raise LabError('Documento no disponible.', 404)
    if row['created_by'] == user['id'] and choice == 'aprobado':
        raise LabError('La aprobación necesita otro integrante autorizado.', 403)
    if row['status'] != 'pendiente':
        raise LabError('El documento ya fue revisado.', 409)
    if choice == 'aprobado' and row['supersedes']:
        previous = c.execute("UPDATE adi_lab_knowledge SET status='sustituido' WHERE id=? AND status='aprobado'", (row['supersedes'],))
        if previous.rowcount != 1:
            raise LabError('La versión anterior ya fue sustituida.', 409)
    result = c.execute("UPDATE adi_lab_knowledge SET status=?,reviewed_by=?,reviewed_at=?,review_note=? WHERE id=? AND status='pendiente'",
                       (choice, user['id'], now.isoformat(timespec='seconds'), note, document_id))
    if result.rowcount != 1:
        raise LabError('El documento ya fue revisado.', 409)


def order_context(c, oid):
    order = c.execute('SELECT o.id,o.code,o.status,o.device_id,d.brand,d.model FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?', (oid,)).fetchone()
    if not order:
        raise LabError('Orden no disponible.', 404)
    return dict(order)


def draft(c, oid, user, category='', query=''):
    require_staff(user)
    require_storage(c)
    order = order_context(c, oid)
    if category and category not in CATEGORIES:
        raise LabError('Categoría no válida.')
    measurements = [dict(row) for row in c.execute('SELECT point,value,unit,conditions,created_at FROM adi_lab_measurements '
                                                  'WHERE order_id=? ORDER BY id DESC LIMIT 40', (oid,))]
    prior = [dict(row) for row in c.execute('SELECT code,status,received_at FROM orders WHERE device_id=? AND id<>? '
                                          'ORDER BY id DESC LIMIT 10', (order.pop('device_id'), oid))]
    return {'order': order, 'prior_orders': prior, 'measurements': measurements, 'checks': CHECKS.get(category, ()), 'kind': 'borrador',
            'sources': search(c, user, query, category) if query or category else []}


def measure(c, oid, data, user, now):
    require_staff(user)
    require_storage(c)
    order_context(c, oid)
    point = text_field(data, 'point', 120)
    value = text_field(data, 'value', 22)
    unit = data.get('unit')
    conditions = text_field(data, 'conditions', 400)
    key = text_field(data, 'request_key', 80)
    try:
        number = Decimal(value.replace(',', '.'))
        valid = bool(re.fullmatch(r'-?[0-9]+(?:[.,][0-9]{1,9})?', value)) and number.is_finite() and abs(number) <= 10**9
    except InvalidOperation:
        valid = False
    if unit not in UNITS or not valid:
        raise LabError('Escribe una medición numérica finita y selecciona una unidad válida.')
    row = c.execute('INSERT INTO adi_lab_measurements(order_id,point,value,unit,conditions,created_by,created_at,request_key) '
                    'VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(order_id,created_by,request_key) DO NOTHING RETURNING id',
                    (oid, point, value, unit, conditions, user['id'], now.isoformat(timespec='seconds'), key)).fetchone()
    if row:
        return row['id'], True
    stored = c.execute('SELECT id,point,value,unit,conditions FROM adi_lab_measurements WHERE order_id=? AND created_by=? AND request_key=?',
                       (oid, user['id'], key)).fetchone()
    if tuple(stored[field] for field in ('point', 'value', 'unit', 'conditions')) != (point, value, unit, conditions):
        raise LabError('La solicitud ya identifica otra medición.', 409)
    return stored['id'], False


def firmware_readiness(data, user):
    require_staff(user)
    missing = [label for key, label in FIRMWARE_FIELDS.items()
               if not isinstance(data.get(key), str) or not 1 <= len(data[key].strip()) <= 400]
    for key in ('backup_sha256', 'image_sha256'):
        if FIRMWARE_FIELDS[key] not in missing and not re.fullmatch(r'[a-fA-F0-9]{64}', data[key].strip()):
            missing.append(FIRMWARE_FIELDS[key])
    return {'missing': missing, 'status': 'incompleto' if missing else 'revision_tecnica_pendiente',
            'write_authorized': False,
            'message': 'Un técnico debe verificar la evidencia, la compatibilidad y la autorización antes de cualquier escritura.'}


def diagnoses_installed(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='adi_lab_diagnoses'").fetchone())


def diagnosis_history(c, oid, user):
    require_staff(user)
    order_context(c, oid)
    if not diagnoses_installed(c):
        return {'installed': False, 'rows': []}
    rows = c.execute(
        "SELECT d.id,d.confirmed,d.conclusion,d.pending_checks,d.status,d.created_by,d.created_at,"
        "d.reviewed_at,d.review_note,a.name author,COALESCE(r.name,'') reviewer "
        "FROM adi_lab_diagnoses d JOIN users a ON a.id=d.created_by LEFT JOIN users r ON r.id=d.reviewed_by "
        "WHERE d.order_id=? ORDER BY d.id DESC LIMIT 25", (oid,))
    return {'installed': True, 'rows': [dict(row, can_review=row['status']=='pendiente' and row['created_by']!=user['id']) for row in rows]}


def submit_diagnosis(c, oid, data, user, now):
    require_staff(user)
    if not diagnoses_installed(c):
        raise LabError('Aplica la migración 132 para habilitar la aprobación de diagnósticos.', 503)
    order = c.execute("SELECT COALESCE(findings,'') findings FROM orders WHERE id=?", (oid,)).fetchone()
    if not order:
        raise LabError('Orden no disponible.', 404)
    values = (text_field(data, 'confirmed', 1700), text_field(data, 'conclusion', 1700))
    pending = data.get('pending_checks', '')
    if not isinstance(pending, str) or len(pending.strip()) > 1500 or '\x00' in pending:
        raise LabError('Las comprobaciones pendientes admiten hasta 1500 caracteres.')
    values += (pending.strip(),)
    key = text_field(data, 'request_key', 80)
    row = c.execute('INSERT INTO adi_lab_diagnoses(order_id,confirmed,conclusion,pending_checks,previous_findings,created_by,created_at,request_key) '
                    'VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(order_id,created_by,request_key) DO NOTHING RETURNING id',
                    (oid, *values, order['findings'], user['id'], now.isoformat(timespec='seconds'), key)).fetchone()
    if row:
        return row['id'], True
    existing = c.execute('SELECT id,confirmed,conclusion,pending_checks FROM adi_lab_diagnoses WHERE order_id=? AND created_by=? AND request_key=?',
                         (oid, user['id'], key)).fetchone()
    if tuple(existing[field] for field in ('confirmed','conclusion','pending_checks')) != values:
        raise LabError('La solicitud ya identifica otra propuesta.', 409)
    return existing['id'], False


def review_diagnosis(c, oid, did, data, user, now):
    import order_workspace

    require_staff(user)
    if not diagnoses_installed(c):
        raise LabError('Aplica la migración 132 para habilitar la aprobación de diagnósticos.', 503)
    choice = data.get('decision')
    if choice not in ('aprobado','devuelto'):
        raise LabError('Selecciona aprobar o devolver.')
    note = text_field(data, 'review_note', 600)
    row = c.execute("SELECT d.*,COALESCE(o.findings,'') current_findings FROM adi_lab_diagnoses d "
                    "JOIN orders o ON o.id=d.order_id WHERE d.id=? AND d.order_id=?", (did, oid)).fetchone()
    if not row:
        raise LabError('Propuesta no disponible.', 404)
    if row['created_by'] == user['id']:
        raise LabError('La revisión corresponde a otro técnico autorizado.', 403)
    if row['status'] != 'pendiente':
        raise LabError('La propuesta ya fue revisada.', 409)
    if choice == 'aprobado' and row['current_findings'] != row['previous_findings']:
        raise LabError('El diagnóstico de la orden cambió. Devuelve esta propuesta y crea una actualizada.', 409)
    c.execute('UPDATE adi_lab_diagnoses SET status=?,reviewed_by=?,reviewed_at=?,review_note=? WHERE id=?',
              (choice,user['id'],now.isoformat(timespec='seconds'),note,did))
    if choice == 'aprobado':
        official = 'Hallazgos confirmados\n' + row['confirmed'] + '\n\nDiagnóstico aprobado\n' + row['conclusion']
        c.execute('UPDATE orders SET findings=?,updated_at=?,revision=revision+1 WHERE id=?',
                  (official,now.isoformat(timespec='microseconds'),oid))
        order_workspace.event(c,oid,user['id'],now,'updated','Diagnóstico técnico aprobado en Laboratorio ADI (propuesta %d).' % did)
