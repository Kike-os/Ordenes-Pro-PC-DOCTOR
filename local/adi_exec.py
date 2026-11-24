"""ADI Executive Intelligence 5.0 · herramientas ejecutivas de SOLO LECTURA, recomendaciones (Insights) y metadatos de respuesta
(docs/ADI-EXECUTIVE.md).

Seguridad (validada aquí, no en el prompt):
- Cada herramienta declara el rol que la puede usar; el servidor la ejecuta solo si el usuario lo tiene.
- Reutiliza los módulos existentes (Mission Control, Smart Collections, reportes de facturación, Database Guardian, Smart Fiscal
  Status, AZUR, Live Support, inventario): no duplica cálculos ni consulta la base sin control.
- Nunca devuelve teléfonos, correos, credenciales, tokens ni textos de mensajes de clientes. Nada escribe en la base.
- Si un dato no está disponible se dice así («no_disponible»); nunca se rellena."""
import json
import re
from datetime import timedelta

ADMIN = 'administrador'

# Etiqueta del paso REAL ejecutado (se muestra al usuario como «Consultando …») y fuente interna citada en la respuesta.
STEPS = {
    'resumen_taller': ('Consultando órdenes', 'Órdenes y agenda'), 'trabajos_atrasados': ('Revisando trabajos atrasados', 'Órdenes, presupuestos y agenda'),
    'buscar_ordenes': ('Consultando órdenes', 'Órdenes'), 'detalle_orden': ('Revisando registros de la orden', 'Órdenes'),
    'presupuestos': ('Consultando presupuestos', 'Presupuestos'), 'citas': ('Consultando la agenda', 'Agenda de citas'), 'licencias': ('Consultando licencias', 'Licencias digitales'),
    'finanzas': ('Consultando información financiera', 'Technical Mission Control (ventas, ingresos, gastos)'),
    'facturacion': ('Consultando facturación', 'Premium Billing Center (reporte de facturación)'),
    'cartera': ('Consultando cartera', 'ADI Smart Collections'), 'atencion_clientes': ('Revisando la atención a clientes', 'ADI Live Support'),
    'repuestos': ('Consultando repuestos pendientes', 'Órdenes en espera de repuesto'), 'inventario_bajo': ('Revisando el inventario', 'Centro de Inventario'),
    'infraestructura': ('Revisando la infraestructura', 'Database Guardian, Smart Fiscal Status, AZUR, respaldos y WhatsApp'),
    'recomendaciones': ('Revisando alertas verificables', 'ADI Intelligence Insights'),
}

_obj = lambda props=None, required=None: {'type': 'object', 'additionalProperties': False, 'required': required or [], 'properties': props or {}}
TOOLS = [
    {'type': 'function', 'name': 'finanzas', 'strict': True, 'description': 'Ventas, ingresos confirmados, facturación autorizada y gastos: hoy, ayer, mes, mes anterior al mismo día, año y año anterior; capital pendiente de cartera. La rentabilidad no se calcula.', 'parameters': _obj()},
    {'type': 'function', 'name': 'facturacion', 'strict': True, 'description': 'Reporte de facturación del ambiente vigente entre dos fechas (AAAA-MM-DD; null = mes en curso): facturado, cobrado, por cobrar, formas de pago, notas de crédito y año.',
     'parameters': _obj({'desde': {'type': ['string', 'null']}, 'hasta': {'type': ['string', 'null']}}, ['desde', 'hasta'])},
    {'type': 'function', 'name': 'cartera', 'strict': True, 'description': 'Cartera (ADI Smart Collections): capital pendiente, vencido, pago al retirar, conciliación y las cuentas con pago vencido o compromiso incumplido.', 'parameters': _obj()},
    {'type': 'function', 'name': 'atencion_clientes', 'strict': True, 'description': 'Atención a clientes: conversaciones que esperan a un asesor, solicitudes de atención humana abiertas, métricas del centro de atención y estado de WhatsApp.', 'parameters': _obj()},
    {'type': 'function', 'name': 'repuestos', 'strict': True, 'description': 'Órdenes en espera de repuesto, con días de espera.', 'parameters': _obj()},
    {'type': 'function', 'name': 'inventario_bajo', 'strict': True, 'description': 'Productos del inventario agotados o bajo el mínimo.', 'parameters': _obj()},
    {'type': 'function', 'name': 'infraestructura', 'strict': True, 'description': 'Estado verificado de la base de datos (Database Guardian, migraciones pendientes), Smart Fiscal Status, AZUR (sin secretos), respaldos y WhatsApp.', 'parameters': _obj()},
    {'type': 'function', 'name': 'recomendaciones', 'strict': True, 'description': 'Alertas verificables con prioridad y acción sugerida (ADI Intelligence Insights).', 'parameters': _obj()},
]
ROLES = {t['name']: (ADMIN,) for t in TOOLS}


def allowed(user, name):
    roles = ROLES.get(name)
    return roles is None or (user is not None and user['role'] in roles)


def _cents(v):
    return None if v is None else round(int(v) / 100, 2)


def _safe(fn):
    def wrapper(c, now, *args):
        try:
            return fn(c, now, *args)
        except Exception as error:
            print('adi-exec', fn.__name__, type(error).__name__, flush=True)
            return {'error': 'no_disponible', 'mensaje': 'No se pudo consultar en este momento. Dilo así; no inventes datos.'}
    wrapper.__name__ = fn.__name__
    return wrapper


@_safe
def finanzas(c, now):
    import mission_control
    s = mission_control.summary(c, now)
    block = lambda b: None if not b else {k: _cents(b[k]) for k in ('today', 'yesterday', 'month', 'prev_month', 'year', 'prev_year')}
    return {'moneda': 'USD', 'hoy': s['today'], 'ventas': block(s.get('sales')), 'ingresos_confirmados': block(s.get('income')), 'facturacion_autorizada': block(s.get('invoiced')),
            'gastos': block(s.get('expenses')), 'cartera': {k: _cents(v) for k, v in (s.get('portfolio') or {}).items()} or None,
            'rentabilidad': 'no_disponible: ' + s['profitability']['reason'], 'fuentes': s['sources'],
            'nota': 'prev_month = mes anterior hasta el mismo día; prev_year = mismo tramo del año anterior. Facturación autorizada no implica cobrada.'}


@_safe
def facturacion(c, now, args):
    import invoice_reports
    import invoicing
    first = now.date().replace(day=1).isoformat()
    raw = {'desde': args.get('desde') or first, 'hasta': args.get('hasta') or now.date().isoformat()}
    arg = lambda k: {'from': raw['desde'], 'to': raw['hasta']}.get(k, '') or ''
    f = invoice_reports.parse(arg, now)
    r = invoice_reports.report(c, f, now)
    return {'ambiente': r['environment_label'], 'desde': f['from'], 'hasta': f['to'], 'comprobantes': r['documents'], 'emitidos_sin_rechazo': r['billed_documents'],
            'facturado': _cents(r['billed_cents']), 'cobrado': _cents(r['collected_cents']), 'por_cobrar': _cents(r['outstanding_cents']), 'iva': _cents(r['tax_cents']),
            'por_estado': {invoicing.STATUS.get(k, k): v for k, v in r['by_status'].items()}, 'por_forma_de_pago': [{m['label']: _cents(m['amount_cents'])} for m in r['by_method']],
            'notas_de_credito': r['credit_notes'], 'anio': {'anio': r['annual']['year'], 'facturado': _cents(r['annual']['year_cents']), 'anio_anterior_mismo_dia': _cents(r['annual']['prev_year_cents'])},
            'metodo': r['method_note']}


@_safe
def cartera(c, now):
    import collections_center
    p = collections_center.portfolio(c, now)
    k = p['kpis']
    flagged = [it for it in p['items'] if it['state'] in ('pago_vencido', 'mora_90', 'compromiso_incumplido', 'pendiente_conciliacion', 'vence_hoy')]
    flagged.sort(key=lambda it: -(it.get('days_overdue') or 0))
    return {'kpis': {key: (_cents(v) if key.endswith('_cents') else v) for key, v in k.items()},
            'cuentas_con_atencion': [{'orden': it['code'], 'cliente': it['client'], 'estado': it['state_label'], 'saldo': _cents(it['balance_cents']),
                                      'dias_vencido': it.get('days_overdue'), 'vence': it.get('due_date') or ''} for it in flagged[:15]],
            'total_cuentas_con_atencion': len(flagged),
            'nota': 'La exigibilidad corre desde la entrega o el compromiso, nunca desde la recepción. Pago al retirar no es cartera vencida.'}


@_safe
def atencion_clientes(c, now):
    import live_support
    import whatsapp_handoff as handoff
    s = live_support.summary(c)
    cases = []
    if handoff.installed(c):
        cases = [{'codigo': r['code'], 'canal': r['channel'], 'prioridad': r['priority'], 'motivo': r['reason'], 'desde': r['created_at']}
                 for r in c.execute("SELECT code,channel,priority,reason,created_at FROM adi_handoffs WHERE status IN ('pendiente','asignada') ORDER BY created_at LIMIT 20")]
    wa = {}
    try:
        import whatsapp_business
        o = whatsapp_business.overview(c)
        wa = {'estado': o['state'], 'respuestas_automaticas': o['adi']['auto_reply'], 'ultimo_mensaje_entrante': o['adi']['last_inbound'],
              'limite_mensual_respuestas_adi': whatsapp_business.MAX_MONTHLY_ADI_REPLIES, 'respuestas_adi_este_mes': whatsapp_business.monthly_adi_reply_count(c, now)}
    except Exception:
        wa = {'estado': 'no_disponible'}
    return {'contadores': s.get('counts', {}), 'solicitudes_abiertas': cases, 'metricas_7_dias': live_support.metrics(c), 'whatsapp': wa}


@_safe
def repuestos(c, now):
    import adi_admin
    rows = adi_admin._orders(c, "o.status='esperando_repuesto'", (), 30, now.date())
    return {'total': len(rows), 'ordenes': rows}


@_safe
def inventario_bajo(c, now):
    import inventory
    alerts = inventory.overview(c, now)['alerts']
    return {'total': len(alerts), 'productos': [{k: r.get(k) for k in ('code', 'name', 'stock', 'min_stock') if k in r} for r in alerts[:30]]}


@_safe
def infraestructura(c, now):
    out = {}
    try:
        import db_guardian
        g = db_guardian.status(c, now)
        out['base_de_datos'] = {'nivel': g['label'], 'motivo': g['reason'], 'comprobado': g['checked_at'], 'latencia_ms': g['latency_ms'],
                                'migraciones': g['migrations'], 'migraciones_pendientes': g['pending'], 'esquema_correcto': g['schema_ok'], 'incidencias_activas': g['incidents_active']}
    except Exception as error:
        out['base_de_datos'] = 'no_disponible (%s)' % type(error).__name__
    try:
        import fiscal_status
        f = fiscal_status.status(c, now)
        out['estado_fiscal'] = {k: f.get(k) for k in ('level', 'label', 'reason', 'checked_at', 'environment') if k in f}
    except Exception as error:
        out['estado_fiscal'] = 'no_disponible (%s)' % type(error).__name__
    try:
        import azur_invoicing
        a = azur_invoicing.readiness(c)
        out['azur'] = {'listo': a.get('ready'), 'problemas': a.get('problems', [])[:5]}
    except Exception as error:
        out['azur'] = 'no_disponible (%s)' % type(error).__name__
    try:
        import backups
        ok = [r for r in backups.runs(c) if r.get('status') == 'correcto']
        out['respaldos'] = {'ultimo_correcto': (ok[0].get('finished_at') or ok[0].get('started_at') or '') if ok else 'sin registro', 'destino': ok[0].get('destination', '') if ok else ''}
    except Exception as error:
        out['respaldos'] = 'no_disponible (%s)' % type(error).__name__
    try:
        import stability
        st = stability.status(c, now)
        out['estabilidad'] = {'estado': st.get('label'), 'version': st.get('version'), 'pruebas_con_aviso': [t['name'] for t in st.get('tests', []) if t.get('status') != 'ok']}
    except Exception as error:
        out['estabilidad'] = 'no_disponible (%s)' % type(error).__name__
    return out


def run(c, now, name, args, user):
    """Ejecuta una herramienta ejecutiva si el usuario tiene permiso. None si no es de este módulo."""
    if name not in ROLES:
        return None
    if not allowed(user, name):
        return {'error': 'sin_permiso', 'mensaje': 'El usuario no tiene permiso para esta información. Dilo así, sin dar datos.'}
    if name == 'facturacion':
        return facturacion(c, now, args)
    if name == 'recomendaciones':
        return {'recomendaciones': insights(c, now)['items']}
    return {'finanzas': finanzas, 'cartera': cartera, 'atencion_clientes': atencion_clientes, 'repuestos': repuestos, 'inventario_bajo': inventario_bajo,
            'infraestructura': infraestructura}[name](c, now)


def meta(tools, now):
    """Pasos realmente ejecutados (en orden, sin repetir) y fuentes internas para mostrar con la respuesta."""
    names = list(dict.fromkeys(t for t in tools or [] if t))
    return {'steps': [STEPS[n][0] for n in names if n in STEPS], 'sources': list(dict.fromkeys(STEPS[n][1] for n in names if n in STEPS)),
            'consulted_at': now.isoformat(timespec='seconds')}


# ------------------------------------------------------------------------------------------------------------------ Insights
PRIORITY = {'alta': 0, 'media': 1, 'baja': 2}


def insights(c, now):
    """Recomendaciones verificables. Cada una: clave única (sin duplicados), motivo, prioridad, fecha de detección (ahora: se calcula en
    vivo), registros relacionados, datos usados, acción sugerida y enlace al módulo. Un fallo en una fuente no inventa nada: se omite."""
    items = []
    stamp = now.isoformat(timespec='seconds')

    def add(key, title, priority, reason, records, data, action, href):
        items.append({'key': key, 'title': title, 'priority': priority, 'reason': reason, 'detected_at': stamp, 'records': records[:8], 'data': data,
                      'action': action, 'href': href})

    def guard(fn):
        try:
            fn()
        except Exception as error:
            print('adi-insight', fn.__name__, type(error).__name__, flush=True)

    def orders():
        import adi_admin
        a = adi_admin.alerts(c, now)
        by = {}
        for item in a.get('avisos', []):
            by.setdefault(item['tipo'], []).append(item['texto'].split(' (')[0].split(' · ')[0])
        rules = (('entrega_vencida', 'ordenes_vencidas', 'Reparaciones con entrega vencida', 'alta', '%d órdenes superaron su fecha estimada de entrega.',
                  'Fecha estimada de entrega anterior a hoy y orden sin entregar.', 'Revisa cada orden y actualiza la fecha o informa al cliente.', '#orders?active=1'),
                 ('sin_movimiento', 'ordenes_sin_movimiento', 'Órdenes activas sin movimiento', 'media', '%d órdenes activas no tienen movimientos recientes.',
                  a.get('criterio_sin_movimiento', 'Sin eventos recientes en el historial.'), 'Revisa su estado con el técnico asignado.', '#orders?active=1'),
                 ('presupuesto_vencido', 'presupuestos_sin_respuesta', 'Presupuestos sin respuesta', 'media', '%d presupuestos enviados vencieron sin respuesta del cliente.',
                  'Presupuestos enviados con validez vencida y sin decisión.', 'Haz seguimiento con el cliente.', '#orders?active=1'))
        for tipo, key, title, prio, reason, data, action, href in rules:
            codes = by.get(tipo) or []
            if codes:
                add(key, title, prio, reason % len(codes), codes, data, action, href)

    def parts():
        n = c.execute("SELECT COUNT(*) FROM orders WHERE status='esperando_repuesto'").fetchone()[0]
        if n:
            codes = [r[0] for r in c.execute("SELECT code FROM orders WHERE status='esperando_repuesto' ORDER BY received_at LIMIT 8")]
            add('repuestos_pendientes', 'Repuestos pendientes', 'media', '%d órdenes esperan un repuesto.' % n, codes, 'Órdenes en estado «Esperando repuesto».',
                'Confirma con el proveedor la fecha de llegada.', '#orders?status=esperando_repuesto')

    def pickups():
        rows = c.execute("SELECT code,COALESCE((SELECT MAX(created_at) FROM order_status_log l WHERE l.order_id=o.id AND l.to_status IN ('listo','espera_entrega')),'') at "
                         "FROM orders o WHERE status IN ('listo','espera_entrega')").fetchall()
        old = [r['code'] for r in rows if r['at'] and r['at'][:10] <= (now.date() - timedelta(days=30)).isoformat()]
        if old:
            add('equipos_sin_retirar', 'Equipos pendientes de retiro (30 días o más)', 'media', '%d equipos listos llevan 30 días o más sin retirarse.' % len(old), old,
                'Fecha en que la orden pasó a «Listo» o «Espera de entrega».', 'Contacta al cliente para coordinar el retiro.', '#invoicing?tab=retiros')

    def collections():
        import collections_center
        p = collections_center.portfolio(c, now)
        broken = [it['code'] for it in p['items'] if it['state'] == 'compromiso_incumplido']
        if broken:
            add('compromisos_incumplidos', 'Compromisos de pago incumplidos', 'alta', '%d compromisos de pago no se cumplieron.' % len(broken), broken,
                'Estado financiero de ADI Smart Collections.', 'Revisa el expediente del cliente antes de contactarlo.', '#invoicing?tab=cartera')
        recon = [it['code'] for it in p['items'] if it['state'] == 'pendiente_conciliacion']
        if recon:
            add('pagos_por_conciliar', 'Pagos pendientes de conciliación', 'media', '%d cuentas tienen transferencias por validar.' % len(recon), recon,
                'Transferencias registradas y aún no validadas.', 'Valida las transferencias en Pagos.', '#invoicing?tab=pagos')

    def support():
        import whatsapp_handoff as handoff
        if not handoff.installed(c):
            return
        rows = c.execute("SELECT code,priority FROM adi_handoffs WHERE status='pendiente' ORDER BY created_at").fetchall()
        if rows:
            high = any(r['priority'] in ('alta', 'urgente') for r in rows)
            add('atencion_humana', 'Solicitudes de atención humana', 'alta' if high else 'media', '%d clientes esperan a un asesor.' % len(rows), [r['code'] for r in rows],
                'Solicitudes de atención abiertas y sin aceptar.', 'Atiende primero la que más espera.', '#live')

    def stock():
        import inventory
        n = inventory.alert_count(c)
        if n:
            add('inventario_bajo', 'Productos con inventario bajo', 'baja', '%d productos están agotados o bajo el mínimo.' % n, [], 'Existencias frente al mínimo de cada ficha.',
                'Revisa las compras pendientes.', '#inventory')

    def infra():
        import db_guardian
        g = db_guardian.status(c, now)
        if g['level'] in ('rojo', 'naranja') or g['incidents_active']:
            add('infra_base', 'Incidencia de base de datos', 'alta', g['reason'] or 'Database Guardian informa una incidencia.', [], 'Database Guardian Pro.',
                'Revisa Sistema → Database Guardian.', '#system')
        if g['pending']:
            add('migraciones_pendientes', 'Migraciones pendientes', 'media', '%d migraciones están pendientes de aplicar.' % len(g['pending']), g['pending'],
                'Migraciones verificadas frente al manifiesto.', 'Aplícalas desde Sistema con un respaldo reciente.', '#system')
        import fiscal_status
        f = fiscal_status.status(c, now)
        if f.get('level') == 'rojo':
            add('infra_fiscal', 'Facturación electrónica con problemas', 'alta', f.get('reason') or 'Smart Fiscal Status en rojo.', [], 'Smart Fiscal Status.',
                'Revisa Facturación → Estado fiscal antes de emitir.', '#invoicing')

    for fn in (orders, parts, pickups, collections, support, stock, infra):
        guard(fn)
    seen, unique = set(), []
    for it in items:
        if it['key'] not in seen:
            seen.add(it['key'])
            unique.append(it)
    unique.sort(key=lambda it: PRIORITY[it['priority']])
    return {'items': unique, 'generated_at': stamp, 'total': len(unique)}


# ------------------------------------------------------------------------------------------------------------------ Estado
STATE_KEY = 'adi_exec_service'


def record_service(c, ok, now, detail=''):
    """Guarda el resultado REAL de la última llamada al modelo (para no indicar «en línea» si no responde)."""
    try:
        row = c.execute('SELECT value FROM system_state WHERE key=?', (STATE_KEY,)).fetchone()
        state = json.loads(row['value']) if row else {}
        state['last_ok' if ok else 'last_error'] = now.isoformat(timespec='seconds')
        if not ok:
            state['error'] = detail[:120]
        c.execute('INSERT INTO system_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (STATE_KEY, json.dumps(state)))
    except Exception as error:
        print('adi-exec-state', type(error).__name__, flush=True)


def service(c, now):
    """Estado verificable de ADI: configurada, última respuesta correcta y último error. «en_linea» solo con una respuesta reciente
    correcta y sin un error posterior."""
    import adi_ai
    configured = bool(adi_ai.openai_key())
    row = c.execute('SELECT value FROM system_state WHERE key=?', (STATE_KEY,)).fetchone()
    try:
        state = json.loads(row['value']) if row else {}
    except ValueError:
        state = {}
    ok, err = state.get('last_ok', ''), state.get('last_error', '')
    if not configured:
        level, label = 'gris', 'Sin IA configurada: respuestas solo con datos'
    elif err and err > ok:
        level, label = 'rojo', 'La última consulta a la IA falló'
    elif ok:
        level, label = 'verde', 'En línea'
    else:
        level, label = 'gris', 'Sin consultas recientes para verificar'
    return {'configured': configured, 'level': level, 'label': label, 'last_ok': ok, 'last_error': err, 'read_only': True, 'checked_at': now.isoformat(timespec='seconds')}


# ------------------------------------------------------------------------------------------------------------------ Historial seguro
SECRET_PATTERNS = (
    re.compile(r'(?i)\b(contrase[nñ]a|password|clave|pin|token|secret[oa]?|api[_ -]?key)\b(\s*(?:de\s+\w+\s*)?[:=]\s*|\s+(?:es|era)\s+)(\S+)'),
    re.compile(r'\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}\b'),
    re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}\b'),   # JWT
    re.compile(r'\b[A-Fa-f0-9]{40,}\b'),                                                  # claves hexadecimales largas
)


def redact(text):
    """Quita credenciales, contraseñas y tokens ANTES de guardar el historial o enviarlo a la IA."""
    out = str(text or '')
    out = SECRET_PATTERNS[0].sub(lambda m: m.group(1) + m.group(2) + '[dato sensible omitido]', out)
    for pattern in SECRET_PATTERNS[1:]:
        out = pattern.sub('[dato sensible omitido]', out)
    return out


def installed(c):
    return c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('adi_admin_flags','adi_admin_meta','adi_admin_feedback')").fetchone()[0] == 3
