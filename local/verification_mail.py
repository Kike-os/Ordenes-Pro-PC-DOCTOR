"""Correo corporativo con un código de verificación de un solo uso.

HTML con tablas y estilos en línea (Gmail, Outlook y aplicaciones móviles), sin JavaScript, con alternativa en texto
plano. El código lo genera el servidor en cada solicitud; aquí solo se presenta. No incluye contraseñas ni claves."""
import html
import re
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from corporate import settings
from reception import public_base_url

SUBJECT = 'Tu código de verificación | PC-DOCTOR S.A.'
SENDER_NAME = 'PC-DOCTOR S.A. · Seguridad'
TITLE = 'Verifica tu correo electrónico'
LOGO_FALLBACK = 'https://ordenes-pro.ecuadorpcdoctor.com'


def logo_url():
    """El logo debe cargarse desde una dirección HTTPS pública; en entornos locales se usa la del sitio oficial."""
    base = public_base_url().rstrip('/')
    return (base if base.startswith('https://') else LOGO_FALLBACK) + '/static/logo-firma.png'


def plain(code, minutes, where, context=''):
    company = settings()
    lines = [company['name'], '', TITLE, '']
    if context:
        lines += [context, '']
    lines += ['Tu código de verificación es:', '', '    ' + code, '',
              'Ingrésalo ' + where + '. Caduca en %d minutos y solo puede usarse una vez.' % minutes, '',
              'Si no solicitaste este código, ignora este mensaje. Nadie de ' + company['name'] + ' te pedirá este código por teléfono ni por chat.',
              '', company['name'], company['website']]
    return '\n'.join(lines)


def markup(code, minutes, where, context=''):
    company = settings()
    e = html.escape
    font = "font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
    digits = ''.join('<td align="center" style="padding:0 5px;%s;font-size:34px;line-height:44px;font-weight:700;color:#143f77">%s</td>' % (font, digit) for digit in code)
    site = company['website']
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>' + e(TITLE) + '</title></head>'
            '<body style="margin:0;padding:0;background-color:#eef2f8">'
            '<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#eef2f8">Tu código caduca en %d minutos. No lo compartas con nadie.</div>' % minutes +
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#eef2f8" style="background-color:#eef2f8"><tr><td align="center" style="padding:28px 12px">'
            '<table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:560px;background-color:#ffffff;border:1px solid #d9e2ef;border-radius:14px">'
            # Encabezado: logo sobre fondo claro (se ve igual en modo oscuro) y filete con los colores corporativos.
            '<tr><td align="center" bgcolor="#ffffff" style="padding:26px 24px 14px;border-radius:14px 14px 0 0">'
            '<img src="' + e(logo_url()) + '" width="132" height="101" alt="PC-DOCTOR S.A." style="display:block;border:0;outline:none;width:132px;height:auto;max-width:132px">'
            '<div style="' + font + ';font-size:18px;line-height:24px;font-weight:700;color:#143f77;padding-top:10px">' + e(company['name']) + '</div>'
            '<div style="' + font + ';font-size:11px;line-height:16px;letter-spacing:1.4px;text-transform:uppercase;color:#68768a">' + e(company['specialty']) + '</div></td></tr>'
            '<tr><td style="padding:0 24px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            '<td height="3" bgcolor="#143f77" style="height:3px;line-height:3px;font-size:0;background-color:#143f77">&nbsp;</td>'
            '<td width="64" height="3" bgcolor="#d94049" style="width:64px;height:3px;line-height:3px;font-size:0;background-color:#d94049">&nbsp;</td></tr></table></td></tr>'
            '<tr><td align="center" style="padding:26px 28px 6px;' + font + '">'
            '<h1 style="margin:0;' + font + ';font-size:22px;line-height:30px;font-weight:700;color:#102744">' + e(TITLE) + '</h1>'
            + ('<p style="margin:10px 0 0;' + font + ';font-size:14px;line-height:21px;color:#4a5a70">' + e(context) + '</p>' if context else '') +
            '<p style="margin:10px 0 0;' + font + ';font-size:15px;line-height:23px;color:#33435a">Usa este código para continuar. Lo generamos solo para esta solicitud.</p></td></tr>'
            '<tr><td align="center" style="padding:16px 20px 8px">'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" bgcolor="#f3f7fd" style="background-color:#f3f7fd;border:1px solid #c9d8ee;border-radius:12px"><tr><td style="padding:14px 16px">'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" aria-label="Código de verificación"><tr>' + digits + '</tr></table></td></tr></table></td></tr>'
            '<tr><td align="center" style="padding:8px 28px 4px;' + font + ';font-size:14px;line-height:22px;color:#33435a">'
            'Ingrésalo ' + e(where) + '.<br><strong style="color:#102744">Caduca en %d minutos</strong> y solo puede usarse una vez.</td></tr>' % minutes +
            '<tr><td style="padding:18px 28px 6px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#fff7f7" style="background-color:#fff7f7;border-left:3px solid #d94049"><tr>'
            '<td style="padding:11px 14px;' + font + ';font-size:13px;line-height:20px;color:#4a5a70">Si no solicitaste este código, ignora este mensaje. Nadie de ' + e(company['name']) + ' te pedirá este código por teléfono ni por chat.</td></tr></table></td></tr>'
            '<tr><td align="center" style="padding:20px 28px 24px;border-top:1px solid #e3e9f1;' + font + ';font-size:12px;line-height:19px;color:#68768a">'
            '<strong style="color:#143f77">' + e(company['name']) + '</strong><br><a href="' + e(site) + '" style="color:#2359ac;text-decoration:none">' + e(re.sub(r'^https?://|/$', '', site)) + '</a><br>'
            'Mensaje automático de seguridad de Órdenes Pro. No respondas a este correo.</td></tr>'
            '</table></td></tr></table></body></html>')


def build(config, recipient, code, minutes, where, context=''):
    """Mensaje listo para entregar con el buzón del sistema ya configurado. «code» debe ser el código real de seis dígitos."""
    if not re.fullmatch(r'\d{6}', str(code)):
        raise ValueError('Código de verificación inválido.')
    message = EmailMessage()
    message['From'] = SENDER_NAME + ' <' + config['username'] + '>'
    message['To'] = recipient
    message['Subject'] = SUBJECT
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid(domain=config['username'].split('@')[-1])
    message['Auto-Submitted'] = 'auto-generated'
    message.set_content(plain(code, minutes, where, context))
    message.add_alternative(markup(code, minutes, where, context), subtype='html')
    return message
