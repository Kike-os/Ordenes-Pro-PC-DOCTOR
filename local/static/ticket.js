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
