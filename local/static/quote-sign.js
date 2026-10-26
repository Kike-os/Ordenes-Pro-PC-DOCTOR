'use strict';
// Página privada del presupuesto: firma manuscrita (se guarda como trazos, no como imagen), «aprobar todo / rechazar todo»
// y total aprobado en vivo. Sin este guion la página sigue mostrando el presupuesto, pero no se puede firmar.
(()=>{
 const form=document.querySelector('.quote-form');if(!form)return;
 const money=cents=>'$'+Math.floor(cents/100)+','+String(cents%100).padStart(2,'0');
 const items=[...form.querySelectorAll('.quote-item')].map(box=>{const strong=box.querySelector('.quote-amount strong'),value=strong?Math.round(parseFloat(strong.textContent.replace('$','').replace('.','').replace(',','.'))*100):0;return {box,value,radios:[...box.querySelectorAll('input[type=radio]')]};});
 const approved=form.querySelector('[data-quote-approved]');
 const paint=()=>{let total=0,decided=0;for(const item of items){const chosen=item.radios.find(radio=>radio.checked);item.box.dataset.choice=chosen?chosen.value:'';if(chosen)decided++;if(chosen&&chosen.value==='aprobado')total+=item.value;}if(approved)approved.textContent=decided?money(total):'—';};
 form.addEventListener('change',paint);
 for(const button of form.querySelectorAll('[data-quote-all]'))button.addEventListener('click',()=>{for(const item of items){const radio=item.radios.find(node=>node.value===button.dataset.quoteAll);if(radio)radio.checked=true;}paint();});
 const pad=form.querySelector('[data-quote-sign]'),canvas=pad&&pad.querySelector('canvas'),field=form.elements.signature;
 if(canvas&&field){const context=canvas.getContext('2d');let strokes=[],current=null;
  const point=event=>{const box=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1000,Math.round((event.clientX-box.left)/box.width*1000))),Math.max(0,Math.min(300,Math.round((event.clientY-box.top)/box.height*300)))];};
  const draw=()=>{context.clearRect(0,0,1000,300);context.lineWidth=4;context.lineCap='round';context.lineJoin='round';context.strokeStyle='#0b1f3d';for(const stroke of strokes){context.beginPath();stroke.forEach(([x,y],index)=>index?context.lineTo(x,y):context.moveTo(x,y));context.stroke();}field.value=strokes.length?JSON.stringify(strokes):'';pad.dataset.signed=String(strokes.length>0);};
  canvas.addEventListener('pointerdown',event=>{event.preventDefault();canvas.setPointerCapture(event.pointerId);current=[point(event)];strokes.push(current);});
  canvas.addEventListener('pointermove',event=>{if(!current)return;const next=point(event),last=current[current.length-1];if(Math.abs(next[0]-last[0])+Math.abs(next[1]-last[1])<3)return;if(strokes.reduce((sum,stroke)=>sum+stroke.length,0)<3500)current.push(next);draw();});
  const end=()=>{if(current&&current.length<2)strokes.pop();current=null;draw();};canvas.addEventListener('pointerup',end);canvas.addEventListener('pointercancel',end);
  pad.querySelector('[data-quote-clear]').addEventListener('click',()=>{strokes=[];draw();});draw();}
 // Documento de identidad (solo si el taller lo solicitó): se lee en el navegador y viaja en el mismo envío; no se sube a ningún otro sitio.
 const paper=form.querySelector('[data-quote-document]');
 if(paper){const picker=paper.querySelector('input[type=file]'),hidden=paper.querySelector('input[name=id_document]'),note=paper.querySelector('[data-quote-document-status]');
  picker.addEventListener('change',()=>{const file=picker.files[0];hidden.value='';paper.dataset.ready='false';if(!file)return;if(!['image/png','image/jpeg','image/webp','application/pdf'].includes(file.type)){note.textContent='Usa una foto (JPG, PNG, WebP) o un PDF.';picker.value='';return;}if(file.size>700000){note.textContent='El archivo supera los 700 KB. Toma la foto con menor resolución o recórtala.';picker.value='';return;}
   const reader=new FileReader();reader.onload=()=>{hidden.value=String(reader.result).split(',')[1]||'';paper.dataset.ready='true';note.textContent='Documento listo: «'+file.name+'» ('+Math.max(1,Math.round(file.size/1024))+' KB).';};reader.onerror=()=>{note.textContent='No se pudo leer el archivo.';};reader.readAsDataURL(file);});}
 paint();
})();
// Copiar los datos bancarios del presupuesto (para pegarlos en la app del banco, WhatsApp o un correo).
(()=>{const button=document.querySelector('[data-copy-bank]');if(!button)return;const status=document.querySelector('[data-copy-status]');
 button.addEventListener('click',async()=>{const text=button.dataset.copyBank||'';try{await navigator.clipboard.writeText(text);if(status)status.textContent='Datos bancarios copiados.';}
  catch{const area=document.createElement('textarea');area.value=text;area.setAttribute('readonly','');area.style.position='fixed';area.style.opacity='0';document.body.append(area);area.select();
   try{document.execCommand('copy');if(status)status.textContent='Datos bancarios copiados.';}catch{if(status)status.textContent='No se pudo copiar: selecciona los datos y cópialos.';}area.remove();}});})();
