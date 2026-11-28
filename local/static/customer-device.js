'use strict';
(()=>{
 const batterySelector='[data-cdi-battery]';
 function paint(node){
  if(!node.classList.contains('equip-battery-widget'))node.replaceChildren();
  BatteryWidget.render(node,()=> '')({
   status:'evaluada',percent:node.dataset.cdiBattery,
   showWear:node.dataset.cdiWear==='1',safety:node.dataset.cdiBatterySafety==='1'
  });
 }
 const live=document.querySelector('[data-cdi-refresh]');
 if(!live){document.querySelectorAll(batterySelector).forEach(paint);return;}
 const printed=document.querySelector('[data-cdi-print]');
 const markup=new WeakMap();
 function remember(root){
  for(const section of root.children)markup.set(section,section.outerHTML);
 }
 remember(live);
 if(printed)remember(printed);
 document.querySelectorAll(batterySelector).forEach(paint);
 function replaceContent(root,fragment){
  const sections=[...root.children];
  const unchanged=new Map(sections.map(section=>[markup.get(section),section]));
  const next=[...fragment.children].map(section=>{
   const html=section.outerHTML;
   const existing=unchanged.get(html);
   if(existing){unchanged.delete(html);return existing;}
   markup.set(section,html);
   return section;
  });
  const keep=new Set(next);
  const retired=sections.filter(section=>!keep.has(section));
  const widgets=new Map(retired.flatMap(section=>[...section.querySelectorAll(batterySelector)]
   .map(node=>[node.dataset.cdiBatteryKey,node])));
  BatteryWidget.preserveMotion(widgets.values(),()=>{
   for(const section of next){
    if(section.parentNode===root)continue;
    for(const incoming of section.querySelectorAll(batterySelector)){
     const previous=widgets.get(incoming.dataset.cdiBatteryKey);
     if(!previous)continue;
     for(const key of ['cdiBattery','cdiWear','cdiBatterySafety']){
      if(previous.dataset[key]!==incoming.dataset[key])previous.dataset[key]=incoming.dataset[key];
     }
     incoming.replaceWith(previous);
    }
   }
   retired.forEach(section=>section.remove());
   let cursor=root.firstElementChild;
   for(const section of next){
    if(section!==cursor)root.insertBefore(section,cursor);
    else cursor=cursor.nextElementSibling;
   }
   root.querySelectorAll(batterySelector).forEach(paint);
  });
 }
 const time=document.querySelector('[data-cdi-checked]');
 const status=document.querySelector('[data-cdi-sync]');
 const pendingQuote=document.querySelector('[data-cdi-quote-pending]');
 const summaryFacts=document.querySelectorAll('[data-cdi-public-fact]');
 function syncSummary(){
  for(const fact of summaryFacts)fact.hidden=!!live.querySelector('[data-cdi-'+fact.dataset.cdiPublicFact+']');
 }
 function message(text){
  if(status){status.textContent=text;status.hidden=!text;}
 }
 live.addEventListener('click',event=>{
  const link=event.target.closest('a[href="#cdi-report"]');
  if(link){const report=live.querySelector('details#cdi-report');if(report)report.open=true;}
 });
 let busy=false,expired=false;
 const deadline=performance.now()+Date.parse(live.dataset.cdiExpiry)-Date.parse(live.dataset.cdiServer);
 function hide(){
  if(expired)return;
  expired=true;
  clearTimeout(expiryTimer);
  clearInterval(refreshTimer);
  document.removeEventListener('visibilitychange',refresh);
  removeEventListener('online',refresh);
  removeEventListener('offline',refresh);
  removeEventListener('beforeprint',checkPrintExpiry);
  live.replaceChildren();printed?.replaceChildren();syncSummary();
  if(pendingQuote)pendingQuote.hidden=true;
  if(time)time.closest('.cdi-checked').hidden=true;
  message('Vuelve a verificar tu identidad para consultar la ficha.');
 }
 const expiryTimer=setTimeout(hide,Math.max(0,deadline-performance.now()));
 function checkPrintExpiry(){if(performance.now()>=deadline)hide();}
 addEventListener('beforeprint',checkPrintExpiry);
 async function refresh(){
  if(performance.now()>=deadline){hide();return;}
  if(document.hidden||busy||expired)return;
  const stale=()=>message('No se pudo actualizar. Se muestra la última información disponible.');
  if(navigator.onLine===false){
   message('Conexión interrumpida. Se muestra la última información disponible.');
   return;
  }
  busy=true;
  if(status?.hidden)message('Sincronizando ficha técnica…');
  try{
   const response=await fetch(live.dataset.cdiRefresh,{cache:'no-store',credentials:'same-origin'});
   if([401,403,404].includes(response.status)){hide();return;}
   if(expired||performance.now()>=deadline){hide();return;}
   if(!response.ok){stale();return;}
   const data=await response.json();
   if(expired||performance.now()>=deadline){hide();return;}
   if(typeof data.html!=='string'||typeof data.print!=='string'||typeof data.snapshot!=='string'||
      !Number.isFinite(Date.parse(data.checked_at))){stale();return;}
   const candidate=document.createElement('template');
   candidate.innerHTML=data.html; // HTML rendered on the same origin from escaped allowlisted fields.
   if(live.dataset.cdiSnapshot!==data.snapshot){
    const open=[...live.querySelectorAll('details[open] summary')].map(node=>node.textContent);
    replaceContent(live,candidate.content);
    for(const summary of live.querySelectorAll('details summary'))if(open.includes(summary.textContent))summary.parentNode.open=true;
    live.dataset.cdiSnapshot=data.snapshot;syncSummary();
    if(printed){
     const printCandidate=document.createElement('template');
     printCandidate.innerHTML=data.print;
     replaceContent(printed,printCandidate.content);
    }
   }
   if(pendingQuote)pendingQuote.hidden=data.quote_pending!==true;
   message('');
   if(time){time.hidden=false;time.dateTime=data.checked_at;time.textContent=new Date(data.checked_at).toLocaleString('es-EC',{timeZone:'America/Guayaquil'});}
  }catch{if(!expired)stale();}finally{busy=false;}
 }
 const refreshTimer=setInterval(refresh,45000);
 document.addEventListener('visibilitychange',refresh);
 addEventListener('online',refresh);
 addEventListener('offline',refresh);
})();
