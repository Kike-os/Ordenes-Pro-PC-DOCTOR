'use strict';
// ---- Centro de Ventas ------------------------------------------------------------------------------------------------------------
// Reúne lo que ya existe sin duplicarlo: la factura directa (con inventario, series, caja y pago mixto), las cotizaciones y proformas,
// las ventas de licencias, las ventas registradas en el inventario y los cobros. Lo propio son los pedidos comerciales, el panel y los
// reportes. La facturación electrónica sigue en ambiente de pruebas; nada se borra (se anula el borrador o se emite nota de crédito).
Object.assign(invIcons,{wrench:'<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>'});
const salesState={tab:'panel',q:'',kind:'',state:'',user:'',from:'',to:'',group:'dia',rfrom:'',rto:'',req:'abiertos',reqQ:''};
const salesGroups=[['Resumen',[['panel','Panel de ventas','layout-dashboard']]],
 ['Vender',[['nueva','Nueva venta','shopping-cart'],['cotizaciones','Cotizaciones y proformas','file-text'],['pedidos','Pedidos comerciales','truck']]],
 ['Seguimiento',[['historial','Historial de ventas','scroll-text'],['licencias','Ventas de licencias','key-round'],['cobros','Cobros','coins'],['reportes','Reportes','chart-column']]]];
const salesTabs=salesGroups.flatMap(([,items])=>items);
const salesTone={pagada:'autorizado',por_cobrar:'pendiente',anulada:'descartado',sin_cobro:'borrador'};
const salesRequestTone={solicitado:'borrador',pedido_proveedor:'enviado',recibido:'pendiente',entregado:'autorizado',cancelado:'descartado'};
function salesGo(tab){salesState.tab=tab;renderSalesCenter().then(()=>$('module-content').querySelector('.ic-nav [aria-current=page]')?.focus());}
function salesReload(){if(document.querySelector('.sv-shell'))renderSalesCenter();}
async function renderSalesCenter(){const root=$('module-content');const tab=salesTabs.find(t=>t[0]===salesState.tab)||salesTabs[0];salesState.tab=tab[0];
 const shell=el('div',undefined,'inv-module ic-module ic-shell sv-shell'),main=el('div',undefined,'ic-main'),panel=el('div',undefined,'inv-panel');panel.setAttribute('aria-label',tab[1]);panel.id='sv-section';
 shell.dataset.collapsed=String(!!centerPref('sv-nav-collapsed',false));main.append(panel);shell.append(salesNav(),main);root.replaceChildren(shell);
 const run={panel:salesPanel,nueva:salesNew,cotizaciones:proformasPanel,pedidos:salesRequests,historial:salesHistory,licencias:salesLicenses,cobros:salesPayments,reportes:salesReports}[tab[0]];
 panel.append(el('p','Cargando…','empty-module'));try{await run(panel);}catch(error){panel.replaceChildren(el('p',error.message,'empty-module'));}}
function salesNav(){const nav=el('nav',undefined,'ic-nav');nav.setAttribute('aria-label','Secciones del Centro de Ventas');const current=salesTabs.find(t=>t[0]===salesState.tab);
 const toggle=button('',()=>{const shell=nav.closest('.ic-shell');const next=shell.dataset.collapsed!=='true';shell.dataset.collapsed=String(next);centerSetPref('sv-nav-collapsed',next);toggle.setAttribute('aria-expanded',String(!next));},'ic-nav-collapse');
 toggle.setAttribute('aria-label','Plegar o desplegar el menú');toggle.setAttribute('aria-expanded',String(!centerPref('sv-nav-collapsed',false)));toggle.append(invIcon('panel-left'));
 const mobile=button('',()=>{const open_=nav.dataset.open!=='true';nav.dataset.open=String(open_);mobile.setAttribute('aria-expanded',String(open_));},'ic-nav-mobile');mobile.setAttribute('aria-expanded','false');mobile.setAttribute('aria-controls','sv-nav-groups');
 mobile.append(invIcon(current[2]),el('span',current[1]),invIcon('chevron-down'));
 const groups=el('div',undefined,'ic-nav-groups');groups.id='sv-nav-groups';
 for(const[title,items]of salesGroups){const g=el('div',undefined,'ic-nav-group');g.append(el('p',title,'ic-nav-title'));
  for(const[key,label,icon]of items){const b=button('',()=>{nav.dataset.open='false';if(salesState.tab!==key)salesGo(key);},'ic-nav-item');b.dataset.tab=key;b.title=label;if(key===salesState.tab)b.setAttribute('aria-current','page');
   b.append(invIcon(icon),el('span',label));g.append(b);}groups.append(g);}
 nav.addEventListener('keydown',event=>{if(event.key==='Escape'&&nav.dataset.open==='true'){nav.dataset.open='false';mobile.setAttribute('aria-expanded','false');mobile.focus();}});
 nav.append(mobile,toggle,groups);return nav;}
function salesKpis(list){const grid=el('div',undefined,'inv-kpis ic-kpis sv-kpis');for(const[icon,label,value,hint,tone,go]of list){const card=button('',()=>go&&go(),'inv-kpi ic-kpi');if(!go)card.disabled=true;if(tone)card.dataset.tone=tone;
  const mark=el('span',undefined,'inv-kpi-icon'),body=el('div');mark.append(invIcon(icon));body.append(el('small',label),el('strong',value));if(hint)body.append(el('em',hint));card.append(mark,body);card.setAttribute('aria-label',label+': '+value+(go?'. Ver detalle':''));grid.append(card);}return grid;}
const salesToday=()=>new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10);
function salesFilter(values){Object.assign(salesState,{q:'',kind:'',state:'',user:'',from:'',to:''},values);salesGo('historial');}
// Abre la venta en la ventana que ya la gestiona (proforma, venta de licencias o factura).
async function salesOpen(row,refresh){try{if(row.kind==='licencia'){if(!licenseMeta)await licenseLoadMeta();licenseSaleView(row.id,refresh);}else if(row.kind==='inventario'){if(row.invoice_id)openInvoice(row.invoice_id);else toast('Venta registrada en el inventario sin factura. Puedes facturarla desde Inventario → Movimientos.','info');}else proformaDetail(row.id,refresh);}
 catch(error){toast(error.message,'error');}}
function salesRowsTable(rows,refresh,compact=false){const cols=compact?['Fecha','Venta','Cliente','Total','Estado']:['Fecha','Venta','Cliente','Total','Pagado','Saldo','Estado','Factura','Acciones'];
 return centerTable(cols,rows.map(r=>{const code=el('div',undefined,'sv-code');code.append(button(r.code,()=>salesOpen(r,refresh),'text-action'),el('small',r.kind_label+(r.detail?' · '+r.detail:'')+(r.delivery==='pendiente'?' · por entregar':''),'ic-muted'));
  const state=invoiceChip(salesTone[r.state],r.state_label),invoice=r.invoice_id?button(r.invoice_number||r.invoice_label,()=>openInvoice(r.invoice_id),'text-action'):el('span','Sin factura','ic-muted');
  if(compact)return centerRow([['Fecha',formatOrderDate(r.at)],['Venta',code],['Cliente',r.client],['Total',centerMoney(r.total_cents)],['Estado',state]]);
  const menu=centerMenu('Acciones de '+r.code,[['Imprimir comprobante',()=>salesReceipt(r.kind,r.id)],['Ver la venta',()=>salesOpen(r,refresh)],r.invoice_id&&['Ver la factura',()=>openInvoice(r.invoice_id)],r.client_id&&['Ver el cliente',()=>{if(typeof openClientQuick==='function')openClientQuick(r.client_id);else go('clients',new URLSearchParams({id:r.client_id}));}]]);
  return centerRow([['Fecha',formatOrderDate(r.at)],['Venta',code],['Cliente',r.client],['Total',centerMoney(r.total_cents)],['Pagado',r.kind==='inventario'?'—':centerMoney(r.paid_cents)],['Saldo',r.balance_cents?centerMoney(r.balance_cents):'—'],['Estado',state],['Factura',invoice],['Acciones',salesActions(r,menu)]]);}),'sv-table'+(compact?' sv-compact':''));}
function salesActions(r,menu){const box=el('div',undefined,'sv-acts'),print=invIconBtn('Imprimir comprobante de '+r.code,'printer',()=>salesReceipt(r.kind,r.id));print.classList.add('sv-print');box.append(print,menu);return box;}

// ---- Panel ----
async function salesPanel(panel){const d=await api('/api/sales/dashboard'),today=salesToday(),month=today.slice(0,8)+'01';panel.replaceChildren();
 const quick=el('div',undefined,'inv-actions sv-quick');quick.append(invBtn('Nueva venta','shopping-cart',()=>invoiceComposer(null,salesReload),'primary'),invBtn('Vender licencias','key-round',()=>salesLicenseSale()),invBtn('Nueva cotización','file-text',()=>proformaComposer(null,salesReload)),invBtn('Nuevo pedido','truck',()=>salesRequestDialog()));
 panel.append(invSectionHead('Panel de ventas','Ventas confirmadas: facturas directas, cotizaciones convertidas, licencias y ventas del inventario. No incluye las órdenes técnicas.'),quick);
 const p=d.pending,parts=[p.drafts&&p.drafts+' sin confirmar',p.to_emit&&p.to_emit+' por facturar',p.to_deliver&&p.to_deliver+' licencias por entregar',p.requests&&p.requests+' pedidos abiertos'].filter(Boolean);
 panel.append(salesKpis([['circle-dollar-sign','Ventas del día',centerMoney(d.today.total_cents),d.today.count+(d.today.count===1?' venta':' ventas'),'',()=>salesFilter({from:today,to:today})],
  ['chart-column','Ventas del mes',centerMoney(d.month.total_cents),d.month.count+(d.month.count===1?' venta':' ventas'),'',()=>salesFilter({from:month,to:today})],
  ['receipt-text','Total facturado (mes)',centerMoney(d.invoiced.total_cents),d.invoiced.count+' comprobantes'+(d.invoiced.test_mode?' · ambiente de pruebas':''),'',null],
  ['clock','Ventas pendientes',String(p.count),parts.join(' · ')||'Nada pendiente',p.count?'warn':'',()=>salesGo(p.requests&&!p.drafts&&!p.to_emit&&!p.to_deliver?'pedidos':'historial')],
  ['coins','Cobros pendientes',centerMoney(d.collections.total_cents),d.collections.count+(d.collections.count===1?' venta con saldo':' ventas con saldo'),d.collections.count?'warn':'',()=>salesFilter({state:'por_cobrar'})]]));
 const grid=el('div',undefined,'sv-grid'),top=el('section',undefined,'inv-card sv-card'),last=el('section',undefined,'inv-card sv-card');
 top.append(el('h4','Productos más vendidos (mes)'));if(d.top.length)top.append(centerTable(['Producto','Cantidad','Total'],d.top.map(t=>centerRow([['Producto',t.name],['Cantidad',String(t.quantity)],['Total',centerMoney(t.total_cents)]])),'sv-table sv-compact'));else top.append(el('p','Aún no hay ventas este mes.','ic-muted'));
 last.append(el('h4','Últimas transacciones'));if(d.latest.length)last.append(salesRowsTable(d.latest,()=>salesGo('panel'),true));else last.append(el('p','Todavía no hay ventas registradas.','ic-muted'));
 grid.append(top,last);panel.append(grid);}

// ---- Nueva venta: cada camino abre la ventana que ya existe ----
async function salesLicenseSale(preset={}){try{if(!licenseMeta)await licenseLoadMeta();licenseSaleDialog(preset);}catch(error){toast(error.message,'error');}}
function salesNew(panel){panel.replaceChildren(invSectionHead('Nueva venta','Elige qué vas a vender. Confirmar una venta exige la caja abierta (si está configurada así); la factura electrónica se genera en ambiente de pruebas.'));
 const list=el('div',undefined,'sv-starts');
 for(const[icon,title,text,run]of [['shopping-cart','Productos y servicios','Inventario con existencias y series, catálogo o partidas libres; cobro en efectivo, transferencia, depósito, tarjeta (DATAFAST), crédito o pago mixto.',()=>invoiceComposer(null,salesReload)],
  ['key-round','Licencias digitales','Elige el cliente y licencias disponibles y vigentes; cobra ahora o después y entrega con enlace privado. Una licencia vendida no se vende otra vez.',()=>salesLicenseSale()],
  ['file-text','Desde una cotización','Convierte una cotización aprobada en venta. Los anticipos registrados se aplican a la factura.',()=>salesGo('cotizaciones')],
  ['wrench','Desde una orden técnica','Lleva a facturación los conceptos de una orden sin copiarlos: usa el borrador de factura de la orden, o el mismo si ya existe.',()=>salesFromOrder()]]){
  const card=button('',run,'sv-start');const mark=el('span',undefined,'inv-kpi-icon');mark.append(invIcon(icon));const copy=el('span');copy.append(el('strong',title),el('small',text));card.append(mark,copy);list.append(card);}
 panel.append(list,el('p','La clave de una licencia solo la ven quienes tienen permiso; nunca aparece en los comprobantes. Para anular una venta se descarta su borrador de factura (los productos vuelven al inventario) o se emite una nota de crédito.','inv-form-note'));}
function salesFromOrder(){centerPrompt('Venta desde una orden técnica',{note:'Los conceptos y pagos salen de la orden; no se duplican. Si la orden ya tiene factura vigente, se abre esa.',fields:[['order_code','Número de orden',{required:true,max:40,hint:'Por ejemplo, PCD-20261102-0001.'}]],submit:'Abrir factura'},
 async v=>{const r=await api('/api/sales/from-order',{order_code:v.order_code.trim()});toast('Factura de la orden lista en borrador.','success');openInvoice(r.invoice_id);});}

// ---- Historial ----
async function salesHistory(panel){const s=salesState,params={q:s.q,kind:s.kind,state:s.state,user:s.user,from:s.from,to:s.to};const data=await api('/api/sales/history?'+new URLSearchParams(params));panel.replaceChildren(invSectionHead('Historial de ventas','Las ventas anuladas se conservan con su estado. Abre cada venta para ver sus pagos, entrega y factura.',invBtn('Nueva venta','shopping-cart',()=>salesGo('nueva'),'primary inv-add')));
 const bar=el('div',undefined,'sp-bar sv-bar'),box=el('label',undefined,'inv-search sp-search'),search=el('input');search.type='search';search.value=s.q;search.placeholder='Venta o cliente';search.setAttribute('aria-label','Buscar venta');box.append(invIcon('search'),search);
 let timer;search.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{s.q=search.value.trim();salesHistory(panel).then(()=>{const f=panel.querySelector('input[type=search]');f.focus();f.setSelectionRange(f.value.length,f.value.length);});},300);});
 const select=(label,key,options)=>{const node=el('select');node.setAttribute('aria-label',label);for(const[v,t]of options)node.add(new Option(t,v));node.value=s[key];node.addEventListener('change',()=>{s[key]=node.value;salesHistory(panel);});return node;};
 const date=(label,key)=>{const wrap=el('label',undefined,'sv-date'),node=el('input');node.type='date';node.value=s[key];node.max=salesToday();node.addEventListener('change',()=>{s[key]=node.value;salesHistory(panel);});wrap.append(el('span',label),node);return wrap;};
 bar.append(box,select('Tipo de venta','kind',[['','Todos los tipos'],...Object.entries(data.kinds)]),select('Estado','state',[['','Todos los estados'],...Object.entries(data.states)]),select('Usuario','user',[['','Todos los usuarios'],...data.users.map(u=>[String(u.id),u.name])]),date('Desde','from'),date('Hasta','to'));
 if(Object.values(params).some(Boolean))bar.append(button('Quitar filtros',()=>salesFilter({}),'text-action'));panel.append(bar);
 if(!data.rows.length){panel.append(invEmpty('scroll-text','No hay ventas para mostrar','Registra una con «Nueva venta», o cambia los filtros.'));return;}
 const total=data.rows.filter(r=>r.state!=='anulada').reduce((a,r)=>a+r.total_cents,0),due=data.rows.reduce((a,r)=>a+r.balance_cents,0);
 panel.append(el('p',data.rows.length+(data.rows.length===1?' venta':' ventas')+' · '+centerMoney(total)+' vendidos'+(due?' · '+centerMoney(due)+' por cobrar':'')+(data.rows.length>=300?' · se muestran las 300 más recientes':''),'ic-muted sv-count'),salesRowsTable(data.rows,()=>salesHistory(panel)));}

// ---- Licencias y cobros: los paneles que ya existen ----
async function salesLicenses(panel){if(!licenseMeta)await licenseLoadMeta();panel.replaceChildren(invSectionHead('Ventas de licencias','Carrito, pagos y entrega de licencias. La disponibilidad, reservas, activaciones, vencimientos y renovaciones siguen en Licencias.'));
 const box=el('section',undefined,'licenses sv-licenses');panel.append(box);await licenseSales(box);}
async function salesPayments(panel){panel.replaceChildren(invSectionHead('Cobros','Pagos y anticipos de las ventas y cotizaciones, con su caja, cuenta receptora y comprobante. Los cobros de licencias se registran en «Ventas de licencias».'));
 const box=el('div');panel.append(box);await paymentsAllPanel(box);}

// ---- Pedidos comerciales ----
async function salesRequests(panel){const s=salesState,data=await api('/api/sales/requests?'+new URLSearchParams({status:s.req,q:s.reqQ}));
 panel.replaceChildren(invSectionHead('Pedidos comerciales','Lo que piden los clientes y aún no está en existencias: pedido al proveedor, recepción y entrega. Un pedido no se borra: se cancela con motivo.',invBtn('Nuevo pedido','plus',()=>salesRequestDialog(()=>salesRequests(panel)),'primary inv-add')));
 const bar=el('div',undefined,'sp-bar'),box=el('label',undefined,'inv-search sp-search'),search=el('input');search.type='search';search.value=s.reqQ;search.placeholder='Pedido, cliente, producto o proveedor';search.setAttribute('aria-label','Buscar pedido');box.append(invIcon('search'),search);
 let timer;search.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{s.reqQ=search.value.trim();salesRequests(panel).then(()=>{const f=panel.querySelector('input[type=search]');f.focus();f.setSelectionRange(f.value.length,f.value.length);});},300);});
 const status=el('select');status.setAttribute('aria-label','Filtrar por estado');for(const[v,t]of [['abiertos','Abiertos'],['todos','Todos'],...Object.entries(data.status)])status.add(new Option(t,v));status.value=s.req;status.addEventListener('change',()=>{s.req=status.value;salesRequests(panel);});bar.append(box,status);panel.append(bar);
 if(!data.rows.length){panel.append(invEmpty('truck','No hay pedidos para mostrar','Registra uno con «Nuevo pedido», o cambia el filtro.'));return;}
 const refresh=()=>salesRequests(panel);
 panel.append(centerTable(['Pedido','Cliente','Detalle','Proveedor','Estado','Acciones'],data.rows.map(r=>{const code=el('div',undefined,'sv-code');code.append(button(r.code,()=>salesRequestView(r.id,refresh),'text-action'),el('small',formatOrderDate(r.created_at),'ic-muted'));
  const what=el('div',undefined,'sv-code');what.append(el('strong',r.quantity+' × '+r.description),el('small',r.kind_label+(r.estimate_cents!==null?' · aprox. '+centerMoney(r.estimate_cents):'')+(r.expected_at?' · llega '+dashboardDate(r.expected_at):''),'ic-muted'));
  return centerRow([['Pedido',code],['Cliente',r.client],['Detalle',what],['Proveedor',r.supplier||'—'],['Estado',invoiceChip(salesRequestTone[r.status],r.status_label)],['Acciones',centerMenu('Acciones de '+r.code,[...salesRequestMoves(r,refresh),['Agregar nota',()=>salesRequestNote(r,refresh)],['Ver historial',()=>salesRequestView(r.id,refresh)]])]]);}),'sv-table'));}
function salesRequestMoves(r,refresh){const label={pedido_proveedor:'Marcar pedido al proveedor',recibido:'Marcar recibido',entregado:'Marcar entregado',cancelado:'Cancelar pedido'};
 return r.next.map(target=>[label[target],()=>salesRequestStatus(r,target,refresh),target==='cancelado']);}
async function salesRequestStatus(r,target,refresh){let fields=[['note','Nota (opcional)',{area:true,max:300}]],note='';
 if(target==='pedido_proveedor'){let suppliers=[];try{suppliers=(await api('/api/inventory/suppliers')).rows.filter(x=>x.active);}catch{}fields=[['supplier_id','Proveedor',{options:[['','Sin indicar'],...suppliers.map(x=>[String(x.id),x.name])],value:r.supplier_id?String(r.supplier_id):''}],['expected_at','Fecha estimada de llegada',{type:'date'}],...fields];note='Registra a qué proveedor se pidió y cuándo se espera.';}
 if(target==='entregado'){fields=[['sale_code','Venta con que se entregó (opcional)',{max:40,hint:'Número de la proforma o factura directa (PF-…) o de la venta de licencias (VLIC-…).'}],...fields];note='La venta y el cobro se registran en «Nueva venta»; aquí solo se cierra el pedido.';}
 if(target==='cancelado'){fields=[['note','Motivo de la cancelación',{required:true,area:true,max:300}]];note='El pedido se conserva con su historial.';}
 centerPrompt((target==='cancelado'?'Cancelar ':'Actualizar ')+r.code,{note,fields,submit:target==='cancelado'?'Cancelar pedido':'Guardar',danger:target==='cancelado'},async v=>{await api('/api/sales/requests/'+r.id,{action:'status',status:target,...v});toast('Pedido '+r.code+' actualizado.','success');refresh();});}
function salesRequestNote(r,refresh){centerPrompt('Nota en '+r.code,{fields:[['note','Nota',{required:true,area:true,max:300}]]},async v=>{await api('/api/sales/requests/'+r.id,{action:'note',note:v.note});toast('Nota agregada.','success');refresh();});}
async function salesRequestView(id,refresh){const dialog=invDialog('Pedido');const body=el('div',undefined,'inv-body');dialog.append(body);let d;try{d=await api('/api/sales/requests/'+id);}catch(error){body.append(el('p',error.message,'empty-module'));return;}
 const r=d.request;dialog.querySelector('h2').textContent='Pedido '+r.code;body.append(invoiceChip(salesRequestTone[r.status],r.status_label),centerFacts([['Detalle',r.quantity+' × '+r.description],...(r.cancel_reason?[['Motivo de cancelación',r.cancel_reason]]:[]),...(r.notes?[['Observaciones',r.notes]]:[])]));
 const list=el('ol',undefined,'license-history sv-events');for(const e of d.events){const li=el('li');li.append(el('span',e.detail),el('small',formatOrderDate(e.created_at)+' · '+(e.actor||'Sistema')));list.append(li);}body.append(el('h4','Historial'),list);
 const acts=el('div',undefined,'inv-actions');for(const[label,run,danger]of salesRequestMoves({...r,next:r.next},()=>{dialog.close();refresh&&refresh();}))acts.append(invBtn(label,danger?'x':'circle-check',run,danger?'secondary danger':'secondary'));body.append(acts);}
function salesRequestDialog(done){const dialog=invDialog('Nuevo pedido comercial',true),{form,msg,field,fail,clear}=invForm('bank-form inv-sheet-form sv-request-form');dialog.classList.add('sv-request');
 form.append(el('p','Registra lo que pide el cliente. La venta y el cobro se hacen después en «Nueva venta».','inv-form-note'),invRequiredNote());
 const who=el('div',undefined,'sv-client wide');form.append(who);const picker=licenseClientPicker(who,()=>{});
 field('kind','Tipo',{options:[['producto','Producto'],['licencia','Licencia'],['servicio','Servicio'],['otro','Otro']]});field('description','Qué pide el cliente',{required:true,max:300});field('quantity','Cantidad',{type:'number',value:'1',required:true});
 field('estimate','Valor aproximado (USD)',{mode:'decimal',hint:'Opcional. Solo informativo.'});field('expected_at','Fecha estimada',{type:'date'});field('notes','Observaciones',{area:true,max:300});
 const key=cjKey(),save=el('button','Registrar pedido','primary');save.type='submit';form.append(msg,invDialogActions(dialog,save));dialog.append(form);setTimeout(()=>picker.focus(),0);
 form.addEventListener('submit',async event=>{event.preventDefault();clear();if(!picker.client){msg.textContent='Selecciona el cliente del pedido.';return;}save.disabled=true;
  try{const r=await api('/api/sales/requests',{...Object.fromEntries(new FormData(form)),client_id:String(picker.client.id),request_key:key});dialog.close();toast('Pedido '+r.request.code+' registrado.','success');(done||salesReload)();}catch(error){fail(error);save.disabled=false;}});}

// ---- Reportes ----
async function salesReports(panel){const s=salesState,today=salesToday();if(!s.rfrom)s.rfrom=today.slice(0,8)+'01';if(!s.rto)s.rto=today;
 const data=await api('/api/sales/report?'+new URLSearchParams({group:s.group,from:s.rfrom,to:s.rto}));panel.replaceChildren(invSectionHead('Reportes de ventas','Ventas confirmadas (sin anuladas) por fechas, productos, clientes, usuarios o tipo de venta.'));
 const bar=el('div',undefined,'sp-bar sv-bar'),group=el('select');group.setAttribute('aria-label','Agrupar por');for(const[v,t]of [['dia','Por día'],['producto','Por producto'],['cliente','Por cliente'],['usuario','Por usuario'],['tipo','Por tipo de venta']])group.add(new Option(t,v));group.value=s.group;group.addEventListener('change',()=>{s.group=group.value;salesReports(panel);});
 const date=(label,key)=>{const wrap=el('label',undefined,'sv-date'),node=el('input');node.type='date';node.value=s[key];node.max=today;node.addEventListener('change',()=>{if(!node.value)return;s[key]=node.value;salesReports(panel).catch(error=>toast(error.message,'error'));});wrap.append(el('span',label),node);return wrap;};
 bar.append(group,date('Desde','rfrom'),date('Hasta','rto'),invBtn('Exportar CSV','download',()=>salesCsv(data)));panel.append(bar);
 if(!data.rows.length){panel.append(invEmpty('chart-column','Sin ventas en este período','Cambia las fechas o la agrupación.'));return;}
 const money=data.group!=='producto';panel.append(el('p',(money?data.totals.count+' ventas':data.totals.count+' unidades')+' · '+centerMoney(data.totals.total_cents),'ic-muted sv-count'));
 panel.append(centerTable([data.group_label,money?'Ventas':'Unidades','Total',...(money?['Cobrado','Saldo']:[])],data.rows.map(g=>centerRow([[data.group_label,data.group==='dia'?dashboardDate(g.label):g.label],[money?'Ventas':'Unidades',String(g.count)],['Total',centerMoney(g.total_cents)],...(money?[['Cobrado',centerMoney(g.paid_cents)],['Saldo',g.balance_cents?centerMoney(g.balance_cents):'—']]:[])])),'sv-table'));}
function salesCsv(data){const money=data.group!=='producto',cell=v=>{const t=String(v??'');return /[";\n]/.test(t)?'"'+t.replace(/"/g,'""')+'"':t;},amount=c=>c===null||c===undefined?'':(c/100).toFixed(2).replace('.',',');
 const lines=[[data.group_label,money?'Ventas':'Unidades','Total',...(money?['Cobrado','Saldo']:[])].join(';'),...data.rows.map(g=>[g.label,g.count,amount(g.total_cents),...(money?[amount(g.paid_cents),amount(g.balance_cents)]:[])].map(cell).join(';'))];
 const link=el('a');link.href=URL.createObjectURL(new Blob(['﻿'+lines.join('\n')],{type:'text/csv;charset=utf-8'}));link.download='ventas-'+data.group+'-'+data.from+'-a-'+data.to+'.csv';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),2000);}

// ---- Comprobante de venta -------------------------------------------------------------------------------------------------------
// Ventana «Imprimir comprobante» (como «Imprimir ticket» de las órdenes): vista previa del PDF real, formato (ticket de 80 mm o A4), copia
// del cliente, del establecimiento o ambas y, si la venta tiene factura electrónica autorizada, su RIDE. Imprimir y descargar usan exactamente
// el PDF mostrado. Solo lee: reimprimir no crea ventas, cobros, movimientos de caja ni de inventario.
for(const[k,v]of Object.entries({'loader-circle':'<path d="M21 12a9 9 0 1 1-6.219-8.56"/>','circle-alert':'<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
 'printer':'<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 9V3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v6"/><rect x="6" y="14" width="12" height="8" rx="1"/>',
 'download':'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>','x':'<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'}))invIcons[k]??=v;
async function salesReceipt(kind,id){const dialog=invDialog('Imprimir comprobante',true);dialog.classList.add('sr-dialog');const body=el('div',undefined,'inv-body sr');dialog.append(body);
 const loading=el('p','Cargando…','empty-module');body.append(loading);let s;
 try{s=await api('/api/sales/receipt/'+kind+'/'+id);}catch(error){loading.textContent=error.message;return;}if(!dialog.isConnected)return;body.replaceChildren();
 dialog.querySelector('h2').textContent='Imprimir comprobante · '+s.code;let blobUrl='';dialog.addEventListener('close',()=>{if(blobUrl)URL.revokeObjectURL(blobUrl);});
 const head=el('div',undefined,'sr-head'),who=el('div',undefined,'sr-who');who.append(el('strong',s.code),el('span',s.kind_label+' · '+s.client),el('small',formatOrderDate(s.sold_at)));
 const money=el('div',undefined,'sr-money');money.append(el('b',centerMoney(s.total_cents)),invoiceChip(salesTone[s.state]||'pendiente',s.state_label));head.append(who,money);body.append(head);
 const inv=s.invoice,emitted=inv&&inv.status!=='borrador';
 const note=el('p',inv&&inv.authorized?'Esta venta tiene la factura electrónica '+(inv.number||'')+' autorizada'+(inv.test?' en el ambiente de pruebas (sin validez tributaria)':'')+'. Su representación impresa es el RIDE; el comprobante de venta no es tributario.'
  :emitted?'Factura electrónica '+(inv.number||'')+' · '+inv.status_label+'. Hasta su autorización solo se imprime el comprobante de venta no tributario.'
  :'Comprobante de venta no tributario: no es válido como factura.','sr-note');note.dataset.tone=inv&&inv.authorized?'ok':'info';body.append(note);
 // Opciones: formato en botones de opción y copia en un desplegable (el RIDE no lleva copias).
 const opts=el('div',undefined,'sr-options'),group=el('fieldset',undefined,'sr-formats');group.append(el('legend','Formato'));let format='termico';
 const formats=[['termico','Ticket 80 mm','receipt-text'],['a4','A4','file-text'],...(inv&&inv.authorized?[['ride','Factura (RIDE)','badge-check']]:[])];
 for(const[value,label,icon]of formats){const l=el('label',undefined,'sr-format'),r=el('input');r.type='radio';r.name='sr-format-'+id;r.value=value;r.checked=value===format;
  r.addEventListener('change',()=>{format=value;copyBox.hidden=value==='ride';load();});l.append(r,invIcon(icon),el('span',label));group.append(l);}
 const copyBox=el('label',undefined,'inv-field sr-copy'),copy=el('select');for(const[value,label]of [['cliente','Copia del cliente'],['establecimiento','Copia del establecimiento'],['ambas','Ambas copias']])copy.add(new Option(label,value));
 copy.addEventListener('change',()=>load());copyBox.append(el('span','Copia'),copy);opts.append(group,copyBox);body.append(opts);
 // Vista previa: URL de objeto temporal (el servidor no permite incrustar sus respuestas). Sin visor de PDF (teléfonos), se omite y los botones siguen.
 // El ticket de 72 mm se muestra a tamaño natural (zoom fijo); el A4 y el RIDE, al ancho de la ventana.
 const viewer=navigator.pdfViewerEnabled!==false&&!matchMedia('(max-width:720px)').matches,frame=el('iframe',undefined,'sr-frame'),status=el('p',undefined,'document-status sr-status');status.setAttribute('role','status');
 frame.title='Vista previa del comprobante '+s.code;frame.hidden=true;body.append(status,frame);
 const say=(text,state)=>{status.dataset.state=state;status.replaceChildren(invIcon(state==='ready'?'badge-check':state==='error'?'circle-alert':'loader-circle'),el('span',text));};
 const acts=el('div',undefined,'sr-actions'),print=invBtn('Imprimir','printer',()=>{if(!blobUrl)return;if(viewer&&!frame.hidden){try{frame.contentWindow.focus();frame.contentWindow.print();return;}catch{}}const w=window.open(blobUrl,'_blank');if(w)w.opener=null;else toast('Permite las ventanas emergentes para imprimir.','error');},'primary');
 const download=el('a',undefined,'secondary inv-btn');download.append(invIcon('download'),el('span','Descargar PDF'));const close=invBtn('Cerrar','x',()=>dialog.close());acts.append(close,download,print);body.append(acts);
 const url=()=>format==='ride'?'/api/invoicing/'+inv.id+'/ride.pdf':'/api/sales/receipt/'+kind+'/'+id+'.pdf?'+new URLSearchParams({formato:format,copia:copy.value});
 const name=()=>format==='ride'?'FACTURA-'+(inv.number||s.code)+'.pdf':'COMPROBANTE-'+s.code+(format==='termico'?'-80MM':'')+(copy.value==='establecimiento'?'-ESTABLECIMIENTO':copy.value==='ambas'?'-AMBAS':'')+'.pdf';
 let version=0;async function load(){const mine=++version;print.disabled=true;download.setAttribute('aria-disabled','true');download.removeAttribute('href');frame.hidden=true;say(format==='ride'?'Generando el RIDE…':'Generando comprobante…','loading');
  try{const blob=await fetchDocument(url());if(mine!==version||!dialog.open)return;if(!blob.size)throw new Error('El servidor no devolvió un PDF válido.');if(blobUrl)URL.revokeObjectURL(blobUrl);blobUrl=URL.createObjectURL(blob);
   download.href=blobUrl;download.download=name();download.removeAttribute('aria-disabled');print.disabled=false;
   if(!viewer){say('Comprobante listo. Este dispositivo no muestra la vista previa: usa Imprimir o Descargar PDF.','ready');return;}
   let shown=false;const timer=setTimeout(()=>{if(!shown&&mine===version){frame.hidden=true;say('No se pudo mostrar la vista previa. Puedes imprimir o descargar el PDF.','error');}},12000);
   frame.onload=()=>{if(mine!==version||!frame.src.startsWith('blob:'))return;shown=true;clearTimeout(timer);say(format==='ride'?'RIDE listo':'Comprobante listo · el mismo PDF se imprime y se descarga','ready');};
   frame.hidden=false;frame.src=blobUrl+'#toolbar=0&navpanes=0&'+(format==='termico'?'zoom=110':'view=FitH');}catch(error){if(mine===version)say(error.message,'error');}}
 load();}
