'use strict';
// Chat público de Adi: conversación en vivo con el asistente y relevo a un asesor. Compartido por el panel y la agenda de citas.
(()=>{
 const root=document.getElementById('adi-widget');if(!root)return;
 const $=id=>document.getElementById(id),toggle=$('adi-toggle'),panel=$('adi-panel'),list=$('adi-messages'),form=$('adi-form'),input=$('adi-input'),human=$('adi-human'),status=$('adi-status'),quick=$('adi-quick'),dot=$('adi-unread');
 let lastId=0,busy=false,mode='adi',started=false,typing=null;
 const el=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
 async function request(path,data){const response=await fetch(path,{method:data===undefined?'GET':'POST',credentials:'same-origin',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});let result;try{result=await response.json();}catch{throw new Error('No se pudo conectar con Adi. Inténtalo de nuevo.');}if(!response.ok)throw new Error(result.error||'No se pudo enviar el mensaje.');return result;}
 // Enlaces seguros: solo direcciones https y la ruta interna de citas se convierten en vínculos.
 function rich(node,text){let last=0;for(const match of text.matchAll(/https:\/\/[^\s<>"']+[^\s<>"'.,;:!?)]|\/citas\b/g)){node.append(text.slice(last,match.index));const link=el('a',match[0]==='/citas'?'la agenda de citas':match[0]);link.href=match[0];if(match[0]!=='/citas'){link.target='_blank';link.rel='noopener noreferrer';}node.append(link);last=match.index+match[0].length;}node.append(text.slice(last));}
 const clock=value=>{const date=new Date(value);return Number.isNaN(date.getTime())?'':new Intl.DateTimeFormat('es-EC',{timeZone:'America/Guayaquil',hour:'2-digit',minute:'2-digit'}).format(date);};
 function note(text){list.append(el('p',text,'adi-note'));list.scrollTop=list.scrollHeight;}
 function setTyping(on){typing?.remove();typing=null;if(on){typing=el('p',undefined,'adi-message adi adi-typing');typing.setAttribute('aria-label','Adi está escribiendo');typing.append(el('span'),el('span'),el('span'));list.append(typing);list.scrollTop=list.scrollHeight;}}
 function draw(items){let incoming=false;for(const item of items||[]){if(item.id<=lastId)continue;const bubble=el('p',undefined,'adi-message '+item.author),who=item.author==='client'?'':item.author==='operator'?'Asesor':'Adi';if(who)bubble.append(el('span',who,'adi-author'));const body=el('span',undefined,'adi-text');rich(body,item.content);bubble.append(body);const at=clock(item.created_at);if(at)bubble.append(el('time',at));typing?list.insertBefore(bubble,typing):list.append(bubble);lastId=item.id;started=true;if(item.author!=='client')incoming=true;}if(started)quick.hidden=true;list.scrollTop=list.scrollHeight;if(incoming&&panel.hidden)dot.hidden=false;}
 function setMode(value){mode=value;human.disabled=value==='human';human.textContent=value==='human'?'Esperando a un asesor…':'Solicitar un asesor';status.textContent=value==='human'?'Atención con un asesor':'Asistente virtual · En línea';root.dataset.mode=value;}
 async function poll(){try{const data=await request('/api/public/adi/messages?after='+lastId);draw(data.messages);setMode(data.mode);}catch{}}
 async function send(text){if(busy||!text)return;busy=true;const submit=form.querySelector('button');submit.disabled=true;quick.hidden=true;if(mode==='adi')setTyping(true);try{const data=await request('/api/public/adi/message',{message:text});input.value='';setTyping(false);draw(data.messages);setMode(data.mode);document.dispatchEvent(new CustomEvent('adi:sent'));}catch(error){setTyping(false);note(error.message);}finally{busy=false;submit.disabled=false;input.focus();}}
 function setOpen(open,focus=true){panel.hidden=!open;toggle.setAttribute('aria-expanded',String(open));root.classList.toggle('adi-open',open);if(open){dot.hidden=true;poll();if(focus)input.focus();}else if(focus)toggle.focus();}
 toggle.addEventListener('click',()=>setOpen(panel.hidden));
 // El lanzador se presenta unos segundos con su nombre y después se recoge a un botón compacto para no tapar el contenido.
 root.classList.add('adi-intro');const settle=()=>{root.classList.remove('adi-intro');removeEventListener('scroll',settle,true);};setTimeout(settle,3800);addEventListener('scroll',settle,{capture:true,passive:true,once:true});
 $('adi-close').addEventListener('click',()=>setOpen(false));
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!panel.hidden&&!document.querySelector('dialog[open]')){event.stopPropagation();setOpen(false);}},true);
 form.addEventListener('submit',event=>{event.preventDefault();send(input.value.trim());});
 quick.addEventListener('click',event=>{const option=event.target.closest('button');if(option)send(option.dataset.message);});
 human.addEventListener('click',async()=>{human.disabled=true;try{if(!started)await request('/api/public/adi/message',{message:'Hola, necesito hablar con un asesor.'});await request('/api/public/adi/human',{});await poll();note('Solicitud enviada. Un asesor continuará la conversación en este chat.');document.dispatchEvent(new CustomEvent('adi:sent'));}catch(error){note(error.message);human.disabled=false;}});
 // Abierto: consulta frecuente. Cerrado: solo si ya existe conversación, para avisar de respuestas del asesor.
 setInterval(()=>{if(document.hidden)return;if(!panel.hidden)poll();},2500);
 setInterval(()=>{if(!document.hidden&&panel.hidden&&started)poll();},12000);
 poll();
})();
