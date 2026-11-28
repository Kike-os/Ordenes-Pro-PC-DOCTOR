"""Order-scoped, verified customer view of equipment and battery data."""
import html
import json

import battery_diagnostics as diagnostics
import order_battery
from reception import DEVICE_TYPES

LABELS = {
    'device': 'Mostrar ficha técnica', 'photo': 'Mostrar fotografía autorizada',
    'hardware': 'Mostrar características de hardware', 'health': 'Mostrar salud de batería',
    'wear': 'Mostrar desgaste', 'date': 'Mostrar fecha de evaluación',
    'pending': 'Mostrar diagnóstico pendiente', 'cycles': 'Mostrar ciclos',
    'capacity': 'Mostrar capacidades', 'physical': 'Mostrar diagnóstico físico',
    'electrical': 'Mostrar diagnóstico eléctrico', 'replacement': 'Mostrar reemplazos',
    'comparison': 'Mostrar comparación antes y después', 'warranty': 'Mostrar garantía',
    'recommendation': 'Mostrar recomendaciones técnicas', 'advisor': 'Mostrar explicaciones de ADI',
    'print': 'Incluir ficha técnica en seguimiento A4',
}
DEFAULTS = {'cdi_' + key: key in ('health', 'wear', 'date', 'cycles', 'capacity', 'replacement',
                                  'comparison', 'warranty', 'advisor') for key in LABELS}
HARDWARE = {'processor': 'Procesador', 'memory': 'Memoria RAM', 'storage': 'Almacenamiento'}
CONDITIONS = {'wear': 'Desgaste natural', 'undetected': 'Batería no detectada', 'not_charging': 'Batería no carga',
              'drain': 'Descarga acelerada', 'absent': 'Batería ausente'}
HAZARDS = {'inflamacion': 'Batería inflamada', 'corto_sospechado': 'Cortocircuito sospechado',
           'corto_confirmado': 'Cortocircuito confirmado', 'sobrecalentamiento': 'Sobrecalentamiento peligroso',
           'fuga': 'Fuga de electrolito', 'dano_fisico': 'Daño físico', 'dano_termico': 'Daño térmico',
           'proteccion': 'Falla del circuito de protección'}
FINDINGS = {'bateria': 'Falla interna de batería', 'bms': 'Falla del BMS', 'smbus': 'Comunicación SMBus',
            'proteccion': 'Protección electrónica activa', 'conector': 'Falla del conector',
            'carga_motherboard': 'Circuito de carga de la placa principal', 'alimentacion': 'Alimentación primaria',
            'adaptador': 'Adaptador incompatible o defectuoso', 'consumo': 'Consumo anormal',
            'corto_interno': 'Cortocircuito interno', 'corto_externo': 'Cortocircuito externo'}
FINDING_STATUS = {'confirmado': 'Confirmado', 'sospechado': 'Sospechado', 'descartado': 'Descartado',
                  'pendiente': 'Pendiente de comprobación'}
REPLACEMENT = {'new': 'Batería nueva instalada', 'used': 'Batería usada instalada',
               'refurbished': 'Batería reacondicionada instalada'}
ASSETS = ('<link rel="stylesheet" href="/static/battery-widget.css">'
          '<link rel="stylesheet" href="/static/customer-device.css">'
          '<script defer src="/static/battery-widget.js"></script>'
          '<script defer src="/static/customer-device.js"></script>')


def order_settings(c, oid):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (f'customer_device:{oid}',)).fetchone()
    return json.loads(row['value']) if row else {}


def photos(c, oid):
    import order_evidence
    return [f for f in order_evidence.public_files(c, oid) if f['mime'].startswith('image/') and f['preview']]


def save(c, oid, data):
    payload = {key: diagnostics.clean(data.get(key, ''), 120) for key in HARDWARE}
    for key in ('device_approved', 'hardware_approved'):
        value = data.get(key, False)
        if not isinstance(value, bool):
            raise ValueError('Revisa los permisos de la ficha.')
        payload[key] = value
    photo = data.get('photo', '')
    if photo and (not isinstance(photo, str) or photo not in {str(x['id']) for x in photos(c, oid)}):
        raise ValueError('Selecciona una fotografía autorizada de esta orden.')
    payload['photo'] = photo
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
              (f'customer_device:{oid}', json.dumps(payload, ensure_ascii=False)))
    return payload


def _masked(serial):
    if not serial:
        return ''
    return '••••' + (serial[-4:] if len(serial) > 4 else '')


def view(c, oid, token, cfg):
    """Only call after verifying the active identity session for this order."""
    row = c.execute("SELECT COALESCE(NULLIF(d.kind,''),d.category) kind,d.brand,d.model,d.code,d.serial,o.received_at "
                    'FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?', (oid,)).fetchone()
    if not row:
        return {}
    local = order_settings(c, oid)
    device = []
    photo = ''
    if cfg['cdi_device'] and local.get('device_approved'):
        device = [(k, v) for k, v in [('Tipo', DEVICE_TYPES.get(row['kind'], '')), ('Marca', row['brand']),
                  ('Modelo', row['model']), ('Código interno', row['code']), ('Serie', _masked(row['serial'])),
                  ('Recepción', (row['received_at'] or '')[:10])] if v]
        if cfg['cdi_hardware'] and local.get('hardware_approved'):
            device.extend((label, local[key]) for key, label in HARDWARE.items() if local.get(key))
        if cfg['cdi_photo'] and local.get('photo'):
            archived = next((f for f in photos(c, oid) if str(f['id']) == local['photo']), None)
            if archived:
                photo = f"/s/{token}/files/{archived['id']}" + ('/thumb' if archived['preview'] == 'thumb' else '?part=0')
    battery = {}
    if row['kind'] in order_battery.TYPES:
        record = order_battery.current_assessment(c, oid)
        if record:
            battery = battery_view(record, cfg)
    return {'device': device, 'photo': photo, 'kind': row['kind'], 'battery': battery}


def battery_view(record, cfg):
    advanced = record.get('advanced', {})
    share = set(advanced.get('share', []))
    percent = record['percent']
    health = 'health' in share and cfg['cdi_health']
    wear = 'health' in share and cfg['cdi_wear']
    condition = advanced.get('condition', '')
    readings = advanced.get('readings', {})
    rows = []
    evaluation = ''
    if condition == 'absent' and ('physical' in share or health or wear):
        evaluation = CONDITIONS[condition]
        percent = None
    elif (health or wear or cfg['cdi_pending']) and record['status'] != 'evaluada':
        evaluation = ('Medición suspendida por seguridad' if advanced.get('hazards') or
                      any(r.get('status') == 'seguridad' for r in readings.values()) else
                      'Pendiente de diagnóstico' if record['status'] == 'pendiente' else 'No se pudo evaluar')
    if percent is not None and (health or wear):
        evaluation = 'Evaluada'
    if percent is not None and wear and not health:
        rows.append(('Desgaste', f'{round(100-percent, 2):g} %'))
    if condition and condition != 'absent' and cfg['cdi_physical'] and 'physical' in share:
        rows.append(('Diagnóstico físico', CONDITIONS[condition]))
    if cfg['cdi_electrical'] and 'electrical' in share:
        rows.extend((FINDINGS[key], FINDING_STATUS[value['status']]) for key, value in advanced.get('findings', {}).items())
        for key in ('battery_nominal', 'battery_measured', 'charger_nominal', 'charger_measured', 'current', 'temperature'):
            if key in share and readings.get(key, {}).get('value'):
                reading = readings[key]
                rows.append((order_battery.PUBLIC_MEASUREMENTS[key], f"{reading['value']} {reading['unit']}"))
    for key, setting in (('cycles', 'cycles'), ('design', 'capacity'), ('full', 'capacity')):
        reading = readings.get(key, {})
        if key in share and cfg['cdi_' + setting] and reading.get('value'):
            rows.append((order_battery.PUBLIC_MEASUREMENTS[key], (reading['value'] + ' ' + reading['unit']).strip()))
    has_measurement = bool(rows or percent is not None and (health or wear))
    if cfg['cdi_date'] and has_measurement:
        when = advanced.get('measured_on') or (record['created_at'] or '')[:10]
        if when:
            rows.append(('Fecha de medición', when))
    if 'measurement_source' in share and cfg['cdi_capacity'] and advanced.get('source'):
        rows.append(('Fuente de medición', advanced['source']))
    if advanced.get('method') == 'capacity' and health and percent is not None:
        rows.append(('Método', 'Salud estimada por capacidad'))
    installation = []
    if cfg['cdi_replacement'] and 'replacement' in share and advanced.get('installation'):
        installed = advanced['installation']
        label = REPLACEMENT.get(installed.get('kind'), 'Batería instalada')
        installation.append(('Reemplazo', 'Batería instalada — Pendiente de evaluación' if percent is None else label))
        if percent is None and label != 'Batería instalada':
            installation.append(('Tipo de repuesto', label.removesuffix(' instalada')))
        installation.append(('Fecha de instalación', installed['date']))
        if cfg['cdi_warranty'] and installed.get('warranty'):
            installation.append(('Garantía', installed['warranty']))
        if cfg['cdi_comparison'] and installed.get('before_bp') is not None:
            before = installed['before_bp'] / 100
            installation.append(('Antes', f'Salud {before:g} % · Desgaste {round(100-before, 2):g} %'))
            if percent is not None:
                installation.extend((('Después', f'Salud {percent:g} % · Desgaste {round(100-percent, 2):g} %'),
                                     ('Variación', f'{round(percent-before, 2):+g} puntos porcentuales')))
    advisory = ''
    if cfg['cdi_advisor'] and 'explanation' in share:
        from adi_order import battery_explanation
        advisory = (battery_explanation(record)['customer'] if health or advanced.get('hazards') else
                    'La salud estima la capacidad que conserva la batería. La carga actual se mide por separado.')
    recommendation = ''
    if cfg['cdi_recommendation'] and 'recommendation' in share and not advanced.get('hazards'):
        recommendation = advanced.get('customer_recommendation', '')
    auxiliary = []
    for pack in advanced.get('auxiliary', []):
        if not pack['approved']:
            continue
        points = pack.get('health_bp')
        child_share = ['health', 'cycles', 'design', 'full']
        child = battery_view({'status': 'pendiente' if points is None else 'evaluada',
                              'percent': None if points is None else points / 100, 'created_at': '',
                              'advanced': {'method': 'capacity', 'share': child_share,
                                           'measured_on': pack['measured_on'], 'readings': pack['readings']}}, cfg)
        if child:
            child['label'] = 'Batería adicional ' + str(len(auxiliary)+1)
            auxiliary.append(child)
    visible = bool(auxiliary or rows or installation or advisory or recommendation or evaluation or (health and percent is not None))
    hazards = [HAZARDS[key] for key in advanced.get('hazards', [])]
    if not visible and not ('safety' in share and hazards):
        return {}
    return {'percent': percent if health else None, 'wear': wear, 'evaluation': evaluation,
            'rows': rows, 'installation': installation, 'advisor': advisory, 'recommendation': recommendation,
            'hazards': hazards, 'auxiliary': auxiliary}


def _list(rows):
    e = html.escape
    return '<dl class="cdi-facts">' + ''.join(f'<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>' for k, v in rows) + '</dl>' if rows else ''


def render(info, *, printing=False):
    e = html.escape
    device, battery = info.get('device', []), info.get('battery', {})
    if not (device or battery):
        return ''
    css = 'cdi-print' if printing else 'cdi-screen'
    panels = []
    if device:
        photo = info.get('photo')
        icons = {'impresora': 'M6 8V3h12v5 M6 17H3V8h18v9h-3 M6 14h12v7H6z M17 11h1',
                 'consola': 'M7 8h10c3 0 5 9 2 9l-4-3H9l-4 3c-3 0-1-9 2-9z M7 12h4m-2-2v4 M16 11h1 M18 13h1'}
        icon_path = ('M4 4h16v12H4z M2 20h20' if info['kind'] in order_battery.TYPES else
                     icons.get(info['kind'], 'M3 4h18v13H3z M8 21h8m-4-4v4'))
        image = (f'<img class="cdi-photo" src="{e(photo)}" alt="Fotografía autorizada del equipo" width="64" height="64" loading="lazy">'
                 if photo and not printing else
                 f'<svg class="cdi-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="{icon_path}"/></svg>')
        panels.append('<section class="cdi-panel"><h2>Ficha técnica del equipo</h2><div class="cdi-device">' + image + _list(device) + '</div></section>')
    if battery:
        content = _battery_content(battery, printing)
        for child in battery['auxiliary']:
            content += '<section class="cdi-pack"><h3>' + e(child['label']) + '</h3>' + _battery_content(child, printing) + '</section>'
        panels.append('<section class="cdi-panel"><h2>Diagnóstico de batería</h2>' + content + '</section>')
    return f'<div class="cdi-grid {css}">' + ''.join(panels) + '</div>'


def _battery_content(battery, printing):
    e = html.escape
    percent = battery['percent']
    content = ''
    if battery['hazards']:
        content += ('<p class="cdi-danger" role="alert"><strong>' + e(' · '.join(battery['hazards'])) +
                    '</strong> — No utilizar ni cargar el equipo hasta que el personal técnico resuelva esta condición.</p>')
    if percent is not None:
        content += (f'<div data-cdi-battery="{percent:g}" data-cdi-wear="{int(battery["wear"])}">'
                    f'<span>Salud {percent:g} %</span>' + (f'<span> · Desgaste {round(100-percent, 2):g} %</span>' if battery['wear'] else '') + '</div>')
    if battery['evaluation']:
        content += '<p>' + e(battery['evaluation']) + '</p>'
    rows = _list(battery['rows'])
    if rows:
        content += rows if printing else '<details><summary>Mediciones autorizadas</summary>' + rows + '</details>'
    if battery['installation']:
        content += '<h3>Reemplazo de batería</h3>' + _list(battery['installation'])
    if not printing:
        for key, label in (('recommendation', 'Recomendación técnica'), ('advisor', 'Explicación de ADI')):
            if battery[key]:
                content += f'<details><summary>{label}</summary><p>{e(battery[key])}</p></details>'
    return content
