'use strict';
// Página pública del presupuesto · Premium compacto (1.5.282). Mejora progresiva: sin este guion la página funciona y el servidor valida todo.
// El total seleccionado SOLO suma importes, bases e IVA que el servidor ya calculó por partida (data-net, data-base, data-tax): no recalcula impuestos.
(()=>{
 const money=c=>{const v=Math.round(Math.abs(c)),s=String(Math.floor(v/100)).replace(/\B(?=(\d{3})+(?!\d))/g,'.');return (c<0?'-':'')+'$'+s+','+String(v%100).padStart(2,'0');};
 const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
 const go=(node,focus)=>{if(!node)return;node.scrollIntoView({behavior:reduce?'auto':'smooth',block:'start'});if(focus)setTimeout(()=>focus.focus({preventScroll:true}),reduce?0:280);};
 const copy=async text=>{try{await navigator.clipboard.writeText(text);return true;}catch{const area=document.createElement('textarea');area.value=text;area.setAttribute('readonly','');area.className='qp-sr';document.body.append(area);area.select();let ok=false;try{ok=document.execCommand('copy');}catch{}area.remove();return ok;}};

 // Copiar el número de presupuesto
 for(const button of document.querySelectorAll('[data-qp-copy]')){button.hidden=false;const status=document.querySelector('[data-qp-copy-status]'),label=button.querySelector('span');
  button.addEventListener('click',async()=>{const ok=await copy(button.dataset.qpCopy);if(label){label.textContent=ok?'Copiado':'No se pudo copiar';setTimeout(()=>{label.textContent='Copiar';},1800);}if(status)status.textContent=ok?'Número de presupuesto copiado.':'No se pudo copiar: selecciónalo y cópialo.';});}
 // Datos bancarios (bloque común)
 for(const button of document.querySelectorAll('[data-copy-bank]')){const status=document.querySelector('[data-copy-status]');
  button.addEventListener('click',async()=>{const ok=await copy(button.dataset.copyBank||'');if(status)status.textContent=ok?'Datos bancarios copiados.':'No se pudo copiar: selecciona los datos y cópialos.';});}
 // Imprimir (A4)
 for(const button of document.querySelectorAll('[data-qp-print]')){button.hidden=false;button.addEventListener('click',()=>window.print());}

 const form=document.querySelector('[data-qp-form]');if(!form)return;
 const items=[...form.querySelectorAll('.qp-item')].map(box=>({box,name:box.dataset.name||'',net:+box.dataset.net||0,base:+box.dataset.base||0,tax:+box.dataset.tax||0,taxed:box.dataset.taxed==='1',radios:[...box.querySelectorAll('input[type=radio]')]}));
 const sums=[...document.querySelectorAll('[data-qp-sum]')],counts=[...document.querySelectorAll('[data-qp-count]')];
 const decided=document.querySelector('[data-qp-decided]'),progress=document.querySelector('[data-qp-progress]');
 const review=form.querySelector('[data-qp-review]');
 const choice=item=>{const r=item.radios.find(x=>x.checked);return r?r.value:'';};
 const li=(name,amount)=>{const row=document.createElement('li'),a=document.createElement('span'),b=document.createElement('strong');a.textContent=name;b.textContent=money(amount);row.append(a,b);return row;};
 const paint=()=>{
  const t={base_taxed:0,base_zero:0,tax:0,total:0},n={aprobado:0,rechazado:0,pendiente:0},groups={aprobado:[],rechazado:[],pendiente:[]};let done=0;
  for(const item of items){const c=choice(item);item.box.dataset.choice=c;if(c)done++;if(c)item.box.removeAttribute('data-attention');
   const kind=c==='aprobado'||c==='rechazado'?c:'pendiente';n[kind]++;groups[kind].push(item);
   if(c==='aprobado'){t.total+=item.net;t.tax+=item.tax;t[item.taxed?'base_taxed':'base_zero']+=item.base;}}
  for(const node of sums)node.textContent=money(t[node.dataset.qpSum]||0);
  for(const node of counts)node.textContent=String(n[node.dataset.qpCount]||0);
  if(decided)decided.textContent=String(done);if(progress)progress.value=done;
  if(review)for(const kind of Object.keys(groups)){const list=review.querySelector('[data-qp-rev-list="'+kind+'"]'),count=review.querySelector('[data-qp-rev-count="'+kind+'"]');if(!list)continue;
   list.replaceChildren(...(groups[kind].length?groups[kind].map(item=>li(item.name,item.net)):[Object.assign(document.createElement('li'),{className:'qp-empty',textContent:'Ninguno'})]));if(count)count.textContent=String(groups[kind].length);}
 };
 form.addEventListener('change',event=>{if(event.target.matches('.qp-item input[type=radio]'))paint();});
 // Aprobar todo / Rechazar todo: actualiza visualmente cada servicio (nada se registra hasta confirmar)
 const live=document.querySelector('[data-qp-copy-status]');
 for(const button of form.querySelectorAll('[data-quote-all]')){button.hidden=false;button.addEventListener('click',()=>{for(const item of items){const r=item.radios.find(x=>x.value===button.dataset.quoteAll);if(r)r.checked=true;}paint();
  if(live)live.textContent=button.dataset.quoteAll==='aprobado'?'Marcaste todos los servicios como aprobados. Revisa y confirma para registrarlo.':'Marcaste todos los servicios como rechazados. Revisa y confirma para registrarlo.';});}
 // Revisar selección: lleva al resumen; si falta decidir algún servicio, lleva al primero pendiente
 const confirm=document.getElementById('qp-confirm');
 for(const link of document.querySelectorAll('[data-qp-review-go]'))link.addEventListener('click',event=>{event.preventDefault();const missing=items.find(item=>!choice(item));
  if(missing){missing.box.dataset.attention='true';go(missing.box,missing.radios[0]);if(live)live.textContent='Falta decidir «'+missing.name+'».';return;}go(confirm,confirm);});
 // Barra inferior (tableta y móvil): total seleccionado y acceso al botón de confirmación
 const dock=document.querySelector('[data-qp-dock]');
 if(dock&&confirm&&'IntersectionObserver' in window){dock.hidden=false;document.body.classList.add('qp-has-dock');
  new IntersectionObserver(entries=>{for(const entry of entries)dock.hidden=entry.isIntersecting;document.body.classList.toggle('qp-has-dock',!dock.hidden);},{rootMargin:'0px 0px -30% 0px'}).observe(confirm);}
 // Firma manuscrita: trazos vectoriales en una rejilla de 1000 × 300 (mismo formato que antes)
 const pad=form.querySelector('[data-quote-sign]'),canvas=pad&&pad.querySelector('canvas'),field=form.elements.signature;
 if(canvas&&field){const ctx=canvas.getContext('2d');let strokes=[],current=null;
  const point=e=>{const b=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1000,Math.round((e.clientX-b.left)/b.width*1000))),Math.max(0,Math.min(300,Math.round((e.clientY-b.top)/b.height*300)))];};
  const draw=()=>{ctx.clearRect(0,0,1000,300);ctx.lineWidth=4;ctx.lineCap='round';ctx.lineJoin='round';ctx.strokeStyle='#0b1f3d';for(const s of strokes){ctx.beginPath();s.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();}field.value=strokes.length?JSON.stringify(strokes):'';pad.dataset.signed=String(strokes.length>0);};
  canvas.addEventListener('pointerdown',e=>{e.preventDefault();canvas.setPointerCapture(e.pointerId);current=[point(e)];strokes.push(current);});
  canvas.addEventListener('pointermove',e=>{if(!current)return;const next=point(e),last=current[current.length-1];if(Math.abs(next[0]-last[0])+Math.abs(next[1]-last[1])<3)return;if(strokes.reduce((s,x)=>s+x.length,0)<3500)current.push(next);draw();});
  const end=()=>{if(current&&current.length<2)strokes.pop();current=null;draw();};canvas.addEventListener('pointerup',end);canvas.addEventListener('pointercancel',end);
  pad.querySelector('[data-quote-clear]').addEventListener('click',()=>{strokes=[];draw();});draw();}
 // Documento de identidad (solo si el taller lo solicitó): se lee aquí y viaja en el mismo envío
 const paper=form.querySelector('[data-quote-document]');
 if(paper){const picker=paper.querySelector('input[type=file]'),hidden=paper.querySelector('input[name=id_document]'),note=paper.querySelector('[data-quote-document-status]');
  picker.addEventListener('change',()=>{const file=picker.files[0];hidden.value='';paper.dataset.ready='false';if(!file)return;if(!['image/png','image/jpeg','image/webp','application/pdf'].includes(file.type)){note.textContent='Usa una foto (JPG, PNG, WebP) o un PDF.';picker.value='';return;}if(file.size>700000){note.textContent='El archivo supera los 700 KB. Toma la foto con menor resolución o recórtala.';picker.value='';return;}
   const reader=new FileReader();reader.onload=()=>{hidden.value=String(reader.result).split(',')[1]||'';paper.dataset.ready='true';note.textContent='Documento listo: «'+file.name+'» ('+Math.max(1,Math.round(file.size/1024))+' KB).';};reader.onerror=()=>{note.textContent='No se pudo leer el archivo.';};reader.readAsDataURL(file);});}
 // Confirmar: comprobaciones amables antes del envío y bloqueo del doble envío (el servidor también lo impide)
 let sending=false;
 form.addEventListener('submit',event=>{const action=event.submitter&&event.submitter.value;
  if(sending){event.preventDefault();return;}
  if(action==='decide'){const missing=items.find(item=>!choice(item));if(missing){event.preventDefault();missing.box.dataset.attention='true';go(missing.box,missing.radios[0]);if(live)live.textContent='Falta decidir «'+missing.name+'».';return;}
   if(items.length&&items.every(item=>choice(item)==='pendiente')){event.preventDefault();if(live)live.textContent='Decide al menos un servicio: aprueba o rechaza alguno antes de confirmar.';go(items[0].box,items[0].radios[0]);return;}
   const approving=items.some(item=>choice(item)==='aprobado');if(approving&&field&&!field.value){event.preventDefault();go(pad,canvas);if(live)live.textContent='Firma en el recuadro para autorizar los servicios aprobados.';pad.dataset.signed='false';return;}}
  sending=true;for(const b of form.querySelectorAll('[data-qp-submit]')){b.setAttribute('aria-disabled','true');b.setAttribute('aria-busy',String(b===event.submitter));}
  if(event.submitter){const label=event.submitter.querySelector('span');if(label)label.textContent='Registrando…';}});
 window.addEventListener('pageshow',e=>{if(e.persisted){sending=false;for(const b of form.querySelectorAll('[data-qp-submit]')){b.removeAttribute('aria-disabled');b.removeAttribute('aria-busy');}}});
 paint();
})();
