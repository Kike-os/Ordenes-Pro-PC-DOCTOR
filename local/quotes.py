"""Presupuestos profesionales de una orden: catálogo, versiones, estado por ítem, aprobación y evidencia.

- Los precios del catálogo incluyen IVA. El presupuesto guarda la tarifa vigente al crearse y desglosa base e impuesto.
- Cada presupuesto copia descripción y precio de sus ítems: cambiar el catálogo después no altera los ya emitidos.
- Las decisiones solo cambian mediante acciones registradas (cliente por enlace privado o personal con sesión).
- Una aprobación no cambia el estado de la orden ni inicia trabajos: el técnico confirma el inicio."""
import hashlib
import catalog_icons
import json
import re
import sqlite3
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

CATEGORIES = {'servicio': 'Servicios técnicos y reparaciones', 'licencia': 'Licencias de Windows y Office', 'seguridad': 'Antivirus y seguridad', 'repuesto': 'Repuestos y componentes', 'otro': 'Productos'}
# Categoría del presupuesto anterior de la orden a la que se traslada cada ítem aprobado (de ahí salen el total a cobrar y el saldo).
BUDGET_KEY = {'servicio': 'labor', 'repuesto': 'parts', 'licencia': 'digital', 'seguridad': 'digital', 'otro': 'services'}
STATUS = {'borrador': 'Borrador', 'enviado': 'Esperando aprobación', 'aprobado': 'Aprobado', 'parcial': 'Aprobado parcialmente', 'rechazado': 'Rechazado', 'modificacion': 'Revisión solicitada', 'cancelado': 'Cancelado'}
ITEM_STATUS = {'pendiente': 'Pendiente', 'aprobado': 'Aprobado', 'rechazado': 'Rechazado', 'cancelado': 'Cancelado'}
EDITABLE = ('borrador', 'modificacion')
EXECUTION = {'pendiente': 'Pendiente', 'proceso': 'En proceso', 'realizado': 'Finalizado'}
DECIDED = ('aprobado', 'parcial', 'rechazado')
# Clasificación de cada partida: informa al cliente qué tan necesaria es. No aprueba nada ni cambia precios. (etiqueta, color de pantalla, color RGB para el PDF)
PRIORITIES = {'necesario': ('Necesario', '#DC3545', (.86, .21, .27)), 'obligatorio': ('Obligatorio', '#F59E0B', (.80, .50, .02)), 'opcional': ('Opcional', '#38BDF8', (.07, .52, .78))}
DEFAULT_TAX_BP = 1500
PRICE_MODES = {'incluido': 'IVA incluido', 'agregar': 'Agregar IVA', 'sin_iva': 'Sin IVA (tarifa 0 %)'}
# Descuento autorizado: únicamente estas tres opciones; solo lo aplica administración.
DISCOUNTS = {0: 'Sin descuento', 300: 'Descuento especial', 500: 'Descuento máximo'}
IMAGE_LIMIT = 300000
DOCUMENT_LIMIT = 700000
DOCUMENT_NOTICE = ('Se solicita una copia de su documento de identidad únicamente para comprobar quién autoriza este presupuesto. '
                   'Solo la consulta el personal administrativo de PC-DOCTOR S.A., no se comparte con terceros y puede pedir su eliminación al taller.')
LINK_DAYS = 15
MAX_ITEMS = 60
MAX_FAILED = 6
METHOD = 'Enlace privado enviado al correo registrado y últimos cuatro dígitos de la identificación'
# Condiciones de aprobación y ejecución (texto entregado por la administración el 2026-10-13, sujeto a revisión legal). Cada cláusula es
# un título numerado seguido de su texto. Un presupuesto ya enviado conserva las condiciones con las que se envió.
CONDITIONS = '\n'.join((
    '1. Autorización del servicio',
    'Mediante la aceptación de este presupuesto, el cliente autoriza expresamente a PC-DOCTOR S.A. a ejecutar los productos y servicios seleccionados, conforme a los valores y condiciones indicados.',
    '2. Inicio de trabajos',
    'Los trabajos autorizados podrán programarse o iniciarse una vez registrada la aprobación del cliente y cumplidas las condiciones necesarias para su ejecución.',
    '3. Modificación o desistimiento',
    'Una vez aprobado el presupuesto, cualquier solicitud posterior de modificación, rechazo o cancelación deberá comunicarse a PC-DOCTOR S.A. para su evaluación según el estado de ejecución. La aprobación no podrá revertirse unilateralmente mediante la simple modificación del enlace cuando ya existan trabajos iniciados o compromisos de adquisición de repuestos, sin perjuicio de los derechos legales del consumidor.',
    '4. Trabajos y gastos realizados',
    'En caso de cancelación posterior, podrán liquidarse únicamente los trabajos efectivamente realizados, los gastos debidamente justificados y los demás importes legalmente procedentes.',
    '5. Servicios adicionales',
    'Cualquier servicio adicional que implique un costo no contemplado en el presupuesto aprobado requerirá una nueva autorización del cliente.',
    '6. Evidencia de aceptación',
    'La aprobación electrónica quedará vinculada al número y versión del presupuesto, con la evidencia correspondiente.',
    '7. Documento informativo',
    'Este presupuesto no constituye factura ni comprobante de venta autorizado por el SRI.'))


def clauses(text):
    """Condiciones como lista de (título, texto). Un renglón «N. Título» encabeza el renglón siguiente; las condiciones antiguas, sin títulos, quedan como ('', renglón)."""
    lines, out, index = [line.strip() for line in str(text or '').split('\n') if line.strip()], [], 0
    while index < len(lines):
        if re.fullmatch(r'\d{1,2}\. .{3,70}', lines[index]) and index + 1 < len(lines) and not re.match(r'\d{1,2}\. ', lines[index + 1]):
            out.append((lines[index], lines[index + 1]))
            index += 2
        else:
            out.append(('', lines[index]))
            index += 1
    return out


def link_days(c):
    """Días de vigencia del enlace privado de aprobación (configurable por administración entre 1 y 60; por omisión 15)."""
    row = c.execute("SELECT value FROM system_state WHERE key='quote_link_days'").fetchone()
    try:
        return max(1, min(60, int(row['value']))) if row else LINK_DAYS
    except (TypeError, ValueError):
        return LINK_DAYS


def set_link_days(c, value):
    if not str(value).strip().isdigit() or not 1 <= int(str(value).strip()) <= 60:
        raise QuoteError('La vigencia del enlace debe estar entre 1 y 60 días.', fields={'link_days': 'Valor inválido.'})
    c.execute("INSERT INTO system_state(key,value) VALUES ('quote_link_days',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(int(str(value).strip())),))
    return int(str(value).strip())


def active_link(c, quote, token, now):
    """Datos del enlace para el documento si `token` es el enlace vigente de este presupuesto: {'expires_at'}; None en cualquier otro caso.
    El sistema solo guarda la huella del enlace, así que el código QR solo puede emitirse a quien ya lo tiene (el cliente, o el personal al enviarlo)."""
    if quote['status'] != 'enviado' or not re.fullmatch(r'[A-Za-z0-9_-]{30,80}', str(token or '')):
        return None
    link = c.execute("SELECT expires_at,failed FROM quote_links WHERE quote_id=? AND token_hash=? AND revoked_at=''", (quote['id'], digest(token))).fetchone()
    if not link or datetime.fromisoformat(link['expires_at']) < now or link['failed'] >= MAX_FAILED:
        return None
    return {'expires_at': link['expires_at']}


class QuoteError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def usd(cents):
    """Importe para documentos y mensajes al cliente: símbolo de dólar, separador de miles y dos decimales ($1.250,00). No altera el valor guardado."""
    return ('-' if cents < 0 else '') + '$' + format(abs(cents) // 100, ',d').replace(',', '.') + ',%02d' % (abs(cents) % 100)


def cents(value, field='price'):
    """Importe en USD escrito por una persona (coma o punto decimal) a centavos."""
    try:
        amount = Decimal(str(value).strip().replace(',', '.'))
        if not amount.is_finite() or amount < 0 or amount > Decimal('999999.99') or amount.as_tuple().exponent < -2:
            raise InvalidOperation()
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise QuoteError('Indica un importe en USD, no negativo, con hasta dos decimales.', fields={field: 'Importe inválido.'})


# --- Impuesto y totales -----------------------------------------------------------------------------------------------

def tax_rate(c):
    row = c.execute("SELECT value FROM system_state WHERE key='quote_tax_bp'").fetchone()
    try:
        return max(0, min(3000, int(row['value']))) if row else DEFAULT_TAX_BP
    except (TypeError, ValueError):
        return DEFAULT_TAX_BP


def set_tax_rate(c, value):
    try:
        rate = Decimal(str(value).strip().replace(',', '.').rstrip('%'))
        if not rate.is_finite() or rate < 0 or rate > 30 or rate.as_tuple().exponent < -2:
            raise InvalidOperation()
    except (InvalidOperation, ValueError):
        raise QuoteError('Indica la tarifa de IVA entre 0 y 30 %.', fields={'tax': 'Tarifa inválida.'})
    c.execute("INSERT INTO system_state(key,value) VALUES ('quote_tax_bp',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(int(rate * 100)),))
    return int(rate * 100)


def split(line_cents, taxed, rate_bp):
    """Base e impuesto de un importe que ya incluye IVA. Un ítem con tarifa 0 % no lleva impuesto."""
    if not taxed or not rate_bp:
        return line_cents, 0
    base = (line_cents * 10000 + (10000 + rate_bp) // 2) // (10000 + rate_bp)
    return base, line_cents - base


def net(line_cents, discount_bp):
    """Importe de una línea después del descuento autorizado (redondeo al centavo por línea)."""
    return line_cents - (line_cents * discount_bp + 5000) // 10000


def totals(items, rate_bp, discount_bp=0):
    """Importes cotizado, aprobado, rechazado y pendiente, con el desglose de base e IVA de lo cotizado y de lo aprobado.
    Con descuento, todos los importes son netos; `gross` y `discount` muestran el valor antes del descuento y lo descontado."""
    result = {'gross': 0, 'discount': 0, 'discount_bp': discount_bp, 'quoted': 0, 'approved': 0, 'rejected': 0, 'pending': 0, 'cancelled': 0, 'base_taxed': 0, 'base_zero': 0, 'tax': 0, 'approved_base_taxed': 0, 'approved_base_zero': 0, 'approved_tax': 0,
              'count': {'aprobado': 0, 'rechazado': 0, 'pendiente': 0, 'cancelado': 0}}
    for item in items:
        full = item['quantity'] * item['unit_cents']
        line = net(full, discount_bp)
        base, tax = split(line, item['taxed'], rate_bp)
        status = item.get('status', 'pendiente')
        result['count'][status] += 1
        if status == 'cancelado':
            result['cancelled'] += line
            continue
        result['gross'] += full
        result['discount'] += full - line
        result['quoted'] += line
        result['tax'] += tax
        result['base_taxed' if item['taxed'] else 'base_zero'] += base
        result[{'aprobado': 'approved', 'rechazado': 'rejected', 'pendiente': 'pending'}[status]] += line
        if status == 'aprobado':
            result['approved_tax'] += tax
            result['approved_base_taxed' if item['taxed'] else 'approved_base_zero'] += base
    return result


# --- Catálogo ---------------------------------------------------------------------------------------------------------

def catalog(c, query='', only_available=False, category=''):
    rows = [dict(r) for r in c.execute("SELECT i.id,i.code,i.name,i.description,i.category,i.brand,i.price_cents,i.entered_cents,i.price_mode,i.taxed,i.available,i.license_term,i.devices,i.updated_at,i.icon,i.tax_pending,"
                                       "(SELECT updated_at FROM catalog_images g WHERE g.item_id=i.id) image FROM catalog_items i ORDER BY i.category,i.name COLLATE NOCASE")]
    words = [w for w in re.sub(r'\s+', ' ', str(query or '')).strip().lower().split(' ') if w]
    for row in rows:
        row['image'] = row['image'] or ''
        row['price_mode_label'] = PRICE_MODES[row['price_mode']]
        row['icon'] = catalog_icons.valid(row['icon']) if row['icon'] else catalog_icons.guess(row['category'], row['name'], row['brand'])
    return [r for r in rows if (r['available'] or not only_available) and (not category or r['category'] == category)
            and all(w in ' '.join((r['code'] or '', r['name'], r['description'], r['brand'], CATEGORIES[r['category']])).lower() for w in words)]


def price_from(entered_cents, mode, rate_bp):
    """Precio final y si lleva IVA, según cómo se escribió: con IVA incluido, base más IVA o sin IVA."""
    if mode == 'agregar':
        return entered_cents + (entered_cents * rate_bp + 5000) // 10000, 1
    return entered_cents, 0 if mode == 'sin_iva' else 1


def save_catalog_item(c, data, user, now):
    name = re.sub(r'\s+', ' ', str(data.get('name', ''))).strip()
    description = str(data.get('description', '')).strip()
    category = str(data.get('category', ''))
    brand = re.sub(r'\s+', ' ', str(data.get('brand', ''))).strip()
    term = re.sub(r'\s+', ' ', str(data.get('license_term', ''))).strip()
    devices = re.sub(r'\s+', ' ', str(data.get('devices', ''))).strip()
    # Compatibilidad: «taxed» desmarcado equivale a «sin IVA» cuando no se indica el modo.
    mode = str(data.get('price_mode', '') or ('sin_iva' if data.get('taxed') is False else 'incluido'))
    errors = {}
    if not 2 <= len(name) <= 120:
        errors['name'] = 'Indica un nombre de 2 a 120 caracteres.'
    if len(description) > 500:
        errors['description'] = 'La descripción admite hasta 500 caracteres.'
    if category not in CATEGORIES:
        errors['category'] = 'Selecciona una categoría.'
    if mode not in PRICE_MODES:
        errors['price_mode'] = 'Selecciona cómo se trata el IVA.'
    if len(brand) > 60 or len(term) > 60 or len(devices) > 40:
        errors['brand'] = 'Marca, duración y dispositivos admiten textos breves.'
    try:
        entered = cents(data.get('price', ''))
    except QuoteError:
        entered = 0
        errors['price'] = 'Indica el precio en USD con hasta dos decimales.'
    item_id = str(data.get('id', ''))
    if not errors and c.execute('SELECT 1 FROM catalog_items WHERE lower(name)=lower(?) AND id!=?', (name, int(item_id) if item_id.isdigit() else 0)).fetchone():
        errors['name'] = 'Ya existe un elemento con ese nombre en el catálogo.'
    if errors:
        raise QuoteError(next(iter(errors.values())) if len(errors) == 1 else 'Revisa los campos señalados.', fields=errors)
    icon = str(data.get('icon') or '')
    if icon and icon not in catalog_icons.ICONS:
        raise QuoteError('Selecciona un icono válido.', fields={'icon': 'Icono no válido.'})
    price, taxed = price_from(entered, mode, tax_rate(c))
    available, stamp = 1 if data.get('available') is not False else 0, now.isoformat(timespec='seconds')
    if item_id:
        old = c.execute('SELECT price_cents,icon FROM catalog_items WHERE id=?', (item_id,)).fetchone() if item_id.isdigit() else None
        if not old:
            raise QuoteError('El elemento del catálogo ya no existe.', 404)
        # El icono elegido se conserva si la edición no indica otro (por ejemplo, al activar o desactivar el elemento).
        icon = icon or old['icon'] or catalog_icons.guess(category, name, brand)
        c.execute('UPDATE catalog_items SET name=?,description=?,category=?,brand=?,price_cents=?,entered_cents=?,price_mode=?,taxed=?,available=?,license_term=?,devices=?,icon=?,updated_at=?,updated_by=? WHERE id=?',
                  (name, description, category, brand, price, entered, mode, taxed, available, term, devices, icon, stamp, user['id'], item_id))
        # El IVA queda confirmado solo cuando administración lo indica expresamente; el alta marcada como pendiente lo conserva.
        if data.get('tax_confirmed') is True:
            c.execute('UPDATE catalog_items SET tax_pending=0 WHERE id=?', (item_id,))
        elif data.get('tax_pending') is True:
            c.execute('UPDATE catalog_items SET tax_pending=1 WHERE id=?', (item_id,))
        if old['price_cents'] != price:
            # Historial de precios: el cambio no toca los presupuestos ya emitidos, que guardan su propio importe.
            c.execute('INSERT INTO catalog_price_history(item_id,old_cents,new_cents,user_id,created_at) VALUES (?,?,?,?,?)', (item_id, old['price_cents'], price, user['id'], stamp))
        return int(item_id)
    icon = icon or catalog_icons.guess(category, name, brand)
    return c.execute('INSERT INTO catalog_items(name,description,category,brand,price_cents,entered_cents,price_mode,taxed,available,license_term,devices,icon,tax_pending,created_at,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (name, description, category, brand, price, entered, mode, taxed, available, term, devices, icon, 1 if data.get('tax_pending') is True else 0, stamp, stamp, user['id'])).lastrowid


def price_history(c, item_id):
    return [dict(r) for r in c.execute("SELECT h.old_cents,h.new_cents,h.created_at,COALESCE(u.name,'') actor FROM catalog_price_history h LEFT JOIN users u ON u.id=h.user_id WHERE h.item_id=? ORDER BY h.id DESC LIMIT 50", (item_id,))]


def save_image(c, item_id, content, user, now):
    """Imagen o logotipo del elemento: PNG, JPEG o WebP reales (se comprueba la cabecera), hasta 300 KB."""
    if not c.execute('SELECT 1 FROM catalog_items WHERE id=?', (item_id,)).fetchone():
        raise QuoteError('El elemento del catálogo ya no existe.', 404)
    kind = 'image/png' if content[:8] == b'\x89PNG\r\n\x1a\n' else 'image/jpeg' if content[:3] == b'\xff\xd8\xff' and content[-2:] == b'\xff\xd9' else 'image/webp' if content[:4] == b'RIFF' and content[8:12] == b'WEBP' else None
    if not kind:
        raise QuoteError('Usa una imagen PNG, JPG o WebP.')
    if len(content) > IMAGE_LIMIT:
        raise QuoteError('La imagen supera el máximo de 300 KB.')
    stamp = now.isoformat(timespec='seconds')
    c.execute('INSERT INTO catalog_images(item_id,mime,data,updated_at,updated_by) VALUES (?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET mime=excluded.mime,data=excluded.data,updated_at=excluded.updated_at,updated_by=excluded.updated_by', (item_id, kind, content, stamp, user['id']))
    return stamp


# Catálogo inicial de PC-DOCTOR S.A. (13/10/2026): nombres y precios finales (IVA incluido) entregados por la administración.
# Las descripciones no añaden características, compatibilidades, duraciones ni dispositivos que no consten en el nombre.
INITIAL = (
 ('Programación o flasheo de BIOS corrupta – PlayStation 5', 'servicio', 'PlayStation', '150.00', 'Servicio técnico especializado de reprogramación de la BIOS de la consola cuando su contenido está dañado.', '', ''),
 ('Mantenimiento parcial – PlayStation 5', 'servicio', 'PlayStation', '55.00', 'Servicio de mantenimiento parcial de la consola realizado en el taller.', '', ''),
 ('Cambio profesional de metal líquido – PlayStation 5', 'servicio', 'PlayStation', '189.00', 'Servicio de sustitución del metal líquido de la consola realizado por personal técnico.', '', ''),
 ('Tanque o caja de mantenimiento para impresora Epson', 'repuesto', 'Epson', '68.56', 'Tanque o caja de mantenimiento para impresora Epson. La compatibilidad con el modelo se confirma en el taller.', '', ''),
 ('Microsoft Office Pro Plus 2024 + Windows 11 Pro', 'licencia', 'Microsoft', '189.99', 'Licencias de Microsoft Office Pro Plus 2024 y Windows 11 Pro.', '', ''),
 ('Microsoft Office 365 Pro Plus – 5 dispositivos', 'licencia', 'Microsoft', '155.00', 'Licencia de Microsoft Office 365 Pro Plus para cinco dispositivos.', '', '5 dispositivos'),
 ('Microsoft Office 2024 Estándar', 'licencia', 'Microsoft', '85.99', 'Licencia de Microsoft Office 2024 Estándar.', '', ''),
 ('Microsoft Office Professional Plus 2021', 'licencia', 'Microsoft', '79.99', 'Licencia de Microsoft Office Professional Plus 2021.', '', ''),
 ('Microsoft Office Professional Plus 2024', 'licencia', 'Microsoft', '99.99', 'Licencia de Microsoft Office Professional Plus 2024.', '', ''),
 ('Windows 11 Pro – Licencia empresarial', 'licencia', 'Microsoft', '165.00', 'Licencia empresarial de Windows 11 Pro.', '', ''),
 ('Chequeo y diagnóstico profesional de memoria RAM', 'servicio', '', '18.00', 'Revisión y diagnóstico de la memoria RAM del equipo realizados en el taller.', '', ''),
 ('Windows 11 Home ES – Licencia', 'licencia', 'Microsoft', '69.99', 'Licencia de Windows 11 Home en español.', '', ''),
 ('Windows 11 Pro – Actualización', 'licencia', 'Microsoft', '112.99', 'Actualización a Windows 11 Pro.', '', ''),
 ('Kaspersky Standard – Licencia Antivirus de 1 Año', 'seguridad', 'Kaspersky', '30.00', 'Licencia de antivirus Kaspersky Standard con vigencia de un año.', '1 año', ''),
 ('Kaspersky Standard – Licencia Antivirus de Duración Ilimitada, 1 dispositivo', 'seguridad', 'Kaspersky', '125.00', 'Licencia de antivirus Kaspersky Standard de duración ilimitada para un dispositivo.', 'Duración ilimitada', '1 dispositivo'),
 ('McAfee Plus – Licencia Antivirus, 1 dispositivo, 1 año', 'seguridad', 'McAfee', '25.00', 'Licencia de antivirus McAfee Plus para un dispositivo con vigencia de un año.', '1 año', '1 dispositivo'),
 ('Defender Plus – Licencia Antivirus, 1 año', 'seguridad', 'Defender Plus', '45.00', 'Licencia de antivirus Defender Plus con vigencia de un año.', '1 año', ''),
 ('Norton 360 Estándar – Licencia Antivirus, 1 dispositivo, 1 año', 'seguridad', 'Norton', '45.00', 'Licencia de antivirus Norton 360 Estándar para un dispositivo con vigencia de un año.', '1 año', '1 dispositivo'),
 ('ESET NOD32 Antivirus – Licencia de 1 Año', 'seguridad', 'ESET', '40.00', 'Licencia de ESET NOD32 Antivirus con vigencia de un año.', '1 año', ''),
)


# Segunda carga del catálogo (2026-10-13). (nombre, categoría, precio, descripción, icono, IVA por confirmar, palabras que identifican un registro previo a actualizar)
# Las pantallas van en «Productos». Todos los precios incluyen IVA: el de los siete servicios lo confirmó la administración el 2026-10-13.
# La marca «IVA por confirmar» sigue disponible para futuras cargas con el tratamiento tributario pendiente.
ADDITIONS = (
 ('Cambio de pantalla de portátil de 14 pulgadas', 'otro', '115.00', 'Pantalla para portátil de 14 pulgadas con su instalación.', 'pantalla', False, ()),
 ('Cambio de pantalla de portátil de 15,6 pulgadas', 'otro', '150.00', 'Pantalla para portátil de 15,6 pulgadas con su instalación.', 'pantalla', False, ()),
 ('Cambio de pantalla de portátil gamer de 15,6 pulgadas', 'otro', '280.00', 'Pantalla para portátil gamer de 15,6 pulgadas con su instalación.', 'pantalla_gamer', False, ()),
 ('Reparación de bisagras de portátil de 14 pulgadas', 'servicio', '32.00', 'Reparación de las bisagras de un portátil de 14 pulgadas.', 'bisagra', False, ()),
 ('Reparación de bisagras de portátil de 15,6 pulgadas', 'servicio', '48.00', 'Reparación de las bisagras de un portátil de 15,6 pulgadas.', 'bisagra', False, ()),
 ('Pegado de bisagras de portátil de 14 pulgadas', 'servicio', '35.00', 'Pegado de las bisagras de un portátil de 14 pulgadas.', 'bisagra', False, ()),
 ('Pegado de bisagras de portátil de 15,6 pulgadas', 'servicio', '48.00', 'Pegado de las bisagras de un portátil de 15,6 pulgadas.', 'bisagra', False, ()),
 ('Mantenimiento de PC de escritorio y cambio de pasta térmica del CPU, sin tarjeta gráfica dedicada', 'servicio', '45.00', 'Mantenimiento de un PC de escritorio sin tarjeta gráfica dedicada, con cambio de la pasta térmica del procesador.', 'escritorio', False, ('mantenimiento', 'escritorio')),
 ('Mantenimiento de PC Gamer con cambio de pasta térmica del CPU', 'servicio', '75.00', 'Mantenimiento de un PC gamer con cambio de la pasta térmica del procesador.', 'pc_gamer', False, ()),
 ('Creación de nueva BIOS para computadora portátil', 'servicio', '130.00', 'Creación de una BIOS nueva para una computadora portátil. Es un servicio distinto de la actualización o reprogramación de BIOS.', 'bios', False, ()),
)


# Tercera carga (2026-10-20): renovación de pasta térmica en portátiles. Precios con IVA incluido (no se suma de nuevo).
THERMAL = (
 ('Renovación de pasta térmica para portátiles sin GPU dedicada', 'servicio', '20.00', 'Servicio de sustitución de pasta térmica del procesador (CPU) para optimizar la transferencia de calor y mejorar la refrigeración del equipo.', 'termica_portatil'),
 ('Renovación de pasta térmica para portátiles Gamer con GPU dedicada', 'servicio', '65.00', 'Servicio de sustitución de pasta térmica del CPU y GPU para mejorar la disipación térmica y mantener temperaturas adecuadas de funcionamiento.', 'termica_gamer'),
)


# Cuarta carga (2026-10-20): formateo con instalación de Windows y respaldo de información. Precios finales con IVA incluido.
FORMAT_BACKUP = (
 ('Formateo e Instalación Profesional de Windows', 'servicio', '15.00', 'Formateo de la unidad, instalación limpia de Windows, configuración inicial y controladores básicos.', 'formateo'),
 ('Servicio de Respaldo y Protección de Información Digital', 'servicio', '20.00', 'Respaldo de archivos personales y documentos importantes con verificación de integridad.', 'respaldo'),
)
# Lotes que se crean una sola vez (marca en system_state). Si administración renombra o desactiva un servicio, no se vuelve a crear.
SEED_BATCHES = (('catalog_seed_20261020', 'THERMAL'), ('catalog_seed_20261020b', 'FORMAT_BACKUP'))


def seed_batch(c, items, user, now):
    """Agrega servicios sin duplicar: si ya existe un elemento con el mismo nombre, no se toca."""
    created = 0
    for name, category, price, description, icon in items:
        if c.execute('SELECT 1 FROM catalog_items WHERE lower(name)=lower(?)', (name,)).fetchone():
            continue
        save_catalog_item(c, {'name': name, 'category': category, 'price': price, 'description': description, 'icon': icon, 'price_mode': 'incluido'}, user, now)
        created += 1
    return {'created': created, 'existing': len(items) - created, 'total': len(items)}


def seed_thermal(c, user, now):
    """Agrega los servicios de pasta térmica para portátiles sin duplicar: si ya existe un elemento con el mismo nombre, no se toca."""
    created = 0
    for name, category, price, description, icon in THERMAL:
        if c.execute('SELECT 1 FROM catalog_items WHERE lower(name)=lower(?)', (name,)).fetchone():
            continue
        save_catalog_item(c, {'name': name, 'category': category, 'price': price, 'description': description, 'icon': icon, 'price_mode': 'incluido'}, user, now)
        created += 1
    return {'created': created, 'existing': len(THERMAL) - created, 'total': len(THERMAL)}


def seed_thermal_once(c, now):
    """Al iniciar: crea una sola vez cada lote de servicios nuevos (queda marcado; si administración los renombra o desactiva después,
    no se vuelven a crear). El alta queda a nombre de la primera cuenta de administración. Devuelve el resultado del primer lote
    pendiente (None si no había ninguno)."""
    admin = c.execute("SELECT id,name FROM users WHERE role='administrador' ORDER BY id LIMIT 1").fetchone()
    if not admin:
        return None
    user, first = {'id': admin['id'], 'name': admin['name'], 'role': 'administrador'}, None
    for flag, name in SEED_BATCHES:
        if c.execute('SELECT 1 FROM system_state WHERE key=?', (flag,)).fetchone():
            continue
        result = seed_batch(c, globals()[name], user, now)
        c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (flag, now.isoformat(timespec='seconds')))
        first = first or result
    return first


def seed_additions(c, user, now):
    """Registra la segunda carga sin duplicar. Un elemento con el mismo nombre no se toca; el mantenimiento de PC de escritorio actualiza
    el registro previo equivalente (misma categoría, mismas palabras clave y sin «gamer») en lugar de crear otro."""
    created = updated = 0
    for name, category, price, description, icon, pending, match in ADDITIONS:
        if c.execute('SELECT 1 FROM catalog_items WHERE lower(name)=lower(?)', (name,)).fetchone():
            continue
        previous = None
        if match:
            for row in c.execute('SELECT * FROM catalog_items WHERE category=? ORDER BY id', (category,)):
                words = catalog_icons.plain(row['name'])
                if all(word in words for word in match) and 'gamer' not in words:
                    previous = dict(row)
                    break
        data = {'name': name, 'category': category, 'price': price, 'description': description, 'icon': icon, 'price_mode': 'incluido', 'tax_pending': pending}
        if previous:
            # Conserva identificador, código, marca, modo de IVA e historial; solo cambian nombre, descripción, icono y precio.
            save_catalog_item(c, dict(data, id=str(previous['id']), brand=previous['brand'], price_mode=previous['price_mode'], license_term=previous['license_term'], devices=previous['devices'], available=bool(previous['available']), tax_pending=None), user, now)
            updated += 1
        else:
            save_catalog_item(c, data, user, now)
            created += 1
    return {'created': created, 'updated': updated, 'existing': len(ADDITIONS) - created - updated, 'total': len(ADDITIONS)}


def seed_initial(c, user, now):
    """Registra el catálogo inicial sin duplicar: un elemento con el mismo nombre no se vuelve a crear ni se modifica."""
    created = 0
    for name, category, brand, price, description, term, devices in INITIAL:
        if c.execute('SELECT 1 FROM catalog_items WHERE lower(name)=lower(?)', (name,)).fetchone():
            continue
        save_catalog_item(c, {'name': name, 'category': category, 'brand': brand, 'price': price, 'description': description, 'license_term': term, 'devices': devices, 'price_mode': 'incluido'}, user, now)
        created += 1
    return {'created': created, 'existing': len(INITIAL) - created, 'total': len(INITIAL)}


# --- Presupuestos -----------------------------------------------------------------------------------------------------

def event(c, quote_id, name, detail, now, user=None, actor=''):
    c.execute('INSERT INTO quote_events(quote_id,actor_id,actor,event,detail,created_at) VALUES (?,?,?,?,?,?)', (quote_id, user['id'] if user else None, actor or (user['name'] if user else ''), name, detail[:500], now.isoformat(timespec='seconds')))


def order_code(c, order_id):
    row = c.execute('SELECT id,code FROM orders WHERE id=?', (order_id,)).fetchone()
    if not row:
        raise QuoteError('Orden no disponible.', 404)
    return row['code'] or 'OP-%05d' % row['id']


def items_of(c, quote_id):
    rows = [dict(r) for r in c.execute('SELECT q.id,q.position,q.catalog_id,q.description,q.category,q.quantity,q.unit_cents,q.taxed,q.status,q.execution,q.execution_at,q.priority,'
                                       "COALESCE(g.icon,'') catalog_icon,COALESCE(g.tax_pending,0) tax_pending FROM quote_items q LEFT JOIN catalog_items g ON g.id=q.catalog_id WHERE q.quote_id=? ORDER BY q.position,q.id", (quote_id,))]
    for row in rows:
        # Icono: el del elemento del catálogo (ligado a su identificador); en una línea libre, el propuesto para su categoría y descripción.
        row['icon'] = catalog_icons.valid(row.pop('catalog_icon')) if row['catalog_id'] and row['catalog_icon'] else catalog_icons.guess(row['category'], row['description'])
        row['priority_label'] = PRIORITIES[row['priority']][0] if row['priority'] else ''
    return rows


def get(c, quote_id):
    row = c.execute('SELECT * FROM quotes WHERE id=?', (quote_id,)).fetchone()
    if not row or row['deleted_at']:
        raise QuoteError('Presupuesto no disponible.', 404)
    return dict(row)


def detail(c, quote):
    items = items_of(c, quote['id'])
    acceptance = c.execute('SELECT signer_name,method,signature,evidence_hash,created_at FROM quote_acceptances WHERE quote_id=?', (quote['id'],)).fetchone()
    paper = c.execute('SELECT mime,created_at,length(data) size FROM quote_documents WHERE quote_id=?', (quote['id'],)).fetchone()
    link = c.execute("SELECT created_at,expires_at,verified_at FROM quote_links WHERE quote_id=? AND revoked_at='' ORDER BY id DESC LIMIT 1", (quote['id'],)).fetchone()
    for item in items:
        item['line_cents'] = item['quantity'] * item['unit_cents']
        item['net_cents'] = net(item['line_cents'], quote['discount_bp'])
        item['status_label'] = ITEM_STATUS[item['status']]
        item['category_label'] = CATEGORIES[item['category']]
        item['execution_label'] = EXECUTION[item['execution']]
    return dict(quote, mail_state=mail_state(c, quote['id']), client_note=client_note(c, quote['id']), status_label=STATUS[quote['status']], editable=quote['status'] in EDITABLE, items=items, totals=totals(items, quote['tax_rate_bp'], quote['discount_bp']), discount_label=DISCOUNTS[quote['discount_bp']],
                bank_account=bank_for(c, quote), acceptance=dict(acceptance, signed=bool(acceptance['signature'])) if acceptance else None, identity_document=dict(paper) if paper else None, link=dict(link) if link else None,
                events=[dict(r) for r in c.execute('SELECT event,detail,actor,created_at FROM quote_events WHERE quote_id=? ORDER BY id DESC LIMIT 60', (quote['id'],))])


def brief(c, order_id):
    """Resumen del presupuesto vigente de un equipo (su última versión) para la vista de la orden; None si no tiene."""
    row = c.execute("SELECT * FROM quotes WHERE order_id=? AND deleted_at='' ORDER BY version DESC LIMIT 1", (order_id,)).fetchone()
    if not row:
        return None
    items = items_of(c, row['id'])
    t = totals(items, row['tax_rate_bp'], row['discount_bp'])
    return {'id': row['id'], 'code': row['code'], 'status': row['status'], 'status_label': STATUS[row['status']], 'editable': row['status'] in EDITABLE,
            'lines': sum(1 for item in items if item['status'] != 'cancelado'), 'approved_count': t['count']['aprobado'], 'rejected_count': t['count']['rechazado'], 'pending_count': t['count']['pendiente'],
            'sent_at': row['sent_at'], 'authorized_cents': sum(line['net_cents'] for line in approved_lines(c, dict(row))) if row['status'] in DECIDED else (lambda found: sum(line['net_cents'] for line in found['items']) if found else 0)(authorized(c, order_id)),
            'quoted_cents': t['quoted'], 'approved_cents': t['approved'], 'pending_cents': t['pending'], 'rejected_cents': t['rejected']}


def mail_state(c, quote_id):
    """Resultado real del último correo con el enlace: 'sent' (aceptado por el servidor), 'failed', 'not_configured' o '' si no hubo intento."""
    row = c.execute("SELECT detail FROM quote_events WHERE quote_id=? AND event='correo' ORDER BY id DESC LIMIT 1", (quote_id,)).fetchone()
    if not row:
        return ''
    return 'sent' if 'aceptado' in row['detail'] else 'not_configured' if 'no está configurado' in row['detail'] else 'failed'


def client_note(c, quote_id):
    """Motivo u observación que escribió el cliente al decidir (si lo dio)."""
    row = c.execute("SELECT detail FROM quote_events WHERE quote_id=? AND event IN ('aprobado','parcial','rechazado') ORDER BY id DESC LIMIT 1", (quote_id,)).fetchone()
    if row and 'Observación del cliente: ' in row['detail']:
        return row['detail'].split('Observación del cliente: ', 1)[1].strip()
    return ''


WAITING_ORDER = ('presupuesto', 'esperando_cliente')  # estados de la orden que esperan la decisión del presupuesto


def sync_order(c, quote, status, now):
    """Estado técnico de la orden tras la decisión. Solo si la orden esperaba esa decisión («Aprobación de presupuesto» o «Esperando respuesta
    del cliente»): con algo aprobado pasa a «Procesando»; si se rechazó todo, queda donde estaba para que el taller decida.
    Nunca toca «Listo», «En espera de entrega» ni «Entregado», y nunca marca el equipo como reparado."""
    import order_workspace
    row = c.execute('SELECT o.status,s.label FROM orders o JOIN statuses s ON s.code=o.status WHERE o.id=?', (quote['order_id'],)).fetchone()
    if not row or row['status'] not in WAITING_ORDER:
        return False
    who = 'por el cliente' if not str(c.execute('SELECT decided_by FROM quotes WHERE id=?', (quote['id'],)).fetchone()[0]).startswith('personal') else '(decisión registrada por el personal)'
    if status in ('aprobado', 'parcial'):
        c.execute("UPDATE orders SET status='reparacion',updated_at=?,revision=revision+1 WHERE id=?", (now.isoformat(timespec='microseconds'), quote['order_id']))
        order_workspace.event(c, quote['order_id'], None, now, 'status', 'Presupuesto ' + quote['code'] + ' ' + ('aprobado' if status == 'aprobado' else 'aprobado parcialmente') +
                              ' ' + who + ': el equipo pasa de «' + row['label'] + '» a «Procesando». Solo se ejecutan los servicios aprobados.')
        return True
    order_workspace.event(c, quote['order_id'], None, now, 'follow_up', 'Presupuesto ' + quote['code'] + ' rechazado: no se autoriza ningún servicio. Definir con el cliente la devolución del equipo.')
    return False


def for_order(c, order_id):
    """Presupuesto vigente de la orden (su última versión) y la lista de versiones."""
    rows = [dict(r) for r in c.execute("SELECT * FROM quotes WHERE order_id=? AND deleted_at='' ORDER BY version DESC", (order_id,))]
    versions = []
    for r in rows:
        items = items_of(c, r['id'])
        t = totals(items, r['tax_rate_bp'], r['discount_bp'])
        link = c.execute("SELECT verified_at FROM quote_links WHERE quote_id=? AND revoked_at='' ORDER BY id DESC LIMIT 1", (r['id'],)).fetchone()
        versions.append({'id': r['id'], 'code': r['code'], 'version': r['version'], 'status': r['status'], 'status_label': STATUS[r['status']], 'created_at': r['created_at'], 'valid_until': r['valid_until'], 'sent_at': r['sent_at'],
                         'sent_to': r['sent_to'], 'decided_at': r['decided_at'], 'editable': r['status'] in EDITABLE, 'lines': sum(1 for item in items if item['status'] != 'cancelado'), 'quoted_cents': t['quoted'], 'approved_cents': t['approved'],
                         'pending_cents': t['pending'], 'rejected_cents': t['rejected'], 'count': t['count'], 'verified_at': link['verified_at'] if link else '', 'removable': removable(c, r) == '',
                         'mail_state': mail_state(c, r['id']), 'client_note': client_note(c, r['id'])})
    return {'current': detail(c, rows[0]) if rows else None, 'versions': versions,
            'tax_rate_bp': tax_rate(c), 'categories': CATEGORIES, 'conditions': CONDITIONS, 'priorities': {key: {'label': label, 'color': color} for key, (label, color, _) in PRIORITIES.items()}, 'icons': catalog_icons.catalog(), 'discounts': {str(key): '%s: %g %%' % (label, key / 100) for key, label in DISCOUNTS.items()}}


def create(c, order_id, user, now, copy_from=None, pending_only=False):
    """Nueva versión del presupuesto de la orden: P1, P2… La anterior, si seguía abierta, queda cancelada."""
    code = order_code(c, order_id)
    last = c.execute("SELECT * FROM quotes WHERE order_id=? AND deleted_at='' ORDER BY version DESC LIMIT 1", (order_id,)).fetchone()
    highest = c.execute('SELECT COALESCE(MAX(version),0) FROM quotes WHERE order_id=?', (order_id,)).fetchone()[0]
    if last and last['status'] in ('borrador',):
        raise QuoteError('Esta orden ya tiene un presupuesto en borrador. Edítalo o cancélalo antes de crear otra versión.', 409)
    if pending_only and not (last and last['status'] in DECIDED and any(item['status'] == 'pendiente' for item in items_of(c, last['id']))):
        raise QuoteError('El presupuesto vigente no tiene partidas que el cliente haya dejado pendientes.', 409)
    version, stamp = highest + 1, now.isoformat(timespec='seconds')
    quote_id = c.execute("INSERT INTO quotes(order_id,version,code,status,tax_rate_bp,created_by,created_at,updated_at,discount_bp,discount_by,discount_at,continues_id) VALUES (?,?,?,'borrador',?,?,?,?,?,?,?,?)", (order_id, version, '%s-P%d' % (code, version), tax_rate(c), user['id'], stamp, stamp, last['discount_bp'] if last else 0, last['discount_by'] if last else None, last['discount_at'] if last else '', last['id'] if pending_only else None)).lastrowid
    if last and last['status'] in ('enviado', 'modificacion'):
        c.execute("UPDATE quotes SET status='cancelado',updated_at=? WHERE id=?", (stamp, last['id']))
        c.execute("UPDATE quote_links SET revoked_at=? WHERE quote_id=? AND revoked_at=''", (stamp, last['id']))
        event(c, last['id'], 'cancelado', 'Sustituido por la versión P%d.' % version, now, user)
    source = copy_from if copy_from is not None else (last['id'] if last else None)
    if source:
        for item in items_of(c, source):
            if item['status'] != 'cancelado' and (not pending_only or item['status'] == 'pendiente'):
                c.execute("INSERT INTO quote_items(quote_id,position,catalog_id,description,category,quantity,unit_cents,taxed,priority) VALUES (?,?,?,?,?,?,?,?,?)", (quote_id, item['position'], item['catalog_id'], item['description'], item['category'], item['quantity'], item['unit_cents'], item['taxed'], item['priority']))
    event(c, quote_id, 'creado', 'Presupuesto %s-P%d creado%s.' % (code, version, ' con las partidas que el cliente dejó pendientes; lo ya autorizado se conserva' if pending_only else ' a partir de la versión anterior' if source else ''), now, user)
    return quote_id


def save(c, quote, data, user, now):
    """Guarda el borrador: ítems, vigencia y notas. Solo mientras el presupuesto es editable."""
    if quote['status'] not in EDITABLE:
        raise QuoteError('Este presupuesto ya fue enviado o decidido. Crea una nueva versión para modificarlo.', 409)
    rows = data.get('items')
    if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
        raise QuoteError('El presupuesto admite hasta %d ítems.' % MAX_ITEMS)
    clean = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise QuoteError('Revisa los ítems del presupuesto.')
        description = re.sub(r'[ \t]+', ' ', str(row.get('description', ''))).strip()
        category = str(row.get('category', ''))
        quantity = row.get('quantity')
        unit = row.get('unit_cents')
        if not 2 <= len(description) <= 300 or category not in CATEGORIES or type(quantity) is not int or not 1 <= quantity <= 999 or type(unit) is not int or not 0 <= unit <= 99999999:
            raise QuoteError('El ítem %d necesita descripción, categoría, cantidad e importe válidos.' % (index + 1))
        catalog_id = row.get('catalog_id')
        if catalog_id is not None and (type(catalog_id) is not int or not c.execute('SELECT 1 FROM catalog_items WHERE id=?', (catalog_id,)).fetchone()):
            catalog_id = None
        priority = str(row.get('priority') or '')
        if priority and priority not in PRIORITIES:
            raise QuoteError('El ítem %d tiene una clasificación no válida.' % (index + 1))
        clean.append((index, catalog_id, description, category, quantity, unit, 1 if row.get('taxed') is not False else 0, priority))
    valid = str(data.get('valid_until', '')).strip()
    if valid:
        try:
            if date.fromisoformat(valid).isoformat() != valid:
                raise ValueError()
        except ValueError:
            raise QuoteError('Indica una fecha de vigencia válida.', fields={'valid_until': 'Fecha inválida.'})
    notes = str(data.get('notes', '')).strip()
    if len(notes) > 1500:
        raise QuoteError('Las observaciones admiten hasta 1500 caracteres.', fields={'notes': 'Texto demasiado largo.'})
    # Descuento autorizado: solo 0, 3 o 5 %, y solo lo cambia administración. Queda registrado quién y cuándo.
    discount = quote['discount_bp']
    if 'discount' in data and str(data['discount']) != str(discount):
        if user['role'] != 'administrador':
            raise QuoteError('Solo administración puede aplicar o modificar descuentos.', 403)
        if str(data['discount']) not in ('0', '300', '500'):
            raise QuoteError('El descuento autorizado solo puede ser 0 %, 3 % o 5 %.', fields={'discount': 'Descuento no permitido.'})
        discount = int(data['discount'])
        c.execute('UPDATE quotes SET discount_bp=?,discount_by=?,discount_at=? WHERE id=?', (discount, user['id'], now.isoformat(timespec='seconds'), quote['id']))
        event(c, quote['id'], 'descuento', '%s (%g %%) aplicado al presupuesto.' % (DISCOUNTS[discount], discount / 100), now, user)
    if data.get('require_id') in (True, False) and bool(quote['require_id']) != data['require_id']:
        if user['role'] != 'administrador':
            raise QuoteError('Solo administración puede solicitar el documento de identidad.', 403)
        c.execute('UPDATE quotes SET require_id=? WHERE id=?', (1 if data['require_id'] else 0, quote['id']))
        event(c, quote['id'], 'identidad', 'Documento de identidad %s para la aprobación.' % ('solicitado' if data['require_id'] else 'ya no solicitado'), now, user)
    c.execute('DELETE FROM quote_items WHERE quote_id=?', (quote['id'],))
    c.executemany('INSERT INTO quote_items(quote_id,position,catalog_id,description,category,quantity,unit_cents,taxed,priority) VALUES (?,?,?,?,?,?,?,?,?)', [(quote['id'], *row) for row in clean])
    c.execute("UPDATE quotes SET valid_until=?,notes=?,status='borrador',updated_at=? WHERE id=?", (valid, notes, now.isoformat(timespec='seconds'), quote['id']))
    event(c, quote['id'], 'guardado', 'Borrador guardado con %d %s. Total cotizado: %s.' % (len(clean), 'ítem' if len(clean) == 1 else 'ítems', usd(sum(net(row[4] * row[5], discount) for row in clean))), now, user)


def send(c, quote, recipient, user, now):
    """Marca el presupuesto como enviado y crea su enlace privado. Devuelve el token (solo existe aquí)."""
    if quote['status'] not in EDITABLE + ('enviado',):
        raise QuoteError('Este presupuesto ya fue decidido o cancelado.', 409)
    items = items_of(c, quote['id'])
    if not items:
        raise QuoteError('Agrega al menos un ítem antes de enviar el presupuesto.')
    unconfirmed = [item['description'].split(' — ')[0][:70] for item in items if item['tax_pending'] and item['status'] != 'cancelado']
    if unconfirmed:
        raise QuoteError('No se puede enviar: falta confirmar el IVA en el catálogo de «%s». Indica si su precio incluye IVA, se le agrega o no lleva IVA, y vuelve a intentarlo.' % '», «'.join(unconfirmed[:3]), 409)
    if quote['valid_until'] and quote['valid_until'] < now.date().isoformat():
        raise QuoteError('La vigencia del presupuesto ya venció. Actualízala antes de enviarlo.', fields={'valid_until': 'Fecha vencida.'})
    stamp, token = now.isoformat(timespec='seconds'), secrets.token_urlsafe(32)
    c.execute("UPDATE quote_links SET revoked_at=? WHERE quote_id=? AND revoked_at=''", (stamp, quote['id']))
    c.execute('INSERT INTO quote_links(quote_id,token_hash,created_at,expires_at) VALUES (?,?,?,?)', (quote['id'], digest(token), stamp, (now + timedelta(days=link_days(c))).isoformat(timespec='seconds')))
    c.execute("UPDATE quotes SET status='enviado',conditions=?,sent_at=?,sent_to=?,updated_at=? WHERE id=?", (CONDITIONS, stamp, recipient, stamp, quote['id']))
    c.execute("UPDATE quote_items SET status='pendiente' WHERE quote_id=? AND status!='cancelado'", (quote['id'],))
    event(c, quote['id'], 'enviado', 'Enviado para aprobación a ' + recipient + '.', now, user)
    return token


def chain(c, quote):
    """El presupuesto y las versiones que continúa (las que dejaron partidas pendientes), de la más reciente a la más antigua."""
    rows, seen = [dict(quote)], {quote['id']}
    while rows[-1].get('continues_id') and rows[-1]['continues_id'] not in seen:
        previous = c.execute('SELECT * FROM quotes WHERE id=?', (rows[-1]['continues_id'],)).fetchone()
        if not previous:
            break
        rows.append(dict(previous))
        seen.add(previous['id'])
    return rows


def approved_lines(c, quote):
    """Partidas aprobadas vigentes: las de este presupuesto y las de las versiones que continúa. Cada una se cuenta una sola vez."""
    result = []
    for row in reversed(chain(c, quote)):
        if row['status'] not in DECIDED:
            continue
        acceptance = c.execute('SELECT signer_name,signature FROM quote_acceptances WHERE quote_id=?', (row['id'],)).fetchone()
        for item in items_of(c, row['id']):
            if item['status'] == 'aprobado':
                line = net(item['quantity'] * item['unit_cents'], row['discount_bp'])
                base, tax = split(line, item['taxed'], row['tax_rate_bp'])  # misma regla por línea que los totales del presupuesto
                ref = c.execute('SELECT code,brand FROM catalog_items WHERE id=?', (item['catalog_id'],)).fetchone() if item['catalog_id'] else None
                result.append(dict(item, quote_id=row['id'], quote_code=row['code'], approved_at=row['decided_at'], net_cents=line, base_cents=base, tax_cents=tax, reference=(ref['code'] or '') if ref else '', brand=(ref['brand'] or '') if ref else '', category_label=CATEGORIES[item['category']],
                                   execution_label=EXECUTION[item['execution']], signed=bool(acceptance and acceptance['signature']), signer=acceptance['signer_name'] if acceptance else '', by_staff=str(row['decided_by']).startswith('personal')))
    return result


def pending_codes(c, order_id):
    """Presupuestos de la orden enviados al cliente y aún sin decidir (para avisarle de que se aprueban desde su propio enlace)."""
    return [row[0] for row in c.execute("SELECT code FROM quotes WHERE order_id=? AND status='enviado' AND deleted_at='' ORDER BY version", (order_id,)).fetchall()]


def authorized(c, order_id):
    """Lo que el cliente tiene autorizado hoy para un equipo: {'code', 'items'} según la última versión decidida y las que continúa; None si no hay nada aprobado."""
    row = c.execute("SELECT * FROM quotes WHERE order_id=? AND status IN ('aprobado','parcial','rechazado') ORDER BY version DESC LIMIT 1", (order_id,)).fetchone()
    if not row:
        return None
    items = approved_lines(c, dict(row))
    return {'code': row['code'], 'items': items} if items else None


PROCESSING = ('reparacion', 'revision_recurrente', 'listo', 'espera_entrega', 'entregado')  # la orden ya pasó a trabajarse (o más allá)


def authorization(c, order_id, order_status=''):
    """Ficha de «Autorizaciones del cliente»: quién y cuándo decidió, línea de tiempo con hechos registrados (sin inventar fechas),
    subtotal, IVA y total autorizados por línea, y el historial de decisiones con su evidencia. None si no hay nada aprobado."""
    found = authorized(c, order_id)
    if not found:
        return None
    head = dict(c.execute("SELECT * FROM quotes WHERE order_id=? AND status IN ('aprobado','parcial','rechazado') ORDER BY version DESC LIMIT 1", (order_id,)).fetchone())
    items = found['items']
    acceptance = c.execute('SELECT signer_name,method,evidence_hash,created_at FROM quote_acceptances WHERE quote_id=?', (head['id'],)).fetchone()
    staff = str(head['decided_by']).startswith('personal:')
    who = ''
    if staff:
        user = c.execute('SELECT name FROM users WHERE id=?', (int(head['decided_by'].split(':', 1)[1]),)).fetchone()
        who = user['name'] if user else 'Personal autorizado'
    note = ''
    decided = c.execute("SELECT detail,actor FROM quote_events WHERE quote_id=? AND event=? ORDER BY id DESC LIMIT 1", (head['id'], head['status'])).fetchone()
    if decided and staff and 'Registrado por el personal: ' in decided['detail']:
        note = decided['detail'].split('Registrado por el personal: ', 1)[1][:300]
    sent = c.execute("SELECT MIN(created_at) FROM quote_events WHERE quote_id=? AND event='enviado'", (head['id'],)).fetchone()[0] or head['sent_at']
    opened = c.execute("SELECT MIN(verified_at) FROM quote_links WHERE quote_id=? AND verified_at!=''", (head['id'],)).fetchone()[0] or ''
    working = c.execute("SELECT occurred_at FROM order_history WHERE order_id=? AND event='status' AND status_label='Procesando' AND occurred_at>=? ORDER BY id LIMIT 1", (order_id, head['decided_at'])).fetchone()
    steps = [{'key': 'enviado', 'label': 'Enviado', 'done': bool(sent), 'at': sent or ''},
             {'key': 'revision', 'label': 'En revisión', 'done': bool(opened), 'at': opened, 'note': '' if opened else ('El cliente no abrió el enlace: la decisión la registró el personal.' if staff else '')},
             {'key': 'aprobado', 'label': 'Aprobado parcialmente' if head['status'] == 'parcial' else 'Aprobado', 'done': head['status'] in ('aprobado', 'parcial'), 'at': head['decided_at']},
             {'key': 'procesando', 'label': 'Procesando', 'done': bool(working) or order_status in PROCESSING, 'at': working['occurred_at'] if working else ''}]
    codes = list(dict.fromkeys(item['quote_code'] for item in items))
    history = []
    for row in chain(c, head):
        for e in c.execute('SELECT event,detail,actor,created_at FROM quote_events WHERE quote_id=? ORDER BY id', (row['id'],)):
            history.append({'quote': row['code'], 'event': e['event'], 'detail': e['detail'], 'actor': e['actor'] or 'Sistema', 'at': e['created_at']})
    history.sort(key=lambda e: e['at'], reverse=True)
    t = totals(items_of(c, head['id']), head['tax_rate_bp'], head['discount_bp'])
    return {'quote_id': head['id'], 'code': head['code'], 'codes': codes, 'status': head['status'], 'status_label': STATUS[head['status']], 'decided_at': head['decided_at'],
            'by_staff': staff, 'staff_name': who, 'staff_note': note, 'signed': bool(acceptance), 'signer': acceptance['signer_name'] if acceptance else '',
            'method': acceptance['method'] if acceptance else '', 'evidence_hash': (acceptance['evidence_hash'] or '')[:16] if acceptance else '',
            'approved_count': len(items), 'total_count': sum(t['count'][k] for k in ('aprobado', 'rechazado', 'pendiente')) if len(codes) == 1 else None,
            'subtotal_cents': sum(item['base_cents'] for item in items), 'tax_cents': sum(item['tax_cents'] for item in items), 'total_cents': sum(item['net_cents'] for item in items),
            'steps': steps, 'history': history[:60]}


def set_execution(c, quote, item_id, value, user, now):
    """Avance de una partida aprobada (pendiente, en proceso, realizado). No cambia importes, pagos ni el estado del equipo."""
    if value not in EXECUTION:
        raise QuoteError('Estado de ejecución no válido.')
    item = c.execute('SELECT * FROM quote_items WHERE id=? AND quote_id=?', (item_id, quote['id'])).fetchone()
    if not item or item['status'] != 'aprobado' or quote['status'] not in DECIDED:
        raise QuoteError('Solo se marca el avance de partidas aprobadas por el cliente.', 409)
    if item['execution'] != value:
        c.execute('UPDATE quote_items SET execution=?,execution_by=?,execution_at=? WHERE id=?', (value, user['id'], now.isoformat(timespec='seconds'), item['id']))
        event(c, quote['id'], 'ejecucion', '«%s»: %s.' % (item['description'][:80], EXECUTION[value].lower()), now, user)


def sync_budget(c, quote):
    """Traslada lo aprobado al presupuesto de la orden (del que salen el total a cobrar y el saldo). No toca pagos ni estado."""
    lines = [(BUDGET_KEY[item['category']], ('%d × ' % item['quantity'] if item['quantity'] > 1 else '') + item['description'], item['net_cents']) for item in approved_lines(c, get(c, quote['id']))]
    sums = {key: sum(amount for category, _, amount in lines if category == key) for key in ('labor', 'parts', 'services', 'digital')}
    c.execute('INSERT INTO order_budget(order_id,labor_cents,parts_cents,services_cents,digital_cents) VALUES (?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET labor_cents=excluded.labor_cents,parts_cents=excluded.parts_cents,services_cents=excluded.services_cents,digital_cents=excluded.digital_cents',
              (quote['order_id'], sums['labor'], sums['parts'], sums['services'], sums['digital']))
    c.execute('DELETE FROM order_budget_lines WHERE order_id=?', (quote['order_id'],))
    c.executemany('INSERT INTO order_budget_lines(order_id,category,description,amount_cents) VALUES (?,?,?,?)', [(quote['order_id'], category, description[:250], amount) for category, description, amount in lines])


def decide(c, quote, decisions, now, user=None, actor='', note=''):
    """Registra la decisión sobre cada ítem. `decisions`: {id de ítem: 'aprobado' | 'rechazado' | 'pendiente'}.
    Lo que queda pendiente no se cuenta como aprobado ni rechazado: el taller lo ofrece después en una versión de continuación."""
    if quote['status'] != 'enviado':
        raise QuoteError('Este presupuesto no está pendiente de decisión.', 409)
    items = [item for item in items_of(c, quote['id']) if item['status'] != 'cancelado']
    if set(decisions) != {item['id'] for item in items} or any(value not in ('aprobado', 'rechazado', 'pendiente') for value in decisions.values()):
        raise QuoteError('Indica si apruebas o rechazas cada uno de los ítems.')
    if all(value == 'pendiente' for value in decisions.values()):
        raise QuoteError('Decide al menos una partida: aprueba o rechaza alguna antes de confirmar.')
    previous = sum(line['net_cents'] for old in chain(c, quote)[1:] for line in approved_lines(c, old) if line['quote_id'] == old['id'])
    import equipment
    paid = equipment.money(c, quote['order_id'])['paid_cents']  # pagos netos del equipo: la misma fuente que el saldo
    approved_total = previous + sum(net(item['quantity'] * item['unit_cents'], quote['discount_bp']) for item in items if decisions[item['id']] == 'aprobado')
    if paid > approved_total:
        raise QuoteError('La orden ya tiene pagos registrados por %s, más que el total aprobado (%s). Revisa los pagos antes de registrar esta decisión.' % (usd(paid), usd(approved_total)), 409)
    for item in items:
        c.execute('UPDATE quote_items SET status=? WHERE id=?', (decisions[item['id']], item['id']))
    approved = sum(1 for value in decisions.values() if value == 'aprobado')
    waiting = sum(1 for value in decisions.values() if value == 'pendiente')
    status, stamp = ('aprobado' if approved == len(items) else 'rechazado' if not approved else 'parcial'), now.isoformat(timespec='seconds')
    c.execute('UPDATE quotes SET status=?,decided_at=?,decided_by=?,updated_at=? WHERE id=?', (status, stamp, 'cliente' if not user else 'personal:%d' % user['id'], stamp, quote['id']))
    c.execute("UPDATE quote_links SET revoked_at=? WHERE quote_id=? AND revoked_at=''", (stamp, quote['id']))
    sync_budget(c, quote)
    sync_order(c, quote, status, now)
    if status in ('aprobado', 'parcial'):
        # Licencias digitales con inventario: se reservan unidades concretas (sin revelar credenciales). Un borrador no descuenta nada.
        import licenses
        held = licenses.reserve_for_quote(c, quote, now, user, actor or ('' if user else 'cliente'))
        if held['reserved'] or held['missing']:
            event(c, quote['id'], 'licencias', '%d %s reservada%s del inventario.%s' % (held['reserved'], 'licencia' if held['reserved'] == 1 else 'licencias', '' if held['reserved'] == 1 else 's',
                  (' %d pendiente%s de existencias.' % (held['missing'], '' if held['missing'] == 1 else 's')) if held['missing'] else ''), now, user, actor)
    event(c, quote['id'], status, '%d de %d ítems aprobados%s. Total autorizado: %s.%s' % (approved, len(items), ('; %d quedaron pendientes para una nueva versión' % waiting) if waiting else '', usd(approved_total), ' ' + note if note else ''), now, user, actor)
    return status


def removable(c, quote):
    """Motivo por el que un presupuesto NO se puede eliminar como borrador; '' si se puede. Solo borradores que nunca salieron del taller."""
    if quote.get('deleted_at'):
        return 'Este borrador ya fue eliminado.'
    if quote['status'] != 'borrador' or quote['sent_at'] or quote['decided_at']:
        return 'Solo se eliminan borradores que no se han enviado al cliente. Un presupuesto enviado o decidido se anula, no se elimina.'
    if c.execute('SELECT 1 FROM quote_links WHERE quote_id=?', (quote['id'],)).fetchone() or c.execute('SELECT 1 FROM quote_acceptances WHERE quote_id=?', (quote['id'],)).fetchone():
        return 'Este presupuesto ya tuvo un enlace o una autorización del cliente: no se elimina.'
    if c.execute('SELECT 1 FROM quotes WHERE continues_id=?', (quote['id'],)).fetchone():
        return 'Otra versión continúa este presupuesto: no se elimina.'
    return ''


def delete_draft(c, quote, user, now):
    """Eliminación lógica de un borrador: sale de las listas y deja de editarse; su registro y su historial se conservan."""
    reason = removable(c, quote)
    if reason:
        raise QuoteError(reason, 409)
    if user['role'] != 'administrador' and quote['created_by'] != user['id']:
        raise QuoteError('Solo administración o quien creó el borrador puede eliminarlo.', 403)
    stamp = now.isoformat(timespec='seconds')
    c.execute("UPDATE quotes SET deleted_at=?,deleted_by=?,updated_at=? WHERE id=? AND deleted_at='' AND status='borrador'", (stamp, user['id'], stamp, quote['id']))
    event(c, quote['id'], 'eliminado', 'Borrador eliminado. Su registro se conserva para auditoría.', now, user)


def cancel(c, quote, user, now, reason=''):
    if quote['status'] in ('cancelado',):
        raise QuoteError('El presupuesto ya estaba cancelado.', 409)
    if quote['status'] in ('aprobado', 'parcial'):
        raise QuoteError('Un presupuesto con servicios aprobados no se cancela: crea una nueva versión si cambian los trabajos.', 409)
    stamp = now.isoformat(timespec='seconds')
    c.execute("UPDATE quotes SET status='cancelado',updated_at=? WHERE id=?", (stamp, quote['id']))
    c.execute("UPDATE quote_links SET revoked_at=? WHERE quote_id=? AND revoked_at=''", (stamp, quote['id']))
    event(c, quote['id'], 'cancelado', 'Presupuesto cancelado.' + (' Motivo: ' + reason[:300] if reason else ''), now, user)


# --- Aprobación del cliente por enlace privado ------------------------------------------------------------------------

def lookup(c, token, now):
    """Presupuesto del enlace, o None si el enlace no existe, venció o fue revocado."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{30,80}', token or ''):
        return None, None
    link = c.execute('SELECT * FROM quote_links WHERE token_hash=?', (digest(token),)).fetchone()
    if not link:
        return None, None
    quote = get(c, link['quote_id'])
    # Un enlace revocado sigue sirviendo para consultar el resultado ya registrado, nunca para decidir de nuevo.
    usable = not link['revoked_at'] and datetime.fromisoformat(link['expires_at']) >= now and link['failed'] < MAX_FAILED
    return quote, dict(link, usable=usable)


def verify(c, link, identification, last4, now):
    """Comprobación de identidad: últimos cuatro dígitos de la identificación registrada del cliente."""
    number = re.sub(r'\D', '', str(identification or ''))
    if len(number) < 6:
        raise QuoteError('El cliente no tiene una identificación registrada con la que comprobar su identidad. Comunícate con el taller.', 409)
    if not re.fullmatch(r'\d{4}', str(last4 or '')) or not secrets.compare_digest(number[-4:], str(last4)):
        c.execute('UPDATE quote_links SET failed=failed+1 WHERE id=?', (link['id'],))
        return False
    return True


def clean_signature(raw):
    """Firma manuscrita como trazos vectoriales [[x,y],…] en una rejilla de 1000 × 300. Vacía si no es válida."""
    try:
        strokes = json.loads(raw) if isinstance(raw, str) and raw else []
    except ValueError:
        return []
    if not isinstance(strokes, list) or len(strokes) > 80:
        return []
    clean, points = [], 0
    for stroke in strokes:
        if not isinstance(stroke, list):
            return []
        line = [[int(p[0]), int(p[1])] for p in stroke if isinstance(p, list) and len(p) == 2 and all(type(v) in (int, float) for v in p) and 0 <= p[0] <= 1000 and 0 <= p[1] <= 300]
        points += len(line)
        if len(line) >= 2:
            clean.append(line)
    return clean if points <= 4000 and sum(len(line) for line in clean) >= 8 else []


def clean_document(raw):
    """Documento de identidad enviado desde la página: imagen (PNG, JPEG, WebP) o PDF reales, de tamaño acotado. (tipo, contenido) o None."""
    import base64
    try:
        content = base64.b64decode(str(raw or '').split(',')[-1], validate=True)
    except Exception:
        return None
    if not 200 <= len(content) <= DOCUMENT_LIMIT:
        return None
    kind = ('image/png' if content[:8] == b'\x89PNG\r\n\x1a\n' else 'image/jpeg' if content[:3] == b'\xff\xd8\xff' else 'image/webp' if content[:4] == b'RIFF' and content[8:12] == b'WEBP'
            else 'application/pdf' if content[:5] == b'%PDF-' else None)
    return (kind, content) if kind else None


def accept(c, quote, link, form, order, now, origin):
    """Decisión del cliente con su evidencia. `form`: decision_<id>, accept, name, signature, comment, action."""
    if quote['status'] != 'enviado' or not link['usable']:
        raise QuoteError('Este presupuesto ya no admite una decisión desde este enlace.', 409)
    items = [item for item in items_of(c, quote['id']) if item['status'] != 'cancelado']
    comment = str(form.get('comment', '')).strip()[:600]
    if form.get('action') == 'change':
        if len(comment) < 5:
            raise QuoteError('Describe qué cambio necesitas en el presupuesto.', fields={'comment': 'Escribe tu solicitud.'})
        stamp = now.isoformat(timespec='seconds')
        c.execute("UPDATE quotes SET status='modificacion',updated_at=? WHERE id=?", (stamp, quote['id']))
        c.execute("UPDATE quote_links SET revoked_at=? WHERE id=?", (stamp, link['id']))
        event(c, quote['id'], 'modificacion', 'El cliente solicitó una modificación: ' + comment, now, actor='Cliente')
        return 'modificacion'
    decisions = {item['id']: form.get('decision_%d' % item['id'], '') for item in items}
    errors = {}
    if any(value not in ('aprobado', 'rechazado', 'pendiente') for value in decisions.values()):
        errors['items'] = 'Indica si apruebas o rechazas cada servicio.'
    elif all(value == 'pendiente' for value in decisions.values()):
        errors['items'] = 'Decide al menos un servicio: aprueba o rechaza alguno antes de confirmar.'
    name = re.sub(r'\s+', ' ', str(form.get('name', ''))).strip()
    if not 5 <= len(name) <= 120:
        errors['name'] = 'Escribe tu nombre completo.'
    if form.get('accept') != 'on':
        errors['accept'] = 'Debes aceptar expresamente las condiciones.'
    signature = clean_signature(form.get('signature', ''))
    approving = any(value == 'aprobado' for value in decisions.values())
    if approving and not signature:
        errors['signature'] = 'Firma en el recuadro para autorizar los servicios aprobados.'
    document = None
    if quote.get('require_id') and approving:
        document = clean_document(form.get('id_document', ''))
        if not document:
            errors['id_document'] = 'Adjunta una foto o PDF legible de tu documento de identidad (hasta 700 KB).'
    if errors:
        raise QuoteError('Revisa los datos señalados.', fields=errors)
    status = decide(c, quote, decisions, now, actor='Cliente: ' + name, note=('Observación del cliente: ' + comment) if comment else '')
    final = items_of(c, quote['id'])
    document_hash = hashlib.sha256(document[1]).hexdigest() if document else ''
    if document:
        c.execute('INSERT OR REPLACE INTO quote_documents(quote_id,mime,data,sha256,created_at) VALUES (?,?,?,?,?)', (quote['id'], document[0], document[1], document_hash, now.isoformat(timespec='seconds')))
    evidence = {'identity_document_sha256': document_hash, 'quote': quote['code'], 'order': order['code'], 'signer': name, 'method': METHOD, 'accepted_at': now.isoformat(timespec='seconds'), 'conditions': quote['conditions'] or CONDITIONS, 'comment': comment,
                'tax_rate_bp': quote['tax_rate_bp'], 'items': [{'description': item['description'], 'quantity': item['quantity'], 'unit_cents': item['unit_cents'], 'taxed': bool(item['taxed']), 'decision': item['status']} for item in final],
                'discount_bp': quote['discount_bp'], 'totals': {key: value for key, value in totals(final, quote['tax_rate_bp'], quote['discount_bp']).items() if key != 'count'}, 'signature_points': sum(len(line) for line in signature), 'ip': origin.get('ip', ''), 'agent': origin.get('agent', '')}
    payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    c.execute('INSERT INTO quote_acceptances(quote_id,signer_name,method,signature,evidence,evidence_hash,created_at) VALUES (?,?,?,?,?,?,?)', (quote['id'], name, METHOD, json.dumps(signature), payload, digest(payload + json.dumps(signature)), now.isoformat(timespec='seconds')))
    return status


def evidence_ok(c, quote_id):
    row = c.execute('SELECT evidence,signature,evidence_hash FROM quote_acceptances WHERE quote_id=?', (quote_id,)).fetchone()
    return bool(row) and digest(row['evidence'] + row['signature']) == row['evidence_hash']


# --- Páginas del enlace privado ---------------------------------------------------------------------------------------

def _shell(title, body):
    import html
    from corporate import settings
    company = settings()
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta name="robots" content="noindex,nofollow">'
            '<title>%s | PC-DOCTOR S.A.</title><link rel="icon" href="/favicon.ico?v=2" sizes="48x48"><link rel="stylesheet" href="/static/tracking.css"><link rel="stylesheet" href="/static/quote.css"><script defer src="/static/quote-sign.js"></script></head>'
            '<body><main class="tracking-page quote-page"><header><img src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="150"><p>%s</p></header>%s'
            '<footer><p>WhatsApp: %s</p><p class="tracking-note">La firma de esta página es un trazo manuscrito digitalizado con registro de fecha, hora y método de verificación. No es una firma electrónica certificada.</p></footer></main></body></html>'
            ) % (html.escape(title), html.escape(company['specialty']), body, html.escape(company['whatsapp']))


def missing_page():
    return _shell('Enlace no disponible', '<section class="tracking-card"><h1>Enlace no disponible</h1><p>Este enlace de presupuesto no existe, venció o fue reemplazado por una versión más reciente. Comunícate con el taller.</p></section>')


def _summary_block(quote, order):
    import html
    e = html.escape
    device = ' '.join(part for part in (order.get('brand') or '', order.get('model') or '') if part) or 'Equipo'
    return '<small>PRESUPUESTO</small><h1>%s</h1><p class="quote-device">Orden %s · %s</p>' % (e(quote['code']), e(order['code']), e(device))


def identify_page(token, quote, order, error=''):
    import html
    return _shell('Presupuesto ' + quote['code'], '<section class="tracking-card quote-card">%s<form class="auth-form" method="post" action="/presupuesto/%s" autocomplete="off">%s'
                  '<p class="auth-step">Paso 1 de 2 · Comprueba tu identidad</p><label for="last4">Escribe los <strong>últimos cuatro dígitos</strong> de tu cédula o RUC</label>'
                  '<input id="last4" name="last4" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" required autofocus><button class="quote-primary" type="submit">Ver mi presupuesto</button></form></section>'
                  % (_summary_block(quote, order), html.escape(token), '<p class="quote-error" role="alert">%s</p>' % html.escape(error) if error else ''))


def bank_for(c, quote):
    """Cuenta para depósito o transferencia del presupuesto: la elegida o, si no se eligió, la predeterminada activa del catálogo."""
    import banking
    try:
        chosen = quote['bank_account_id'] if 'bank_account_id' in quote.keys() else None
        row = c.execute('SELECT * FROM bank_accounts WHERE id=? AND active=1', (chosen,)).fetchone() if chosen else c.execute('SELECT * FROM bank_accounts WHERE is_default=1 AND active=1').fetchone()
    except sqlite3.OperationalError:
        return None  # instalación sin el catálogo de cuentas todavía
    return banking.public(row)


def bank_html(account):
    """Bloque de la página del cliente con los datos de la cuenta y un botón para copiarlos (texto plano, sin estilos en línea)."""
    import html
    if not account:
        return ''
    e = html.escape
    rows = ''.join('<div><dt>%s</dt><dd>%s</dd></div>' % (e(k), e(v)) for k, v in (('Banco', account['bank']), ('Tipo de cuenta', account['type_label']), ('Número de cuenta', account['number']),
                                                                                  ('Titular', account['holder']), ('RUC / identificación', account['holder_id'])))
    return ('<section class="quote-bank"><h2>Datos para depósito o transferencia</h2><dl>%s</dl><button type="button" class="quote-secondary" data-copy-bank="%s">Copiar datos bancarios</button>'
            '<p class="quote-bank-note" data-copy-status role="status"></p></section>') % (rows, e(account['copy_text'], quote=True))


def decision_page(token, passkey, quote, order, items, errors=None, form=None, bank=''):
    import html
    e, errors, form = html.escape, errors or {}, form or {}
    summary = totals(items, quote['tax_rate_bp'], quote['discount_bp'])
    rows = ''
    for item in items:
        if item['status'] == 'cancelado':
            continue
        chosen = form.get('decision_%d' % item['id'], '')
        rows += ('<fieldset class="quote-item"><legend>%s%s</legend>%s<p class="quote-amount">%s%s · <strong>%s</strong>%s</p>'
                 '<label><input type="radio" name="decision_%d" value="aprobado"%s required> Apruebo este servicio</label>'
                 '<label><input type="radio" name="decision_%d" value="rechazado"%s> No lo apruebo</label>'
                 '<label><input type="radio" name="decision_%d" value="pendiente"%s> Lo decidiré después</label></fieldset>'
                 ) % (_icon(item), e(item['description']), _priority(item), '%d × ' % item['quantity'] if item['quantity'] > 1 else '', e(usd(item['unit_cents'])), e(usd(net(item['quantity'] * item['unit_cents'], quote['discount_bp']))), '' if item['taxed'] else ' <small>(tarifa 0 %)</small>',
                      item['id'], ' checked' if chosen == 'aprobado' else '', item['id'], ' checked' if chosen == 'rechazado' else '', item['id'], ' checked' if chosen == 'pendiente' else '')
    problem = lambda key: '<p class="quote-error" role="alert">%s</p>' % e(errors[key]) if errors.get(key) else ''
    rate = quote['tax_rate_bp'] / 100
    conditions = ''.join('<li>%s%s</li>' % ('<strong>%s.</strong> ' % e(title.rstrip('.')) if title else '', e(body)) for title, body in clauses(quote['conditions'] or CONDITIONS))
    body = ('<section class="tracking-card quote-card">%s<p class="quote-valid">%s</p>'
            '<form class="auth-form quote-form" method="post" action="/presupuesto/%s" autocomplete="off"><input type="hidden" name="passkey" value="%s">'
            '<p class="auth-step">Paso 2 de 2 · Revisa y decide cada servicio</p><div class="quote-bulk"><button type="button" data-quote-all="aprobado">Aprobar todo</button><button type="button" data-quote-all="rechazado">Rechazar todo</button></div>%s%s'
            '<dl class="quote-totals">%s<div><dt>Subtotal con IVA %g %%</dt><dd>%s</dd></div><div><dt>Subtotal tarifa 0 %%</dt><dd>%s</dd></div><div><dt>IVA %g %%</dt><dd>%s</dd></div><div class="quote-total"><dt>Total cotizado</dt><dd>%s</dd></div>'
            '<div class="quote-chosen"><dt>Total que apruebas</dt><dd data-quote-approved>—</dd></div></dl>' + bank.replace('%', '%%') +
            '<h2>Condiciones de autorización</h2><ul class="quote-conditions">%s</ul>'
            '<label for="name">Nombre completo de quien autoriza</label><input id="name" name="name" maxlength="120" value="%s" required>%s'
            '<label for="comment">Observaciones (opcional)</label><textarea id="comment" name="comment" rows="2" maxlength="600">%s</textarea>%s'
            '<p class="quote-sign-label">Firma con el dedo o el ratón dentro del recuadro</p><div class="quote-sign" data-quote-sign><canvas width="1000" height="300" aria-label="Recuadro de firma"></canvas><button type="button" data-quote-clear>Borrar firma</button></div><input type="hidden" name="signature" value="">%s'
            '%s<label class="quote-accept"><input type="checkbox" name="accept"%s required> He leído los importes y las condiciones, y confirmo mi decisión sobre cada servicio.</label>%s'
            '<button class="quote-primary" type="submit" name="action" value="decide">Confirmar mi decisión</button>'
            '<button class="quote-secondary" type="submit" name="action" value="change" formnovalidate>Solicitar una modificación</button></form>'
            '<p class="quote-pdf"><a href="/presupuesto/%s/documento.pdf?k=%s">Descargar el presupuesto en PDF</a></p></section>'
            ) % (_summary_block(quote, order), 'Válido hasta el ' + e(date.fromisoformat(quote['valid_until']).strftime('%d/%m/%Y')) if quote['valid_until'] else 'Sin fecha límite indicada', e(token), e(passkey), problem('items'), rows,
                 ('<div><dt>%s (%g %%)</dt><dd>− %s</dd></div>' % (e(DISCOUNTS[quote['discount_bp']]), quote['discount_bp'] / 100, e(usd(summary['discount']))) if quote['discount_bp'] else ''), rate, e(usd(summary['base_taxed'])), e(usd(summary['base_zero'])), rate, e(usd(summary['tax'])), e(usd(summary['quoted'])), conditions, e(form.get('name', '')), problem('name'), e(form.get('comment', '')), problem('comment'), problem('signature'),
                 ('<div class="quote-document" data-quote-document><p class="quote-sign-label">Documento de identidad</p><p class="quote-document-note">%s</p><input type="file" accept="image/png,image/jpeg,image/webp,application/pdf" aria-label="Foto o PDF de tu documento de identidad"><input type="hidden" name="id_document" value=""><small data-quote-document-status>Formatos: foto (JPG, PNG, WebP) o PDF, hasta 700 KB. Solo se exige si apruebas algún servicio.</small></div>%s' % (e(DOCUMENT_NOTICE), problem('id_document'))) if quote.get('require_id') else '',
                 ' checked' if form.get('accept') == 'on' else '', problem('accept'), e(token), e(passkey))
    return _shell('Presupuesto ' + quote['code'], body)


def _icon(item):
    return '<svg class="quote-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="%s"/></svg>' % catalog_icons.svg_path(item.get('icon') or 'generico')


def _priority(item):
    """Clasificación de la partida para la página del cliente: texto y color (por clase; la página no usa estilos en línea)."""
    return '<span class="quote-priority" data-priority="%s">%s</span>' % (item['priority'], PRIORITIES[item['priority']][0]) if item.get('priority') else ''


def result_page(token, quote, order, items, bank=''):
    import html
    e = html.escape
    summary = totals(items, quote['tax_rate_bp'], quote['discount_bp'])
    lines = ''.join('<li data-status="%s"><span>%s%s</span><strong>%s</strong><em>%s</em></li>' % (e(item['status']), e(item['description']), (' ' + _priority(item)) if item.get('priority') else '', e(usd(net(item['quantity'] * item['unit_cents'], quote['discount_bp']))), e('Por decidir' if item['status'] == 'pendiente' and quote['status'] in DECIDED else ITEM_STATUS[item['status']])) for item in items if item['status'] != 'cancelado')
    waiting = quote['status'] in DECIDED and summary['pending'] > 0
    message = {'modificacion': 'Recibimos tu solicitud de modificación. El taller revisará el presupuesto y te enviará una nueva versión.', 'rechazado': 'Registramos que no apruebas este presupuesto. No se ejecutará ningún trabajo sin tu autorización.',
               'cancelado': 'Este presupuesto fue cancelado por el taller.'}.get(quote['status'], 'Registramos tu decisión. El taller ejecutará únicamente los servicios aprobados y te avisará del avance.')
    if waiting:
        message = 'Registramos tu decisión. Solo se ejecutarán los servicios aprobados. Los que dejaste por decidir (%s) no se realizarán por ahora: el taller te enviará un nuevo presupuesto con ellos.' % usd(summary['pending'])
    extra = '<dl class="quote-totals"><div><dt>Total cotizado</dt><dd>%s</dd></div><div class="quote-total"><dt>Total aprobado</dt><dd>%s</dd></div><div><dt>Importe rechazado</dt><dd>%s</dd></div></dl>' % (e(usd(summary['quoted'])), e(usd(summary['approved'])), e(usd(summary['rejected']))) if quote['status'] in ('aprobado', 'parcial', 'rechazado') else ''
    # Datos bancarios solo si queda algo aprobado por pagar (no en rechazados, cancelados ni modificaciones).
    payable = bank if quote['status'] in ('aprobado', 'parcial') else ''
    return _shell('Presupuesto ' + quote['code'], '<section class="tracking-card quote-card">%s<p class="tracking-state quote-state" data-status="%s">%s</p><p>%s</p><ul class="quote-result">%s</ul>%s%s</section>' % (_summary_block(quote, order), e(quote['status']), e(STATUS[quote['status']]), e(message), lines, extra, payable))


def handle(c, token, quote, link, order, form, now, origin):
    """Atiende el formulario del enlace. Devuelve (página HTML, estado nuevo o None)."""
    items = items_of(c, quote['id'])
    if quote['status'] != 'enviado' or not link['usable']:
        return (result_page(token, quote, order, items, bank_html(bank_for(c, quote))) if quote['status'] != 'enviado' else missing_page()), None
    passkey = str(form.get('passkey', ''))
    if not passkey:
        # Paso 1: comprobación de identidad. Al acertar se emite una llave de un solo uso para el paso 2 (treinta minutos).
        if not verify(c, link, order.get('identification'), form.get('last4'), now):
            return identify_page(token, quote, order, 'Los dígitos no coinciden con la identificación registrada.'), None
        passkey = secrets.token_urlsafe(24)
        c.execute('UPDATE quote_links SET verified_at=?,passkey_hash=?,failed=0 WHERE id=?', (now.isoformat(timespec='seconds'), digest(passkey), link['id']))
        return decision_page(token, passkey, quote, order, items, bank=bank_html(bank_for(c, quote))), None
    if not valid_passkey(link, passkey, now):
        return identify_page(token, quote, order, 'La comprobación de identidad caducó. Vuelve a escribir los cuatro dígitos.'), None
    try:
        status = accept(c, quote, link, form, order, now, origin)
    except QuoteError as error:
        if not error.fields:
            return identify_page(token, quote, order, str(error)), None
        return decision_page(token, passkey, quote, order, items, error.fields, form, bank_html(bank_for(c, quote))), None
    return result_page(token, get(c, quote['id']), order, items_of(c, quote['id']), bank_html(bank_for(c, quote))), status


def valid_passkey(link, passkey, now):
    if not link.get('passkey_hash') or not link.get('verified_at') or not secrets.compare_digest(link['passkey_hash'], digest(str(passkey))):
        return False
    return datetime.fromisoformat(link['verified_at']) + timedelta(minutes=30) >= now
