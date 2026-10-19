// Selector de servicios de la Agenda (reserva pública y agenda del personal): servicios agrupados por categoría, buscador,
// varios servicios por cita (hasta 5, sin repetir) con su duración total, y tipo de licencia cuando se elige «Compra de licencia».
// El valor se guarda en un campo oculto «service» como lista separada por comas; el servidor vuelve a validar todo.
(function(){
 'use strict';
 const LICENSE='licencia',PICKUP='retiro',MAX=5;
 const LICENSE_OPTIONS=[['windows','Windows 10 y Windows 11'],['office','Microsoft Office'],['m365','Microsoft 365'],['antivirus','Antivirus Kaspersky, ESET NOD32, McAfee, Norton y otros'],['otras','Otras licencias de software']];
 const plain=text=>String(text||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
 const minutes=total=>{const h=Math.floor(total/60),m=total%60;return h?(h+' h'+(m?' '+m+' min':'')):m+' min';};
 const make=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
 let counter=0;
 window.ServicePicker=function(host,services,options={}){
  const id='service-picker-'+(++counter),hidden=options.input||make('input');hidden.type='hidden';hidden.name=hidden.name||'service';if(!hidden.isConnected)host.append(hidden);
  host.classList.add('service-picker');
  const search=make('input');search.type='search';search.placeholder='Buscar servicio';search.autocomplete='off';search.setAttribute('aria-label','Buscar servicio');search.setAttribute('aria-controls',id+'-list');
  const list=make('div',undefined,'service-picker-list');list.id=id+'-list';list.setAttribute('role','group');list.setAttribute('aria-label','Servicios disponibles');
  const empty=make('p','No hay servicios que coincidan con la búsqueda.','service-picker-empty');empty.hidden=true;
  const summary=make('p','','service-picker-summary');summary.setAttribute('aria-live','polite');
  const license=make('div',undefined,'service-picker-license');license.hidden=true;
  const kindLabel=make('label','Tipo de licencia *'),kind=make('select');kind.name='license_category';kind.append(new Option('Selecciona el tipo de licencia',''));for(const[value,text]of LICENSE_OPTIONS)kind.append(new Option(text,value));kindLabel.append(kind);
  const notesLabel=make('label','Observaciones de la licencia (opcional)'),notes=make('textarea');notes.name='license_notes';notes.maxLength=500;notes.rows=2;notes.placeholder='Por ejemplo, número de equipos o versión que necesitas';notesLabel.append(notes);
  license.append(kindLabel,notesLabel);
  const order=[],boxes=new Map(),groups=[];
  const byCategory=new Map();for(const item of services){const key=item.category||'Otros servicios';if(!byCategory.has(key))byCategory.set(key,[]);byCategory.get(key).push(item);}
  for(const[category,items]of byCategory){const group=make('fieldset',undefined,'service-picker-group');group.append(make('legend',category));
   for(const item of items){const row=make('label',undefined,'service-option'),box=make('input');box.type='checkbox';box.value=item.code;const name=make('span',item.label,'service-option-name'),time=make('small',minutes(item.duration_minutes),'service-option-time');row.append(box,name,time);row.dataset.search=plain(item.label+' '+(item.keywords||'')+' '+category);group.append(row);boxes.set(item.code,{box,item,row});box.addEventListener('change',()=>toggle(item.code,box.checked));}
   groups.push(group);list.append(group);}
  host.append(search,list,empty,summary,license);
  function toggle(code,on){const at=order.indexOf(code);if(on&&at<0){
    // El retiro de equipos se agenda solo; elegir otro servicio lo quita, y elegir el retiro quita los demás.
    if(code===PICKUP)order.splice(0).forEach(other=>{boxes.get(other).box.checked=false;});else if(order.includes(PICKUP)){order.splice(order.indexOf(PICKUP),1);boxes.get(PICKUP).box.checked=false;}
    order.push(code);}else if(!on&&at>=0)order.splice(at,1);paint(true);}
  function total(){return order.reduce((sum,code)=>sum+boxes.get(code).item.duration_minutes,0);}
  function paint(changed){hidden.value=order.join(',');const full=order.length>=MAX;
   for(const{box,row}of boxes.values()){box.disabled=full&&!box.checked;row.classList.toggle('is-selected',box.checked);row.classList.toggle('is-disabled',box.disabled);}
   summary.textContent=order.length?(order.length===1?'1 servicio':order.length+' servicios')+' · duración estimada '+minutes(total())+(full?' · máximo '+MAX+' servicios por cita':''):'Puedes elegir uno o varios servicios (hasta '+MAX+').';
   license.hidden=!order.includes(LICENSE);if(license.hidden){kind.value='';notes.value='';}
   if(changed){hidden.dispatchEvent(new Event('change',{bubbles:true}));options.onChange&&options.onChange(api);}}
  search.addEventListener('input',()=>{const words=plain(search.value).split(/\s+/).filter(Boolean);let shown=0;for(const{row}of boxes.values()){const match=words.every(word=>row.dataset.search.includes(word));row.hidden=!match;if(match)shown++;}for(const group of groups)group.hidden=![...group.querySelectorAll('.service-option')].some(row=>!row.hidden);empty.hidden=shown>0;});
  search.addEventListener('keydown',event=>{if(event.key==='Escape'&&search.value){event.preventDefault();event.stopPropagation();search.value='';search.dispatchEvent(new Event('input'));}else if(event.key==='Enter')event.preventDefault();});
  const api={input:hidden,search,license:kind,notes,
   value:()=>order.slice(),total,
   labels:()=>order.map(code=>boxes.get(code).item.label+(code===LICENSE&&kind.value?' ('+kind.selectedOptions[0].textContent+')':'')),
   has:code=>order.includes(code),
   // Elige exactamente estos servicios (los que no existan se ignoran). Devuelve si quedó al menos uno.
   set(codes){for(const{box}of boxes.values())box.checked=false;order.splice(0);for(const code of codes||[])if(boxes.has(code)&&!order.includes(code)&&order.length<MAX){if(code===PICKUP&&order.length)continue;if(order.includes(PICKUP))break;boxes.get(code).box.checked=true;order.push(code);}paint(true);return order.length>0;},
   focus(){(order.length?boxes.get(order[0]).box:search).focus();}};
  paint(false);return api;};
})();
