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
 initBatteryMotion();
 node.classList.add('equip-battery-widget');
 const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
 icon.classList.add('equip-battery-icon');
 icon.setAttribute('viewBox','0 0 600 244');
 icon.setAttribute('aria-hidden','true');icon.setAttribute('focusable','false');
 const finish='battery-finish-'+(++batteryIconSequence);
 const glow=finish+'-glow',mask=finish+'-mask';
 const geometry=[[43,91],[144,91],[244,91],[345,91],[439,77]];
 const segments=geometry.map(([x,width],i)=>
  '<rect class="equip-battery-slot" x="'+x+'" y="42" width="'+width+'" height="162" rx="13"/>'+
  '<g class="equip-battery-level"><rect x="'+x+'" y="42" width="'+width+'" height="162" rx="13"/>'+
   '<rect x="'+x+'" y="42" width="'+width+'" height="162" rx="13" fill="url(#'+finish+')"/>'+
   '<g clip-path="url(#'+finish+'-clip-'+i+')">'+
   '<rect class="equip-battery-glow" style="--battery-segment:'+i+'" x="'+x+'" y="42" width="'+width+
   '" height="162" fill="white" mask="url(#'+mask+')"/></g></g>');
 icon.innerHTML='<defs><linearGradient id="'+finish+'" x2="0" y2="1">'+
  '<stop stop-color="white" stop-opacity=".14"/><stop offset=".22" stop-color="white" stop-opacity=".02"/>'+
  '<stop offset="1" stop-color="#001c2a" stop-opacity=".09"/></linearGradient>'+
  '<linearGradient id="'+glow+'" x2="1" y2="0"><stop stop-color="white" stop-opacity="0"/>'+
  '<stop offset=".48" stop-color="white"/><stop offset="1" stop-color="white" stop-opacity="0"/></linearGradient>'+
  '<mask id="'+mask+'" maskContentUnits="objectBoundingBox" mask-type="alpha">'+
  '<rect width="1" height="1" fill="url(#'+glow+')"/></mask>'+
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
 return record=>{
  const value=record.percent;
  const measured=record.status==='evaluada'&&Number.isFinite(value)&&value>=0&&value<=100;
  const [,tone,label]=measured?batteryConditions.find(([min])=>value>=min):[0,'pendiente',BATTERY_STATES[record.status==='no_evaluada'?'no_evaluada':'pendiente']];
  node.dataset.tone=tone;
  status.hidden=measured;status.textContent=measured?'':label;
  percent.hidden=!measured;percent.textContent=measured?batteryValue(record):'';
  condition.hidden=!measured;condition.textContent=measured?label:'';
  wear.hidden=!measured;
  wear.textContent=measured?'Desgaste: '+batteryNumber.format((10000-Math.round(value*100))/100)+' %':'';
  reviewed.hidden=!record.created_at;
  reviewed.dateTime=record.created_at||'';
  reviewed.textContent=record.created_at?'Última revisión · '+formatOrderDate(record.created_at):'';
  node.title=[node.matches('button')?'Abrir diagnóstico de batería':'',reviewed.textContent].filter(Boolean).join(' · ');
  levels.forEach((level,i)=>{
   const fill=measured?Math.max(0,Math.min(1,(Math.round(value*100)-i*2000)/2000)):0;
   level.style.setProperty('--battery-fill',fill);
   level.toggleAttribute('data-battery-filled',fill>0);
  });
 };
}
return {states:BATTERY_STATES,number:batteryNumber,value:batteryValue,basisPoints:batteryBasisPoints,motionKey:batteryMotionKey,setMotionDisabled:setBatteryMotionDisabled,render:batteryHealthPremium,conditions:batteryConditions};
})();
