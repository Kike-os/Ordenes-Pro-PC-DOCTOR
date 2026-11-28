'use strict';
const BatteryWidget=(()=>{
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
const BATTERY_STATES={pendiente:'Pendiente de diagnóstico',evaluada:'Evaluada',no_evaluada:'No se pudo evaluar'};
const batteryNumber=new Intl.NumberFormat('es-EC',{maximumFractionDigits:2});
function batteryValue(record){return record.status==='evaluada'?batteryNumber.format(record.percent)+' %':BATTERY_STATES[record.status];}
const batteryConditions=[
 [90,'esmeralda','Excelente'],[80,'verde','Buen estado'],[60,'amarillo','Desgaste moderado'],
 [40,'naranja','Desgaste elevado'],[0,'rojo','Estado crítico'],
];
function batteryBasisPoints(value){
 const match=/^([0-9]{1,3})(?:[.,]([0-9]{1,2}))?$/.exec(value);
 if(!match)return null;
 const points=Number(match[1])*100+Number((match[2]||'').padEnd(2,'0'));
 return points<=10000?points:null;
}
const batteryMotionKey='ordenes-pro:bateria-sin-animaciones';
const batteryWidgetSelector='.equip-battery-widget';
let batteryIconSequence=0,batteryObserver;
const mountedWidgets=new WeakMap();
function setBatteryMotionDisabled(disabled){
 document.documentElement.toggleAttribute('data-battery-motion-disabled',disabled);
}
function initBatteryMotion(){
 if(!batteryIconSequence){
  try{setBatteryMotionDisabled(localStorage.getItem(batteryMotionKey)==='1');}catch{}
  const updateVisibility=()=>document.documentElement.toggleAttribute('data-battery-page-hidden',document.hidden);
  document.addEventListener('visibilitychange',updateVisibility);
  updateVisibility();
  if('IntersectionObserver' in window){
   batteryObserver=new IntersectionObserver(entries=>{
    for(const entry of entries)entry.target.toggleAttribute('data-battery-visible',entry.isIntersecting);
   });
   new MutationObserver(records=>{
    for(const record of records)for(const removed of record.removedNodes){
     if(removed.nodeType!==1||removed.isConnected)continue;
     if(removed.matches(batteryWidgetSelector))batteryObserver.unobserve(removed);
     for(const widget of removed.querySelectorAll(batteryWidgetSelector))batteryObserver.unobserve(widget);
    }
    for(const record of records)for(const added of record.addedNodes){
     if(added.nodeType!==1||!added.isConnected)continue;
     if(added.matches(batteryWidgetSelector))batteryObserver.observe(added);
     for(const widget of added.querySelectorAll(batteryWidgetSelector))batteryObserver.observe(widget);
    }
   }).observe(document.body,{childList:true,subtree:true});
  }
 }
}
function batteryHealthPremium(node,formatOrderDate){
 if(mountedWidgets.has(node))return mountedWidgets.get(node);
 initBatteryMotion();
 node.classList.add('equip-battery-widget');
 // El portal monta el indicador en un nodo que ya está en el documento.
 if(!batteryObserver)node.setAttribute('data-battery-visible','');
 else if(node.isConnected)batteryObserver.observe(node);
 const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
 icon.classList.add('equip-battery-icon');
 icon.setAttribute('viewBox','0 0 600 244');
 icon.setAttribute('aria-hidden','true');icon.setAttribute('focusable','false');
 const finish='battery-finish-'+(++batteryIconSequence);
 const glow=finish+'-glow';
 const geometry=[[43,91],[144,91],[244,91],[345,91],[439,77]];
 const segments=geometry.map(([x,width],i)=>
  '<rect class="equip-battery-slot" x="'+x+'" y="42" width="'+width+'" height="162" rx="13"/>'+
  '<g class="equip-battery-level" style="--battery-segment-start:'+x+'px"><rect x="'+x+'" y="42" width="'+width+'" height="162" rx="13"/>'+
   '<rect x="'+x+'" y="42" width="'+width+'" height="162" rx="13" fill="url(#'+finish+')"/>'+
   '<g clip-path="url(#'+finish+'-clip-'+i+')">'+
   '<rect class="equip-battery-glow" style="--battery-segment:'+i+'" x="'+x+'" y="42" width="'+width+
   '" height="162" fill="url(#'+glow+')"/></g></g>');
 icon.innerHTML='<defs><linearGradient id="'+finish+'" x2="0" y2="1">'+
  '<stop stop-color="white" stop-opacity=".14"/><stop offset=".22" stop-color="white" stop-opacity=".02"/>'+
  '<stop offset="1" stop-color="#001c2a" stop-opacity=".09"/></linearGradient>'+
  '<linearGradient id="'+glow+'" x2="1" y2="0"><stop stop-color="white" stop-opacity="0"/>'+
  '<stop offset=".48" stop-color="white"/><stop offset="1" stop-color="white" stop-opacity="0"/></linearGradient>'+
  geometry.map(([x,width],i)=>'<clipPath id="'+finish+'-clip-'+i+'"><rect x="'+x+'" y="42" width="'+width+
   '" height="162" rx="13"/></clipPath>').join('')+'</defs>'+
  '<rect class="equip-battery-case" x="16" y="16" width="526" height="215" rx="37"/>'+
  '<rect class="equip-battery-rim" x="27" y="27" width="504" height="193" rx="27"/>'+
  '<rect class="equip-battery-terminal" x="555" y="78" width="30" height="91" rx="14"/>'+
  segments.join('')+
  '<rect class="equip-battery-slot-shine" x="451" y="48" width="55" height="27" rx="12"/>';
 const levels=[...icon.querySelectorAll('.equip-battery-level')];
 const visual=el('span',undefined,'equip-battery-visual');
 const condition=el('span',undefined,'equip-battery-condition');
 const copy=el('span',undefined,'equip-battery-copy');
 const title=el('span','SALUD DE BATERÍA','equip-battery-title');
 const status=el('span',undefined,'equip-battery-status');
 const percent=el('strong',undefined,'equip-battery-percent');
 const wear=el('span',undefined,'equip-battery-wear');
 const reviewed=el('time',undefined,'sr-only');
 visual.append(icon,condition);copy.append(title,status,percent,wear,reviewed);node.append(visual,copy);
 let previousPoints,previousStatus,previousDate,previousSafety,previousWear;
 const paint=record=>{
  const points=record.status==='evaluada'?batteryBasisPoints(record.percent):null;
  const measured=points!==null;
  const safety=record.safety===true||!!record.advanced?.hazards?.length;
  const showWear=record.showWear!==false;
  if(points!==previousPoints||record.status!==previousStatus||safety!==previousSafety||showWear!==previousWear){
   const [,tone,label]=measured?batteryConditions.find(([min])=>points>=min*100):
    [0,'pendiente',BATTERY_STATES[record.status==='no_evaluada'?'no_evaluada':'pendiente']];
   node.dataset.tone=tone;
   node.toggleAttribute('data-battery-safety',safety);
   status.hidden=measured;status.textContent=measured?'':label;
   percent.hidden=!measured;percent.textContent=measured?batteryValue({...record,percent:points/100}):'';
   condition.hidden=!measured&&!safety;
   condition.textContent=safety?'Riesgo crítico':measured?label:'';
   wear.hidden=!measured||!showWear;
   wear.textContent=wear.hidden?'':'Desgaste: '+batteryNumber.format((10000-points)/100)+' %';
   if(points!==previousPoints)levels.forEach((level,i)=>{
    const fill=measured?Math.max(0,Math.min(1,(points-i*2000)/2000)):0;
    if(level.style.getPropertyValue('--battery-fill')!==String(fill))level.style.setProperty('--battery-fill',fill);
    level.toggleAttribute('data-battery-filled',fill>0);
   });
   previousPoints=points;previousStatus=record.status;previousSafety=safety;previousWear=showWear;
  }
  const date=record.created_at||'';
  if(date!==previousDate){
   reviewed.hidden=!date;
   reviewed.dateTime=date;
   reviewed.textContent=date?'Última revisión · '+formatOrderDate(date):'';
   node.title=[node.matches('button')?'Abrir diagnóstico de batería':'',reviewed.textContent].filter(Boolean).join(' · ');
   previousDate=date;
  }
 };
 mountedWidgets.set(node,paint);
 return paint;
}
// Al sustituir el contenido circundante, algunos navegadores recrean las
// animaciones CSS aunque se reutilice el mismo SVG. Conserva su fase visual.
function preserveMotion(widgets,replace){
 const frames=[];
 for(const widget of widgets){
  for(const animation of widget.getAnimations({subtree:true})){
   if(animation.animationName&&typeof animation.currentTime==='number'){
    frames.push([animation.effect.target,animation.animationName,animation.currentTime]);
   }
  }
 }
 replace();
 for(const [target,name,time] of frames){
  if(!target.isConnected)continue;
  const animation=target.getAnimations().find(item=>item.animationName===name);
  if(animation&&animation.currentTime<time)animation.currentTime=time;
 }
}
return {preserveMotion,states:BATTERY_STATES,number:batteryNumber,value:batteryValue,basisPoints:batteryBasisPoints,motionKey:batteryMotionKey,setMotionDisabled:setBatteryMotionDisabled,render:batteryHealthPremium,conditions:batteryConditions};
})();
