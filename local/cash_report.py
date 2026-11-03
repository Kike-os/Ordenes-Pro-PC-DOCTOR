"""Reporte de cierre de caja: A4 administrativo y ticket térmico de 80 mm (Epson TM-m30II: 72 mm útiles a 203 dpi, una página de altura
variable). Solo lee: los datos salen de la sesión, de la foto inmutable guardada al cerrar (cifras) y de los registros actuales de
transferencias y vouchers (estado de confirmación). Nada se recalcula a mano ni se escribe.

Tres cifras que no se mezclan:
- Recaudación del período: todo lo cobrado, por cualquier medio.
- Movimiento de efectivo: lo que entró y salió del cajón (fondo + entradas − salidas = efectivo esperado).
- Saldo de caja: lo contado en el arqueo frente a lo esperado (diferencia), lo entregado y el fondo reservado.

El QR abre el mismo reporte en una ruta que exige sesión y permisos: no expone información financiera en un enlace público."""
from datetime import datetime

import segno

import banking
import card_vouchers
import cash_sessions as cs
from corporate import settings as corporate_settings
from document_canvas import BLUE, GRAY, INK, Canvas
from reception import ECUADOR_TZ

NAVY = (.08, .20, .38)
SOFT = (.94, .96, .99)
LINE = (.80, .85, .91)
GREEN = (.06, .45, .27)
RED = (.70, .13, .16)
AMBER = (.62, .40, .02)
DOT = 72 / 203  # un punto de la impresora térmica


def _dt(value, seconds=False):
    try:
        return datetime.fromisoformat(str(value)).strftime('%d/%m/%Y %H:%M' + (':%S' if seconds else ''))
    except ValueError:
        return str(value or '')


def _money(cents):
    return cs.usd(cents or 0)


def _signed(cents):
    return ('+' if cents > 0 else '') + _money(cents)


def _state(cents):
    return 'Cuadrado' if cents == 0 else 'Sobrante' if cents > 0 else 'Faltante'


def _tone(cents):
    return GREEN if cents == 0 else AMBER if cents > 0 else RED


def collect(c, user, session_id):
    """Todos los datos del reporte, con los controles de integridad calculados."""
    d = cs.view(c, user, session_id)  # comprueba que el usuario pueda ver esta caja
    s, closing, live = d['session'], d['closing'], d['summary']
    snap = closing['summary'] if closing and isinstance(closing.get('summary'), dict) and 'by_method' in closing['summary'] else live
    rows = snap.get('rows') if closing and snap.get('rows') is not None else live['rows']
    valid = [r for r in rows if not r['voided']]
    income = [r for r in valid if r['direction'] == 'ingreso' and r['kind'] != 'retencion_recibida']
    outgo = [r for r in valid if r['direction'] == 'egreso']
    method_in = lambda *keys: sum(r['amount_cents'] for r in income if r['method'] in keys)
    cash_in, cash_out = method_in('efectivo'), sum(r['amount_cents'] for r in outgo if r['method'] == 'efectivo')
    expected = closing['expected_cash_cents'] if closing else snap['expected_cash_cents']
    totals = {'opening': s['opening_cents'], 'sales': sum(r['amount_cents'] for r in income if r['kind'] != 'otro_ingreso'),
              'other_in': sum(r['amount_cents'] for r in income if r['kind'] == 'otro_ingreso'), 'income': sum(r['amount_cents'] for r in income),
              'outgo': sum(r['amount_cents'] for r in outgo), 'cash': cash_in, 'transfer': method_in('transferencia'), 'deposit': method_in('deposito'),
              'card': method_in('credito', 'debito'), 'others': method_in('cheque', 'otro'), 'cash_in': cash_in, 'cash_out': cash_out, 'expected': expected,
              'counted': closing['counted_cash_cents'] if closing else None, 'difference': closing['difference_cents'] if closing else None,
              'withdrawn': closing['withdrawn_cents'] if closing else None, 'reserved': closing['reserved_cents'] if closing else None}
    totals['electronic'] = totals['transfer'] + totals['deposit'] + totals['card'] + totals['others']
    refs = [r['ref'] for r in rows]
    checks = [('Suma por medio de pago = total de ingresos', totals['cash'] + totals['electronic'] == totals['income']),
              ('Ventas + otros ingresos = total de ingresos', totals['sales'] + totals['other_in'] == totals['income']),
              ('Fondo + entradas - salidas de efectivo = efectivo esperado', totals['opening'] + cash_in - cash_out == expected),
              ('Ninguna operación repetida', len(refs) == len(set(refs)))]
    if closing:
        checks.append(('Contado - esperado = diferencia', totals['counted'] - expected == totals['difference']))
        checks.append(('Entregado + reservado = contado', totals['withdrawn'] + totals['reserved'] == totals['counted']))
    # Transferencias, depósitos y vouchers: registros actuales (estado de confirmación al día), solo los de esta caja.
    accounts = {a['id']: a for a in c.execute('SELECT id,bank,account_type,number FROM bank_accounts')}
    transfers = []
    for t in live['transfers']:
        a = accounts.get(t['bank_account_id'])
        transfers.append({'code': t['code'], 'method': 'Depósito' if t['method'] == 'deposito' else 'Transferencia', 'bank': a['bank'] if a else '',
                          'type': banking.TYPES.get(a['account_type'], a['account_type']) if a else '', 'last4': a['number'][-4:] if a else '', 'reference': t['reference'],
                          'at': t['paid_at'], 'status': banking.TRANSFER_STATUS.get(t['status'], t['status']), 'amount': t['amount_cents'], 'voided': False})
    vouchers = {('orden' if v['payment_id'] else 'anticipo', v['payment_id'] or v['advance_id']): v for v in live['vouchers']}
    cards = []
    for r in income:
        if r['method'] not in ('credito', 'debito'):
            continue
        v = vouchers.get((r['source'], r['source_id']))
        cards.append({'ref': r['ref'], 'brand': v['brand'] if v else r['method_label'], 'issuer': ('%s · %s' % (v['issuer_bank'], v['acquirer'])) if v else 'Sin voucher registrado',
                      'type': card_vouchers.TYPES.get(v['tx_type'], v['tx_type']) if v else r['method_label'], 'auth': ('Lote %s · ref. %s · aut. %s' % (v['lot'], v['reference'], v['approval_code'])) if v else '—',
                      'amount': r['amount_cents']})
    counts = closing['counts'] if closing else []
    counts = sorted((x for x in counts if x.get('qty')), key=lambda x: (x['kind'] != 'billete', -x['value_cents']))
    names = {u['id']: u['name'] for u in c.execute('SELECT id,name FROM users')}
    try:
        import invoicing
        fiscal = invoicing.settings(c)
    except Exception:  # sin datos fiscales todavía
        fiscal = {}
    corp = corporate_settings()
    return {'session': s, 'closing': closing, 'rows': rows, 'income': [r for r in rows if r['direction'] == 'ingreso' and r['kind'] != 'retencion_recibida'],
            'outgo': [r for r in rows if r['direction'] == 'egreso'], 'totals': totals, 'checks': checks, 'transfers': transfers, 'cards': cards, 'counts': counts,
            'adjustments': live['adjustments'], 'pending': live['pending'], 'events': d['events'], 'fund_next': d['fund_next'],
            'counter': (names.get(closing['closed_by'], '') if closing else ''), 'company': {
                'name': fiscal.get('trade_name') or corp.get('name') or 'PC-DOCTOR S.A.', 'legal': fiscal.get('legal_name') or corp.get('name') or 'PC-DOCTOR S.A.',
                'ruc': fiscal.get('ruc') or '', 'address': fiscal.get('head_office_address') or '',
                'contact': ' · '.join(x for x in (corp.get('whatsapp', ''), corp.get('support_email', ''), corp.get('website', '')) if x)}}


def _concept(r):
    parts = [r['kind_label']]
    if r.get('concept'):
        parts.append(r['concept'])
    who = r.get('client') or r.get('beneficiary')
    if who:
        parts.append(who)
    return ' · '.join(parts)


def _bank(label):
    """«Banco · Tipo · número» con el número enmascarado (solo los 4 últimos dígitos)."""
    parts = str(label or '').split(' · ')
    if len(parts) >= 3 and parts[-1].replace('-', '').isdigit():
        parts[-1] = '•••• ' + parts[-1][-4:]
    return ' · '.join(p for p in parts if p)


def _method(r):
    return r['method_label'] + (' · ' + _bank(r['bank']) if r.get('bank') else '')


def _status_note(r):
    return ' (anulado)' if r['voided'] else ''


class Flow:
    """Registra lo que se dibuja por página; al final se crean las páginas y se numeran (Página n de N)."""

    def __init__(self, width, top, bottom):
        self.width, self.top, self.bottom = width, top, bottom
        self.pages, self.y = [[]], top
        self.measure = Canvas(10, 10, 'medida')

    def op(self, *args):
        self.pages[-1].append(args)

    def new_page(self):
        self.pages.append([])
        self.y = self.top

    def need(self, height):
        if self.y + height > self.bottom:
            self.new_page()
            return True
        return False

    def wrap(self, text, width, size, limit=None):
        pieces = self.measure.wrap(text, width, size)
        if limit and len(pieces) > limit:
            last = pieces[limit - 1]
            while last and self.measure.width_of(last + '…', size) > width:
                last = last[:-1]
            pieces = pieces[:limit - 1] + [last.rstrip() + '…']
        return pieces

    def width_of(self, text, size, bold=False):
        return self.measure.width_of(text, size, bold)


# ---- A4 -----------------------------------------------------------------------------------------------------------------------

def a4(c, user, session_id, link, now):
    data = collect(c, user, session_id)
    s, k, t = data['session'], data['closing'], data['totals']
    W, H, L = 595, 842, 36
    R = W - L
    CW = R - L
    f = Flow(W, 96, H - 64)

    def text(value, x, y, size=8.5, bold=False, color=INK):
        f.op('text', value, x, y, size, bold, color)

    def right(value, x, y, size=8.5, bold=False, color=INK):
        f.op('text', value, x - f.width_of(value, size, bold), y, size, bold, color)

    def rule(x, y, width, color=LINE, thick=.6):
        f.op('box', x, y, width, thick, color)

    def frame(x, y, width, height, color=LINE):
        for args in ((x, y, width, .6), (x, y + height - .6, width, .6), (x, y, .6, height), (x + width - .6, y, .6, height)):
            f.op('box', *args, color)

    def section(title, note=''):
        f.need(40)
        f.y += 6
        f.op('box', L, f.y, 3, 13, NAVY)
        text(title.upper(), L + 9, f.y + 1, 10, True, NAVY)
        if note:
            right(note, R, f.y + 2.5, 7.5, False, GRAY)
        f.y += 18

    def table(columns, rows, total=None, empty='Sin registros.'):
        """columns: (título, ancho relativo, alineación). Filas de varias líneas; encabezado repetido al cambiar de página."""
        scale = CW / sum(w for _, w, _ in columns)
        ws = [w * scale for _, w, _ in columns]
        size, lead = 7.8, 9.6

        def header():
            f.op('box', L, f.y, CW, 17, SOFT)
            x = L
            for (title, _, align), w in zip(columns, ws):
                if align == 'r':
                    right(title, x + w - 5, f.y + 5, 7.2, True, NAVY)
                else:
                    text(title, x + 5, f.y + 5, 7.2, True, NAVY)
                x += w
            f.y += 17
        if not rows:
            f.need(22)
            text(empty, L + 5, f.y + 2, 8, False, GRAY)
            f.y += 16
            return
        f.need(17 + 20)
        header()
        for n, row in enumerate(rows):
            cells = [f.wrap(str(v), w - 10, size, 3) for v, w in zip(row['cells'], ws)]
            height = 8 + lead * max(len(x) for x in cells)
            if f.need(height):
                header()
            if n % 2:
                f.op('box', L, f.y, CW, height, (.975, .98, .99))
            x = L
            for (title, _, align), w, pieces in zip(columns, ws, cells):
                for i, piece in enumerate(pieces):
                    color = GRAY if row.get('muted') else INK
                    if align == 'r':
                        right(piece, x + w - 5, f.y + 4 + i * lead, size, row.get('bold', False), color)
                    else:
                        text(piece, x + 5, f.y + 4 + i * lead, size, row.get('bold', False), color)
                x += w
            f.y += height
            rule(L, f.y, CW, (.88, .91, .95), .5)
        if total:
            f.need(18)
            rule(L, f.y, CW, NAVY, .8)
            text(total[0], L + 5, f.y + 5, 8.2, True, NAVY)
            right(total[1], R - 5, f.y + 5, 8.6, True, NAVY)
            f.y += 19

    # Encabezado de la primera página: logo original, empresa (datos fiscales), título, código, estado y QR protegido.
    f.y = 34
    f.op('logo', L, 30, 104)
    co = data['company']
    text(co['legal'], L + 118, 34, 12.5, True, NAVY)
    if co['ruc']:
        text('RUC ' + co['ruc'], L + 118, 51, 8.2, False, INK)
        y = 63
    else:
        y = 51
        for piece in f.wrap('RUC no configurado: complételo en Facturación › Datos fiscales.', 215, 7.8, 2):
            text(piece, L + 118, y, 7.8, True, RED)
            y += 10
        y += 2
    for line in [co['address'], co['contact']]:
        for piece in f.wrap(line, 215, 7.6, 2) if line else []:
            text(piece, L + 118, y, 7.6, False, GRAY)
            y += 10
    if link:
        f.op('qr', link, R - 70, 26, 70)
        right('Verificación interna', R - 76, 74, 7, True, NAVY)
        right('requiere sesión autorizada', R - 76, 84, 6.8, False, GRAY)
    right('REPORTE DE CIERRE DE CAJA', R - 76, 32, 9, True, GRAY)
    right(s['code'], R - 76, 44, 19, True, NAVY)
    status = s['status_label'] + (' · con ajustes posteriores' if data['adjustments'] else '')
    right(status, R - 76, 64, 8.2, True, _tone(t['difference']) if t['difference'] is not None else BLUE)
    f.y = 112
    rule(L, f.y, CW, NAVY, 1.2)
    f.y += 9
    # Datos del cierre en una franja de 4 × 2.
    info = [('Caja', s['register']), ('Turno', s['shift'] or '—'), ('Cajero', s['cashier']), ('Abrió la caja', s['opened_by_name'] or '—'),
            ('Apertura', _dt(s['opened_at'])), ('Cierre', _dt(k['closed_at']) if k else 'Caja en curso'), ('Confirmó el cierre', k['confirmed_name'] if k else '—'),
            ('Autorizó', s['reviewed_by_name'] or '—')]
    f.op('box', L, f.y, CW, 54, SOFT)
    cw4 = CW / 4
    for i, (label, value) in enumerate(info):
        x, yy = L + 10 + (i % 4) * cw4, f.y + 7 + (i // 4) * 24
        text(label.upper(), x, yy, 6.6, True, GRAY)
        text(f.wrap(value, cw4 - 16, 8.6, 1)[0], x, yy + 9, 8.6, True, INK)
    f.y += 60
    # Resumen ejecutivo: tres bloques que no se suman entre sí.
    section('Resumen ejecutivo del cierre', 'Valores en USD')
    gap = 10
    bw = (CW - 2 * gap) / 3
    blocks = [
        ('Recaudación del período', 'Todos los medios de pago', [('Ventas y cobros', t['sales']), ('Otros ingresos', t['other_in']), ('Total de ingresos', t['income'], 'total'),
                                                                  ('Efectivo', t['cash'], 'sub'), ('Transferencias', t['transfer'], 'sub'), ('Depósitos', t['deposit'], 'sub'),
                                                                  ('Tarjetas', t['card'], 'sub'), ('Otros medios', t['others'], 'sub'), ('Egresos del período', t['outgo'], 'out')]),
        ('Movimiento de efectivo', 'Solo el dinero del cajón', [('Fondo inicial de caja', t['opening']), ('Entradas en efectivo', t['cash_in'], 'plus'),
                                                               ('Salidas en efectivo', t['cash_out'], 'minus'), ('Efectivo esperado', t['expected'], 'total')]),
        ('Saldo de caja (arqueo)', 'Conteo físico al cerrar', [('Efectivo esperado', t['expected']), ('Efectivo contado', t['counted']),
                                                               ('Diferencia', t['difference'], 'diff'), ('Efectivo entregado', t['withdrawn']), ('Fondo reservado', t['reserved'])])]
    top = f.y
    f.need(150)
    top = f.y
    heights = []
    for i, (title, note, lines) in enumerate(blocks):
        x, y = L + i * (bw + gap), top
        f.op('box', x, y, bw, 27, SOFT)
        text(title, x + 9, y + 6, 9, True, NAVY)
        text(note, x + 9, y + 17, 7, False, GRAY)
        y += 32
        for line in lines:
            label, cents = line[0], line[1]
            kind = line[2] if len(line) > 2 else ''
            value = '—' if cents is None else (_signed(cents) + ' · ' + _state(cents)) if kind == 'diff' else ('- ' if kind == 'minus' and cents else '+ ' if kind == 'plus' and cents else '') + _money(cents)
            if kind == 'total':
                rule(x + 9, y - 2, bw - 18, NAVY, .8)
            size, bold = (9, True) if kind == 'total' else (7.6 if kind == 'sub' else 8.2, kind == 'diff')
            color = _tone(cents) if kind == 'diff' and cents is not None else NAVY if kind == 'total' else GRAY if kind == 'sub' else INK
            text(('   ' if kind == 'sub' else '') + label, x + 9, y + 1, size, kind in ('total',), GRAY if kind == 'sub' else INK)
            right(value, x + bw - 9, y + 1, size, bold or kind == 'total', color)
            y += 12 if kind != 'total' else 15
        heights.append(y - top)
    tallest = max(heights) + 4
    for i in range(3):
        frame(L + i * (bw + gap), top, bw, tallest)
    f.y = top + tallest + 4
    text('La recaudación incluye todos los medios; el efectivo esperado solo cuenta el cajón. Transferencias, depósitos y tarjetas se concilian aparte.',
         L, f.y + 2, 7.2, False, GRAY)
    f.y += 14
    # Desglose de movimientos (solo las secciones que aplican; los totales de control siempre).
    section('Ingresos', '%d operaciones' % len(data['income']))
    table([('Fecha y hora', 70, 'l'), ('Código', 48, 'l'), ('Documento', 84, 'l'), ('Concepto', 146, 'l'), ('Método', 100, 'l'), ('Monto', 60, 'r')],
          [{'cells': [_dt(r['at']), r['ref'], r['document'] or '—', _concept(r) + _status_note(r), _method(r), _money(r['amount_cents'])], 'muted': r['voided']} for r in data['income']],
          ('Total de ingresos (sin anulados)', _money(t['income'])), 'Sin ingresos en esta caja.')
    if data['outgo']:
        section('Egresos', '%d operaciones' % len(data['outgo']))
        table([('Código', 54, 'l'), ('Fecha y hora', 74, 'l'), ('Concepto', 168, 'l'), ('Responsable', 86, 'l'), ('Método', 66, 'l'), ('Importe', 62, 'r')],
              [{'cells': [r['ref'], _dt(r['at']), _concept(r) + _status_note(r), r['actor'] or '—', _method(r), _money(r['amount_cents'])], 'muted': r['voided']} for r in data['outgo']],
              ('Total de egresos (sin anulados)', _money(t['outgo'])))
    if data['transfers']:
        section('Transferencias y depósitos', 'Estado de confirmación al generar el reporte')
        table([('Código', 50, 'l'), ('Banco', 70, 'l'), ('Cuenta', 52, 'l'), ('Últ. 4', 30, 'l'), ('Referencia', 84, 'l'), ('Fecha y hora', 70, 'l'), ('Estado', 66, 'l'), ('Monto', 58, 'r')],
              [{'cells': [x['code'] + ' · ' + x['method'], x['bank'], x['type'], x['last4'], x['reference'], _dt(x['at']), x['status'], _money(x['amount'])]} for x in data['transfers']],
              ('Total transferencias y depósitos', _money(sum(x['amount'] for x in data['transfers']))))
    if data['cards']:
        section('Tarjetas')
        table([('Operación', 50, 'l'), ('Marca', 60, 'l'), ('Banco o procesador', 110, 'l'), ('Tipo', 90, 'l'), ('Referencia o autorización', 120, 'l'), ('Valor', 60, 'r')],
              [{'cells': [x['ref'], x['brand'], x['issuer'], x['type'], x['auth'], _money(x['amount'])]} for x in data['cards']],
              ('Total cobrado con tarjetas', _money(t['card'])))
    # Arqueo por denominaciones (del conteo guardado al cerrar).
    section('Arqueo de efectivo por denominaciones')
    if data['counts']:
        table([('Denominación', 120, 'l'), ('Tipo', 100, 'l'), ('Cantidad', 80, 'r'), ('Subtotal', 100, 'r')],
              [{'cells': [_money(x['value_cents']), 'Billete' if x['kind'] == 'billete' else 'Moneda', str(x['qty']), _money(x['subtotal_cents'])]} for x in data['counts']],
              ('Total contado', _money(sum(x['subtotal_cents'] for x in data['counts']))))
    else:
        f.need(18)
        text('Desglose no registrado.' if k else 'La caja sigue abierta: el arqueo se registra al cerrar.', L + 5, f.y + 2, 8.2, True, GRAY)
        f.y += 16
    if k:
        lines = [('Total esperado en efectivo', _money(t['expected'])), ('Total contado', _money(t['counted'])),
                 ('Diferencia', _signed(t['difference'])), ('Estado', _state(t['difference']))]
        notes = [x for x in (('Explicación de la diferencia: ' + k['difference_reason']) if k['difference_reason'] else '', ('Observaciones: ' + k['note']) if k['note'] else '',
                             ('Revisión de administración: ' + s['review_note']) if s.get('review_note') else '') if x]
        f.need(16 * len(lines) + 12 * len(notes) + 8)
        half = CW / 2
        for i, (label, value) in enumerate(lines):
            x, y = L + (i % 2) * half, f.y + (i // 2) * 16
            text(label, x + 5, y + 2, 8, False, GRAY)
            color = _tone(t['difference']) if label in ('Diferencia', 'Estado') else INK
            right(value, x + half - 8, y + 2, 8.6, True, color)
        f.y += ((len(lines) + 1) // 2) * 16 + 2
        notes.insert(0, 'Responsable del conteo: %s (confirmó %s).' % (data['counter'] or k['confirmed_name'], k['confirmed_name']))
        for note in notes:
            for piece in f.wrap(note, CW - 10, 7.8, 3):
                f.need(11)
                text(piece, L + 5, f.y, 7.8, False, INK)
                f.y += 10.5
    if data['adjustments']:
        section('Ajustes posteriores', 'El cierre original no se modifica')
        table([('Fecha y hora', 80, 'l'), ('Motivo', 250, 'l'), ('Responsable', 100, 'l'), ('Importe', 70, 'r')],
              [{'cells': [_dt(a['created_at']), a['reason'], a['actor'], _signed(a['amount_cents'])]} for a in data['adjustments']],
              ('Total ajustado', _signed(sum(a['amount_cents'] for a in data['adjustments']))))
    # Controles de integridad (calculados, no escritos a mano).
    # Controles y firmas van juntos: las firmas nunca quedan solas en una hoja.
    f.need(40 + 11 * ((len(data['checks']) + 1) // 2) + (11 if data['pending'] else 0) + 54)
    section('Controles de integridad')
    half = CW / 2
    f.need(11 * ((len(data['checks']) + 1) // 2) + 4)
    for i, (label, ok) in enumerate(data['checks']):
        text(('Correcto · ' if ok else 'REVISAR · ') + label, L + 5 + (i % 2) * half, f.y + (i // 2) * 11, 7.4, not ok, GREEN if ok else RED)
    f.y += 11 * ((len(data['checks']) + 1) // 2) + 2
    if data['pending']:
        f.need(12)
        text('%d %s pendiente(s) de verificar o liquidar (%s): no son dinero confirmado.' % (len(data['pending']), 'cobro' if len(data['pending']) == 1 else 'cobros',
                                                                                                   _money(sum(p['amount_cents'] for p in data['pending']))), L + 5, f.y, 7.8, True, AMBER)
        f.y += 11
    # Firmas.
    f.need(50)
    f.y += 26
    for i, (role, name) in enumerate((('Cajero', s['cashier']), ('Administración', s['reviewed_by_name'] or ''))):
        x = L + i * (CW / 2 + 10)
        rule(x, f.y, CW / 2 - 10, INK, .7)
        text(role, x, f.y + 5, 8, True, INK)
        if name:
            text(name, x, f.y + 15, 7.6, False, GRAY)
    f.y += 26
    # Páginas: encabezado reducido desde la segunda y pie numerado en todas.
    pdf = Canvas(W, H, 'Cierre ' + s['code'])
    total_pages = len(f.pages)
    for number, ops in enumerate(f.pages, 1):
        pdf.page()
        if number > 1:
            pdf.logo(L, 26, 70)
            pdf.text('Reporte de cierre de caja · ' + s['code'] + ' (continuación)', L + 84, 40, 10, True, NAVY)
            pdf.text(s['register'] + ' · ' + s['cashier'], L + 84, 55, 8, False, GRAY)
            pdf.box(L, 78, CW, 1, NAVY)
        for op in ops:
            kind, args = op[0], op[1:]
            if kind == 'text':
                pdf.text(*args)
            elif kind == 'box':
                pdf.box(*args)
            elif kind == 'logo':
                pdf.logo(*args)
            elif kind == 'qr':
                pdf.qr(*args)
        pdf.box(L, H - 46, CW, .6, LINE)
        pdf.text('%s · %s · Generado el %s (hora de Ecuador)' % (data['company']['name'], s['code'], now.strftime('%d/%m/%Y %H:%M')), L, H - 38, 7, False, GRAY)
        label = 'Página %d de %d' % (number, total_pages)
        pdf.text(label, R - pdf.width_of(label, 7), H - 38, 7, False, GRAY)
    return pdf.finish()


# ---- Ticket térmico de 80 mm -------------------------------------------------------------------------------------------------

def thermal(c, user, session_id, link, now):
    """72 mm útiles (el PPD de la TM-m30II define RP80 con 204,3 pt), margen de 1 mm y altura según el contenido: sin escalar."""
    data = collect(c, user, session_id)
    s, k, t = data['session'], data['closing'], data['totals']
    W = 72 * 72 / 25.4
    M = 1 * 72 / 25.4
    IN = W - 2 * M
    f = Flow(W, 0, 10 ** 6)  # una sola página: la altura se calcula al final

    def text(value, x, y, size=8.5, bold=False):
        f.op('text', value, x, y, size, bold)

    def center(value, size=8.5, bold=False, gap=1.32):
        for piece in f.wrap(value, IN, size):
            text(piece, M + (IN - f.width_of(piece, size, bold)) / 2, f.y, size, bold)
            f.y += size * gap

    def para(value, size=8, bold=False, indent=0):
        for piece in f.wrap(value, IN - indent, size):
            text(piece, M + indent, f.y, size, bold)
            f.y += size * 1.3

    def row(label, value, size=8.5, bold=False, indent=0):
        """Etiqueta a la izquierda (se ajusta en varias líneas) e importe alineado a la derecha en la primera línea."""
        vw = f.width_of(value, size, bold)
        pieces = f.wrap(label, IN - indent - vw - 8, size)
        for i, piece in enumerate(pieces):
            text(piece, M + indent, f.y, size, bold)
            if i == 0:
                text(value, M + IN - vw, f.y, size, bold)
            f.y += size * 1.3

    def rule(dashed=False):
        f.y += 2
        if dashed:
            x = M
            while x < M + IN:
                f.op('box', x, f.y, min(3, M + IN - x), .6)
                x += 5
        else:
            f.op('box', M, f.y, IN, .9)
        f.y += 5

    def title(value):
        rule()
        para(value.upper(), 9, True)
        f.y += 1

    f.y = 6
    logo_w = 34 * 72 / 25.4
    f.op('logo', M + (IN - logo_w) / 2, f.y, logo_w)
    f.y += logo_w * f.measure.ih / f.measure.iw + 6  # proporción real del logo original
    co = data['company']
    center(co['legal'], 9.5, True)
    center(('RUC ' + co['ruc']) if co['ruc'] else 'RUC no configurado', 8)
    if co['contact']:
        center(co['contact'], 7.5)
    rule()
    center('CIERRE DE CAJA', 9, True)
    center(s['code'], 15, True, 1.2)
    center(s['status_label'], 8.5, True)
    rule(True)
    for label, value in (('Caja', s['register']), ('Turno', s['shift'] or '—'), ('Cajero', s['cashier']), ('Apertura', _dt(s['opened_at'])),
                         ('Cierre', _dt(k['closed_at']) if k else 'En curso'), ('Confirmó', k['confirmed_name'] if k else '—')):
        row(label, value, 8)
    title('Resumen')
    row('Fondo inicial', _money(t['opening']))
    row('Ventas y cobros', _money(t['sales']))
    row('Otros ingresos', _money(t['other_in']))
    row('Total de ingresos', _money(t['income']), 9, True)
    for label, cents in (('Efectivo', t['cash']), ('Transferencias', t['transfer']), ('Depósitos', t['deposit']), ('Tarjetas', t['card']), ('Otros medios', t['others'])):
        if cents:
            row(label, _money(cents), 8, False, 8)
    row('Total de egresos', _money(t['outgo']))
    title('Efectivo del cajón')
    row('Fondo inicial', _money(t['opening']))
    row('+ Entradas en efectivo', _money(t['cash_in']))
    row('- Salidas en efectivo', _money(t['cash_out']))
    row('Efectivo esperado', _money(t['expected']), 9, True)
    if data['income'] or data['outgo']:
        title('Operaciones (%d)' % (len(data['income']) + len(data['outgo'])))
        for r in data['income'] + data['outgo']:
            sign = '-' if r['direction'] == 'egreso' else ''
            row('%s %s%s' % (r['ref'], r['method_label'], ' (anulado)' if r['voided'] else ''), sign + _money(r['amount_cents']), 8)
            detail = ' · '.join(x for x in (_dt(r['at']), r['document'], r.get('reference') or '', _bank(r.get('bank'))) if x)
            for piece in f.wrap(detail, IN - 8, 7.5, 2):
                text(piece, M + 8, f.y, 7.5)
                f.y += 7.5 * 1.28
            f.y += 1.5
    if data['transfers']:
        title('Transferencias y depósitos')
        for x in data['transfers']:
            row('%s %s' % (x['code'], x['method']), _money(x['amount']), 8)
            para('%s %s •••• %s · ref. %s · %s' % (x['bank'], x['type'].lower(), x['last4'], x['reference'], x['status']), 7.5, False, 8)
    if data['cards']:
        title('Tarjetas')
        for x in data['cards']:
            row('%s %s' % (x['ref'], x['brand']), _money(x['amount']), 8)
            para('%s · %s · %s' % (x['issuer'], x['type'], x['auth']), 7.5, False, 8)
    title('Arqueo de caja')
    if data['counts']:
        for x in data['counts']:
            row('%s %s × %d' % ('Billete' if x['kind'] == 'billete' else 'Moneda', _money(x['value_cents']), x['qty']), _money(x['subtotal_cents']), 8)
        rule(True)
    elif k:
        para('Desglose no registrado.', 8, True)
    if k:
        row('Esperado', _money(t['expected']))
        row('Contado', _money(t['counted']))
        row('Diferencia', _signed(t['difference']), 9.5, True)
        center('ESTADO: ' + _state(t['difference']).upper(), 10, True)
        if k['difference_reason']:
            para('Explicación: ' + k['difference_reason'], 7.5)
        row('Entregado', _money(t['withdrawn']), 8)
        row('Fondo reservado', _money(t['reserved']), 8)
        para('Conteo: ' + (data['counter'] or k['confirmed_name']), 7.5)
    else:
        para('Caja en curso: el arqueo se registra al cerrar.', 8)
    if data['adjustments']:
        title('Ajustes posteriores')
        for a in data['adjustments']:
            row(_dt(a['created_at']), _signed(a['amount_cents']), 8)
            para(a['reason'] + ' · ' + a['actor'], 7.5, False, 8)
    if not all(ok for _, ok in data['checks']):
        rule()
        para('REVISAR: hay totales que no cuadran.', 9, True)
    rule()
    center('ESTADO FINAL: ' + s['status_label'].upper(), 9, True)
    # Firmas.
    f.y += 26
    for role, name in (('Firma del cajero', s['cashier']), ('Firma de administración', s['reviewed_by_name'] or '')):
        f.op('box', M + 10, f.y, IN - 20, .7)
        f.y += 4
        center(role + (' · ' + name if name else ''), 7.5)
        f.y += 22
    # QR alineado a la rejilla de 203 dpi, con su zona de silencio dentro del ancho útil.
    if link:
        modules = len(list(segno.make_qr(link, error='m').matrix)) + 8
        dots = max(2, min(4, int((IN * .62) / (modules * DOT))))
        size = modules * dots * DOT
        x = round((M + (IN - size) / 2) / DOT) * DOT
        f.y = round(f.y / DOT) * DOT
        f.op('qr', link, x, f.y, size)
        f.y += size + 2
        center('Verificación interna: requiere sesión autorizada', 7.2)
    f.y += 4
    center('Generado el %s (hora de Ecuador)' % now.strftime('%d/%m/%Y %H:%M'), 7.2)
    f.y += 8
    pdf = Canvas(W, f.y, 'Cierre ' + s['code'], mono=True)
    pdf.page()
    for op in f.pages[0]:
        kind, args = op[0], op[1:]
        if kind == 'text':
            pdf.text(*args)
        elif kind == 'box':
            pdf.stream.set_color_rgb(0, 0, 0)
            pdf.stream.rectangle(args[0], pdf.h - args[1] - args[3], args[2], args[3])
            pdf.stream.fill()
        elif kind == 'logo':
            pdf.logo(*args)
        elif kind == 'qr':
            pdf.qr(*args)
    return pdf.finish()


def render(c, user, session_id, link, thermal_format=False, now=None):
    now = now or datetime.now(ECUADOR_TZ)
    return thermal(c, user, session_id, link, now) if thermal_format else a4(c, user, session_id, link, now)
