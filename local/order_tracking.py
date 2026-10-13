"""Seguimiento público de una orden mediante un enlace aleatorio y revocable.

El enlace no contiene datos de la orden ni del cliente. La página pública muestra solo número de orden, estado,
equipo (tipo, marca y modelo) y fechas; nunca nombre, identificación, teléfono, serie, falla, notas ni importes.
El `qr_url` histórico de cada orden no se modifica.
"""
from datetime import datetime
import html
import re
import secrets

from corporate import settings
from reception import DEVICE_TYPES,ECUADOR_TZ,public_base_url

TOKEN=re.compile(r'[A-Za-z0-9_-]{22}')
PHASES=(('Recibido',('pendiente',)),('En proceso',('reparacion','esperando_cliente','presupuesto')),('Listo',('listo','espera_entrega')),('Entregado',('entregado',)))


def url(token):
    return public_base_url()+'/s/'+token


def active(c,oid):
    row=c.execute("SELECT token,created_at FROM order_tracking_links WHERE order_id=? AND revoked_at='' ORDER BY id DESC LIMIT 1",(oid,)).fetchone()
    return {'active':True,'url':url(row['token']),'created_at':row['created_at']} if row else {'active':False,'url':'','created_at':''}


def create(c,oid,actor,now):
    """Genera un enlace nuevo; el anterior, si existía, queda revocado."""
    revoke(c,oid,actor,now)
    token=secrets.token_urlsafe(16)  # 128 bits aleatorios
    c.execute('INSERT INTO order_tracking_links(order_id,token,created_at,created_by) VALUES (?,?,?,?)',(oid,token,now.isoformat(timespec='seconds'),actor))
    return url(token)


def revoke(c,oid,actor,now):
    return c.execute("UPDATE order_tracking_links SET revoked_at=?,revoked_by=? WHERE order_id=? AND revoked_at=''",(now.isoformat(timespec='seconds'),actor,oid)).rowcount


def lookup(c,token):
    if not TOKEN.fullmatch(token or ''):return None
    row=c.execute("""SELECT o.code,o.id,o.status,s.label status_label,o.received_at,o.created_at,o.updated_at,COALESCE(NULLIF(d.kind,''),d.category) category,d.type,d.brand,d.model
        FROM order_tracking_links t JOIN orders o ON o.id=t.order_id JOIN devices d ON d.id=o.device_id JOIN statuses s ON s.code=o.status
        WHERE t.token=? AND t.revoked_at=''""",(token,)).fetchone()
    if not row:return None
    def stamp(value):
        try:return datetime.fromisoformat(value).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')
        except (TypeError,ValueError):return ''
    received=stamp(row['received_at']) or datetime.fromtimestamp(row['created_at'],ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')
    kind=row['category'] or row['type']
    return {'id':row['id'],'code':row['code'] or 'OP-%05d'%row['id'],'status':row['status'],'status_label':row['status_label'],'received':received,'updated':stamp(row['updated_at']),
            'device':' · '.join(filter(None,[DEVICE_TYPES.get(kind,''),' '.join(filter(None,[row['brand'],row['model']]))]))}


HEAD='<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta name="robots" content="noindex,nofollow"><title>%s | PC-DOCTOR S.A.</title><link rel="icon" href="/favicon.ico?v=2" sizes="48x48"><link rel="stylesheet" href="/static/tracking.css"></head><body><main class="tracking-page"><header><img src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="150"><p>%s</p></header>'


def public_page(data,token=''):
    return card_page(data,'/s/'+token+'/qr.svg' if token else '',True)


# Tarjeta Digital de Seguimiento Técnico: ticket de dos secciones (datos de la orden arriba; QR y código de barras abajo).
# Las etapas salen del estado real de la orden; una etapa futura nunca se marca como completada.
STAGES=(('Recepción',('pendiente',)),('Diagnóstico y reparación',('reparacion','esperando_cliente','presupuesto')),('Listo para retiro',('listo','espera_entrega')),('Entrega',('entregado',)))
CARD_HEAD='<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta name="robots" content="noindex,nofollow">%s<title>Seguimiento de reparación %s | PC-DOCTOR S.A.</title><link rel="icon" href="/favicon.ico?v=2" sizes="48x48"><link rel="stylesheet" href="/static/ticket.css"><script defer src="/static/ticket.js"></script></head><body class="ticket-page"><main>'


def card(data,qr_src,public):
    """Fragmento HTML de la tarjeta. `data` trae solo datos reales; lo que falta se muestra como pendiente, nunca inventado."""
    import barcode128
    company=settings();e=html.escape
    current=max(0,next((i for i,stage in enumerate(STAGES) if data['status'] in stage[1]),0));done=data['status']=='entregado'
    steps=''.join('<li data-state="%s"%s><i aria-hidden="true"></i><span>%s</span></li>'%('done' if i<current or done else 'current' if i==current else 'pending',' aria-current="step"' if i==current and not done else '',e(label)) for i,(label,_) in enumerate(STAGES))
    progress=100 if done else round(current/(len(STAGES)-1)*100)
    facts=[] if public else [('Cliente',data.get('client') or 'No registrado')]
    facts+=[('Equipo',data.get('device') or 'No registrado'),('Fecha de ingreso',data.get('received') or 'No registrada'),('Última actualización',data.get('updated') or 'Sin movimientos')]
    if not public:facts.append(('Técnico responsable',data.get('responsible') or 'Sin asignar'))
    rows=''.join('<div><dt>%s</dt><dd>%s</dd></div>'%(e(label),e(value)) for label,value in facts)
    code=data['code']
    try:bars=barcode128.svg(code,color='#0b1526',background='#ffffff')
    except barcode128.BarcodeError:bars=''
    qr='<img class="ticket-qr" src="%s" width="132" height="132" alt="Código QR del seguimiento de la orden %s">'%(e(qr_src),e(code)) if qr_src else '<p class="ticket-noqr">Sin enlace público activo. Genéralo desde la orden para obtener el código QR.</p>'
    return ('<article class="ticket" data-status="%s"><section class="ticket-top" aria-label="Datos de la orden">'
            '<header class="ticket-head"><img class="ticket-logo" src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="120"><div><small>%s</small><h1>Seguimiento de reparación</h1></div></header>'
            '<div class="ticket-order"><div><small>Orden de servicio</small><strong>%s</strong></div><span class="ticket-state" data-status="%s">%s</span></div>'
            '<div class="ticket-progress" role="img" aria-label="Avance: %s"><span data-progress="%d"></span></div><ol class="ticket-steps">%s</ol><dl class="ticket-facts">%s</dl></section>'
            '<div class="ticket-cut" aria-hidden="true"></div>'
            '<section class="ticket-bottom" aria-label="Código de seguimiento"><div class="ticket-verify"><h2>Código de seguimiento</h2><p>%s</p></div>%s'
            '<div class="ticket-barcode">%s<span>%s</span></div><footer><strong>%s</strong><span>%s</span><span>WhatsApp %s</span></footer></section></article>'
            )%(e(data['status']),e(company['name']),e(code),e(data['status']),e(data['status_label']),e(STAGES[current][0]),progress,steps,rows,
               'Escanea el código QR para consultar el estado actualizado de la reparación. El código de barras identifica esta orden en el taller.',qr,bars,e(code),e(company['name']),e(company['specialty']),e(company['whatsapp']))


def card_page(data,qr_src,public):
    e=html.escape
    actions='<div class="ticket-actions"><button type="button" data-print>Imprimir o guardar como PDF</button>'+('' if public else '<a href="/#orders?id=%d">Volver a la orden</a>'%data['id'])+'</div>'
    note='<p class="ticket-note">Esta página muestra solo el estado de la reparación. No contiene datos personales.</p>' if public else '<p class="ticket-note">Vista interna con datos del cliente: no la compartas. Para el cliente usa el enlace público de seguimiento.</p>'
    return CARD_HEAD%('<meta http-equiv="refresh" content="180">' if public else '',e(data['code']))+card(data,qr_src,public)+actions+note+'</main></body></html>'


def staff_data(c,oid):
    """Datos de la tarjeta para el personal (incluye cliente y técnico). Solo con sesión."""
    row=c.execute("""SELECT o.id,o.code,o.status,s.label status_label,o.received_at,o.created_at,o.updated_at,COALESCE(NULLIF(d.kind,''),d.category) category,d.type,d.brand,d.model,cl.name client,
        COALESCE((SELECT name FROM users WHERE id=o.assigned_to),'') responsible FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id JOIN statuses s ON s.code=o.status WHERE o.id=?""",(oid,)).fetchone()
    if not row:return None
    def stamp(value):
        try:return datetime.fromisoformat(value).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')
        except (TypeError,ValueError):return ''
    kind=row['category'] or row['type']
    return {'id':row['id'],'code':row['code'] or 'OP-%05d'%row['id'],'status':row['status'],'status_label':row['status_label'],'received':stamp(row['received_at']) or datetime.fromtimestamp(row['created_at'],ECUADOR_TZ).strftime('%d/%m/%Y %H:%M'),
            'updated':stamp(row['updated_at']),'device':' · '.join(filter(None,[DEVICE_TYPES.get(kind,''),' '.join(filter(None,[row['brand'],row['model']]))])),'client':row['client'],'responsible':row['responsible']}


def missing_page():
    company=settings();e=html.escape
    return HEAD%('Enlace no disponible',e(company['specialty']))+'<section class="tracking-card"><h1>Enlace no disponible</h1><p>Este enlace de seguimiento no existe o fue desactivado. Comunícate con el taller para consultar tu reparación.</p></section><footer><p>WhatsApp: %s</p></footer></main></body></html>'%e(company['whatsapp'])
