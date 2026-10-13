"""Feriados de Ecuador para la agenda de citas.

Los feriados nacionales se CALCULAN con las reglas de traslado de la ley vigente (fines de semana largos); no se descargan de ningún
servicio. El Gobierno puede decretar días adicionales o cambios puntuales: por eso administración puede añadir, ajustar u ocultar
cualquier fecha, y lo que decide administración siempre prevalece sobre lo calculado.

Cada feriado tiene un modo de atención: «normal» (horarios habituales), «especial» (horario propio) o «cerrado» (sin citas nuevas).
Un feriado calculado sobre el que nadie ha decidido se atiende con normalidad y queda señalado como «sin definir». Nunca se cancela
una cita existente: si un día cerrado tiene citas, se avisa a administración para que lo resuelva."""
from datetime import date, time, timedelta

MODES = {'normal': 'Atención normal', 'especial': 'Horario especial', 'cerrado': 'Cerrado por feriado'}
SCOPES = {'nacional': 'Feriado nacional', 'local': 'Feriado local', 'otro': 'Día no laborable'}
# Feriados que no se trasladan cuando caen entre semana (martes a jueves).
FIXED = ('Año Nuevo', 'Navidad')


def easter(year):
    """Domingo de Pascua (calendario gregoriano, algoritmo de Meeus/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    month = (h + l - 7 * m + 90) // 25
    return date(year, month, (h + l - 7 * m + 33 * month + 19) % 32)


def observed(day, movable=True):
    """Día de descanso que corresponde a un feriado: sábado → viernes anterior; domingo → lunes siguiente;
    martes → lunes anterior; miércoles o jueves → viernes de esa semana (estas tres últimas, solo si el feriado es trasladable)."""
    weekday = day.weekday()
    if weekday == 5:
        return day - timedelta(days=1)
    if weekday == 6:
        return day + timedelta(days=1)
    if movable and weekday == 1:
        return day - timedelta(days=1)
    if movable and weekday in (2, 3):
        return day + timedelta(days=4 - weekday)
    return day


def national(year):
    """Feriados nacionales del año con su día de descanso. [{'day', 'label', 'actual'}] ordenados por fecha."""
    pascua = easter(year)
    rows = [(date(year, 1, 1), 'Año Nuevo'), (date(year, 5, 1), 'Día del Trabajo'), (date(year, 5, 24), 'Batalla de Pichincha'),
            (date(year, 8, 10), 'Primer Grito de Independencia'), (date(year, 10, 9), 'Independencia de Guayaquil'), (date(year, 12, 25), 'Navidad')]
    out = [{'day': observed(day, label not in FIXED), 'label': label, 'actual': day} for day, label in rows]
    # Carnaval (lunes y martes) y Viernes Santo dependen de la Pascua y no se trasladan.
    out += [{'day': pascua - timedelta(days=48), 'label': 'Carnaval (lunes)', 'actual': pascua - timedelta(days=48)},
            {'day': pascua - timedelta(days=47), 'label': 'Carnaval (martes)', 'actual': pascua - timedelta(days=47)},
            {'day': pascua - timedelta(days=2), 'label': 'Viernes Santo', 'actual': pascua - timedelta(days=2)}]
    # 2 y 3 de noviembre son feriados consecutivos y se trasladan como pareja, según el día en que caiga el 2.
    second, third = date(year, 11, 2), date(year, 11, 3)
    shift = {0: (0, 0), 1: (0, -2), 2: (2, 0), 3: (0, 0), 4: (0, -2), 5: (-1, 1), 6: (2, 0)}[second.weekday()]
    out += [{'day': second + timedelta(days=shift[0]), 'label': 'Día de Difuntos', 'actual': second},
            {'day': third + timedelta(days=shift[1]), 'label': 'Independencia de Cuenca', 'actual': third}]
    return sorted(out, key=lambda item: item['day'])


def _stored(c, first, last):
    return {row['day']: dict(row) for row in c.execute('SELECT * FROM appointment_holidays WHERE day BETWEEN ? AND ?', (first.isoformat(), last.isoformat()))}


def between(c, first, last):
    """Feriados vigentes entre dos fechas: los nacionales calculados (salvo los que administración ocultó) y los guardados por administración."""
    stored, out = _stored(c, first, last), {}
    for year in range(first.year, last.year + 2):  # el Año Nuevo que cae sábado se descansa el 31 de diciembre anterior
        for item in national(year):
            if first <= item['day'] <= last:
                out[item['day'].isoformat()] = {'day': item['day'].isoformat(), 'label': item['label'], 'scope': 'nacional', 'place': '', 'mode': 'normal', 'open_time': '', 'close_time': '',
                                                'decided': False, 'calculated': True, 'moved_from': item['actual'].isoformat() if item['actual'] != item['day'] else ''}
    for day, row in stored.items():
        if row['hidden']:
            out.pop(day, None)
            continue
        base = out.get(day, {'calculated': False, 'moved_from': ''})
        out[day] = dict(base, day=day, label=row['label'], scope=row['scope'] if row['scope'] != 'otro' or not base.get('calculated') else 'nacional', place=row['place'], mode=row['mode'],
                        open_time=row['open_time'], close_time=row['close_time'], decided=True)
    for item in out.values():
        item['mode_label'] = MODES[item['mode']]
        item['scope_label'] = SCOPES[item['scope']] + (' · ' + item['place'] if item['place'] else '')
    return sorted(out.values(), key=lambda item: item['day'])


def on(c, day):
    """Feriado vigente en una fecha, o None."""
    found = between(c, day, day)
    return found[0] if found else None


def hours(c, day, weekday_hours):
    """Horario de citas de un día teniendo en cuenta el feriado: (inicio, fin) como objetos time, o None si no se atiende.
    `weekday_hours`: fila de appointment_hours de ese día de la semana (o None)."""
    stored = c.execute('SELECT mode,open_time,close_time,hidden FROM appointment_holidays WHERE day=?', (day.isoformat(),)).fetchone()
    if stored and not stored['hidden']:
        if stored['mode'] == 'cerrado':
            return None
        if stored['mode'] == 'especial':
            return time.fromisoformat(stored['open_time']), time.fromisoformat(stored['close_time'])
    if not weekday_hours or not weekday_hours['enabled']:
        return None
    return time.fromisoformat(weekday_hours['start_time']), time.fromisoformat(weekday_hours['end_time'])


def save(c, data):
    """Alta o ajuste de un feriado por administración. Devuelve la fecha guardada."""
    try:
        day = date.fromisoformat(str(data.get('day', '')))
    except ValueError:
        raise ValueError('Indica una fecha válida.')
    label, mode, scope = str(data.get('label', '')).strip()[:100], str(data.get('mode', 'cerrado')), str(data.get('scope', 'otro'))
    place = str(data.get('place', '')).strip()[:60]
    if len(label) < 3:
        raise ValueError('Escribe el nombre del feriado.')
    if mode not in MODES or scope not in SCOPES:
        raise ValueError('Selecciona un modo de atención y un ámbito válidos.')
    if scope == 'local' and not place:
        raise ValueError('Indica la ciudad o el cantón del feriado local.')
    start = end = ''
    if mode == 'especial':
        try:
            begin, finish = time.fromisoformat(str(data.get('open_time', ''))), time.fromisoformat(str(data.get('close_time', '')))
        except ValueError:
            raise ValueError('Indica la hora de apertura y de cierre del horario especial.')
        if begin >= finish or begin.minute % 15 or finish.minute % 15:
            raise ValueError('El horario especial debe abrir antes de cerrar, en intervalos de 15 minutos.')
        start, end = begin.strftime('%H:%M'), finish.strftime('%H:%M')
    c.execute('INSERT INTO appointment_holidays(day,label,mode,open_time,close_time,scope,place,hidden) VALUES (?,?,?,?,?,?,?,0) ON CONFLICT(day) DO UPDATE SET '
              'label=excluded.label,mode=excluded.mode,open_time=excluded.open_time,close_time=excluded.close_time,scope=excluded.scope,place=excluded.place,hidden=0',
              (day.isoformat(), label, mode, start, end, scope, place if scope == 'local' else ''))
    return day.isoformat()


def remove(c, day_text):
    """Quita un feriado. Si era uno calculado, queda oculto (se puede restaurar); si lo añadió administración, se elimina."""
    try:
        day = date.fromisoformat(str(day_text))
    except ValueError:
        raise ValueError('Indica una fecha válida.')
    calculated = next((item for item in national(day.year) if item['day'] == day), None)
    if calculated:
        c.execute('INSERT INTO appointment_holidays(day,label,mode,scope,hidden) VALUES (?,?,?,?,1) ON CONFLICT(day) DO UPDATE SET hidden=1', (day.isoformat(), calculated['label'], 'normal', 'nacional'))
    else:
        c.execute('DELETE FROM appointment_holidays WHERE day=?', (day.isoformat(),))


def restore(c, day_text):
    """Vuelve a mostrar un feriado calculado que estaba oculto, sin decisión de atención."""
    c.execute('DELETE FROM appointment_holidays WHERE day=? AND hidden=1', (str(day_text),))


def hidden(c, year):
    return [dict(r) for r in c.execute('SELECT day,label FROM appointment_holidays WHERE hidden=1 AND day BETWEEN ? AND ? ORDER BY day', ('%d-01-01' % year, '%d-12-31' % year))]


def conflicts(c, today):
    """Citas vigentes en días cerrados por feriado (o fuera del horario especial): administración debe resolverlas; el sistema no las cancela."""
    out = []
    for row in c.execute("SELECT a.id,a.public_code,a.starts_at,a.duration_minutes,a.status,cl.name client FROM appointments a LEFT JOIN clients cl ON cl.id=a.client_id "
                         "WHERE a.deleted_at IS NULL AND a.status NOT IN ('cancelada','completada','no_asistio') AND substr(a.starts_at,1,10)>=? ORDER BY a.starts_at", (today.isoformat(),)):
        day = date.fromisoformat(row['starts_at'][:10])
        stored = c.execute('SELECT label,mode,open_time,close_time,hidden FROM appointment_holidays WHERE day=?', (day.isoformat(),)).fetchone()
        if not stored or stored['hidden'] or stored['mode'] == 'normal':
            continue
        clock = row['starts_at'][11:16]
        if stored['mode'] == 'cerrado' or not stored['open_time'] <= clock < stored['close_time']:
            out.append({'id': row['id'], 'code': row['public_code'], 'starts_at': row['starts_at'], 'client': row['client'] or '', 'holiday': stored['label'],
                        'reason': 'El día está cerrado por feriado.' if stored['mode'] == 'cerrado' else 'La cita queda fuera del horario especial (%s a %s).' % (stored['open_time'], stored['close_time'])})
    return out


def notice(c, today):
    """Aviso de ADI para el personal cuando hoy es feriado. None si no lo es."""
    item = on(c, today)
    if not item:
        return None
    kind = {'nacional': 'feriado nacional', 'local': 'feriado local' + (' en ' + item['place'] if item['place'] else ''), 'otro': 'día no laborable'}[item['scope']]
    detail = {'normal': 'Verifica el horario especial de atención de PC-DOCTOR S.A.', 'cerrado': 'La agenda está cerrada por feriado: no se reciben citas nuevas para hoy.',
              'especial': 'Horario especial de hoy: %s a %s.' % (item['open_time'], item['close_time'])}[item['mode'] if item['decided'] else 'normal']
    return {'day': item['day'], 'label': item['label'], 'scope': item['scope'], 'mode': item['mode'], 'decided': item['decided'],
            'text': 'ADI informa: Hoy es %s (%s). %s' % (kind, item['label'], detail)}


REMIND_DAYS = 7
DAYS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
MONTHS = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')


def reminders(c, today, days=REMIND_DAYS):
    """Feriados de los próximos días cuya atención nadie ha definido todavía. Sirve para que ADI se lo recuerde a administración a tiempo
    de revisar el decreto oficial. En cuanto se elige un modo de atención (o se oculta la fecha) el recordatorio desaparece."""
    out = []
    for item in between(c, today + timedelta(days=1), today + timedelta(days=days)):
        if item['decided']:
            continue
        day = date.fromisoformat(item['day'])
        left = (day - today).days
        when = 'Mañana' if left == 1 else 'El %s %d de %s' % (DAYS[day.weekday()], day.day, MONTHS[day.month - 1])
        kind = {'nacional': 'feriado nacional', 'local': 'feriado local', 'otro': 'día no laborable'}[item['scope']]
        out.append({'day': item['day'], 'label': item['label'], 'days_left': left,
                    'text': 'ADI informa: %s es %s (%s) y aún no se ha definido la atención. Revisa el decreto oficial y elige atención normal, horario especial o cerrado.' % (when, kind, item['label'])})
    return out

