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
    'history': 'Mostrar historial de batería', 'report': 'Mostrar informe técnico autorizado',
    'print': 'Incluir ficha técnica e informe en seguimiento A4',
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
                  'pendiente': 'Pendiente de comprobación', 'resuelto': 'Resuelto'}
REPLACEMENT = {'new': 'Batería nueva instalada', 'used': 'Batería usada instalada',
               'refurbished': 'Batería reacondicionada instalada'}
STYLE = '<link rel="stylesheet" href="/static/customer-device.css">'
ASSETS = (STYLE + '<link rel="stylesheet" href="/static/battery-widget.css">'
          '<script defer src="/static/battery-widget.js"></script>'
          '<script defer src="/static/customer-device.js"></script>')


def order_settings(c, oid):
    row = c.execute('SELECT value FROM system_state WHERE key=?', (f'customer_device:{oid}',)).fetchone()
    return json.loads(row['value']) if row else {}


def photos(c, oid):
    import order_evidence
    return [f for f in order_evidence.public_files(c, oid) if f['mime'].startswith('image/') and f['preview']]


def replacement_parts(c, oid):
    return c.execute('SELECT id,name,stage,situation FROM order_part_requests '
                     'WHERE order_id=? AND public_visible=1 ORDER BY id DESC', (oid,)).fetchall()


def public_quote(c, oid):
    return c.execute("SELECT id,code,status FROM quotes WHERE order_id=? AND deleted_at='' "
                     "AND status IN ('enviado','aprobado','parcial','rechazado') AND sent_at!='' "
                     "ORDER BY version DESC,id DESC LIMIT 1", (oid,)).fetchone()


def save(c, oid, data):
    prior = order_settings(c, oid)
    payload = {key: diagnostics.clean(data.get(key, prior.get(key, '')), 120) for key in HARDWARE}
    for key in ('device_approved', 'hardware_approved', 'report_approved', 'replacement_recommended', 'quote_approved'):
        value = data.get(key, prior.get(key, False))
        if not isinstance(value, bool):
            raise ValueError('Revisa los permisos de la ficha.')
        payload[key] = value
    photo = data.get('photo', prior.get('photo', ''))
    if 'photo' in data and photo and (not isinstance(photo, str) or photo not in {str(x['id']) for x in photos(c, oid)}):
        raise ValueError('Selecciona una fotografía autorizada de esta orden.')
    payload['photo'] = photo
    part = data.get('replacement_part', prior.get('replacement_part', ''))
    if 'replacement_part' in data and (not isinstance(part, str) or
            part and part not in {str(item['id']) for item in replacement_parts(c, oid)}):
        raise ValueError('Selecciona un repuesto visible de esta orden.')
    payload['replacement_part'] = part
    quote_id = data.get('replacement_quote', prior.get('replacement_quote', ''))
    if 'replacement_quote' in data:
        available = public_quote(c, oid) if quote_id else None
        if not isinstance(quote_id, str) or quote_id and (not available or str(available['id']) != quote_id):
            raise ValueError('El presupuesto no está disponible para esta orden.')
    payload['replacement_quote'] = quote_id
    c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
              (f'customer_device:{oid}', json.dumps(payload, ensure_ascii=False)))
    return payload


def _masked(serial):
    if not serial:
        return ''
    return '••••' + (serial[-4:] if len(serial) > 4 else '')


REPORT_SECTIONS = {
    'diagnostico': 'Diagnóstico y hallazgos comunicados',
    'reparacion': 'Reparaciones registradas',
    'repuesto': 'Componentes y repuestos',
    'pruebas': 'Comprobaciones posteriores',
    'finalizado': 'Resultados técnicos',
    'incidencia': 'Incidencias y garantía',
}


def technical_report(c, oid, cfg, local):
    if not cfg['cdi_report'] or not local.get('report_approved'):
        return []
    import order_followups
    updates = order_followups.public_updates(c, oid, limit=30, kinds=REPORT_SECTIONS)
    groups = {}
    for update in reversed(updates):
        groups.setdefault(REPORT_SECTIONS[update['kind']], []).append((update['at'], update['message']))
    return list(groups.items())


def replacement_progress(part, *, recommended=False, quote_pending=False):
    if part:
        if part['situation'] == 'cancelado':
            return 'Reemplazo cancelado'
        if part['stage'] in ('instalado', 'listo'):
            return 'Batería instalada — Pendiente de evaluación'
        if part['stage'] in ('recibido', 'instalacion'):
            return 'Pendiente de instalación'
        if part['stage'] == 'transito':
            return 'Repuesto en tránsito'
        return 'Repuesto solicitado'
    if recommended:
        return 'Pendiente de aprobación' if quote_pending else 'Reemplazo recomendado'
    return ''


def _battery_history(c, oid, cfg, record):
    if not cfg['cdi_history'] or 'history' not in record.get('advanced', {}).get('share', []):
        return []
    rows = order_battery.read(c, oid)['history']
    output = []
    for row in rows:
        if not {'health', 'history'} <= set(row.get('advanced', {}).get('share', [])) or row['percent'] is None:
            continue
        label = row['created_at'][:10] if cfg['cdi_date'] else 'Evaluación registrada'
        pieces = []
        if cfg['cdi_health']:
            pieces.append(f"Salud {row['percent']:g} %")
        if cfg['cdi_wear']:
            pieces.append(f"Desgaste {round(100-row['percent'], 2):g} %")
        if pieces:
            output.append((label, ' · '.join(pieces)))
    return output


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
    quote = public_quote(c, oid) if local.get('quote_approved') else None
    if row['kind'] in order_battery.TYPES:
        record = order_battery.current_assessment(c, oid)
        if record:
            if cfg['cdi_replacement'] and local.get('replacement_recommended'):
                part_id = local.get('replacement_part')
                part = next((p for p in replacement_parts(c, oid) if str(p['id']) == part_id), None) if part_id else None
                record['replacement_progress'] = replacement_progress(part, recommended=True,
                                                                      quote_pending=bool(quote and str(quote['id']) == local.get('replacement_quote')
                                                                                         and quote['status'] == 'enviado'))
            battery = battery_view(record, cfg)
            history = _battery_history(c, oid, cfg, record)
            if history:
                if not battery:
                    battery = battery_view({**record, 'history_visible': True}, cfg)
                battery['history'] = history
    report = technical_report(c, oid, cfg, local)
    if report and battery:
        warranty = dict(battery['installation']).get('Garantía')
        installed_on = dict(battery['installation']).get('Fecha de instalación')
        if warranty and installed_on:
            report.append(('Garantía registrada', [(installed_on, warranty)]))
    return {'device': device, 'photo': photo, 'kind': row['kind'], 'battery': battery,
            'report': report, 'base': f'/s/{token}/cuenta',
            'quote': {'status': quote['status']} if quote else None, 'statement': cfg['statement'],
            'print_allowed': cfg['cdi_print']}


def battery_view(record, cfg):
    advanced = record.get('advanced', {})
    share = set(advanced.get('share', []))
    percent = record['percent'] if record['status'] == 'evaluada' else None
    health = 'health' in share and cfg['cdi_health']
    wear = 'health' in share and cfg['cdi_wear']
    condition = advanced.get('condition', '')
    readings = advanced.get('readings', {})
    rows = []
    evaluation = ''
    physical = cfg['cdi_physical'] and 'physical' in share
    is_pending = record['status'] == 'pendiente'
    suspended = bool(advanced.get('hazards')) or any(r.get('status') == 'seguridad' for r in readings.values())
    if condition == 'absent':
        percent = None
        if physical or health or wear:
            evaluation = CONDITIONS[condition]
    elif record['status'] != 'evaluada':
        if suspended and (health or wear or cfg['cdi_pending'] or 'safety' in share):
            evaluation = 'Medición suspendida por seguridad'
        elif is_pending and cfg['cdi_pending']:
            evaluation = 'En evaluación' if advanced.get('in_review') else 'Pendiente de diagnóstico'
        elif not is_pending and (health or wear or cfg['cdi_pending']):
            evaluation = 'Medición no disponible'
    if percent is not None and (health or wear):
        evaluation = 'Evaluación completada'
    if percent is not None and wear and not health:
        rows.append(('Desgaste', f'{round(100-percent, 2):g} %'))
    if condition and condition != 'absent' and physical:
        if condition == 'undetected' and percent is None and not suspended:
            evaluation = CONDITIONS[condition]
        else:
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
    comparison = []
    if cfg['cdi_replacement'] and 'replacement' in share and advanced.get('installation'):
        installed = advanced['installation']
        label = REPLACEMENT.get(installed.get('kind'), 'Batería instalada')
        installation.append(('Reemplazo', 'Batería instalada — Pendiente de evaluación' if percent is None else label))
        if percent is None and label != 'Batería instalada':
            installation.append(('Tipo de repuesto', label.removesuffix(' instalada')))
        installation.append(('Fecha de instalación', installed['date']))
        if cfg['cdi_warranty'] and installed.get('warranty'):
            installation.append(('Garantía', installed['warranty']))
        if cfg['cdi_comparison'] and installed.get('before_bp') is not None and (health or wear):
            before = installed['before_bp'] / 100
            for heading, value in (('Batería anterior', before), ('Batería instalada', percent)):
                if value is not None:
                    comparison.append((heading, value))
            if percent is not None and health:
                installation.append(('Variación', f'{round(percent-before, 2):+g} puntos porcentuales'))
        if percent is not None:
            installation.append(('Estado', 'Reemplazo completado'))
    elif record.get('replacement_progress'):
        installation.append(('Estado', record['replacement_progress']))
    recommendation = ''
    if cfg['cdi_recommendation'] and 'recommendation' in share and not advanced.get('hazards'):
        recommendation = advanced.get('customer_recommendation', '')
    advisory = ''
    if cfg['cdi_advisor'] and 'explanation' in share:
        from adi_order import battery_explanation
        danger = bool(advanced.get('hazards'))
        projected = {'status': record['status'], 'percent': percent if health else None,
                     'advanced': {'hazards': danger}}
        advisory = battery_explanation(projected)['customer']
        if not danger:
            details = []
            if not health:
                advisory = ('La salud estima la capacidad que conserva la batería. La carga actual se mide por separado. '
                            'Se requiere una evaluación técnica para interpretar su efecto en la autonomía.')
            if cfg['cdi_electrical'] and 'electrical' in share:
                details.extend(FINDINGS[key] + ' (' + FINDING_STATUS[finding['status']].lower() + ')'
                               for key, finding in advanced.get('findings', {}).items()
                               if finding['status'] in ('confirmado', 'sospechado', 'resuelto'))
            if details:
                advisory += ' Hallazgos autorizados: ' + '; '.join(details) + '.'
            installed = dict(installation)
            if installed.get('Reemplazo'):
                advisory += ' ' + installed['Reemplazo'] + '.'
            if installed.get('Garantía'):
                advisory += ' Garantía registrada: ' + installed['Garantía'] + '.'
    auxiliary = []
    for index, pack in enumerate(advanced.get('auxiliary', []), 1):
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
            child['widget_key'] = 'aux-' + (pack.get('battery_key') or str(index))
            auxiliary.append(child)
    visible = bool(record.get('history_visible') or auxiliary or rows or installation or advisory or recommendation or evaluation or (health and percent is not None))
    hazards = [HAZARDS[key] for key in advanced.get('hazards', [])]
    if not visible and not ('safety' in share and hazards):
        return {}
    if hazards and 'safety' not in share:
        hazards = ['Advertencia crítica de batería']
    return {'percent': percent if health else None, 'wear': wear, 'evaluation': evaluation,
            'rows': rows, 'installation': installation, 'comparison': comparison, 'show_health': health, 'advisor': advisory, 'recommendation': recommendation,
            'hazards': hazards, 'auxiliary': auxiliary}


def _list(rows):
    e = html.escape
    return '<dl class="cdi-facts">' + ''.join(f'<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>' for k, v in rows) + '</dl>' if rows else ''


def render(info, *, printing=False):
    e = html.escape
    device, battery = info.get('device', []), info.get('battery', {})
    report = info.get('report', [])
    if not (device or battery or report or (not printing and info.get('quote'))):
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
        values = dict(device)
        model = ' '.join(values[k] for k in ('Marca', 'Modelo') if values.get(k))
        kind = values.get('Tipo', '')
        heading = '<h3>' + e(model) + '</h3>' if model else ''
        category = '<p class="cdi-device-kind">' + e(kind) + '</p>' if kind else ''
        specs = [(k, v) for k, v in device if k not in ('Tipo', 'Marca', 'Modelo')]
        details = (_list(specs) if printing else '<details><summary>Ver detalles</summary>' + _list(specs) + '</details>') if specs else ''
        markers = ''
        if not printing:
            markers = ' id="cdi-device"'
            if model or kind:
                markers += ' data-cdi-equipment'
            if values.get('Recepción'):
                markers += ' data-cdi-reception'
        panels.append('<section class="cdi-panel"' + markers +
                      '><h2>Ficha técnica del equipo</h2><div class="cdi-device">' +
                      image + '<div class="cdi-equipment-data">' + heading + category + details + '</div></div></section>')
    supplemental = ''
    if battery:
        content = _battery_content(battery, printing)
        for child in battery['auxiliary']:
            content += '<section class="cdi-pack"><h3>' + e(child['label']) + '</h3>' + _battery_content(child, printing) + '</section>'
        panels.append('<section class="cdi-panel"' + ('' if printing else ' id="cdi-diagnosis"') +
                      '><header class="cdi-panel-heading"><h2>Diagnóstico de batería</h2>' +
                      ('' if printing else '<span class="cdi-version">Battery Health Premium 6.5</span>') +
                      '</header>' + content + '</section>')
        supplemental = _replacement(battery, printing) if printing else _advisor(battery) + _replacement(battery, printing)
    report_html = report_section(report, info.get('base', ''), printing=printing) if report else ''
    action_bar = '' if printing else actions(info)
    grid = f'<div class="cdi-grid {css}">' + ''.join(panels) + '</div>' if panels else ''
    return action_bar + grid + supplemental + report_html


def _battery_content(battery, printing):
    e = html.escape
    percent = battery['percent']
    content = ''
    widget = _widget(percent, battery['wear'], battery.get('widget_key', 'primary'), bool(battery['hazards'])) if percent is not None else ''
    summary_labels = ('Fecha de medición', 'Ciclos de carga', 'Capacidad de diseño', 'Capacidad de carga completa')
    summary = [row for row in battery['rows'] if row[0] in summary_labels]
    details = [row for row in battery['rows'] if row[0] not in summary_labels]
    evaluation = '<p class="cdi-evaluation">' + e(battery['evaluation']) + '</p>' if battery['evaluation'] else ''
    if battery['hazards']:
        content += ('<p class="cdi-danger" role="alert"><strong>' + e(' · '.join(battery['hazards'])) +
                    '</strong> — No utilizar ni cargar el equipo hasta que el personal técnico resuelva esta condición.</p>')
    if widget or evaluation or summary:
        content += '<div class="cdi-battery-overview">' + widget + '<div>' + evaluation + _list(summary) + '</div></div>'
    rows = _list(details)
    if rows:
        content += rows if printing else '<details><summary>Mediciones autorizadas</summary>' + rows + '</details>'
    if not printing:
        if battery.get('history'):
            content += '<details><summary>Historial de batería</summary>' + _list(battery['history']) + '</details>'
        if battery['recommendation']:
            content += '<details><summary>Recomendación técnica</summary><p>' + e(battery['recommendation']) + '</p></details>'
    return content


def _replacement(battery, printing):
    e = html.escape
    content = ''
    if battery['installation']:
        content += '<section class="cdi-replacement '+('cdi-print' if printing else 'cdi-screen')+'"' + ('' if printing else ' id="cdi-replacement"') + (
            '><h3>Reemplazo de batería</h3>' + _list(battery['installation']))
        comparison = []
        for heading, value in battery['comparison']:
            if battery['show_health']:
                block = _widget(value, battery['wear'], 'installed' if heading == 'Batería instalada' else 'previous',
                                bool(battery['hazards']) and heading == 'Batería instalada')
            elif battery['wear']:
                block = _list([('Desgaste', f'{round(100-value, 2):g} %')])
            else:
                continue
            comparison.append('<div><h4>' + e(heading) + '</h4>' + block + '</div>')
        if comparison:
            content += '<div class="cdi-comparison">' + ''.join(comparison) + '</div>'
        content += '</section>'
    return content


def _advisor(battery):
    e = html.escape
    if not battery['advisor']:
        return ''
    brief = battery['advisor'].partition('. ')[0].rstrip('.') + '.'
    details = '<details><summary>Ver explicación completa</summary><p>' + e(battery['advisor']) + '</p></details>' if brief != battery['advisor'] else ''
    return '<section class="cdi-advisor cdi-screen"><h3>ADI Technical Intelligence</h3><p>' + e(brief) + '</p>' + details + '</section>'


def _widget(percent, wear, key, safety):
    return (f'<div data-cdi-battery="{percent:g}" data-cdi-wear="{int(wear)}" '
            f'data-cdi-battery-key="{key}" data-cdi-battery-safety="{int(safety)}">'
            f'<span>Salud {percent:g} %</span>' + (f'<span> · Desgaste {round(100-percent, 2):g} %</span>' if wear else '') + '</div>')


def actions(info):
    links = []
    base = info.get('base')
    if info.get('quote') and base and info['quote']['status'] != 'enviado':
        links.append(('Ver presupuesto', base + '/presupuesto.pdf'))
    if info.get('battery'):
        links.append(('Consultar diagnóstico', '#cdi-diagnosis'))
        items = dict(info['battery']['installation'])
        if items:
            links.append(('Consultar reemplazo', '#cdi-replacement'))
        if items.get('Garantía'):
            links.append(('Consultar garantía', '#cdi-replacement'))
    if info.get('report'):
        links.append(('Consultar informe técnico', '#cdi-report'))
    if not links:
        return ''
    return '<nav class="cdi-actions" aria-label="Acciones de la orden">' + ''.join(
        f'<a href="{html.escape(url)}">{html.escape(title)}</a>' for title, url in links) + '</nav>'


def report_section(report, base='', *, printing=False):
    e = html.escape
    rows = ''.join('<section><h3>' + e(label) + '</h3>' + ''.join(
        '<p><time>' + e(at.replace('T', ' ')[:16]) + '</time> · ' + e(message) + '</p>'
        for at, message in values) + '</section>' for label, values in report)
    if printing:
        return '<section class="cdi-report cdi-print"><h2>Informe técnico autorizado</h2>' + rows + '</section>'
    link = f'<a class="cdi-report-download" download href="{e(base)}/informe">Descargar informe</a>' if base else ''
    return '<details class="cdi-report cdi-screen" id="cdi-report"><summary>Informe técnico autorizado</summary>' + rows + link + '</details>'


def report_document(code, report):
    return ('<!doctype html><html lang="es"><meta charset="utf-8"><title>Informe técnico</title>'
            '<h1>PC-DOCTOR S.A. · ' + html.escape(code) + '</h1>' +
            report_section(report, printing=True) + '</html>')
