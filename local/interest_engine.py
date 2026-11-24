"""ADI 3.0 · fase 3: política de gracia de 90 días y motor de intereses — SOLO SIMULACIÓN (docs/ADI-INTERESES.md).

El cálculo lo hace este módulo, nunca la IA: aritmética Decimal, interés simple, base 365 días, solo sobre capital vencido (los pagos
parciales lo reducen desde su fecha), sin capitalizar, sin interés sobre interés, sin cargos de cobranza ni multas, con la tasa validada
vigente cada día. Días 1 a N de retraso (N = gracia, 90 por defecto): sin intereses y nunca se cobran después de forma retroactiva.

Modo único habilitado: «simulación». Calcula un estimado que no se guarda, no cambia saldos, pagos ni facturas, no emite documentos
tributarios y no se comunica al cliente. Los modos «revisión administrativa» y «aplicación autorizada» existen como definición, pero el
sistema rechaza activarlos: requieren validación jurídica, contable y tributaria y una autorización expresa e independiente.

Tasas: solo las registradas en «Configuración financiera — Tasas legales Ecuador» con estado VALIDADA. Si falta una tasa validada para
algún día del período, la simulación se suspende y se avisa a administración: nunca se reemplaza por un valor inventado. No se usan tasas
bancarias de consumo ni de microcrédito. El período de mora no se cuenta desde la fecha de ingreso del equipo: parte del vencimiento de
una obligación exigible (aquí, la fecha acordada de un compromiso de pago incumplido, o la que indique administración para simular)."""
import json
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

MODES = {'simulacion': 'Simulación', 'revision': 'Revisión administrativa', 'aplicacion': 'Aplicación autorizada'}
KINDS = {'legal': 'Tasa legal anual', 'maxima_convencional': 'Tasa máxima convencional anual'}
RATE_STATUS = {'sin_validar': 'Sin validar', 'validada': 'Validada', 'anulada': 'Anulada'}
DEFAULT_POLICY = {'grace_days': 90, 'rate_kind': 'legal'}
BASE = Decimal(365)
CENT = Decimal('0.01')
BCE_SOURCE = 'https://contenido.bce.fin.ec/documentos/Estadisticas/SectorMonFin/TasasInteres/Indice.htm'
NOT_INSTALLED = 'El registro de tasas necesita la migración 120 (Sistema → Migraciones). Sin tasas validadas no se simulan intereses.'
LEGAL_NOTE = ('Simulación sin efectos: no afecta saldos ni se comunica al cliente. La aplicación definitiva requiere validación jurídica '
              '(tipo de obligación, tasa, fecha de exigibilidad y metodología), contable y tributaria, y una autorización independiente.')


class InterestError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def installed(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='financial_rates'").fetchone())


def mode(c):
    """Siempre «simulacion»: los demás modos no se pueden activar desde el sistema."""
    return 'simulacion'


def set_mode(c, value):
    if value != 'simulacion':
        raise InterestError('No autorizado: «%s» requiere validación jurídica, contable y tributaria y una autorización expresa e independiente. '
                            'El sistema permanece en simulación.' % MODES.get(value, value), 403)
    return 'simulacion'


def policy(c):
    row = c.execute("SELECT value FROM system_state WHERE key='interest_policy'").fetchone()
    try:
        stored = json.loads(row['value']) if row else {}
    except (TypeError, ValueError):
        stored = {}
    out = dict(DEFAULT_POLICY)
    if str(stored.get('grace_days', '')).isdigit() and 30 <= int(stored['grace_days']) <= 180:
        out['grace_days'] = int(stored['grace_days'])
    if stored.get('rate_kind') in KINDS:
        out['rate_kind'] = stored['rate_kind']
    return out


def save_policy(c, data):
    grace, kind = str(data.get('grace_days', '')), str(data.get('rate_kind', '') or 'legal')
    if not grace.isdigit() or not 30 <= int(grace) <= 180 or kind not in KINDS:
        raise InterestError('Gracia de 30 a 180 días y un tipo de tasa válido.', 400)
    c.execute("INSERT INTO system_state(key,value) VALUES ('interest_policy',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (json.dumps({'grace_days': int(grace), 'rate_kind': kind}),))
    return policy(c)


# ---- Registro de tasas --------------------------------------------------------------------------------------------------------------------

def _day(value):
    try:
        return date.fromisoformat(str(value or '')[:10])
    except ValueError:
        return None


def percent(bp):
    return ('%s %%' % (Decimal(bp) / 100).quantize(CENT)).replace('.', ',')


def rates(c):
    if not installed(c):
        return []
    return [dict(r, kind_label=KINDS[r['kind']], status_label=RATE_STATUS[r['status']], rate=percent(r['annual_bp']))
            for r in c.execute('SELECT f.*,COALESCE(u.name,\'\') user FROM financial_rates f LEFT JOIN users u ON u.id=f.user_id ORDER BY f.kind,f.effective_from DESC,f.id DESC')]


def add_rate(c, data, user, now):
    if not installed(c):
        raise InterestError(NOT_INSTALLED, 409)
    kind = str(data.get('kind', ''))
    if kind not in KINDS:
        raise InterestError('Elige el tipo de tasa.', 400, {'kind': 'Obligatorio.'})
    raw = str(data.get('rate', '') or '').strip().replace('%', '').replace(',', '.')
    if not re.fullmatch(r'\d{1,2}(\.\d{1,2})?', raw) or not Decimal('0.01') <= Decimal(raw) < Decimal(100):
        raise InterestError('Escribe la tasa anual en porcentaje, con hasta dos decimales (p. ej., 6,88).', 400, {'rate': 'No válida.'})
    start, end = _day(data.get('effective_from')), _day(data.get('effective_to')) if data.get('effective_to') else None
    if not start or (data.get('effective_to') and (not end or end < start)):
        raise InterestError('Indica la fecha de vigencia (y, si corresponde, su fin).', 400, {'effective_from': 'No válida.'})
    consulted = _day(data.get('consulted_at'))
    if not consulted or consulted > now.date():
        raise InterestError('Indica la fecha en que se consultó la fuente oficial.', 400, {'consulted_at': 'No válida.'})
    source = str(data.get('source_url', '') or '').strip()
    if not re.fullmatch(r'https://[^\s]{8,400}', source) or not re.search(r'(bce\.fin\.ec|bce\.ec|gob\.ec)', source):
        raise InterestError('La fuente debe ser una publicación oficial (Banco Central del Ecuador u otra entidad pública, https).', 400, {'source_url': 'Fuente oficial.'})
    evidence = re.sub(r'\s+', ' ', str(data.get('evidence', '') or '')).strip()
    if not 10 <= len(evidence) <= 400:
        raise InterestError('Describe la evidencia de publicación (documento, tabla y fecha).', 400, {'evidence': 'Obligatoria.'})
    bp = int((Decimal(raw) * 100).to_integral_value(ROUND_HALF_UP))
    return c.execute('INSERT INTO financial_rates(kind,annual_bp,effective_from,effective_to,consulted_at,source_url,evidence,status,user_id,created_at) '
                     "VALUES (?,?,?,?,?,?,?,'sin_validar',?,?)", (kind, bp, start.isoformat(), end.isoformat() if end else '', consulted.isoformat(), source,
                                                                 evidence, user['id'], now.isoformat(timespec='seconds'))).lastrowid


def set_rate_status(c, rate_id, status, note, user):
    if not installed(c):
        raise InterestError(NOT_INSTALLED, 409)
    if status not in ('validada', 'anulada'):
        raise InterestError('Estado no válido.')
    note = re.sub(r'\s+', ' ', str(note or '')).strip()
    if not 10 <= len(note) <= 300:
        raise InterestError('Indica quién y cómo se validó o por qué se anula (10 a 300 caracteres).', 400, {'note': 'Obligatoria.'})
    row = c.execute('SELECT * FROM financial_rates WHERE id=?', (rate_id,)).fetchone()
    if not row:
        raise InterestError('Tasa no encontrada.', 404)
    if row['status'] == 'anulada':
        raise InterestError('Una tasa anulada no cambia de estado: registra una nueva.', 409)
    if status == 'validada' and row['user_id'] == user['id'] and \
            c.execute("SELECT COUNT(*) FROM users WHERE role='administrador' AND id!=?", (user['id'],)).fetchone()[0]:
        raise InterestError('La tasa la valida una persona de administración distinta de quien la registró (doble control).', 409)
    c.execute('UPDATE financial_rates SET status=?,note=? WHERE id=?', (status, note, rate_id))


def _rate_table(c, kind):
    if not installed(c):
        return []
    return [(_day(r['effective_from']), _day(r['effective_to']) if r['effective_to'] else None, r['annual_bp'])
            for r in c.execute("SELECT * FROM financial_rates WHERE kind=? AND status='validada' ORDER BY effective_from,id", (kind,))]


def rate_on(table, day):
    """Tasa validada vigente un día (la de vigencia más reciente que lo cubre) o None."""
    found = None
    for start, end, bp in table:
        if start <= day and (end is None or day <= end):
            found = bp
    return found


# ---- Simulador --------------------------------------------------------------------------------------------------------------------------

def simulate(capital_cents, due, as_of, payments=(), table=(), grace=90):
    """Interés simple estimado, base 365. payments: [(fecha, centavos)] confirmados después del vencimiento. Devuelve el detalle por tramo.
    Lanza InterestError(409) si falta una tasa validada para algún día sujeto a intereses (la simulación se suspende)."""
    if capital_cents <= 0:
        raise InterestError('No hay capital vencido para simular.', 409)
    late = max(0, (as_of - due).days)
    start = due + timedelta(days=grace + 1)
    pays = sorted((d, int(c)) for d, c in payments)
    periods, total = [], Decimal(0)
    day = start
    missing = []
    while day <= as_of:
        capital = Decimal(capital_cents - sum(c for d, c in pays if d <= day)) / 100   # el día del pago ya no genera interés
        if capital <= 0:
            break
        bp = rate_on(table, day)
        if bp is None:
            missing.append(day)
            day += timedelta(days=1)
            continue
        daily = capital * Decimal(bp) / Decimal(10000) / BASE
        if periods and periods[-1]['bp'] == bp and periods[-1]['capital'] == capital and periods[-1]['to'] == day - timedelta(days=1):
            periods[-1]['to'], periods[-1]['days'] = day, periods[-1]['days'] + 1
            periods[-1]['raw'] += daily
        else:
            periods.append({'from': day, 'to': day, 'days': 1, 'bp': bp, 'capital': capital, 'raw': daily})
        total += daily
        day += timedelta(days=1)
    if missing:
        raise InterestError('Simulación suspendida: no hay una tasa validada para %d día(s) del período (desde el %s). Registra y valida la tasa '
                            'oficial; el sistema no la reemplaza por otro valor.' % (len(missing), missing[0].strftime('%d/%m/%Y')), 409)
    interest = total.quantize(CENT, ROUND_HALF_UP)
    capital_now = Decimal(capital_cents - sum(c for d, c in pays if d <= as_of)) / 100
    return {'mode': 'simulacion', 'due': due.isoformat(), 'as_of': as_of.isoformat(), 'days_late': late, 'grace_days': grace,
            'grace_until': (due + timedelta(days=grace)).isoformat(), 'interest_start': start.isoformat(),
            'interest_days': sum(p['days'] for p in periods), 'capital': str(max(capital_now, Decimal(0)).quantize(CENT)),
            'interest': str(interest), 'total': str((max(capital_now, Decimal(0)) + interest).quantize(CENT)),
            'periods': [{'from': p['from'].isoformat(), 'to': p['to'].isoformat(), 'days': p['days'], 'rate': percent(p['bp']),
                         'capital': str(p['capital'].quantize(CENT)), 'interest': str(p['raw'].quantize(CENT, ROUND_HALF_UP))} for p in periods],
            'note': LEGAL_NOTE}


def for_order(c, oid, as_of, data=None):
    """Simulación de una orden: por defecto, el compromiso de pago incumplido (su fecha acordada es el vencimiento). Administración puede
    indicar otro capital y vencimiento para comparar («¿y si…?»). Nunca se guarda ni se comunica."""
    import adi_comms
    import adi_order
    import payment_commitments as pc
    data = data or {}
    pol = policy(c)
    ctx = adi_order.context(c, oid)
    if not ctx:
        raise InterestError('Orden no encontrada.', 404)
    blocked = [d for d in adi_comms.delays(ctx, adi_comms_now(as_of)) if d['attributable']]
    if blocked:
        raise InterestError('No exigible: hay un retraso atribuible a PC-DOCTOR (%s). No se simulan intereses mientras la obligación no sea exigible.'
                            % blocked[0]['detail'], 409)
    if ctx['pending_transfers']['count']:
        raise InterestError('Hay transferencias por conciliar: primero se concilian en Caja; mientras tanto no se simulan intereses.', 409)
    if not installed(c):
        raise InterestError(NOT_INSTALLED, 409)
    manual = bool(data.get('capital') or data.get('due_date'))
    if manual:
        import equipment
        capital = equipment.cents_of(str(data.get('capital', '') or ''))
        due = _day(data.get('due_date'))
        if not capital or not due or due > as_of:
            raise InterestError('Para comparar, indica el capital y un vencimiento pasado.', 400)
        source, payments = 'Valores indicados por administración (comparación)', []
    else:
        cur = pc.for_order(c, oid, as_of)['current'] if pc.installed(c) else None
        if not cur or cur['state'] not in ('incumplido', 'parcial'):
            raise InterestError('No hay una obligación vencida y exigible registrada (un compromiso de pago incumplido). Puedes comparar indicando capital y vencimiento.', 409)
        capital, due = cur['amount_cents'], _day(cur['due_date'])
        row = c.execute('SELECT committed_at FROM payment_commitments WHERE id=?', (cur['id'],)).fetchone()
        import equipment
        payments = [(_day(p['created_at']), int(p['amount_cents'])) for p in equipment.payments(c, oid)
                    if not p.get('voided_at') and p.get('kind') in ('pago', 'asignacion') and p.get('transfer_status') != 'pendiente' and str(p['created_at']) >= row['committed_at']]
        source = 'Compromiso de pago #%d incumplido (fecha acordada %s)' % (cur['id'], cur['due'])
    result = simulate(capital, due, as_of, payments, _rate_table(c, pol['rate_kind']), pol['grace_days'])
    result.update(source=source, rate_kind=KINDS[pol['rate_kind']], mode_label=MODES['simulacion'])
    return result


def adi_comms_now(day):
    from datetime import datetime
    from reception import ECUADOR_TZ
    return datetime(day.year, day.month, day.day, 12, tzinfo=ECUADOR_TZ)
