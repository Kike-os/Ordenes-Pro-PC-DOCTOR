"""Document prompts and server-side checks shared by private customer links."""
import html
import re
import secrets
import time

import reception

ASSETS = '<link rel="stylesheet" href="/static/public-identity.css"><script defer src="/static/public-identity.js"></script>'
MISMATCH = 'Los dígitos ingresados no coinciden con el documento registrado. Verifica tu información e inténtalo nuevamente'
LABELS = {'cedula': 'cédula registrada', 'ruc': 'RUC registrado', 'pasaporte': 'pasaporte registrado'}
ICONS = {
    'shield': 'M12 22s7-3 7-9V5l-7-3-7 3v8c0 6 7 9 7 9Zm-3-10 2 2 4-4',
    'id': 'M3 5h18v14H3zM7 15c0-3 6-3 6 0m-3-5h.01M16 9h2m-2 5h2',
    'ruc': 'M3 21h18M6 21V3h12v18M10 7h.01M14 7h.01M10 11h.01M14 11h.01M10 15h.01M14 15h.01M10 21v-3h4v3',
    'pasaporte': 'M5 3h14v18H5zM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm-4 4h8',
}


def kind(identification, stored=''):
    if stored in LABELS:
        return stored
    number = re.sub(r'\s+', '', str(identification or ''))
    candidate = {10: 'cedula', 13: 'ruc'}.get(len(number))
    return candidate if candidate and not reception.document_error(number, candidate) else ''


def digits(identification):
    return re.sub(r'[^0-9]', '', str(identification or ''))


def matches(value, identification, minimum=4):
    number = digits(identification)
    return bool(len(number) >= minimum and isinstance(value, str) and re.fullmatch(r'[0-9]{4}', value)
                and secrets.compare_digest(number[-4:], value))


def instruction(document_kind):
    label = LABELS.get(document_kind, 'identificación registrada')
    prefix = 'Si tu pasaporte incluye letras, usa solo sus números.' if document_kind == 'pasaporte' else ''
    return 'Ingresa los últimos 4 dígitos de tu ' + label + ('. ' + prefix if prefix else '')


def _icon(name):
    return ('<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="%s"/></svg>') % ICONS[name]


def heading(step=1, total=2):
    progress = ''.join('<i%s></i>' % (' class="active"' if pos <= step else '') for pos in range(1, total + 1))
    return ('<div class="public-identity-heading"><span class="public-identity-shield">%s</span><div><strong>Comprueba tu identidad</strong>'
            '<small>Paso %d de %d</small></div><span class="public-identity-progress" aria-hidden="true">%s</span></div>') % (_icon('shield'), step, total, progress)


def fields(document_kind='', *, field='last4', total=2, full=False):
    label = ('Ingresa el número de tu ' + LABELS.get(document_kind, 'identificación registrada')
             if full else instruction(document_kind))
    attributes = 'maxlength="20"' if full else 'inputmode="numeric" pattern="[0-9]{4}" minlength="4" maxlength="4"'
    if full and document_kind in ('cedula', 'ruc'):
        attributes += ' inputmode="numeric"'
    return (f'<div class="public-identity-panel" data-public-identity>{heading(total=total)}'
            f'<label>{_icon(document_kind if document_kind in ("ruc", "pasaporte") else "id")}<span>{html.escape(label)}</span>'
            f'<input class="public-identity-value" name="{html.escape(field, quote=True)}" {attributes} autocomplete="off" spellcheck="false" required></label>'
            '<p class="public-identity-status" role="status"></p></div>')


SUCCESS = '<p class="public-identity-success" role="status">' + _icon('shield') + 'Identidad verificada correctamente</p>'


def confirm(page):
    """Insert confirmation into the next step after a successful server check."""
    return re.sub(r'(<main\b[^>]*>)', lambda match: match[0] + SUCCESS, page, count=1)


def record(c, module, matched, entity_id):
    action = 'public_identity_' + module + ('_verified' if matched else '_failed')
    c.execute('INSERT INTO audit(user_id,action,entity_id,created_at) VALUES (NULL,?,?,?)',
              (action, entity_id, int(time.time())))
