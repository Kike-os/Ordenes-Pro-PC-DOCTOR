// Inventario de Licencias Digitales (solo administración): productos y logos, registro individual o por lote, inventario por unidad,
// ventas y entregas (confirmar pago y autorizar entrega por separado) e historial. Las credenciales nunca se listan: se consultan una a una
// con registro, y el cliente las recibe por un enlace privado con identificación y código. El servidor vuelve a validar todo.
'use strict';
const licenseState={tab:'productos',product:'',status:'',q:''};
const licenseMoney=cents=>cents===null||cents===undefined?'—':'$'+(cents/100).toLocaleString('es-EC',{minimumFractionDigits:2,maximumFractionDigits:2});
const licenseDay=value=>{if(!value)return '';const text=String(value);return /^\d{4}-\d{2}-\d{2}$/.test(text)?text.slice(8,10)+'/'+text.slice(5,7)+'/'+text.slice(0,4):formatOrderDate(text);};
const licenseIcons={key:'M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z M16.5 7.5h.01',
 list:'M3 12h.01 M3 18h.01 M3 6h.01 M8 12h13 M8 18h13 M8 6h13',plus:'M12 5v14 M5 12h14',layers:'M12 2 2 7l10 5 10-5-10-5z M2 17l10 5 10-5 M2 12l10 5 10-5',history:'M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8 M3 3v5h5 M12 7v5l4 2',
 image:'M3 3h18v18H3z M9 9h.01 M21 15l-5-5L5 21',truck:'M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2 M15 18H9 M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14 M17 18a2 2 0 1 0 0 0.01 M7 18a2 2 0 1 0 0 0.01'};
async function renderLicenses(){
 const content=$('module-content');let data;try{data=await api('/api/licenses');}catch(error){content.replaceChildren(el('p',error.message,'empty-module'));return;}
 content.replaceChildren();const wrap=el('section',undefined,'licenses');content.append(wrap);
 const bar=el('div',undefined,'licenses-actions'),action=(text,icon,run,kind='secondary')=>{const b=button('',run,kind);b.append(systemIcon(licenseIcons[icon]),el('span',text));bar.append(b);return b;};
 action('Registrar nueva licencia','plus',()=>licenseRegister(data,false),'primary');action('Registrar varias licencias','layers',()=>licenseRegister(data,true));
 const tabs=el('div',undefined,'licenses-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Secciones del inventario');
 const panel=el('div',undefined,'licenses-panel');panel.setAttribute('role','tabpanel');
 const defs=[['productos','Administrar productos y logos','image'],['inventario','Consultar inventario','list'],['entregas','Ventas y entregas','truck'],['historial','Historial','history']];
 for(const[key,label,icon]of defs){const tab=button('',()=>{licenseState.tab=key;paint();},'licenses-tab');tab.setAttribute('role','tab');tab.dataset.tab=key;tab.append(systemIcon(licenseIcons[icon]),el('span',label));tabs.append(tab);}
 tabs.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;const list=[...tabs.children],at=list.indexOf(document.activeElement);if(at<0)return;event.preventDefault();const next=list[(at+(event.key==='ArrowRight'?1:list.length-1))%list.length];next.focus();next.click();});
 wrap.append(bar,tabs,panel);
 async function paint(){for(const tab of tabs.children){const on=tab.dataset.tab===licenseState.tab;tab.setAttribute('aria-selected',String(on));tab.tabIndex=on?0:-1;if(on)tab.scrollIntoView({block:'nearest',inline:'nearest'});}
  panel.replaceChildren(el('p','Cargando…','system-muted'));
  try{if(licenseState.tab==='productos')licenseProducts(panel,data,reload);else if(licenseState.tab==='inventario')await licenseInventory(panel,data,reload);else if(licenseState.tab==='entregas')await licenseDeliveries(panel,reload);else await licenseHistory(panel);}
  catch(error){panel.replaceChildren(el('p',error.message,'empty-module'));}}
 async function reload(){try{data=await api('/api/licenses');}catch(error){notify(error.message);}await paint();}
 window.licenseReload=reload;await paint();
}
function licenseProducts(panel,data,reload){
 panel.replaceChildren();if(!data.products.length){panel.append(el('p','No hay productos de licencias en el catálogo. Créalos en Configuración → Catálogo con la categoría «Licencias» o «Antivirus y seguridad».','empty-module'));return;}
 const grid=el('div',undefined,'license-products');
 for(const item of data.products){const card=el('article',undefined,'license-product'),head=el('header'),title=el('div');title.append(el('strong',item.name),el('small',[item.kind_label,item.brand].filter(Boolean).join(' · ')));head.append(catalogLogo(item,{},'catalog-logo license-logo'),title);
  const stock=el('dl',undefined,'license-stock');for(const key of ['disponible','reservada','entregada','vencida']){const box=el('div');box.dataset.state=key;box.append(el('dt',data.statuses[key]),el('dd',String(item.stock[key])));stock.append(box);}
  const facts=el('p',[item.managed?'Venta '+licenseMoney(item.price_cents):'',item.purchase_cents!==null&&item.purchase_cents!==undefined?'Compra '+licenseMoney(item.purchase_cents):'',item.supplier,item.term,item.devices?item.devices+' dispositivo'+(item.devices===1?'':'s'):''].filter(Boolean).join(' · ')||'Sin datos de inventario','license-facts-line');
  card.append(head,stock,facts);if(item.pending)card.append(el('p',item.pending+' pendiente'+(item.pending===1?'':'s')+' de existencias en ventas aprobadas','license-alert'));
  if(!item.managed)card.append(el('p','Configura su tipo para registrar licencias.','license-hint'));
  const actions=el('div',undefined,'license-card-actions');actions.append(button(item.managed?'Editar producto':'Configurar',()=>licenseProductDialog(data,item,reload),'secondary'),button(item.image?'Reemplazar logo':'Subir logo',()=>licenseLogoDialog(item,reload),'secondary'));
  if(item.managed)actions.append(button('Ver licencias',()=>{licenseState.tab='inventario';licenseState.product=String(item.id);reload();},'text-action'));card.append(actions);grid.append(card);}
 panel.append(grid);
}
function licenseField(form,label,name,value='',options={}){const box=el('label',undefined,'license-field'+(options.wide?' wide':''));box.append(el('span',label));const node=el(options.textarea?'textarea':options.select?'select':'input');node.name=name;
 if(options.select)for(const[key,text]of options.select)node.add(new Option(text,key));else if(!options.textarea){node.type=options.type||'text';node.autocomplete='off';node.spellcheck=false;}
 if(options.max)node.maxLength=options.max;if(options.rows)node.rows=options.rows;if(options.placeholder)node.placeholder=options.placeholder;if(options.inputmode)node.inputMode=options.inputmode;node.value=value??'';const hint=el('small','','license-field-error');box.append(node,hint);form.append(box);return node;}
function licenseErrors(form,error,message){form.querySelectorAll('.license-field-error').forEach(node=>node.textContent='');form.querySelectorAll('[aria-invalid]').forEach(node=>node.removeAttribute('aria-invalid'));
 for(const[key,text]of Object.entries(error.fields||{})){const node=form.elements[key];if(node){node.setAttribute('aria-invalid','true');const hint=node.parentElement.querySelector('.license-field-error');if(hint)hint.textContent=text;}}
 message.textContent=error.message;form.querySelector('[aria-invalid=true]')?.focus();}
function licenseFormDialog(title,build,submit,label='Guardar'){const dialog=smallDialog(title);dialog.classList.add('license-dialog');const form=el('form',undefined,'license-form-grid'),message=el('p','','form-message'),save=el('button',label,'primary'),cancel=button('Cancelar',()=>requestModalClose(dialog),'secondary'),foot=el('div',undefined,'license-dialog-actions');
 message.setAttribute('role','alert');save.type='submit';foot.append(cancel,save);build(form,dialog);dialog.append(form);form.append(message,foot);(form.querySelector('input:not([type=hidden]),select,textarea')||save).focus();
 form.onsubmit=async event=>{event.preventDefault();if(save.disabled)return;save.disabled=true;message.textContent='';try{await submit(form,dialog);}catch(error){licenseErrors(form,error,message);}finally{save.disabled=false;}};return dialog;}
function licenseProductDialog(data,item,reload){
 licenseFormDialog('Producto: '+item.name,form=>{const kinds=Object.entries(data.kinds);licenseField(form,'Tipo de licencia *','kind',item.kind||'',{select:[['','Selecciona el tipo'],...kinds]});
  licenseField(form,'Proveedor','supplier',item.supplier||'',{max:120});licenseField(form,'Precio de compra (USD)','purchase_price',item.purchase_cents!==null&&item.purchase_cents!==undefined?(item.purchase_cents/100).toFixed(2):'',{inputmode:'decimal',placeholder:'0,00'});
  licenseField(form,'Duración','term',item.term||item.license_term||'',{max:60,placeholder:'1 año, 2 años, permanente…'});licenseField(form,'Dispositivos','devices',item.devices||'',{inputmode:'numeric',max:4});
  form.append(el('p','El nombre, la categoría y el precio de venta se editan en el catálogo: son los que usa el presupuesto ('+licenseMoney(item.price_cents)+').','license-hint wide'));},
  async(form,dialog)=>{const v=name=>form.elements[name].value;await api('/api/licenses/products',{item_id:String(item.id),kind:v('kind'),supplier:v('supplier'),purchase_price:v('purchase_price'),term:v('term'),devices:v('devices')});dialog.close();toast('Producto actualizado.','success');reload();});
}
function licenseLogoDialog(item,reload){
 // El logo se conserva tal cual (sin recortes ni cambios): PNG, JPG o WebP de hasta 300 KB. Reemplazarlo pide confirmación.
 licenseFormDialog('Logo de '+item.name,form=>{const preview=el('div',undefined,'license-logo-preview');preview.append(item.image?catalogLogo(item,{},'catalog-logo license-logo-large'):el('span','Sin logo','license-hint'));form.append(preview);
  const file=el('input');file.type='file';file.name='logo';file.accept='image/png,image/jpeg,image/webp';const box=el('label',undefined,'license-field wide');box.append(el('span','Imagen PNG, JPG o WebP (hasta 300 KB)'),file,el('small','','license-field-error'));form.append(box);
  file.addEventListener('change',()=>{const chosen=file.files[0];if(!chosen)return;const image=new Image();image.className='license-logo-large';image.alt='Vista previa del logo';image.src=URL.createObjectURL(chosen);image.onload=()=>URL.revokeObjectURL(image.src);preview.replaceChildren(image);});},
  async(form,dialog)=>{const chosen=form.elements.logo.files[0];if(!chosen)throw Object.assign(new Error('Elige una imagen.'),{fields:{logo:'Selecciona un archivo.'}});
   if(!['image/png','image/jpeg','image/webp'].includes(chosen.type))throw Object.assign(new Error('Usa una imagen PNG, JPG o WebP.'),{fields:{logo:'Formato no admitido.'}});if(chosen.size>300000)throw Object.assign(new Error('La imagen supera el máximo de 300 KB.'),{fields:{logo:'Archivo demasiado grande.'}});
   if(item.image&&await confirmClose({title:'¿Reemplazar el logo?',text:'El logo actual de «'+item.name+'» se sustituirá por la imagen elegida en todas sus licencias, presupuestos y tarjetas.',keep:'Conservar el actual',discard:'Reemplazar logo'})!=='discard')return;
   const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]||'');reader.onerror=()=>reject(new Error('No se pudo leer la imagen.'));reader.readAsDataURL(chosen);});
   await api('/api/catalog/'+item.id+'/image',{data:content});dialog.close();toast('Logo guardado.','success');reload();},'Guardar logo');
}
function licenseUnitFields(form,data,kind,unit={}){const holder=el('div',undefined,'license-kind-fields wide');form.append(holder);
 for(const key of data.fields[kind]||[]){const isDate=['purchased_at','activated_at','expires_at'].includes(key);licenseField(holder,data.field_labels[key],key,unit[key]??'',{type:isDate?'date':'text',inputmode:key==='devices'?'numeric':undefined,max:key==='devices'?4:120});}
 return holder;}
function licenseSecretFields(form,data,kind,optional){const holder=el('fieldset',undefined,'license-secret wide');holder.append(el('legend',optional?'Reemplazar credencial (opcional)':'Credencial (se guarda cifrada)'));
 for(const field of data.secrets[kind]||[]){const node=licenseField(holder,field.label+(optional?'':' *'),field.key,'',{max:300,type:field.key==='password'?'password':'text'});node.autocomplete=field.key==='password'?'new-password':'off';}
 holder.append(el('small','Nunca se muestra en listados ni registros. Solo administración puede consultarla, y cada consulta queda registrada.','license-hint'));form.append(holder);return holder;}
function licenseRegister(data,many){
 const managed=data.products.filter(item=>item.managed);if(!managed.length){toast('Configura primero un producto en «Administrar productos y logos».','warning');return;}
 licenseFormDialog(many?'Registrar varias licencias':'Registrar nueva licencia',form=>{
  const product=licenseField(form,'Producto *','product_id',licenseState.product&&managed.some(item=>String(item.id)===licenseState.product)?licenseState.product:String(managed[0].id),{select:managed.map(item=>[String(item.id),item.name+' · '+item.kind_label]),wide:true});
  const area=el('div',undefined,'license-dynamic wide');form.append(area);
  const batch=el('fieldset',undefined,'license-batch wide');batch.append(el('legend','Compra (opcional)'));licenseField(batch,'Proveedor','supplier','',{max:120});licenseField(batch,'Costo unitario (USD)','unit_cost','',{inputmode:'decimal'});licenseField(batch,'Fecha de compra','batch_date','',{type:'date'});licenseField(batch,'Factura','invoice','',{max:80});form.append(batch);
  const build=()=>{const item=managed.find(row=>String(row.id)===product.value),kind=item.kind;area.replaceChildren();licenseUnitFields(area,data,kind,{devices:item.devices||'',term:item.term||''});
   if(many){const label=kind==='m365'?'Una cuenta por línea con el formato usuario;contraseña':'Una clave o serial por línea';const lines=licenseField(area,label+' *','lines','',{textarea:true,rows:8,wide:true});lines.spellcheck=false;lines.setAttribute('autocomplete','off');area.append(el('small','Hasta '+data.max_bulk+' licencias. Si una línea no es válida o ya existe, no se registra ninguna.','license-hint wide'));}
   else{licenseSecretFields(area,data,kind,false);licenseField(area,'Observaciones','notes','',{max:300,wide:true});}};
  product.addEventListener('change',build);build();},
  async(form,dialog)=>{const body={};for(const node of form.elements)if(node.name&&node.type!=='file')body[node.name]=node.value;const result=await api(many?'/api/licenses/units/bulk':'/api/licenses/units',body);
   dialog.close();toast(many?result.count+' licencias registradas.':'Licencia registrada. Las ventas aprobadas que esperaban existencias se reservaron automáticamente.','success');window.licenseReload&&window.licenseReload();},many?'Registrar licencias':'Registrar licencia');
}
async function licenseInventory(panel,data,reload){
 const tools=el('form',undefined,'licenses-filters');tools.setAttribute('role','search');const product=el('select'),status=el('select'),search=el('input'),go=el('button','Buscar','secondary');go.type='submit';
 product.add(new Option('Todos los productos',''));for(const item of data.products.filter(row=>row.managed))product.add(new Option(item.name,String(item.id)));status.add(new Option('Todos los estados',''));for(const[key,text]of Object.entries(data.statuses))status.add(new Option(text,key));
 product.value=licenseState.product;status.value=licenseState.status;search.type='search';search.value=licenseState.q;search.placeholder='Código, cliente, orden o clave';search.setAttribute('aria-label','Buscar licencia');search.spellcheck=false;
 for(const[node,label]of [[product,'Producto'],[status,'Estado']])node.setAttribute('aria-label',label);tools.append(product,status,search,go);
 tools.onsubmit=event=>{event.preventDefault();licenseState.product=product.value;licenseState.status=status.value;licenseState.q=search.value.trim();licenseInventory(panel,data,reload);};product.onchange=status.onchange=()=>tools.requestSubmit();
 const query=new URLSearchParams({product:licenseState.product,status:licenseState.status,q:licenseState.q});const result=await api('/api/licenses/units?'+query.toString());
 panel.replaceChildren(tools);if(!result.rows.length){panel.append(el('p','No hay licencias con estos filtros.','empty-module'));return;}
 const table=el('div',undefined,'license-table');panel.append(el('p',result.rows.length+' licencia'+(result.rows.length===1?'':'s'),'license-count'),table);
 for(const row of result.rows){const item=el('article',undefined,'license-row'),main=el('div',undefined,'license-row-main'),badge=el('span',row.status_label,'license-badge');badge.dataset.state=row.status;
  main.append(el('strong',row.code),el('span',row.product),badge);const facts=el('p',[row.kind_label,row.edition,row.license_type,row.manufacturer,row.version,row.devices?row.devices+' disp.':'',row.term,row.expires_at?'Vence '+licenseDay(row.expires_at):'',row.activated?'Activada':'',row.order_code?'Orden '+row.order_code:'',row.quote_code,row.client].filter(Boolean).join(' · '),'license-row-facts');
  const actions=el('div',undefined,'license-row-actions');
  actions.append(button('Ver credencial',async()=>{try{const shown=await api('/api/licenses/units/'+row.id,{action:'reveal'});licenseShowSecret(row,shown.credentials);}catch(error){toast(error.message,'error');}},'text-action'));
  if(!['entregada','anulada'].includes(row.status))actions.append(button('Editar',()=>licenseEdit(data,row,()=>licenseInventory(panel,data,reload)),'text-action'));
  if(row.status==='reservada')actions.append(button('Anular reserva',async()=>{if(await confirmClose({title:'¿Anular la reserva de '+row.code+'?',text:'Vuelve a estar disponible solo si no fue activada ni entregada.',keep:'Conservar reserva',discard:'Anular reserva'})!=='discard')return;try{await api('/api/licenses/units/'+row.id,{action:'release'});toast('Reserva anulada.','success');licenseInventory(panel,data,reload);}catch(error){toast(error.message,'error');}},'text-action'));
  if(!['entregada','anulada'].includes(row.status))actions.append(button('Anular',()=>licenseVoid(row,()=>licenseInventory(panel,data,reload)),'text-action danger'));
  item.append(main,facts,actions);table.append(item);}
}
function licenseShowSecret(row,credentials){const dialog=smallDialog('Credencial de '+row.code);dialog.classList.add('license-dialog');const list=el('dl',undefined,'license-secret-view');
 for(const item of credentials){const box=el('div'),value=el('code',item.value);box.append(el('dt',item.label),el('dd'));box.lastChild.append(value,button('Copiar',async()=>{try{await navigator.clipboard.writeText(item.value);toast('Copiado.','success');}catch{toast('No se pudo copiar.','error');}},'text-action'));list.append(box);}
 dialog.append(el('p','Consulta registrada en el historial. No compartas esta credencial por canales no seguros.','license-hint'),list);
 // Se borra de la pantalla al cerrar o tras 60 segundos.
 const timer=setTimeout(()=>dialog.isConnected&&dialog.close(),60000);dialog.addEventListener('close',()=>clearTimeout(timer));}
function licenseEdit(data,row,done){licenseFormDialog('Editar '+row.code,form=>{licenseUnitFields(form,data,row.kind,row);licenseSecretFields(form,data,row.kind,true);licenseField(form,'Observaciones','notes',row.notes||'',{max:300,wide:true});
  const flag=el('label',undefined,'booking-consent wide'),box=el('input');box.type='checkbox';box.name='activated';box.checked=!!row.activated;flag.append(box,el('span','Licencia ya activada en el equipo del cliente (si se anula la reserva, no vuelve al inventario).'));form.append(flag);},
  async(form,dialog)=>{const body={action:'edit'};for(const node of form.elements)if(node.name)body[node.name]=node.type==='checkbox'?node.checked:node.value;await api('/api/licenses/units/'+row.id,body);dialog.close();toast('Licencia actualizada.','success');done();});}
function licenseVoid(row,done){licenseFormDialog('Anular '+row.code,form=>{form.append(el('p','El registro queda invalidado y no vuelve a venderse. Su historial se conserva.','license-hint wide'));licenseField(form,'Motivo *','reason','',{max:300,wide:true});},
  async(form,dialog)=>{await api('/api/licenses/units/'+row.id,{action:'void',reason:form.elements.reason.value});dialog.close();toast('Licencia anulada.','success');done();},'Anular licencia');}
async function licenseDeliveries(panel,reload){
 const result=await api('/api/licenses/deliveries');panel.replaceChildren();
 panel.append(el('p','Las credenciales solo se entregan cuando el presupuesto está aprobado, el pago está completo, administración confirmó el pago y autorizó la entrega. El servidor lo vuelve a comprobar en cada paso.','license-hint'));
 if(!result.rows.length){panel.append(el('p','Todavía no hay ventas de licencias.','empty-module'));return;}
 const again=()=>licenseDeliveries(panel,reload);
 for(const row of result.rows){const card=el('article',undefined,'license-delivery'),head=el('header');head.append(el('strong','Orden '+row.order),el('span',row.client),el('span',row.balance_cents>0?'Saldo pendiente '+licenseMoney(row.balance_cents):'Sin saldo pendiente','license-balance'+(row.balance_cents>0?' due':'')));card.append(head);
  if(row.pending.length)card.append(el('p','Pendiente de existencias: '+row.pending.map(item=>item.missing+' × '+item.product+' ('+item.quote+')').join('; '),'license-alert'));
  if(row.reserved.length){card.append(el('p','Reservadas sin entregar: '+row.reserved.map(item=>item.code+' · '+item.product).join(', '),'license-row-facts'));
   if(row.blockers.length)card.append(el('p',row.blockers.join(' '),'license-alert'));
   const confirm=button('Confirmar pago',async()=>{if(await confirmClose({title:'¿Confirmar el pago completo?',text:'Confirmas que el cliente pagó todo lo correspondiente a la orden '+row.order+'. Después, la entrega necesita una autorización aparte.',keep:'Volver',discard:'Confirmar pago'})!=='discard')return;try{await api('/api/licenses/orders/'+row.order_id+'/confirm-payment',{});toast('Pago confirmado. Falta autorizar la entrega.','success');again();}catch(error){toast(error.message,'error');}},'primary');
   confirm.disabled=row.blockers.length>0;card.append(confirm);}
  for(const delivery of row.deliveries){const box=el('div',undefined,'license-delivery-step');box.dataset.state=delivery.status;
   box.append(el('p',{pago_confirmado:'Pago confirmado',autorizada:'Entrega autorizada',anulada:'Confirmación anulada'}[delivery.status]+' · '+delivery.units.map(unit=>unit.code+' '+unit.product).join(', ')),
    el('small',['Pago confirmado por '+delivery.confirmed_by+' el '+formatOrderDate(delivery.payment_confirmed_at),delivery.authorized_at?'Autorizada por '+delivery.authorized_by_name+' el '+formatOrderDate(delivery.authorized_at):'',delivery.reveal_count?'Consultada '+(delivery.reveal_count===1?'1 vez':delivery.reveal_count+' veces')+' por el cliente':'',delivery.void_reason?'Motivo: '+delivery.void_reason:''].filter(Boolean).join(' · ')));
   const actions=el('div',undefined,'license-row-actions');
   const share=result=>licenseShareLink(result,row);
   if(delivery.status==='pago_confirmado'){actions.append(button('Autorizar entrega',async()=>{if(await confirmClose({title:'¿Autorizar la entrega?',text:'Las licencias quedarán entregadas al cliente de la orden '+row.order+' y se generará su enlace privado ('+'72 h). Esta acción no se deshace.',keep:'Volver',discard:'Autorizar entrega'})!=='discard')return;try{share(await api('/api/licenses/deliveries/'+delivery.id,{action:'authorize'}));again();}catch(error){toast(error.message,'error');again();}},'primary'),
     button('Anular confirmación',()=>licenseFormDialog('Anular confirmación de pago',form=>licenseField(form,'Motivo *','reason','',{max:300,wide:true}),async(form,dialog)=>{await api('/api/licenses/deliveries/'+delivery.id,{action:'void',reason:form.elements.reason.value});dialog.close();again();},'Anular'),'secondary'));}
   if(delivery.status==='autorizada'){actions.append(button('Tarjeta (sin credenciales)',()=>licenseCard(delivery.id),'secondary'),button(delivery.link_active?'Generar nuevo enlace':'Enlace vencido: generar nuevo',async()=>{try{share(await api('/api/licenses/deliveries/'+delivery.id,{action:'renew'}));again();}catch(error){toast(error.message,'error');}},'secondary'));}
   box.append(actions);card.append(box);}
  panel.append(card);}
}
function licenseShareLink(result,row){const dialog=smallDialog('Enlace privado de entrega');dialog.classList.add('license-dialog');const field=el('input');field.readOnly=true;field.value=result.link;field.setAttribute('aria-label','Enlace privado');
 const mail={sent:'Enviado al correo registrado del cliente (sin credenciales).',failed:'No se pudo enviar el correo: comparte el enlace por otro medio.',not_configured:'El correo del sistema no está configurado: comparte el enlace por otro medio.',no_email:'El cliente no tiene correo registrado: para abrir el enlace necesita recibir un código por correo; registra su correo o entrega las licencias en el taller.'}[result.mail]||'';
 dialog.append(el('p',mail,'license-hint'),field,el('p','Válido hasta '+formatOrderDate(result.expires_at)+'. El cliente deberá escribir su identificación y un código enviado a su correo.','license-hint'),button('Copiar enlace',async()=>{try{await navigator.clipboard.writeText(result.link);toast('Enlace copiado.','success');}catch{field.select();}},'primary'));field.focus();field.select();}
async function licenseCard(id){const card=await api('/api/licenses/deliveries/'+id+'/card');const dialog=smallDialog('Tarjeta de licencias');dialog.classList.add('license-dialog','license-card-dialog');
 const sheet=el('div',undefined,'license-sheet'),top=el('header'),logo=new Image();logo.src='/static/logo-original.png';logo.alt='PC-DOCTOR S.A.';logo.className='license-brand';top.append(logo,el('div'));top.lastChild.append(el('strong',card.client),el('small','Orden '+card.order+' · Entregada el '+formatOrderDate(card.delivered_at)));sheet.append(top);
 for(const item of card.items){const box=el('article',undefined,'license-sheet-item'),head=el('div',undefined,'license-sheet-head');head.append(catalogLogo({id:item.product_id,image:item.has_logo?'1':'',category:'licencia',name:item.product},{},'catalog-logo license-logo'),el('strong',item.product));
  box.append(head,el('p',[item.kind,item.term?'Duración: '+item.term:'',item.devices?item.devices+' dispositivo'+(item.devices===1?'':'s')+' autorizado'+(item.devices===1?'':'s'):'',item.expires_at?'Vence el '+licenseDay(item.expires_at):''].filter(Boolean).join(' · '),'license-row-facts'));sheet.append(box);}
 sheet.append(el('p','Versión pública: las credenciales solo aparecen en la versión privada, que el cliente abre con su enlace, su identificación y un código.','license-hint'),el('p','PC-DOCTOR S.A. · '+card.contact.phone+' · '+card.contact.email,'license-contact'));
 dialog.append(sheet,button('Imprimir',()=>window.print(),'secondary'));}
async function licenseHistory(panel){const result=await api('/api/licenses/history');panel.replaceChildren();if(!result.rows.length){panel.append(el('p','Sin movimientos todavía.','empty-module'));return;}
 const list=el('ol',undefined,'license-history');for(const row of result.rows){const item=el('li');item.append(el('span',row.detail||row.event),el('small',[formatOrderDate(row.created_at),row.actor||'Sistema',row.unit_code,row.product,row.order_code?'Orden '+row.order_code:'',row.client].filter(Boolean).join(' · ')));list.append(item);}panel.append(list);}
