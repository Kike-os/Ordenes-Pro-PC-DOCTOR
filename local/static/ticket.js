'use strict';
// Tarjeta de seguimiento: botón para imprimir o guardar como PDF con el diálogo del navegador.
document.addEventListener('click',event=>{if(event.target.closest('[data-print]'))window.print();});
// Evidencias autorizadas: el original se pide por partes (cada respuesta cabe en una petición) y se arma aquí, sin reducirlo. Fotografías
// en un visor con zoom (botones, rueda y arrastre); los PDF se abren en una pestaña nueva. Escape cierra el visor.
(()=>{const mk=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;};
 async function original(url){const meta=await (await fetch(url+'/meta',{credentials:'omit'})).json();if(meta.error)throw new Error(meta.error);const parts=[];
  for(let i=0;i<meta.parts;i++){const r=await fetch(url+'?part='+i,{credentials:'omit'});if(!r.ok)throw new Error('No se pudo cargar el archivo.');parts.push(await r.arrayBuffer());}
  return new Blob(parts,{type:meta.mime});}
 function viewer(src,name){const box=mk('div','ticket-viewer'),bar=mk('div','ticket-viewer-bar'),stage=mk('div','ticket-viewer-stage'),img=mk('img');img.src=src;img.alt=name;stage.append(img);let z=1;
  const set=v=>{z=Math.min(8,Math.max(1,v));img.style.width=(z*100)+'%';zoom.textContent=Math.round(z*100)+' %';};
  const btn=(label,fn)=>{const b=mk('button','',label);b.type='button';b.addEventListener('click',fn);bar.append(b);return b;};
  btn('−',()=>set(z/1.5));const zoom=mk('span','ticket-viewer-zoom','100 %');bar.append(zoom);btn('+',()=>set(z*1.5));btn('Ajustar',()=>set(1));const close=btn('Cerrar',()=>done());close.className='ticket-viewer-close';
  bar.prepend(mk('strong','',name));box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');box.setAttribute('aria-label','Evidencia '+name);box.append(bar,stage);document.body.append(box);close.focus();
  stage.addEventListener('wheel',e=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();set(z*(e.deltaY<0?1.2:1/1.2));},{passive:false});
  let drag=null;stage.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,l:stage.scrollLeft,t:stage.scrollTop};});addEventListener('pointerup',()=>{drag=null;});
  stage.addEventListener('pointermove',e=>{if(!drag)return;stage.scrollLeft=drag.l-(e.clientX-drag.x);stage.scrollTop=drag.t-(e.clientY-drag.y);});
  const key=e=>{if(e.key==='Escape')done();};document.addEventListener('keydown',key);
  function done(){document.removeEventListener('keydown',key);URL.revokeObjectURL(src);box.remove();}}
 document.addEventListener('click',async event=>{const b=event.target.closest('.ticket-ev');if(!b||b.getAttribute('aria-busy')==='true')return;b.setAttribute('aria-busy','true');
  try{const blob=await original(b.dataset.file),src=URL.createObjectURL(blob);if(b.dataset.mime==='application/pdf'){window.open(src,'_blank','noopener');setTimeout(()=>URL.revokeObjectURL(src),60000);}else viewer(src,b.dataset.name);}
  catch(error){alert(error.message||'No se pudo cargar el archivo.');}finally{b.removeAttribute('aria-busy');}});})();
