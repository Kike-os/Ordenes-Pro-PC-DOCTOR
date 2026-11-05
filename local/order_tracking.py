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
PHASES=(('Recibido',('pendiente',)),('En proceso',('reparacion','esperando_cliente','presupuesto','revision_recurrente')),('Listo',('listo','espera_entrega')),('Entregado',('entregado',)))


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
    try:
        import order_followups
        updates=[dict(u,at=stamp(u['at'])) for u in order_followups.public_updates(c,row['id'])]
    except Exception:
        updates=[]  # base anterior al centro de seguimiento
    try:
        import order_evidence
        files=order_evidence.public_files(c,row['id'])
    except Exception:
        files=[]  # base anterior a las evidencias por partes
    try:
        import order_part_requests
        parts=order_part_requests.public(c,row['id'])
    except Exception:
        parts=[]  # base anterior al seguimiento de repuestos
    return {'id':row['id'],'code':row['code'] or 'OP-%05d'%row['id'],'status':row['status'],'status_label':row['status_label'],'received':received,'updated':stamp(row['updated_at']),
            'device':' · '.join(filter(None,[DEVICE_TYPES.get(kind,''),' '.join(filter(None,[row['brand'],row['model']]))])),'updates':updates,'files':files,'parts':parts}


HEAD='<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta name="robots" content="noindex,nofollow"><title>%s | PC-DOCTOR S.A.</title><link rel="icon" href="/favicon.ico?v=2" sizes="48x48"><link rel="stylesheet" href="/static/tracking.css"></head><body><main class="tracking-page"><header><img src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="150"><p>%s</p></header>'


def public_page(data,token=''):
    page=CARD_HEAD%('<meta http-equiv="refresh" content="180">',html.escape(data['code']))
    return page.replace('<body class="ticket-page">','<body class="ticket-page ticket-public">',1)+public_card(dict(data,token=token),'/s/'+token+'/qr.svg' if token else '')+'</main></body></html>'


# Tarjeta Digital de Seguimiento Técnico: ticket de dos secciones (datos de la orden arriba; QR y código de barras abajo).
# Las etapas salen del estado real de la orden; una etapa futura nunca se marca como completada.
STAGES=(('Recepción',('pendiente',)),('Diagnóstico y reparación',('reparacion','esperando_cliente','presupuesto','revision_recurrente')),('Listo para retiro',('listo','espera_entrega')),('Entrega',('entregado',)))
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
    # Iconos de trazo fino por dato (dibujados en línea: no dependen de fuentes ni de archivos externos).
    icons={'Cliente':'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z','Equipo':'M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v9H4zM2 19h20','Fecha de ingreso':'M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z','Última actualización':'M12 6v6l4 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0z','Técnico responsable':'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z'}
    icon=lambda label:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="%s"/></svg>'%icons[label] if label in icons else ''
    rows=''.join('<div>%s<span><dt>%s</dt><dd>%s</dd></span></div>'%(icon(label),e(label),e(value)) for label,value in facts)
    # Novedades: solo los mensajes que el técnico marcó como visibles para el cliente (la nota interna del taller nunca se publica).
    if data.get('updates'):
        rows+='</dl><section class="ticket-updates" aria-label="Novedades del servicio"><h2>Novedades del servicio</h2><ol>'+''.join(
            '<li><time>%s</time><strong>%s</strong><p>%s</p></li>'%(e(u['at']),e(u['label']),e(u['message']).replace('\n','<br>')) for u in data['updates'])+'</ol></section><dl class="ticket-facts" hidden>'
    code=data['code']
    try:bars=barcode128.svg(code,color='#0b1526',background='#ffffff')
    except barcode128.BarcodeError:bars=''
    qr='<img class="ticket-qr" src="%s" width="140" height="140" alt="Código QR del seguimiento de la orden %s">'%(e(qr_src),e(code)) if qr_src else '<p class="ticket-noqr">Sin enlace público activo. Genéralo desde la orden para obtener el código QR.</p>'
    return ('<article class="ticket" data-status="%s"><section class="ticket-top" aria-label="Datos de la orden">'
            '<header class="ticket-head"><img class="ticket-logo" src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="150"><div><small>%s</small><h1>Seguimiento de reparación</h1></div></header>'
            '<div class="ticket-order"><div><small>Orden de servicio</small><strong>%s</strong></div><span class="ticket-state" data-status="%s">%s</span></div>'
            '<div class="ticket-progress" role="img" aria-label="Avance: %s"><span data-progress="%d"></span></div><ol class="ticket-steps">%s</ol><dl class="ticket-facts">%s</dl></section>'
            '<div class="ticket-cut" aria-hidden="true"></div>'
            '<section class="ticket-bottom" aria-label="Código de seguimiento"><div class="ticket-verify"><h2>Código de seguimiento</h2><p>%s</p></div>%s'
            '<div class="ticket-barcode">%s<span>%s</span></div><footer><strong>%s</strong><span>%s</span><span>WhatsApp %s</span></footer></section></article>'
            )%(e(data['status']),e(company['name']),e(code),e(data['status']),e(data['status_label']),e(STAGES[current][0]),progress,steps,rows,
               'Escanea el código QR para consultar el estado actualizado de la reparación. El código de barras identifica esta orden en el taller.',qr,bars,e(code),e(company['name']),e(company['specialty']),e(company['whatsapp']))


# ---- Página pública ampliada (1.5.240) ----------------------------------------------------------------------------------------------
# Misma identidad de la tarjeta (degradado azul, logo original, corte de ticket), más ancha en escritorio y en una columna en el teléfono.
# La barra de avance tiene un segmento por etapa: solo las completadas llevan su color (azul → turquesa → verde claro → verde intenso); las
# pendientes quedan neutras. Los estados de espera se muestran como aviso, sin adelantar el avance. Todo sale de datos reales registrados.
FLAGS={'esperando_cliente':'Esperando su respuesta para continuar','presupuesto':'Presupuesto pendiente de su aprobación','revision_recurrente':'En revisión por falla recurrente'}
ICONS={'Equipo':'M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v9H4zM2 19h20','Fecha de ingreso':'M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z',
       'Última actualización':'M12 6v6l4 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0z'}


def _when(value,with_time=True):
    try:
        moment=datetime.fromisoformat(value)
        return (moment.astimezone(ECUADOR_TZ) if 'T' in value else moment).strftime('%d/%m/%Y %H:%M' if with_time and 'T' in value else '%d/%m/%Y')
    except (TypeError,ValueError):
        return ''


def _icon(path):
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="%s"/></svg>'%path


def _parts_section(data):
    e=html.escape;out=[]
    for p in data.get('parts') or []:
        steps=''.join('<li data-state="%s" data-c="%d"%s><i aria-hidden="true"></i><span>%s</span><small class="sr-only">%s</small>%s</li>'%(
            s['state'],s['color'],(' aria-current="step"'+(' data-tone="%s"'%e(p['tone']) if p['situation']!='normal' else '')) if s['state']=='current' else '',e(s['label']),
            {'done':'completada','current':'etapa actual','pending':'pendiente'}[s['state']],'<time>%s</time>'%e(_when(s['at'],False)) if s['at'] else '') for s in p['steps'])
        facts=[('Solicitado',_when(p['requested'],False)),('Disponibilidad estimada',_when(p['eta'],False) if p['eta'] else ''),('Recibido en el taller',_when(p['received'],False) if p['received'] else ''),
               ('Última actualización',_when(p['updated']))]
        hist=''.join('<li><time>%s</time><strong>%s</strong>%s</li>'%(e(_when(h['at'])),e(h['label']),'<p>%s</p>'%e(h['text']) if h['text'] else '') for h in p['history'])
        finished=p['steps'][-1]['state']=='done'
        out.append('<article class="tp" data-situation="%s"><header><div><strong>%s</strong>%s</div><span class="tp-state" data-tone="%s">%s</span></header><p class="tp-desc">%s</p>'
                   '<ol class="tp-steps" data-n="%d" aria-label="Etapas del repuesto">%s</ol><dl class="tp-facts">%s</dl>%s</article>'%(
                   e(p['situation']),e(p['name']),'<small>%s</small>'%e(p['brand']) if p['brand'] else '',e(p['tone'] if p['situation']!='normal' else ('verde' if finished else 'azul')),
                   e(p['status_label']),e(p['description']),len(p['steps']),steps,''.join('<div><dt>%s</dt><dd>%s</dd></div>'%(e(k),e(v)) for k,v in facts if v),
                   '<details class="tp-hist"><summary>Historial del repuesto (%d)</summary><ol>%s</ol></details>'%(len(p['history']),hist) if hist else ''))
    if not out:return ''
    return '<section class="tw-sec ticket-parts" aria-label="Seguimiento de repuestos"><h2>Seguimiento de repuestos</h2>'+''.join(out)+'</section>'


def _evidence_section(data):
    files=data.get('files') or []
    if not files or not data.get('token'):return ''
    e=html.escape;base='/s/'+data['token']+'/files/';photos=docs=0;items=''
    for f in files:
        pdf=f['mime']=='application/pdf'
        if pdf:docs+=1
        else:photos+=1
        label='Documento %d'%docs if pdf else 'Fotografía %d'%photos
        src=(base+'%d/thumb'%f['id']) if f.get('preview')=='thumb' else (base+'%d?part=0'%f['id']) if f.get('preview')=='original' else ''
        inner='<img src="%s" alt="" loading="lazy" decoding="async" width="160" height="160">'%e(src) if src else '<b aria-hidden="true">%s</b>'%('PDF' if pdf else 'Foto')
        items+='<li><button type="button" class="ticket-ev" data-file="%s%d" data-mime="%s" data-name="%s" aria-label="Ver %s"><span class="tw-thumb"%s>%s</span><span>%s</span></button></li>'%(
            base,f['id'],e(f['mime']),e(label),e(label.lower()),'' if src else ' data-ready',inner,e(label))
    return '<section class="tw-sec ticket-evidence" aria-label="Evidencias del servicio"><h2>Evidencias del servicio</h2><ul class="tw-gallery">'+items+'</ul></section>'


def public_card(data,qr_src):
    import barcode128
    company=settings();e=html.escape
    current=max(0,next((i for i,stage in enumerate(STAGES) if data['status'] in stage[1]),0));done=data['status']=='entregado'
    steps=''.join('<li data-state="%s" data-stage="%d"%s><span class="tw-bar" aria-hidden="true"></span><i aria-hidden="true"></i><b>%s</b><small>%s</small></li>'%(
        'done' if i<current or done else 'current' if i==current else 'pending',i+1,' aria-current="step"' if i==current and not done else '',e(label),
        'Completado' if i<current or done else 'Etapa actual' if i==current else 'Pendiente') for i,(label,_) in enumerate(STAGES))
    flags=[FLAGS[data['status']]] if data['status'] in FLAGS else []
    waiting=[p for p in data.get('parts') or [] if p['waiting']]
    if waiting and not done:flags.append('Esperando repuesto' if len(waiting)==1 else 'Esperando %d repuestos'%len(waiting))
    facts=[('Equipo',data.get('device') or 'No registrado'),('Fecha de ingreso',data.get('received') or 'No registrada'),('Última actualización',data.get('updated') or 'Sin movimientos')]
    rows=''.join('<div>%s<span><dt>%s</dt><dd>%s</dd></span></div>'%(_icon(ICONS[k]),e(k),e(v)) for k,v in facts)
    updates=''
    if data.get('updates'):
        updates='<section class="tw-sec ticket-updates" aria-label="Novedades del servicio"><h2>Novedades del servicio</h2><ol>'+''.join(
            '<li><time>%s</time><strong>%s</strong><p>%s</p></li>'%(e(u['at']),e(u['label']),e(u['message']).replace('\n','<br>')) for u in data['updates'])+'</ol></section>'
    main=updates+_evidence_section(data);side=_parts_section(data)
    if not main and not side:main='<section class="tw-sec"><h2>Novedades del servicio</h2><p class="tw-empty">Aún no hay novedades publicadas. Le informaremos cada avance.</p></section>'
    code=data['code']
    try:bars=barcode128.svg(code,color='#0b1526',background='#ffffff')
    except barcode128.BarcodeError:bars=''
    qr='<img class="ticket-qr" src="%s" width="132" height="132" alt="Código QR del seguimiento de la orden %s">'%(e(qr_src),e(code)) if qr_src else ''
    now=datetime.now(ECUADOR_TZ).strftime('%d/%m/%Y %H:%M')
    return ('<article class="ticket tw" data-status="%s"><section class="ticket-top tw-top" aria-label="Datos de la orden">'
            '<header class="tw-head"><img class="ticket-logo" src="/static/logo-original.png" alt="PC-DOCTOR S.A." width="150"><div class="tw-title"><small>%s</small><h1>Seguimiento de reparación</h1></div>'
            '<div class="tw-order"><small>Orden de servicio</small><strong>%s</strong><span class="ticket-state" data-status="%s">%s</span></div></header>'
            '<div class="tw-progress"><h2 class="sr-only">Avance de la reparación</h2><ol class="ticket-steps tw-steps">%s</ol>%s</div><dl class="ticket-facts tw-facts">%s</dl></section>'
            '<div class="tw-body%s">%s%s</div><div class="ticket-cut" aria-hidden="true"></div>'
            '<section class="ticket-bottom tw-codes" aria-label="Código de seguimiento">%s<div class="ticket-barcode">%s<span>%s</span></div>'
            '<div class="tw-verify"><h2>Código de seguimiento</h2><p>Escanea el QR para consultar este seguimiento. El código de barras identifica la orden en el taller.</p></div>'
            '<footer><strong>%s</strong><span>%s</span><span>WhatsApp %s</span></footer></section></article>'
            '<div class="tw-actions"><button type="button" data-refresh>Actualizar seguimiento</button><button type="button" data-print>Imprimir o guardar como PDF</button><small>Consultado el %s</small></div>'
            '<p class="ticket-note">Esta página muestra solo el estado de la reparación. No contiene datos personales.</p>'
            )%(e(data['status']),e(company['name']),e(code),e(data['status']),e(data['status_label']),steps,
               ''.join('<p class="tw-flag" role="status">%s</p>'%e(f) for f in flags),rows,' tw-two' if main and side else '','<div class="tw-col">%s</div>'%main if main else '',
               '<div class="tw-col">%s</div>'%side if side else '',qr,bars,e(code),e(company['name']),e(company['specialty']),e(company['whatsapp']),now)


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
