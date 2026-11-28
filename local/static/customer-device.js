'use strict';
(()=>{
 function paint(root){
  for(const node of root.querySelectorAll('[data-cdi-battery]:not(.equip-battery-widget)')){
   node.replaceChildren();
   const render=BatteryWidget.render(node,()=> '');
   render({status:'evaluada',percent:Number(node.dataset.cdiBattery),created_at:''});
  }
 }
 paint(document);
 const live=document.querySelector('[data-cdi-refresh]');
 if(!live)return;
 const time=document.querySelector('[data-cdi-checked]');
 const printed=document.querySelector('[data-cdi-print]');
 let busy=false,expired=false;
 const deadline=performance.now()+Date.parse(live.dataset.cdiExpiry)-Date.parse(live.dataset.cdiServer);
 function hide(){
  expired=true;live.replaceChildren();printed?.replaceChildren();
  if(time)time.closest('.cdi-checked').hidden=true;
 }
 setTimeout(hide,Math.max(0,deadline-performance.now()));
 addEventListener('beforeprint',()=>{if(performance.now()>=deadline)hide();});
 async function refresh(){
  if(performance.now()>=deadline){hide();return;}
  if(document.hidden||busy||expired)return;
  busy=true;
  try{
   const response=await fetch(live.dataset.cdiRefresh,{cache:'no-store',credentials:'same-origin'});
   if([403,404,503].includes(response.status)){hide();return;}
   if(expired||performance.now()>=deadline)return;
   if(!response.ok)return;
   const data=await response.json();
   if(typeof data.html!=='string'||typeof data.print!=='string')return;
   const candidate=document.createElement('template');
   candidate.innerHTML=data.html; // HTML rendered on the same origin from escaped allowlisted fields.
   if(live.dataset.cdiSnapshot!==data.snapshot){
    const open=[...live.querySelectorAll('details[open] summary')].map(node=>node.textContent);
    live.replaceChildren(candidate.content);
    for(const summary of live.querySelectorAll('details summary'))if(open.includes(summary.textContent))summary.parentNode.open=true;
    live.dataset.cdiSnapshot=data.snapshot;paint(live);
    if(printed){printed.innerHTML=data.print;paint(printed);}
   }
   if(time){time.hidden=false;time.dateTime=data.checked_at;time.textContent=new Date(data.checked_at).toLocaleString('es-EC',{timeZone:'America/Guayaquil'});}
  }catch{}finally{busy=false;}
 }
 setInterval(refresh,45000);
 document.addEventListener('visibilitychange',refresh);
})();
