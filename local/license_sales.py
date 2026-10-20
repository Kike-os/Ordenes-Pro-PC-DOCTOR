"""Ventas de licencias, independientes de las órdenes técnicas.

Una venta (VLIC-AAAAMMDD-0001) pertenece a un cliente y puede tener varios productos con su cantidad, precio y descuento autorizado.
Al registrarla se reservan claves concretas del inventario (ninguna otra venta puede tomarlas); al entregarla pasan a «Entregada» y el
cliente las consulta con su enlace privado (identificación + código). Vincular una orden técnica es opcional.

Estados separados: comercial (Pendiente de pago, Pago parcial, Pagado) según los pagos CONFIRMADOS, y de entrega (Pendiente de entrega,
Entregado). Una venta cancelada queda como «Cancelado» en ambos y libera sus claves. Nada se borra: los pagos se anulan con motivo."""
import base64,re
from datetime import timedelta

import licenses
from licenses import LicenseError,stamp,usd

METHODS={'efectivo':'Efectivo','transferencia':'Transferencia','deposito':'Depósito','tarjeta':'Tarjeta','otro':'Otro'}
PAYMENT={'pendiente':'Pendiente de pago','parcial':'Pago parcial','pagado':'Pagado','cancelado':'Cancelado'}
DELIVERY={'pendiente':'Pendiente de entrega','entregado':'Entregado','cancelado':'Cancelado'}
PAYMENT_STATES={'por_confirmar':'Por confirmar','confirmado':'Confirmado','anulado':'Anulado'}
MAX_LINES=20
MAX_QUANTITY=50
RECEIPT_TYPES={'application/pdf':b'%PDF','image/png':b'\x89PNG','image/jpeg':b'\xff\xd8\xff'}


def _admin(user):
    if user['role']!='administrador':raise LicenseError('Solo administración gestiona las ventas de licencias.',403)


def _log(c,sale_id,name,detail,user,now):
    c.execute('INSERT INTO license_sale_events(sale_id,event,detail,actor_id,created_at) VALUES (?,?,?,?,?)',(sale_id,name,detail[:500],user['id'] if user else None,stamp(now)))


def next_code(c,now):
    """Número consecutivo diario. Se calcula dentro de la transacción de escritura (BEGIN IMMEDIATE): dos ventas no reciben el mismo."""
    prefix='VLIC-'+now.strftime('%Y%m%d')+'-'
    last=c.execute('SELECT MAX(code) FROM license_sales WHERE code LIKE ?',(prefix+'%',)).fetchone()[0]
    number=int(last[-4:])+1 if last else 1
    if number>9999:raise LicenseError('Se alcanzó el máximo de ventas de licencias del día.',409)
    return prefix+'%04d'%number


def sale_row(c,sale_id):
    row=c.execute('SELECT * FROM license_sales WHERE id=?',(sale_id,)).fetchone()
    if not row:raise LicenseError('Venta no disponible.',404)
    return dict(row)


def _paid(c,sale_id,status='confirmado'):
    return c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM license_sale_payments WHERE sale_id=? AND status=?',(sale_id,status)).fetchone()[0]


def refresh(c,sale_id,now):
    """Estado comercial según los pagos confirmados. «Pagado» solo cuando lo confirmado cubre el total."""
    sale=sale_row(c,sale_id)
    if sale['payment_status']=='cancelado':return sale['payment_status']
    paid=_paid(c,sale_id)
    status='pagado' if paid>=sale['total_cents'] else 'parcial' if paid>0 else 'pendiente'
    c.execute('UPDATE license_sales SET payment_status=?,updated_at=? WHERE id=?',(status,stamp(now),sale_id))
    return status


def _items(data):
    lines=data.get('items')
    if not isinstance(lines,list) or not lines:raise LicenseError('Agrega al menos un producto a la venta.',fields={'items':'Carrito vacío.'})
    if len(lines)>MAX_LINES:raise LicenseError('Una venta admite hasta %d productos distintos.'%MAX_LINES,fields={'items':'Demasiados productos.'})
    out=[];seen=set()
    for line in lines:
        if not isinstance(line,dict):raise LicenseError('Partida no válida.',fields={'items':'Partida no válida.'})
        pid=str(line.get('product_id') or '');qty=str(line.get('quantity') or '')
        if not pid.isdigit():raise LicenseError('Selecciona el producto.',fields={'items':'Producto no válido.'})
        if int(pid) in seen:raise LicenseError('Un producto aparece dos veces en el carrito: ajusta su cantidad.',fields={'items':'Producto repetido.'})
        if not qty.isdigit() or not 1<=int(qty)<=MAX_QUANTITY:raise LicenseError('La cantidad debe estar entre 1 y %d.'%MAX_QUANTITY,fields={'items':'Cantidad no válida.'})
        seen.add(int(pid));out.append({'product_id':int(pid),'quantity':int(qty),'price':line.get('price'),'discount':line.get('discount')})
    return out


def _receipt(data,prefix='receipt'):
    """Comprobante adjunto (base64): JPG, PNG o PDF, comprobado por su contenido y no solo por el nombre."""
    content=str(data.get(prefix) or '')
    if not content:return None
    mime=str(data.get(prefix+'_type') or '')
    if mime not in RECEIPT_TYPES:raise LicenseError('El comprobante debe ser JPG, PNG o PDF.',fields={prefix:'Formato no admitido.'})
    try:raw=base64.b64decode(content,validate=True)
    except Exception:raise LicenseError('El comprobante no se pudo leer.',fields={prefix:'Archivo dañado.'})
    if len(raw)>licenses.RECEIPT_LIMIT:raise LicenseError('El comprobante supera 1,5 MB.',fields={prefix:'Archivo demasiado grande.'})
    if not raw.startswith(RECEIPT_TYPES[mime]):raise LicenseError('El archivo no corresponde a un JPG, PNG o PDF válido.',fields={prefix:'Contenido no válido.'})
    name=re.sub(r'[^\w.\- ]+','',str(data.get(prefix+'_name') or 'comprobante'))[:120] or 'comprobante'
    return name,mime,raw


def create(c,data,user,now):
    """Registra la venta y reserva sus claves. Todo o nada: si falta existencia de un producto no se reserva ninguna."""
    _admin(user)
    cid=str(data.get('client_id') or '')
    if not cid.isdigit() or not c.execute('SELECT 1 FROM clients WHERE id=?',(int(cid),)).fetchone():raise LicenseError('Selecciona el cliente de la venta.',fields={'client_id':'Cliente obligatorio.'})
    client=int(cid);order=None
    if data.get('link_order') is True:
        code=str(data.get('order_code') or '').strip()
        if not code:raise LicenseError('Indica la orden técnica que quieres vincular.',fields={'order_code':'Orden obligatoria si la vinculas.'})
        client,order,_=licenses._resolve_order(c,client,code,'')
    licenses.expire(c,now);today=now.date().isoformat();moment=stamp(now)
    lines=[]
    for line in _items(data):
        product=licenses._product(c,line['product_id'])
        if not c.execute('SELECT 1 FROM license_products WHERE item_id=?',(product['id'],)).fetchone():raise LicenseError('«%s» no tiene inventario de licencias.'%product['name'],fields={'items':'Producto sin inventario.'})
        if not product['available']:raise LicenseError('«%s» está desactivado.'%product['name'],fields={'items':'Producto desactivado.'})
        price=licenses._cents(line['price'],'items','el precio de «%s»'%product['name'])
        if price is None:price=product['price_cents'] or 0
        discount=licenses._cents(line['discount'],'items','el descuento de «%s»'%product['name']) or 0
        if discount>price*line['quantity']:raise LicenseError('El descuento de «%s» supera su subtotal.'%product['name'],fields={'items':'Descuento mayor que el subtotal.'})
        free=c.execute("SELECT id FROM license_units WHERE product_id=? AND status='disponible' AND (expires_at='' OR expires_at>=?) ORDER BY expires_at='',expires_at,id LIMIT ?",(product['id'],today,line['quantity'])).fetchall()
        if len(free)<line['quantity']:
            raise LicenseError('Solo hay %d %s de «%s».'%(len(free),'licencia disponible' if len(free)==1 else 'licencias disponibles',product['name']),409,{'items':'Sin existencias suficientes.'})
        lines.append(dict(line,product=product,price=price,discount=discount,units=[r['id'] for r in free]))
    subtotal=sum(l['price']*l['quantity'] for l in lines);discount=sum(l['discount'] for l in lines)
    notes=licenses._text(data,'notes',300,'Las observaciones')
    code=next_code(c,now)
    sale=c.execute('INSERT INTO license_sales(code,client_id,order_id,subtotal_cents,discount_cents,total_cents,notes,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (code,client,order,subtotal,discount,subtotal-discount,notes,user['id'],moment,moment)).lastrowid
    for position,line in enumerate(lines):
        item=c.execute('INSERT INTO license_sale_items(sale_id,product_id,product_name,quantity,unit_price_cents,discount_cents,position) VALUES (?,?,?,?,?,?,?)',
                       (sale,line['product']['id'],line['product']['name'],line['quantity'],line['price'],line['discount'],position)).lastrowid
        for unit in line['units']:
            # La condición status='disponible' impide que dos ventas simultáneas reserven la misma clave.
            if not c.execute("UPDATE license_units SET status='reservada',client_id=?,sale_id=?,sale_item_id=?,reserved_at=?,updated_at=? WHERE id=? AND status='disponible'",(client,sale,item,moment,moment,unit)).rowcount:
                raise LicenseError('Una licencia dejó de estar disponible mientras se registraba la venta. Vuelve a intentarlo.',409)
            licenses.event(c,'reservada',now,'Reservada para la venta %s.'%code,unit,line['product']['id'],client=client,user=user)
    _log(c,sale,'creada','Venta registrada: '+', '.join('%d × %s'%(l['quantity'],l['product']['name']) for l in lines)+'. Total %s.'%usd(subtotal-discount)+(' Vinculada a la orden %s.'%data.get('order_code','').strip().upper() if order else ''),user,now)
    payment=data.get('payment')
    if isinstance(payment,dict) and str(payment.get('amount') or '').strip():add_payment(c,sale,payment,user,now)
    else:refresh(c,sale,now)
    return sale


def add_payment(c,sale_id,data,user,now):
    """Registra un pago (completo o parcial). «Confirmado» solo si quien lo registra lo verificó; si no, queda «Por confirmar» y no cuenta."""
    _admin(user);sale=sale_row(c,sale_id)
    if sale['payment_status']=='cancelado':raise LicenseError('La venta está cancelada.',409)
    amount=licenses._cents(data.get('amount'),'amount','el monto recibido')
    if not amount:raise LicenseError('Indica el monto recibido.',fields={'amount':'Monto obligatorio.'})
    method=str(data.get('method') or '')
    if method not in METHODS:raise LicenseError('Selecciona el método de pago.',fields={'method':'Método obligatorio.'})
    paid_on=licenses._date(data.get('paid_on') or now.date().isoformat(),'paid_on',now.date(),future=False)
    reference=licenses._text(data,'reference',80,'La referencia');notes=licenses._text(data,'notes',200,'La nota del pago')
    if method in ('transferencia','deposito') and not reference and not data.get('receipt'):raise LicenseError('Indica la referencia o adjunta el comprobante de la transferencia.',fields={'reference':'Referencia o comprobante obligatorio.'})
    pending=_paid(c,sale_id)+_paid(c,sale_id,'por_confirmar');balance=sale['total_cents']-pending
    if amount>balance:raise LicenseError('El pago supera el saldo pendiente (%s).'%usd(max(balance,0)),fields={'amount':'Mayor que el saldo.'})
    receipt=_receipt(data);confirmed=data.get('confirmed') is True;moment=stamp(now)
    payment=c.execute('INSERT INTO license_sale_payments(sale_id,amount_cents,method,reference,paid_on,status,notes,created_by,created_at,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                      (sale_id,amount,method,reference,paid_on,'confirmado' if confirmed else 'por_confirmar',notes,user['id'],moment,user['id'] if confirmed else None,moment if confirmed else '')).lastrowid
    if receipt:c.execute('INSERT INTO license_payment_receipts(payment_id,name,mime,data,created_at,created_by) VALUES (?,?,?,?,?,?)',(payment,*receipt,moment,user['id']))
    _log(c,sale_id,'pago','Pago de %s por %s%s (%s)%s.'%(usd(amount),METHODS[method].lower(),', ref. '+reference if reference else '','confirmado' if confirmed else 'por confirmar',', con comprobante' if receipt else ''),user,now)
    refresh(c,sale_id,now);return payment


def _payment(c,sale_id,payment_id):
    row=c.execute('SELECT * FROM license_sale_payments WHERE id=? AND sale_id=?',(payment_id,sale_id)).fetchone()
    if not row:raise LicenseError('Pago no disponible.',404)
    return dict(row)


def confirm_payment(c,sale_id,payment_id,user,now):
    _admin(user);payment=_payment(c,sale_id,payment_id)
    if payment['status']!='por_confirmar':raise LicenseError('Este pago no está pendiente de confirmación.',409)
    c.execute("UPDATE license_sale_payments SET status='confirmado',confirmed_by=?,confirmed_at=? WHERE id=?",(user['id'],stamp(now),payment_id))
    _log(c,sale_id,'pago_confirmado','Pago de %s confirmado.'%usd(payment['amount_cents']),user,now);return refresh(c,sale_id,now)


def void_payment(c,sale_id,payment_id,reason,user,now):
    _admin(user);payment=_payment(c,sale_id,payment_id);reason=re.sub(r'\s+',' ',str(reason or '')).strip()
    if payment['status']=='anulado':raise LicenseError('El pago ya está anulado.',409)
    if len(reason)<5:raise LicenseError('Indica el motivo de la anulación.',fields={'reason':'Motivo obligatorio.'})
    c.execute("UPDATE license_sale_payments SET status='anulado',voided_by=?,voided_at=?,void_reason=? WHERE id=?",(user['id'],stamp(now),reason[:200],payment_id))
    _log(c,sale_id,'pago_anulado','Pago de %s anulado. Motivo: %s'%(usd(payment['amount_cents']),reason[:200]),user,now);return refresh(c,sale_id,now)


def deliver(c,sale_id,data,user,now):
    """Entrega de la venta: las claves reservadas pasan a «Entregada» y se genera el enlace privado. Con saldo pendiente hay que
    aceptarlo expresamente (queda registrado). Devuelve (entrega, token)."""
    _admin(user);sale=sale_row(c,sale_id)
    if sale['delivery_status']=='cancelado':raise LicenseError('La venta está cancelada.',409)
    if sale['delivery_status']=='entregado':raise LicenseError('Esta venta ya fue entregada.',409)
    balance=sale['total_cents']-_paid(c,sale_id)
    if balance>0 and data.get('accept_balance') is not True:
        raise LicenseError('La venta tiene un saldo pendiente de %s. Para entregar igualmente, confírmalo expresamente.'%usd(balance),409,{'accept_balance':'Confirmación obligatoria.'})
    units=[dict(r) for r in c.execute("SELECT u.*,i.name product_name FROM license_units u JOIN catalog_items i ON i.id=u.product_id WHERE u.sale_id=? AND u.status='reservada' ORDER BY u.id",(sale_id,))]
    expected=c.execute('SELECT SUM(quantity) FROM license_sale_items WHERE sale_id=?',(sale_id,)).fetchone()[0]
    if len(units)!=expected:raise LicenseError('Faltan claves reservadas para esta venta. Revisa el inventario.',409)
    activation=licenses._date(data.get('activated_at'),'activated_at',now.date(),future=False) if data.get('activated') is True else ''
    if data.get('activated') is True and not activation:raise LicenseError('Indica la fecha real de activación.',fields={'activated_at':'Fecha obligatoria.'})
    moment=stamp(now);token=licenses.secrets.token_urlsafe(32);status=sale['payment_status']
    delivery=c.execute("INSERT INTO license_deliveries(order_id,client_id,kind,status,payment_confirmed_by,payment_confirmed_at,balance_cents,authorized_by,authorized_at,token_hash,token_expires_at,notes,price_cents,discount_cents,payment_status,created_at,updated_at) VALUES (?,?,'directa','autorizada',?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (sale['order_id'],sale['client_id'],user['id'],moment,max(balance,0),user['id'],moment,licenses._hash(token),stamp(now+timedelta(hours=licenses.LINK_HOURS)),'Venta '+sale['code'],sale['subtotal_cents'],sale['discount_cents'],status if status in ('pagado','parcial','pendiente') else '',moment,moment)).lastrowid
    for unit in units:
        if not c.execute("UPDATE license_units SET status='entregada',delivered_at=?,delivery_id=?,order_id=COALESCE(order_id,?),updated_at=? WHERE id=? AND status='reservada' AND sale_id=?",
                         (moment,delivery,sale['order_id'],moment,unit['id'],sale_id)).rowcount:
            raise LicenseError('Una licencia cambió de estado mientras se entregaba. Vuelve a intentarlo.',409)
        licenses.event(c,'entregada',now,'Entregada en la venta %s%s.'%(sale['code'],' con saldo pendiente de %s aceptado'%usd(balance) if balance>0 else ''),unit['id'],unit['product_id'],delivery,sale['order_id'],sale['client_id'],user)
    if activation:
        for unit in units:licenses.confirm_activation(c,unit['id'],activation,user,now)
    c.execute("UPDATE license_sales SET delivery_status='entregado',delivered_at=?,delivered_by=?,delivery_id=?,updated_at=? WHERE id=?",(moment,user['id'],delivery,moment,sale_id))
    _log(c,sale_id,'entregada','Entrega confirmada de %d %s%s.%s'%(len(units),'licencia' if len(units)==1 else 'licencias',' con saldo pendiente de %s aceptado'%usd(balance) if balance>0 else '',' Activación registrada el %s.'%activation if activation else ' Pendiente de activación.'),user,now)
    if sale['order_id']:
        import order_workspace
        order_workspace.event(c,sale['order_id'],user['id'],now,'follow_up','Licencias entregadas en la venta %s: '%sale['code']+', '.join(u['code']+' ('+u['product_name']+')' for u in units)+'.')
    return delivery,token


def cancel(c,sale_id,reason,user,now):
    """Cancela una venta no entregada: libera sus claves. Si tiene pagos vigentes hay que anularlos antes (queda constancia)."""
    _admin(user);sale=sale_row(c,sale_id);reason=re.sub(r'\s+',' ',str(reason or '')).strip()
    if sale['delivery_status']=='entregado':raise LicenseError('Una venta entregada no se cancela: registra la devolución de cada licencia.',409)
    if sale['delivery_status']=='cancelado':raise LicenseError('La venta ya está cancelada.',409)
    if len(reason)<5:raise LicenseError('Indica el motivo de la cancelación.',fields={'reason':'Motivo obligatorio.'})
    if c.execute("SELECT 1 FROM license_sale_payments WHERE sale_id=? AND status!='anulado'",(sale_id,)).fetchone():
        raise LicenseError('La venta tiene pagos registrados: anúlalos primero (por ejemplo, tras el reembolso) para cancelarla.',409)
    for unit in c.execute("SELECT id FROM license_units WHERE sale_id=? AND status='reservada'",(sale_id,)).fetchall():
        licenses.release(c,unit['id'],user,now,from_sale=True);c.execute('UPDATE license_units SET sale_id=NULL,sale_item_id=NULL WHERE id=?',(unit['id'],))
    moment=stamp(now)
    c.execute("UPDATE license_sales SET payment_status='cancelado',delivery_status='cancelado',cancelled_at=?,cancelled_by=?,cancel_reason=?,updated_at=? WHERE id=?",(moment,user['id'],reason[:300],moment,sale_id))
    _log(c,sale_id,'cancelada','Venta cancelada; sus licencias vuelven al inventario. Motivo: '+reason[:300],user,now)


# ---- Consultas ------------------------------------------------------------------------------------------------------
def _summary(c,row):
    row=dict(row);paid=_paid(c,row['id']);pending=_paid(c,row['id'],'por_confirmar')
    items=[dict(r) for r in c.execute('SELECT product_id,product_name,quantity,unit_price_cents,discount_cents FROM license_sale_items WHERE sale_id=? ORDER BY position',(row['id'],))]
    row.update(paid_cents=paid,pending_cents=pending,balance_cents=max(row['total_cents']-paid,0),items=items,payment_label=PAYMENT[row['payment_status']],delivery_label=DELIVERY[row['delivery_status']],
               quantity=sum(i['quantity'] for i in items))
    return row


def sales(c,query='',payment='',delivery='',limit=300):
    sql=("SELECT s.*,cl.name client,COALESCE(cl.identification,'') identification,COALESCE(o.code,'') order_code FROM license_sales s JOIN clients cl ON cl.id=s.client_id "
         "LEFT JOIN orders o ON o.id=s.order_id WHERE 1=1")
    args=[]
    if payment in PAYMENT:sql+=' AND s.payment_status=?';args.append(payment)
    if delivery in DELIVERY:sql+=' AND s.delivery_status=?';args.append(delivery)
    for word in [w for w in re.sub(r'\s+',' ',str(query or '').lower()).split(' ') if w][:6]:
        sql+=" AND instr(lower(s.code||' '||cl.name||' '||COALESCE(cl.identification,'')||' '||COALESCE(o.code,'')||' '||(SELECT group_concat(product_name,' ') FROM license_sale_items i WHERE i.sale_id=s.id)),?)>0";args.append(word)
    return [_summary(c,r) for r in c.execute(sql+' ORDER BY s.id DESC LIMIT ?',(*args,limit))]


def detail(c,sale_id,now):
    row=c.execute("SELECT s.*,cl.name client,COALESCE(cl.identification,'') identification,COALESCE(cl.email,'') email,COALESCE(cl.phone,'') phone,COALESCE(o.code,'') order_code,"
                  "COALESCE(u.name,'') created_name,COALESCE(d.name,'') delivered_name FROM license_sales s JOIN clients cl ON cl.id=s.client_id LEFT JOIN orders o ON o.id=s.order_id "
                  "LEFT JOIN users u ON u.id=s.created_by LEFT JOIN users d ON d.id=s.delivered_by WHERE s.id=?",(sale_id,)).fetchone()
    if not row:raise LicenseError('Venta no disponible.',404)
    out=_summary(c,row);today=now.date()
    units=[]
    for unit in c.execute("SELECT u.id,u.code,u.product_id,i.name product,u.status,u.activated,u.activated_at,u.expires_at,u.delivered_at,u.renewed_to,u.devices,u.term,p.validity_mode "
                          "FROM license_units u JOIN catalog_items i ON i.id=u.product_id LEFT JOIN license_products p ON p.item_id=u.product_id WHERE u.sale_id=? ORDER BY u.id",(sale_id,)):
        unit=dict(unit);unit['state'],unit['days_left']=licenses.state_of(unit,today);unit['state_label']=licenses.STATES[unit['state']][0];units.append(unit)
    out['units']=units
    out['payments']=[dict(r,method_label=METHODS[r['method']],status_label=PAYMENT_STATES[r['status']]) for r in c.execute(
        "SELECT p.id,p.amount_cents,p.method,p.reference,p.paid_on,p.status,p.notes,p.created_at,p.confirmed_at,p.voided_at,p.void_reason,COALESCE(u.name,'') by_name,"
        "(SELECT 1 FROM license_payment_receipts r WHERE r.payment_id=p.id) has_receipt FROM license_sale_payments p LEFT JOIN users u ON u.id=p.created_by WHERE p.sale_id=? ORDER BY p.id",(sale_id,))]
    out['events']=[dict(r) for r in c.execute("SELECT e.event,e.detail,e.created_at,COALESCE(u.name,'Sistema') actor FROM license_sale_events e LEFT JOIN users u ON u.id=e.actor_id WHERE e.sale_id=? ORDER BY e.id DESC",(sale_id,))]
    link=c.execute('SELECT token_expires_at,reveal_count FROM license_deliveries WHERE id=?',(row['delivery_id'],)).fetchone() if row['delivery_id'] else None
    out['link_active']=bool(link and link['token_expires_at']>stamp(now));out['reveal_count']=link['reveal_count'] if link else 0
    out['contact']=licenses.CONTACT
    return out


def receipt_file(c,payment_id):
    return c.execute('SELECT name,mime,data FROM license_payment_receipts WHERE payment_id=?',(payment_id,)).fetchone()
