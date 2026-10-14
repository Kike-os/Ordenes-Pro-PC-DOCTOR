"""Varios equipos por orden, identidad permanente de cada equipo y pagos por equipo.

Cada equipo recibido es un ingreso propio (una fila de orders) con su fecha, diagnóstico, fotografías, técnico, presupuesto,
estado, pagos y entrega. Los ingresos de una misma orden se unen por group_id a la orden principal y se identifican como
<orden>-E01, <orden>-E02… El equipo físico conserva su identificador permanente EQ-0001 entre ingresos."""
import re
from decimal import Decimal, InvalidOperation

METHODS={'efectivo':'Efectivo','transferencia':'Transferencia','tarjeta':'Tarjeta','deposito':'Depósito','otro':'Otro'}
MAX_UNITS=50
BUDGET="COALESCE((SELECT labor_cents+parts_cents+services_cents+digital_cents FROM order_budget b WHERE b.order_id=o.id),0)"
# Pagos netos de un equipo: sus pagos confirmados menos sus devoluciones, más lo que se le asignó de pagos generales de la orden.
# Los movimientos anulados no cuentan. Importes siempre en centavos enteros.
NET="CASE p.kind WHEN 'devolucion' THEN -p.amount_cents ELSE p.amount_cents END"
PAID=("(COALESCE((SELECT SUM("+NET+") FROM order_payments p WHERE p.order_id=o.id AND p.scope='equipo' AND p.voided_at IS NULL),0)"
      "+COALESCE((SELECT SUM(a.amount_cents) FROM order_payment_allocations a JOIN order_payments p ON p.id=a.payment_id WHERE a.order_id=o.id AND p.voided_at IS NULL),0))")
STATES={'sin_cargos':'Sin cargos registrados','pendiente':'Pendiente de pago','parcial':'Pago parcial registrado','pagado':'Sin saldo pendiente','credito':'Saldo a favor del cliente'}
KEY=re.compile(r'[A-Za-z0-9-]{16,64}')


def code_of(row):
    return row['code'] or 'OP-'+str(row['id']).zfill(5)


def root(c,order_id):
    """Orden principal del grupo al que pertenece un ingreso (la propia orden si no tiene grupo)."""
    row=c.execute('SELECT id,code,group_id,device_id FROM orders WHERE id=?',(order_id,)).fetchone()
    if not row:return None
    if row['group_id'] and row['group_id']!=row['id']:
        row=c.execute('SELECT id,code,group_id,device_id FROM orders WHERE id=?',(row['group_id'],)).fetchone()
    return row


def unit_code(row,main_code):
    """Identificador del equipo dentro de la orden: la principal es E01; las demás ya llevan el sufijo en su código."""
    if not row['group_id']:return ''
    return main_code+'-E%02d'%row['unit_no']


def next_unit(c,main):
    """Reserva el siguiente número de equipo de la orden principal y devuelve (número, código)."""
    if not main['group_id']:c.execute('UPDATE orders SET group_id=id WHERE id=? AND group_id IS NULL',(main['id'],))
    number=c.execute('SELECT COALESCE(MAX(unit_no),1)+1 FROM orders WHERE group_id=?',(main['id'],)).fetchone()[0]
    if number>MAX_UNITS:return None,None
    return number,code_of(main)+'-E%02d'%number


def summary(charges,paid):
    """Estado financiero a partir del total exigible y de los pagos netos (centavos). Saldo = exigible − pagos netos. Un saldo negativo
    no se convierte en cero: se informa como saldo a favor. Sin cargos ni pagos no se afirma que el cliente pagó."""
    due=charges-paid
    state='sin_cargos' if not charges and not paid else 'credito' if due<0 else 'pagado' if due==0 else 'parcial' if paid>0 else 'pendiente'
    return {'budget_cents':charges,'paid_cents':paid,'balance_cents':max(0,due),'credit_cents':max(0,-due),'state':state,'state_label':STATES[state]}


def money(c,order_id):
    """Resumen financiero de un equipo. Es la única fuente del saldo: lo usan el detalle, la entrega, los pagos y la tarjeta."""
    row=c.execute('SELECT '+BUDGET+' budget,'+PAID+' paid FROM orders o WHERE o.id=?',(order_id,)).fetchone()
    return summary(*((row['budget'],row['paid']) if row else (0,0)))


def general(c,main_id):
    """Pagos generales de la orden (sin equipo) y lo que queda de ellos sin asignar a un equipo."""
    rows=[dict(r) for r in c.execute("SELECT p.id,p.amount_cents,p.kind,p.method,p.note,p.created_at,p.voided_at,p.void_reason,COALESCE(u.name,'') actor,"
                                     "COALESCE((SELECT SUM(a.amount_cents) FROM order_payment_allocations a WHERE a.payment_id=p.id),0) allocated_cents "
                                     "FROM order_payments p LEFT JOIN users u ON u.id=p.created_by WHERE p.order_id=? AND p.scope='general' ORDER BY p.id",(main_id,))]
    for row in rows:row['free_cents']=row['amount_cents']-row['allocated_cents'] if row['kind']=='pago' and not row['voided_at'] else 0
    live=[row for row in rows if not row['voided_at']]
    return rows,sum(row['free_cents'] for row in live)-sum(row['amount_cents'] for row in live if row['kind']=='devolucion')


def usd(cents):
    """Importe en dólares con el formato de Ecuador ($1.234,56), a partir de centavos enteros."""
    return '$'+format(cents//100,',').replace(',','.')+',%02d'%(cents%100)


def delivery_block(c,order_id):
    """Mensaje que impide entregar un equipo con saldo pendiente; None si se puede entregar."""
    state=money(c,order_id)
    if state['balance_cents']<=0:return None
    main=root(c,order_id);free=general(c,main['id'])[1] if main else 0
    return 'No se puede entregar: este equipo tiene un saldo pendiente de '+usd(state['balance_cents'])+'. '+('La orden tiene '+usd(free)+' de pagos generales sin asignar: asígnalos a este equipo o registra el pago antes de entregarlo.' if free>0 else 'Registra el pago antes de entregarlo.')


def payments(c,order_id):
    """Movimientos de un equipo: sus pagos y devoluciones, y lo que recibió de pagos generales de la orden."""
    rows=[dict(r) for r in c.execute("SELECT p.id,p.amount_cents,p.kind,p.method,p.note,p.created_at,p.voided_at,p.void_reason,COALESCE(u.name,'') actor FROM order_payments p LEFT JOIN users u ON u.id=p.created_by WHERE p.order_id=? AND p.scope='equipo' ORDER BY p.id",(order_id,))]
    rows+=[dict(r,kind='asignacion') for r in c.execute("SELECT a.id allocation_id,p.id,a.amount_cents,p.method,p.note,a.created_at,p.voided_at,p.void_reason,COALESCE(u.name,'') actor FROM order_payment_allocations a JOIN order_payments p ON p.id=a.payment_id LEFT JOIN users u ON u.id=a.created_by WHERE a.order_id=? ORDER BY a.id",(order_id,))]
    return sorted(rows,key=lambda row:row['created_at'])


def cents_of(value):
    """Importe en centavos enteros a partir de un texto decimal (nunca flotantes); None si no es un importe positivo con hasta dos decimales."""
    try:
        amount=Decimal(str(value).strip().replace(',','.'))
        if not amount.is_finite() or amount<=0 or amount>Decimal('9999999.99') or amount.as_tuple().exponent<-2:return None
        return int(amount*100)
    except (InvalidOperation,ValueError):return None


def add_payment(c,order_id,data,user,now):
    """Registra un pago (o una devolución) de un equipo o general de la orden. Se llama dentro de una transacción de escritura, así
    el saldo que se valida es el mismo que queda guardado aunque lleguen dos solicitudes a la vez."""
    order=c.execute('SELECT id FROM orders WHERE id=?',(order_id,)).fetchone()
    if not order:return 404,{'error':'Orden no disponible.'}
    kind=str(data.get('kind','pago'));scope=str(data.get('scope','equipo'));key=str(data.get('request_key','')).strip()
    if kind not in ('pago','devolucion') or scope not in ('equipo','general'):return 400,{'error':'Movimiento no válido.'}
    if kind=='devolucion' and user['role']!='administrador':return 403,{'error':'Solo administración puede registrar una devolución.'}
    if key and not KEY.fullmatch(key):return 400,{'error':'Solicitud no válida. Recarga la página e inténtalo nuevamente.'}
    main=root(c,order_id);target=main['id'] if scope=='general' else order_id
    if scope=='general' and not main['group_id']:return 400,{'error':'Esta orden tiene un solo equipo: registra el pago en el equipo.'}
    errors={};cents=cents_of(data.get('amount',''))
    if cents is None:errors['amount']='Indica un importe mayor que cero con hasta dos decimales.';cents=0
    method=str(data.get('method',''))
    if method not in METHODS:errors['method']='Selecciona la forma de pago.'
    note=str(data.get('note','')).strip()
    if len(note)>300:errors['note']='La nota admite hasta 300 caracteres.'
    elif kind=='devolucion' and len(note)<5:errors['note']='Indica el motivo o la referencia de la devolución (al menos 5 caracteres).'
    if key and not errors:
        # Reintento o doble clic: la misma solicitud devuelve el movimiento ya registrado en lugar de crear otro.
        same=c.execute('SELECT id,order_id,amount_cents,kind,scope FROM order_payments WHERE request_key=?',(key,)).fetchone()
        if same:
            if (same['order_id'],same['amount_cents'],same['kind'],same['scope'])!=(target,cents,kind,scope):return 409,{'error':'Esta solicitud ya se utilizó para otro movimiento. Recarga la página e inténtalo nuevamente.'}
            return 200,{'ok':True,'id':same['id'],'duplicate':True,**money(c,order_id)}
    if not errors:
        state=money(c,order_id);whole=group(c,order_id)['totals'] if scope=='general' else None
        if kind=='pago':
            limit=whole['balance_cents'] if whole else state['balance_cents']
            if cents>limit:
                errors['amount']=('El pago supera el saldo pendiente de la orden ('+usd(limit)+').' if whole else 'El pago supera el saldo pendiente de este equipo ('+usd(limit)+').') if (whole or state)['budget_cents'] else 'Todavía no hay cargos registrados: registra el presupuesto antes de cobrar.'
        else:
            limit=max(0,whole['general_cents']) if whole else state['paid_cents']
            if cents>limit:errors['amount']='La devolución supera lo pagado '+('sin asignar de la orden' if whole else 'por este equipo')+' ('+usd(limit)+').'
    if errors:return 400,{'error':next(iter(errors.values())),'fields':errors}
    pid=c.execute('INSERT INTO order_payments(order_id,amount_cents,method,note,created_by,created_at,kind,scope,request_key) VALUES (?,?,?,?,?,?,?,?,?)',(target,cents,method,note,user['id'],now.isoformat(timespec='seconds'),kind,scope,key or None)).lastrowid
    return 201,{'ok':True,'id':pid,'amount_cents':cents,'kind':kind,'scope':scope,**money(c,order_id)}


def assign_payment(c,order_id,data,user,now):
    """Asigna a un equipo una parte (o todo) de un pago general de su orden. No crea dinero: mueve saldo sin asignar al equipo."""
    main=root(c,order_id);pid=str(data.get('payment_id',''))
    row=c.execute("SELECT id,amount_cents,voided_at,COALESCE((SELECT SUM(a.amount_cents) FROM order_payment_allocations a WHERE a.payment_id=p.id),0) allocated FROM order_payments p WHERE p.id=? AND p.order_id=? AND p.scope='general' AND p.kind='pago'",(pid,main['id'])).fetchone() if main and pid.isdigit() else None
    if not row or row['voided_at']:return 404,{'error':'Pago general no disponible.'}
    state=money(c,order_id);rows,free_total=general(c,main['id']);free=min(row['amount_cents']-row['allocated'],max(0,free_total))
    cents=cents_of(data['amount']) if str(data.get('amount','')).strip() else min(free,state['balance_cents'])
    if not cents:return 400,{'error':'No hay importe que asignar: el pago ya está distribuido o el equipo no tiene saldo pendiente.' if cents==0 else 'Indica un importe mayor que cero con hasta dos decimales.','fields':{'amount':'Importe no válido.'}}
    if cents>free:return 400,{'error':'El importe supera lo que queda sin asignar de este pago ('+usd(free)+').','fields':{'amount':'Importe no válido.'}}
    if cents>state['balance_cents']:return 400,{'error':'El importe supera el saldo pendiente de este equipo ('+usd(state['balance_cents'])+').','fields':{'amount':'Importe no válido.'}}
    c.execute('INSERT INTO order_payment_allocations(payment_id,order_id,amount_cents,created_by,created_at) VALUES (?,?,?,?,?)',(row['id'],order_id,cents,user['id'],now.isoformat(timespec='seconds')))
    return 201,{'ok':True,'amount_cents':cents,**money(c,order_id)}


def void_payment(c,order_id,data,user,now):
    pid=str(data.get('payment_id',''));reason=str(data.get('reason','')).strip();main=root(c,order_id)
    row=c.execute('SELECT id,order_id,amount_cents,kind,scope,voided_at FROM order_payments WHERE id=?',(pid,)).fetchone() if pid.isdigit() and main else None
    # El pago debe pertenecer a este equipo, o ser un pago general de su misma orden.
    if not row or (row['order_id'],row['scope']) not in ((order_id,'equipo'),(main['id'],'general')):return 404,{'error':'Pago no disponible.'}
    if row['voided_at']:return 409,{'error':'Este pago ya estaba anulado.'}
    if not 5<=len(reason)<=300:return 400,{'error':'Indica el motivo de la anulación (entre 5 y 300 caracteres).','fields':{'reason':'Motivo obligatorio.'}}
    touched=[order_id] if row['scope']=='equipo' else [r[0] for r in c.execute('SELECT DISTINCT order_id FROM order_payment_allocations WHERE payment_id=?',(row['id'],))]
    if any(c.execute("SELECT status FROM orders WHERE id=?",(oid,)).fetchone()['status']=='entregado' for oid in touched):return 409,{'error':'El equipo ya fue entregado: no se anulan pagos de una entrega registrada.'}
    if row['kind']=='pago':
        # Anular un pago no puede dejar devoluciones sin respaldo (pagos netos negativos).
        left=money(c,order_id)['paid_cents']-row['amount_cents'] if row['scope']=='equipo' else general(c,main['id'])[1]-(row['amount_cents']-c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM order_payment_allocations WHERE payment_id=?',(row['id'],)).fetchone()[0])
        if left<0:return 409,{'error':'Este pago tiene devoluciones registradas: anula primero la devolución.'}
        if row['scope']=='general' and any(money(c,oid)['paid_cents']<c.execute('SELECT SUM(amount_cents) FROM order_payment_allocations WHERE payment_id=? AND order_id=?',(row['id'],oid)).fetchone()[0] for oid in touched):return 409,{'error':'Un equipo que recibió parte de este pago tiene devoluciones registradas: anula primero la devolución.'}
    c.execute('UPDATE order_payments SET voided_at=?,voided_by=?,void_reason=? WHERE id=?',(now.isoformat(timespec='seconds'),user['id'],reason,row['id']))
    return 200,{'ok':True,'kind':row['kind'],'scope':row['scope'],**money(c,order_id)}


UNIT_SQL=("SELECT o.id,o.code,o.group_id,o.unit_no,o.status status_code,s.label status,o.received_at,o.delivered_at,o.updated_at,o.problem,d.id device_id,d.code device_code,"
          "COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,d.serial,d.color,COALESCE((SELECT name FROM users WHERE id=o.assigned_to),'Sin asignar') responsible,"
          +BUDGET+" budget_cents,"+PAID+" paid_cents FROM orders o JOIN devices d ON d.id=o.device_id JOIN statuses s ON s.code=o.status ")


PHASES=(('recibido','Recibido',('pendiente',)),('proceso','En proceso',('reparacion','esperando_cliente','presupuesto')),('listo','Listo para entregar',('listo','espera_entrega')),('entregado','Entregado',('entregado',)))
def phase(status):
    """Etapa (recibido, proceso, listo, entregado) a la que pertenece un estado de equipo."""
    return next((code for code,_,statuses in PHASES if status in statuses),'recibido')
def overall(rows):
    """Estado general de una orden con varios equipos, calculado con el estado real de cada uno. Nunca dice «completada» ni «entregada»
    mientras quede un equipo sin entregar. Prioridad: todos entregados → completada; alguno entregado → entrega parcial; alguno en
    proceso (o mezcla de recibidos y listos) → atención en curso; todos listos → listos para entrega; todos recibidos → recibidos."""
    counts={code:sum(1 for row in rows if phase(row['status_code'])==code) for code,_,_ in PHASES};total=len(rows)
    if counts['entregado']==total:code,label='completada','Orden completada'
    elif counts['entregado']:code,label='parcial','Entrega parcial'
    elif counts['proceso'] or (counts['listo'] and counts['recibido']):code,label='curso','Atención en curso'
    elif counts['listo']==total:code,label='listos','Listos para entrega'
    else:code,label='recibidos','Equipos recibidos'
    words={'recibido':('recibido','recibidos'),'proceso':('en proceso','en proceso'),'listo':('listo para entregar','listos para entregar'),'entregado':('entregado','entregados')}
    parts=['1 equipo' if total==1 else '%d equipos'%total]+['%d %s'%(counts[key],words[key][0 if counts[key]==1 else 1]) for key in ('entregado','listo','proceso','recibido') if counts[key]]
    return {'code':code,'label':label,'summary':' · '.join(parts),'counts':counts}
def group(c,order_id):
    """Equipos de la orden a la que pertenece un ingreso, con su resumen económico consolidado."""
    main=root(c,order_id)
    if not main:return None
    rows=[dict(r) for r in c.execute(UNIT_SQL+'WHERE o.group_id=? ORDER BY o.unit_no',(main['id'],))] if main['group_id'] else [dict(r) for r in c.execute(UNIT_SQL+'WHERE o.id=?',(main['id'],))]
    main_code=code_of(main)
    for row in rows:
        row['code']=row['code'] or 'OP-'+str(row['id']).zfill(5)
        row['unit_code']=main_code+'-E%02d'%row['unit_no']
        row.update(summary(row['budget_cents'],row['paid_cents']))
        row['phase']=phase(row['status_code'])
    # Consolidado: cargos de todos los equipos menos pagos netos (los de cada equipo y los generales sin asignar, una sola vez).
    moves,free=general(c,main['id']);charges=sum(r['budget_cents'] for r in rows);paid=sum(r['paid_cents'] for r in rows)+free
    return {'main_id':main['id'],'main_code':main_code,'multiple':len(rows)>1,'units':rows,'overall':overall(rows),'general_payments':moves,
            'totals':{**summary(charges,paid),'general_cents':free,'delivered':sum(1 for r in rows if r['status_code']=='entregado'),'units':len(rows)}}


def finance(c,order_id):
    """Saldo del equipo y saldo general de su orden, para la tarjeta financiera. None si la orden no existe."""
    whole=group(c,order_id)
    if not whole:return None
    unit=next((row for row in whole['units'] if row['id']==order_id),None)
    keys=('budget_cents','paid_cents','balance_cents','credit_cents','state','state_label')
    return {'unit':dict({key:unit[key] for key in keys},unit_code=unit['unit_code'] if whole['multiple'] else '') if unit else None,'order':dict(whole['totals'],code=whole['main_code']),'multiple':whole['multiple'],
            'units':[dict({key:row[key] for key in keys},id=row['id'],unit_code=row['unit_code']) for row in whole['units']]}


def receipt(c,order_id,payment_id):
    """Datos del recibo de un movimiento: el pago debe ser de este equipo o un pago general de su misma orden. None si no corresponde."""
    main=root(c,order_id)
    pay=c.execute("SELECT p.id,p.order_id,p.amount_cents,p.kind,p.scope,p.method,p.note,p.created_at,p.voided_at,p.void_reason,COALESCE(u.name,'') actor FROM order_payments p LEFT JOIN users u ON u.id=p.created_by WHERE p.id=?",(payment_id,)).fetchone()
    if not main or not pay or (pay['order_id'],pay['scope']) not in ((order_id,'equipo'),(main['id'],'general')):return None
    whole=group(c,order_id);unit=next(row for row in whole['units'] if row['id']==order_id)
    order=c.execute("SELECT o.id,cl.name client,COALESCE(cl.identification,'') identification,COALESCE(cl.email,'') email,d.brand,d.model,d.serial FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id WHERE o.id=?",(order_id,)).fetchone()
    general_scope=pay['scope']=='general';source=whole['totals'] if general_scope else unit
    account=dict({key:source[key] for key in ('budget_cents','paid_cents','balance_cents','credit_cents','state','state_label')},scope='de la orden' if general_scope or not whole['multiple'] else 'del equipo '+unit['unit_code'].split('-')[-1])
    info=dict(order,code=whole['main_code'] if general_scope or not whole['multiple'] else unit['unit_code'])
    if general_scope:info['brand'],info['model'],info['serial']='%d equipos de la orden'%len(whole['units']),'',''
    return {'order':info,'payment':dict(pay),'account':account}


def receivables(c,first,last):
    """Reporte financiero: saldos por cobrar (por equipo y consolidado por orden) y lo cobrado entre dos fechas (incluidas), por forma
    de pago. Todo sale de los mismos cargos y movimientos que la tarjeta del detalle; no hay cifras guardadas aparte."""
    units=[dict(r) for r in c.execute("SELECT o.id,COALESCE(o.code,'OP-'||printf('%05d',o.id)) code,COALESCE(o.group_id,o.id) main_id,o.group_id,o.unit_no,o.status status_code,s.label status,cl.name client,"
                                      "COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,"+BUDGET+" budget_cents,"+PAID+" paid_cents "
                                      "FROM orders o JOIN devices d ON d.id=o.device_id JOIN clients cl ON cl.id=d.client_id JOIN statuses s ON s.code=o.status ORDER BY o.id")]
    free={main:general(c,main)[1] for (main,) in c.execute("SELECT DISTINCT order_id FROM order_payments WHERE scope='general'").fetchall()}
    groups={};rows=[]
    for unit in units:
        unit.update(summary(unit['budget_cents'],unit['paid_cents']));groups.setdefault(unit['main_id'],[]).append(unit)
        if unit['balance_cents'] or unit['credit_cents']:rows.append({key:unit[key] for key in ('id','code','client','type','brand','model','status','status_code','budget_cents','paid_cents','balance_cents','credit_cents','state','state_label')})
    # Por cobrar consolidado: en cada orden, cargos menos pagos netos de sus equipos y menos sus pagos generales sin asignar (una sola vez).
    due=credit=0
    for main,members in groups.items():
        net=sum(m['budget_cents']-m['paid_cents'] for m in members)-free.get(main,0)
        if net>0:due+=net
        else:credit-=net
    rows.sort(key=lambda row:(-row['balance_cents'],-row['credit_cents'],row['id']))
    moves=[dict(r) for r in c.execute("SELECT method,kind,COUNT(*) total,SUM(amount_cents) cents FROM order_payments WHERE voided_at IS NULL AND substr(created_at,1,10)>=? AND substr(created_at,1,10)<=? GROUP BY method,kind",(first.isoformat(),last.isoformat()))]
    methods=[]
    for code,label in METHODS.items():
        paid=sum(m['cents'] for m in moves if m['method']==code and m['kind']=='pago');back=sum(m['cents'] for m in moves if m['method']==code and m['kind']=='devolucion')
        if paid or back:methods.append({'code':code,'label':label,'paid_cents':paid,'refunded_cents':back,'net_cents':paid-back,'count':sum(m['total'] for m in moves if m['method']==code)})
    paid=sum(m['paid_cents'] for m in methods);back=sum(m['refunded_cents'] for m in methods)
    return {'from':first.isoformat(),'to':last.isoformat(),'receivable_cents':due,'credit_cents':credit,'general_cents':sum(v for v in free.values() if v>0),'units_due':sum(1 for row in rows if row['balance_cents']),
            'rows':rows[:200],'total_rows':len(rows),'collected':{'paid_cents':paid,'refunded_cents':back,'net_cents':paid-back,'methods':methods}}


def client_history(c,client_id):
    """Historial de equipos del cliente: cada equipo con su identidad permanente y todos sus ingresos."""
    devices=[dict(r) for r in c.execute("SELECT d.id,d.code,COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,d.serial,d.color FROM devices d WHERE d.client_id=? ORDER BY d.id DESC",(client_id,))]
    visits={}
    for row in c.execute("SELECT o.id,o.code,o.device_id,o.group_id,o.unit_no,o.status status_code,s.label status,o.received_at,o.delivered_at,o.problem,o.findings,o.recommendations,"+BUDGET+" budget_cents,"+PAID+" paid_cents,"
                         "(SELECT m.due_date FROM maintenance m WHERE m.order_id=o.id ORDER BY m.id DESC LIMIT 1) maintenance_due "
                         "FROM orders o JOIN devices d ON d.id=o.device_id JOIN statuses s ON s.code=o.status WHERE d.client_id=? ORDER BY o.id DESC",(client_id,)):
        item=dict(row);item['code']=item['code'] or 'OP-'+str(item['id']).zfill(5)
        visits.setdefault(item.pop('device_id'),[]).append(item)
    for device in devices:
        device['orders']=visits.get(device['id'],[])
        device['open']=sum(1 for item in device['orders'] if item['status_code']!='entregado')
    return devices
