'use strict';
// Chat flotante de ADI: asistente virtual y relevo real a un asesor. Compartido por el panel y la Agenda de Citas.
(()=>{
 const root=document.getElementById('adi-widget');if(!root||root.dataset.ready)return;root.dataset.ready='true';
 const $=id=>document.getElementById(id),toggle=$('adi-toggle'),panel=$('adi-panel'),list=$('adi-messages'),form=$('adi-form'),input=$('adi-input'),submit=form.querySelector('button'),human=$('adi-human'),status=$('adi-status'),quick=$('adi-quick'),badge=$('adi-unread'),more=$('adi-more'),menu=$('adi-menu');
 const dashboard=document.body.dataset.page==='dashboard',prefsKey='ordenes-pro:adi-chat';
 {const orb=toggle.querySelector('.adi-orb');if(orb&&!orb.querySelector('.adi-orb-label')){const label=document.createElement('b');label.className='adi-orb-label';label.textContent='ADI';orb.append(label);for(const name of ['adi-level','adi-halo']){const piece=document.createElement('i');piece.className=name;piece.setAttribute('aria-hidden','true');toggle.prepend(piece);}}
  // Equipos modestos: menos efectos (sin desenfoques ni ondas interiores) para que la esfera no reste fluidez.
  if((navigator.hardwareConcurrency&&navigator.hardwareConcurrency<=2)||(navigator.deviceMemory&&navigator.deviceMemory<=2))root.classList.add('adi-lite');}
 let lastId=0,busy=false,state='adi',transient='',started=false,loaded=false,typing=null,unread=0,lastDay='',failures=0,autoHidden=false,closing=null;
 let prefs={sound:true,motion:true};try{prefs=Object.assign(prefs,JSON.parse(localStorage.getItem(prefsKey)||'{}'));}catch{}// Solo se guardan preferencias (sonido, voz elegida, velocidad, animaciones). Nunca el estado de la conversación, la escucha ni la voz en curso.
 delete prefs.restore;const savePrefs=()=>{try{localStorage.setItem(prefsKey,JSON.stringify(prefs));}catch{}};
 const el=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
 async function request(path,data){let response;try{response=await fetch(path,{method:data===undefined?'GET':'POST',credentials:'same-origin',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});}catch{throw new Error('Sin conexión. Tu mensaje sigue en el editor.');}let result;try{result=await response.json();}catch{throw new Error('No se pudo conectar con ADI. Inténtalo de nuevo.');}if(!response.ok)throw Object.assign(new Error(result.error||'No se pudo enviar el mensaje.'),{fields:result.fields});return result;}
 // Tonos breves generados en el navegador; solo suenan si la persona ya interactuó con la página y no los desactivó.
// Esfera 3D (WebGL): lee el estado real del asistente en cada cuadro. Si el navegador no ofrece WebGL queda la esfera CSS como alternativa ligera.
 const orbState={level:0,busy:false,speaking:false,listening:false,dim:false,beatAt:0,pressAt:-1e9};let orb3d=null;
 const readOrb=()=>{orbState.busy=root.classList.contains('adi-busy');orbState.speaking=root.dataset.voice==='speaking';orbState.listening=root.dataset.voice==='listening';orbState.still=prefs.motion===false;orbState.error=root.dataset.orb==='error';orbState.dim=root.dataset.state==='offline'||root.dataset.state==='closed';
  // Sin medidor de volumen (teléfonos), el núcleo responde al inicio y fin de voz que informa el reconocimiento.
  if(!root.dataset.meter)orbState.level=orbState.listening?(root.dataset.heard?.55:.12):0;
  // Voz natural: amplitud real del audio que suena en este instante (envolvente calculada al recibirlo). Con la voz del navegador no hay
  // acceso al audio y la esfera late con cada palabra.
  const env=orbState.speaking&&premium?.adiEnvelope;orbState.voice=env?env[Math.min(env.length-1,Math.floor(premium.currentTime*ENVELOPE_RATE))]||0:null;
  orbState.attend=performance.now()-typedAt<1600;return orbState;};
 const ENVELOPE_RATE=60;let typedAt=-1e9;
 // Envolvente de amplitud del audio de ADI: se decodifica aparte (sin tocar la reproducción, que sigue en el elemento de audio) y se resume
 // en 60 valores por segundo, normalizados para que la voz baja y la alta se distingan. Si el navegador no puede, se usa el latido por palabra.
 async function envelopeOf(bytes){const Offline=window.OfflineAudioContext||window.webkitOfflineAudioContext;if(!Offline)return null;
  const context=new Offline(1,1,22050),buffer=await new Promise((resolve,reject)=>{const out=context.decodeAudioData(bytes.buffer.slice(0),resolve,reject);out?.catch?.(reject);});
  const data=buffer.getChannelData(0),size=Math.max(1,Math.round(buffer.sampleRate/ENVELOPE_RATE)),levels=new Float32Array(Math.ceil(data.length/size));let peak=1e-4;
  for(let i=0;i<levels.length;i++){let sum=0;const end=Math.min(data.length,(i+1)*size);for(let j=i*size;j<end;j++)sum+=data[j]*data[j];levels[i]=Math.sqrt(sum/Math.max(1,end-i*size));if(levels[i]>peak)peak=levels[i];}
  for(let i=0;i<levels.length;i++)levels[i]=Math.sqrt(Math.min(1,levels[i]/(peak*.85)));return levels;}
 let headOrb=null;const headHost=panel.querySelector('.adi-avatar');
 const openHead=()=>{if(headOrb||!headHost||!orb3d||!orb3d.mirror)return;try{headOrb=orb3d.mirror(headHost);}catch{headOrb=null;}headHost.classList.toggle('adi-avatar-gl',!!headOrb);},closeHead=()=>{headOrb?.destroy();headOrb=null;headHost?.classList.remove('adi-avatar-gl');};
 // En escritorio la esfera sigue levemente al cursor: solo se guarda su posición relativa; no hay trabajo extra por movimiento.
 if(matchMedia('(pointer:fine)').matches)addEventListener('pointermove',event=>{const box=toggle.getBoundingClientRect();orbState.px=Math.max(-1,Math.min(1,(event.clientX-box.left-box.width/2)/(innerWidth/2)));orbState.py=Math.max(-1,Math.min(1,-(event.clientY-box.top-box.height/2)/(innerHeight/2)));orbState.hover=Math.hypot(event.clientX-box.left-box.width/2,event.clientY-box.top-box.height/2)<box.width*1.4;},{passive:true});
 toggle.addEventListener('pointerdown',()=>{orbState.hover=true;},{passive:true});toggle.addEventListener('pointerleave',()=>{orbState.hover=false;},{passive:true});toggle.addEventListener('pointercancel',()=>{orbState.hover=false;},{passive:true});toggle.addEventListener('focus',()=>{orbState.hover=true;});toggle.addEventListener('blur',()=>{orbState.hover=false;});
 const mountOrb=()=>{const host=toggle.querySelector('.adi-orb');if(!host||!window.AdiOrb||orb3d)return;try{orb3d=window.AdiOrb.mount(host,readOrb);}catch{orb3d=null;}if(orb3d){root.classList.add('adi-gl');root.adiOrb=orb3d;if(root.classList.contains('adi-open'))openHead();}};
 {const load=()=>{if(window.AdiOrb)return mountOrb();const script=document.createElement('script');script.src='/static/adi-orb.js';script.onload=mountOrb;document.head.append(script);};'requestIdleCallback' in window?requestIdleCallback(load,{timeout:1500}):setTimeout(load,300);}
 // Efectos generados con Web Audio (sin archivos): tonos de cristal breves y suaves. Solo suenan tras una interacción real de la persona,
 // nunca al cargar la página; uno a la vez (el nuevo apaga al anterior) y callan mientras ADI habla para no pisar su voz.
 let audio=null,playing=null,touched=false;for(const kind of ['pointerdown','keydown','touchstart'])addEventListener(kind,()=>{touched=true;},{capture:true,passive:true});
 const tones={open:[[523.25,523.25,0,.55,.034,'sine'],[783.99,783.99,.07,.6,.03,'sine'],[1046.5,1046.5,.15,.7,.018,'sine'],[1567.98,1567.98,.15,.5,.006,'sine']],
  close:[[783.99,783.99,0,.38,.028,'sine'],[523.25,523.25,.09,.5,.03,'sine']],listen:[[880,880,0,.26,.024,'sine'],[1318.5,1318.5,.02,.22,.008,'sine']],
  message:[[659.25,659.25,0,.3,.026,'sine'],[987.77,987.77,.1,.46,.024,'sine'],[1975.5,1975.5,.1,.3,.004,'sine']],advisor:[[587.33,587.33,0,.3,.03,'sine'],[880,880,.12,.5,.028,'sine']],
  error:[[311.13,293.66,0,.3,.034,'sine'],[233.08,220,.16,.42,.03,'sine']]};
 let chain=null;
 const sound=type=>{if(!prefs.sound||!tones[type]||!(touched||navigator.userActivation?.hasBeenActive))return;if(type!=='error'&&'speechSynthesis' in window&&speechSynthesis.speaking)return;
  try{const Context=window.AudioContext||window.webkitAudioContext;if(!Context)return;audio=audio||new Context();if(audio.state==='suspended')audio.resume().catch(()=>{});const now=audio.currentTime;
   // Cadena común: filtro que quita aspereza y un eco corto y muy bajo que da sensación de espacio, sin alargar el sonido.
   if(!chain){const filter=audio.createBiquadFilter(),delay=audio.createDelay(.5),feedback=audio.createGain(),wet=audio.createGain();filter.type='lowpass';filter.frequency.value=3400;filter.Q.value=.4;delay.delayTime.value=.11;feedback.gain.value=.22;wet.gain.value=.16;filter.connect(audio.destination);filter.connect(delay);delay.connect(feedback);feedback.connect(delay);delay.connect(wet);wet.connect(audio.destination);chain=filter;}
   if(playing){try{playing.gain.cancelScheduledValues(now);playing.gain.setTargetAtTime(.0001,now,.03);}catch{}}
   const master=audio.createGain();master.gain.value=1;master.connect(chain);playing=master;
   for(const[from,to,at,length,level,shape]of tones[type]){const osc=audio.createOscillator(),gain=audio.createGain();osc.type=shape;osc.frequency.setValueAtTime(from,now+at);if(to!==from)osc.frequency.exponentialRampToValueAtTime(to,now+at+length*.85);
    gain.gain.setValueAtTime(.0001,now+at);gain.gain.linearRampToValueAtTime(level,now+at+.045);gain.gain.exponentialRampToValueAtTime(.0001,now+at+length);osc.connect(gain);gain.connect(master);osc.start(now+at);osc.stop(now+at+length+.05);}}catch{}};
 // Destello al tocar la esfera: el halo se expande una vez, a la par del sonido.
 const flash=()=>{orbState.pressAt=performance.now();root.classList.remove('adi-flash');void root.offsetWidth;root.classList.add('adi-flash');setTimeout(()=>root.classList.remove('adi-flash'),650);};
 // Enlaces seguros: solo direcciones https y la ruta interna de citas se convierten en vínculos.
 function rich(node,text){let last=0;for(const match of text.matchAll(/https:\/\/[^\s<>"']+[^\s<>"'.,;:!?)]|\/citas(?:\?fecha=(\d{4})-(\d{2})-(\d{2})&hora=(\d{2}):(\d{2})&servicio=[a-z0-9_-]{1,40})?(?![\w?=&])/g)){node.append(text.slice(last,match.index));
   // Un horario ofrecido por ADI se muestra como botón: abre la Agenda de Citas con esa fecha y hora ya elegidas.
   const slot=match[1]!==undefined,hour=slot?+match[4]:0,link=el('a',slot?'Reservar '+match[3]+'/'+match[2]+' · '+((hour%12)||12)+':'+match[5]+(hour<12?' a. m.':' p. m.'):match[0]==='/citas'?'la Agenda de Citas':match[0]);link.href=match[0];if(slot)link.className='adi-book';else if(match[0]!=='/citas'){link.target='_blank';link.rel='noopener noreferrer';}node.append(link);last=match.index+match[0].length;
   // El botón de horario ya ocupa su propia línea: el salto de línea que lo sigue dejaría un hueco vacío entre botones.
   if(slot&&text[last]==='\n')last++;}node.append(text.slice(last));}
 const zone={timeZone:'America/Guayaquil'},clock=date=>new Intl.DateTimeFormat('es-EC',{...zone,hour:'2-digit',minute:'2-digit'}).format(date),dayKey=date=>new Intl.DateTimeFormat('en-CA',{...zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
 const dayLabel=date=>{const key=dayKey(date),today=new Date();if(key===dayKey(today))return 'Hoy';if(key===dayKey(new Date(today.getTime()-86400000)))return 'Ayer';return new Intl.DateTimeFormat('es-EC',{...zone,day:'numeric',month:'long',year:'numeric'}).format(date);};
 let pinned=true;const nearEnd=()=>list.scrollHeight-list.scrollTop-list.clientHeight<72;
 const bottom=force=>{if(force||pinned)list.scrollTop=list.scrollHeight;},place=node=>{pinned=nearEnd();typing?list.insertBefore(node,typing):list.append(node);};
 function note(text,kind){const node=el('p',text,'adi-note'+(kind?' adi-note-'+kind:''));if(kind==='error')node.setAttribute('role','alert');place(node);bottom();return node;}
 function setTyping(on){typing?.remove();typing=null;if(on){typing=el('p',undefined,'adi-message adi adi-typing');typing.setAttribute('aria-label','ADI está procesando tu consulta');typing.append(el('span'),el('span'),el('span'),el('em','ADI está procesando tu consulta…'));pinned=nearEnd();list.append(typing);bottom();}}
 // Estado real de la conversación: el servidor informa «asesor conectado» únicamente cuando una persona la tomó.
 const labels={adi:'ADI disponible',consulting:'ADI está procesando tu consulta…',requesting:'Contactando con soporte técnico…',waiting:'Esperando a un asesor',advisor:'Asesor conectado',closed:'Conversación finalizada',offline:'Sin conexión. Reintentando…'};
 const voiceLabels={listening:'ADI te está escuchando…',processing:'ADI está procesando tu voz…',speaking:'ADI está hablando…'};
 function paint(){const shown=failures>=3?'offline':transient||state;root.dataset.state=shown;status.textContent=(shown==='adi'||shown==='consulting')&&voiceLabels[root.dataset.voice]||labels[shown];toggle.title=/^ADI/.test(labels[shown])?labels[shown]:'ADI · '+labels[shown];human.hidden=state==='advisor';human.disabled=state==='waiting'||transient==='requesting';human.textContent=state==='waiting'?'Solicitud enviada: esperando a soporte técnico':transient==='requesting'?'Contactando…':'Contactar soporte técnico';}
 function setState(value){if(!labels[value]||value===state){paint();return;}const before=state;state=value;paint();if(!loaded)return;if(value==='advisor'){note('Un asesor se unió a la conversación.');sound('advisor');}else if(value==='closed')note('El asesor finalizó la conversación. Si escribes de nuevo, ADI continuará atendiéndote.');else if(value==='adi'&&before==='advisor')note('ADI continúa con la conversación.');}
 function showBadge(){badge.hidden=!unread;badge.textContent=unread>9?'9+':String(unread||'');toggle.setAttribute('aria-label',unread?'Abrir asistente ADI: '+unread+(unread===1?' mensaje nuevo':' mensajes nuevos'):'Abrir asistente ADI');}
 function draw(items){let incoming=0;for(const item of items||[]){if(item.id<=lastId)continue;const date=new Date(item.created_at),valid=!Number.isNaN(date.getTime());if(valid&&dayKey(date)!==lastDay){lastDay=dayKey(date);place(el('p',dayLabel(date),'adi-day'));}
   const bubble=el('p',undefined,'adi-message '+item.author),who=item.author==='client'?'':item.author==='operator'?'Asesor':'ADI';if(who)bubble.append(el('span',who,'adi-author'));const body=el('span',undefined,'adi-text');rich(body,item.content);bubble.append(body);if(valid){const stamp=el('time',clock(date));stamp.dateTime=date.toISOString();stamp.title=new Intl.DateTimeFormat('es-EC',{...zone,dateStyle:'long',timeStyle:'short'}).format(date);bubble.append(stamp);}
   if(item.author!=='client'){const copy=el('button',undefined,'adi-copy');copy.type='button';copy.title='Copiar respuesta';copy.setAttribute('aria-label','Copiar respuesta');copy.append(svg(['M9 9h10a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2z','M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1']));const text=item.content;copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(text);copy.dataset.done='true';copy.title='Copiado';setTimeout(()=>{delete copy.dataset.done;copy.title='Copiar respuesta';},1600);}catch{note('No se pudo copiar. Selecciona el texto y cópialo manualmente.','error');}});bubble.append(copy);}
   place(bubble);lastId=item.id;started=true;if(item.author!=='client')incoming++;}
  if(started){quick.hidden=true;list.querySelector('.adi-start')?.remove();}if(!items?.length)return 0;bottom();return incoming;}
 let spoken=0;const freshItems=items=>(items||[]).filter(item=>item.id>spoken&&item.author!=='client'),freshReplies=items=>freshItems(items).map(item=>item.content);
 let polling=null;
 function poll(){if(polling)return polling;polling=(async()=>{try{const data=await request('/api/public/adi/messages?after='+lastId),replies=loaded?freshItems(data.messages):[],incoming=draw(data.messages);spoken=Math.max(spoken,lastId);if(replies.length&&(prefs.voice||talk.on)&&!panel.hidden)speakItems(replies);if(failures>=3){list.querySelector('.adi-offline')?.remove();note('Conexión restablecida.');}failures=0;setState(data.state||(data.mode==='human'?'waiting':data.mode));if(loaded&&incoming&&!busy){if(panel.hidden){unread+=incoming;showBadge();root.classList.remove('adi-pulse');void root.offsetWidth;root.classList.add('adi-pulse');}sound('message');}loaded=true;list.querySelector('.adi-offline')?.remove();}catch{failures++;if(failures===3){paint();sound('error');if(!list.querySelector('.adi-offline')){const lost=note('Sin conexión con ADI. ','error');lost.classList.add('adi-offline');const again=el('button','Reintentar','adi-retry');again.type='button';again.addEventListener('click',()=>{again.disabled=true;poll().finally(()=>{again.disabled=false;});});lost.append(again);}}}finally{polling=null;}})();return polling;}
 const grow=()=>{input.style.height='auto';const full=input.scrollHeight+2;input.style.height=Math.min(full,112)+'px';input.style.overflowY=full>112?'auto':'hidden';};
 async function send(text){text=text.trim();if(busy||!text)return;busy=true;root.classList.add('adi-busy');submit.disabled=true;submit.dataset.busy='true';quick.hidden=true;list.querySelector('.adi-note-error')?.remove();const draft=input.value;input.value='';grow();
  const pending=el('p',undefined,'adi-message client adi-pending');pending.append(el('span',text,'adi-text'),el('time','Enviando…'));place(pending);bottom(true);if(state==='adi'||state==='closed'){transient='consulting';setTyping(true);bottom(true);}paint();
  try{delete root.dataset.orb;const sent=await request('/api/public/adi/message',{message:text});pending.remove();setTyping(false);transient='';const replies=freshItems(sent.messages);draw(sent.messages);spoken=Math.max(spoken,lastId);loaded=true;if(replies.length&&(prefs.voice||talk.on)&&!panel.hidden)speakItems(replies);else if(replies.length)sound('message');else if(talk.on)talkListen();if(sent.state)setState(sent.state);
   paintSuggestions(sent.suggestions||[]);if(sent.action?.type==='booking')bookingCard(sent.action);paint();poll();root.classList.remove('adi-replied');void root.offsetWidth;root.classList.add('adi-replied');setTimeout(()=>root.classList.remove('adi-replied'),1100);document.dispatchEvent(new CustomEvent('adi:sent'));}
  catch(error){pending.remove();setTyping(false);transient='';paint();root.dataset.orb='error';clearTimeout(root.orbTimer);root.orbTimer=setTimeout(()=>{delete root.dataset.orb;},6000);if(!input.value.trim()){input.value=draft.trim()?draft:text;grow();}if(!started)quick.hidden=false;const failed=note(error.message+' ','error'),again=el('button','Reintentar','adi-retry');again.type='button';
   again.addEventListener('click',()=>{failed.remove();if(input.value.trim()===text){input.value='';grow();}send(text);});failed.append(again);sound('error');}
  finally{busy=false;root.classList.remove('adi-busy');submit.disabled=false;delete submit.dataset.busy;if(!panel.hidden&&!talk.on)input.focus();}}
 // ── Voz de ADI ─────────────────────────────────────────────────────────────────────────────────────────────
 // Entrada: reconocimiento de voz del navegador (Chrome, Edge, Safari). Salida: síntesis de voz del dispositivo con una voz femenina en español
 // cuando existe. El audio del micrófono lo procesa el navegador; al servidor solo llega el texto reconocido, como cualquier mensaje escrito.
 const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition,canSpeak='speechSynthesis' in window;let recognizer=null,voices=[];
 const svg=paths=>{const node=document.createElementNS('http://www.w3.org/2000/svg','svg');node.setAttribute('viewBox','0 0 24 24');node.setAttribute('fill','none');node.setAttribute('stroke','currentColor');node.setAttribute('stroke-width','1.9');node.setAttribute('stroke-linecap','round');node.setAttribute('stroke-linejoin','round');node.setAttribute('aria-hidden','true');for(const d of paths){const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',d);node.append(path);}return node;};
 const micIcon=['M12 19v3','M19 10v2a7 7 0 0 1-14 0v-2','M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z'],voiceOn=['M11 4.7a.7.7 0 0 0-1.2-.5L6.4 7.6a1.4 1.4 0 0 1-1 .4H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.4a1.4 1.4 0 0 1 1 .4l3.4 3.4a.7.7 0 0 0 1.2-.5z','M16 9a5 5 0 0 1 0 6','M19.4 18.4a9 9 0 0 0 0-12.7'],voiceOff=['M11 4.7a.7.7 0 0 0-1.2-.5L6.4 7.6a1.4 1.4 0 0 1-1 .4H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.4a1.4 1.4 0 0 1 1 .4l3.4 3.4a.7.7 0 0 0 1.2-.5z','M22 9l-6 6','M16 9l6 6'];
 const mic=el('button',undefined,'adi-mic'),voiceToggle=el('button',undefined,'adi-voice');mic.type=voiceToggle.type='button';mic.append(svg(micIcon));submit.before(mic);more.before(voiceToggle);
 const stopVoice=el('button',undefined,'adi-stop');stopVoice.type='button';stopVoice.hidden=true;stopVoice.title='Detener la voz de ADI';stopVoice.setAttribute('aria-label',stopVoice.title);stopVoice.append(svg(['M7 7h10v10H7z']));stopVoice.addEventListener('click',()=>hush());mic.before(stopVoice);
 const voiceState=value=>{if(value)root.dataset.voice=value;else delete root.dataset.voice;paint();mic.setAttribute('aria-pressed',String(value==='listening'||!!root.classList.contains('adi-talking')));mic.title=value==='listening'?'Detener el micrófono':'Hablar con ADI';mic.setAttribute('aria-label',mic.title);stopVoice.hidden=value!=='speaking';};
 function paintVoice(){voiceToggle.replaceChildren(svg(prefs.voice?voiceOn:voiceOff));voiceToggle.setAttribute('aria-pressed',String(!!prefs.voice));voiceToggle.title=prefs.voice?'Voz de ADI activada. Pulsa para silenciarla':'Voz de ADI desactivada. Pulsa para que lea sus respuestas';voiceToggle.setAttribute('aria-label',voiceToggle.title);voiceToggle.hidden=!canSpeak;}
 // Voz femenina en español cuando el dispositivo la ofrece; si no, la primera voz en español disponible.
 const loadVoices=()=>{voices=canSpeak?speechSynthesis.getVoices().filter(voice=>/^es(-|_|$)/i.test(voice.lang)):[];};if(canSpeak){loadVoices();speechSynthesis.addEventListener?.('voiceschanged',loadVoices);}
 // Elección de voz: la que la persona fijó; si no, una femenina (primero colombiana, luego latina, luego española). Nunca una masculina conocida
 // mientras exista otra. Los nombres dependen de las voces instaladas en cada equipo o teléfono.
 const femaleNames=/salom[eé]|ximena|soledad|paulina|helena|sabina|dalia|elena|laura|m[oó]nica|paloma|elvira|lupe|andrea|camila|marisol|esperanza|catalina|valentina|sof[ií]a|isabel|luc[ií]a|carmen|renata|beatriz|larissa|yolanda|abril|estrella|irene|lia|nuria|teresa|triana|vera|female|mujer|femenin/i,maleNames=/pablo|ra[uú]l|jorge|diego|juan|carlos|[aá]lvaro|gonzalo|enrique|tom[aá]s|gerardo|jaime|luciano|pelayo|arnau|dar[ií]o|el[ií]as|nil|sa[uú]l|teo|alonso|cecilio|liberto|emilio|federico|manuel|rodrigo|sebasti[aá]n|\bmale\b|hombre|masculin/i;
 const voiceScore=voice=>(femaleNames.test(voice.name)?100:maleNames.test(voice.name)?-100:/google/i.test(voice.name)?40:0)+(/es[-_]CO/i.test(voice.lang)?30:/es[-_](419|MX|US|PE|EC|VE|CL|AR)/i.test(voice.lang)?15:0)+(/natural|neural|online|premium|enhanced/i.test(voice.name)?10:0);
 const pickVoice=()=>voices.find(voice=>voice.name===prefs.voiceName)||[...voices].sort((a,b)=>voiceScore(b)-voiceScore(a))[0]||null;
 const voiceLabel=voice=>voice.name.replace(/^Microsoft |^Google /,'').replace(/ Online \(Natural\)/,' (natural)')+' · '+voice.lang+(femaleNames.test(voice.name)?' · femenina':maleNames.test(voice.name)?' · masculina':'');
 const GREETING='Bienvenido a Órdenes Pro. Soy Adi, tu asistente virtual. ¿En qué puedo ayudarte?',SAMPLE='Hola, bienvenido a PC-DOCTOR S.A. Soy ADI, tu asistente virtual de Órdenes Pro. Estoy aquí para ayudarte con tus órdenes de reparación, citas técnicas y consultas.';
 // Texto para la voz: representación fonética independiente del texto visible. El nombre oficial «PC-DOCTOR S.A.» no cambia en pantalla;
 // aquí se convierte en «Pe ce dóctor, ese a» para que el motor no lea guiones ni siglas raras. También se quitan símbolos que generan pausas.
 const speechText=text=>String(text||'').replace(/https?:\/\/\S+/g,'el enlace indicado').replace(/(?:\borden\s+)?PCD-(\d{8})-0*(\d+)/gi,'orden $2').replace(/(?:\borden\s+)?OP-0*(\d+)/gi,'orden $1').replace(/PC[\s\-‑–]*DOCTOR(\s*,?\s*S\.?\s?A\.?(?![\wáéíóúñ]))?/gi,(match,company,at,all)=>'Pe ce dóctor'+(company?', ese a'+(/^\s*($|[A-ZÁÉÍÓÚÑ¿¡])/.test(all.slice(at+match.length))?'.':''):''))
  .replace(/\bS\.\s?A\.(?![\wáéíóúñ])/g,(match,at,all)=>'ese a'+(/^\s*($|[A-ZÁÉÍÓÚÑ¿¡])/.test(all.slice(at+match.length))?'.':'')).replace(/\bADI\b/g,'Adi').replace(/[«»"*_#`~|]/g,'').replace(/\s*[·•–—]\s*/g,', ').replace(/\s*\n+\s*/g,'. ').replace(/([.!?…:;,])\s*\.+/g,'$1').replace(/\.\s*,/g,',').replace(/,\s*,/g,',').replace(/\s{2,}/g,' ').trim();
 // Lectura por frases: la voz empieza con la primera frase sin esperar a preparar todo el texto, y los navegadores no cortan respuestas largas.
 const speechParts=text=>{const parts=[];let current='';for(const piece of text.slice(0,1400).match(/[^.!?…]+[.!?…]*\s*/g)||[]){if(current&&(current+piece).length>220){parts.push(current.trim());current='';}current+=piece;}if(current.trim())parts.push(current.trim());return parts;};
 const RATE=1.12,rate=()=>Math.min(1.5,Math.max(.8,Number(prefs.rate)||RATE));let speech=0;
 function hush(){speech++;root.classList.remove('adi-beat');if(canSpeak)speechSynthesis.cancel();if(premium){premium.onended=premium.onerror=null;premium.pause();premium=null;}if(root.dataset.voice==='speaking')voiceState(talk.on?'listening':'');}
 function speak(text,force){if(!canSpeak||(!prefs.voice&&!force)||!text)return;hush();const turn=speech,voice=pickVoice(),parts=speechParts(speechText(text));if(!parts.length)return;
  parts.forEach((part,index)=>{const say=new SpeechSynthesisUtterance(part);say.lang=voice?.lang||'es-CO';if(voice)say.voice=voice;say.rate=rate();say.pitch=1.06;say.volume=1;
   if(!index)say.onstart=()=>{if(turn===speech){orbState.beatAt=performance.now();voiceState('speaking');}};
   if(index===parts.length-1)say.onend=()=>{if(turn===speech&&root.dataset.voice==='speaking'){voiceState('');talkListen();}};
   say.onboundary=()=>{if(turn!==speech)return;orbState.beatAt=performance.now();root.classList.remove('adi-beat');void root.offsetWidth;root.classList.add('adi-beat');};
   say.onerror=()=>{if(turn===speech&&root.dataset.voice==='speaking')voiceState('');};speechSynthesis.speak(say);});}
 const micErrors={'not-allowed':'El micrófono está bloqueado. Permite su uso en el candado de la barra de direcciones y vuelve a intentarlo.','service-not-allowed':'El micrófono está bloqueado. Permite su uso en el candado de la barra de direcciones y vuelve a intentarlo.','audio-capture':'No se encontró ningún micrófono conectado.','no-speech':'No escuché nada. Pulsa el micrófono y habla de nuevo.',network:'No hay conexión para el reconocimiento de voz. Revisa tu internet.',aborted:''};
 let meter=null;const phone=/Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
 async function startMeter(){if(phone||meter||!navigator.mediaDevices?.getUserMedia||!(window.AudioContext||window.webkitAudioContext))return;
  try{const stream=await navigator.mediaDevices.getUserMedia({audio:true});if(root.dataset.voice!=='listening'){stream.getTracks().forEach(track=>track.stop());return;}
   const context=new (window.AudioContext||window.webkitAudioContext)(),analyser=context.createAnalyser();analyser.fftSize=256;context.createMediaStreamSource(stream).connect(analyser);const data=new Uint8Array(analyser.fftSize);let frame=0,smooth=0;
   const tick=()=>{analyser.getByteTimeDomainData(data);let sum=0;for(const value of data){const d=(value-128)/128;sum+=d*d;}smooth=smooth*.7+Math.min(1,Math.sqrt(sum/data.length)*5)*.3;orbState.level=smooth;root.style.setProperty('--adi-level',smooth.toFixed(3));frame=requestAnimationFrame(tick);};
   meter={stop(){cancelAnimationFrame(frame);stream.getTracks().forEach(track=>track.stop());context.close().catch(()=>{});root.style.removeProperty('--adi-level');delete root.dataset.meter;}};root.dataset.meter='true';tick();}catch{}}
 const stopMeter=()=>{meter?.stop();meter=null;};
 function listen(){if(recognizer){recognizer.stop();return;}if(!Recognition){note('Este navegador no permite hablar con ADI. Usa Chrome, Edge o Safari, o escribe tu mensaje.','error');return;}if(busy)return;hush();
  let heard='',failed=false;recognizer=new Recognition();recognizer.lang='es-EC';recognizer.interimResults=true;recognizer.continuous=false;recognizer.maxAlternatives=1;
  recognizer.onstart=()=>{voiceState('listening');sound('listen');startMeter();status.textContent='ADI te está escuchando…';list.querySelector('.adi-note-error')?.remove();};
  recognizer.onresult=event=>{let text='';for(const result of event.results)text+=result[0].transcript;heard=text.trim();input.value=heard;grow();};
  recognizer.onspeechstart=()=>{root.dataset.heard='true';};recognizer.onspeechend=()=>{delete root.dataset.heard;};
  recognizer.onerror=event=>{failed=true;const message=micErrors[event.error]??'No se pudo usar el micrófono ('+event.error+').';if(message)note(message,'error');};
  recognizer.onend=()=>{recognizer=null;stopMeter();delete root.dataset.heard;voiceState('');paint();if(failed||!heard)return;if(!prefs.voice&&canSpeak){prefs.voice=true;savePrefs();paintVoice();}send(heard);};
  try{recognizer.start();}catch{recognizer=null;voiceState('');note('No se pudo iniciar el micrófono. Inténtalo de nuevo.','error');}}
 // ── Voz natural (OpenAI, desde el servidor) y conversación continua ─────────────────────────────────────────────
 // La voz natural lee respuestas de ADI guardadas en esta conversación; si no está disponible (sin clave, tope diario o fallo), se usa la
 // voz del navegador. En la conversación continua el navegador detecta cuándo empieza y termina de hablar la persona (con cancelación de
 // eco) y envía solo esa intervención al servidor para transcribirla. El micrófono se pide únicamente cuando la persona inicia la conversación.
 let voiceCfg=null,premium=null;const loadVoiceCfg=()=>voiceCfg?Promise.resolve(voiceCfg):request('/api/public/adi/voice').then(cfg=>voiceCfg=cfg).catch(()=>voiceCfg={premium:false,continuous:false,speed:1,vad:{threshold:.04,silence_ms:900}});loadVoiceCfg();
 async function playPremium(body){const turn=++speech;const data=await request('/api/public/adi/speech',body);if(turn!==speech)return;
  const bytes=Uint8Array.from(atob(data.audio),ch=>ch.charCodeAt(0)),url=URL.createObjectURL(new Blob([bytes],{type:data.mime})),sound2=new Audio(url);
  envelopeOf(bytes).then(levels=>{if(levels)sound2.adiEnvelope=levels;}).catch(()=>{});sound2.addEventListener('ended',()=>URL.revokeObjectURL(url),{once:true});sound2.playbackRate=Math.min(1.25,Math.max(.8,Number(voiceCfg?.speed)||1));premium=sound2;
  sound2.onplay=()=>{if(turn===speech){orbState.beatAt=performance.now();voiceState('speaking');}};sound2.onended=()=>{if(premium===sound2)premium=null;if(turn===speech&&root.dataset.voice==='speaking'){voiceState('');talkListen();}};
  sound2.onerror=()=>{if(premium===sound2)premium=null;if(turn===speech){voiceState('');talkListen();}};await sound2.play();}
 async function speakItems(items){const last=items[items.length-1],text=items.map(item=>item.content).join(' ');await loadVoiceCfg();
  if(voiceCfg.premium&&last?.id){try{hush();await playPremium({message_id:String(last.id)});return;}catch(error){
   // Una interrupción (la persona habla encima o se cierra el chat) cancela la reproducción: no es un fallo y no apaga la voz natural.
   if(error?.name==='AbortError')return;
   // Solo un error del servidor (sin clave, tope diario, OpenAI caído) pasa a la voz del navegador durante esta visita.
   if(!(error instanceof DOMException))voiceCfg.premium=false;}}
  if(canSpeak)speak(text,true);else talkListen();}
 const talk={on:false,muted:false,stream:null,ctx:null,analyser:null,frame:0,rec:null,chunks:[],mime:'',floor:.008,started:0,voiceAt:0,lastVoice:0,loud:0,busy:false};
 const talkBar=el('div',undefined,'adi-talk'),talkDot=el('span',undefined,'adi-talk-dot'),talkText=el('span','Conversación por voz','adi-talk-text'),talkMute=el('button',undefined,'adi-talk-mute'),talkEnd=el('button','Finalizar','adi-talk-end');
 talkMute.type=talkEnd.type='button';talkMute.append(svg(micIcon));talkMute.title='Silenciar el micrófono';talkMute.setAttribute('aria-label',talkMute.title);talkMute.setAttribute('aria-pressed','false');talkEnd.setAttribute('aria-label','Finalizar la conversación por voz');
 talkBar.setAttribute('role','status');talkBar.hidden=true;talkBar.append(talkDot,talkText,talkMute,talkEnd);form.before(talkBar);
 const talkPaint=()=>{const v=root.dataset.voice;talkBar.dataset.state=talk.muted?'muted':v==='speaking'?'speaking':v==='processing'||talk.busy?'processing':'listening';talkText.textContent=talk.muted?'Micrófono en pausa':v==='speaking'?'ADI está hablando · habla para interrumpirla':v==='processing'||talk.busy?'Procesando…':root.dataset.heard?'Te escucho…':'Escuchando · habla cuando quieras';};
 const pickMime=()=>['audio/webm;codecs=opus','audio/webm','audio/mp4','audio/ogg;codecs=opus'].find(type=>window.MediaRecorder?.isTypeSupported?.(type))||'';
 function talkListen(){if(!talk.on||talk.busy||root.dataset.voice==='speaking')return;voiceState('listening');talkPaint();}
 function talkRecord(now){if(talk.rec||!talk.stream)return;try{talk.chunks=[];talk.rec=new MediaRecorder(talk.stream,talk.mime?{mimeType:talk.mime}:undefined);talk.rec.ondataavailable=event=>{if(event.data?.size)talk.chunks.push(event.data);};talk.rec.start(250);talk.started=now;root.dataset.heard='true';talkPaint();}catch{talk.rec=null;}}
 function talkStop(){const rec=talk.rec;if(!rec)return;talk.rec=null;delete root.dataset.heard;const duration=Math.round(performance.now()-talk.started);
  rec.onstop=async()=>{const blob=new Blob(talk.chunks,{type:rec.mimeType||talk.mime||'audio/webm'});talk.chunks=[];if(!talk.on||duration<450||blob.size<1200){talkListen();return;}
   talk.busy=true;voiceState('processing');root.classList.add('adi-busy');talkPaint();
   try{const audio=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]||'');reader.onerror=reject;reader.readAsDataURL(blob);});
    const heard=await request('/api/public/adi/listen',{audio,mime:blob.type,duration_ms:String(duration)});talk.busy=false;root.classList.remove('adi-busy');
    if(!heard.text){talkListen();return;}if(talk.on)await send(heard.text);}
   catch(error){talk.busy=false;root.classList.remove('adi-busy');note(error.message+(talk.on?' Puedes seguir escribiendo.':''),'error');if(/disponible|límite/i.test(error.message||''))endTalk();else talkListen();}};
  try{rec.stop();}catch{talkListen();}}
 function talkTick(){if(!talk.on)return;const data=new Uint8Array(talk.analyser.fftSize);talk.analyser.getByteTimeDomainData(data);let sum=0;for(const value of data){const d=(value-128)/128;sum+=d*d;}const rms=Math.sqrt(sum/data.length),now=performance.now();
  orbState.level=Math.min(1,rms*6);root.style.setProperty('--adi-level',orbState.level.toFixed(3));root.dataset.meter='true';
  const cfg=voiceCfg?.vad||{threshold:.04,silence_ms:900},threshold=Math.max(cfg.threshold,talk.floor*3),speaking=root.dataset.voice==='speaking';
  if(!talk.muted&&!talk.busy){
   if(speaking){// Interrupción: la persona habla por encima de ADI (la cancelación de eco evita que se escuche a sí misma).
    if(rms>threshold*1.6){talk.loud=talk.loud||now;if(now-talk.loud>260){talk.loud=0;hush();talkRecord(now);talk.lastVoice=now;}}else talk.loud=0;}
   else if(rms>threshold){talk.lastVoice=now;if(!talk.rec){talk.voiceAt=talk.voiceAt||now;if(now-talk.voiceAt>90)talkRecord(now);}}
   else{talk.voiceAt=0;if(!talk.rec)talk.floor=talk.floor*.98+rms*.02;}
   if(talk.rec&&(now-talk.lastVoice>cfg.silence_ms||now-talk.started>30000))talkStop();}
  talk.frame=requestAnimationFrame(talkTick);}
 async function startTalk(){if(talk.on)return;await loadVoiceCfg();
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder||!voiceCfg.premium){listen();return;}
  try{talk.stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1}});}
  catch(error){note(error?.name==='NotAllowedError'?'El micrófono está bloqueado. Permite su uso en el candado de la barra de direcciones para conversar con ADI.':'No se pudo usar el micrófono. Puedes escribir tu mensaje.','error');return;}
  talk.on=true;talk.muted=false;talk.mime=pickMime();talk.ctx=new (window.AudioContext||window.webkitAudioContext)();talk.analyser=talk.ctx.createAnalyser();talk.analyser.fftSize=1024;talk.ctx.createMediaStreamSource(talk.stream).connect(talk.analyser);
  prefs.voice=true;savePrefs();paintVoice();talkBar.hidden=false;root.classList.add('adi-talking');mic.setAttribute('aria-pressed','true');sound('listen');talkTick();
  // Saludo hablado una sola vez, al iniciar la primera conversación (nunca al cargar la página).
  if(!started&&voiceCfg.premium){try{await playPremium({kind:'greeting'});return;}catch(error){if(error?.name==='AbortError')return;}}talkListen();}
 function endTalk(){if(!talk.on)return;talk.on=false;cancelAnimationFrame(talk.frame);try{talk.rec?.stop();}catch{}talk.rec=null;talk.stream?.getTracks().forEach(track=>track.stop());talk.ctx?.close().catch(()=>{});talk.stream=talk.ctx=null;
  talkBar.hidden=true;root.classList.remove('adi-talking','adi-busy');delete root.dataset.meter;delete root.dataset.heard;root.style.removeProperty('--adi-level');hush();voiceState('');mic.setAttribute('aria-pressed','false');}
 talkMute.addEventListener('click',()=>{talk.muted=!talk.muted;talk.stream?.getAudioTracks().forEach(track=>{track.enabled=!talk.muted;});if(talk.muted&&talk.rec){try{talk.rec.stop();}catch{}talk.rec=null;}talkMute.setAttribute('aria-pressed',String(talk.muted));talkMute.title=talk.muted?'Activar el micrófono':'Silenciar el micrófono';talkMute.setAttribute('aria-label',talkMute.title);talkPaint();});
 talkEnd.addEventListener('click',()=>{endTalk();input.focus();});
 new MutationObserver(()=>{if(talk.on)talkPaint();}).observe(root,{attributes:true,attributeFilter:['data-voice','data-heard']});
 // El micrófono inicia la conversación continua (si la voz natural está disponible); si no, el dictado de un turno de siempre.
 mic.addEventListener('click',()=>{if(talk.on){endTalk();return;}loadVoiceCfg().then(cfg=>cfg.continuous&&cfg.premium&&window.MediaRecorder?startTalk():listen());});voiceToggle.addEventListener('click',()=>{prefs.voice=!prefs.voice;savePrefs();paintVoice();if(!prefs.voice)hush();else speak(GREETING);});voiceState('');paintVoice();
 // Selector de voz en el menú de opciones: lista las voces en español del dispositivo; la elegida queda guardada.
 const voiceBox=el('label',undefined,'adi-voice-pick'),voiceSelect=el('select');voiceSelect.setAttribute('aria-label','Voz de ADI');voiceBox.append(el('span','Voz de ADI'),voiceSelect);voiceBox.hidden=!canSpeak;menu.append(voiceBox);
 const speedBox=el('label',undefined,'adi-voice-pick adi-voice-speed'),speed=el('input'),speedValue=el('b');speed.type='range';speed.min='0.8';speed.max='1.5';speed.step='0.02';speed.value=String(rate());speed.setAttribute('aria-label','Velocidad de la voz de ADI');const speedLabel=el('span','Velocidad de voz ');speedLabel.append(speedValue);speedBox.append(speedLabel,speed);speedBox.hidden=!canSpeak;
 const paintSpeed=()=>{speedValue.textContent=Number(speed.value).toFixed(2).replace('.',',')+'×';speed.setAttribute('aria-valuetext',speedValue.textContent);};paintSpeed();speed.addEventListener('input',paintSpeed);speed.addEventListener('change',()=>{prefs.rate=Number(speed.value);savePrefs();if(voices.length)speak('Así sonaré a esta velocidad.',true);});speed.addEventListener('click',event=>event.stopPropagation());menu.append(speedBox);
 const sample=el('button','Escuchar muestra de voz','adi-voice-sample');sample.type='button';sample.hidden=!canSpeak;sample.addEventListener('click',event=>{event.stopPropagation();if(!voices.length){note('Este dispositivo no tiene voces en español instaladas.','error');return;}speak(SAMPLE,true);});menu.append(sample);
 function fillVoices(){loadVoices();const chosen=pickVoice();voiceSelect.replaceChildren();if(!voices.length){voiceSelect.append(new Option('Este dispositivo no tiene voces en español',''));voiceSelect.disabled=true;return;}voiceSelect.disabled=false;for(const voice of [...voices].sort((a,b)=>voiceScore(b)-voiceScore(a)))voiceSelect.append(new Option(voiceLabel(voice),voice.name));if(chosen)voiceSelect.value=chosen.name;}
 voiceSelect.addEventListener('change',()=>{prefs.voiceName=voiceSelect.value;prefs.voice=true;savePrefs();paintVoice();speak(SAMPLE);});voiceSelect.addEventListener('click',event=>event.stopPropagation());
 if(canSpeak){fillVoices();speechSynthesis.addEventListener?.('voiceschanged',fillVoices);}
 function setMenu(open){menu.hidden=!open;more.setAttribute('aria-expanded',String(open));}
 function setOpen(open,focus=true){clearTimeout(closing);if(!open){setMenu(false);endTalk();hush();recognizer?.abort();}if(!open)closeHead();if(open){panel.hidden=false;panel.classList.remove('adi-leaving');openHead();pinned=true;autoHidden=false;unread=0;showBadge();root.classList.remove('adi-pulse');poll();bottom();grow();if(focus)input.focus();}else if(!panel.hidden){panel.classList.add('adi-leaving');const done=()=>{panel.hidden=true;panel.classList.remove('adi-leaving');};matchMedia('(prefers-reduced-motion:reduce)').matches?done():closing=setTimeout(done,180);if(focus)toggle.focus();}
  toggle.setAttribute('aria-expanded',String(open));root.classList.toggle('adi-open',open);}
 const isOpen=()=>root.classList.contains('adi-open');
 toggle.addEventListener('click',()=>{const opening=!isOpen();flash();sound(opening?'open':'close');setOpen(opening);});
 // Aviso de bienvenida en la pantalla de acceso: un mensaje pequeño junto a la esfera, una vez por visita. No abre el chat ni reproduce
 // sonido por su cuenta; se puede cerrar, se retira solo a los ocho segundos y al pulsarlo abre el chat que ya existe.
 if(!dashboard){const seenKey='ordenes-pro:adi-saludo';let seen=false;try{seen=sessionStorage.getItem(seenKey)==='1';}catch{}
  if(!seen){let hide=null;const nudge=el('div',undefined,'adi-nudge'),open=el('button',undefined,'adi-nudge-text'),close=el('button',undefined,'adi-nudge-close'),spark=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS(spark.namespaceURI,'path'),cross=document.createElementNS(spark.namespaceURI,'svg'),line=document.createElementNS(spark.namespaceURI,'path');
   spark.setAttribute('viewBox','0 0 24 24');spark.setAttribute('aria-hidden','true');path.setAttribute('d','M12 3l1.9 5.8a2 2 0 0 0 1.3 1.3L21 12l-5.8 1.9a2 2 0 0 0-1.3 1.3L12 21l-1.9-5.8a2 2 0 0 0-1.3-1.3L3 12l5.8-1.9a2 2 0 0 0 1.3-1.3z');spark.append(path);cross.setAttribute('viewBox','0 0 24 24');cross.setAttribute('aria-hidden','true');line.setAttribute('d','M18 6 6 18M6 6l12 12');cross.append(line);
   open.type='button';close.type='button';const greet=el('span','¡Hola! Soy ADI, tu asistente virtual de PC-DOCTOR. ¿Necesitas ayuda? ¡Puedes hablar conmigo!');loadVoiceCfg().then(cfg=>{if(cfg.greeting)greet.textContent=cfg.greeting;});open.append(spark,greet);close.append(cross);close.setAttribute('aria-label','Cerrar el aviso de ADI');nudge.setAttribute('role','status');nudge.append(open,close);
   const remember=()=>{try{sessionStorage.setItem(seenKey,'1');}catch{}},dismiss=()=>{clearTimeout(hide);nudge.classList.remove('adi-nudge-in');setTimeout(()=>nudge.remove(),260);};
   close.addEventListener('click',event=>{event.stopPropagation();remember();dismiss();});open.addEventListener('click',()=>{remember();dismiss();if(!isOpen())toggle.click();});toggle.addEventListener('click',()=>{if(nudge.isConnected){remember();dismiss();}});
   // Tres segundos después de cargar, y solo si la persona no está ya usando el chat ni escribiendo sus credenciales.
   setTimeout(()=>{if(isOpen()||document.activeElement?.matches?.('#login-form input')&&document.activeElement.value)return;root.append(nudge);remember();
    // Si a la izquierda de la esfera taparía el botón de citas o el formulario, el aviso se coloca encima de la esfera.
    {const hit=node=>{if(!node)return false;const x=nudge.getBoundingClientRect(),y=node.getBoundingClientRect();return !(x.right<=y.left||y.right<=x.left||x.bottom<=y.top||y.bottom<=x.top);};if(hit(document.querySelector('.login-book'))||hit(document.querySelector('.access-card')))nudge.classList.add('adi-nudge-up');}
    requestAnimationFrame(()=>nudge.classList.add('adi-nudge-in'));hide=setTimeout(dismiss,8000);},3000);}}
 $('adi-minimize').addEventListener('click',()=>{sound('close');setOpen(false);});
 // Cerrar también descarta el borrador sin enviar; minimizar lo conserva. La conversación guardada no se pierde en ningún caso.
 $('adi-close').addEventListener('click',()=>{input.value='';sound('close');setOpen(false);});
 more.addEventListener('click',()=>setMenu(menu.hidden));
 const sounds=$('adi-sound'),restore=$('adi-restore');sounds.checked=prefs.sound;
 // La antigua opción «Abrir el chat al entrar» pasa a ser la preferencia de animaciones de la esfera.
 restore.checked=prefs.motion!==false;restore.nextElementSibling.textContent='Animaciones de la esfera';const applyMotion=()=>{root.classList.toggle('adi-still',prefs.motion===false);};applyMotion();
 sounds.addEventListener('change',()=>{prefs.sound=sounds.checked;savePrefs();if(prefs.sound)sound('message');});restore.addEventListener('change',()=>{prefs.motion=restore.checked;savePrefs();applyMotion();});
 document.addEventListener('keydown',event=>{if(event.key!=='Escape'||!isOpen()||document.querySelector('dialog[open]'))return;
  // Dentro de la consulta de reparación, Escape la cancela sin cerrar el chat.
  if(check?.isConnected&&check.contains(event.target)){event.stopPropagation();check.querySelector('.adi-check-cancel').click();return;}
  if(booking?.isConnected&&booking.contains(event.target)){event.stopPropagation();booking.querySelector('.adi-check-cancel').click();return;}
  // Acoplado junto al acceso, Escape solo actúa cuando el foco está dentro del chat: no debe cerrarlo mientras se escribe la contraseña.
  if(root.classList.contains('adi-docked')&&!root.contains(document.activeElement))return;event.stopPropagation();if(!menu.hidden){setMenu(false);more.focus();}else setOpen(false);},true);
 document.addEventListener('pointerdown',event=>{if(root.contains(event.target))return void(!menu.hidden&&!menu.contains(event.target)&&!more.contains(event.target)&&setMenu(false));
  // En el panel de trabajo el chat se recoge al usar el resto de la pantalla, para no tapar actividad, menús ni tablas.
  if(dashboard&&isOpen())setOpen(false,false);},true);
 // Capas prioritarias (diálogos, notificaciones, menús): si se abren sobre el chat, este se minimiza y vuelve al cerrarlas.
 const layers='dialog[open],#notify-panel,#account-panel,#assistance-menu';
 let lastBox=null;const blocked=box=>{if(!box?.width)return false;for(const node of document.querySelectorAll(layers)){if(node.hidden||root.contains(node))continue;if(node.matches('dialog[open]'))return true;const other=node.getBoundingClientRect();if(Math.min(other.right,box.right)-Math.max(other.left,box.left)>16&&Math.min(other.bottom,box.bottom)-Math.max(other.top,box.top)>16)return true;}return false;};
 let layerTimer;new MutationObserver(()=>{clearTimeout(layerTimer);layerTimer=setTimeout(()=>{if(isOpen()){const box=panel.getBoundingClientRect();if(blocked(box)){setOpen(false,false);autoHidden=true;lastBox=box;}}},140);}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['hidden','open'],childList:true});
 // «Comenzar conversación»: visible solo mientras no hay mensajes; lleva al campo de escritura.
 {const welcome=list.querySelector('.adi-welcome');if(welcome){const begin=el('button','Comenzar conversación','adi-start');begin.type='button';begin.addEventListener('click',()=>{input.focus();});const voice=el('button',undefined,'adi-start adi-start-voice');voice.type='button';voice.append(svg(micIcon),el('span','Hablar con ADI'));voice.hidden=true;voice.addEventListener('click',()=>startTalk());loadVoiceCfg().then(cfg=>{voice.hidden=!(cfg.continuous&&cfg.premium&&window.MediaRecorder&&navigator.mediaDevices);});welcome.after(begin,voice);}}
 input.addEventListener('input',()=>{grow();typedAt=performance.now();});
 input.addEventListener('keydown',event=>{if(event.key!=='Enter'||event.shiftKey||event.isComposing||event.keyCode===229)return;event.preventDefault();form.requestSubmit();});
 form.addEventListener('submit',event=>{event.preventDefault();send(input.value);});
 quick.addEventListener('click',event=>{const option=event.target.closest('button');if(!option)return;runShortcut(option.dataset.action||'',option.dataset.message,option.dataset.href);});
 // Accesos rápidos y sugerencias: cada uno ejecuta una función real del chat (consulta, reserva, seguimiento o asesor).
 const shortcuts={licencias:['Comprar licencias','licenses'],servicios:['Servicios técnicos','services'],cita:['Agendar cita','booking'],reparacion:['Consultar reparación','order'],asesor:['Hablar con un asesor','human']};
 function runShortcut(action,message,href){if(action==='licenses')send('¿Qué licencias tienen disponibles?');else if(action==='services')send('¿Qué servicios técnicos ofrecen?');else if(action==='booking')bookingCard({});else if(action==='order')orderCheck();else if(action==='human')human.click();else if(href)location.href=href;else if(message)send(message);}
 function paintSuggestions(keys){list.querySelectorAll('.adi-suggest').forEach(node=>node.remove());const valid=keys.filter(key=>shortcuts[key]&&!(key==='asesor'&&(state==='waiting'||state==='advisor')));if(!valid.length)return;
  const row=el('div',undefined,'adi-suggest');row.setAttribute('role','group');row.setAttribute('aria-label','Opciones sugeridas');for(const key of valid){const b=el('button',shortcuts[key][0]);b.type='button';b.addEventListener('click',()=>{row.remove();runShortcut(shortcuts[key][1]);});row.append(b);}place(row);bottom();}
 // Consulta de reparación: conocer el número de orden no basta. El servidor envía un código temporal al correo registrado en la
 // orden y solo con ese código muestra el estado. El reto vive en la memoria de esta página; no se guarda en el navegador.
 let check=null;
 function orderCheck(){
  if(check?.isConnected){check.querySelector('input')?.focus();return;}
  const card=el('div',undefined,'adi-check'),title=el('strong','Consultar reparación'),help=el('p','Escribe el número de orden de tu comprobante. Enviaremos un código de verificación al correo registrado en la orden.'),field=el('input'),go=el('button','Enviar código'),cancel=el('button','Cancelar','adi-check-cancel'),message=el('p',undefined,'adi-check-message'),row=el('div',undefined,'adi-check-actions');
  let token='';card.setAttribute('role','group');card.setAttribute('aria-label','Consultar reparación');field.type='text';field.maxLength=24;field.autocomplete='off';field.spellcheck=false;field.placeholder='PCD-20260101-0001';field.setAttribute('aria-label','Número de orden');go.type=cancel.type='button';message.setAttribute('role','status');row.append(go,cancel);card.append(title,help,field,message,row);
  cancel.addEventListener('click',()=>{card.remove();check=null;input.focus();});
  const run=async()=>{const value=field.value.trim();if(go.disabled)return;if(!value){message.textContent=token?'Escribe el código de 6 dígitos.':'Escribe el número de orden.';field.focus();return;}go.disabled=true;message.textContent=token?'Verificando…':'Enviando el código…';
   try{if(!token){const result=await request('/api/public/adi/order/request',{order:value});token=result.token;help.textContent=result.message;field.value='';field.maxLength=6;field.inputMode='numeric';field.autocomplete='one-time-code';field.placeholder='Código de 6 dígitos';field.setAttribute('aria-label','Código de verificación');go.textContent='Verificar código';message.textContent='';field.focus();}
    else{const order=(await request('/api/public/adi/order/verify',{token,code:value})).order;card.remove();check=null;const bubble=el('p',undefined,'adi-message adi adi-order-result'),body=el('span',undefined,'adi-text');bubble.append(el('span','ADI','adi-author'));
     rich(body,'Orden '+order.code+' · Estado: '+order.status+'.'+(order.device?'\nEquipo: '+order.device+'.':'')+(order.received?'\nIngreso: '+order.received+'.':'')+(order.estimated?'\nEntrega estimada: '+order.estimated+'.':'')+(order.tracking_url?'\nSeguimiento completo: '+order.tracking_url:''));bubble.append(body,el('time',clock(new Date())));place(bubble);bottom();sound('message');if(prefs.voice)speak('Tu orden está en estado '+order.status+'.');input.focus();}}
   catch(error){message.textContent=error.message;sound('error');field.select();}finally{go.disabled=false;}};
  go.addEventListener('click',run);field.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();run();}});
  check=card;quick.hidden=true;place(card);bottom();field.focus();}
 // Reserva desde el chat: el cliente elige servicio, fecha y una hora realmente libre, escribe sus datos, revisa el resumen y acepta
 // las condiciones él mismo; la cita se guarda con la reserva pública de siempre (validaciones, cupos, hora límite, duplicados y correo).
 // ADI solo abre este formulario: nunca crea ni confirma una cita, y el código aparece únicamente cuando el sistema la guardó.
 let booking=null,bookingOptions=null;
 async function bookingCard(prefill){
  if(booking?.isConnected){booking.scrollIntoView({block:'nearest'});booking.querySelector('select,input')?.focus();return;}
  const card=el('div',undefined,'adi-check adi-booking'),title=el('strong','Reservar una cita'),stepText=el('small','','adi-booking-step'),body=el('div',undefined,'adi-booking-body'),message=el('p',undefined,'adi-check-message'),row=el('div',undefined,'adi-check-actions');
  card.setAttribute('role','group');card.setAttribute('aria-label','Reservar una cita');message.setAttribute('role','status');const head=el('div',undefined,'adi-booking-head');head.append(title,stepText);card.append(head,body,message,row);booking=card;quick.hidden=true;place(card);bottom();
  body.append(el('p','Cargando servicios y horarios…'));
  try{bookingOptions=bookingOptions||await request('/api/public/appointments/services');}catch(error){body.replaceChildren(el('p',error.message+' Puedes reservar en /citas o pedir un asesor.'));const close=el('button','Cerrar','adi-check-cancel');close.type='button';close.addEventListener('click',()=>{card.remove();booking=null;});row.replaceChildren(close);return;}
  const o=bookingOptions,key=Array.from(crypto.getRandomValues(new Uint8Array(18)),b=>b.toString(16).padStart(2,'0')).join(''),today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Guayaquil'}).format(new Date());
  const field=(label,node,extra)=>{const box=el('label',undefined,'adi-booking-field'+(extra?' '+extra:''));box.append(el('span',label),node);return box;};
  const make=(type,name,attrs={})=>{const node=el('input');node.type=type;node.name=name;Object.assign(node,attrs);return node;},select=(name,options,value='')=>{const node=el('select');node.name=name;for(const[k,v]of options)node.append(new Option(v,k));node.value=value;return node;};
  const service=select('service',[['','Selecciona el servicio'],...o.services.map(item=>[item.code,item.label])],o.services.some(item=>item.code===prefill.service)?prefill.service:''),license=select('license_category',[['','Selecciona el tipo de licencia'],...Object.entries(o.license_categories||{})]);
  const day=make('date','date',{min:today,value:prefill.date&&prefill.date>=today?prefill.date:''}),hour=select('time',[['','Elige servicio y fecha']]),mode=el('p','','adi-booking-mode');hour.disabled=true;
  const name=make('text','name',{autocomplete:'name',maxLength:150}),docType=select('document_type',[['cedula','Cédula'],['ruc','RUC'],['pasaporte','Pasaporte']],'cedula'),ident=make('text','identification',{inputMode:'numeric',maxLength:20,autocomplete:'off'}),phone=make('tel','phone',{autocomplete:'tel',maxLength:20}),mail=make('email','email',{autocomplete:'email',maxLength:254});
  const device=select('device_type',[['','Selecciona el equipo'],...Object.entries(o.device_types||{})]),brand=make('text','brand',{maxLength:100}),reason=el('textarea');reason.name='description';reason.rows=2;reason.maxLength=1000;const notes=make('text','notes',{maxLength:300});
  const privacy=make('checkbox','privacy_consent'),terms=make('checkbox','terms_accept'),comms=make('checkbox','communications_consent'),last4=make('text','id_last4',{inputMode:'numeric',maxLength:4,autocomplete:'off'});
  const consent=(box,text,link)=>{const label=el('label',undefined,'adi-booking-check');const span=el('span');if(link){const a=el('a',link[0]);a.href=link[1];a.target='_blank';a.rel='noopener';span.append(text[0],a,text[1]);}else span.textContent=text;label.append(box,span);return label;};
  const licenseBox=field('Tipo de licencia',license);
  const step1=el('div',undefined,'adi-booking-grid'),step2=el('div',undefined,'adi-booking-grid'),step3=el('div',undefined,'adi-booking-grid');
  step1.append(field('Servicio',service,'wide'),licenseBox,field('Fecha',day),field('Hora disponible',hour),mode);
  step2.append(field('Nombre y apellidos',name,'wide'),field('Identificación',docType),field('Número',ident),field('Teléfono',phone),field('Correo (opcional)',mail),field('Tipo de equipo',device),field('Marca y modelo (opcional)',brand),field('Motivo o problema',reason,'wide'),field('Observaciones (opcional)',notes,'wide'));
  const summary=el('dl',undefined,'adi-booking-summary');step3.append(summary,consent(privacy,['He leído el ',' y autorizo el uso de estos datos para gestionar esta cita.'],['aviso de privacidad','/privacidad']),consent(terms,['Acepto expresamente los ',' vigentes.'],['términos y condiciones del servicio',o.terms?.local_url||'/privacidad']),consent(comms,'Autorizo comunicaciones sobre esta cita por correo o WhatsApp (opcional).'),field('Últimos 4 dígitos de tu identificación',last4));
  if(!o.terms)step3.append(el('p','No hay condiciones vigentes publicadas: la cita no puede confirmarse en línea ahora. Pide un asesor.','adi-booking-warn'));
  const steps=[step1,step2,step3];let at=0;body.replaceChildren(...steps);
  const back=el('button','Atrás','adi-check-cancel'),next=el('button','Continuar'),cancel=el('button','Cancelar','adi-check-cancel');back.type=next.type=cancel.type='button';row.append(cancel,back,next);
  const paintMode=()=>{const isLicense=service.value===o.license_code;licenseBox.hidden=!isLicense;mode.textContent=service.value==='retiro'?'Modalidad: retiro del equipo en el taller.':service.value?'Modalidad: atención presencial en el taller. Si ya eres cliente, te reconocemos por tu identificación.':'';};
  async function loadHours(){const keep=hour.value||prefill.time||'';hour.disabled=true;hour.replaceChildren(new Option(service.value&&day.value?'Consultando horarios…':'Elige servicio y fecha',''));if(!service.value||!day.value)return;
   try{const data=await request('/api/public/appointments/availability?date='+encodeURIComponent(day.value)+'&service='+encodeURIComponent(service.value));hour.replaceChildren(new Option(data.slots.length?'Selecciona la hora':'Sin horas libres ese día',''));for(const slot of data.slots)hour.append(new Option(slot.time,slot.time));hour.disabled=!data.slots.length;if(data.slots.some(slot=>slot.time===keep))hour.value=keep;if(data.holiday)message.textContent='Ese día es '+data.holiday.label+'.';}
   catch(error){hour.replaceChildren(new Option(error.message,''));}}
  service.addEventListener('change',()=>{paintMode();loadHours();});day.addEventListener('change',loadHours);paintMode();loadHours();
  const missing=()=>{const need=at===0?[[service,'el servicio'],...(service.value===o.license_code?[[license,'el tipo de licencia']]:[]),[day,'la fecha'],[hour,'la hora']]:at===1?[[name,'tu nombre y apellidos'],[ident,'tu identificación'],[phone,'tu teléfono'],[device,'el tipo de equipo'],[reason,'el motivo']]:[];
   return need.find(([node])=>!String(node.value||'').trim());};
  function paintStep(){steps.forEach((node,index)=>{node.hidden=index!==at;});stepText.textContent='Paso '+(at+1)+' de 3 · '+['Servicio y horario','Tus datos','Confirmación'][at];back.hidden=at===0;next.textContent=at===2?'Confirmar cita':'Continuar';
   if(at===2){summary.replaceChildren();for(const[label,value]of [['Servicio',service.selectedOptions[0]?.text+(service.value===o.license_code&&license.value?' · '+license.selectedOptions[0].text:'')],['Fecha y hora',day.value.split('-').reverse().join('/')+' a las '+hour.value],['Cliente',name.value.trim()],['Identificación',docType.selectedOptions[0].text+' '+ident.value.trim()],['Contacto',[phone.value.trim(),mail.value.trim()].filter(Boolean).join(' · ')],['Equipo',[device.selectedOptions[0]?.text,brand.value.trim()].filter(Boolean).join(' · ')],['Motivo',reason.value.trim()]]){const r=el('div');r.append(el('dt',label),el('dd',value));summary.append(r);}}
   (steps[at].querySelector('select:not([disabled]),input,textarea'))?.focus();}
  back.addEventListener('click',()=>{at=Math.max(0,at-1);message.textContent='';paintStep();});
  cancel.addEventListener('click',()=>{card.remove();booking=null;note('Reserva cancelada. No se registró ninguna cita.');input.focus();});
  next.addEventListener('click',async()=>{message.textContent='';const lack=missing();if(lack){message.textContent='Falta '+lack[1]+'.';lack[0].focus();return;}
   if(at<2){at++;paintStep();return;}
   if(!privacy.checked||!terms.checked){message.textContent='Para confirmar, acepta el aviso de privacidad y los términos y condiciones.';(privacy.checked?terms:privacy).focus();return;}
   if(!/^\d{4}$/.test(last4.value)){message.textContent='Escribe los últimos 4 dígitos de tu identificación.';last4.focus();return;}
   next.disabled=true;next.textContent='Guardando tu cita…';
   const data={request_key:key,service:service.value,license_category:service.value===o.license_code?license.value:'',date:day.value,time:hour.value,name:name.value.trim(),document_type:docType.value,identification:ident.value.trim(),phone:phone.value.trim(),email:mail.value.trim(),device_type:device.value,brand:brand.value.trim(),description:reason.value.trim(),notes:notes.value.trim(),
    privacy_consent:privacy.checked,terms_accept:terms.checked,communications_consent:comms.checked,terms_id:o.terms?.id||'',id_last4:last4.value};
   try{const result=await request('/api/public/appointments',data);const done=el('div',undefined,'adi-booking-done');done.setAttribute('role','status');
    const when=new Intl.DateTimeFormat('es-EC',{timeZone:'America/Guayaquil',dateStyle:'full',timeStyle:'short'}).format(new Date(result.starts_at));
    done.append(el('strong','Cita registrada · '+result.code),el('span',when),el('span',result.message||''),el('small',result.status==='confirmada'?'Guarda tu código: lo necesitarás para consultar o cambiar la cita.':'El taller confirmará tu solicitud. Guarda tu código.'));
    card.replaceWith(done);booking=null;bottom(true);sound('message');document.dispatchEvent(new CustomEvent('adi:booked',{detail:{code:result.code}}));}
   catch(error){message.textContent=(error.fields&&Object.values(error.fields)[0]||error.message)+' No se registró la cita.';next.disabled=false;next.textContent='Confirmar cita';sound('error');}});
  paintStep();}
 // La consulta queda siempre a mano bajo el chat, también cuando ya hay conversación (no en el panel interno del personal).
 if(!dashboard){const lookup=el('button','Consultar reparación','adi-human adi-order-open');lookup.type='button';lookup.addEventListener('click',()=>{if(!isOpen())setOpen(true,false);orderCheck();});const foot=el('div',undefined,'adi-foot');human.replaceWith(foot);foot.append(human,lookup);}
 human.addEventListener('click',async()=>{if(busy||state==='waiting'||state==='advisor')return;transient='requesting';paint();try{if(!started)await request('/api/public/adi/message',{message:'Hola, necesito hablar con un asesor.'});const result=await request('/api/public/adi/human',{});transient='';await poll();setState(result.state||'waiting');note('Solicitud registrada. Te avisaremos aquí cuando un asesor tome la conversación.');document.dispatchEvent(new CustomEvent('adi:sent'));}catch(error){transient='';paint();note(error.message,'error');sound('error');}});
 // Abierto: consulta frecuente. Minimizado: solo si ya existe conversación, para avisar de respuestas del asesor.
 setInterval(()=>{if(!document.hidden&&isOpen()&&(started||dashboard))poll();},2500);
 setInterval(()=>{if(!document.hidden&&!isOpen()&&started)poll();},12000);
 // Al entrar permanece minimizado, salvo que la persona haya elegido «Abrir el chat al entrar» y exista una conversación.
 const docked=document.body.dataset.page==='login'&&matchMedia('(min-width:1100px) and (min-height:600px)').matches;if(docked){root.classList.add('adi-docked');
  // El panel acoplado copia la posición vertical y el alto de la tarjeta de acceso, para que formen un conjunto.
  const card=document.querySelector('.access-card'),align=()=>{const active=matchMedia('(min-width:1100px) and (min-height:600px)').matches,box=card?.getBoundingClientRect();if(!active||!box?.height){panel.style.top=panel.style.bottom=panel.style.height='';return;}const height=Math.min(Math.max(box.height,500),innerHeight-32);panel.style.top=Math.max(16,Math.min(box.top,innerHeight-height-16))+'px';panel.style.bottom='auto';panel.style.height=height+'px';};align();addEventListener('resize',align);addEventListener('load',align);setTimeout(align,700);setTimeout(align,2500);if(card&&'ResizeObserver' in window)new ResizeObserver(align).observe(card);}
 paint();poll();
})();
