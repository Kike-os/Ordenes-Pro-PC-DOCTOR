"""Horarios oficiales de PC-DOCTOR S.A. en un solo lugar.

Atención presencial, atención virtual y cierres extraordinarios se guardan aquí y los leen ADI, la página de citas y el panel.
La disponibilidad de las citas es otra cosa (franjas de la agenda y de cada técnico, en `appointments`): este módulo no la
cambia ni la presupone. Todas las horas son de America/Guayaquil."""
import json
from datetime import date, datetime, time, timedelta

from reception import ECUADOR_TZ

DAYS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
VIRTUAL = 'Atención virtual disponible las 24 horas, los 7 días de la semana, mediante ADI, nuestra asistente inteligente.'
CLOSED = 'En este momento la atención presencial está cerrada. ADI puede ayudarte ahora y un asesor te responderá en el siguiente horario de atención.'
# Horarios oficiales comunicados por administración el 12/10/2026.
DEFAULTS = {'hours': [{'weekday': day, 'start': '07:45', 'end': '20:30', 'enabled': True} for day in range(5)]
            + [{'weekday': 5, 'start': '09:00', 'end': '21:00', 'enabled': True}, {'weekday': 6, 'start': '10:00', 'end': '17:00', 'enabled': True}],
            'virtual_enabled': True, 'virtual_message': VIRTUAL, 'closed_message': CLOSED, 'closures': [],
            # Hora límite de cada día para *solicitar* una cita en línea. No es horario de atención ni implica técnicos disponibles a esa hora.
            'request_limits_enabled': True, 'request_limits': [{'weekday': day, 'until': '23:00'} for day in range(5)] + [{'weekday': 5, 'until': '22:30'}, {'weekday': 6, 'until': '19:30'}]}


def get(c):
    row = c.execute("SELECT value FROM system_state WHERE key='business_hours'").fetchone()
    data = json.loads(json.dumps(DEFAULTS))
    if row:
        try:
            saved = json.loads(row['value'])
            data.update({key: saved[key] for key in DEFAULTS if key in saved})
        except (ValueError, TypeError):
            pass
    return data


def validate(data):
    """Normaliza lo enviado por administración. Devuelve (valores, error)."""
    try:
        hours = []
        for item in data.get('hours', []):
            day = int(item['weekday'])
            start, end = time.fromisoformat(str(item['start'])), time.fromisoformat(str(item['end']))
            if day not in range(7) or start >= end:
                return None, 'Revisa los horarios: la apertura debe ser anterior al cierre.'
            hours.append({'weekday': day, 'start': start.strftime('%H:%M'), 'end': end.strftime('%H:%M'), 'enabled': bool(item.get('enabled'))})
        if sorted(item['weekday'] for item in hours) != list(range(7)):
            return None, 'Indica el horario de los siete días.'
        closures = []
        for item in data.get('closures', []):
            day = date.fromisoformat(str(item['date']))
            closures.append({'date': day.isoformat(), 'note': str(item.get('note', '')).strip()[:120]})
        if len(closures) > 60 or len({item['date'] for item in closures}) != len(closures):
            return None, 'Revisa los cierres extraordinarios: hay fechas repetidas o demasiadas.'
    except (KeyError, TypeError, ValueError):
        return None, 'Revisa los horarios y las fechas.'
    try:
        limits = [{'weekday': int(item['weekday']), 'until': time.fromisoformat(str(item['until'])).strftime('%H:%M')} for item in data.get('request_limits', DEFAULTS['request_limits'])]
        if sorted(item['weekday'] for item in limits) != list(range(7)):
            return None, 'Indica la hora límite de solicitud de los siete días.'
    except (KeyError, TypeError, ValueError):
        return None, 'Revisa las horas límite para solicitar citas.'
    virtual, closed = str(data.get('virtual_message', '')).strip()[:300], str(data.get('closed_message', '')).strip()[:300]
    if not virtual or not closed:
        return None, 'Escribe el mensaje de atención virtual y el de fuera de horario.'
    return {'hours': sorted(hours, key=lambda item: item['weekday']), 'virtual_enabled': bool(data.get('virtual_enabled', True)), 'virtual_message': virtual,
            'closed_message': closed, 'closures': sorted(closures, key=lambda item: item['date']),
            'request_limits_enabled': bool(data.get('request_limits_enabled', True)), 'request_limits': sorted(limits, key=lambda item: item['weekday'])}, ''


def save(c, values):
    c.execute("INSERT INTO system_state(key,value) VALUES ('business_hours',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(values, ensure_ascii=False),))


def _clock(value):
    """«07:45» → «7:45 a. m.»"""
    hour, minute = (int(part) for part in value.split(':'))
    return '%d:%02d %s' % (hour % 12 or 12, minute, 'a. m.' if hour < 12 else 'p. m.')


def text(config):
    """Horario presencial agrupando días consecutivos iguales: «lunes a viernes de 7:45 a. m. a 8:30 p. m.; sábado…»."""
    groups = []
    for item in config['hours']:
        if not item['enabled']:
            continue
        span = (item['start'], item['end'])
        if groups and groups[-1][2] == span and groups[-1][1] == item['weekday'] - 1:
            groups[-1][1] = item['weekday']
        else:
            groups.append([item['weekday'], item['weekday'], span])
    return '; '.join((DAYS[a] if a == b else DAYS[a] + ' a ' + DAYS[b]) + ' de ' + _clock(span[0]) + ' a ' + _clock(span[1]) for a, b, span in groups)


def status(config, now):
    """Si la atención presencial está abierta ahora y cuándo abre o cierra, según la hora de Ecuador y los cierres extraordinarios."""
    local = now.astimezone(ECUADOR_TZ)
    closed_days = {item['date']: item['note'] for item in config['closures']}

    def span(day):
        item = config['hours'][day.weekday()]
        return None if not item['enabled'] or day.isoformat() in closed_days else (time.fromisoformat(item['start']), time.fromisoformat(item['end']))
    today = span(local.date())
    if today and today[0] <= local.time() < today[1]:
        return {'open': True, 'closes': today[1].strftime('%H:%M'), 'label': 'Abierto ahora · cierra a las ' + _clock(today[1].strftime('%H:%M')), 'note': ''}
    for offset in range(0, 15):
        day = local.date() + timedelta(days=offset)
        found = span(day)
        if found and (offset or local.time() < found[0]):
            when = 'hoy' if offset == 0 else 'mañana' if offset == 1 else 'el ' + DAYS[day.weekday()] + ' ' + day.strftime('%d/%m')
            return {'open': False, 'opens': datetime.combine(day, found[0], ECUADOR_TZ).isoformat(timespec='minutes'), 'label': 'Cerrado ahora · abre ' + when + ' a las ' + _clock(found[0].strftime('%H:%M')),
                    'note': closed_days.get(local.date().isoformat(), '')}
    return {'open': False, 'opens': '', 'label': 'Cerrado', 'note': closed_days.get(local.date().isoformat(), '')}


def limits_text(config):
    """Hora límite para solicitar citas, agrupando días iguales: «lunes a viernes hasta las 11:00 p. m.; sábado…»."""
    if not config.get('request_limits_enabled'):
        return ''
    groups = []
    for item in config['request_limits']:
        if groups and groups[-1][2] == item['until'] and groups[-1][1] == item['weekday'] - 1:
            groups[-1][1] = item['weekday']
        else:
            groups.append([item['weekday'], item['weekday'], item['until']])
    return '; '.join((DAYS[a] if a == b else DAYS[a] + ' a ' + DAYS[b]) + ' hasta las ' + _clock(until) for a, b, until in groups)


def requests_open(config, now):
    """Si en este momento se pueden enviar solicitudes de cita en línea y, si no, el aviso que debe ver el cliente."""
    if not config.get('request_limits_enabled'):
        return True, ''
    local = now.astimezone(ECUADOR_TZ)
    until = next(item['until'] for item in config['request_limits'] if item['weekday'] == local.weekday())
    if local.time() < time.fromisoformat(until):
        return True, ''
    return False, 'Hoy las solicitudes de cita en línea se reciben hasta las ' + _clock(until) + ' Puede enviar la suya a partir de mañana; ADI sigue disponible para sus consultas.'


def public(c, now):
    """Lo que pueden ver ADI y las páginas públicas: sin datos internos."""
    config = get(c)
    state = status(config, now)
    return {'timezone': 'America/Guayaquil', 'presencial': text(config), 'hours': config['hours'], 'status': state, 'virtual_enabled': config['virtual_enabled'],
            'virtual_message': config['virtual_message'] if config['virtual_enabled'] else '', 'closed_message': config['closed_message'],
            'closures': [item for item in config['closures'] if item['date'] >= now.astimezone(ECUADOR_TZ).date().isoformat()][:10],
            'today': DAYS[now.astimezone(ECUADOR_TZ).weekday()], 'now': now.astimezone(ECUADOR_TZ).strftime('%H:%M'),
            'request_limits': limits_text(config), 'requests_open': requests_open(config, now)[0], 'requests_notice': requests_open(config, now)[1]}
