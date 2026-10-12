'use strict';
// Chat flotante de Adi: asistente virtual y relevo real a un asesor. Compartido por el panel y la agenda de citas.
(()=>{
 const root=document.getElementById('adi-widget');if(!root)return;
 const $=id=>document.getElementById(id),toggle=$('adi-toggle'),panel=$('adi-panel'),list=$('adi-messages'),form=$('adi-form'),input=$('adi-input'),submit=form.querySelector('button'),human=$('adi-human'),status=$('adi-status'),quick=$('adi-quick'),badge=$('adi-unread'),more=$('adi-more'),menu=$('adi-menu');
 const dashboard=document.body.dataset.page==='dashboard',prefsKey='ordenes-pro:adi-chat';
 let lastId=0,busy=false,state='adi',transient='',started=false,loaded=false,typing=null,unread=0,lastDay='',failures=0,autoHidden=false,closing=null;
 let prefs={sound:true,restore:false};try{prefs=Object.assign(prefs,JSON.parse(localStorage.getItem(prefsKey)||'{}'));}catch{}const savePrefs=()=>{try{localStorage.setItem(prefsKey,JSON.stringify(prefs));}catch{}};
 const el=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
 async function request(path,data){let response;try{response=await fetch(path,{method:data===undefined?'GET':'POST',credentials:'same-origin',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});}catch{throw new Error('Sin conexión. Tu mensaje sigue en el editor.');}let result;try{result=await response.json();}catch{throw new Error('No se pudo conectar con Adi. Inténtalo de nuevo.');}if(!response.ok)throw new Error(result.error||'No se pudo enviar el mensaje.');return result;}
 // Tonos breves generados en el navegador; solo suenan si la persona ya interactuó con la página y no los desactivó.
 let audio=null;const sound=type=>{if(!prefs.sound||!navigator.userActivation?.hasBeenActive)return;try{audio=audio||new (window.AudioContext||window.webkitAudioContext)();if(audio.state==='suspended')audio.resume();const now=audio.currentTime,notes={message:[[880,0,.12]],advisor:[[660,0,.14],[880,.11,.2]],error:[[196,0,.2]]}[type];for(const[frequency,at,length]of notes){const osc=audio.createOscillator(),gain=audio.createGain();osc.type=type==='error'?'triangle':'sine';osc.frequency.value=frequency;gain.gain.setValueAtTime(.0001,now+at);gain.gain.linearRampToValueAtTime(.07,now+at+.015);gain.gain.exponentialRampToValueAtTime(.0001,now+at+length);osc.connect(gain);gain.connect(audio.destination);osc.start(now+at);osc.stop(now+at+length+.03);}}catch{}};
 // Enlaces seguros: solo direcciones https y la ruta interna de citas se convierten en vínculos.
 function rich(node,text){let last=0;for(const match of text.matchAll(/https:\/\/[^\s<>"']+[^\s<>"'.,;:!?)]|\/citas\b/g)){node.append(text.slice(last,match.index));const link=el('a',match[0]==='/citas'?'la agenda de citas':match[0]);link.href=match[0];if(match[0]!=='/citas'){link.target='_blank';link.rel='noopener noreferrer';}node.append(link);last=match.index+match[0].length;}node.append(text.slice(last));}
 const zone={timeZone:'America/Guayaquil'},clock=date=>new Intl.DateTimeFormat('es-EC',{...zone,hour:'2-digit',minute:'2-digit'}).format(date),dayKey=date=>new Intl.DateTimeFormat('en-CA',{...zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
 const dayLabel=date=>{const key=dayKey(date),today=new Date();if(key===dayKey(today))return 'Hoy';if(key===dayKey(new Date(today.getTime()-86400000)))return 'Ayer';return new Intl.DateTimeFormat('es-EC',{...zone,day:'numeric',month:'long',year:'numeric'}).format(date);};
 const bottom=()=>{list.scrollTop=list.scrollHeight;},place=node=>{typing?list.insertBefore(node,typing):list.append(node);};
 function note(text,kind){const node=el('p',text,'adi-note'+(kind?' adi-note-'+kind:''));if(kind==='error')node.setAttribute('role','alert');place(node);bottom();return node;}
 function setTyping(on){typing?.remove();typing=null;if(on){typing=el('p',undefined,'adi-message adi adi-typing');typing.setAttribute('aria-label','Adi está preparando la respuesta');typing.append(el('span'),el('span'),el('span'));list.append(typing);bottom();}}
 // Estado real de la conversación: el servidor informa «asesor conectado» únicamente cuando una persona la tomó.
 const labels={adi:'Adi AI disponible',consulting:'Consultando con Adi…',requesting:'Solicitando un asesor…',waiting:'Esperando a un asesor',advisor:'Asesor conectado',closed:'Conversación finalizada',offline:'Sin conexión. Reintentando…'};
 function paint(){const shown=failures>=3?'offline':transient||state;root.dataset.state=shown;status.textContent=labels[shown];human.hidden=state==='advisor';human.disabled=state==='waiting'||transient==='requesting';human.textContent=state==='waiting'?'Solicitud enviada: esperando a un asesor':transient==='requesting'?'Solicitando…':'Solicitar un asesor';}
 function setState(value){if(!labels[value]||value===state){paint();return;}const before=state;state=value;paint();if(!loaded)return;if(value==='advisor'){note('Un asesor se unió a la conversación.');sound('advisor');}else if(value==='closed')note('El asesor finalizó la conversación. Si escribes de nuevo, Adi continuará atendiéndote.');else if(value==='adi'&&before==='advisor')note('Adi continúa con la conversación.');}
 function showBadge(){badge.hidden=!unread;badge.textContent=unread>9?'9+':String(unread||'');toggle.setAttribute('aria-label',unread?'Abrir asistente Adi: '+unread+(unread===1?' mensaje nuevo':' mensajes nuevos'):'Abrir asistente Adi');}
 function draw(items){let incoming=0;for(const item of items||[]){if(item.id<=lastId)continue;const date=new Date(item.created_at),valid=!Number.isNaN(date.getTime());if(valid&&dayKey(date)!==lastDay){lastDay=dayKey(date);place(el('p',dayLabel(date),'adi-day'));}
   const bubble=el('p',undefined,'adi-message '+item.author),who=item.author==='client'?'':item.author==='operator'?'Asesor':'Adi';if(who)bubble.append(el('span',who,'adi-author'));const body=el('span',undefined,'adi-text');rich(body,item.content);bubble.append(body);if(valid)bubble.append(el('time',clock(date)));place(bubble);lastId=item.id;started=true;if(item.author!=='client')incoming++;}
  if(started)quick.hidden=true;if(!items?.length)return 0;bottom();return incoming;}
 let polling=null;
 function poll(){if(polling)return polling;polling=(async()=>{try{const data=await request('/api/public/adi/messages?after='+lastId),incoming=draw(data.messages);if(failures>=3)note('Conexión restablecida.');failures=0;setState(data.state||(data.mode==='human'?'waiting':data.mode));if(loaded&&incoming&&!busy){if(panel.hidden){unread+=incoming;showBadge();root.classList.remove('adi-pulse');void root.offsetWidth;root.classList.add('adi-pulse');}sound('message');}loaded=true;}catch{failures++;if(failures===3){paint();sound('error');}}finally{polling=null;}})();return polling;}
 const grow=()=>{input.style.height='auto';const full=input.scrollHeight+2;input.style.height=Math.min(full,112)+'px';input.style.overflowY=full>112?'auto':'hidden';};
 async function send(text){text=text.trim();if(busy||!text)return;busy=true;root.classList.add('adi-busy');submit.disabled=true;submit.dataset.busy='true';quick.hidden=true;list.querySelector('.adi-note-error')?.remove();const draft=input.value;input.value='';grow();
  const pending=el('p',undefined,'adi-message client adi-pending');pending.append(el('span',text,'adi-text'),el('time','Enviando…'));place(pending);bottom();if(state==='adi'||state==='closed'){transient='consulting';setTyping(true);}paint();
  try{await request('/api/public/adi/message',{message:text});pending.remove();setTyping(false);transient='';await poll();paint();document.dispatchEvent(new CustomEvent('adi:sent'));}
  catch(error){pending.remove();setTyping(false);transient='';paint();if(!input.value.trim()){input.value=draft.trim()?draft:text;grow();}if(!started)quick.hidden=false;note(error.message,'error');sound('error');}
  finally{busy=false;root.classList.remove('adi-busy');submit.disabled=false;delete submit.dataset.busy;if(!panel.hidden)input.focus();}}
 function setMenu(open){menu.hidden=!open;more.setAttribute('aria-expanded',String(open));}
 function setOpen(open,focus=true){clearTimeout(closing);if(!open)setMenu(false);if(open){panel.hidden=false;panel.classList.remove('adi-leaving');autoHidden=false;unread=0;showBadge();root.classList.remove('adi-pulse');poll();bottom();grow();if(focus)input.focus();}else if(!panel.hidden){panel.classList.add('adi-leaving');const done=()=>{panel.hidden=true;panel.classList.remove('adi-leaving');};matchMedia('(prefers-reduced-motion:reduce)').matches?done():closing=setTimeout(done,180);if(focus)toggle.focus();}
  toggle.setAttribute('aria-expanded',String(open));root.classList.toggle('adi-open',open);}
 const isOpen=()=>root.classList.contains('adi-open');
 toggle.addEventListener('click',()=>setOpen(!isOpen()));
 $('adi-minimize').addEventListener('click',()=>setOpen(false));
 // Cerrar también descarta el borrador sin enviar; minimizar lo conserva. La conversación guardada no se pierde en ningún caso.
 $('adi-close').addEventListener('click',()=>{input.value='';setOpen(false);});
 more.addEventListener('click',()=>setMenu(menu.hidden));
 const sounds=$('adi-sound'),restore=$('adi-restore');sounds.checked=prefs.sound;restore.checked=prefs.restore;
 sounds.addEventListener('change',()=>{prefs.sound=sounds.checked;savePrefs();if(prefs.sound)sound('message');});restore.addEventListener('change',()=>{prefs.restore=restore.checked;savePrefs();});
 document.addEventListener('keydown',event=>{if(event.key!=='Escape'||!isOpen()||document.querySelector('dialog[open]'))return;event.stopPropagation();if(!menu.hidden){setMenu(false);more.focus();}else setOpen(false);},true);
 document.addEventListener('pointerdown',event=>{if(root.contains(event.target))return void(!menu.hidden&&!menu.contains(event.target)&&!more.contains(event.target)&&setMenu(false));
  // En el panel de trabajo el chat se recoge al usar el resto de la pantalla, para no tapar actividad, menús ni tablas.
  if(dashboard&&isOpen())setOpen(false,false);},true);
 // Capas prioritarias (diálogos, notificaciones, menús): si se abren sobre el chat, este se minimiza y vuelve al cerrarlas.
 const layers='dialog[open],#notify-panel,#account-panel,#assistance-menu';
 let lastBox=null;const blocked=box=>{if(!box?.width)return false;for(const node of document.querySelectorAll(layers)){if(node.hidden||root.contains(node))continue;if(node.matches('dialog[open]'))return true;const other=node.getBoundingClientRect();if(Math.min(other.right,box.right)-Math.max(other.left,box.left)>16&&Math.min(other.bottom,box.bottom)-Math.max(other.top,box.top)>16)return true;}return false;};
 let layerTimer;new MutationObserver(()=>{clearTimeout(layerTimer);layerTimer=setTimeout(()=>{if(isOpen()){const box=panel.getBoundingClientRect();if(blocked(box)){setOpen(false,false);autoHidden=true;lastBox=box;}}else if(autoHidden&&!blocked(lastBox))setOpen(true,false);},140);}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['hidden','open'],childList:true});
 input.addEventListener('input',grow);
 input.addEventListener('keydown',event=>{if(event.key!=='Enter'||event.shiftKey||event.isComposing||event.keyCode===229)return;event.preventDefault();form.requestSubmit();});
 form.addEventListener('submit',event=>{event.preventDefault();send(input.value);});
 quick.addEventListener('click',event=>{const option=event.target.closest('button');if(option)send(option.dataset.message);});
 human.addEventListener('click',async()=>{if(busy||state==='waiting'||state==='advisor')return;transient='requesting';paint();try{if(!started)await request('/api/public/adi/message',{message:'Hola, necesito hablar con un asesor.'});const result=await request('/api/public/adi/human',{});transient='';await poll();setState(result.state||'waiting');note('Solicitud registrada. Te avisaremos aquí cuando un asesor tome la conversación.');document.dispatchEvent(new CustomEvent('adi:sent'));}catch(error){transient='';paint();note(error.message,'error');sound('error');}});
 // Abierto: consulta frecuente. Minimizado: solo si ya existe conversación, para avisar de respuestas del asesor.
 setInterval(()=>{if(!document.hidden&&isOpen())poll();},2500);
 setInterval(()=>{if(!document.hidden&&!isOpen()&&started)poll();},12000);
 // Al entrar permanece minimizado, salvo que la persona haya elegido «Abrir el chat al entrar» y exista una conversación.
 paint();poll().then(()=>{if(prefs.restore&&started)setOpen(true,false);});
})();
