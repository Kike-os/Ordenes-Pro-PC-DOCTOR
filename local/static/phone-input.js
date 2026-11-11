'use strict';
// Campo internacional «Teléfono / WhatsApp» (1.5.251). Convierte un <input> de teléfono existente en: selector de país (bandera y prefijo, con
// búsqueda por nombre o prefijo, accesible con teclado) + número. Ecuador (+593) es el país predeterminado. Valida con libphonenumber-js
// (las mismas reglas que el servidor, que usa phonenumbers) y guarda en el campo original el número en formato E.164 (p. ej. +593991234567),
// de modo que los formularios y el servidor siguen recibiendo el mismo campo «phone». Un número pegado con «+» o «00» cambia el país solo y
// nunca duplica el prefijo. No afirma que un celular tenga WhatsApp activo. Sin la biblioteca, el campo queda exactamente como estaba.
(()=>{
 const L=window.libphonenumber;
 if(!L||!L.parsePhoneNumberFromString){window.PhoneField={attach:()=>null};return;}
 const DEFAULT='EC',TOP=['EC','CO','PE','US','ES','MX'];
 // 1.5.277 · Páginas públicas bilingües (<body data-i18n-public>, hoy la Agenda de Citas): países y mensajes en el idioma elegido.
 // En el panel del personal sigue todo en español. La validación (libphonenumber) no cambia: solo el texto.
 const I=()=>document.body&&'i18nPublic' in document.body.dataset&&window.i18n?window.i18n:null,T=text=>I()?I().tr(text):text,lang=()=>I()?.lang==='en-US'?'en':'es';
 const namesBy={},names=()=>{const l=lang();if(!(l in namesBy))try{namesBy[l]=new Intl.DisplayNames([l],{type:'region'});}catch{namesBy[l]=null;}return namesBy[l];};
 const nameOf=cc=>{try{return (names()&&names().of(cc))||cc;}catch{return cc;}};
 const fold=s=>String(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
 const lists={};const countries=()=>lists[lang()]||(lists[lang()]=L.getCountries().map(cc=>({cc,code:L.getCountryCallingCode(cc),name:nameOf(cc)})).sort((a,b)=>a.name.localeCompare(b.name,lang())));
 const mk=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 const flag=cc=>{const i=mk('img','pi-flag');i.src='/static/flags/'+cc+'.svg';i.alt='';i.width=22;i.height=15;i.decoding='async';
  i.addEventListener('error',()=>{const s=mk('span','pi-flag pi-noflag',cc);i.replaceWith(s);},{once:true});return i;};
 // Interpreta un texto: «+»/«00» en su país; sin prefijo, en el país elegido; «593…» o «57…» pegados sin «+» también se reconocen.
 function parse(text,cc){const raw=String(text||'').trim();if(!raw)return null;const t=raw.startsWith('00')?'+'+raw.slice(2):raw;
  let p=null;try{p=L.parsePhoneNumberFromString(t,t.startsWith('+')?undefined:cc||DEFAULT);}catch{p=null;}
  if(p&&p.isValid())return p;const d=t.replace(/\D/g,'');
  // Ecuador: la regla que el sistema ya aceptaba (celular 09 + 8 cifras, fijo 0[2-7] + 7) nunca se rechaza (la tabla no trae todos los prefijos móviles).
  if((!t.startsWith('+')&&(cc||DEFAULT)==='EC')||t.replace(/[\s()-]/g,'').startsWith('+593')){const n=t.startsWith('+')?d.slice(3):d;
   if(/^(?:0?9\d{8}|0[2-7]\d{7})$/.test(n)){try{const q=L.parsePhoneNumberFromString('+593'+n.replace(/^0/,''));if(q)return q;}catch{}}}
  if(!t.startsWith('+')&&d.length>=10){try{const q=L.parsePhoneNumberFromString('+'+d);if(q&&q.isValid())return q;}catch{}}
  return p&&p.isValid()?p:null;}
 function problem(text,cc){const raw=String(text||'').trim();if(!raw)return '';if(!/^[+0-9 ().\-]+$/.test(raw))return T('Escribe solo números, espacios y el prefijo «+».');
  const t=raw.startsWith('00')?'+'+raw.slice(2):raw;let where=cc;try{const p=L.parsePhoneNumberFromString(t,t.startsWith('+')?undefined:cc);if(p&&p.country)where=p.country;}catch{}
  let r;try{r=L.validatePhoneNumberLength(t,t.startsWith('+')?undefined:cc);}catch{r='';}
  const n=nameOf(where);return T(r==='TOO_SHORT'?'El número está incompleto para '+n+'.':r==='TOO_LONG'?'El número tiene dígitos de más para '+n+'.':r==='INVALID_COUNTRY'?'El código de país no existe.':r==='NOT_A_NUMBER'?'Escribe solo números.':'El número no es válido para '+n+'.');}
 let uid=0;
 function attach(source,opts={}){
  if(!source)return null;if(source._phoneField)return source._phoneField;
  const id='pi'+(++uid),proto=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');
  const wrap=mk('div','pi'),box=mk('div','pi-box'),pick=mk('span','pi-country'),code=mk('span','pi-code'),num=mk('input','pi-number'),msg=mk('small','pi-msg');
  // El selector de país no es un control «etiquetable»: así la etiqueta del formulario sigue nombrando al número (y el clic en ella lo enfoca).
  pick.setAttribute('role','button');pick.tabIndex=0;pick.setAttribute('aria-haspopup','listbox');pick.setAttribute('aria-expanded','false');pick.setAttribute('aria-controls',id+'-list');
  const chevron=document.createElementNS('http://www.w3.org/2000/svg','svg');chevron.setAttribute('viewBox','0 0 24 24');chevron.setAttribute('aria-hidden','true');chevron.classList.add('pi-chev');chevron.innerHTML='<path d="m6 9 6 6 6-6"/>';
  num.type='tel';num.inputMode='tel';num.autocomplete='tel-national';num.maxLength=24;num.spellcheck=false;
  if(source.id){num.id=source.id;source.id=source.id+'-e164';}
  for(const a of ['aria-describedby','aria-label','aria-labelledby','title'])if(source.hasAttribute(a))num.setAttribute(a,source.getAttribute(a));
  msg.id=id+'-msg';msg.setAttribute('aria-live','polite');num.setAttribute('aria-describedby',[num.getAttribute('aria-describedby'),msg.id].filter(Boolean).join(' '));
  // «Obligatorio» se queda en el campo original (lo revisan las validaciones existentes); el número visible lo anuncia a los lectores de pantalla.
  if(source.required)num.setAttribute('aria-required','true');
  source.addEventListener('invalid',()=>{msg.textContent=source.validationMessage||T('Completa este campo.');wrap.dataset.state='error';num.focus();});
  if(source.disabled)num.disabled=true;if(source.readOnly)num.readOnly=true;
  // Mismo aspecto que los demás campos de su formulario (colores, borde y radio del campo original).
  try{const st=getComputedStyle(source);if(st.backgroundColor&&st.backgroundColor!=='rgba(0, 0, 0, 0)'){wrap.style.setProperty('--pi-bg',st.backgroundColor);wrap.style.setProperty('--pi-border',st.borderTopColor);
   wrap.style.setProperty('--pi-fg',st.color);wrap.style.setProperty('--pi-radius',st.borderTopLeftRadius);wrap.style.setProperty('--pi-gap',st.marginTop);wrap.style.setProperty('--pi-size',st.fontSize);}}catch{}
  source.hidden=true;source.tabIndex=-1;source.classList.add('pi-source');
  source.parentNode.insertBefore(wrap,source);box.append(pick,num);wrap.append(box,msg,source);pick.append(flag(DEFAULT),code,chevron);
  let cc=DEFAULT,touched=false,legacy=false;
  const setCountry=next=>{cc=next;const f=pick.querySelector('.pi-flag');f.replaceWith(flag(cc));code.textContent='+'+L.getCountryCallingCode(cc);
   pick.setAttribute('aria-label',T('País del teléfono: '+nameOf(cc)+' (+'+L.getCountryCallingCode(cc)+'). Cambiar país'));num.placeholder=cc==='EC'?'099 123 4567':T('Número sin el prefijo');};
  const write=v=>{proto.set.call(source,v);};
  // Estado → campo original (E.164 si es válido; si no, el texto escrito, para que el servidor explique el error) y mensaje.
  function sync(final){const text=num.value.trim(),p=parse(text,cc);
   if(p&&p.country&&p.country!==cc&&/^\s*(\+|00)|^\d{10,}$/.test(text))setCountry(p.country);
   write(p?p.number:text);
   let note='',bad='';
   if(!text){note='';}
   else if(p){const type=p.getType();note=T('Número válido · '+nameOf(p.country||cc)+(type==='MOBILE'?' · celular':type==='FIXED_LINE'?' · teléfono fijo (no sirve para WhatsApp)':''));
    if(final){num.value=p.formatNational();legacy=false;}}
   else if(final||touched&&text.replace(/\D/g,'').length>=6){bad=problem(text,cc);note=legacy?'Registrado con un formato anterior: '+bad:bad;}
   num.setCustomValidity(bad);wrap.dataset.state=bad?'error':p?'ok':'';msg.textContent=note;if(bad)num.setAttribute('aria-invalid','true');else num.removeAttribute('aria-invalid');
   source.dispatchEvent(new Event('input',{bubbles:true}));if(final)source.dispatchEvent(new Event('change',{bubbles:true}));}
  // Valor que llega desde el código (prefijar un cliente, restaurar un borrador): se interpreta sin reescribir un dato que no se entiende.
  function load(v){const text=String(v||'').trim(),p=parse(text,opts.country||DEFAULT);legacy=false;  // lo guardado es E.164 o un número antiguo de Ecuador
   if(p){setCountry(p.country||cc);num.value=p.formatNational();write(p.number);}
   else{num.value=text;write(text);legacy=!!text;}
   wrap.dataset.state='';msg.textContent=legacy?'Registrado con un formato anterior: revíselo antes de guardar.':'';num.setCustomValidity('');num.removeAttribute('aria-invalid');}
  Object.defineProperty(source,'value',{configurable:true,get(){return proto.get.call(source);},set(v){load(v);}});
  source.focus=o=>num.focus(o);
  num.addEventListener('input',()=>{touched=true;sync(false);});
  num.addEventListener('blur',()=>{if(num.value.trim())sync(true);});
  num.addEventListener('paste',()=>setTimeout(()=>sync(true)));
  source.form&&source.form.addEventListener('reset',()=>setTimeout(()=>{setCountry(opts.country||DEFAULT);load(proto.get.call(source));}));
  // Lista de países con búsqueda (nombre o prefijo). Teclado: flechas, Inicio/Fin, Intro elige, Escape cierra y devuelve el foco.
  let panel=null,items=[],active=0;
  function close(focus){if(!panel)return;panel.remove();panel=null;pick.setAttribute('aria-expanded','false');document.removeEventListener('pointerdown',outside,true);if(focus)pick.focus();}
  function outside(e){if(panel&&!panel.contains(e.target)&&!pick.contains(e.target))close(false);}
  function choose(next){setCountry(next);close(false);touched=true;sync(false);num.focus();}
  function render(q){const list=panel.querySelector('ul'),f=fold(q).replace(/^\+/,''),digits=/^\+?\d+$/.test(q.trim());
   const rows=countries().filter(c=>!f||(digits?c.code.startsWith(f):fold(c.name).includes(f)||c.cc.toLowerCase()===f));
   const ordered=f?rows:[...TOP.map(t=>rows.find(c=>c.cc===t)).filter(Boolean),...rows.filter(c=>!TOP.includes(c.cc))];
   list.replaceChildren();items=ordered;active=Math.max(0,ordered.findIndex(c=>c.cc===cc));if(f)active=0;
   ordered.forEach((c,i)=>{const li=mk('li','pi-opt');li.id=id+'-o'+i;li.setAttribute('role','option');li.setAttribute('aria-selected',String(c.cc===cc));if(!f&&i===TOP.length-1)li.classList.add('pi-sep');
    const img=flag(c.cc);img.loading='lazy';li.append(img,mk('span','pi-name',c.name),mk('span','pi-dial','+'+c.code));li.addEventListener('click',()=>choose(c.cc));list.append(li);});
   if(!ordered.length)list.append(mk('li','pi-empty',T('Sin resultados')));mark();}
  function mark(){const list=panel.querySelector('ul');[...list.children].forEach((li,i)=>li.classList.toggle('pi-active',i===active));const cur=list.children[active];
   if(cur&&cur.id){panel.querySelector('input').setAttribute('aria-activedescendant',cur.id);cur.scrollIntoView({block:'nearest'});}}
  function open(){if(panel)return close(true);if(num.disabled||num.readOnly)return;panel=mk('div','pi-panel');const search=mk('input','pi-search'),list=mk('ul','pi-list');
   search.type='search';search.placeholder=T('Buscar país o prefijo');search.setAttribute('aria-label',T('Buscar país o prefijo'));search.setAttribute('role','combobox');search.setAttribute('aria-controls',id+'-list');search.setAttribute('aria-expanded','true');search.autocomplete='off';
   list.id=id+'-list';list.setAttribute('role','listbox');list.setAttribute('aria-label',T('Países'));panel.append(search,list);wrap.append(panel);pick.setAttribute('aria-expanded','true');render('');
   const r=panel.getBoundingClientRect();if(r.right>innerWidth-8)panel.style.setProperty('--pi-shift',Math.round(r.right-innerWidth+8)+'px');
   search.addEventListener('input',()=>render(search.value));
   search.addEventListener('keydown',e=>{if(e.key==='ArrowDown'){e.preventDefault();active=Math.min(items.length-1,active+1);mark();}else if(e.key==='ArrowUp'){e.preventDefault();active=Math.max(0,active-1);mark();}
    else if(e.key==='Home'&&!search.value){e.preventDefault();active=0;mark();}else if(e.key==='End'&&!search.value){e.preventDefault();active=items.length-1;mark();}
    else if(e.key==='Enter'){e.preventDefault();if(items[active])choose(items[active].cc);}else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}else if(e.key==='Tab')close(false);});
   document.addEventListener('pointerdown',outside,true);search.focus();}
  pick.addEventListener('click',open);
  pick.addEventListener('keydown',e=>{if(['Enter',' ','ArrowDown'].includes(e.key)){e.preventDefault();open();}});
  setCountry(opts.country||DEFAULT);load(proto.get.call(source));
  // Cambio de idioma: se vuelven a escribir el país, la ayuda y el mensaje del número sin tocar lo escrito.
  document.addEventListener('i18n:change',()=>{if(!I())return;close(false);setCountry(cc);if(num.value.trim())sync(false);});
  const api={source,input:num,get country(){return cc;},set:load,valid:()=>!!parse(num.value,cc)};source._phoneField=api;return api;}
 // Inicio automático: cualquier <input data-phone-intl> presente o agregado después (formularios que se dibujan al abrir una ventana).
 const scan=root=>{if(root.querySelectorAll)for(const i of root.querySelectorAll('input[data-phone-intl]:not(.pi-source)'))attach(i);};
 const start=()=>{scan(document);new MutationObserver(list=>{for(const m of list)for(const n of m.addedNodes)if(n.nodeType===1){if(n.matches&&n.matches('input[data-phone-intl]:not(.pi-source)'))attach(n);else scan(n);}}).observe(document.body,{childList:true,subtree:true});};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
 window.PhoneField={attach,parse:(text,cc)=>parse(text,cc||DEFAULT)};
})();
