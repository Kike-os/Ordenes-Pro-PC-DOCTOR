'use strict';
// Premium Smart Dropdown 2.0 (componente central de listas desplegables de Órdenes Pro).
// 1) <select>: el control cerrado sigue siendo el <select> nativo (mismo tamaño, foco, formularios y lectores de pantalla); solo se sustituye
//    la lista que abre el navegador —que no admite estilos— por una lista con el tema del sistema. Con más de 10 opciones lleva buscador.
//    En pantallas táctiles se conserva el selector del sistema operativo, que allí es más cómodo y accesible.
// 2) <input list="…"> (sugerencias de un <datalist>, p. ej. la Marca de Nueva orden): el navegador dibuja esa lista fuera del control de la
//    página (ocupa toda la altura, colores propios). Se quita el atributo «list» y se muestra la misma lista con el tema del sistema, filtrada
//    sin distinguir mayúsculas ni acentos. El campo sigue aceptando texto libre como antes (no cambia ningún valor guardado).
// Posición: alineada al campo y con su ancho, debajo si cabe y arriba si no, altura máxima 320 px (menos si no hay espacio), 12 px de margen
// con los bordes; se recoloca al desplazar y se cierra si el campo sale de la vista. Dentro de un <dialog> se muestra en el propio diálogo.
(()=>{
 const touch=matchMedia('(pointer:coarse)'),MARGIN=12,GAP=5,MAX=320,SEARCH_FROM=11,SHOW_MAX=200;
 let open=null,typed='',typedAt=0,seq=0;
 const usable=select=>select instanceof HTMLSelectElement&&!select.multiple&&select.size<2&&!select.disabled&&select.dataset.native!=='true'&&(!touch.matches||select.dataset.corporate==='true');
 const fold=text=>String(text||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLocaleLowerCase('es').trim();
 // Nombre accesible del campo: aria-label o el texto de su etiqueta SIN las opciones (el <select> suele estar dentro de la <label>).
 const labelOf=field=>{const own=field.getAttribute('aria-label');if(own)return own;const label=field.labels?.[0];if(!label)return '';const copy=label.cloneNode(true);copy.querySelectorAll('select,input,textarea,datalist,.field-error,small').forEach(n=>n.remove());return copy.textContent.replace(/\s+/g,' ').replace(/\*/g,'').trim();};
 const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 const check=()=>{const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.setAttribute('class','ui-select-check');const p=document.createElementNS(ns,'path');p.setAttribute('d','M20 6 9 17l-5-5');svg.append(p);return svg;};
 function close(restore){if(!open)return;const{list,anchor,off}=open;open=null;list.remove();anchor.removeAttribute('data-ui-open');anchor.setAttribute('aria-expanded','false');anchor.removeAttribute('aria-activedescendant');off();if(restore)anchor.focus({preventScroll:true});}
 // Posición flotante: se mide el desplazamiento real del contenedor (un diálogo con transformación cambia la referencia de position:fixed).
 function place(list,anchor){const box=anchor.getBoundingClientRect();if(box.bottom<0||box.top>innerHeight||box.width===0){close();return;}
  const vw=document.documentElement.clientWidth,below=innerHeight-box.bottom-MARGIN-GAP,above=box.top-MARGIN-GAP,natural=Math.min(MAX,list.scrollHeight+2),up=below<Math.min(natural,180)&&above>below;
  const room=Math.max(96,Math.min(MAX,up?above:below)),width=Math.min(Math.max(box.width,200),Math.max(200,vw-2*MARGIN),Math.max(box.width,480));
  // Referencia real de position:fixed en el contenedor (un diálogo con transformación la cambia): sonda invisible, sin animación.
  const probe=document.createElement('i');probe.style.cssText='position:fixed;left:0;top:0;width:0;height:0;visibility:hidden';list.parentNode.append(probe);const origin=probe.getBoundingClientRect();probe.remove();
  list.style.maxHeight=room+'px';list.style.width=width+'px';const height=Math.min(list.scrollHeight+2,room);
  const left=Math.max(MARGIN,Math.min(box.left,vw-width-MARGIN)),top=up?Math.max(MARGIN,box.top-GAP-height):box.bottom+GAP;
  list.style.left=(left-origin.left)+'px';list.style.top=(top-origin.top)+'px';list.dataset.side=up?'top':'bottom';}
 function frame(anchor,label){const list=node('div','ui-select-list');list.id='ui-select-'+(++seq);if(anchor.dataset.corporate==='true')list.classList.add('corporate-smart-options');list.setAttribute('role','listbox');list.tabIndex=-1;if(label)list.setAttribute('aria-label',label);
  (anchor.closest('dialog[open]')||document.body).append(list);anchor.setAttribute('aria-controls',list.id);anchor.setAttribute('aria-expanded','true');anchor.dataset.uiOpen='true';
  list.addEventListener('mousedown',event=>{if(!event.target.closest('.ui-select-search'))event.preventDefault();});return list;}
 function watch(list,anchor,onBlur){let raf=0;const reposition=()=>{cancelAnimationFrame(raf);raf=requestAnimationFrame(()=>{if(open&&open.list===list)place(list,anchor);});};
  const outside=event=>{if(event.target!==anchor&&!list.contains(event.target))close();},scrolled=event=>{if(!list.contains(event.target))reposition();},blur=()=>setTimeout(()=>{if(open&&open.list===list&&document.activeElement!==anchor&&!list.contains(document.activeElement))(onBlur||close)();},0);
  document.addEventListener('mousedown',outside,true);addEventListener('scroll',scrolled,true);addEventListener('resize',reposition);anchor.addEventListener('blur',blur);list.addEventListener('focusout',blur);
  return()=>{cancelAnimationFrame(raf);document.removeEventListener('mousedown',outside,true);removeEventListener('scroll',scrolled,true);removeEventListener('resize',reposition);anchor.removeEventListener('blur',blur);};}
 function itemNode(text,selected,disabled){const item=node('div','ui-select-option');item.id='ui-opt-'+(++seq);item.setAttribute('role','option');item.append(node('span','ui-select-text',text||' '));if(selected)item.append(check());item.setAttribute('aria-selected',String(!!selected));if(disabled)item.setAttribute('aria-disabled','true');return item;}
 // ───────────────────────────────────────────── <select>
 function choose(select,option){if(option.disabled||option.closest('optgroup')?.disabled)return;if(select.value!==option.value||select.selectedOptions[0]!==option){option.selected=true;select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}));}}
 function show(select){
  close();const label=labelOf(select),list=frame(select,label),items=[];
  const count=select.options.length,searchable=count>=SEARCH_FROM;let search=null,empty=null;
  if(searchable){const wrap=node('div','ui-select-search');search=node('input');search.type='search';search.placeholder='Buscar…';search.setAttribute('aria-label','Buscar en '+(label||'la lista'));search.autocomplete='off';search.setAttribute('aria-controls',list.id);wrap.append(search);list.append(wrap);empty=node('div','ui-select-empty','Sin resultados');empty.hidden=true;}
  const add=(option,parent)=>{const off=option.disabled||!!parent?.disabled,item=itemNode(option.label||option.textContent,option.selected,off);if(option.hidden)item.hidden=true;
   const entry={item,option,off:off||option.hidden,key:fold(option.label||option.textContent),group:parent};items.push(entry);
   if(!off)item.addEventListener('click',()=>{choose(select,option);close(true);});item.addEventListener('mousemove',()=>{if(!entry.off&&!item.hidden)mark(items.indexOf(entry),false);});(parent?parent.box:list).append(item);};
  for(const child of select.children){if(child.tagName==='OPTGROUP'){const box=node('div','ui-select-group');box.setAttribute('role','group');box.setAttribute('aria-label',child.label);box.append(node('div','ui-select-group-label',child.label));list.append(box);for(const option of child.children)add(option,{box,disabled:child.disabled});}else if(child.tagName==='OPTION')add(child);}
  if(empty)list.append(empty);
  let active=items.findIndex(entry=>entry.option.selected);
  const visible=index=>index>=0&&index<items.length&&!items[index].off&&!items[index].item.hidden;
  function mark(index,scroll=true){if(!visible(index))return;items[active]?.item.removeAttribute('data-active');active=index;items[index].item.dataset.active='true';(search||select).setAttribute('aria-activedescendant',items[index].item.id);if(scroll)items[index].item.scrollIntoView({block:'nearest'});}
  const step=(from,delta)=>{for(let index=from+delta;index>=0&&index<items.length;index+=delta)if(visible(index))return index;return from;};
  const filter=()=>{const needle=fold(search.value);let shown=0;for(const entry of items){const hit=!needle||entry.key.includes(needle);entry.item.hidden=entry.option.hidden||!hit;if(!entry.item.hidden)shown++;}
   list.querySelectorAll('.ui-select-group').forEach(g=>{g.hidden=![...g.querySelectorAll('.ui-select-option')].some(o=>!o.hidden);});empty.hidden=shown>0;if(!visible(active))mark(step(-1,1));place(list,select);};
  const key=event=>{const k=event.key;
   if(k==='Escape'){event.preventDefault();event.stopPropagation();close(true);return true;}
   if(k==='Enter'||(k===' '&&event.target!==search)){event.preventDefault();if(k===' '&&typed&&Date.now()-typedAt<700)return true;if(visible(active))choose(select,items[active].option);close(true);return true;}
   if(k==='Tab'){if(visible(active)&&event.target!==search)choose(select,items[active].option);close();return true;}
   if(k==='ArrowDown'||k==='ArrowUp'){event.preventDefault();mark(active<0||!visible(active)?step(-1,1):step(active,k==='ArrowDown'?1:-1));return true;}
   if((k==='Home'||k==='PageUp')&&event.target!==search){event.preventDefault();mark(step(-1,1));return true;}
   if((k==='End'||k==='PageDown')&&event.target!==search){event.preventDefault();mark(step(items.length,-1));return true;}
   if(search&&event.target!==search&&k.length===1&&!event.ctrlKey&&!event.metaKey&&!event.altKey){event.preventDefault();search.focus();search.value+=k;filter();return true;}
   if(!search&&k.length===1&&!event.ctrlKey&&!event.metaKey&&!event.altKey){event.preventDefault();const now=Date.now();typed=now-typedAt>700?k:typed+k;typedAt=now;const needle=fold(typed),start=typed.length===1?active+1:Math.max(active,0);
    for(let n=0;n<items.length;n++){const index=(start+n)%items.length;if(visible(index)&&items[index].key.startsWith(needle)){mark(index);break;}}return true;}
   return false;};
  place(list,select);if(active>=0&&visible(active))mark(active);
  if(search){search.addEventListener('input',filter);search.addEventListener('keydown',event=>{event.stopPropagation();key(event);});setTimeout(()=>search.focus({preventScroll:true}),0);}
  const off=watch(list,select);open={list,anchor:select,off,key};
 }
 document.addEventListener('mousedown',event=>{if(event.button!==0)return;const select=event.target instanceof Element?event.target.closest('select'):null;if(!select||!usable(select))return;event.preventDefault();select.focus();if(open&&open.anchor===select)close();else show(select);},true);
 document.addEventListener('keydown',event=>{const target=event.target;
  if(target instanceof HTMLSelectElement){if(open&&open.anchor===target){open.key(event);return;}
   if(!usable(target))return;if(event.key===' '||event.key==='Enter'||event.key==='F4'||((event.altKey||target.dataset.corporate==='true')&&(event.key==='ArrowDown'||event.key==='ArrowUp'))){if(event.key==='Enter'&&target.form&&!target.dataset.uiEnter)return;event.preventDefault();show(target);}return;}
  if(target instanceof HTMLInputElement&&target.dataset.uiList&&open&&open.anchor===target)open.key(event);},true);
 // ───────────────────────────────────────────── <input list> (combobox con sugerencias)
 function suggest(input){
  const source=document.getElementById(input.dataset.uiList);if(!source)return;
  const label=labelOf(input);const all=[...source.querySelectorAll('option')].map(o=>({value:o.value,label:o.label&&o.label!==o.value?o.label:'',key:fold(o.value+' '+(o.label||''))})).filter(o=>o.value);
  const needle=fold(input.value),exact=all.some(o=>fold(o.value)===needle),matches=(needle&&!exact?all.filter(o=>o.key.includes(needle)):all);
  // Primero lo que empieza por lo escrito, luego lo que lo contiene; el orden de la lista original se conserva dentro de cada grupo.
  matches.sort((a,b)=>(needle&&!exact?(fold(a.value).startsWith(needle)?0:1)-(fold(b.value).startsWith(needle)?0:1):0));
  if(open&&open.anchor===input){open.repaint(matches,needle,exact);return;}
  close();const list=frame(input,label);list.classList.add('ui-select-suggest');let items=[],active=-1;
  const pick=value=>{if(input.value!==value){input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));}close(true);};
  function mark(index,scroll=true){if(index<0||index>=items.length)return;items[active]?.item.removeAttribute('data-active');active=index;items[index].item.dataset.active='true';input.setAttribute('aria-activedescendant',items[index].item.id);if(scroll)items[index].item.scrollIntoView({block:'nearest'});}
  function repaint(rows,query,isExact){list.replaceChildren();items=[];active=-1;
   const typedValue=input.value.trim();
   if(typedValue&&!isExact&&input.dataset.uiCreate!=='false'){const item=itemNode('Usar «'+typedValue+'»',false,false);item.classList.add('ui-select-create');items.push({item,value:typedValue});list.append(item);}
   if(input.value&&isExact){const item=itemNode('Limpiar selección',false,false);item.classList.add('ui-select-clear');items.push({item,value:''});list.append(item);}
   for(const row of rows.slice(0,SHOW_MAX)){const item=itemNode(row.value,fold(row.value)===fold(input.value),false);if(row.label)item.append(node('small','ui-select-note',row.label));items.push({item,value:row.value});list.append(item);}
   if(rows.length>SHOW_MAX)list.append(node('div','ui-select-empty','Se muestran '+SHOW_MAX+' de '+rows.length+'. Sigue escribiendo para acotar.'));
   if(!rows.length&&!typedValue)list.append(node('div','ui-select-empty','Sin sugerencias'));
   items.forEach((entry,index)=>{entry.item.addEventListener('click',()=>pick(entry.value));entry.item.addEventListener('mousemove',()=>mark(index,false));});
   const current=items.findIndex(e=>e.item.getAttribute('aria-selected')==='true');if(current>=0)mark(current);else if(query&&items.length)mark(items[0].item.classList.contains('ui-select-create')&&items.length>1?1:0);
   place(list,input);}
  const key=event=>{const k=event.key;
   if(k==='Escape'){event.preventDefault();event.stopPropagation();close();return true;}
   if(k==='ArrowDown'||k==='ArrowUp'){event.preventDefault();mark(active<0?0:Math.max(0,Math.min(items.length-1,active+(k==='ArrowDown'?1:-1))));return true;}
   if(k==='Enter'&&active>=0){event.preventDefault();event.stopPropagation();pick(items[active].value);return true;}
   if(k==='Tab'){close();return true;}return false;};
  open={list,anchor:input,key,repaint,off:watch(list,input)};repaint(matches,needle,exact);
 }
 function enhance(input){if(!(input instanceof HTMLInputElement)||!input.getAttribute('list'))return;input.dataset.uiList=input.getAttribute('list');input.removeAttribute('list');
  if(input.dataset.uiCombo)return;input.dataset.uiCombo='true';
  input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-expanded','false');input.autocomplete='off';
  input.addEventListener('input',()=>{if(document.activeElement===input)suggest(input);});
  // Como el navegador: se abre al hacer clic, al escribir o con la flecha abajo (no al llegar con Tab).
  input.addEventListener('mousedown',()=>{if(input.readOnly||input.disabled)return;if(open&&open.anchor===input){close();return;}setTimeout(()=>{if(document.activeElement===input)suggest(input);},0);});
  input.addEventListener('keydown',event=>{if(event.key==='ArrowDown'&&!(open&&open.anchor===input)){event.preventDefault();suggest(input);}});}
 const scan=root=>{if(root instanceof HTMLInputElement)enhance(root);root.querySelectorAll?.('input[list]').forEach(enhance);};
 const start=()=>{scan(document);new MutationObserver(changes=>{for(const change of changes){if(change.type==='attributes')enhance(change.target);else change.addedNodes.forEach(scan);}}).observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['list']});};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
 window.UiSelect={close,isOpen:()=>!!open,enhance};
})();
