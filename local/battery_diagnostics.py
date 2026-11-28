"""Validation and inert Windows Battery Report extraction."""
import base64
import binascii
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from html.parser import HTMLParser
from pathlib import PurePath
import re

MAX_REPORT = 1_000_000
STATUSES = ('medido', 'sistema', 'no_disponible', 'no_aplica', 'pendiente', 'seguridad')
SOURCES = ('Windows Battery Report', 'BIOS/UEFI', 'Diagnóstico oficial del fabricante', 'HWiNFO',
           'AIDA64', 'BatteryInfoView', 'Multímetro', 'Instrumentación de laboratorio',
           'Etiqueta del fabricante', 'Otro método')
MEASUREMENTS = {
    'battery_nominal': ('V',), 'battery_measured': ('V',),
    'charger_nominal': ('V',), 'charger_measured': ('V',),
    'current': ('A', 'mA'), 'cycles': ('',), 'temperature': ('°C',),
    'design': ('Wh', 'mWh', 'Ah', 'mAh'), 'full': ('Wh', 'mWh', 'Ah', 'mAh'),
    'remaining': ('Wh', 'mWh', 'Ah', 'mAh'), 'charge': ('%',),
}
IDENTITY = ('technology', 'manufacturer', 'model', 'part', 'serial')
HAZARDS = ('inflamacion', 'corto_sospechado', 'corto_confirmado', 'sobrecalentamiento',
           'fuga', 'dano_fisico', 'dano_termico', 'proteccion')
FINDINGS = ('bateria', 'bms', 'smbus', 'proteccion', 'conector', 'carga_motherboard',
            'alimentacion', 'adaptador', 'consumo', 'corto_interno', 'corto_externo')
FINDING_STATES = ('sospechado', 'confirmado', 'descartado', 'pendiente', 'resuelto')
PHYSICAL = ('battery_measured', 'charger_measured', 'current', 'temperature')


def mapping(value):
    if not isinstance(value, dict):
        raise ValueError('La estructura del diagnóstico no es válida.')
    return value


def clean(value, limit=160):
    if not isinstance(value, str) or len(value) > limit or any(ord(ch) < 32 and ch not in '\r\n\t' for ch in value):
        raise ValueError('Revisa el texto y los límites del diagnóstico.')
    return value.strip()


def iso_date(value):
    value = clean(value, 10)
    if not value:
        return ''
    try:
        canonical = date.fromisoformat(value).isoformat()
    except ValueError:
        canonical = ''
    if canonical != value:
        raise ValueError('Ingresa una fecha de medición válida.')
    return value


def normalize(data, previous):
    data = mapping(data)
    method = data.get('method', 'manual')
    if method not in ('manual', 'capacity'):
        raise ValueError('Selecciona un método de evaluación.')
    identity = {k: clean(mapping(data.get('identity', {})).get(k, '')) for k in IDENTITY}
    source = clean(data.get('source', ''))
    if source and source not in SOURCES:
        raise ValueError('Selecciona una fuente de medición válida.')
    hazards = data.get('hazards', [])
    if not isinstance(hazards, list) or any(x not in HAZARDS for x in hazards):
        raise ValueError('Revisa los hallazgos de seguridad.')
    hazards = [key for key in HAZARDS if key in hazards]
    findings = {}
    for key, value in mapping(data.get('findings', {})).items():
        value = mapping(value)
        status = value.get('status')
        if key not in FINDINGS or status not in FINDING_STATES:
            raise ValueError('Revisa la clasificación de microelectrónica.')
        findings[key] = {'status': status, 'notes': clean(value.get('notes', ''), 600)}
    if any(findings.get(k, {}).get('status') in ('sospechado', 'confirmado') for k in ('corto_interno', 'corto_externo')):
        key = 'corto_confirmado' if any(findings.get(k, {}).get('status') == 'confirmado'
                                      for k in ('corto_interno', 'corto_externo')) else 'corto_sospechado'
        if key not in hazards:
            hazards.append(key)
    in_review = data.get('in_review', False)
    if not isinstance(in_review, bool):
        raise ValueError('Revisa el estado de la evaluación en curso.')
    condition = data.get('condition', '')
    if condition not in ('', 'wear', 'undetected', 'not_charging', 'drain', 'absent'):
        raise ValueError('Selecciona una condición de batería válida.')
    resolved = set(previous.get('hazards', [])) - set(hazards)
    if resolved and (data.get('resolve_safety') is not True or not clean(data.get('safety_notes', ''), 1000)):
        raise ValueError('Confirma la resolución técnica y registra las medidas para retirar la alerta.')
    readings = {}
    software = ('Windows Battery Report', 'BIOS/UEFI', 'HWiNFO', 'AIDA64', 'BatteryInfoView')
    for key, reading in mapping(data.get('readings', {})).items():
        reading = mapping(reading)
        status, unit = reading.get('status'), reading.get('unit', '')
        if key not in MEASUREMENTS or status not in STATUSES or unit not in MEASUREMENTS[key]:
            raise ValueError('Revisa el estado y la unidad de cada medición.')
        raw = clean(reading.get('value', ''), 20).replace(',', '.')
        if raw:
            if status not in ('medido', 'sistema') or not re.fullmatch(r'-?[0-9]{1,9}(?:\.[0-9]{1,6})?', raw):
                raise ValueError('Ingresa un valor decimal con un estado compatible.')
            number = Decimal(raw)
            if (number < 0 and key != 'temperature' or key == 'charge' and number > 100
                    or key == 'cycles' and number != number.to_integral_value()):
                raise ValueError('El valor está fuera del rango admitido.')
        elif status in ('medido', 'sistema'):
            raise ValueError('Una medición registrada requiere un valor.')
        provenance = clean(reading.get('source', ''))
        if provenance and provenance not in SOURCES:
            raise ValueError('La fuente individual de una medición no es válida.')
        if status == 'medido' and (provenance or source) in software:
            raise ValueError('Identifica los datos de software como reportados por el sistema.')
        normalized = {'status': status, 'unit': unit, 'value': raw}
        if provenance:
            normalized['source'] = provenance
        prior = previous.get('readings', {}).get(key, {})
        same_reading = all(normalized[k] == prior.get(k) for k in ('status', 'unit', 'value'))
        if (hazards or previous.get('hazards')) and key in PHYSICAL and status == 'medido' and not same_reading:
            raise ValueError('La condición peligrosa impide registrar una nueva medición física.')
        readings[key] = normalized
    instrument = clean(data.get('instrument', ''))
    measured_on = iso_date(data.get('measured_on', ''))
    if any(r['value'] for r in readings.values()) and (not source or not measured_on):
        raise ValueError('Registra la fuente y la fecha de las mediciones.')
    share = data.get('share', [])
    public_fields = (*MEASUREMENTS, 'health', 'safety', 'replacement', 'explanation', 'physical', 'electrical', 'recommendation', 'measurement_source', 'history')
    if not isinstance(share, list) or any(not isinstance(key, str) or key not in public_fields for key in share):
        raise ValueError('Revisa la información autorizada para el cliente.')
    auxiliary = data.get('auxiliary', [])
    if not isinstance(auxiliary, list) or len(auxiliary) > 8:
        raise ValueError('Revisa las baterías adicionales. Se admiten hasta ocho por equipo.')
    packs, serials = [], {identity['serial'].casefold()} - {''}
    for index, item in enumerate(auxiliary, 1):
        item = mapping(item)
        allowed = ('cycles', 'design', 'full')
        item_readings = mapping(item.get('readings', {}))
        if any(key not in allowed for key in item_readings):
            raise ValueError('La batería adicional admite ciclos y capacidades.')
        if not isinstance(item.get('approved', False), bool):
            raise ValueError('Revisa el permiso de la batería adicional.')
        label = clean(item.get('label', ''), 80) or f'Batería adicional {index}'
        raw = normalize({'identity': item.get('identity', {}), 'readings': item_readings,
                         'source': 'Windows Battery Report', 'measured_on': item.get('measured_on', '')}, {})
        serial = raw['identity']['serial'].casefold()
        if serial and serial in serials:
            raise ValueError('Una serie de batería no puede repetirse en la evaluación.')
        if serial:
            serials.add(serial)
        estimate = None
        try:
            points, review = capacity_health(raw['readings'])
            if not review:
                estimate = points
        except ValueError:
            pass  # Se conservan capacidades que todavía no permiten calcular una salud.
        packs.append({'label': label, 'identity': raw['identity'], 'readings': raw['readings'],
                      'measured_on': raw['measured_on'], 'approved': item.get('approved', False), 'health_bp': estimate})
    return {**({'in_review': True} if in_review else {}), 'method': method, 'auxiliary': packs, 'condition': condition, 'customer_recommendation': clean(data.get('customer_recommendation', ''), 500), 'identity': identity, 'source': source, 'instrument': instrument,
            'measured_on': measured_on, 'hazards': hazards, 'safety_notes': clean(data.get('safety_notes', ''), 1000),
            'findings': findings, 'readings': readings, 'share': sorted(set(share))}


def capacity_health(readings):
    design, full = (readings.get(k, {}) for k in ('design', 'full'))
    if not design.get('value') or not full.get('value'):
        raise ValueError('Registra ambas capacidades de la batería activa para calcular la salud.')
    nominal, measured = Decimal(design['value']), Decimal(full['value'])
    if nominal <= 0:
        raise ValueError('La capacidad de diseño debe ser mayor que cero.')
    design_unit, full_unit = design['unit'], full['unit']
    if design_unit.endswith('Wh') != full_unit.endswith('Wh'):
        voltage = readings.get('battery_nominal', {}).get('value')
        if not voltage or Decimal(voltage) <= 0:
            raise ValueError('Las unidades requieren un voltaje nominal de referencia de la misma batería.')
        voltage = Decimal(voltage)
    else:
        voltage = Decimal(1)
    def normalized(value, unit):
        return value * (1 if unit.startswith('m') else 1000) * (voltage if unit.endswith('Ah') else 1)
    ratio = normalized(measured, full_unit) / normalized(nominal, design_unit)
    return int((min(ratio, Decimal(1)) * 10000).quantize(Decimal(1), rounding=ROUND_HALF_UP)), ratio > 1


class ReportTables(HTMLParser):
    """Collect bounded text cells. Active elements are ignored and never rendered."""
    ignored = frozenset(('script', 'style', 'iframe', 'object', 'template', 'svg', 'noscript', 'head'))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.section = ''
        self.table = self.row = self.cell = self.heading = None
        self.blocked = []

    def handle_starttag(self, tag, attrs):
        if tag in self.ignored:
            self.blocked.append(tag)
        if self.blocked:
            return
        if tag in ('h1', 'h2', 'h3'):
            self.heading = []
        elif tag == 'table' and self.table is None:
            self.table = []
        elif tag == 'tr' and self.table is not None:
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if self.blocked:
            if tag == self.blocked[-1]:
                self.blocked.pop()
            return
        if tag in ('h1', 'h2', 'h3') and self.heading is not None:
            self.section = ' '.join(self.heading).strip().lower()
            self.heading = None
        elif tag in ('td', 'th') and self.cell is not None and self.row is not None:
            self.row.append(' '.join(' '.join(self.cell).split())[:240])
            self.cell = None
        elif tag == 'tr' and self.row is not None and self.table is not None:
            self.table.append(self.row[:17])
            self.row = self.cell = None
        elif tag == 'table' and self.table is not None:
            self.tables.append((self.section, self.table[:500]))
            self.table = None

    def handle_data(self, value):
        if self.blocked:
            return
        if self.cell is not None:
            self.cell.append(value[:240])
        if self.heading is not None:
            self.heading.append(value[:100])


REPORT_FIELDS = {
    'name': 'model', 'nombre': 'model', 'manufacturer': 'manufacturer', 'fabricante': 'manufacturer',
    'serial number': 'serial', 'número de serie': 'serial', 'chemistry': 'technology', 'composición química': 'technology',
    'design capacity': 'design', 'capacidad de diseño': 'design', 'full charge capacity': 'full',
    'capacidad de carga completa': 'full', 'cycle count': 'cycles', 'recuento de ciclos': 'cycles',
}


def _report_reading(text, key):
    match = re.fullmatch(r'([0-9][0-9 ,.]*)\s*(mWh|Wh|mAh|Ah)?', text)
    if not match:
        return None
    digits, unit = match.groups()
    digits = digits.strip().replace(' ', '')
    if unit in ('mWh', 'mAh') and re.fullmatch(r'\d{1,3}(?:[,.]\d{3})+', digits):
        digits = digits.replace(',', '').replace('.', '')
    else:
        digits = digits.replace(',', '.')
    if not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9]{1,6})?', digits):
        return None
    if key == 'cycles' and unit is None and digits.isdigit() or key != 'cycles' and unit in MEASUREMENTS[key]:
        return {'value': digits, 'unit': unit or '', 'status': 'sistema'}


def parse_report(data):
    data = mapping(data)
    name = clean(data.get('name', ''), 255).replace('\\', '/')
    name = PurePath(name).name
    if not name.lower().endswith(('.html', '.htm')) or data.get('type', '') not in ('', 'text/html'):
        raise ValueError('Selecciona un informe HTML generado por Windows.')
    payload = data.get('content', '')
    if not isinstance(payload, str) or len(payload) > ((MAX_REPORT + 2) // 3) * 4:
        raise ValueError('El informe supera el límite de 1 MB.')
    try:
        raw = base64.b64decode(payload, validate=True)
        if len(raw) > MAX_REPORT:
            raise ValueError('El informe supera el límite de 1 MB.')
        encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        document = raw.decode(encoding)
    except (UnicodeError, binascii.Error) as exc:
        raise ValueError('No se pudo leer el informe HTML.') from exc
    if '\x00' in document or not re.search(r'<html(?:\s|>)', document, re.I):
        raise ValueError('El archivo no tiene la estructura de un informe Windows.')
    parser = ReportTables()
    try:
        parser.feed(document)
        parser.close()
    except (AssertionError, ValueError) as exc:
        raise ValueError('No se pudo interpretar la estructura del informe.') from exc
    batteries, report_date, history = [], '', []
    for section, rows in parser.tables:
        if 'installed batteries' in section or 'baterías instaladas' in section:
            columns = max((len(row) for row in rows), default=0)
            for index in range(1, columns):
                battery = {'identity': {}, 'readings': {}}
                for row in rows:
                    key = REPORT_FIELDS.get(row[0].lower().rstrip(':')) if len(row) > index else None
                    if key in IDENTITY and row[index] not in ('', '-', '—'):
                        battery['identity'][key] = row[index][:160]
                    elif key in ('design', 'full', 'cycles'):
                        reading = _report_reading(row[index], key)
                        if reading:
                            battery['readings'][key] = reading
                if any(battery.values()):
                    batteries.append(battery)
        for row in rows:
            if len(row) > 1 and row[0].lower().rstrip(':') in ('report time', 'hora del informe'):
                try:
                    report_date = iso_date(row[1][:10])
                except ValueError:
                    pass
        if 'capacity history' in section or 'historial de capacidad' in section:
            for row in rows:
                if len(row) == 3 and re.fullmatch(r'\d{4}-\d\d-\d\d(?:\s+-\s+\d{4}-\d\d-\d\d)?', row[0]):
                    full, design = _report_reading(row[1], 'full'), _report_reading(row[2], 'design')
                    if full and design:
                        history.append({'period': row[0], 'full': full, 'design': design})
    if not batteries:
        raise ValueError('No se encontró una tabla de baterías instaladas en el informe.')
    return {'name': name, 'size': len(raw), 'date': report_date, 'batteries': batteries,
            'history': history if len(batteries) == 1 else []}
