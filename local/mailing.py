"""Correos institucionales: una sola plantilla, la firma autorizada, la revisión de ADI y la copia exacta de lo enviado.

- La estructura visual (alineación, márgenes, tablas) la da la plantilla HTML; nunca la inteligencia artificial.
- ADI revisa la redacción de los párrafos. Los datos (códigos, importes, fechas, enlaces, correos, líneas «Dato: valor» y el
  saludo con el nombre) viajan enmascarados y se restituyen tal cual; si la respuesta no los conserva, se usa la plantilla.
- Si la IA no está disponible, tarda o falla, el correo sale con el texto de la plantilla ya revisada y así queda registrado."""
import hashlib
import html as html_lib
import re
import threading

FACT = re.compile(r'^([^:\n]{2,42}):[ \t]+(\S.*)$')
URL = re.compile(r'https?://[^\s<>"\']+')
SHIELD = re.compile(r'https?://[^\s<>"\']+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|PCD-\d{8}-\d{3,}(?:-[EP]\d+)*|OP-\d+|EQ-\d+|\$\s?\d[\d.,]*|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{1,2}:\d{2}\b|\+?\d[\d ]{6,}\d|«[^»\n]{1,80}»')
MARK = re.compile(r'⟦(\d+)⟧')
REVIEW_SECONDS = 9
SYSTEM = ("Eres ADI, correctora de los correos institucionales de PC-DOCTOR S.A., un taller de servicio técnico de computadoras en Ecuador. "
          "Recibes párrafos numerados de un correo para un cliente. Corrige ortografía, tildes, puntuación, mayúsculas y gramática, y mejora la redacción "
          "para que sea formal, clara y cordial, con trato de usted. No cambies el significado ni añadas o quites información, promesas, precios, plazos, saludos o despedidas. "
          "Conserva cada marcador con la forma ⟦n⟧ exactamente como está y en el mismo párrafo. Devuelve únicamente los mismos párrafos, cada uno con su número entre corchetes al inicio.")


def blocks(body):
    """Bloques del texto: saludo, párrafos, tablas de datos («Dato: valor»), listas, enlaces y cierre."""
    result = []
    for chunk in re.split(r'\n\s*\n', str(body or '').strip()):
        lines = [line.rstrip() for line in chunk.split('\n') if line.strip()]
        if not lines:
            continue
        if len(lines) == 1 and URL.fullmatch(lines[0].strip()):
            result.append(('link', lines[0].strip()))
        elif len(lines) >= 2 and all(FACT.match(line) and not URL.match(line.strip()) for line in lines):
            result.append(('facts', [FACT.match(line).groups() for line in lines]))
        elif all(re.match(r'\s*- \S', line) for line in lines):
            result.append(('list', [re.sub(r'^\s*- ', '', line) for line in lines]))
        else:
            result.append(('text', '\n'.join(lines)))
    # El saludo (primera línea breve terminada en dos puntos o coma) y el cierre («Atentamente» en adelante) no son prosa revisable.
    closing = next((index for index, (kind, value) in enumerate(result) if kind == 'text' and re.match(r'(Atentamente|Cordialmente|Saludos cordiales)\b', value)), len(result))
    tagged = []
    for index, (kind, value) in enumerate(result):
        if kind == 'text' and index == 0 and len(value) <= 90 and '\n' not in value and value.rstrip().endswith((':', ',')):
            kind = 'greeting'
        elif index >= closing:
            kind = 'closing'
        tagged.append((kind, value))
    return tagged


def _shield(text):
    tokens = []

    def keep(match):
        tokens.append(match.group(0))
        return '⟦%d⟧' % len(tokens)
    return SHIELD.sub(keep, text), tokens


def review(c, body, now):
    """Texto final y si ADI lo revisó de verdad: ('…', 'revisado' | 'plantilla'). Nunca lanza errores hacia el envío."""
    try:
        import adi_ai
        if not adi_ai.provider() or not adi_ai.enabled(c) or not adi_ai.correction(c).get('mail_review', True):
            return body, 'plantilla'
        parts = blocks(body)
        prose = [(index, value) for index, (kind, value) in enumerate(parts) if kind == 'text' and len(value) >= 25]
        if not prose:
            return body, 'plantilla'
        shielded = [_shield(value) for _, value in prose]
        request = '\n'.join('[%d] %s' % (number, text.replace('\n', ' ')) for number, (text, _) in enumerate(shielded, 1))
        key = hashlib.sha256((SYSTEM + '\n' + request).encode()).hexdigest()
        row = c.execute('SELECT reviewed FROM mail_review_cache WHERE hash=?', (key,)).fetchone()
        answer = row['reviewed'] if row else None
        if answer is None:
            # La consulta puede tardar: se cierra antes la transacción y se espera como mucho unos segundos.
            c.commit()
            box = {}

            def ask():
                try:
                    box['text'] = adi_ai._complete(SYSTEM, request)[0]
                except Exception as error:  # proveedor caído, límite, clave inválida…
                    box['error'] = type(error).__name__
            worker = threading.Thread(target=ask, daemon=True, name='mail-review')
            worker.start()
            worker.join(REVIEW_SECONDS)
            answer = box.get('text')
            if not answer:
                print('mail-review', box.get('error', 'timeout'), flush=True)
                return body, 'plantilla'
        pieces = re.split(r'(?m)^\s*\[(\d+)\]\s*', answer.strip())
        found = {int(pieces[i]): pieces[i + 1].strip() for i in range(1, len(pieces) - 1, 2)}
        if sorted(found) != list(range(1, len(prose) + 1)):
            return body, 'plantilla'
        final = list(parts)
        for number, ((index, original), (text, tokens)) in enumerate(zip(prose, shielded), 1):
            fixed = found[number]
            # Los datos deben volver intactos: mismos marcadores, una vez cada uno; y el párrafo no puede crecer o encogerse en exceso.
            if sorted(MARK.findall(fixed)) != sorted(str(n) for n in range(1, len(tokens) + 1)) or not 0.5 <= len(fixed) / max(1, len(text)) <= 1.8 or '⟦' in MARK.sub('', fixed):
                return body, 'plantilla'
            final[index] = ('text', MARK.sub(lambda match: tokens[int(match.group(1)) - 1], fixed))
        if row is None:
            c.execute('INSERT OR REPLACE INTO mail_review_cache(hash,reviewed,created_at) VALUES (?,?,?)', (key, answer, now.isoformat(timespec='seconds')))
        return join(final), 'revisado'
    except Exception as error:
        print('mail-review', type(error).__name__, flush=True)
        return body, 'plantilla'


def join(parts):
    """Texto plano a partir de los bloques (misma forma que entienden `blocks` y la plantilla)."""
    out = []
    for kind, value in parts:
        if kind == 'facts':
            out.append('\n'.join('%s: %s' % pair for pair in value))
        elif kind == 'list':
            out.append('\n'.join('- ' + item for item in value))
        else:
            out.append(value)
    return '\n\n'.join(out)


FONT = "font-family:Arial,Helvetica,sans-serif;"


def html(body, title, signature_html='', quoted_html=''):
    """Documento HTML institucional: encabezado textual (sin logotipo), contenido alineado, tablas de datos y firma al final.
    Tablas y estilos en línea para Gmail, Outlook y clientes móviles; en pantallas pequeñas el texto justificado pasa a la izquierda."""
    e = lambda value: html_lib.escape(str(value), quote=True)
    rows = []
    parts = blocks(body)
    if signature_html:
        # La firma institucional sustituye a las líneas de despedida escritas a mano: se conserva solo «Atentamente,».
        kept, closed = [], False
        for kind, value in parts:
            if kind == 'closing':
                if not closed:
                    kept.append(('closing', value.split('\n')[0]))
                    closed = True
                continue
            kept.append((kind, value))
        parts = kept
    for kind, value in parts:
        if kind == 'facts':
            cells = ''.join('<tr><td valign="top" width="38%%" style="padding:8px 12px 8px 14px;border-bottom:1px solid #e6ebf2;%sfont-size:13px;line-height:19px;color:#5b6b82;">%s</td>'
                            '<td valign="top" style="padding:8px 14px 8px 0;border-bottom:1px solid #e6ebf2;%sfont-size:14px;line-height:19px;font-weight:bold;color:#14233b;">%s</td></tr>' % (FONT, e(label), FONT, e(text)) for label, text in value)
            rows.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%%" bgcolor="#f6f8fb" style="margin:0 0 16px;background-color:#f6f8fb;border:1px solid #e0e6ef;border-collapse:separate;">%s</table>' % cells)
        elif kind == 'list':
            rows.append('<ul style="margin:0 0 16px;padding:0 0 0 20px;%sfont-size:14px;line-height:22px;color:#263445;">%s</ul>' % (FONT, ''.join('<li style="margin:0 0 4px;">%s</li>' % e(item) for item in value)))
        elif kind == 'link':
            rows.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:2px 0 8px;"><tr><td bgcolor="#1d5fb0" style="background-color:#1d5fb0;border-radius:6px;"><a href="%s" style="display:inline-block;padding:11px 22px;%sfont-size:14px;font-weight:bold;color:#ffffff;text-decoration:none;">Abrir enlace seguro</a></td></tr></table>'
                        '<p style="margin:0 0 16px;%sfont-size:12px;line-height:18px;color:#5b6b82;word-break:break-all;">%s</p>' % (e(value), FONT, FONT, e(value)))
        else:
            text = '<br>'.join(e(line) for line in value.split('\n'))
            text = re.sub(r'(https?://[^\s<>&]+)', r'<a href="\1" style="color:#1d5fb0;">\1</a>', text)
            long = kind == 'text' and len(value) > 90
            weight = 'font-weight:bold;' if kind == 'greeting' else ''
            rows.append('<p %sstyle="margin:0 0 16px;%sfont-size:14px;line-height:22px;color:#263445;text-align:%s;%s">%s</p>' % ('class="op-j" ' if long else '', FONT, 'justify' if long else 'left', weight, text))
    # La firma conserva su formato; en pantallas estrechas se desplaza dentro de su propio bloque en lugar de ensanchar el mensaje.
    signature = '<tr><td class="op-pad" style="padding:4px 32px 24px;"><div style="max-width:100%%;overflow-x:auto;">%s</div></td></tr>' % signature_html if signature_html else ''
    quoted = '<tr><td class="op-pad" style="padding:0 32px 22px;">%s</td></tr>' % quoted_html if quoted_html else ''
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>%s</title>'
            '<style>@media only screen and (max-width:480px){.op-j{text-align:left!important}.op-pad{padding-left:18px!important;padding-right:18px!important}}</style></head>'
            '<body style="margin:0;padding:0;background-color:#f2f4f8;">'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%%" bgcolor="#f2f4f8" style="background-color:#f2f4f8;"><tr><td align="center" style="padding:24px 12px;">'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" bgcolor="#ffffff" style="width:100%%;max-width:600px;background-color:#ffffff;border:1px solid #dfe5ee;">'
            '<tr><td class="op-pad" style="padding:22px 32px 16px;border-bottom:3px solid #1d5fb0;"><div style="%sfont-size:12px;line-height:16px;letter-spacing:2px;font-weight:bold;color:#1d5fb0;">PC-DOCTOR S.A.</div>'
            '<div style="%sfont-size:20px;line-height:27px;font-weight:bold;color:#14233b;margin-top:4px;">%s</div></td></tr>'
            '<tr><td class="op-pad" style="padding:24px 32px 6px;">%s</td></tr>%s%s'
            '<tr><td class="op-pad" style="padding:14px 32px;border-top:1px solid #e6ebf2;%sfont-size:11px;line-height:16px;color:#7a8799;">Mensaje enviado por Órdenes Pro, el sistema de gestión técnica de PC-DOCTOR S.A.</td></tr>'
            '</table></td></tr></table></body></html>') % (e(title), FONT, FONT, e(title), ''.join(rows), signature, quoted, FONT)


def archive(c, kind, order_id, recipient, subject, message, adi, actor, now, attachments=(), private=()):
    """Guarda la copia exacta del mensaje preparado. Los enlaces privados de un solo uso se omiten de la copia (dan acceso a actuar por el cliente)."""
    plain = message.get_body(('plain',))
    rich = message.get_body(('html',))
    text, page = (plain.get_content() if plain else ''), (rich.get_content() if rich else '')
    for secret in private:
        if secret:
            text = text.replace(secret, '[enlace privado omitido en la copia]')
            page = page.replace(html_lib.escape(secret, quote=True), '#').replace(secret, '[enlace privado omitido en la copia]')
    return c.execute('INSERT INTO mail_archive(kind,order_id,recipient,subject,body_text,body_html,attachments,adi,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                     (kind, order_id, recipient, str(message['Subject'] or subject), text, page, ', '.join(attachments), adi, actor, now.isoformat(timespec='seconds'))).lastrowid


def mark(c, archive_id, status, detail='', message_id='', now=None):
    c.execute('UPDATE mail_archive SET status=?,detail=?,message_id=?,sent_at=? WHERE id=?', (status, str(detail)[:300], message_id, now.isoformat(timespec='seconds') if now and status == 'enviado' else '', archive_id))


LABELS = {'receipt': 'Comprobante de recepción', 'client_authorization': 'Autorización de servicio', 'authorization_notice': 'Aviso interno de autorización', 'quote': 'Presupuesto', 'payment_receipt': 'Recibo de pago', 'stay': 'Aviso de permanencia',
          'maintenance': 'Recordatorio de mantenimiento', 'appointment': 'Cita técnica', 'manual': 'Mensaje del personal'}
STATUS = {'preparado': 'Preparado', 'enviado': 'Enviado', 'error': 'Error de envío'}


def history(c, order_id):
    """Correos de la orden, del más reciente al más antiguo. «Enviado» significa que el servidor de correo aceptó el mensaje."""
    rows = [dict(r) for r in c.execute('SELECT id,kind,recipient,subject,attachments,status,adi,detail,created_at,sent_at FROM mail_archive WHERE order_id=? ORDER BY id DESC LIMIT 100', (order_id,))]
    for row in rows:
        row['kind_label'] = LABELS.get(row['kind'], 'Notificación')
        row['status_label'] = STATUS[row['status']]
    return rows
