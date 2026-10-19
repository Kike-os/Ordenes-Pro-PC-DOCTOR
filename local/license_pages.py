"""Páginas públicas de la entrega de licencias (enlace privado): identificación, código de acceso y tarjeta privada con credenciales.
Se generan en el servidor, sin scripts. La tarjeta pública (sin credenciales) la ve administración en el panel."""
import html
from datetime import date,datetime

e=html.escape


def _shell(title,body):
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta name="robots" content="noindex,nofollow">'
            '<title>%s | PC-DOCTOR S.A.</title><link rel="icon" href="/favicon.ico?v=2" sizes="48x48"><link rel="stylesheet" href="/static/tracking.css"><link rel="stylesheet" href="/static/licencias.css"></head>'
            '<body><main class="tracking-page license-page"><header><img src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="150"><p>Licencias digitales originales</p></header>%s'
            '<footer><p>WhatsApp: +593 98 746 0591 · licencias-orig@ecuadorpcdoctor.com</p><p class="tracking-note">Enlace personal e intransferible. No lo reenvíe.</p></footer></main></body></html>') % (e(title),body)


def missing_page():
    return _shell('Enlace no disponible','<section class="tracking-card"><h1>Enlace no disponible</h1><p>Este enlace de entrega no existe, venció o fue reemplazado. Comuníquese con PC-DOCTOR S.A. para recibir uno nuevo.</p></section>')


def _form(token,step,inner,button,error=''):
    return ('<form class="license-form" method="post" action="/licencias/%s" autocomplete="off"><input type="hidden" name="step" value="%s">%s%s<button class="license-primary" type="submit">%s</button></form>'
            % (e(token),e(step),'<p class="license-error" role="alert">%s</p>' % e(error) if error else '',inner,e(button)))


def identify_page(token,error=''):
    inner=('<p class="license-step">Paso 1 de 2 · Compruebe su identidad</p><label for="identification">Número de cédula, RUC o pasaporte del titular de la compra</label>'
           '<input id="identification" name="identification" maxlength="20" required autofocus spellcheck="false">')
    return _shell('Entrega de licencias','<section class="tracking-card license-card-box"><small>ENTREGA SEGURA</small><h1>Sus licencias digitales</h1><p>Para proteger sus credenciales, confirme su identidad. Le enviaremos un código de un solo uso a su correo registrado.</p>%s</section>'
                  % _form(token,'identify',inner,'Enviar código',error))


def code_page(token,minutes,error=''):
    inner=('<p class="license-step">Paso 2 de 2 · Código de acceso</p><p class="license-notice" role="status">Si la identificación coincide con la registrada, enviamos un código de 6 dígitos a su correo. Caduca en %d minutos.</p>'
           '<label for="code">Código de 6 dígitos</label><input id="code" name="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required autofocus autocomplete="one-time-code">') % minutes
    return _shell('Entrega de licencias','<section class="tracking-card license-card-box"><h1>Código de acceso</h1>%s<p class="license-hint"><a href="/licencias/%s">Volver a empezar</a> · Si no recibe el código, comuníquese con PC-DOCTOR S.A.</p></section>'
                  % (_form(token,'verify',inner,'Ver mis licencias',error),e(token)))


def _day(value):
    if not value:return ''
    try:return (datetime.fromisoformat(value) if 'T' in value else datetime.combine(date.fromisoformat(value),datetime.min.time())).strftime('%d/%m/%Y')
    except ValueError:return e(value)


def card_page(token,card):
    """Tarjeta privada: logo de PC-DOCTOR, logo de cada producto, datos de la licencia y sus credenciales."""
    blocks=[]
    for item in card['items']:
        logo='<img class="license-product-logo" src="/licencias/%s/logo/%d" alt="Logo de %s">' % (e(token),item['product_id'],e(item['product'])) if item['has_logo'] else '<span class="license-product-logo license-product-mark" aria-hidden="true">%s</span>' % e(item['product'][:1])
        facts=[('Tipo',item['kind'])]+[(label,value) for label,value in (('Edición',item['edition']),('Tipo de licencia',item['license_type']),('Fabricante',item['manufacturer']),('Versión',item['version']),
              ('Duración',item['term']),('Dispositivos autorizados',str(item['devices']) if item['devices'] else ''),('Activación',_day(item['activated_at'])),('Vencimiento',_day(item['expires_at']) or 'Según el fabricante')) if value]
        creds=''.join('<div class="license-credential"><dt>%s</dt><dd><code>%s</code></dd></div>' % (e(c['label']),e(c['value'])) for c in item.get('credentials',[]))
        blocks.append('<article class="license-card"><header>%s<div><strong>%s</strong><small>%s</small></div></header><dl class="license-facts">%s</dl>%s</article>'
                      % (logo,e(item['product']),e(item['unit_code']),''.join('<div><dt>%s</dt><dd>%s</dd></div>' % (e(a),e(b)) for a,b in facts),('<dl class="license-credentials">%s</dl>' % creds) if creds else ''))
    head=('<section class="tracking-card license-card-box"><small>TARJETA DE LICENCIAS · VERSIÓN PRIVADA</small><h1>%s</h1><p>Orden %s · Entregada el %s</p>'
          '<p class="license-warning">Guarde estas credenciales en un lugar seguro. Por seguridad, el código de acceso ya no sirve: para volver a consultarlas solicite uno nuevo desde este enlace mientras esté vigente.</p>%s'
          '<p class="license-contact">PC-DOCTOR S.A. · %s · %s</p></section>') % (e(card['client']),e(card['order']),_day(card['delivered_at']),''.join(blocks),e(card['contact']['phone']),e(card['contact']['email']))
    return _shell('Sus licencias',head)
