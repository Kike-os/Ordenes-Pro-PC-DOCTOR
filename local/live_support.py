"""Centro de Atención en Tiempo Real: conversaciones del chat público atendidas por ADI o por el personal."""
import re

import reception
ORDER_CODE=re.compile(r'\b(?:PCD-\d{8}-\d{4}|OP-\d{4,})\b',re.I)
LIST_SQL="""SELECT v.id,v.mode,v.assigned_to,v.created_at,v.updated_at,v.last_seen_admin,v.client_id,v.order_id,u.name operator,cl.name client,o.code order_code,o.status order_status,
 (SELECT content FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_message,
 (SELECT author FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_author,
 (SELECT created_at FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public' ORDER BY m.id DESC LIMIT 1) last_at,
 (SELECT COUNT(*) FROM adi_messages m WHERE m.conversation_id=v.id AND m.author='client' AND m.visibility='public' AND m.created_at>v.last_seen_admin) unread,
 (SELECT COUNT(*) FROM adi_messages m WHERE m.conversation_id=v.id AND m.visibility='public') total
 FROM adi_conversations v LEFT JOIN users u ON u.id=v.assigned_to LEFT JOIN clients cl ON cl.id=v.client_id LEFT JOIN orders o ON o.id=v.order_id """


def summary(c):
    """Contadores del Centro de Atenciones. Cada conversación abierta cuenta en una sola categoría:
    - waiting: con un asesor (o solicitándolo) y el último mensaje es del cliente → espera respuesta humana;
    - transferred: transferida por ADI a un asesor y ya respondida (en curso);
    - new_conversations: atendida por ADI y con mensajes del cliente que el personal aún no ha visto.
    Además devuelve las atenciones que requieren acción, de la que más tiempo lleva esperando a la más reciente."""
    counts={'new_conversations':0,'waiting':0,'transferred':0};pending=[]
    import whatsapp_handoff as handoff
    # Una solicitud de atención sin aceptar espera al personal aunque el último mensaje sea la confirmación de ADI (1.5.321).
    unattended={r[0] for r in c.execute("SELECT conversation_id FROM adi_handoffs WHERE status='pendiente'")} if handoff.installed(c) else set()
    for row in c.execute(LIST_SQL+"WHERE v.mode!='closed' ORDER BY v.updated_at"):
        if not row['total']:continue
        if row['mode']=='human':kind='waiting' if row['last_author']=='client' or row['id'] in unattended else 'transferred'
        elif row['unread'] or (row['last_seen_admin']=='' and row['last_author'] is not None):kind='new_conversations'
        else:continue
        counts[kind]+=1
        if kind!='transferred':pending.append({'id':row['id'],'kind':kind,'client':row['client'] or '','order_code':row['order_code'] or '','source':'Transferida por ADI' if row['mode']=='human' else 'Chat con ADI',
                                               'created_at':row['created_at'],'waiting_since':row['last_at'] or row['updated_at'],'unread':row['unread'],'preview':(row['last_message'] or '')[:120] if row['last_author']=='client' else ''})
    pending.sort(key=lambda item:(item['kind']!='waiting',item['waiting_since']))
    return dict(counts,pending=pending[:5],total=sum(counts.values()))


FILTERS={'todas':'Todas','activas':'Activas','sin_leer':'Sin leer','con_adi':'Con ADI','con_asesor':'Con asesor','esperando_asesor':'Esperando asesor',
         'esperando_cliente':'Esperando cliente','proximas_cerrar':'Próximas a cerrar','cerradas_auto':'Cerradas automáticamente','cerradas_manual':'Cerradas manualmente','reabiertas':'Reabiertas'}


def rows(c,scope='active',filt='',channel=''):
    """Bandeja. `scope` (compatibilidad): active | closed. `filt`: uno de FILTERS. `channel`: web | whatsapp. Las cerradas nunca aparecen en
    «Activas». Antes de listar se aplican en el servidor los cierres y avisos que ya vencieron (barrido limitado)."""
    import support_sessions as ss
    now=reception.reception_now()
    try:ss.sweep(c,now)
    except Exception as error:print('support-sweep',type(error).__name__,flush=True)
    closed_filters=('cerradas_auto','cerradas_manual')
    if filt in closed_filters or (filt=='todas') or (scope=='closed' and not filt):
        where="WHERE v.mode='closed' " if filt in closed_filters or scope=='closed' and not filt else ''
        sql=LIST_SQL+where+"ORDER BY v.updated_at DESC LIMIT 100"
    else:sql=LIST_SQL+"WHERE v.mode!='closed' ORDER BY v.updated_at DESC LIMIT 100"
    out=[dict(r) for r in c.execute(sql)]
    sessions={}
    if out and ss.installed(c):
        ids=[r['id'] for r in out];marks=','.join('?'*len(ids))
        sessions={r['conversation_id']:r for r in c.execute('SELECT * FROM support_sessions WHERE conversation_id IN ('+marks+')',ids)}
    for r in out:
        t=ss.timer(c,r['id'],now) if r['id'] in sessions else {'status':'sin_sesion','enabled':ss.settings(c)['enabled'] if ss.installed(c) else False}
        r['session']=t;s_=sessions.get(r['id'])
        r['close_kind']=s_['close_kind'] if s_ else '';r['reopened']=s_['reopened_count'] if s_ else 0
    import whatsapp_handoff as handoff
    if out and handoff.installed(c):
        ids=[r['id'] for r in out];marks=','.join('?'*len(ids))
        cases={r['conversation_id']:r for r in c.execute("SELECT conversation_id,code,priority,status FROM adi_handoffs WHERE status IN ('pendiente','asignada') AND conversation_id IN ("+marks+")",ids)}
        wa={r[0] for r in c.execute('SELECT conversation_id FROM whatsapp_conversations WHERE conversation_id IN ('+marks+')',ids)}
        for r in out:
            case=cases.get(r['id'])
            r.update(channel='whatsapp' if r['id'] in wa else 'web',case_code=case['code'] if case else '',case_priority=case['priority'] if case else '',case_status=case['status'] if case else '')
        if scope!='closed':  # las urgentes primero, luego alta; dentro de cada nivel, el orden de siempre
            rank={'urgente':0,'alta':1}
            out.sort(key=lambda r:rank.get(r.get('case_priority'),2))
    for r in out:r.setdefault('channel','web');r.setdefault('case_status','')
    def keep(r):
        t=r['session'];waiting_staff=(r['mode']=='human' and (r['last_author']=='client' or r.get('case_status')=='pendiente')) or t.get('waiting_staff')
        return {'todas':True,'activas':r['mode']!='closed','sin_leer':bool(r['unread']),'con_adi':r['mode']=='adi','con_asesor':r['mode']=='human' and bool(r['assigned_to']),
                'esperando_asesor':r['mode']!='closed' and bool(waiting_staff),'esperando_cliente':r['mode']!='closed' and r['last_author'] in ('adi','operator') and not waiting_staff,
                'proximas_cerrar':t.get('status')=='activa' and t.get('remaining_seconds') is not None and t['remaining_seconds']<=180 and not t.get('waiting_staff'),
                'cerradas_auto':r['mode']=='closed' and r['close_kind']=='automatico','cerradas_manual':r['mode']=='closed' and r['close_kind']!='automatico',
                'reabiertas':bool(r['reopened'])}.get(filt or 'activas' if scope!='closed' else 'todas',True)
    out=[r for r in out if keep(r) and (not channel or r['channel']==channel)]
    return out


def detail(c,conv,after,now):
    """Mensajes posteriores a «after» y el contexto real de la conversación. Consultarla la marca como vista por el personal."""
    messages=[dict(r) for r in c.execute('SELECT m.id,m.author,m.visibility,m.content,m.created_at,u.name operator FROM adi_messages m LEFT JOIN users u ON u.id=m.author_id WHERE m.conversation_id=? AND m.id>? ORDER BY m.id',(conv['id'],after))]
    c.execute('UPDATE adi_conversations SET last_seen_admin=? WHERE id=?',(now,conv['id']))
    info=dict(c.execute(LIST_SQL+'WHERE v.id=?',(conv['id'],)).fetchone());info['unread']=0
    client=c.execute('SELECT id,name,phone,email FROM clients WHERE id=?',(conv['client_id'],)).fetchone() if conv['client_id'] else None
    order=c.execute("SELECT o.id,o.code,o.status,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.id=?",(conv['order_id'],)).fetchone() if conv['order_id'] else None
    actions=[dict(r) for r in c.execute('SELECT a.action,a.created_at,a.details,u.name actor FROM adi_actions a LEFT JOIN users u ON u.id=a.user_id WHERE a.conversation_id=? ORDER BY a.id DESC LIMIT 8',(conv['id'],))]
    # Órdenes que el cliente mencionó por su número exacto: se sugieren, nunca se vinculan solas.
    mentioned=[]
    if not conv['order_id']:
        for row in c.execute("SELECT content FROM adi_messages WHERE conversation_id=? AND author='client' ORDER BY id DESC LIMIT 40",(conv['id'],)):
            for code in ORDER_CODE.findall(row['content']):
                code=code.upper()
                if code not in mentioned and c.execute('SELECT 1 FROM orders WHERE code=?',(reception.current_order_code(c,code),)).fetchone():mentioned.append(code)
    import whatsapp_handoff as handoff
    try:moment=reception.reception_now();attention=handoff.for_conversation(c,conv['id'],moment)
    except Exception:attention=None
    if attention and handoff.installed(c):
        failed={r['message_id']:r['detail'] for r in c.execute("SELECT message_id,detail FROM whatsapp_operator_sends WHERE conversation_id=? AND status='fallido'",(conv['id'],))}
        for m in messages:
            if m['id'] in failed:m['whatsapp_failed']=failed[m['id']] or 'WhatsApp no aceptó el mensaje.'
    staff=[dict(r) for r in c.execute("SELECT id,name FROM users WHERE active=1 AND role IN ('administrador','tecnico') ORDER BY name")]
    import support_sessions as ss
    try:ss.sweep_one(c,conv['id'],reception.reception_now());timer=ss.timer(c,conv['id'],reception.reception_now());history=ss.events(c,conv['id'],20)
    except Exception as error:print('support-session',type(error).__name__,flush=True);timer,history={'status':'sin_sesion'},[]
    return {'conversation':info,'messages':messages,'client':dict(client) if client else None,'order':dict(order) if order else None,'actions':actions,'mentioned':mentioned[:3],
            'attention':attention,'staff':staff,'session':timer,'session_events':history,'receipts':_receipt(lambda ms:ms.recent(c,conv['id']))}


def act(c,conv,user,data,now,moment=None):
    """Acciones del personal. En las conversaciones de WhatsApp (1.5.321) la respuesta sale por WhatsApp, la solicitud de atención
    (adi_handoffs) se acepta, transfiere o cierra y el cliente recibe el aviso; si WhatsApp no acepta el mensaje, se informa."""
    import whatsapp_handoff as handoff
    if moment is None:
        moment=reception.reception_now()
    action=data.get('action');details='';extra={}
    if action=='reply':
        content=str(data.get('message','')).strip()
        if not content or len(content)>3000:return 400,{'error':'Escribe una respuesta de hasta 3000 caracteres.'}
        if conv['mode']=='closed':return 409,{'error':'La conversación está cerrada. Reábrela para responder.'}
        mid=c.execute("INSERT INTO adi_messages(conversation_id,author,author_id,content,created_at) VALUES (?,'operator',?,?,?)",(conv['id'],user['id'],content,now)).lastrowid
        c.execute("UPDATE adi_conversations SET mode='human',assigned_to=?,updated_at=? WHERE id=?",(user['id'],now,conv['id']))
        handoff.on_staff_action(c,conv['id'],'reply',user,moment)
        _ss(lambda ss:ss.activity(c,conv['id'],'human',moment))
        sent,detail=handoff.send_text(c,conv['id'],content,moment,message_id=mid)
        if sent is not None:extra['whatsapp']={'sent':bool(sent),'detail':detail}
        def receipts(ms):
            row=c.execute('SELECT provider_id,detail FROM whatsapp_operator_sends WHERE message_id=?',(mid,)).fetchone() if sent is not None else None
            if row is not None:ms.record_out(c,mid,conv['id'],'whatsapp',moment,row['provider_id'],'' if row['provider_id'] else (row['detail'] or 'WhatsApp no aceptó el mensaje.'))
            else:ms.record_out(c,mid,conv['id'],'web',moment)
            ms.inbound_read(c,conv['id'],moment,user['name'] if 'name' in user.keys() else 'Asesor')   # quien responde leyó lo anterior
        _receipt(receipts)
        return 200,dict({'ok':True},**extra)
    if action=='transfer':
        target=str(data.get('user_id',''))
        row=c.execute("SELECT id,name FROM users WHERE id=? AND active=1 AND role IN ('administrador','tecnico')",(int(target),)).fetchone() if target.isdigit() else None
        if not row:return 404,{'error':'Elige una persona activa del personal.'}
        if conv['mode']=='closed':return 409,{'error':'La conversación está cerrada.'}
        c.execute("UPDATE adi_conversations SET mode='human',assigned_to=?,updated_at=? WHERE id=?",(row['id'],now,conv['id']))
        handoff.on_staff_action(c,conv['id'],'transfer',user,moment,target=row['id']);details='Transferida a '+row['name']
    elif action in ('takeover','resume','close','reopen'):
        if action=='reopen' and conv['mode']!='closed':return 409,{'error':'La conversación ya está abierta.'}
        if action!='reopen' and conv['mode']=='closed':return 409,{'error':'La conversación está cerrada.'}
        mode={'takeover':'human','resume':'adi','close':'closed','reopen':'human'}[action]
        c.execute('UPDATE adi_conversations SET mode=?,assigned_to=?,updated_at=? WHERE id=?',(mode,user['id'] if mode=='human' else None,now,conv['id']))
        note=handoff.on_staff_action(c,conv['id'],action,user,moment)
        if action=='close':_ss(lambda ss:ss.close_manual(c,conv['id'],user,moment))
        if action=='reopen':_ss(lambda ss:ss.reopen_manual(c,conv['id'],user,moment))
        if note:extra['warning']=note
    elif action=='pause':
        import support_sessions
        try:support_sessions.pause(c,conv['id'],user,data.get('minutes'),data.get('reason'),moment)
        except support_sessions.SupportError as error:return error.status,{'error':str(error)}
        details='Cierre automático pausado'
    elif action=='seen':
        # El panel confirma qué mensajes del cliente estuvieron visibles en una pestaña activa: solo entonces se marcan leídos por el asesor.
        try:up_to=int(data.get('up_to') or 0)
        except (TypeError,ValueError):up_to=0
        if up_to<=0:return 400,{'error':'Mensaje no válido.'}
        _receipt(lambda ms:ms.inbound_read(c,conv['id'],moment,user['name'] if 'name' in user.keys() else 'Asesor',up_to))
        return 200,{'ok':True,'receipts':_receipt(lambda ms:ms.recent(c,conv['id']))}
    elif action=='note':
        # Nota interna: visibility='internal' nunca se muestra ni se envía al cliente (ni por el chat web ni por WhatsApp).
        content=' '.join(str(data.get('message','')).split())
        if not 3<=len(content)<=1000:return 400,{'error':'Escribe una nota interna de 3 a 1000 caracteres.'}
        c.execute("INSERT INTO adi_messages(conversation_id,author,author_id,visibility,content,created_at) VALUES (?,'operator',?,'internal',?,?)",(conv['id'],user['id'],content,now))
        details='Nota interna'
    elif action=='link':
        if data.get('clear') is True:
            c.execute('UPDATE adi_conversations SET client_id=NULL,order_id=NULL WHERE id=?',(conv['id'],));details='Vínculo retirado'
        elif str(data.get('order_code','')).strip():
            code=str(data['order_code']).strip().upper()
            order=c.execute('SELECT o.id,o.code,d.client_id FROM orders o JOIN devices d ON d.id=o.device_id WHERE o.code=?',(reception.current_order_code(c,code),)).fetchone()
            if not order:return 404,{'error':'No existe una orden con ese número.'}
            c.execute('UPDATE adi_conversations SET client_id=?,order_id=? WHERE id=?',(order['client_id'],order['id'],conv['id']));details='Orden '+order['code']
        elif str(data.get('client_id','')).isdigit():
            client=c.execute('SELECT id,name FROM clients WHERE id=?',(int(data['client_id']),)).fetchone()
            if not client:return 404,{'error':'El cliente ya no está disponible.'}
            c.execute('UPDATE adi_conversations SET client_id=?,order_id=NULL WHERE id=?',(client['id'],conv['id']));details='Cliente '+client['name']
        else:return 400,{'error':'Indica una orden o un cliente para vincular.'}
    else:return 400,{'error':'Acción de conversación inválida.'}
    c.execute('INSERT INTO adi_actions(conversation_id,user_id,action,created_at,details) VALUES (?,?,?,?,?)',(conv['id'],user['id'],'conversation_'+action,now,details))
    return 200,dict({'ok':True},**extra)


def _ss(fn):
    """ADI Live Support 4.0: registra la actividad o el cierre en la sesión; un fallo nunca impide responder."""
    try:
        import support_sessions
        fn(support_sessions)
    except Exception as error:
        print('support-session',type(error).__name__,flush=True)


def metrics(c):
    """Indicadores del centro de atención con registros reales (conversaciones abiertas y sesiones/eventos de 7 días)."""
    out={'active':0,'with_adi':0,'with_advisor':0,'waiting_reply':0,'unread':0}
    for r in c.execute(LIST_SQL+"WHERE v.mode!='closed'"):
        if not r['total']:continue
        out['active']+=1;out['with_adi']+=r['mode']=='adi';out['with_advisor']+=r['mode']=='human'
        out['waiting_reply']+=r['last_author']=='client';out['unread']+=r['unread'] or 0
    try:
        import support_sessions
        out.update(support_sessions.metrics(c,reception.reception_now()))
    except Exception as error:
        print('support-metrics',type(error).__name__,flush=True)
    return out


def _receipt(fn):
    """Live Read Receipts: un fallo de confirmaciones nunca impide atender."""
    try:
        import message_status
        return fn(message_status)
    except Exception as error:
        print('message-status',type(error).__name__,flush=True)
        return None
