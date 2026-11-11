'use strict';
// PQRS públicas (1.5.278): formulario y seguimiento. Bilingüe con i18n.js (el mismo idioma del inicio, la Agenda y ADI). Los datos que
// escribe el cliente nunca se traducen. El servidor repite todas las comprobaciones; aquí solo se ayuda a corregir antes de enviar.
(()=>{
const I18N=window.i18n||null,LANG=()=>I18N?.lang==='en-US'?'en-US':'es-EC',EN=()=>LANG()==='en-US',T=text=>I18N?I18N.tr(text):text;
const tx=(node,text)=>{if(!node)return node;if(I18N)I18N.text(node,text);else node.textContent=text??'';return node;};
const $=id=>document.getElementById(id),make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;},makeT=(tag,text,cls)=>tx(make(tag,undefined,cls),text);
const randomId=(n=24)=>Array.from(crypto.getRandomValues(new Uint8Array(n)),b=>b.toString(16).padStart(2,'0')).join('');
const CATEGORY={peticion:'Petición',queja:'Queja',reclamo:'Reclamo',sugerencia:'Sugerencia'};
const STATUS={recibida:'Recibida',en_revision:'En revisión',asignada:'Asignada',esperando_cliente:'Esperando información del cliente',en_solucion:'En proceso de solución',respondida:'Respondida',cerrada:'Cerrada'};
const zone='America/Guayaquil',when=value=>{const d=new Date(value);return Number.isNaN(d.getTime())?'':new Intl.DateTimeFormat(LANG(),{timeZone:zone,dateStyle:'medium',timeStyle:'short'}).format(d);};
if(I18N){I18N.bind(document.querySelector('.appointment-public-header'));I18N.bind(document.querySelector('.pqrs-main'));I18N.apply();}
const title=()=>{document.title=T(location.pathname==='/pqrs/seguimiento'?'Consultar estado':'PQRS')+' | PC-DOCTOR S.A.';};
async function api(url,data){let response;try{response=await fetch(url,{method:data?'POST':'GET',credentials:'same-origin',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined});}
 catch{throw Object.assign(new Error('No pudimos completar la operación. Comprueba tu conexión e inténtalo nuevamente.'),{offline:true});}
 let body;try{body=await response.json();}catch{throw new Error('El servidor devolvió una respuesta inválida.');}
 if(!response.ok)throw Object.assign(new Error(body.error||'No se pudo completar la solicitud.'),{status:response.status,fields:body.fields||{}});return body;}

// ---- Formulario ----
const form=$('pqrs-form'),message=form.querySelector('.appointment-message'),submit=$('pqrs-submit'),done=$('pqrs-done');
let options={max_files:3,max_bytes:10485760,part_bytes:2621440,sites:[]},draft=randomId(16),requestKey='pqrs-'+randomId(20),busy=false;
const files=[];// {file,token,state:'subiendo'|'lista'|'error',progress,error,thumb,url}
function paintSites(){const select=form.elements.site,keep=select.value;select.replaceChildren(tx(new Option('',''),options.sites.length>1?'Elige la sede':'Cargando…'));for(const site of options.sites)select.add(new Option(site,site));
 if(options.sites.length===1)select.value=options.sites[0];else if(options.sites.includes(keep))select.value=keep;}
api('/api/public/pqrs/options').then(data=>{options=data;paintSites();}).catch(error=>tx(message,error.message));
const hint=name=>form.querySelector('[data-error="'+name+'"]');
function showErrors(errors){form.querySelectorAll('[aria-invalid]').forEach(n=>n.removeAttribute('aria-invalid'));form.querySelectorAll('.appointment-error').forEach(n=>tx(n,''));
 for(const[name,text]of Object.entries(errors||{})){const box=hint(name);if(box)tx(box,text);const input=name==='category'?form.querySelector('input[name=category]'):name==='files'?$('pqrs-file-input'):form.elements[name];
  if(input&&input.setAttribute){input.setAttribute('aria-invalid','true');if(box){box.id='pqrs-error-'+name;input.setAttribute('aria-describedby',[input.getAttribute('aria-describedby'),box.id].filter((v,i,a)=>v&&a.indexOf(v)===i).join(' '));}}}
 const first=form.querySelector('[aria-invalid=true]');if(first){(first.type==='radio'?first:first).focus();first.closest('label,fieldset')?.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth'});}}
function validate(){const v=name=>(form.elements[name]?.value||'').trim(),errors={};
 if(!form.querySelector('input[name=category]:checked'))errors.category='Elige el tipo de solicitud.';
 if(v('name').split(/\s+/).filter(p=>p.length>=2).length<2)errors.name='Ingresa tus nombres y apellidos completos.';
 if(!/^[^\s@<>]+@[^\s@<>.]+(?:\.[^\s@<>.]+)+$/.test(v('email')))errors.email='Ingresa un correo electrónico válido.';
 const phone=v('phone');if(!phone||(typeof window.PhoneField?.parse==='function'&&!window.PhoneField.parse(phone)))errors.phone='Ingresa un número de contacto válido.';
 if(!v('site'))errors.site='Elige la sede o establecimiento.';
 if(v('subject').length<5)errors.subject='Escribe un asunto (mínimo 5 caracteres).';
 if(v('description').length<20)errors.description='Describe tu solicitud con al menos 20 caracteres.';
 if(v('order_code')&&!/^[A-Za-z0-9-]{4,40}$/.test(v('order_code').replace(/\s+/g,'')))errors.order_code='Revisa el número de orden: solo letras, números y guiones.';
 if(v('identification')&&!/^[A-Za-z0-9-]{5,30}$/.test(v('identification')))errors.identification='Revisa el número de identificación.';
 if(!form.elements.privacy_consent.checked)errors.privacy_consent='Acepta la política de privacidad y tratamiento de datos personales.';
 if(files.some(f=>f.state==='subiendo'))errors.files='Espera a que terminen de subirse los archivos.';
 return errors;}
const count=$('pqrs-description-count');form.elements.description.addEventListener('input',()=>{count.textContent=form.elements.description.value.length+'/5000';});
form.addEventListener('input',event=>{const name=event.target.name;if(!name)return;event.target.removeAttribute('aria-invalid');const box=hint(name);if(box)tx(box,'');});
form.addEventListener('change',event=>{if(event.target.name==='category'){event.target.closest('fieldset').removeAttribute('aria-invalid');tx(hint('category'),'');}});

// ---- Adjuntos: hasta 3, 10 MB, tipo real comprobado también en el servidor; se suben por partes de 2,5 MiB ----
const list=$('pqrs-file-list'),input=$('pqrs-file-input'),TYPES=['image/jpeg','image/png','image/webp','application/pdf'];
const sizeText=bytes=>bytes>=1048576?(bytes/1048576).toFixed(1).replace('.',EN()?'.':',')+' MB':Math.max(1,Math.round(bytes/1024))+' KB';
function paintFiles(){list.replaceChildren();for(const item of files){const li=make('li',undefined,'pqrs-file');li.dataset.state=item.state;
  const preview=make('span',undefined,'pqrs-file-preview');if(item.url){const img=new Image();img.src=item.url;img.alt='';preview.append(img);}else preview.textContent='PDF';
  const info=make('span',undefined,'pqrs-file-info');info.append(make('strong',item.file.name),make('small',sizeText(item.file.size)+' · '+T(item.state==='lista'?'Listo':item.state==='error'?'No se pudo adjuntar':'Subiendo…')+(item.state==='subiendo'?' '+item.progress+' %':'')));
  if(item.error){const err=makeT('small',item.error,'pqrs-file-error');info.append(err);}
  const remove=make('button',undefined,'pqrs-file-remove');remove.type='button';remove.setAttribute('aria-label',T('Quitar archivo')+': '+item.file.name);remove.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
  remove.disabled=item.state==='subiendo';remove.addEventListener('click',()=>removeFile(item));li.append(preview,info,remove);list.append(li);}
 $('pqrs-drop').classList.toggle('is-full',files.length>=options.max_files);input.disabled=files.length>=options.max_files;}
async function removeFile(item){const at=files.indexOf(item);if(at<0)return;files.splice(at,1);if(item.url)URL.revokeObjectURL(item.url);paintFiles();
 if(item.token)try{await api('/api/public/pqrs/upload/cancel',{draft,token:item.token});}catch{}input.focus();}
async function thumbnail(file){if(!file.type.startsWith('image/'))return '';try{const bitmap=await createImageBitmap(file);const scale=Math.min(1,480/Math.max(bitmap.width,bitmap.height)),canvas=document.createElement('canvas');
  canvas.width=Math.round(bitmap.width*scale);canvas.height=Math.round(bitmap.height*scale);canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);return canvas.toDataURL('image/jpeg',.72);}catch{return '';}}
const b64=buffer=>{let out='';const bytes=new Uint8Array(buffer);for(let i=0;i<bytes.length;i+=0x8000)out+=String.fromCharCode.apply(null,bytes.subarray(i,i+0x8000));return btoa(out);};
async function upload(item){try{const buffer=await item.file.arrayBuffer(),hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buffer)),b=>b.toString(16).padStart(2,'0')).join('');
  const start=await api('/api/public/pqrs/upload/start',{draft,name:item.file.name,size:String(item.file.size),sha256:hash,type:item.file.type});item.token=start.token;
  for(let i=0;i<start.parts;i++){const slice=buffer.slice(i*start.part_bytes,(i+1)*start.part_bytes);let tries=0;
   for(;;){try{await api('/api/public/pqrs/upload/part',{draft,token:start.token,index:String(i),data:b64(slice)});break;}catch(error){if(++tries>=3||error.status===404)throw error;await new Promise(r=>setTimeout(r,800*tries));}}
   item.progress=Math.round((i+1)/start.parts*100);paintFiles();}
  await api('/api/public/pqrs/upload/finish',{draft,token:start.token,thumb:await thumbnail(item.file)});item.state='lista';}
 catch(error){item.state='error';item.error=error.message;item.token='';}paintFiles();}
input.addEventListener('change',()=>{const chosen=[...input.files];input.value='';tx(hint('files'),'');
 for(const file of chosen){if(files.length>=options.max_files){tx(hint('files'),'Puedes adjuntar hasta 3 archivos.');break;}
  const item={file,state:'subiendo',progress:0,token:'',error:'',url:file.type.startsWith('image/')?URL.createObjectURL(file):''};
  if(!TYPES.includes(file.type)){item.state='error';item.error='Solo se admiten fotografías (JPG, PNG, WEBP) y documentos PDF.';}
  else if(file.size>options.max_bytes){item.state='error';item.error='Cada archivo puede pesar como máximo 10 MB.';}
  else if(!file.size){item.state='error';item.error='El archivo está vacío.';}
  files.push(item);if(item.state==='subiendo')upload(item);}paintFiles();});

form.addEventListener('submit',async event=>{event.preventDefault();if(busy)return;tx(message,'');const errors=validate();showErrors(errors);
 if(Object.keys(errors).length){tx(message,'Revisa los datos marcados.');return;}
 busy=true;submit.disabled=true;tx(submit.querySelector('span'),'Enviando…');
 const data={request_key:requestKey,draft,locale:LANG(),category:form.querySelector('input[name=category]:checked').value,name:form.elements.name.value.trim(),email:form.elements.email.value.trim(),
  phone:form.elements.phone.value.trim(),site:form.elements.site.value,order_code:form.elements.order_code.value.trim(),identification:form.elements.identification.value.trim(),subject:form.elements.subject.value.trim(),
  description:form.elements.description.value.trim(),privacy_consent:form.elements.privacy_consent.checked,whatsapp_consent:form.elements.whatsapp_consent.checked,files:files.filter(f=>f.state==='lista').map(f=>f.token).join(',')};
 try{const result=await api('/api/public/pqrs',data);showDone(result,data);}
 catch(error){tx(message,error.offline?error.message:Object.keys(error.fields||{}).length?'Revisa los datos marcados.':error.message);showErrors(error.fields||{});}
 finally{busy=false;submit.disabled=false;tx(submit.querySelector('span'),'Enviar solicitud');}});
function trackLink(code,token){return location.origin+'/pqrs/seguimiento?codigo='+encodeURIComponent(code)+'&token='+encodeURIComponent(token);}
function showDone(result,data){form.hidden=true;done.hidden=false;done.replaceChildren();window.onbeforeunload=null;
 const head=make('div',undefined,'pqrs-done-head'),badge=make('span',undefined,'appointment-check');badge.setAttribute('aria-hidden','true');head.append(badge,makeT('h2','Solicitud recibida correctamente'));
 const code=make('p',undefined,'appointment-code');code.append(makeT('small','Número de seguimiento'),make('strong',result.code));
 const link=trackLink(result.code,result.token),box=make('div',undefined,'pqrs-link'),field=make('input');field.readOnly=true;field.value=link;field.setAttribute('aria-label',T('Enlace privado de seguimiento'));
 const copy=makeT('button','Copiar enlace','secondary');copy.type='button';copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(link);tx(copy,'Enlace copiado');}catch{field.select();}});
 const open=make('a',undefined,'primary');open.href=link;tx(open,'Consultar estado');box.append(field,copy,open);
 const facts=make('dl',undefined,'appointment-facts');for(const[label,value,translate]of [['Tipo',CATEGORY[data.category],true],['Estado','Recibida',true],['Correo electrónico',data.email]]){const row=make('div');row.append(makeT('dt',label),translate?makeT('dd',value):make('dd',value));facts.append(row);}
 done.append(head,code,facts,makeT('p','Guarda este enlace: es privado y te permite consultar el estado y responder a nuestro equipo. También lo enviamos a tu correo.','appointment-note'),box);
 if(result.duplicate)done.append(makeT('p','Esta solicitud ya estaba registrada; no se creó un duplicado.','appointment-note'));
 const again=makeT('button','Registrar otra solicitud','secondary');again.type='button';again.addEventListener('click',()=>location.reload());done.append(again);
 done.focus();done.scrollIntoView({block:'start'});}
addEventListener('beforeunload',event=>{if(form.hidden||location.pathname!=='/pqrs')return;const dirty=[...form.querySelectorAll('input:not([type=radio]):not([type=checkbox]):not([type=file]),textarea')].some(n=>n.value.trim()&&n.name!=='site');if(dirty&&!busy){event.preventDefault();event.returnValue='';}});

// ---- Seguimiento ----
const trackView=$('pqrs-track-view'),trackForm=$('pqrs-track-form'),statusBox=$('pqrs-status');let lastView=null,lastAuth=null;
function paintStatus(){if(!lastView)return;const v=lastView;statusBox.hidden=false;statusBox.replaceChildren();
 const head=make('div',undefined,'pqrs-status-head');const badge=makeT('span',STATUS[v.status]||v.status,'pqrs-badge');badge.dataset.status=v.status;head.append(make('strong',v.code),badge);
 const facts=make('dl',undefined,'appointment-facts');for(const[label,value,translate]of [['Tipo',CATEGORY[v.category],true],['Sede o establecimiento',v.site],['Asunto',v.subject],['Recibida',when(v.created_at)],['Última actualización',when(v.updated_at)],...(v.files?[['Archivos adjuntos',String(v.files)]]:[])]){const row=make('div');row.append(makeT('dt',label),translate?makeT('dd',value):make('dd',value));facts.append(row);}
 const timeline=make('ol',undefined,'pqrs-timeline');timeline.setAttribute('aria-label',T('Historial de la solicitud'));
 for(const item of v.timeline){const li=make('li');li.dataset.kind=item.kind;const title={creada:'Solicitud recibida',estado:'Cambio de estado',respuesta:'Respuesta de PC-DOCTOR S.A.',mensaje_cliente:'Tu mensaje',cierre:'Solicitud cerrada',reapertura:'Solicitud reabierta'}[item.kind]||item.kind;
  const top=make('div',undefined,'pqrs-timeline-head');top.append(makeT('strong',title),make('time',when(item.at)));li.append(top);
  if(item.status&&item.kind==='estado')li.append(makeT('span',STATUS[item.status]||item.status,'pqrs-timeline-status'));
  if(item.body){const body=make('p',item.body,'pqrs-timeline-body');li.append(body);}timeline.append(li);}
 statusBox.append(head,facts,makeT('h2','Historial de la solicitud'),timeline);
 if(v.can_reply){const reply=make('form',undefined,'pqrs-reply');reply.noValidate=true;const label=make('label');const area=make('textarea');area.name='message';area.rows=3;area.maxLength=2000;label.append(makeT('span','Responder o aportar información'),area);
  const msg=make('p',undefined,'appointment-message');msg.setAttribute('role','alert');const send=makeT('button','Enviar mensaje','primary');send.type='submit';reply.append(label,msg,send);
  reply.addEventListener('submit',async event=>{event.preventDefault();const text=area.value.trim();if(text.length<2){tx(msg,'Escribe tu mensaje.');area.focus();return;}send.disabled=true;
   try{lastView=await api('/api/public/pqrs/reply',{code:lastAuth.code,token:lastAuth.token,message:text});paintStatus();statusBox.querySelector('.pqrs-timeline li:last-child')?.scrollIntoView({block:'nearest'});}
   catch(error){tx(msg,error.message);send.disabled=false;}});statusBox.append(reply);}
 else statusBox.append(makeT('p','Esta solicitud está cerrada. Si necesitas ayuda, registra una nueva solicitud.','appointment-note'));}
async function track(code,token){const msg=trackForm.querySelector('.appointment-message');tx(msg,'');statusBox.hidden=true;
 try{lastView=await api('/api/public/pqrs/track',{code:code.trim().toUpperCase(),token:token.trim()});lastAuth={code:code.trim().toUpperCase(),token:token.trim()};paintStatus();}
 catch(error){tx(msg,error.message);}}
trackForm.addEventListener('submit',event=>{event.preventDefault();const code=trackForm.elements.code.value,token=trackForm.elements.token.value;if(!code.trim()||!token.trim()){tx(trackForm.querySelector('.appointment-message'),'Escribe el número de seguimiento y el código privado.');return;}track(code,token);});
if(location.pathname==='/pqrs/seguimiento'){$('pqrs-form-view').hidden=true;trackView.hidden=false;const q=new URLSearchParams(location.search),code=q.get('codigo')||'',token=q.get('token')||'';
 trackForm.elements.code.value=code;trackForm.elements.token.value=token;if(code&&token)track(code,token);}
title();

// ---- Cambio de idioma en vivo: textos al instante, sin tocar lo escrito ----
document.addEventListener('i18n:change',()=>{title();paintSites();paintFiles();paintStatus();count.textContent=form.elements.description.value.length+'/5000';});
})();
