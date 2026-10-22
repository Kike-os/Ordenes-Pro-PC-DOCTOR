"""ADI para administración: consultas de solo lectura sobre órdenes, estados, presupuestos, citas y licencias, y avisos de trabajos
atrasados. Todo sale de la base (consultas parametrizadas); nada se estima ni se inventa. Nunca escribe ni envía nada.

El canal de clientes (adi.reply) no usa este módulo: un cliente nunca recibe datos internos."""
import json
import re
from datetime import date, datetime, timedelta

import appointments
import quotes
import reception

STALE_DAYS = 7  # una orden activa sin ningún movimiento en su historial durante 7 días o más se avisa como «sin movimiento»
ACTIVE = "o.status!='entregado'"
LIMIT = 25


def _dmy(value):
    """AAAA-MM-DD → DD/MM/AAAA (lo demás, tal cual)."""
    value = str(value or '')
    return value[8:10] + '/' + value[5:7] + '/' + value[:4] if re.fullmatch(r'\d{4}-\d{2}-\d{2}.*', value) else value


def _days(since, today):
    try:
        return (today - date.fromisoformat(str(since)[:10])).days
    except ValueError:
        return None


def _orders(c, where, args=(), limit=LIMIT, today=None):
    """Órdenes con cliente, equipo, estado, entrega estimada, días de atraso, último movimiento y presupuesto vigente."""
    today = today or appointments.now().date()
    rows = c.execute("SELECT o.id,o.code,o.status,s.label estado,o.estimated_delivery,o.priority,o.received_at,cl.name cliente,"
                     "TRIM(COALESCE(d.brand,'')||' '||COALESCE(d.model,'')) equipo,COALESCE(NULLIF(d.kind,''),d.category) tipo,"
                     "(SELECT MAX(h.occurred_at) FROM order_history h WHERE h.order_id=o.id) ultimo "
                     "FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id JOIN statuses s ON s.code=o.status "
                     "WHERE " + where + " ORDER BY o.id DESC LIMIT ?", (*args, limit)).fetchall()
    out = []
    for r in rows:
        late = _days(r['estimated_delivery'], today) if r['estimated_delivery'] else None
        q = c.execute("SELECT code,status FROM quotes WHERE order_id=? AND deleted_at='' ORDER BY version DESC LIMIT 1", (r['id'],)).fetchone()
        out.append({'orden': r['code'], 'enlace': '#orders?id=%d' % r['id'], 'cliente': r['cliente'], 'equipo': r['equipo'] or reception.DEVICE_TYPES.get(r['tipo'] or '', r['tipo']) or 'sin especificar',
                    'estado': r['estado'], 'prioridad': r['priority'], 'entrega_estimada': r['estimated_delivery'] or 'sin fecha',
                    'dias_de_atraso': late if late and late > 0 and r['status'] != 'entregado' else 0,
                    'dias_sin_movimiento': _days(r['ultimo'], today) if r['ultimo'] else None,
                    'presupuesto': (q['code'] + ' · ' + quotes.STATUS[q['status']]) if q else 'sin presupuesto'})
    return out


def alerts(c, now):
    """Trabajos atrasados y pendientes que requieren atención, con su motivo. Solo hechos registrados."""
    today = now.date()
    iso = today.isoformat()
    overdue = _orders(c, ACTIVE + " AND o.estimated_delivery!='' AND o.estimated_delivery<?", (iso,), 50, today)
    stale = [o for o in _orders(c, ACTIVE + " AND o.status NOT IN ('listo','espera_entrega')", (), 200, today)
             if o['dias_sin_movimiento'] is not None and o['dias_sin_movimiento'] >= STALE_DAYS and not o['dias_de_atraso']]
    expired = [dict(r) for r in c.execute("SELECT q.code,q.valid_until,o.code orden,o.id oid,cl.name cliente FROM quotes q JOIN orders o ON o.id=q.order_id JOIN devices d ON d.id=o.device_id "
                                          "JOIN clients cl ON cl.id=d.client_id WHERE q.deleted_at='' AND q.status='enviado' AND q.valid_until!='' AND q.valid_until<? ORDER BY q.valid_until", (iso,))]
    requested = c.execute("SELECT COUNT(*) FROM appointments WHERE deleted_at IS NULL AND status='solicitada' AND starts_at>=?", (appointments.stamp(now),)).fetchone()[0]
    no_date = c.execute("SELECT COUNT(*) FROM orders o WHERE " + ACTIVE + " AND o.estimated_delivery='' AND o.status NOT IN ('listo','espera_entrega')").fetchone()[0]
    items = []
    for o in sorted(overdue, key=lambda o: -o['dias_de_atraso']):
        items.append({'tipo': 'entrega_vencida', 'gravedad': 'alta', 'texto': '%s (%s) · %s · entrega prevista %s, %d día%s de atraso · %s' % (o['orden'], o['cliente'], o['equipo'], _dmy(o['entrega_estimada']), o['dias_de_atraso'], '' if o['dias_de_atraso'] == 1 else 's', o['estado']), 'enlace': o['enlace']})
    for o in sorted(stale, key=lambda o: -o['dias_sin_movimiento']):
        items.append({'tipo': 'sin_movimiento', 'gravedad': 'media', 'texto': '%s (%s) · %s · sin movimiento desde hace %d días · %s' % (o['orden'], o['cliente'], o['equipo'], o['dias_sin_movimiento'], o['estado']), 'enlace': o['enlace']})
    for q in expired:
        items.append({'tipo': 'presupuesto_vencido', 'gravedad': 'media', 'texto': '%s (%s) · venció el %s sin respuesta del cliente' % (q['code'], q['cliente'], _dmy(q['valid_until'])), 'enlace': '#orders?id=%d' % q['oid']})
    return {'total': len(items), 'entregas_vencidas': len(overdue), 'sin_movimiento': len(stale), 'presupuestos_vencidos': len(expired),
            'citas_por_confirmar': requested, 'ordenes_activas_sin_fecha_de_entrega': no_date, 'criterio_sin_movimiento': '%d días o más sin eventos en el historial' % STALE_DAYS,
            'avisos': items[:40]}


def order_detail(c, code, now):
    row = c.execute('SELECT id FROM orders WHERE code=?', (reception.current_order_code(c, code),)).fetchone()
    if not row:
        return {'error': 'orden_no_encontrada', 'mensaje': 'No existe una orden con el número ' + str(code)[:40] + '.'}
    base = _orders(c, 'o.id=?', (row['id'],), 1, now.date())[0]
    import equipment
    money = equipment.money(c, row['id'])
    found = quotes.authorization(c, row['id'], c.execute('SELECT status FROM orders WHERE id=?', (row['id'],)).fetchone()[0])
    versions = quotes.for_order(c, row['id'])['versions']
    history = [{'fecha': h['occurred_at'][:16].replace('T', ' '), 'estado': h['status_label'], 'detalle': (h['comment'] or '')[:200], 'usuario': h['actor'] or 'sistema'}
               for h in c.execute("SELECT h.occurred_at,h.status_label,h.comment,u.name actor FROM order_history h LEFT JOIN users u ON u.id=h.actor_id WHERE h.order_id=? ORDER BY h.id DESC LIMIT 6", (row['id'],))]
    return dict(base, presupuestos=[{'codigo': v['code'], 'estado': v['status_label'], 'cotizado': quotes.usd(v['quoted_cents']), 'aprobado': quotes.usd(v['approved_cents'])} for v in versions],
                autorizacion=({'total_autorizado': quotes.usd(found['total_cents']), 'partidas': found['approved_count'], 'registro': 'personal (' + found['staff_name'] + '), sin firma del cliente' if found['by_staff'] else 'cliente con firma electrónica', 'fecha': found['decided_at']} if found else 'sin partidas aprobadas'),
                cobro={'total_a_cobrar': quotes.usd(money['budget_cents']), 'pagado': quotes.usd(money['paid_cents']), 'saldo': quotes.usd(money['balance_cents']), 'estado': money['state_label']},
                ultimos_movimientos=history)


QUOTE_GROUPS = {'pendientes': ('enviado', 'modificacion'), 'aprobados': ('aprobado', 'parcial'), 'rechazados': ('rechazado',), 'borradores': ('borrador',),
                'todos': ('borrador', 'enviado', 'modificacion', 'aprobado', 'parcial', 'rechazado')}


def quote_rows(c, group, now):
    codes = QUOTE_GROUPS.get(group, QUOTE_GROUPS['pendientes'])
    rows = c.execute("SELECT q.id,q.code,q.status,q.sent_at,q.decided_at,q.valid_until,q.tax_rate_bp,q.discount_bp,o.id oid,o.code orden,cl.name cliente FROM quotes q JOIN orders o ON o.id=q.order_id "
                     "JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE q.deleted_at='' AND q.status IN (%s) ORDER BY q.updated_at DESC LIMIT ?" % ','.join('?' * len(codes)), (*codes, LIMIT)).fetchall()
    out = []
    for r in rows:
        t = quotes.totals(quotes.items_of(c, r['id']), r['tax_rate_bp'], r['discount_bp'])
        opened = c.execute("SELECT MIN(verified_at) FROM quote_links WHERE quote_id=? AND verified_at!=''", (r['id'],)).fetchone()[0]
        out.append({'presupuesto': r['code'], 'orden': r['orden'], 'enlace': '#orders?id=%d' % r['oid'], 'cliente': r['cliente'], 'estado': quotes.STATUS[r['status']],
                    'cotizado': quotes.usd(t['quoted']), 'aprobado': quotes.usd(t['approved']), 'enviado': (r['sent_at'] or '')[:16].replace('T', ' ') or 'no enviado',
                    'decidido': (r['decided_at'] or '')[:16].replace('T', ' ') or 'sin decisión', 'valido_hasta': r['valid_until'] or 'sin fecha',
                    'vencido_sin_respuesta': bool(r['status'] == 'enviado' and r['valid_until'] and r['valid_until'] < now.date().isoformat()),
                    'enlace_abierto_por_el_cliente': (opened or '')[:16].replace('T', ' ') or 'no'})
    return out


def appointment_rows(c, start_day, end_day):
    start = appointments.stamp(datetime.combine(start_day, appointments.time.min, appointments.TZ))
    end = appointments.stamp(datetime.combine(end_day + timedelta(days=1), appointments.time.min, appointments.TZ))
    return [{'fecha': r['starts_at'][:10], 'hora': r['starts_at'][11:16], 'cliente': r['customer_name'], 'servicio': r['service_label'], 'estado': appointments.STATUSES.get(r['status'], r['status']),
             'codigo': r.get('code') or '', 'tecnico': r.get('technician') or 'sin asignar'} for r in appointments.admin_rows(c, start, end)][:60]


def license_rows(c, kind, now):
    import licenses
    if kind == 'por_vencer':
        return [{'licencia': u['code'], 'producto': u['product'], 'cliente': u['client'] or 'sin vender', 'vence': u['expires_at'], 'dias': u['days_left']} for u in licenses.expiring(c, now, 200) if 0 <= u['days_left'] <= 30][:40]
    out = []
    for p in licenses.products(c, now):
        if not p['managed']:
            continue
        s = p['stock']
        out.append({'producto': p['name'], 'disponibles': s.get('disponible', 0), 'reservadas': s.get('reservada', 0), 'entregadas': s.get('entregada', 0), 'vencidas': s.get('vencida', 0),
                    'pendientes_de_existencias': p['pending'], 'precio': quotes.usd(p['price_cents']), 'activo_en_catalogo': bool(p['available'])})
    return out


def _date(value, fallback):
    try:
        return date.fromisoformat(str(value)) if value else fallback
    except ValueError:
        return fallback


TOOLS = [
    {'type': 'function', 'name': 'resumen_taller', 'strict': True, 'description': 'Indicadores del taller ahora: órdenes por estado, recibidas y entregadas hoy, citas de hoy, alertas.',
     'parameters': {'type': 'object', 'additionalProperties': False, 'required': [], 'properties': {}}},
    {'type': 'function', 'name': 'trabajos_atrasados', 'strict': True, 'description': 'Órdenes con entrega vencida, órdenes activas sin movimiento, presupuestos vencidos sin respuesta y citas por confirmar.',
     'parameters': {'type': 'object', 'additionalProperties': False, 'required': [], 'properties': {}}},
    {'type': 'function', 'name': 'buscar_ordenes', 'strict': True, 'description': 'Lista órdenes reales filtradas por estado y/o texto (número de orden, cliente, marca o modelo).',
     'parameters': {'type': 'object', 'additionalProperties': False, 'required': ['estado', 'texto'],
                    'properties': {'estado': {'type': ['string', 'null'], 'enum': ['activas', 'pendiente', 'reparacion', 'esperando_cliente', 'presupuesto', 'listo', 'espera_entrega', 'entregado', 'revision_recurrente', None]},
                                   'texto': {'type': ['string', 'null'], 'description': 'Cliente, número de orden, marca o modelo; null para no filtrar.'}}}},
    {'type': 'function', 'name': 'detalle_orden', 'strict': True, 'description': 'Detalle de una orden por su número (PCD-AAAAMMDD-NNNN): estado, presupuestos, autorización, cobro y últimos movimientos.',
     'parameters': {'type': 'object', 'additionalProperties': False, 'required': ['codigo'], 'properties': {'codigo': {'type': 'string'}}}},
    {'type': 'function', 'name': 'presupuestos', 'strict': True, 'description': 'Presupuestos reales por grupo: pendientes (enviados o con revisión solicitada), aprobados, rechazados, borradores o todos.',
     'parameters': {'type': 'object', 'additionalProperties': False, 'required': ['grupo'], 'properties': {'grupo': {'type': 'string', 'enum': list(QUOTE_GROUPS)}}}},
    {'type': 'function', 'name': 'citas', 'strict': True, 'description': 'Citas de la agenda entre dos fechas (AAAA-MM-DD). Sin fechas: las de hoy.',
     'parameters': {'type': 'object', 'additionalProperties': False, 'required': ['desde', 'hasta'], 'properties': {'desde': {'type': ['string', 'null']}, 'hasta': {'type': ['string', 'null']}}}},
    {'type': 'function', 'name': 'licencias', 'strict': True, 'description': 'Licencias: inventario por producto (disponibles, reservadas, entregadas, vencidas) o las que vencen en 30 días.',
     'parameters': {'type': 'object', 'additionalProperties': False, 'required': ['vista'], 'properties': {'vista': {'type': 'string', 'enum': ['inventario', 'por_vencer']}}}},
]

STATUS_FILTERS = {'activas': ACTIVE, 'pendiente': "o.status='pendiente'", 'reparacion': "o.status='reparacion'", 'esperando_cliente': "o.status='esperando_cliente'", 'presupuesto': "o.status='presupuesto'",
                  'listo': "o.status='listo'", 'espera_entrega': "o.status='espera_entrega'", 'entregado': "o.status='entregado'", 'revision_recurrente': "o.status='revision_recurrente'"}


def run_tool(c, now, name, raw):
    """Ejecuta una herramienta de solo lectura con argumentos validados. Nunca lanza al modelo un error interno."""
    import adi
    try:
        args = json.loads(raw or '{}')
    except ValueError:
        return {'error': 'argumentos_no_validos'}
    if not isinstance(args, dict):
        return {'error': 'argumentos_no_validos'}
    try:
        if name == 'resumen_taller':
            live = adi.snapshot(c, now)
            found = alerts(c, now)
            return dict(live, alertas={k: v for k, v in found.items() if k != 'avisos'})
        if name == 'trabajos_atrasados':
            return alerts(c, now)
        if name == 'buscar_ordenes':
            where, params = [STATUS_FILTERS.get(args.get('estado') or '', '1=1')], []
            text = re.sub(r'\s+', ' ', str(args.get('texto') or '')).strip().lower()[:60]
            if text:
                where.append("instr(lower(o.code||' '||cl.name||' '||COALESCE(d.brand,'')||' '||COALESCE(d.model,'')||' '||COALESCE(d.serial,'')),?)>0")
                params.append(text)
            rows = _orders(c, ' AND '.join(where), tuple(params), LIMIT, now.date())
            total = c.execute("SELECT COUNT(*) FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE " + ' AND '.join(where), tuple(params)).fetchone()[0]
            return {'total': total, 'mostradas': len(rows), 'ordenes': rows}
        if name == 'detalle_orden':
            return order_detail(c, str(args.get('codigo') or '')[:40], now)
        if name == 'presupuestos':
            rows = quote_rows(c, args.get('grupo'), now)
            return {'grupo': args.get('grupo'), 'total': len(rows), 'presupuestos': rows}
        if name == 'citas':
            start = _date(args.get('desde'), now.date())
            end = _date(args.get('hasta'), start)
            if end < start or (end - start).days > 31:
                return {'error': 'rango_no_valido', 'mensaje': 'El rango debe ser de hasta 31 días.'}
            rows = appointment_rows(c, start, end)
            return {'desde': start.isoformat(), 'hasta': end.isoformat(), 'total': len(rows), 'citas': rows}
        if name == 'licencias':
            vista = args.get('vista') if args.get('vista') in ('inventario', 'por_vencer') else 'inventario'
            rows = license_rows(c, vista, now)
            return {'vista': vista, 'total': len(rows), 'licencias': rows}
    except Exception as error:
        print('adi-admin-tool', name, type(error).__name__, flush=True)
        return {'error': 'consulta_no_disponible', 'mensaje': 'No se pudo consultar en este momento. Dilo así; no inventes datos.'}
    return {'error': 'herramienta_desconocida'}


SYSTEM = ("Eres ADI, la asistente interna de administración de PC-DOCTOR S.A. Hablas con un administrador autenticado de Órdenes Pro, no con un cliente. "
          "Tienes acceso de solo lectura a los datos reales del sistema mediante las herramientas: úsalas siempre antes de responder sobre órdenes, estados, "
          "presupuestos, citas, licencias o trabajos atrasados. Responde en español, breve y ordenado (listas cortas), citando números de orden y presupuesto. "
          "Usa únicamente lo que devuelven las herramientas: si un dato no aparece, di que no consta; nunca lo inventes ni lo estimes. "
          "No ejecutas cambios, envíos ni escrituras: si te piden modificar algo, indica en qué módulo se hace. "
          "No ofrezcas un asesor humano ni hables de compras o reservas de clientes: el usuario es del taller. "
          "Fechas en formato día/mes/año y hora de Ecuador; importes en dólares tal como vienen.")


def ask(c, text, now, history=()):
    """Respuesta con IA y herramientas de solo lectura. None si la IA no está configurada o falla (se usa la respuesta por datos)."""
    import adi
    import adi_ai
    import os
    import urllib.error
    key = adi_ai.openai_key()
    if not key:
        return None
    model = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')
    instructions = SYSTEM + ' Hoy es ' + now.strftime('%d/%m/%Y %H:%M') + ' (Ecuador).'
    payload = {'model': model, 'instructions': instructions, 'input': list(history) + [{'role': 'user', 'content': text[:2000]}], 'tools': TOOLS, 'max_output_tokens': 700}
    used = []
    try:
        for _ in range(adi.MAX_TOOL_ROUNDS + 1):
            data = adi._post(key, payload)
            calls = [item for item in data.get('output', []) if item.get('type') == 'function_call']
            if not calls:
                answer = adi._text_of(data)[:4000]
                return {'answer': answer, 'tools': used} if answer else None
            outputs = []
            for call in calls:
                used.append(call.get('name'))
                outputs.append({'type': 'function_call_output', 'call_id': call.get('call_id'), 'output': json.dumps(run_tool(c, now, call.get('name'), call.get('arguments')), ensure_ascii=False, default=str)[:14000]})
            payload = {'model': model, 'instructions': instructions, 'previous_response_id': data.get('id'), 'input': outputs, 'tools': TOOLS, 'max_output_tokens': 700}
        answer = adi._text_of(data)[:4000]
        return {'answer': answer, 'tools': used} if answer else None
    except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
        print('adi-admin-ia', type(error).__name__, flush=True)
        return None


def links_for(c, text, used):
    """Enlaces a los módulos según lo consultado (y a las órdenes citadas en la respuesta)."""
    out = []
    for code in dict.fromkeys(m.upper() for m in re.findall(r'PCD-\d{8}-\d{4,}', text, re.I)):
        row = c.execute('SELECT id FROM orders WHERE code=?', (code,)).fetchone()
        if row:
            out.append({'label': 'Abrir ' + code, 'href': '#orders?id=%d' % row['id']})
    extra = {'citas': ('Agenda de Citas', '#appointments'), 'licencias': ('Licencias', '#licenses'), 'trabajos_atrasados': ('Órdenes activas', '#orders?active=1'),
             'buscar_ordenes': ('Órdenes', '#orders?active=1'), 'presupuestos': ('Órdenes', '#orders?active=1')}
    for name in dict.fromkeys(used or []):
        if name in extra and extra[name][1] not in [x['href'] for x in out]:
            out.append({'label': extra[name][0], 'href': extra[name][1]})
    return out[:5]
