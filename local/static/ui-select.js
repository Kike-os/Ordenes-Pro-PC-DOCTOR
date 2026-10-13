'use strict';
// Menú desplegable propio para los <select> del sistema. El control cerrado sigue siendo el <select> nativo (mismo tamaño, foco, formularios
// y lectores de pantalla); solo se sustituye la lista que el navegador abre —y que no admite estilos— por una lista con el tema azul.
// En pantallas táctiles se conserva el selector nativo del sistema operativo, que allí es más cómodo.
(()=>{
 const touch=matchMedia('(pointer:coarse)'),fine={get matches(){return !touch.matches;}};
 let open=null,typed='',typedAt=0;
 const usable=select=>select instanceof HTMLSelectElement&&!select.multiple&&select.size<2&&!select.disabled&&select.dataset.native!=='true'&&fine.matches;
 function close(){if(!open)return;const{list,select,off}=open;open=null;list.remove();select.removeAttribute('data-ui-open');off();}
 function choose(select,option){if(option.disabled||option.closest('optgroup')?.disabled)return;if(select.value!==option.value||select.selectedOptions[0]!==option){option.selected=true;select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}));}}
 function show(select){
  close();const host=select.closest('dialog')||document.body,list=document.createElement('div');list.className='ui-select-list';list.setAttribute('role','listbox');list.tabIndex=-1;
  const label=select.getAttribute('aria-label')||select.labels?.[0]?.textContent?.trim();if(label)list.setAttribute('aria-label',label);
  const items=[];
  const add=(option,parent)=>{const item=document.createElement('div');item.className='ui-select-option';item.setAttribute('role','option');item.textContent=option.label||option.textContent||' ';const off=option.disabled||!!parent?.disabled;if(off)item.setAttribute('aria-disabled','true');if(option.hidden)item.hidden=true;item.setAttribute('aria-selected',String(option.selected));
   if(!off)item.addEventListener('click',()=>{choose(select,option);close();select.focus();});item.addEventListener('mousemove',()=>{if(!off)mark(items.indexOf(entry));});const entry={item,option,off:off||option.hidden};items.push(entry);(parent?parent.box:list).append(item);};
  for(const child of select.children){if(child.tagName==='OPTGROUP'){const box=document.createElement('div');box.className='ui-select-group';box.setAttribute('role','group');const title=document.createElement('div');title.className='ui-select-group-label';title.textContent=child.label;box.append(title);list.append(box);for(const option of child.children)add(option,{box,disabled:child.disabled});}else if(child.tagName==='OPTION')add(child);}
  let active=items.findIndex(entry=>entry.option.selected);
  function mark(index){if(index<0||index>=items.length||items[index].off)return;items[active]?.item.removeAttribute('data-active');active=index;items[index].item.dataset.active='true';items[index].item.scrollIntoView({block:'nearest'});}
  const step=(from,delta)=>{for(let index=from+delta;index>=0&&index<items.length;index+=delta)if(!items[index].off)return index;return from;};
  host.append(list);
  // Posición: debajo del control; arriba si no cabe. Se corrige contra el propio rectángulo por si el contenedor desplaza los elementos fijos.
  function place(){const box=select.getBoundingClientRect(),below=innerHeight-box.bottom-10,above=box.top-10,up=below<180&&above>below,space=Math.max(120,Math.min(340,up?above:below));
   list.style.maxHeight=space+'px';list.style.minWidth=box.width+'px';list.style.maxWidth=Math.max(box.width,Math.min(420,innerWidth-16))+'px';list.style.animation='none';list.style.left='0px';list.style.top='0px';
   const mine=list.getBoundingClientRect(),left=Math.max(8,Math.min(box.left,innerWidth-mine.width-8)),top=up?box.top-mine.height-4:box.bottom+4;
   list.style.left=(left-mine.left)+'px';list.style.top=(top-mine.top)+'px';list.dataset.side=up?'top':'bottom';list.style.animation='';}
  place();if(active>=0){items[active].item.dataset.active='true';items[active].item.scrollIntoView({block:'nearest'});}
  list.addEventListener('mousedown',event=>event.preventDefault());
  const outside=event=>{if(event.target!==select&&!list.contains(event.target))close();},scrolled=event=>{if(!list.contains(event.target))close();},blur=()=>setTimeout(()=>{if(open&&open.select===select&&document.activeElement!==select)close();},0);
  document.addEventListener('mousedown',outside,true);addEventListener('scroll',scrolled,true);addEventListener('resize',close);select.addEventListener('blur',blur);
  select.dataset.uiOpen='true';
  open={list,select,off(){document.removeEventListener('mousedown',outside,true);removeEventListener('scroll',scrolled,true);removeEventListener('resize',close);select.removeEventListener('blur',blur);},
   key(event){const k=event.key;
    if(k==='Escape'){event.preventDefault();event.stopPropagation();close();return;}
    if(k==='Enter'||k===' '){event.preventDefault();if(k===' '&&typed&&Date.now()-typedAt<700)return;const entry=items[active];if(entry&&!entry.off)choose(select,entry.option);close();return;}
    if(k==='Tab'){const entry=items[active];if(entry&&!entry.off)choose(select,entry.option);close();return;}
    if(k==='ArrowDown'||k==='ArrowUp'){event.preventDefault();mark(active<0?step(-1,1):step(active,k==='ArrowDown'?1:-1));return;}
    if(k==='Home'||k==='PageUp'){event.preventDefault();mark(step(-1,1));return;}
    if(k==='End'||k==='PageDown'){event.preventDefault();mark(step(items.length,-1));return;}
    if(k.length===1&&!event.ctrlKey&&!event.metaKey&&!event.altKey){event.preventDefault();const now=Date.now();typed=now-typedAt>700?k:typed+k;typedAt=now;const needle=typed.toLocaleLowerCase(),start=typed.length===1?active+1:Math.max(active,0);
     for(let n=0;n<items.length;n++){const index=(start+n)%items.length;if(!items[index].off&&items[index].item.textContent.trim().toLocaleLowerCase().startsWith(needle)){mark(index);break;}}}}};
 }
 document.addEventListener('mousedown',event=>{if(event.button!==0)return;const select=event.target instanceof Element?event.target.closest('select'):null;if(!select||!usable(select))return;event.preventDefault();select.focus();if(open&&open.select===select)close();else show(select);},true);
 document.addEventListener('keydown',event=>{const select=event.target;if(!(select instanceof HTMLSelectElement))return;if(open&&open.select===select){open.key(event);return;}
  if(!usable(select))return;if(event.key===' '||event.key==='Enter'||event.key==='F4'||(event.altKey&&(event.key==='ArrowDown'||event.key==='ArrowUp'))){if(event.key==='Enter'&&select.form&&!select.dataset.uiEnter)return;event.preventDefault();show(select);}},true);
 window.UiSelect={close,isOpen:()=>!!open};
})();
