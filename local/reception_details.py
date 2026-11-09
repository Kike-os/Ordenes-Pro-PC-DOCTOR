"""Recepción técnica estructurada (1.5.262): inspección física, control del cargador y accesorios recibidos.

- Se guarda en orders.reception_details (JSON) y, además, se compone en los textos de siempre (physical_condition y accessories), que usan
  el comprobante de ingreso, la hoja A4 y las órdenes anteriores. Las órdenes antiguas (sin JSON) siguen igual.
- Las opciones dependen del tipo de equipo (p. ej., bisagras y touchpad solo en portátiles). «Sin daños visibles» excluye cualquier daño.
- Accesorio NO entregado ≠ accesorio recibido con daños: solo se registra lo recibido, con su cantidad y su estado aparente.
- Los textos describen lo observado («en buen estado aparente»); nunca afirman que algo funciona si no se probó, ni inventan diagnósticos."""
import json
import re

# Familias de equipo (los tipos de reception.DEVICE_TYPES se agrupan aquí).
FAMILY = {'portatil': 'laptop', 'notebook': 'laptop', 'gaming': 'laptop', 'escritorio': 'desktop', 'mini_pc': 'desktop', 'servidor': 'desktop',
          'aio': 'aio', 'aio_hp': 'aio', 'aio_lenovo': 'aio', 'aio_dell': 'aio', 'tablet': 'mobile', 'celular': 'mobile', 'impresora': 'printer',
          'monitor': 'monitor', 'mouse': 'peripheral', 'teclado': 'peripheral', 'hdd': 'storage', 'ssd': 'storage', 'router': 'network',
          'consola': 'console', 'otro': 'other'}
ALL = ('laptop', 'desktop', 'aio', 'mobile', 'printer', 'monitor', 'peripheral', 'storage', 'network', 'console', 'other')
SCREEN = ('laptop', 'aio', 'mobile', 'monitor', 'other')
POWERED = ('laptop', 'desktop', 'aio', 'mobile', 'printer', 'monitor', 'network', 'console', 'other')

# Zonas de inspección: (código, título, familias). Cada daño: (código, etiqueta, zona).
ZONES = (('general', 'Estado general', ALL), ('carcasa', 'Carcasa', ALL), ('pantalla', 'Pantalla', SCREEN),
         ('bisagras', 'Bisagras', ('laptop', 'other')), ('faltantes', 'Tornillos, tapas y gomas', ALL),
         ('puertos', 'Puertos', ('laptop', 'desktop', 'aio', 'mobile', 'printer', 'monitor', 'network', 'console', 'storage', 'other')),
         ('teclado', 'Teclado', ('laptop', 'peripheral', 'other')), ('touchpad', 'Touchpad', ('laptop', 'other')),
         ('bateria', 'Batería', ('laptop', 'mobile', 'other')), ('humedad', 'Humedad y manipulación', ALL), ('encendido', 'Encendido', POWERED))
DAMAGES = (
    ('sin_danos', 'Sin daños visibles', 'general'),
    ('carcasa_rota', 'Carcasa rota', 'carcasa'), ('carcasa_deformada', 'Carcasa deformada', 'carcasa'),
    ('piezas_desprendidas', 'Piezas desprendidas', 'carcasa'), ('golpes_rayones', 'Golpes o rayones', 'carcasa'),
    ('pantalla_rayas', 'Pantalla con rayas', 'pantalla'), ('pantalla_manchas', 'Pantalla con manchas', 'pantalla'),
    ('pantalla_pixeles', 'Píxeles dañados', 'pantalla'), ('pantalla_rota', 'Pantalla rota', 'pantalla'),
    ('bisagra_floja', 'Bisagras flojas', 'bisagras'), ('bisagra_dura', 'Bisagras duras', 'bisagras'),
    ('bisagra_rota', 'Bisagras rotas', 'bisagras'), ('bisagra_desprendida', 'Bisagras desprendidas', 'bisagras'),
    ('faltan_tornillos', 'Faltan tornillos', 'faltantes'), ('faltan_tapas', 'Faltan tapas', 'faltantes'), ('faltan_gomas', 'Faltan gomas', 'faltantes'),
    ('puerto_usb', 'Puerto USB dañado', 'puertos'), ('puerto_hdmi', 'Puerto HDMI dañado', 'puertos'),
    ('puerto_audio', 'Puerto de audio dañado', 'puertos'), ('puerto_alimentacion', 'Puerto de alimentación dañado', 'puertos'),
    ('teclas_desprendidas', 'Teclas desprendidas', 'teclado'), ('teclado_danado', 'Teclado dañado', 'teclado'),
    ('touchpad_danado', 'Touchpad dañado', 'touchpad'),
    ('bateria_hinchada', 'Batería hinchada o carcasa levantada', 'bateria'),
    ('humedad', 'Señales de humedad', 'humedad'), ('corrosion', 'Corrosión', 'humedad'), ('manipulacion', 'Señales de manipulación previa', 'humedad'),
    ('no_enciende', 'No enciende', 'encendido'), ('encendido_intermitente', 'Encendido intermitente', 'encendido'),
)
DAMAGE = {code: (label, zone) for code, label, zone in DAMAGES}
ZONE = {code: (title, families) for code, title, families in ZONES}

CHARGER_STATUS = {'no_entregado': 'No entregado por el cliente', 'buen_estado': 'Recibido en buen estado aparente', 'con_danos': 'Recibido con daños',
                  'pendiente_revision': 'Pendiente de revisión técnica'}
CHARGER_DEFECTS = {'cable': 'Cable pelado, cortado o deteriorado', 'punta': 'Punta de carga rota, doblada o floja', 'carcasa': 'Carcasa del adaptador rota',
                   'falso_contacto': 'Conector con falso contacto', 'sin_voltaje': 'No entrega voltaje al verificarlo'}
NO_CHARGER_NOTE = 'El equipo fue recibido sin cargador. Las pruebas de alimentación quedan sujetas a la disponibilidad de una fuente compatible.'

ACCESSORIES = (('cable_poder', 'Cable de poder'), ('mouse_receptor', 'Mouse y receptor USB'), ('adaptadores', 'Adaptadores y convertidores'),
               ('memorias', 'Memorias USB y discos externos'), ('baterias', 'Baterías removibles'), ('cables_video', 'Cables de video y datos'),
               ('soportes', 'Soportes y bases'), ('mochila', 'Mochila'), ('funda', 'Funda'), ('caja', 'Caja original'))
ACCESSORY = dict(ACCESSORIES)
ACCESSORY_STATE = {'buen_estado': 'buen estado aparente', 'con_danos': 'con daños'}

PHOTO_CATEGORIES = {'recepcion': 'Recepción', 'diagnostico': 'Diagnóstico', 'reparacion': 'Reparación', 'entrega': 'Entrega'}


def family(device_type):
    return FAMILY.get(str(device_type or ''), 'other')


def catalog():
    """Catálogo para la interfaz (las familias indican dónde aplica cada zona)."""
    return {'zones': [{'code': c, 'title': t, 'families': list(f)} for c, t, f in ZONES],
            'damages': [{'code': c, 'label': l, 'zone': z} for c, l, z in DAMAGES],
            'family': FAMILY, 'charger_status': CHARGER_STATUS, 'charger_defects': CHARGER_DEFECTS, 'charger_families': list(POWERED),
            'accessories': [{'code': c, 'label': l} for c, l in ACCESSORIES], 'accessory_states': ACCESSORY_STATE,
            'photo_categories': PHOTO_CATEGORIES, 'no_charger_note': NO_CHARGER_NOTE}


def _text(value, limit):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def parse(raw, device_type):
    """Valida y normaliza el JSON enviado por la recepción. Devuelve (detalle o None, errores). Ignora opciones que no aplican al equipo."""
    if raw in (None, '', {}):
        return None, {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return None, {'reception_details': 'Los datos de la inspección no son válidos. Recarga la página.'}
    fam = family(device_type)
    errors = {}
    damages = []
    for item in (data.get('damages') or [])[:40]:
        code = str((item or {}).get('code', ''))
        if code not in DAMAGE or fam not in ZONE[DAMAGE[code][1]][1] or any(d['code'] == code for d in damages):
            continue
        damages.append({'code': code, 'location': _text(item.get('location'), 80)})
    if any(d['code'] == 'sin_danos' for d in damages) and len(damages) > 1:
        errors['physical_condition'] = '«Sin daños visibles» no puede combinarse con daños. Quita una de las dos opciones.'
    charger = None
    if fam in POWERED and data.get('charger'):
        ch = data['charger'] or {}
        status = str(ch.get('status', ''))
        if status not in CHARGER_STATUS:
            errors['charger'] = 'Indica el estado del cargador.'
        else:
            defects = [d for d in dict.fromkeys(str(x) for x in (ch.get('defects') or [])) if d in CHARGER_DEFECTS] if status == 'con_danos' else []
            other = _text(ch.get('other'), 200) if status == 'con_danos' else ''
            if status == 'con_danos' and not defects and not other:
                errors['charger'] = 'Indica qué daño tiene el cargador.'
            charger = {'status': status, 'defects': defects, 'other': other}
            if status != 'no_entregado':
                charger.update({k: _text(ch.get(k), 40) for k in ('brand', 'power', 'voltage', 'serial')})
                if charger['serial'] and not re.fullmatch(r'[A-Za-z0-9 ./-]+', charger['serial']):
                    errors['charger'] = 'El número de serie del cargador solo admite letras, números, puntos y guiones.'
    accessories = []
    for item in (data.get('accessories') or [])[:30]:
        code = str((item or {}).get('code', ''))
        label = ACCESSORY.get(code) or (_text(item.get('label'), 60) if code == 'otro' else '')
        if not label:
            continue
        try:
            qty = int(item.get('qty') or 1)
        except (TypeError, ValueError):
            qty = 0
        if not 1 <= qty <= 20:
            errors['accessories'] = 'La cantidad de cada accesorio debe estar entre 1 y 20.'
            qty = max(1, min(20, qty or 1))
        state = str(item.get('state') or 'buen_estado')
        if state not in ACCESSORY_STATE:
            state = 'buen_estado'
        accessories.append({'code': code, 'label': label, 'qty': qty, 'state': state, 'note': _text(item.get('note'), 120)})
    out = {'version': 1, 'family': fam, 'damages': damages, 'charger': charger, 'accessories': accessories}
    return out, errors


def _dmg(d):
    label = DAMAGE[d['code']][0]
    return label + (' (' + d['location'] + ')' if d.get('location') else '')


def inspection_text(details):
    """«Inspección inicial: …» agrupado por zona, con la ubicación de cada daño."""
    if not details or not details.get('damages'):
        return ''
    if details['damages'][0]['code'] == 'sin_danos' and len(details['damages']) == 1:
        return 'Inspección inicial: sin daños visibles.'
    by_zone = {}
    for d in details['damages']:
        by_zone.setdefault(DAMAGE[d['code']][1], []).append(_dmg(d))
    parts = ['%s: %s' % (ZONE[z][0], ', '.join(v).replace(ZONE[z][0] + ' ', '')) for z, v in by_zone.items()]
    return 'Inspección inicial: ' + '; '.join(parts) + '.'


def charger_text(details):
    ch = (details or {}).get('charger')
    if not ch:
        return ''
    if ch['status'] == 'no_entregado':
        return NO_CHARGER_NOTE
    text = 'Cargador: ' + CHARGER_STATUS[ch['status']].lower()
    found = [CHARGER_DEFECTS[d].lower() for d in ch.get('defects') or []] + ([ch['other']] if ch.get('other') else [])
    if found:
        text += ' (' + '; '.join(found) + ')'
    data = [('marca', ch.get('brand')), ('potencia', ch.get('power')), ('voltaje', ch.get('voltage')), ('S/N', ch.get('serial'))]
    data = ['%s %s' % (k, v) for k, v in data if v]
    if data:
        text += ' · ' + ', '.join(data)
    return text + '.'


def accessories_text(details):
    items = (details or {}).get('accessories') or []
    if not items:
        return ''
    return ', '.join('%s%s (%s%s)' % (a['label'], ' ×%d' % a['qty'] if a['qty'] > 1 else '', ACCESSORY_STATE[a['state']], ': ' + a['note'] if a.get('note') else '') for a in items)


def merge_condition(text, details):
    """Texto de estado físico: lo escrito por el técnico, más la inspección y el cargador si no están ya. Nunca borra lo escrito."""
    text = str(text or '').strip()
    lines = [l for l in text.split('\n') if not l.startswith('Inspección inicial:') and not l.startswith('Cargador:') and l.strip() != NO_CHARGER_NOTE]
    head = [x for x in (inspection_text(details), charger_text(details)) if x]
    return '\n'.join(head + [l for l in lines if l.strip()]).strip()[:2000]


def dumps(details):
    return json.dumps(details, ensure_ascii=False, separators=(',', ':')) if details else ''


def loads(raw):
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


# ---- Fotos: nombres descriptivos ---------------------------------------------------------------------------------------------------------
def _slug(text, limit=24):
    import unicodedata
    text = unicodedata.normalize('NFD', str(text or ''))
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    text = re.sub(r'[^A-Za-z0-9]+', '-', text).strip('-')
    if len(text) > limit and '-' in text[:limit + 1]:
        return text[:limit + 1].rsplit('-', 1)[0].strip('-')  # sin partir una palabra
    return text[:limit].strip('-')


def photo_filename(code, brand, model, subject, number, category='', ext='jpg'):
    """Nombre descriptivo (1.5.265): PCD-20261109-0001_HP-240-G7_Recepcion_Frontal_01.jpg.

    Orden, equipo (marca y modelo unidos), categoría o etapa, tema de la foto y un número secuencial. Sin acentos ni espacios: solo letras,
    números, guiones y guiones bajos. No lleva nombre, contacto ni identificación del cliente."""
    device = '-'.join(p for p in (_slug(brand, 20), _slug(model, 24)) if p)
    small = {'y', 'e', 'o', 'u', 'de', 'del', 'la', 'el', 'los', 'las', 'a'}
    title = lambda slug: '-'.join(w if i and w.lower() in small else w[:1].upper() + w[1:] for i, w in enumerate(slug.split('-')))
    cat, sub = title(_slug(category, 40)), title(_slug(subject, 32))
    label = '_'.join(x for x in (cat, sub if sub.lower() != cat.lower() else '') if x) or 'General'
    parts = [_slug(code, 40) or 'orden', device, label]
    return '_'.join(p for p in parts if p) + '_%02d.%s' % (max(1, int(number)), ext)


SAFE_NAME = re.compile(r'[^A-Za-z0-9_-]+')


def safe_filename(name, ext):
    """Nombre escrito por el usuario, seguro para guardar: sin ruta, sin acentos ni caracteres especiales, con la extensión REAL del archivo
    (la que indica su contenido, no la que se escribió). '' si no queda nada utilizable."""
    import unicodedata
    base = str(name or '').replace('\\', '/').split('/')[-1].strip()
    base = re.sub(r'\.(jpe?g|png|webp|pdf|heic|gif)$', '', base, flags=re.I)
    base = unicodedata.normalize('NFD', base)
    base = ''.join(ch for ch in base if unicodedata.category(ch) != 'Mn')
    base = re.sub(r'-{2,}', '-', SAFE_NAME.sub('-', base)).strip('-_.')[:110].strip('-_')
    return base + '.' + ext if base else ''


def personal_terms(client):
    """Partes del nombre del cliente (de 4 letras o más) que no deben aparecer en un nombre de archivo."""
    words = [_slug(w).lower() for w in str(client or '').split()]
    return [w for w in words if len(w) >= 4]


def unique_filename(name, taken):
    """Devuelve `name` o, si ya existe (sin distinguir mayúsculas), la misma base con -2, -3…; nunca reemplaza un archivo anterior."""
    used = {str(t).lower() for t in taken if t}
    if name.lower() not in used:
        return name
    base, dot, ext = name.rpartition('.')
    for n in range(2, 1000):
        candidate = '%s-%d.%s' % (base, n, ext)
        if candidate.lower() not in used:
            return candidate
    raise ValueError('Demasiados archivos con el mismo nombre.')


class NameError_(ValueError):
    """Nombre de archivo no aceptado (mensaje para el usuario)."""


def original_name(value):
    """Nombre del archivo tal como lo eligió el usuario, solo como metadato (sin ruta ni caracteres de control; máximo 160)."""
    name = str(value or '').replace('\\', '/').split('/')[-1]
    return re.sub(r'[\x00-\x1f\x7f<>"]', '', name).strip()[:160]


def photo_name(c, oid, category, subject, custom='', exclude=None):
    """Nombre definitivo de una foto de la orden: el escrito por el usuario (seguro) o el sugerido; nunca repetido en la orden.
    El número es la secuencia de fotos de la orden (las retiradas cuentan: un número no se reutiliza)."""
    info = c.execute("SELECT o.code,d.brand,d.model,cl.name client FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?", (oid,)).fetchone()
    taken = [r[0] for r in c.execute('SELECT filename FROM order_photos WHERE order_id=? AND id!=?', (oid, exclude or 0))]
    if str(custom or '').strip():
        name = safe_filename(custom, 'jpg')
        if not name or len(name) < 8:
            raise NameError_('Escribe un nombre de al menos 3 letras o números para la foto.')
        low = name.lower()
        if any(term in low for term in personal_terms(info['client'])):
            raise NameError_('No incluyas el nombre del cliente en el nombre del archivo: usa la orden, el equipo y lo que muestra la foto.')
        return unique_filename(name, taken)
    number = c.execute('SELECT COUNT(*) FROM order_photos WHERE order_id=? AND id!=?', (oid, exclude or 0)).fetchone()[0] + 1
    title = PHOTO_CATEGORIES.get(category, '')
    return unique_filename(photo_filename(info['code'] or 'OP-%05d' % oid, info['brand'], info['model'], subject, number, title), taken)
