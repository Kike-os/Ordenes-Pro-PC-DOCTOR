'use strict';
// Seguimiento público (1.5.240): imprimir, actualizar, miniaturas con carga y error visibles, y visor de evidencias con navegación.
// El original se pide por partes (cada respuesta cabe en una petición) y se arma aquí sin reducirlo. Los PDF se abren en otra pestaña.
document.addEventListener('click',event=>{if(event.target.closest('[data-print]'))window.print();if(event.target.closest('[data-refresh]'))location.reload();});
(()=>{const mk=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;};
 // Miniaturas: se marca la carga (o el error) también si ya ocurrió antes de que corra este script.
 for(const img of document.querySelectorAll('.tw-thumb img')){const box=img.parentElement,ok=()=>{box.dataset.ready='';},bad=()=>{box.dataset.ready='';box.dataset.error='';img.remove();};
  if(img.complete){img.naturalWidth?ok():bad();}else{img.addEventListener('load',ok,{once:true});img.addEventListener('error',bad,{once:true});}}
 async function original(url){const meta=await (await fetch(url+'/meta',{credentials:'omit'})).json();if(meta.error)throw new Error(meta.error);const parts=[];
  for(let i=0;i<meta.parts;i++){const r=await fetch(url+'?part='+i,{credentials:'omit'});if(!r.ok)throw new Error('La imagen no está disponible.');parts.push(await r.arrayBuffer());}
  return new Blob(parts,{type:meta.mime});}
 function viewer(list,start){let at=start,src='',z=1,img=null,token=0;const box=mk('div','ticket-viewer'),bar=mk('div','ticket-viewer-bar'),stage=mk('div','ticket-viewer-stage'),title=mk('strong'),count=mk('span','ticket-viewer-zoom');
  const btn=(label,fn,aria)=>{const b=mk('button','',label);b.type='button';if(aria)b.setAttribute('aria-label',aria);b.addEventListener('click',fn);return b;};
  const prev=btn('‹',()=>go(at-1),'Fotografía anterior'),next=btn('›',()=>go(at+1),'Fotografía siguiente'),zoom=mk('span','ticket-viewer-zoom','100 %');
  const set=v=>{z=Math.min(8,Math.max(1,v));if(img){img.classList.toggle('zoomed',z>1);img.style.width=z>1?(z*100)+'%':'';}zoom.textContent=Math.round(z*100)+' %';};
  bar.append(title,count,prev,next,btn('−',()=>set(z/1.5),'Alejar'),zoom,btn('+',()=>set(z*1.5),'Acercar'),btn('Ajustar',()=>set(1)));const close=btn('Cerrar',()=>done());close.className='ticket-viewer-close';bar.append(close);
  box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');box.append(bar,stage);document.body.append(box);close.focus();
  stage.addEventListener('wheel',e=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();set(z*(e.deltaY<0?1.2:1/1.2));},{passive:false});
  let drag=null;stage.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,l:stage.scrollLeft,t:stage.scrollTop};});addEventListener('pointerup',()=>{drag=null;});
  stage.addEventListener('pointermove',e=>{if(!drag)return;stage.scrollLeft=drag.l-(e.clientX-drag.x);stage.scrollTop=drag.t-(e.clientY-drag.y);});
  async function go(i){if(i<0||i>=list.length)return;at=i;const b=list[i],mine=++token;if(src)URL.revokeObjectURL(src);src='';img=null;set(1);
   title.textContent=b.dataset.name;count.textContent=(i+1)+' de '+list.length;prev.disabled=i===0;next.disabled=i===list.length-1;box.setAttribute('aria-label',b.dataset.name);stage.replaceChildren(mk('p','','Cargando fotografía…'));
   try{const blob=await original(b.dataset.file);if(mine!==token)return;src=URL.createObjectURL(blob);img=mk('img');img.alt=b.dataset.name;img.src=src;img.addEventListener('error',()=>stage.replaceChildren(mk('p','','La imagen no está disponible.')),{once:true});stage.replaceChildren(img);}
   catch(error){if(mine===token)stage.replaceChildren(mk('p','',error.message||'La imagen no está disponible.'));}}
  const key=e=>{if(e.key==='Escape')done();else if(e.key==='ArrowLeft')go(at-1);else if(e.key==='ArrowRight')go(at+1);};document.addEventListener('keydown',key);
  function done(){document.removeEventListener('keydown',key);if(src)URL.revokeObjectURL(src);box.remove();list[at]?.focus();}
  go(start);}
 document.addEventListener('click',async event=>{const b=event.target.closest('.ticket-ev');if(!b||b.getAttribute('aria-busy')==='true')return;
  if(b.dataset.mime==='application/pdf'){b.setAttribute('aria-busy','true');try{const blob=await original(b.dataset.file),src=URL.createObjectURL(blob);window.open(src,'_blank','noopener');setTimeout(()=>URL.revokeObjectURL(src),60000);}
   catch(error){alert(error.message||'El documento no está disponible.');}finally{b.removeAttribute('aria-busy');}return;}
  const photos=[...document.querySelectorAll('.ticket-ev')].filter(x=>x.dataset.mime!=='application/pdf');viewer(photos,photos.indexOf(b));});})();
// Mapa de ruta de repuestos (1.5.246): las animaciones continuas (puntos luminosos, halo y vehículo en marcha) se pausan fuera de pantalla
// y con la pestaña oculta; el SVG también detiene sus animaciones. Sin soporte del navegador, quedan como están.
(()=>{const maps=[...document.querySelectorAll('.lgx')];if(!maps.length)return;
 const set=(m,on)=>{if(on){delete m.dataset.paused;m.querySelector('svg')?.unpauseAnimations?.();}else{m.dataset.paused='';m.querySelector('svg')?.pauseAnimations?.();}};
 if('IntersectionObserver' in window){const seen=new Map();const io=new IntersectionObserver(list=>{for(const e of list){seen.set(e.target,e.isIntersecting);set(e.target,e.isIntersecting&&!document.hidden);}},{rootMargin:'80px'});
  maps.forEach(m=>io.observe(m));document.addEventListener('visibilitychange',()=>maps.forEach(m=>set(m,!document.hidden&&seen.get(m)!==false)));}})();
// Cancelación de repuestos (1.5.247): ventana de confirmación y plazo de 24 h con la hora del SERVIDOR (no la del equipo). Al vencer, el botón
// se reemplaza por el aviso con candado sin recargar la página. El servidor vuelve a comprobar el plazo al recibir la solicitud.
(()=>{const boxes=[...document.querySelectorAll('.tp-cancel[data-deadline]')];if(!boxes.length)return;
 const fmt=ms=>{const m=Math.floor(ms/60000),h=Math.floor(m/60);return h?h+' h '+String(m%60).padStart(2,'0')+' min':m?m+' min':'menos de 1 min';};
 for(const box of boxes){const offset=Number(box.dataset.now)-Date.now(),deadline=Number(box.dataset.deadline),limit=()=>Number(box.dataset.deadline)||deadline,left=box.querySelector('[data-left]'),form=box.querySelector('form'),summary=box.querySelector('summary');
  let dialog=null;
  if(typeof HTMLDialogElement==='function'){dialog=document.createElement('dialog');dialog.className='tp-dialog';dialog.setAttribute('aria-labelledby','tp-dlg-'+deadline);
   const head=document.createElement('header'),h=document.createElement('h2'),x=document.createElement('button');h.id='tp-dlg-'+deadline;h.textContent='Solicitar cancelación';x.type='button';x.className='tp-dialog-x';x.setAttribute('aria-label','Cerrar');x.textContent='×';x.addEventListener('click',()=>dialog.close());
   head.append(h,x);const name=box.closest('.tp')?.querySelector('.tp-id strong')?.textContent||'';const sub=document.createElement('p');sub.className='tp-dialog-sub';sub.textContent=name;
   const back=document.createElement('button');back.type='button';back.className='tp-dialog-back';back.textContent='Volver sin solicitar';back.addEventListener('click',()=>dialog.close());
   form.querySelector('.tp-cancel-acts')?.prepend(back);dialog.append(head,sub,form);document.body.append(dialog);
   summary.addEventListener('click',event=>{event.preventDefault();if(!box.isConnected)return;dialog.showModal();dialog.querySelector('input[name=last4]')?.focus();});
   dialog.addEventListener('close',()=>summary.focus());}
  const tick=()=>{const rest=limit()-(Date.now()+offset);if(rest>0){if(left)left.textContent='Quedan '+fmt(rest);return true;}
   // Plazo vencido: candado y explicación; una ventana abierta se cierra (el servidor rechazaría la solicitud de todos modos).
   const tpl=box.querySelector('template[data-locked]'),wrap=document.createElement('div');wrap.innerHTML=tpl?tpl.innerHTML:'';if(dialog?.open)dialog.close();dialog?.remove();box.replaceWith(...wrap.childNodes);return false;};
  if(tick()){const id=setInterval(()=>{if(!tick())clearInterval(id);},15000);}}})();
// Seguimiento A4 (1.5.248): al imprimir se anota la hora de impresión (Ecuador) y el pie de cada hoja suma el número de orden a la numeración
// «Página n de N» (regla @page de seguimiento-a4.css). Si el navegador no admite esos márgenes de página, el cierre del documento ya lleva los datos.
(()=>{const doc=document.querySelector('.pa4');if(!doc)return;let ready=false;
 const fmt=()=>{try{return new Intl.DateTimeFormat('es-EC',{timeZone:'America/Guayaquil',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date()).replace(',','');}catch{return '';}};
 addEventListener('beforeprint',()=>{const t=fmt();if(t)doc.querySelectorAll('[data-printed]').forEach(n=>{n.textContent=t;});if(ready)return;ready=true;
  const code=(doc.dataset.code||'').replace(/[^A-Za-z0-9-]/g,''),sheet=[...document.styleSheets].find(s=>(s.href||'').includes('/static/seguimiento-a4.css'));
  if(code&&sheet){try{sheet.insertRule('@page{@bottom-right{content:"Orden '+code+'\\A Página " counter(page) " de " counter(pages)}}',sheet.cssRules.length);}catch{}}});})();
// Actualización automática del seguimiento (1.5.252): cada 30 s, con la pestaña visible, se pide solo una huella opaca del estado; si cambió
// (el técnico avanzó la orden, se aprobó un presupuesto o llegó un repuesto), la página se recarga. No recarga mientras el cliente escribe o
// tiene una ventana abierta (lo hace al terminar). Sin JavaScript, la página se recarga sola cada 3 minutos.
(()=>{const box=document.querySelector('.tw-progress[data-sig]'),m=location.pathname.match(/^\/s\/([A-Za-z0-9_-]{1,64})$/);if(!box||!m)return;
 const sig=box.dataset.sig;let busy=false,pending=false,wait=30000,timer=0;
 const quiet=()=>!!(document.querySelector('dialog[open],.ticket-viewer')||document.activeElement?.closest('form,details[open]'));
 const reload=()=>{if(quiet()){pending=true;return;}location.reload();};
 async function check(){if(document.hidden||busy)return;busy=true;try{const r=await fetch('/s/'+m[1]+'/estado',{credentials:'omit',cache:'no-store'});
   if(r.ok){wait=30000;const d=await r.json();if(d.v&&d.v!==sig)reload();}else if(r.status===429||r.status>=500)wait=Math.min(wait*2,300000);}catch{wait=Math.min(wait*2,300000);}finally{busy=false;schedule();}}
 function schedule(){clearTimeout(timer);timer=setTimeout(check,wait);}
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});
 document.addEventListener('focusout',()=>setTimeout(()=>{if(pending&&!quiet())location.reload();},300));
 document.addEventListener('close',()=>{if(pending)setTimeout(reload,300);},true);
 schedule();})();
