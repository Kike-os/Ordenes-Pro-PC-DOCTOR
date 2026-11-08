"""Mensajes de seguimiento para el cliente según el estado real de la orden (1.5.257), para WhatsApp o correo.

- ADI redacta el cuerpo con los datos técnicos registrados de la orden, ya depurados (sin nombre ni contacto del cliente, serie, precios ni
  credenciales: adi_reports.order_context). Debe distinguir lo confirmado de una posibilidad técnica y no inventar diagnósticos, trabajos,
  presupuestos ni fechas; los controles de adi_ai (_guard, repeticiones) avisan lo que no está respaldado.
- Sin ADI (desactivado, sin proveedor o con error), el cuerpo es la explicación del estado: nunca un texto inventado.
- Saludo con el nombre real, orden, equipo, enlace de seguimiento y firma los pone el sistema. Nada se envía desde aquí: el técnico revisa
  y edita el mensaje antes de enviarlo por la comunicación de la orden."""
import repair_status

CHANNELS = {'whatsapp': 'WhatsApp', 'correo': 'Correo electrónico'}
WORDS = {'whatsapp': 70, 'correo': 110}
NEXT = {'pendiente': 'Le informaremos cuando comience el diagnóstico.', 'diagnostico': 'Al terminar la evaluación le informaremos el resultado.',
        'reparacion': 'Le notificaremos cuando su equipo esté listo para retirar.', 'pruebas': 'Le avisaremos en cuanto el equipo esté listo para retirar.',
        'esperando_repuesto': 'Le informaremos cuando llegue el repuesto.', 'revision_recurrente': 'Le informaremos el resultado de la revisión.'}


class MessageError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def base_body(c, oid):
    """Cuerpo sin IA: la explicación pública del estado actual (y la acción que se espera del cliente, si la hay)."""
    info = repair_status.public(c, oid)
    if not info:
        raise MessageError('Orden no disponible.', 404)
    parts = ['Estado actual: %s.' % info['label'], info['text']]
    if info['action']:
        parts.append(info['action'])
    if info['estimated']:
        from datetime import date
        parts.append('Fecha estimada de entrega: %s.' % date.fromisoformat(info['estimated']).strftime('%d/%m/%Y'))
    return info, ' '.join(parts)


def _adi(c, oid, channel, info, body, note):
    """Cuerpo redactado por ADI con el contexto técnico depurado. Devuelve (cuerpo, avisos) o lanza adi_ai.AdiError."""
    import adi_ai
    import adi_reports
    ctx = adi_reports.order_context(c, oid)
    data = dict(ctx['data'])
    data['Estado actual de la orden'] = info['label']
    data['Explicación del estado para el cliente'] = info['text']
    if info['estimated']:
        data['Fecha estimada confirmada'] = info['estimated']
    instruction = ('Mensaje de seguimiento para %s. Explica el estado actual y lo que sigue, adaptado al tipo de equipo y al trabajo registrado. '
                   'Distingue lo confirmado (diagnóstico registrado) de lo que solo es una posibilidad técnica («podría», «es posible»). '
                   'No menciones precios, proveedores ni notas internas. Máximo %d palabras.') % (CHANNELS[channel], WORDS[channel])
    text = instruction + ('\nIndicación del técnico: ' + adi_ai.redact(note, ctx['names']) if note else '') + '\nBorrador base: ' + body
    result = adi_ai.professional_message(text, data)
    return result['body'], result['warnings']


def compose(c, oid, channel, note='', use_ai=True):
    """Mensaje completo para revisar y editar. Devuelve canal, asunto, cuerpo, origen ('adi' o 'plantilla') y avisos."""
    import order_followups
    import order_tracking
    if channel not in CHANNELS:
        raise MessageError('Elige WhatsApp o correo electrónico.')
    note = ' '.join(str(note or '').split())[:600]
    info, body = base_body(c, oid)
    source, warnings = 'plantilla', []
    import adi_ai
    if use_ai and not (adi_ai.enabled(c) and adi_ai.provider()):
        use_ai = False
        warnings = ['ADI no está disponible en este servidor: se usó la explicación del estado real. Revísala antes de enviar.']
    if use_ai:
        try:
            body, warnings = _adi(c, oid, channel, info, body, note)
            source = 'adi'
        except adi_ai.AdiError as error:
            warnings = ['ADI no pudo redactar el mensaje (%s). Se usó la explicación del estado; revísala antes de enviar.' % str(error).rstrip('.')]
    nxt = NEXT.get(info['code'], '')
    if nxt and nxt.lower()[:20] not in body.lower():
        body = body.rstrip() + ' ' + nxt
    link = order_tracking.active(c, oid)['url']
    o = order_followups._order(c, oid)
    subject = 'PC-DOCTOR · Orden %s · %s' % (o['code'], info['label'])
    if channel == 'correo':
        full = order_followups.ai_wrap(c, oid, 'estado', body, cost=False, tracking_url=link)['body']
    else:
        device = ' '.join(x for x in (o['brand'], o['model']) if x)
        lines = ['Hola, %s. Le saluda PC-DOCTOR.' % order_followups._first_name(o['client']), '', 'Orden %s%s' % (o['code'], ' · ' + device if device else ''),
                 body.strip(), '']
        if link:
            lines.append('Seguimiento: ' + link)
        full = '\n'.join(lines + ['PC-DOCTOR | Servicio Técnico'])
    return {'channel': channel, 'channel_label': CHANNELS[channel], 'subject': subject, 'body': full, 'source': source, 'warnings': warnings,
            'status': info['code'], 'status_label': info['label']}
