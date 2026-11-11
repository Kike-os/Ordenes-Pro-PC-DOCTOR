'use strict';
// PQRS en el panel (1.5.278). Administración: todas las solicitudes, asignación, prioridad, cierre, reapertura, sedes y exportación.
// Técnico: solo las asignadas (el servidor lo impone; la interfaz solo oculta lo que no le corresponde). Usa las utilidades de app.js.
(()=>{
const CATEGORY={peticion:['Petición','#3d8bff'],queja:['Queja','#f0a640'],reclamo:['Reclamo','#ff5c8a'],sugerencia:['Sugerencia','#33c48d']};
const STATUS={recibida:'Recibida',en_revision:'En revisión',asignada:'Asignada',esperando_cliente:'Esperando información del cliente',en_solucion:'En proceso de solución',respondida:'Respondida',cerrada:'Cerrada'};
const PRIORITY={baja:'Baja',normal:'Normal',alta:'Alta',urgente:'Urgente'};
const EVENT={creada:'Solicitud recibida',estado:'Cambio de estado',asignacion:'Asignación',prioridad:'Prioridad',respuesta:'Respuesta al cliente',nota:'Nota interna',mensaje_cliente:'Mensaje del cliente',cierre:'Cierre',reapertura:'Reapertura'};
const RESULT={pendiente:'Pendiente',enviado:'Enviado',fallido:'Fallido',sin_configurar:'Correo no configurado',sin_destinatario:'Sin correo válido'};
const ICON='M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1';
const when=value=>{if(!value)return '—';const d=new Date(value);return Number.isNaN(d.getTime())?value:new Intl.DateTimeFormat('es-EC',{timeZone:'America/Guayaquil',dateStyle:'medium',timeStyle:'short'}).format(d);};
const hours=h=>h===null||h===undefined?'—':h<48?String(h).replace('.',',')+' h':(Math.round(h/24*10)/10).toString().replace('.',',')+' días';
const state={status:'abiertas',category:'',site:'',priority:'',q:'',from:'',to:'',page:1};
const badge=(text,cls,attr)=>{const b=el('span',text,cls);if(attr)for(const[k,v]of Object.entries(attr))b.dataset[k]=v;return b;};
const chip=key=>{const[label,color]=CATEGORY[key]||[key,'#8ea2c2'];const c=el('span',label,'pqrs-chip');c.style.setProperty('--tone',color);return c;};

// Contador del menú: nuevas (administración) o asignadas por atender (técnico).
async function refreshBadge(){const tag=document.getElementById('pqrs-nav-badge');if(!tag)return;try{const {new:count}=await api('/api/pqrs/count');tag.hidden=!count;tag.textContent=count>99?'99+':String(count);}catch{}}
setTimeout(refreshBadge,1500);setInterval(()=>{if(!document.hidden)refreshBadge();},60000);

async function render(params){const box=document.getElementById('module-content');const id=params?.get?.('id');
 if(id&&/^\d+$/.test(id))return detail(box,+id);return list(box);}

async function list(box){const query=new URLSearchParams(Object.entries(state).filter(([,v])=>v!==''&&v!==null).map(([k,v])=>[k,String(v)]));
 const data=await api('/api/pqrs?'+query.toString());box.replaceChildren();box.classList.add('pqrs-admin');const m=data.metrics;
 const cards=el('div',undefined,'pqrs-kpis');for(const[label,value,note,tone]of [['Nuevas',m.new,'Sin revisar todavía','pink'],['Abiertas',m.open,'No cerradas','blue'],
   ['Sin primera respuesta',m.late_first_response,'Más de '+m.late_hours+' h desde que llegaron',m.late_first_response?'warn':'ok'],['Primera respuesta',hours(m.first_response_hours),'Tiempo medio','blue'],['Resolución',hours(m.resolution_hours),'Tiempo medio hasta el cierre','green']]){
  const card=el('div',undefined,'pqrs-kpi');card.dataset.tone=tone;card.append(el('span',label),el('strong',String(value)),el('small',note));cards.append(card);}
 const chips=el('div',undefined,'pqrs-status-filter');chips.setAttribute('role','group');chips.setAttribute('aria-label','Filtrar por estado');
 for(const[key,label,count]of [['abiertas','Abiertas',m.open],['',('Todas'),m.total],...Object.entries(STATUS).map(([k,v])=>[k,v,m.by_status[k]])]){const b=button('',()=>{state.status=key;state.page=1;list(box);},'pqrs-filter');b.append(el('span',label),el('b',String(count??0)));b.setAttribute('aria-pressed',String(state.status===key));chips.append(b);}
 const bar=el('form',undefined,'pqrs-filters');bar.noValidate=true;const field=(label,node)=>{const l=el('label',undefined,'pqrs-filter-field');l.append(el('span',label),node);return l;};
 const q=el('input');q.type='search';q.placeholder='Código, cliente, correo, asunto u orden';q.value=state.q;q.maxLength=80;
 const sel=(options,value)=>{const s=el('select');for(const[k,v]of options)s.append(new Option(v,k));s.value=value;return s;};
 const category=sel([['','Todos los tipos'],...Object.entries(CATEGORY).map(([k,v])=>[k,v[0]])],state.category),site=sel([['','Todas las sedes'],...data.sites.map(s=>[s,s])],state.site),
  priority=sel([['','Todas las prioridades'],...Object.entries(PRIORITY)],state.priority),from=el('input'),to=el('input');from.type=to.type='date';from.value=state.from;to.value=state.to;
 bar.append(field('Buscar',q),field('Tipo',category),field('Sede',site),field('Prioridad',priority),field('Desde',from),field('Hasta',to));
 const apply=button('Aplicar filtros',()=>bar.requestSubmit(),'primary');apply.type='submit';const clear=button('Limpiar',()=>{Object.assign(state,{status:'abiertas',category:'',site:'',priority:'',q:'',from:'',to:'',page:1});list(box);});
 const tools=el('div',undefined,'pqrs-tools');tools.append(apply,clear);
 if(data.admin){tools.append(button('Exportar CSV',()=>exportCsv(query)),button('Sedes',()=>sitesDialog(()=>list(box))));}
 tools.append(button('Imprimir',()=>printView(box)));bar.append(tools);
 bar.addEventListener('submit',event=>{event.preventDefault();Object.assign(state,{q:q.value.trim(),category:category.value,site:site.value,priority:priority.value,from:from.value,to:to.value,page:1});list(box);});
 const table=el('div',undefined,'pqrs-list');table.setAttribute('role','list');
 if(!data.rows.length)table.append(el('p',data.admin?'No hay solicitudes con estos filtros.':'No tienes PQRS asignadas con estos filtros.','empty-module'));
 for(const r of data.rows){const row=el('a',undefined,'pqrs-row');row.href='#pqrs?id='+r.id;row.setAttribute('role','listitem');row.dataset.status=r.status;
  const top=el('div',undefined,'pqrs-row-top');top.append(el('strong',r.code),chip(r.category),badge(STATUS[r.status],'pqrs-badge',{status:r.status}));if(r.priority!=='normal')top.append(badge(PRIORITY[r.priority],'pqrs-priority',{priority:r.priority}));
  const subject=el('p',r.subject,'pqrs-row-subject');const meta=el('p',undefined,'pqrs-row-meta');
  meta.append(el('span',r.name),el('span',r.site),el('span','Recibida '+when(r.created_at)),el('span',r.assigned_name?'Responsable: '+r.assigned_name:'Sin responsable'));
  if(r.order_code)meta.append(el('span','Orden '+r.order_code+(r.order_verified?' · verificada':' · sin verificar')));if(r.language==='en-US')meta.append(el('span','English'));
  row.append(top,subject,meta);table.append(row);}
 const pager=el('div',undefined,'pqrs-pager');if(data.pages>1){const prev=button('Anterior',()=>{state.page--;list(box);}),next=button('Siguiente',()=>{state.page++;list(box);});prev.disabled=data.page<=1;next.disabled=data.page>=data.pages;pager.append(prev,el('span','Página '+data.page+' de '+data.pages+' · '+data.total+' solicitudes'),next);}
 else pager.append(el('span',data.total+(data.total===1?' solicitud':' solicitudes')));
 box.append(cards,chips,bar,table,pager);refreshBadge();}

async function exportCsv(query){try{const response=await fetch('/api/pqrs/export.csv?'+query.toString(),{credentials:'same-origin'});if(!response.ok){const e=await response.json().catch(()=>({}));throw new Error(e.error||'No se pudo exportar.');}
  const blob=await response.blob(),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='pqrs-'+new Date().toISOString().slice(0,10)+'.csv';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);}
 catch(error){notify(error.message);}}

function sitesDialog(done){const dialog=smallDialog('Sedes o establecimientos');const form=el('form',undefined,'pqrs-sites');const area=el('textarea');area.rows=6;area.maxLength=2000;
 const msg=el('p','','field-error');form.append(el('p','Una sede por línea. Aparecen en el formulario público de PQRS; si hay una sola, se elige sola.','config-note'),area,msg);
 const save=button('Guardar sedes',()=>form.requestSubmit(),'primary');save.type='submit';const row=el('div',undefined,'pqrs-dialog-actions');row.append(save);form.append(row);dialog.append(form);
 api('/api/pqrs/settings').then(s=>{area.value=s.sites.join('\n');area.focus();}).catch(e=>msg.textContent=e.message);
 form.addEventListener('submit',async event=>{event.preventDefault();save.disabled=true;try{await api('/api/pqrs/settings',{sites:area.value});dialog.close();notify('Sedes guardadas.',true);done&&done();}catch(e){msg.textContent=e.fields?.sites||e.message;save.disabled=false;}});}

// Impresión A4: se imprime una copia limpia del contenido (sin menús, botones ni campos), con encabezado de la empresa y fecha.
function printView(scope){document.getElementById('pqrs-print')?.remove();const sheet=el('div');sheet.id='pqrs-print';
 const head=el('header',undefined,'pqrs-print-head');const logo=new Image();logo.src='/static/logo-original.png';logo.alt='PC-DOCTOR S.A.';head.append(logo,el('div'));head.lastChild.append(el('strong','PC-DOCTOR S.A. · PQRS'),el('small','Impreso el '+when(new Date().toISOString())+' por '+(currentUser?.name||'')));
 const copy=scope.cloneNode(true);copy.querySelectorAll('button,select,textarea,input,form,.pqrs-tools,.pqrs-status-filter,.pqrs-pager,.pqrs-control,.pqrs-back').forEach(n=>n.remove());sheet.append(head,copy);document.body.append(sheet);document.body.classList.add('pqrs-printing');
 const off=()=>{document.body.classList.remove('pqrs-printing');sheet.remove();removeEventListener('afterprint',off);};addEventListener('afterprint',off);
 const go=()=>{print();setTimeout(()=>{if(document.body.classList.contains('pqrs-printing'))off();},1000);};logo.complete?go():(logo.onload=logo.onerror=go);}

async function openFile(caseId,file){try{const parts=[];for(let i=0;i<file.parts;i++){const p=await api('/api/pqrs/'+caseId+'/files/'+file.id+'/'+i);parts.push(Uint8Array.from(atob(p.data),c=>c.charCodeAt(0)));}
  const url=URL.createObjectURL(new Blob(parts,{type:file.mime}));const win=open(url,'_blank','noopener');if(!win){const a=el('a');a.href=url;a.download=file.name;document.body.append(a);a.click();a.remove();}setTimeout(()=>URL.revokeObjectURL(url),60000);}
 catch(error){notify(error.message);}}

async function detail(box,id){const c=await api('/api/pqrs/'+id);box.replaceChildren();box.classList.add('pqrs-admin');
 const reload=async()=>{await detail(box,id);refreshBadge();};
 const act=async(data,ok)=>{try{await api('/api/pqrs/'+id,data);notify(ok,true);await reload();}catch(error){notify(error.fields?Object.values(error.fields)[0]:error.message);}};
 const head=el('div',undefined,'pqrs-detail-head');const back=el('a','← Volver a la bandeja','back-link pqrs-back');back.href='#pqrs';
 const title=el('div',undefined,'pqrs-detail-title');title.append(el('h2',c.code),chip(c.category),badge(STATUS[c.status],'pqrs-badge',{status:c.status}),badge('Prioridad '+PRIORITY[c.priority].toLowerCase(),'pqrs-priority',{priority:c.priority}));
 if(c.language==='en-US')title.append(badge('Cliente en English','pqrs-lang'));
 const print=button('Imprimir A4',()=>printView(box));head.append(back,title,print);
 const grid=el('div',undefined,'pqrs-detail');const main=el('div',undefined,'pqrs-detail-main'),side=el('aside',undefined,'pqrs-detail-side');
 const section=(name,...nodes)=>{const s=el('section',undefined,'pqrs-section');s.append(el('h3',name),...nodes);return s;};
 const facts=(rows)=>{const dl=el('dl',undefined,'pqrs-facts');for(const[k,v]of rows){if(v===''||v===null||v===undefined)continue;const d=el('div');d.append(el('dt',k),el('dd',String(v)));dl.append(d);}return dl;};
 main.append(section('Solicitud',el('p',c.subject,'pqrs-subject'),el('p',c.description,'pqrs-description')));
 main.append(section('Cliente',facts([['Nombre',c.name],['Correo',c.email],['Teléfono',c.phone],['Sede',c.site],['Idioma',c.language==='en-US'?'English':'Español'],['WhatsApp',c.whatsapp_consent?'Autorizó avisos por WhatsApp':'Sin autorización de WhatsApp']])));
 if(c.order_code){const orderBox=el('div');orderBox.append(facts([['Orden indicada',c.order_code],['Verificación',c.order_verified?'Coincide con la identificación del cliente de la orden':'Sin verificar: la identificación no coincide o no se indicó']]));
  if(c.order_verified&&c.order){const link=el('a','Abrir la orden '+c.order.code,'pqrs-order-link');link.href='#orders?id='+c.order.id;orderBox.append(link);}main.append(section('Orden relacionada',orderBox));}
 if(c.files.length){const list=el('ul',undefined,'pqrs-admin-files');for(const f of c.files){const li=el('li');const thumb=el('span',undefined,'pqrs-admin-thumb');if(f.thumb){const img=new Image();img.src='data:image/jpeg;base64,'+f.thumb;img.alt='';thumb.append(img);}else thumb.textContent=f.mime==='application/pdf'?'PDF':'IMG';
   const info=el('span');info.append(el('strong',f.name),el('small',(f.size>=1048576?(f.size/1048576).toFixed(1).replace('.',',')+' MB':Math.max(1,Math.round(f.size/1024))+' KB')+' · '+(f.mime==='application/pdf'?'PDF':'Imagen')));li.append(thumb,info,button('Abrir',()=>openFile(id,f)));list.append(li);}
  main.append(section('Archivos adjuntos ('+c.files.length+')',list,el('p','Se abren desde la base, solo con sesión autorizada. No se ejecutan.','pqrs-note')));}
 const log=el('ol',undefined,'pqrs-log');for(const e of c.events){const li=el('li');li.dataset.kind=e.kind;const top=el('div',undefined,'pqrs-log-head');top.append(el('strong',EVENT[e.kind]||e.kind),badge(e.public?'Visible para el cliente':'Interno','pqrs-visibility',{public:String(!!e.public)}),el('time',when(e.created_at)));
  li.append(top);const detail=e.kind==='estado'||e.kind==='cierre'||e.kind==='reapertura'?(STATUS[e.old_value]?STATUS[e.old_value]+' → ':'')+(STATUS[e.new_value]||''):e.kind==='prioridad'?PRIORITY[e.old_value]+' → '+PRIORITY[e.new_value]:e.kind==='asignacion'?'Responsable: '+e.body:'';
  if(detail)li.append(el('p',detail,'pqrs-log-detail'));if(e.body&&e.kind!=='asignacion')li.append(el('p',e.body,'pqrs-log-body'));li.append(el('small',e.actor?'Por '+e.actor:e.kind==='mensaje_cliente'||e.kind==='creada'?'Cliente':'Sistema','pqrs-log-actor'));log.append(li);}
 main.append(section('Historial',log));
 // Gestión
 const closed=c.status==='cerrada';const panel=el('div',undefined,'pqrs-manage');
 panel.append(facts([['Recibida',when(c.created_at)],['Primera respuesta',c.first_response_at?when(c.first_response_at):'Pendiente'],['Cerrada',c.closed_at?when(c.closed_at):''],['Responsable',c.assigned_name||'Sin asignar']]));
 if(!closed){const status=el('select');for(const s of c.allowed_statuses)status.append(new Option(STATUS[s],s));status.value=c.allowed_statuses.includes(c.status)?c.status:c.allowed_statuses[0];
  const f=el('label',undefined,'pqrs-control');f.append(el('span','Estado'),status);const go2=button('Cambiar estado',()=>act({action:'status',status:status.value},'Estado actualizado.'));panel.append(f,go2);
  if(c.admin){const who=el('select');who.append(new Option('Sin asignar',''));for(const u of c.staff)who.append(new Option(u.name+(u.role==='tecnico'?' · técnico':' · administración'),String(u.id)));who.value=c.assigned_to?String(c.assigned_to):'';
   const g=el('label',undefined,'pqrs-control');g.append(el('span','Responsable'),who);panel.append(g,button('Asignar',()=>act({action:'assign',user_id:who.value},'Responsable actualizado.')));
   const pr=el('select');for(const[k,v]of Object.entries(PRIORITY))pr.append(new Option(v,k));pr.value=c.priority;const h=el('label',undefined,'pqrs-control');h.append(el('span','Prioridad'),pr);panel.append(h,button('Guardar prioridad',()=>act({action:'priority',priority:pr.value},'Prioridad actualizada.')));}
  const reply=el('textarea');reply.rows=5;reply.maxLength=5000;reply.placeholder=c.language==='en-US'?'El cliente eligió English: responde en inglés.':'Respuesta para el cliente';const after=el('select');for(const s of ['respondida','esperando_cliente','en_solucion'])after.append(new Option('Después: '+STATUS[s],s));
  const r=el('label',undefined,'pqrs-control');r.append(el('span','Responder al cliente'),reply,after);panel.append(r,button('Enviar respuesta',()=>{if(reply.value.trim().length<2){notify('Escribe la respuesta para el cliente.');reply.focus();return;}act({action:'reply',body:reply.value,status:after.value},'Respuesta registrada. El aviso al cliente queda en «Avisos».');},'primary'));}
 const note=el('textarea');note.rows=3;note.maxLength=5000;note.placeholder='Solo para el equipo; el cliente no la ve';const n=el('label',undefined,'pqrs-control');n.append(el('span','Nota interna'),note);panel.append(n,button('Guardar nota',()=>{if(note.value.trim().length<2){notify('Escribe la nota interna.');note.focus();return;}act({action:'note',body:note.value},'Nota guardada.');}));
 if(c.admin){const text=el('textarea');text.rows=3;text.maxLength=2000;const k=el('label',undefined,'pqrs-control');
  if(!closed){text.placeholder='Resolución que se comunicará al cliente';k.append(el('span','Cerrar el caso'),text);panel.append(k,button('Cerrar PQRS',async()=>{if(text.value.trim().length<5){notify('Escribe la resolución con la que se cierra el caso.');text.focus();return;}
    if(await confirmClose({title:'¿Cerrar '+c.code+'?',text:'El cliente recibirá la resolución por correo. Podrás reabrirla si es necesario.',keep:'Volver',discard:'Cerrar PQRS'})!=='discard')return;act({action:'close',body:text.value},'PQRS cerrada.');},'secondary confirm-mac-discard'));}
  else{text.placeholder='Motivo de la reapertura (se informa al cliente)';k.append(el('span','Reabrir el caso'),text);panel.append(k,button('Reabrir PQRS',()=>{if(text.value.trim().length<5){notify('Indica el motivo de la reapertura.');text.focus();return;}act({action:'reopen',body:text.value},'PQRS reabierta.');}));}}
 side.append(section('Gestión',panel));
 const notices=el('ul',undefined,'pqrs-notices');for(const x of c.notifications){const li=el('li');li.dataset.result=x.result;li.append(el('strong',{recibida:'Confirmación de recepción',estado:'Cambio de estado',respuesta:'Respuesta',cierre:'Cierre'}[x.event]||x.event),el('span','Correo · '+(RESULT[x.result]||x.result)+(x.attempts>1?' · '+x.attempts+' intentos':'')),el('small',x.detail||''),el('time',when(x.updated_at)));
  if(x.result!=='enviado')li.append(button('Reintentar',()=>act({action:'retry',notification_id:String(x.id)},'Aviso reintentado.')));notices.append(li);}
 for(const w of c.whatsapp||[]){const li=el('li');li.dataset.result=w.status;li.append(el('strong',w.label||w.event),el('span','WhatsApp · '+w.status),el('small',w.detail||''),el('time',when(w.updated_at||w.created_at)));notices.append(li);}
 if(!notices.children.length)notices.append(el('li','Sin avisos registrados.'));
 side.append(section('Avisos al cliente',notices));
 grid.append(main,side);box.append(head,grid);}

window.PqrsAdmin={render,refreshBadge,icon:ICON};
})();
