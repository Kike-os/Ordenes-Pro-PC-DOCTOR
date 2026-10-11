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
    row=c.execute("""SELECT o.code,o.id,o.status,s.label status_label,o.received_at,o.created_at,o.updated_at,d.category,d.type,d.brand,d.model
        FROM order_tracking_links t JOIN orders o ON o.id=t.order_id JOIN devices d ON d.id=o.device_id JOIN statuses s ON s.code=o.status
        WHERE t.token=? AND t.revoked_at=''""",(token,)).fetchone()
    if not row:return None
    def stamp(value):
        try:return datetime.fromisoformat(value).astimezone(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')
        except (TypeError,ValueError):return ''
    received=stamp(row['received_at']) or datetime.fromtimestamp(row['created_at'],ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')
    kind=row['category'] or row['type']
    return {'code':row['code'] or 'OP-%05d'%row['id'],'status':row['status'],'status_label':row['status_label'],'received':received,'updated':stamp(row['updated_at']),
            'device':' · '.join(filter(None,[DEVICE_TYPES.get(kind,''),' '.join(filter(None,[row['brand'],row['model']]))]))}


HEAD='<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta name="robots" content="noindex,nofollow"><title>%s | PC-DOCTOR S.A.</title><link rel="icon" href="/favicon.ico?v=2" sizes="48x48"><link rel="stylesheet" href="/static/tracking.css"></head><body><main class="tracking-page"><header><img src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="150"><p>%s</p></header>'


def public_page(data):
    company=settings();e=html.escape
    current=max(0,next((i for i,phase in enumerate(PHASES) if data['status'] in phase[1]),0))
    steps=''.join('<li data-state="%s"%s><span></span>%s</li>'%('done' if i<current or data['status']=='entregado' else 'current' if i==current else 'pending',' aria-current="step"' if i==current else '',e(label)) for i,(label,_) in enumerate(PHASES))
    rows=''.join('<div><dt>%s</dt><dd>%s</dd></div>'%(e(label),e(value)) for label,value in (('Equipo',data['device']),('Fecha de recepción',data['received']),('Última actualización',data['updated'])) if value)
    return (HEAD%('Seguimiento de reparación',e(company['specialty']))+'<section class="tracking-card"><small>ORDEN DE SERVICIO</small><h1>%s</h1><p class="tracking-state" data-status="%s">%s</p><ol class="tracking-steps" aria-label="Avance de la reparación">%s</ol><dl>%s</dl></section>'%(e(data['code']),e(data['status']),e(data['status_label']),steps,rows)
        +'<footer><p>Para más información comunícate con el taller e indica tu número de orden.</p><p>WhatsApp: %s</p><p class="tracking-note">Esta página muestra solo el estado de la reparación. No contiene datos personales.</p></footer></main></body></html>'%e(company['whatsapp']))


def missing_page():
    company=settings();e=html.escape
    return HEAD%('Enlace no disponible',e(company['specialty']))+'<section class="tracking-card"><h1>Enlace no disponible</h1><p>Este enlace de seguimiento no existe o fue desactivado. Comunícate con el taller para consultar tu reparación.</p></section><footer><p>WhatsApp: %s</p></footer></main></body></html>'%e(company['whatsapp'])
