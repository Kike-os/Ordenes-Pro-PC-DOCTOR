// Reagendamiento por enlace privado: muestra la cita, las fechas y los horarios realmente libres, y confirma en el servidor.
'use strict';
(()=>{
 const token=(location.pathname.split('/')[2]||'').trim(),state=document.getElementById('reschedule-state'),form=document.getElementById('reschedule-form'),renew=document.getElementById('reschedule-renew');
 const days=document.getElementById('reschedule-days'),slots=document.getElementById('reschedule-slots'),facts=document.getElementById('reschedule-facts'),message=document.getElementById('reschedule-message'),submit=document.getElementById('reschedule-submit');
 let chosenDay='',chosenTime='',busy=false;
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const when=value=>new Intl.DateTimeFormat('es-EC',{timeZone:'America/Guayaquil',dateStyle:'full',timeStyle:'short'}).format(new Date(value));
 const dayLabel=value=>new Intl.DateTimeFormat('es-EC',{timeZone:'America/Guayaquil',weekday:'short',day:'numeric',month:'short'}).format(new Date(value+'T12:00:00-05:00'));
 async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});let data={};try{data=await r.json();}catch{}if(!r.ok){const e=new Error(data.error||'No se pudo completar la operación.');e.status=r.status;e.data=data;throw e;}return data;}
 function showRenew(text){state.textContent=text;state.dataset.kind='warn';renew.hidden=false;form.hidden=true;}
 function paintFacts(a){facts.replaceChildren();for(const[label,value]of [['Cita',a.code],['Servicio',a.service],['Equipo',a.device],['Fecha y hora anteriores',when(a.starts_at)],...(a.expires_at?[['Enlace válido hasta',when(a.expires_at)]]:[])]){const row=el('div');row.append(el('dt',label),el('dd',value));facts.append(row);}}
 function pick(group,button){group.querySelectorAll('button').forEach(b=>b.setAttribute('aria-checked',String(b===button)));}
 async function loadSlots(day){chosenDay=day;chosenTime='';submit.disabled=true;slots.replaceChildren(el('p','Consultando horarios…','reschedule-hint'));
  try{const data=await api('/api/public/reschedule/'+encodeURIComponent(token)+'?date='+day);slots.replaceChildren();if(data.holiday)slots.append(el('p','Feriado: '+data.holiday.label+(data.holiday.mode==='especial'?' (horario especial)':''),'reschedule-hint'));
   if(!data.slots.length){slots.append(el('p','No quedan horarios libres ese día. Elige otra fecha.','reschedule-hint'));return;}
   for(const time of data.slots){const b=el('button',time,'reschedule-slot');b.type='button';b.setAttribute('role','radio');b.setAttribute('aria-checked','false');b.onclick=()=>{chosenTime=time;pick(slots,b);submit.disabled=false;message.textContent='';};slots.append(b);}}
  catch(error){slots.replaceChildren(el('p',error.message,'reschedule-hint'));}}
 async function load(){if(!token){showRenew('Este enlace no es válido. Si necesitas reagendar, solicita un enlace nuevo.');return;}
  try{const data=await api('/api/public/reschedule/'+encodeURIComponent(token));state.textContent='Hola '+data.appointment.name+'. Elige una nueva fecha y hora.';state.dataset.kind='ok';paintFacts(data.appointment);form.hidden=false;days.replaceChildren();
   const open=data.days.filter(d=>d.slots>0);if(!open.length){days.append(el('p','No hay fechas libres en los próximos 30 días. Contáctanos por WhatsApp.','reschedule-hint'));return;}
   for(const d of data.days){const b=el('button',undefined,'reschedule-day');b.type='button';b.setAttribute('role','radio');b.setAttribute('aria-checked','false');b.disabled=!d.slots;b.append(el('strong',dayLabel(d.date)),el('small',d.slots?d.slots+' horario'+(d.slots===1?'':'s'):'Sin horarios'));b.onclick=()=>{pick(days,b);loadSlots(d.date);};days.append(b);}}
  catch(error){if(error.data?.state==='expired'){showRenew(error.message);return;}state.textContent=error.message;state.dataset.kind='warn';if(error.data?.appointment)paintFacts(error.data.appointment),form.hidden=true;if(['invalid'].includes(error.data?.state))renew.hidden=false;}}
 form.addEventListener('submit',async event=>{event.preventDefault();if(busy||!chosenDay||!chosenTime)return;busy=true;submit.disabled=true;submit.textContent='Confirmando…';message.textContent='';
  try{const data=await api('/api/public/reschedule',{token,date:chosenDay,time:chosenTime});form.hidden=true;state.dataset.kind='ok';state.replaceChildren(el('strong',data.message),el('span','Nueva fecha: '+when(data.starts_at)+'. Cita '+data.code+'.'));}
  catch(error){message.textContent=error.message;if(error.status===409&&error.data?.conflict){loadSlots(chosenDay);if(error.data.alternatives?.length)message.textContent+=' Opciones cercanas: '+error.data.alternatives.map(a=>a.label).join(', ')+'.';}if(error.data?.state==='expired')showRenew(error.message);}
  finally{busy=false;submit.textContent='Confirmar nueva cita';submit.disabled=!chosenTime;}});
 renew.addEventListener('submit',async event=>{event.preventDefault();const out=document.getElementById('renew-message');const data=Object.fromEntries(new FormData(renew));if(!data.code.trim()||!data.identification.trim()){out.textContent='Completa los dos datos.';return;}
  try{const result=await api('/api/public/reschedule/renew',{code:data.code.trim(),identification:data.identification.trim()});out.textContent=result.message;renew.querySelector('button').disabled=true;}catch(error){out.textContent=error.message;}});
 load();
})();
