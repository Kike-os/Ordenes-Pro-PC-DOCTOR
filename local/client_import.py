"""Importación de clientes desde hojas de cálculo.

Lee .xls, .xlsx, tablas HTML guardadas como .xls y texto delimitado. Analiza sin escribir
(`analyze`) y solo inserta al confirmar (`commit`), después de crear una copia de seguridad.
Nunca sobrescribe clientes existentes: un duplicado se omite o, si se autoriza fila a fila,
completa únicamente los campos que la ficha tiene vacíos. Los valores originales de cada fila
se conservan en `client_import_rows`.
"""
import csv
import hashlib
import io
import json
import re
import sys
import unicodedata
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
import geography
from reception import document_error, valid_ecuador_phone

MAX_BYTES = 6_000_000
MAX_ROWS = 20000
FIELDS = {
    'identification': ('identificacion', 'cedula', 'ruc', 'cedula ruc', 'ruc cedula', 'ci', 'ci ruc', 'ruc ci', 'documento', 'numero identificacion', 'nro identificacion', 'no identificacion', 'num identificacion', 'identificacion cliente', 'numero de identificacion', 'dni', 'nit', 'id cliente'),
    'document_type': ('tipo identificacion', 'tipo de identificacion', 'tipo documento', 'tipo de documento', 'tipo id'),
    'name': ('nombre', 'nombres', 'cliente', 'razon social', 'nombre cliente', 'nombres y apellidos', 'apellidos y nombres', 'nombre completo', 'razon social nombres', 'nombre razon social', 'nombres razon social', 'contribuyente', 'titular'),
    'surname': ('apellido', 'apellidos'),
    'trade_name': ('nombre comercial', 'comercial', 'nombre fantasia', 'establecimiento'),
    'phone': ('telefono', 'celular', 'movil', 'telefono celular', 'telefono 1', 'telefono1', 'telefono movil', 'whatsapp', 'telefonos', 'fono', 'contacto telefono', 'cel'),
    'phone_secondary': ('telefono 2', 'telefono2', 'convencional', 'telefono convencional', 'telefono fijo', 'fijo', 'telefono domicilio', 'celular 2', 'telefono trabajo'),
    'email': ('correo', 'email', 'e mail', 'mail', 'correo electronico', 'correo e', 'email cliente'),
    'address': ('direccion', 'domicilio', 'direccion domicilio', 'direccion cliente', 'calle', 'calle principal', 'direccion principal'),
    'province': ('provincia',),
    'canton': ('canton',),
    'city': ('ciudad', 'localidad', 'poblacion'),
    'parish': ('parroquia',),
    'location_reference': ('referencia', 'referencia direccion', 'referencia ubicacion'),
    'notes': ('observacion', 'observaciones', 'nota', 'notas', 'comentario', 'comentarios', 'detalle'),
}
LABELS = {'identification': 'Identificación', 'document_type': 'Tipo de identificación', 'name': 'Nombre o razón social', 'surname': 'Apellidos', 'trade_name': 'Nombre comercial', 'phone': 'Teléfono', 'phone_secondary': 'Teléfono secundario', 'email': 'Correo electrónico', 'address': 'Dirección', 'province': 'Provincia', 'canton': 'Cantón', 'city': 'Ciudad', 'parish': 'Parroquia', 'location_reference': 'Referencia', 'notes': 'Observaciones'}
CLIENT_COLUMNS = ('name', 'client_type', 'country', 'document_type', 'identification', 'trade_name', 'phone', 'phone_secondary', 'email', 'province', 'province_code', 'canton', 'canton_code', 'parish', 'parish_code', 'city', 'locality_code', 'address', 'main_street', 'secondary_street', 'building_number', 'location_reference', 'geo_version', 'notes')
FILLABLE = ('trade_name', 'phone', 'phone_secondary', 'email', 'address', 'main_street', 'location_reference', 'notes')


class ImportError_(ValueError):
    pass


def plain(value):
    text = ''.join(ch for ch in unicodedata.normalize('NFD', str(value).casefold()) if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def cell_text(value):
    """Texto de una celda sin los artefactos numéricos de Excel (1712345678.0, 9.91234567E8)."""
    if value is None:
        return ''
    if isinstance(value, float):
        return str(int(value)) if value == int(value) and abs(value) < 1e17 else repr(value)
    text = str(value).replace('\xa0', ' ').strip()
    if re.fullmatch(r'[0-9]+\.0+', text):
        return text.split('.')[0]
    if re.fullmatch(r'[0-9](?:\.[0-9]+)?[eE]\+?[0-9]{1,2}', text):
        try:
            number = float(text)
            if number == int(number):
                return str(int(number))
        except ValueError:
            pass
    return re.sub(r'\s+', ' ', text)


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None and self.row is not None:
            self.row.append(''.join(self.cell))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def _xlsx(raw):
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(raw)) as book:
        names = book.namelist()
        if sum(book.getinfo(name).file_size for name in names) > 80_000_000:
            raise ImportError_('El archivo es demasiado grande.')
        shared = []
        if 'xl/sharedStrings.xml' in names:
            for item in ElementTree.fromstring(book.read('xl/sharedStrings.xml')).findall('m:si', ns):
                shared.append(''.join(node.text or '' for node in item.iter('{%s}t' % ns['m'])))
        sheets = sorted((name for name in names if re.fullmatch(r'xl/worksheets/sheet[0-9]+\.xml', name)), key=lambda name: int(re.findall(r'[0-9]+', name)[-1]))
        best = []
        for name in sheets:
            rows = []
            for row in ElementTree.fromstring(book.read(name)).iter('{%s}row' % ns['m']):
                values = []
                for cell in row.findall('m:c', ns):
                    letters = re.match(r'[A-Z]+', cell.get('r', 'A')).group()
                    index = 0
                    for letter in letters:
                        index = index * 26 + ord(letter) - 64
                    while len(values) < index:
                        values.append('')
                    kind, node = cell.get('t'), cell.find('m:v', ns)
                    if kind == 'inlineStr':
                        text = ''.join(part.text or '' for part in cell.iter('{%s}t' % ns['m']))
                    elif node is None:
                        text = ''
                    elif kind == 's':
                        text = shared[int(node.text)]
                    else:
                        text = node.text or ''
                    values[index - 1] = text
                rows.append(values)
            if len(rows) > len(best):
                best = rows
        return best


def read_rows(raw, filename=''):
    """Devuelve todas las filas de la hoja con más registros, como listas de texto."""
    if not raw:
        raise ImportError_('El archivo está vacío.')
    if len(raw) > MAX_BYTES:
        raise ImportError_('El archivo supera el tamaño máximo de 6 MB.')
    try:
        if raw[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            import xlrd
            book = xlrd.open_workbook(file_contents=raw)
            sheet = max(book.sheets(), key=lambda item: item.nrows)
            rows = []
            for index in range(sheet.nrows):
                values = []
                for cell in sheet.row(index):
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            values.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode).date().isoformat())
                        except Exception:
                            values.append(cell_text(cell.value))
                    else:
                        values.append(cell.value)
                rows.append(values)
        elif raw[:2] == b'PK':
            rows = _xlsx(raw)
        else:
            text = None
            for encoding in ('utf-8-sig', 'utf-16', 'cp1252', 'latin-1'):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeError:
                    continue
            if re.search(r'<\s*(table|tr)\b', text[:20000], re.I):
                parser = _Tables()
                parser.feed(text)
                rows = parser.rows
            else:
                sample = text[:5000]
                delimiter = max('\t;,|', key=sample.count)
                rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except ImportError_:
        raise
    except Exception:
        raise ImportError_('No se pudo leer el archivo. Usa un Excel (.xls o .xlsx) o un CSV válido.')
    rows = [[cell_text(value) for value in row] for row in rows]
    rows = [row for row in rows if any(row)]
    if not rows:
        raise ImportError_('El archivo no contiene registros.')
    if len(rows) > MAX_ROWS:
        raise ImportError_('El archivo supera el máximo de ' + str(MAX_ROWS) + ' filas.')
    return rows


def match_field(header):
    key = plain(header)
    if not key:
        return None
    for field, names in FIELDS.items():
        if key in names:
            return field
    for field, names in FIELDS.items():
        # «Teléfono celular del cliente» → teléfono; se exige que el encabezado empiece por un nombre conocido.
        if any(key.startswith(name + ' ') for name in names if len(name) > 3):
            return field
    return None


def detect(rows):
    """Localiza la fila de encabezados y asigna cada campo a una columna."""
    best = (0, 0, {})
    for index, row in enumerate(rows[:25]):
        mapping = {}
        for column, header in enumerate(row):
            field = match_field(header)
            if field and field not in mapping:
                mapping[field] = column
        score = len(mapping) + (2 if 'name' in mapping else 0) + (2 if 'identification' in mapping else 0)
        if score > best[0]:
            best = (score, index, mapping)
    score, index, mapping = best
    if 'name' not in mapping and 'surname' not in mapping:
        raise ImportError_('No se encontró una columna de nombre o razón social. Revisa los encabezados del archivo.')
    headers = [header or 'Columna ' + str(column + 1) for column, header in enumerate(rows[index])]
    return index, headers, mapping


def normalize_identification(value):
    text = re.sub(r'[\s.\-]', '', value)
    notes = []
    if text.isdigit():
        # Excel elimina el cero inicial de cédulas y RUC guardados como número.
        if len(text) in (9, 12) and not document_error('0' + text):
            text = '0' + text
            notes.append('Se restituyó el cero inicial de la identificación.')
        if len(text) in (10, 13):
            error = document_error(text)
            return text, 'cedula' if len(text) == 10 else 'ruc', notes, error
        return text, 'pasaporte', notes + ['Identificación numérica que no es cédula ni RUC ecuatoriano; se conserva como documento extranjero.'], ''
    if re.fullmatch(r'[A-Za-z0-9]{3,30}', text):
        return text.upper(), 'pasaporte', notes + ['Identificación con letras; se conserva como documento extranjero.'], ''
    return text, '', notes, 'La identificación tiene un formato no reconocido.'


def normalize_phone(value):
    digits = re.sub(r'[\s().\-]', '', value)
    if digits.isdigit():
        if len(digits) == 9 and digits[0] == '9':
            digits = '0' + digits
        elif len(digits) == 8 and digits[0] in '234567':
            digits = '0' + digits
        elif len(digits) == 12 and digits.startswith('593'):
            digits = '+' + digits
    return digits


def split_phones(*values):
    found = []
    for value in values:
        for part in re.split(r'[/;,|]|\s+-\s+|\s{2,}|\by\b', value or ''):
            part = part.strip()
            if part and part not in found:
                found.append(part)
    return found


def locate(record):
    """Completa los códigos territoriales solo cuando el nombre coincide de forma inequívoca con el catálogo INEC."""
    norm = geography.normalize
    province = next((row for row in geography.PROVINCES.values() if norm(row['name']) == norm(record['province'])), None) if record['province'] else None
    cantons = [row for row in geography.CANTONS.values() if not province or row['province_code'] == province['code']]
    wanted = record['canton'] or record['city']
    matches = [row for row in cantons if norm(row['name']) == norm(wanted)] if wanted else []
    canton = matches[0] if len(matches) == 1 else None
    if canton and not province:
        province = geography.PROVINCES[canton['province_code']]
    if province:
        record['province'], record['province_code'] = province['name'], province['code']
    if canton:
        record['canton'], record['canton_code'] = canton['name'], canton['code']
        if not record['city']:
            record['city'] = canton['name']
        if record['parish']:
            parishes = [row for row in geography.PARISHES.values() if row['canton_code'] == canton['code'] and norm(row['name']) == norm(record['parish'])]
            if len(parishes) == 1:
                record['parish'], record['parish_code'] = parishes[0]['name'], parishes[0]['code']
    if record['province_code'] and record['canton_code'] and record['parish_code']:
        record['geo_version'] = geography.METADATA['version']


def build(row, mapping):
    """Convierte una fila del archivo en una ficha normalizada con sus advertencias."""
    get = lambda field: row[mapping[field]].strip() if field in mapping and mapping[field] < len(row) else ''
    record = {key: '' for key in CLIENT_COLUMNS}
    record.update(client_type='natural', country='Ecuador')
    warnings, error = [], ''
    name = ' '.join(part for part in (get('surname'), get('name')) if part) if 'surname' in mapping else get('name')
    record['name'] = re.sub(r'\s+', ' ', name)[:150]
    record['trade_name'] = get('trade_name')[:150]
    if not record['name'] and record['trade_name']:
        record['name'] = record['trade_name']
        warnings.append('Sin razón social: se usa el nombre comercial como nombre.')
    if not record['name']:
        error = 'La fila no tiene nombre ni razón social.'
    raw_id = get('identification')
    if raw_id:
        value, kind, notes, id_error = normalize_identification(raw_id)
        warnings += notes
        record['identification'], record['document_type'] = value[:30], kind or ('cedula' if len(value) == 10 else 'ruc' if len(value) == 13 else 'pasaporte')
        if id_error:
            warnings.append('Identificación por revisar: ' + id_error)
        if record['document_type'] == 'ruc' and len(value) == 13 and value[2] in '69':
            record['client_type'] = 'empresa'
    else:
        warnings.append('Sin identificación.')
    phones = [normalize_phone(part) for part in split_phones(get('phone'), get('phone_secondary'))]
    if phones:
        record['phone'] = phones[0][:30]
        record['phone_secondary'] = ' / '.join(phones[1:])[:30]
        if not valid_ecuador_phone(record['phone']):
            warnings.append('El teléfono principal no tiene un formato ecuatoriano reconocido.')
    else:
        warnings.append('Sin teléfono.')
    email = get('email').replace(' ', '').lower()
    if email:
        first = re.split(r'[;,/]', email)[0]
        if re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', first) and len(first) <= 254:
            record['email'] = first
        else:
            warnings.append('Correo con formato inválido; no se importa: ' + email[:60])
    record['address'] = get('address')[:500]
    record['main_street'] = record['address'][:250]
    record['location_reference'] = get('location_reference')[:500]
    record['notes'] = get('notes')[:2000]
    for key, limit in (('province', 80), ('canton', 100), ('parish', 150), ('city', 100)):
        record[key] = get(key)[:limit]
    locate(record)
    complete = all(record[key] for key in ('identification', 'phone', 'province_code', 'canton_code', 'parish_code', 'city', 'main_street')) and not any('por revisar' in note or 'reconocido' in note for note in warnings)
    return record, warnings, error, 0 if complete else 1


def analyze(c, raw, filename=''):
    """Analiza el archivo contra la base sin escribir nada."""
    rows = read_rows(raw, filename)
    header_index, headers, mapping = detect(rows)
    existing = {row['identification']: dict(row) for row in c.execute("SELECT id,name,identification,phone,email,trade_name,address FROM clients WHERE identification!=''")}
    by_name = {}
    for row in c.execute("SELECT id,name,phone FROM clients WHERE identification=''"):
        by_name.setdefault(plain(row['name']), dict(row))
    seen, seen_names, items = {}, {}, []
    for offset, row in enumerate(rows[header_index + 1:]):
        number = header_index + offset + 2
        row = row + [''] * (len(headers) - len(row))
        original = {headers[index]: value for index, value in enumerate(row[:len(headers)]) if value}
        record, warnings, error, review = build(row, mapping)
        item = {'row': number, 'record': record, 'warnings': warnings, 'original': original, 'needs_review': review, 'status': 'new', 'detail': '', 'existing': None}
        identity = record['identification']
        if error:
            item.update(status='error', detail=error)
        elif identity and re.fullmatch(r'9{10}|9{13}', identity):
            item.update(status='skipped', detail='Consumidor final genérico; no es una ficha de cliente.')
        elif identity and identity in existing:
            item.update(status='duplicate', detail='Ya existe un cliente con esta identificación.', existing=existing[identity])
        elif identity and identity in seen:
            item.update(status='repeated', detail='Identificación repetida en el archivo; se conserva la fila ' + str(seen[identity]) + '.')
        elif not identity and plain(record['name']) in by_name:
            item.update(status='duplicate', detail='Posible duplicado: ya existe un cliente sin identificación con el mismo nombre.', existing=by_name[plain(record['name'])])
        elif not identity and (plain(record['name']), record['phone']) in seen_names:
            item.update(status='repeated', detail='Mismo nombre y teléfono que la fila ' + str(seen_names[(plain(record['name']), record['phone'])]) + '.')
        if item['status'] == 'new':
            if identity:
                seen[identity] = number
            else:
                seen_names[(plain(record['name']), record['phone'])] = number
        items.append(item)
    counts = {status: sum(1 for item in items if item['status'] == status) for status in ('new', 'duplicate', 'repeated', 'skipped', 'error')}
    counts.update(total=len(items), needs_review=sum(1 for item in items if item['status'] == 'new' and item['needs_review']), with_warnings=sum(1 for item in items if item['status'] == 'new' and item['warnings']))
    used = set(mapping.values())
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'filename': filename[:200], 'header_row': header_index + 1, 'counts': counts,
            'mapping': [{'field': LABELS[field], 'column': headers[column]} for field, column in mapping.items()],
            'unmapped': [header for index, header in enumerate(headers) if index not in used and not header.startswith('Columna ')],
            'items': items}


def summary(analysis, limit=40):
    """Vista previa acotada para mostrar antes de confirmar."""
    def view(item):
        record = item['record']
        return {'row': item['row'], 'name': record['name'], 'identification': record['identification'], 'document_type': record['document_type'], 'phone': record['phone'], 'email': record['email'], 'city': record['city'] or record['canton'],
                'warnings': item['warnings'], 'detail': item['detail'], 'needs_review': item['needs_review'], 'existing': item['existing']}
    groups = {status: [view(item) for item in analysis['items'] if item['status'] == status] for status in ('new', 'duplicate', 'repeated', 'skipped', 'error')}
    return {**{key: analysis[key] for key in ('sha256', 'filename', 'header_row', 'counts', 'mapping', 'unmapped')},
            'new': groups['new'][:limit], 'duplicates': groups['duplicate'][:500], 'repeated': groups['repeated'][:200], 'skipped': groups['skipped'][:200], 'errors': groups['error'][:200]}


def commit(c, raw, filename, expected_sha, merge_rows, actor_id, now, backup):
    """Importa tras crear la copia de seguridad. `merge_rows`: filas duplicadas autorizadas a completar campos vacíos."""
    analysis = analyze(c, raw, filename)
    if analysis['sha256'] != expected_sha:
        raise ImportError_('El archivo no coincide con la vista previa. Genera la vista previa de nuevo.')
    backup_name = backup()
    counts = analysis['counts']
    batch = c.execute('INSERT INTO client_import_batches(filename,file_sha256,actor_id,created_at,total,imported,merged,duplicates,skipped,errors) VALUES (?,?,?,?,?,0,0,0,0,0)', (analysis['filename'], analysis['sha256'], actor_id, now, counts['total'])).lastrowid
    c.execute('UPDATE client_import_batches SET backup_name=? WHERE id=?', (backup_name, batch))
    done = {'imported': 0, 'merged': 0, 'duplicates': 0, 'skipped': 0, 'errors': 0}
    merge_rows = {int(value) for value in merge_rows}
    for item in analysis['items']:
        record, client_id, outcome, detail = item['record'], None, item['status'], item['detail']
        if item['status'] == 'new':
            key = record['document_type'] + ':' + record['identification'] if record['identification'] else None
            client_id = c.execute('INSERT INTO clients(' + ','.join(CLIENT_COLUMNS) + ',identity_key,needs_review,import_batch_id,created_at) VALUES (' + ','.join('?' for _ in range(len(CLIENT_COLUMNS) + 4)) + ')',
                                  (*(record[column] for column in CLIENT_COLUMNS), key, item['needs_review'], batch, now)).lastrowid
            outcome, detail = 'imported', '; '.join(item['warnings'])
            done['imported'] += 1
        elif item['status'] == 'duplicate' and item['row'] in merge_rows:
            client_id = item['existing']['id']
            current = c.execute('SELECT * FROM clients WHERE id=?', (client_id,)).fetchone()
            filled = [column for column in FILLABLE if record[column] and not (current[column] or '').strip()]
            if filled:
                c.execute('UPDATE clients SET ' + ','.join(column + '=?' for column in filled) + ' WHERE id=?', (*(record[column] for column in filled), client_id))
            outcome, detail = 'merged', 'Campos completados: ' + (', '.join(filled) if filled else 'ninguno; la ficha ya tenía esos datos') + '.'
            done['merged'] += 1
        elif item['status'] == 'duplicate':
            client_id = item['existing']['id']
            done['duplicates'] += 1
        elif item['status'] == 'error':
            done['errors'] += 1
        else:
            done['skipped'] += 1
        c.execute('INSERT INTO client_import_rows(batch_id,row_number,client_id,outcome,detail,original) VALUES (?,?,?,?,?,?)', (batch, item['row'], client_id, outcome, detail, json.dumps(item['original'], ensure_ascii=False)))
    c.execute('UPDATE client_import_batches SET imported=?,merged=?,duplicates=?,skipped=?,errors=? WHERE id=?', (done['imported'], done['merged'], done['duplicates'], done['skipped'], done['errors'], batch))
    return {'batch': batch, 'total': counts['total'], 'backup': backup_name, **done}


def report_csv(c, batch):
    labels = {'imported': 'Importado', 'merged': 'Ficha existente completada', 'duplicate': 'Duplicado omitido', 'repeated': 'Repetido en el archivo', 'skipped': 'Omitido', 'error': 'Con error'}
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';', lineterminator='\r\n')
    writer.writerow(['Fila', 'Resultado', 'Cliente', 'Identificación', 'Detalle'])
    for row in c.execute('SELECT r.row_number,r.outcome,r.detail,cl.name,cl.identification FROM client_import_rows r LEFT JOIN clients cl ON cl.id=r.client_id WHERE r.batch_id=? ORDER BY r.row_number', (batch,)):
        writer.writerow([row['row_number'], labels.get(row['outcome'], row['outcome']), safe_cell(row['name'] or ''), safe_cell(row['identification'] or ''), safe_cell(row['detail'])])
    return '﻿' + out.getvalue()


def safe_cell(value):
    """Evita que una hoja de cálculo interprete el texto exportado como fórmula."""
    text = str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


def export_csv(c):
    columns = [('identification', 'Identificación'), ('document_type', 'Tipo de identificación'), ('name', 'Nombre o razón social'), ('trade_name', 'Nombre comercial'), ('client_type', 'Tipo de cliente'), ('phone', 'Teléfono'), ('phone_secondary', 'Teléfono secundario'), ('email', 'Correo electrónico'),
               ('province', 'Provincia'), ('canton', 'Cantón'), ('parish', 'Parroquia'), ('city', 'Ciudad'), ('address', 'Dirección'), ('location_reference', 'Referencia'), ('notes', 'Observaciones')]
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';', lineterminator='\r\n')
    writer.writerow([label for _, label in columns])
    for row in c.execute('SELECT * FROM clients ORDER BY name COLLATE NOCASE'):
        writer.writerow([safe_cell(row[key] or '') for key, _ in columns])
    return '﻿' + out.getvalue()


def main(argv=None):
    """Vista previa e importación desde la terminal: python client_import.py preview|import archivo [--confirmar]"""
    import argparse
    import app
    parser = argparse.ArgumentParser(description='Importación de clientes')
    parser.add_argument('command', choices=['preview', 'import'])
    parser.add_argument('file')
    parser.add_argument('--confirmar', action='store_true')
    parser.add_argument('--completar', default='', help='Filas duplicadas (separadas por comas) cuya ficha existente puede completarse.')
    args = parser.parse_args(argv)
    app.load_env()
    app.migrate()
    raw = Path(args.file).read_bytes()
    try:
        with app.connect() as c:
            analysis = analyze(c, raw, Path(args.file).name)
            view = summary(analysis, 15)
            counts = view['counts']
            print('Archivo:', view['filename'], '· encabezados en la fila', view['header_row'])
            print('Columnas reconocidas:', '; '.join(item['column'] + ' → ' + item['field'] for item in view['mapping']))
            print('Columnas conservadas solo como valor original:', ', '.join(view['unmapped']) or 'ninguna')
            print(f"Filas: {counts['total']} · nuevas: {counts['new']} (por completar: {counts['needs_review']}) · duplicadas: {counts['duplicate']} · repetidas en el archivo: {counts['repeated']} · omitidas: {counts['skipped']} · con error: {counts['error']}")
            for title, key in (('Duplicados', 'duplicates'), ('Repetidos', 'repeated'), ('Omitidos', 'skipped'), ('Errores', 'errors')):
                for item in view[key][:20]:
                    print(f"  [{title}] fila {item['row']}: {item['name'] or '(sin nombre)'} · {item['identification']} · {item['detail']}")
            if args.command == 'preview' or not args.confirmar:
                print('Vista previa: no se modificó la base. Para importar: import <archivo> --confirmar')
                return 0
            c.execute('BEGIN IMMEDIATE')
            result = commit(c, raw, Path(args.file).name, analysis['sha256'], [value for value in args.completar.split(',') if value.strip().isdigit()], None, app.reception_now().isoformat(timespec='seconds'), app.make_backup)
            print(f"Importación {result['batch']}: {result['imported']} importados, {result['merged']} fichas completadas, {result['duplicates']} duplicados omitidos, {result['skipped']} omitidos, {result['errors']} con error. Copia de seguridad: {result['backup']}")
    except ImportError_ as error:
        raise SystemExit(str(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
