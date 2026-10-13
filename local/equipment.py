"""Varios equipos por orden, identidad permanente de cada equipo y pagos por equipo.

Cada equipo recibido es un ingreso propio (una fila de orders) con su fecha, diagnóstico, fotografías, técnico, presupuesto,
estado, pagos y entrega. Los ingresos de una misma orden se unen por group_id a la orden principal y se identifican como
<orden>-E01, <orden>-E02… El equipo físico conserva su identificador permanente EQ-0001 entre ingresos."""
from decimal import Decimal, InvalidOperation

METHODS={'efectivo':'Efectivo','transferencia':'Transferencia','tarjeta':'Tarjeta','deposito':'Depósito','otro':'Otro'}
MAX_UNITS=50
BUDGET="COALESCE((SELECT labor_cents+parts_cents+services_cents+digital_cents FROM order_budget b WHERE b.order_id=o.id),0)"
PAID="COALESCE((SELECT SUM(amount_cents) FROM order_payments p WHERE p.order_id=o.id AND p.voided_at IS NULL),0)"


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


def money(c,order_id):
    row=c.execute('SELECT '+BUDGET+' budget,'+PAID+' paid FROM orders o WHERE o.id=?',(order_id,)).fetchone()
    budget,paid=(row['budget'],row['paid']) if row else (0,0)
    return {'budget_cents':budget,'paid_cents':paid,'balance_cents':max(0,budget-paid)}


def usd(cents):
    return '$%d.%02d'%(cents//100,cents%100)


def delivery_block(c,order_id):
    """Mensaje que impide entregar un equipo con saldo pendiente; None si se puede entregar."""
    state=money(c,order_id)
    if state['balance_cents']<=0:return None
    return 'No se puede entregar: este equipo tiene un saldo pendiente de '+usd(state['balance_cents'])+'. Registra el pago antes de entregarlo.'


def payments(c,order_id):
    return [dict(r) for r in c.execute("SELECT p.id,p.amount_cents,p.method,p.note,p.created_at,p.voided_at,p.void_reason,COALESCE(u.name,'') actor FROM order_payments p LEFT JOIN users u ON u.id=p.created_by WHERE p.order_id=? ORDER BY p.id",(order_id,))]


def add_payment(c,order_id,data,user,now):
    if not c.execute('SELECT 1 FROM orders WHERE id=?',(order_id,)).fetchone():return 404,{'error':'Orden no disponible.'}
    errors={}
    try:
        amount=Decimal(str(data.get('amount','')).replace(',','.'))
        if not amount.is_finite() or amount<=0 or amount>Decimal('9999999.99') or amount.as_tuple().exponent<-2:raise InvalidOperation()
        cents=int(amount*100)
    except (InvalidOperation,ValueError):errors['amount']='Indica un importe mayor que cero con hasta dos decimales.';cents=0
    method=str(data.get('method',''))
    if method not in METHODS:errors['method']='Selecciona la forma de pago.'
    note=str(data.get('note','')).strip()
    if len(note)>300:errors['note']='La nota admite hasta 300 caracteres.'
    state=money(c,order_id)
    if not errors and cents>state['balance_cents']:
        errors['amount']='El pago supera el saldo pendiente de este equipo ('+usd(state['balance_cents'])+').' if state['budget_cents'] else 'Este equipo todavía no tiene presupuesto: regístralo antes de cobrar.'
    if errors:return 400,{'error':next(iter(errors.values())),'fields':errors}
    pid=c.execute('INSERT INTO order_payments(order_id,amount_cents,method,note,created_by,created_at) VALUES (?,?,?,?,?,?)',(order_id,cents,method,note,user['id'],now.isoformat(timespec='seconds'))).lastrowid
    return 201,{'ok':True,'id':pid,**money(c,order_id)}


def void_payment(c,order_id,data,user,now):
    pid=str(data.get('payment_id',''));reason=str(data.get('reason','')).strip()
    row=c.execute('SELECT id,voided_at FROM order_payments WHERE id=? AND order_id=?',(pid,order_id)).fetchone() if pid.isdigit() else None
    if not row:return 404,{'error':'Pago no disponible.'}
    if row['voided_at']:return 409,{'error':'Este pago ya estaba anulado.'}
    if not 5<=len(reason)<=300:return 400,{'error':'Indica el motivo de la anulación (entre 5 y 300 caracteres).','fields':{'reason':'Motivo obligatorio.'}}
    if c.execute("SELECT status FROM orders WHERE id=?",(order_id,)).fetchone()['status']=='entregado':return 409,{'error':'El equipo ya fue entregado: no se anulan pagos de una entrega registrada.'}
    c.execute('UPDATE order_payments SET voided_at=?,voided_by=?,void_reason=? WHERE id=?',(now.isoformat(timespec='seconds'),user['id'],reason,row['id']))
    return 200,{'ok':True,**money(c,order_id)}


UNIT_SQL=("SELECT o.id,o.code,o.group_id,o.unit_no,o.status status_code,s.label status,o.received_at,o.delivered_at,o.problem,d.id device_id,d.code device_code,"
          "COALESCE(NULLIF(d.kind,''),d.category) type,d.brand,d.model,d.serial,d.color,COALESCE((SELECT name FROM users WHERE id=o.assigned_to),'Sin asignar') responsible,"
          +BUDGET+" budget_cents,"+PAID+" paid_cents FROM orders o JOIN devices d ON d.id=o.device_id JOIN statuses s ON s.code=o.status ")


def group(c,order_id):
    """Equipos de la orden a la que pertenece un ingreso, con su resumen económico consolidado."""
    main=root(c,order_id)
    if not main:return None
    rows=[dict(r) for r in c.execute(UNIT_SQL+'WHERE o.group_id=? ORDER BY o.unit_no',(main['id'],))] if main['group_id'] else [dict(r) for r in c.execute(UNIT_SQL+'WHERE o.id=?',(main['id'],))]
    main_code=code_of(main)
    for row in rows:
        row['code']=row['code'] or 'OP-'+str(row['id']).zfill(5)
        row['unit_code']=main_code+'-E%02d'%row['unit_no']
        row['balance_cents']=max(0,row['budget_cents']-row['paid_cents'])
    return {'main_id':main['id'],'main_code':main_code,'multiple':len(rows)>1,'units':rows,
            'totals':{'budget_cents':sum(r['budget_cents'] for r in rows),'paid_cents':sum(r['paid_cents'] for r in rows),'balance_cents':sum(r['balance_cents'] for r in rows),
                      'delivered':sum(1 for r in rows if r['status_code']=='entregado'),'units':len(rows)}}


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
