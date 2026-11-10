"""Firma empresarial visual (1.5.271): imagen de identificación de PC-DOCTOR S.A. en documentos PDF elegidos por administración.

- La imagen original se guarda INTACTA (business_signature_versions.data) con su huella. Para imprimir se derivan, sin tocar el original,
  una representación A4 (RGB + transparencia) y una de ticket térmico de 80 mm (blanco y negro, al ancho elegido, sin deformar).
- Es una FIRMA VISUAL, no una firma electrónica: cada documento la acompaña de la leyenda CAPTION. Un QR incluido en la imagen
  pertenece a la firma original y no verifica el documento nuevo; nada se presenta como firmado electrónicamente.
- Desactivada por defecto y por documento: administración decide en cuáles aparece. Cada carga es una versión nueva (las anteriores se
  conservan) y cada cambio queda auditado. Los PDF ya firmados electrónicamente nunca se modifican (no pasan por aquí)."""
import base64
import hashlib
import json
import re
import struct
import zlib
from functools import lru_cache

KEY = 'business_signature'
DOCS = {'ticket': 'Ticket de recepción (80 mm)', 'comprobante': 'Comprobante de recepción (A4)', 'servicio': 'Hoja de servicio técnico (informe)',
        'presupuesto': 'Presupuestos', 'proforma': 'Proformas', 'garantia': 'Certificados de garantía', 'pago': 'Recibos de pago'}
# Documentos pedidos que todavía no existen como PDF en Órdenes Pro: se muestran, pero no se pueden activar.
UNAVAILABLE = {'entrega': 'Comprobantes de entrega', 'repuestos': 'Documentos de pedidos de repuestos'}
CAPTION = 'Firma visual de identificación de PC-DOCTOR S.A. · No constituye firma electrónica de este documento.'
DEFAULTS = {'enabled': False, 'version_id': None, 'docs': {k: False for k in DOCS}, 'a4_width_mm': 50, 'ticket_width_mm': 48, 'align': 'derecha', 'ticket_mode': 'columna'}
A4_WIDTHS = range(25, 91)
TICKET_WIDTHS = range(30, 73)  # área útil del rollo de 80 mm: 72 mm
# 1.5.272 · Ticket: «columna» = en el espacio «Recibido por PC-DOCTOR S.A.» (junto a la firma del cliente, ancho máximo de la columna);
# «ancho» = debajo de ambas firmas, al ancho configurado (para un QR más grande); «omitir» = sin firma visual en el ticket.
TICKET_MODES = {'columna': 'Junto a «Recibido por» (compacto)', 'ancho': 'Debajo de las firmas, más grande', 'omitir': 'Omitir en el ticket'}
TICKET_COLUMN_MM = 33  # media columna del área útil de 72 mm
MIN_QR_DOTS = 3  # puntos de impresora por módulo del QR por debajo de los cuales la lectura no es fiable
MIN_QR_MM = 0.33  # tamaño mínimo de módulo en A4
DOTS_PER_MM = 8  # Epson TM-m30II: 203 ppp
MAX_BYTES = 2_000_000
PT_PER_MM = 72 / 25.4
CONNECT = None  # app.py asigna su conexión; los generadores de PDF no reciben la base de datos


class SignatureError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---- Configuración -----------------------------------------------------------------------------------------------------------------

def settings(c):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (KEY,)).fetchone()
    data = dict(DEFAULTS, docs=dict(DEFAULTS['docs']))
    if row:
        try:
            saved = json.loads(row['value'] if hasattr(row, 'keys') else row[0])
            data.update({k: v for k, v in saved.items() if k in DEFAULTS and k != 'docs'})
            data['docs'].update({k: bool(v) for k, v in (saved.get('docs') or {}).items() if k in DOCS})
            if data['ticket_mode'] == 'bn':  # 1.5.271: «imprimir en blanco y negro» ahora es la disposición compacta en columna
                data['ticket_mode'] = 'columna'
        except (ValueError, TypeError, AttributeError):
            pass
    return data


def _save(c, data):
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY, json.dumps(data)))


def update(c, data, user, audit):
    if user['role'] != 'administrador':
        raise SignatureError('Solo administración configura la firma empresarial.', 403)
    current = settings(c)
    if 'enabled' in data:
        current['enabled'] = data.get('enabled') is True
    if 'docs' in data:
        try:
            docs = json.loads(data['docs']) if isinstance(data['docs'], str) else dict(data['docs'])
        except (ValueError, TypeError):
            raise SignatureError('Selección de documentos no válida.')
        if any(k not in DOCS for k in docs):
            raise SignatureError('Hay documentos que no admiten la firma visual.')
        current['docs'].update({k: bool(v) for k, v in docs.items()})
    for key, allowed in (('a4_width_mm', A4_WIDTHS), ('ticket_width_mm', TICKET_WIDTHS)):
        if key in data:
            value = str(data.get(key, ''))
            if not value.isdigit() or int(value) not in allowed:
                raise SignatureError('El ancho debe estar entre %d y %d mm.' % (allowed.start, allowed.stop - 1))
            current[key] = int(value)
    if 'align' in data:
        if data['align'] not in ('izquierda', 'centro', 'derecha'):
            raise SignatureError('Alineación no válida.')
        current['align'] = data['align']
    if 'ticket_mode' in data:
        if data['ticket_mode'] not in TICKET_MODES:
            raise SignatureError('Opción del ticket no válida.')
        current['ticket_mode'] = data['ticket_mode']
    if 'version_id' in data:
        vid = str(data.get('version_id', ''))
        if not vid.isdigit() or not c.execute('SELECT 1 FROM business_signature_versions WHERE id=?', (int(vid),)).fetchone():
            raise SignatureError('Versión de la firma no encontrada.', 404)
        current['version_id'] = int(vid)
    if current['enabled'] and not current['version_id']:
        raise SignatureError('Carga primero la imagen de la firma.')
    _save(c, current)
    audit(c, user['id'], 'business_signature_settings', current['version_id'])
    return current


# ---- Imagen ------------------------------------------------------------------------------------------------------------------------

def _png(data):
    """(ancho, alto, rgb, alpha|None) de un PNG de 8 bits (escala de grises, RGB, con alfa o paleta), sin entrelazado."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise SignatureError('El archivo no es un PNG válido.')
    pos, idat, palette, trns = 8, [], b'', b''
    width = height = depth = color = interlace = None
    while pos < len(data):
        size = struct.unpack('>I', data[pos:pos + 4])[0]
        kind, chunk = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + size]
        pos += size + 12
        if kind == b'IHDR':
            width, height, depth, color, _, _, interlace = struct.unpack('>IIBBBBB', chunk)
        elif kind == b'PLTE':
            palette = chunk
        elif kind == b'tRNS':
            trns = chunk
        elif kind == b'IDAT':
            idat.append(chunk)
    if not width or interlace or color not in (0, 2, 3, 4, 6) or (depth != 8 and not (color in (0, 3) and depth in (1, 2, 4))):
        raise SignatureError('Usa un PNG de 8 bits sin entrelazado (o JPEG).')
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    bpp = max(1, channels * depth // 8)
    stride = (width * channels * depth + 7) // 8
    raw = zlib.decompress(b''.join(idat))
    rows, prev, at = [], bytearray(stride), 0
    for _ in range(height):
        kind, line = raw[at], bytearray(raw[at + 1:at + 1 + stride])
        at += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            cc = prev[i - bpp] if i >= bpp else 0
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - cc
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - cc)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else cc)) & 255
        rows.append(bytes(line))
        prev = line
    rgb, alpha, has_alpha = bytearray(), bytearray(), color in (4, 6) or bool(trns)
    for line in rows:
        if color == 3:
            if depth < 8:
                per = 8 // depth
                idx = [(line[x // per] >> (8 - depth * (x % per + 1))) & ((1 << depth) - 1) for x in range(width)]
            else:
                idx = line[:width]
            for i in idx:
                rgb += palette[i * 3:i * 3 + 3] or b'\0\0\0'
                alpha.append(trns[i] if i < len(trns) else 255)
        elif color == 0:
            if depth < 8:
                per, top = 8 // depth, (1 << depth) - 1
                values = [((line[x // per] >> (8 - depth * (x % per + 1))) & top) * 255 // top for x in range(width)]
            else:
                values = line[:width]
            for v in values:
                rgb += bytes((v, v, v))
                alpha.append(255)
        elif color == 4:
            for x in range(width):
                v = line[2 * x]
                rgb += bytes((v, v, v))
                alpha.append(line[2 * x + 1])
        elif color == 2:
            rgb += line[:3 * width]
            alpha.extend(b'\xff' * width)
        else:
            for x in range(width):
                rgb += line[4 * x:4 * x + 3]
                alpha.append(line[4 * x + 3])
    return width, height, bytes(rgb), bytes(alpha) if has_alpha else None


def _jpeg_size(data):
    if data[:2] != b'\xff\xd8':
        raise SignatureError('El archivo no es un JPEG válido.')
    pos = 2
    while pos < len(data) - 9:
        if data[pos] != 0xff:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xc0, 0xc1, 0xc2):
            height, width = struct.unpack('>HH', data[pos + 5:pos + 9])
            comps = data[pos + 9]
            if comps not in (1, 3):
                raise SignatureError('Usa un JPEG en color RGB o escala de grises (no CMYK).')
            return width, height, comps
        pos += 2 + struct.unpack('>H', data[pos + 2:pos + 4])[0]
    raise SignatureError('No se pudo leer el tamaño del JPEG.')


def upload(c, filename, content, user, now, audit):
    if user['role'] != 'administrador':
        raise SignatureError('Solo administración puede cargar o reemplazar la firma empresarial.', 403)
    try:
        data = base64.b64decode(str(content or ''), validate=True)
    except (ValueError, TypeError):
        raise SignatureError('El archivo no se pudo leer.')
    if not data or len(data) > MAX_BYTES:
        raise SignatureError('Carga una imagen PNG o JPEG de hasta 2 MB.')
    rgb = alpha = None
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        mime = 'image/png'
        width, height, raw_rgb, raw_alpha = _png(data)
        rgb, alpha = zlib.compress(raw_rgb, 9), zlib.compress(raw_alpha, 9) if raw_alpha else None
    elif data[:2] == b'\xff\xd8':
        mime = 'image/jpeg'
        width, height, _ = _jpeg_size(data)
    else:
        raise SignatureError('Carga una imagen PNG o JPEG.')
    if width < 80 or height < 30 or width > 6000 or height > 6000:
        raise SignatureError('La imagen debe medir entre 80×30 y 6000×6000 píxeles.')
    sha = hashlib.sha256(data).hexdigest()
    same = c.execute('SELECT id FROM business_signature_versions WHERE sha256=?', (sha,)).fetchone()
    if same:
        vid = same['id']
    else:
        name = re.sub(r'[^\w .()-]+', '', str(filename or ''))[:120] or 'firma'
        vid = c.execute('INSERT INTO business_signature_versions(filename,mime,data,size,sha256,width,height,rgb,alpha,uploaded_by,uploaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (name, mime, data, len(data), sha, width, height, rgb, alpha, user['id'], now.isoformat(timespec='seconds'))).lastrowid
        audit(c, user['id'], 'business_signature_uploaded', vid)
    current = settings(c)
    if not current['version_id']:  # la primera carga queda seleccionada, pero la firma sigue desactivada hasta que se active
        current['version_id'] = vid
        _save(c, current)
    return {'id': vid, 'duplicate': bool(same)}


def versions(c):
    return [dict(r) for r in c.execute("SELECT v.id,v.filename,v.mime,v.size,v.sha256,v.width,v.height,v.uploaded_at,COALESCE(u.name,'') uploader "
                                       'FROM business_signature_versions v LEFT JOIN users u ON u.id=v.uploaded_by ORDER BY v.id DESC')]


def overview(c):
    data = settings(c)
    rows = versions(c)
    check = {'qr_detected': False, 'warnings': []}
    if data['version_id']:
        try:
            check = legibility(preview_sig(c))
        except Exception:
            pass
    return {'settings': data, 'versions': rows, 'current': next((v for v in rows if v['id'] == data['version_id']), None), 'legibility': check,
            'ticket_modes': TICKET_MODES, 'ticket_column_mm': TICKET_COLUMN_MM,
            'docs': [{'key': k, 'label': v, 'available': True, 'enabled': data['docs'].get(k, False)} for k, v in DOCS.items()] +
                    [{'key': k, 'label': v, 'available': False, 'enabled': False} for k, v in UNAVAILABLE.items()],
            'caption': CAPTION, 'limits': {'a4': [A4_WIDTHS.start, A4_WIDTHS.stop - 1], 'ticket': [TICKET_WIDTHS.start, TICKET_WIDTHS.stop - 1]}}


def original(c, vid):
    row = c.execute('SELECT mime,data,filename FROM business_signature_versions WHERE id=?', (vid,)).fetchone()
    return (row['mime'], bytes(row['data']), row['filename']) if row else None


# ---- Representaciones de impresión ------------------------------------------------------------------------------------------------

_IMAGES = {}


def _image(vid, sha, c=None):
    """Datos de una versión listos para dibujar (se cachean por versión y huella; una ausencia no se cachea). c permite leer con la
    conexión en curso (p. ej. justo después de cargarla, antes de confirmar la transacción)."""
    key = (vid, sha)
    if key in _IMAGES:
        return _IMAGES[key]
    if c is None:
        with CONNECT() as conn:
            row = conn.execute('SELECT mime,data,width,height,rgb,alpha FROM business_signature_versions WHERE id=? AND sha256=?', (vid, sha)).fetchone()
    else:
        row = c.execute('SELECT mime,data,width,height,rgb,alpha FROM business_signature_versions WHERE id=? AND sha256=?', (vid, sha)).fetchone()
    if not row:
        return None
    if row['mime'] == 'image/jpeg':
        comps = _jpeg_size(bytes(row['data']))[2]
        image = {'kind': 'jpeg', 'w': row['width'], 'h': row['height'], 'jpeg': bytes(row['data']), 'comps': comps}
    else:
        image = {'kind': 'png', 'w': row['width'], 'h': row['height'], 'rgb': zlib.decompress(row['rgb']), 'alpha': zlib.decompress(row['alpha']) if row['alpha'] else None}
    while len(_IMAGES) >= 8:
        _IMAGES.pop(next(iter(_IMAGES)))
    _IMAGES[key] = image
    return image


def qr_module_px(image):
    """Tamaño en píxeles de un módulo del QR de la imagen (por sus patrones de esquina 1:1:3:1:1), o None si no se detecta un QR."""
    w, h = image['w'], image['h']
    if image['kind'] != 'png':
        return None
    rgb, alpha = image['rgb'], image['alpha']
    found = []
    for y in range(0, h, max(1, h // 120)):
        runs, last, start = [], None, 0
        for x in range(w):
            i = y * w + x
            lum = (rgb[3 * i] * 299 + rgb[3 * i + 1] * 587 + rgb[3 * i + 2] * 114) // 1000
            a = alpha[i] if alpha else 255
            dark = (lum * a + 255 * (255 - a)) // 255 < 128
            if dark != last:
                if last is not None:
                    runs.append((last, x - start))
                last, start = dark, x
        runs.append((last, w - start))
        for k in range(len(runs) - 4):
            seq = runs[k:k + 5]
            if not seq[0][0] or [d for d, _ in seq] != [True, False, True, False, True]:
                continue
            unit = sum(n for _, n in seq) / 7
            if unit >= 1 and all(abs(n - e * unit) <= unit * .6 for (_, n), e in zip(seq, (1, 1, 3, 1, 1))):
                found.append(unit)
    if len(found) < 3:
        return None
    found.sort()
    return found[len(found) // 2]


def ticket_width_pt(sig):
    """Ancho de la firma en el ticket según la disposición elegida (en columna nunca supera media columna)."""
    mm = sig['ticket_width_mm'] if sig.get('ticket_mode') == 'ancho' else min(sig['ticket_width_mm'], TICKET_COLUMN_MM)
    return mm * PT_PER_MM


def legibility(sig):
    """Avisos solo cuando el QR de la imagen quedaría demasiado pequeño (ticket o A4). Lista vacía si todo está bien o no hay QR."""
    image = sig['image']
    module = qr_module_px(image)
    out = {'qr_detected': bool(module), 'warnings': []}
    if not module:
        return out
    if sig.get('ticket_mode') != 'omitir':
        dots = module * (ticket_width_pt(sig) / PT_PER_MM * DOTS_PER_MM) / image['w']
        out['ticket_dots'] = round(dots, 1)
        if dots < MIN_QR_DOTS:
            out['warnings'].append('En el ticket cada módulo del QR mide %.1f puntos de impresora: puede no leerse. Usa «Debajo de las firmas, más grande» con más ancho, u omite la firma en el ticket.' % dots)
    a4_mm = module * sig['a4_width_mm'] / image['w']
    out['a4_module_mm'] = round(a4_mm, 2)
    if a4_mm < MIN_QR_MM:
        out['warnings'].append('En A4 cada módulo del QR mide %.2f mm: aumenta el ancho en documentos A4 para que se pueda leer.' % a4_mm)
    return out


def thermal_bitmap(image, dots):
    """(ancho, alto, gris 8 bits) en blanco y negro al ancho de impresión, sin deformar: promedio por área y umbral (bordes nítidos del QR)."""
    w, h = image['w'], image['h']
    tw = max(1, min(dots, w))
    th = max(1, round(h * tw / w))
    rgb, alpha = image['rgb'], image['alpha']
    out = bytearray(tw * th)
    for ty in range(th):
        y0, y1 = ty * h // th, max(ty * h // th + 1, (ty + 1) * h // th)
        for tx in range(tw):
            x0, x1 = tx * w // tw, max(tx * w // tw + 1, (tx + 1) * w // tw)
            total = count = 0
            for y in range(y0, y1):
                base = y * w
                for x in range(x0, x1):
                    i = base + x
                    lum = (rgb[3 * i] * 299 + rgb[3 * i + 1] * 587 + rgb[3 * i + 2] * 114) // 1000
                    a = alpha[i] if alpha else 255
                    total += (lum * a + 255 * (255 - a)) // 255
                    count += 1
            out[ty * tw + tx] = 0 if total < 160 * count else 255
    return tw, th, bytes(out)


@lru_cache(maxsize=8)
def _thermal(vid, sha, dots):
    image = _image(vid, sha)
    if not image or image['kind'] != 'png':
        raise SignatureError('Sin imagen PNG para el ticket.', 404)  # se lanza (no se cachea) en vez de devolver None
    return thermal_bitmap(image, dots)


def for_doc(kind):
    """Configuración e imagen para un documento, o None si no corresponde ponerla (desactivada, sin imagen u omitida en el ticket)."""
    if CONNECT is None or kind not in DOCS:
        return None
    try:
        with CONNECT() as c:
            data = settings(c)
            if not data['enabled'] or not data['docs'].get(kind) or not data['version_id']:
                return None
            if kind == 'ticket' and data['ticket_mode'] == 'omitir':
                return None
            row = c.execute('SELECT id,sha256 FROM business_signature_versions WHERE id=?', (data['version_id'],)).fetchone()
        if not row:
            return None
        image = _image(row['id'], row['sha256'])
        if not image:
            return None
        return dict(data, kind=kind, image=image, vid=row['id'], sha=row['sha256'])
    except Exception as error:  # una falla de la firma nunca impide emitir el documento
        print('business-signature', type(error).__name__, flush=True)
        return None


def _xobject(pdf, sig, thermal=False):
    """Objeto de imagen en el PDF (uno por documento y variante)."""
    import pydyf
    cache = pdf.__dict__.setdefault('_business_signature', {})
    key = 'thermal' if thermal else 'a4'
    if key in cache:
        return cache[key]
    image = sig['image']
    if thermal and image['kind'] == 'png':
        tw, th, gray = _thermal(sig['vid'], sig['sha'], round(ticket_width_pt(sig) / PT_PER_MM * DOTS_PER_MM))
        stream = pydyf.Stream([gray], extra={'Type': '/XObject', 'Subtype': '/Image', 'Width': tw, 'Height': th, 'ColorSpace': '/DeviceGray',
                                             'BitsPerComponent': 8, 'Interpolate': 'false'}, compress=True)
        pdf.add_object(stream)
        cache[key] = (stream, tw, th)
        return cache[key]
    if image['kind'] == 'jpeg':
        stream = pydyf.Stream([image['jpeg']], extra={'Type': '/XObject', 'Subtype': '/Image', 'Width': image['w'], 'Height': image['h'],
                                                      'ColorSpace': '/DeviceRGB' if image['comps'] == 3 else '/DeviceGray', 'BitsPerComponent': 8, 'Filter': '/DCTDecode'})
    else:
        # Sin suavizado: los bordes del QR quedan nítidos al ampliar o reducir. Compresión sin pérdida (Flate).
        extra = {'Type': '/XObject', 'Subtype': '/Image', 'Width': image['w'], 'Height': image['h'], 'ColorSpace': '/DeviceRGB', 'BitsPerComponent': 8, 'Interpolate': 'false'}
        if image['alpha']:
            mask = pydyf.Stream([image['alpha']], extra={'Type': '/XObject', 'Subtype': '/Image', 'Width': image['w'], 'Height': image['h'],
                                                         'ColorSpace': '/DeviceGray', 'BitsPerComponent': 8}, compress=True)
            pdf.add_object(mask)
            extra['SMask'] = mask.reference
        stream = pydyf.Stream([image['rgb']], extra=extra, compress=True)
    pdf.add_object(stream)
    cache[key] = (stream, image['w'], image['h'])
    return cache[key]


def size_pt(sig, thermal=False):
    """(ancho, alto) en puntos al ancho configurado, conservando la proporción."""
    width = ticket_width_pt(sig) if thermal else sig['a4_width_mm'] * PT_PER_MM
    return width, width * sig['image']['h'] / sig['image']['w']


def draw(pdf, stream, resources, page_h, x, y, sig, thermal=False, width=None):
    """Dibuja la imagen con su borde superior en y (medido desde arriba). Devuelve su alto en puntos. thermal=True usa la representación
    en blanco y negro para la impresora; si no, el original a color. width fija el ancho (el alto conserva la proporción)."""
    import pydyf
    obj, _, _ = _xobject(pdf, sig, thermal)
    xobjects = resources.get('XObject')
    if xobjects is None:
        xobjects = pydyf.Dictionary({})
        resources['XObject'] = xobjects
    xobjects['FirmaVisual' + ('T' if thermal else '')] = obj.reference
    w, h = size_pt(sig, thermal)
    if width:
        w, h = width, width * sig['image']['h'] / sig['image']['w']
    stream.push_state()
    stream.set_matrix(w, 0, 0, h, x, page_h - y - h)
    stream.draw_x_object('FirmaVisual' + ('T' if thermal else ''))
    stream.pop_state()
    return h


def x_for(sig, left, right, thermal=False):
    w = size_pt(sig, thermal)[0]
    if thermal or sig['align'] == 'centro':
        return left + (right - left - w) / 2
    return left if sig['align'] == 'izquierda' else right - w


def preview_sig(c):
    """Firma seleccionada con su configuración, sin exigir que esté activada (solo para la vista previa de Configuración)."""
    data = settings(c)
    if not data['version_id']:
        raise SignatureError('Carga primero la imagen de la firma.', 409)
    row = c.execute('SELECT id,sha256 FROM business_signature_versions WHERE id=?', (data['version_id'],)).fetchone()
    image = _image(row['id'], row['sha256'], c) if row else None
    if not image:
        raise SignatureError('Carga primero la imagen de la firma.', 409)
    return dict(data, kind='preview', image=image, vid=row['id'], sha=row['sha256'])


def preview_pdf(c, target):
    """PDF de muestra (sin datos de clientes) para ver la firma en A4 o en el ticket de 80 mm antes de activarla."""
    import io
    import pydyf
    from document_canvas import Canvas, BLUE, GRAY
    sig = preview_sig(c)
    if target in ('ticket', 'ticket-digital'):
        thermal = target == 'ticket' and sig['image']['kind'] == 'png'
        width = 72 * PT_PER_MM
        w, h = size_pt(sig, True)
        pdf = Canvas(width, h + 74, 'Vista previa · firma visual en ticket (' + ('impresión térmica' if thermal else 'digital a color') + ')', mono=thermal)
        pdf.page()
        pdf.text('VISTA PREVIA · ' + ('TICKET TÉRMICO (BLANCO Y NEGRO)' if thermal else 'TICKET DIGITAL (COLOR)'), 6, 8, 7, True)
        draw(pdf.pdf, pdf.stream, pdf.resources, pdf.h, (width - w) / 2, 22, sig, thermal=thermal)
        y = 22 + h + 4
        for line in pdf.wrap(CAPTION, width - 12, 5.8):
            pdf.text(line, 6, y, 5.8)
            y += 7.5
        return pdf.finish()
    pdf = Canvas(595.28, 841.89, 'Vista previa · firma visual en documentos A4')
    pdf.page()
    pdf.logo(42, 26, 60)
    pdf.text('VISTA PREVIA DE LA FIRMA VISUAL', 114, 34, 14, True, BLUE)
    pdf.text('Documento de muestra sin datos de clientes. Así aparecerá la firma al final de los documentos elegidos.', 114, 54, 8.5, False, GRAY)
    pdf.line(42, 92, 511)
    for i, line in enumerate(pdf.wrap('Contenido del documento de muestra. ' * 18, 511, 9)):
        pdf.text(line, 42, 110 + i * 13, 9, False, GRAY)
    pdf.business_signature('preview', 210, 800, left=42, right=553, sig=sig)
    return pdf.finish()


def png_bytes(width, height, gray):
    """PNG en escala de grises (vista previa de la impresión térmica)."""
    raw = b''.join(b'\x00' + gray[y * width:(y + 1) * width] for y in range(height))

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')


def thermal_preview(c, vid, width_mm):
    row = c.execute('SELECT id,sha256,mime FROM business_signature_versions WHERE id=?', (vid,)).fetchone()
    if not row:
        raise SignatureError('Versión no encontrada.', 404)
    if row['mime'] != 'image/png':
        raise SignatureError('La vista previa en blanco y negro está disponible para imágenes PNG; un JPEG lo convierte a gris el controlador de la impresora.', 409)
    tw, th, gray = _thermal(row['id'], row['sha256'], int(width_mm) * DOTS_PER_MM)
    return png_bytes(tw, th, gray)
