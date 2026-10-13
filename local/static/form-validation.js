'use strict';
// Validadores puros compartidos por fichas de cliente y agenda.
function validCedula(value){if(!/^[0-9]{10}$/.test(value)||!((+value.slice(0,2)>=1&&+value.slice(0,2)<=24)||value.startsWith('30'))||+value[2]>5)return false;const sum=[...value.slice(0,9)].reduce((sum,n,i)=>{const p=+n*(i%2===0?2:1);return sum+(p>9?p-9:p);},0);return(10-sum%10)%10===+value[9];}
// Cédula y RUC ecuatorianos con las reglas de cada tipo (las mismas del servidor, reception.document_check). Devuelve {error, notice}.
// Cédula: provincia, tercer dígito 0-5 y dígito verificador. RUC de persona natural: su cédula más el establecimiento. RUC de entidad
// pública (6) o sociedad (9): provincia y establecimiento; si su dígito verificador no coincide solo se avisa, no se rechaza.
function documentCheck(value,kind=''){const size={cedula:10,ruc:13}[kind],fail=error=>({error,notice:''});
 if(!/^[0-9]+$/.test(value)||(size?value.length!==size:![10,13].includes(value.length)))return fail(size===10?'La cédula debe contener exactamente 10 dígitos.':size===13?'El RUC debe contener exactamente 13 dígitos.':'Ingresa 10 dígitos para cédula o 13 para RUC, sin letras ni símbolos.');
 const province=(+value.slice(0,2)>=1&&+value.slice(0,2)<=24)||value.startsWith('30'),third=+value[2];
 if(value.length===10){if(!province)return fail('Los dos primeros dígitos de la cédula no corresponden a una provincia.');if(third>5)return fail('El tercer dígito no corresponde a una cédula ecuatoriana.');return fail(validCedula(value)?'':'El número de cédula no es válido. Revisa los dígitos ingresados.');}
 if(!province)return fail('Los dos primeros dígitos del RUC no corresponden a una provincia.');if(third===7||third===8)return fail('El tercer dígito no corresponde a ningún tipo de RUC.');
 const branch='El RUC debe terminar en su número de establecimiento (por ejemplo, 001).';
 if(third<6){if(!validCedula(value.slice(0,10)))return fail('Los diez primeros dígitos del RUC no forman una cédula válida. Revisa los dígitos ingresados.');return fail(+value.slice(10)>0?'':branch);}
 const weights=third===6?[3,2,7,6,5,4,3,2]:[4,3,2,7,6,5,4,3,2],position=third===6?8:9;if(+value.slice(position+1)===0)return fail(branch);
 const check=(11-weights.reduce((sum,w,i)=>sum+w*(+value[i]),0)%11)%11;return{error:'',notice:check<10&&check===+value[position]?'':'No pudimos comprobar el dígito verificador de este RUC. Confirma que esté escrito correctamente.'};}
function documentError(value,kind=''){return documentCheck(value,kind).error;}
// Selector segmentado sobre un <select> existente: el select sigue siendo el dato del formulario (nombre, valor, eventos) y queda oculto;
// los botones lo reflejan. Admite opciones añadidas o deshabilitadas después y cambios hechos por código (llamar a la función devuelta).
function segmentedSelect(select,label){if(select._segmented)return select._segmented;const group=document.createElement('div');group.className='seg-control';group.setAttribute('role','radiogroup');if(label)group.setAttribute('aria-label',label);
 const buttons=()=>[...group.querySelectorAll('button')],pick=(value,focus)=>{if(select.value!==value){select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));}paint();if(focus)buttons().find(b=>b.dataset.value===select.value)?.focus();};
 function paint(){const options=[...select.options].filter(option=>!option.hidden&&option.value);if(options.map(o=>o.value+'|'+o.textContent).join()!==group.dataset.options){group.dataset.options=options.map(o=>o.value+'|'+o.textContent).join();group.replaceChildren(...options.map(option=>{const b=document.createElement('button');b.type='button';b.setAttribute('role','radio');b.dataset.value=option.value;b.textContent=option.dataset.short||option.textContent;return b;}));group.style.setProperty('--seg-count',String(options.length));}
  for(const b of buttons()){const option=[...select.options].find(o=>o.value===b.dataset.value),on=select.value===b.dataset.value;b.setAttribute('aria-checked',String(on));b.tabIndex=on?0:-1;b.disabled=select.disabled||!!option?.disabled;}}
 group.addEventListener('click',event=>{const b=event.target.closest('button');if(b&&!b.disabled)pick(b.dataset.value,true);});
 group.addEventListener('keydown',event=>{const list=buttons().filter(b=>!b.disabled),at=list.indexOf(document.activeElement);if(at<0)return;const step={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1}[event.key];if(step){event.preventDefault();pick(list[(at+step+list.length)%list.length].dataset.value,true);}else if(event.key==='Home'||event.key==='End'){event.preventDefault();pick(list[event.key==='Home'?0:list.length-1].dataset.value,true);}});
 select.addEventListener('change',paint);new MutationObserver(paint).observe(select,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','hidden']});if(select.form)select.form.addEventListener('reset',()=>setTimeout(paint));
 select.hidden=true;select.after(group);paint();return select._segmented=paint;}
// Campo de identificación reutilizable (citas públicas, ficha de cliente, recepción y cita del personal). Une el tipo (select segmentado)
// con el número: límite y teclado según el tipo, solo dígitos al escribir o pegar, ceros iniciales intactos y contador en tiempo real.
// Cambiar de tipo nunca borra ni recorta lo escrito. `check()` devuelve {error, notice, complete} sin tocar la pantalla.
const ID_LIMITS={cedula:10,ruc:13,pasaporte:30};
function identificationControl({select,input,count,label}){const paintKind=segmentedSelect(select,label||'Tipo de identificación'),kind=()=>ID_LIMITS[select.value]?select.value:'cedula',digits=()=>kind()!=='pasaporte',limit=()=>ID_LIMITS[kind()];
 if(count){count.classList.add('id-count');count.setAttribute('aria-hidden','true');}
 function refresh(){paintKind();const size=limit(),length=input.value.length;input.maxLength=size;input.inputMode=digits()?'numeric':'text';if(digits())input.pattern='[0-9]*';else input.removeAttribute('pattern');input.autocomplete='off';if(count){count.textContent=length+'/'+size;count.dataset.state=length>size?'over':length===size&&digits()?'ok':'';}}
 input.addEventListener('beforeinput',event=>{if(digits()&&event.data&&event.inputType!=='insertFromPaste'&&/[^0-9]/.test(event.data))event.preventDefault();});
 // Pegar: se conservan solo los dígitos (un número copiado con guiones, puntos o espacios queda limpio) y nunca se supera el límite.
 input.addEventListener('paste',event=>{if(!digits())return;event.preventDefault();const text=(event.clipboardData?.getData('text')||'').replace(/[^0-9]/g,''),start=input.selectionStart??input.value.length,end=input.selectionEnd??start,room=Math.max(0,limit()-(input.value.length-(end-start)));if(!text||!room)return;input.setRangeText(text.slice(0,room),start,end,'end');input.dispatchEvent(new Event('input',{bubbles:true}));});
 input.addEventListener('input',()=>{if(digits()){const clean=input.value.replace(/[^0-9]/g,'');if(clean!==input.value)input.value=clean;}refresh();});
 select.addEventListener('change',refresh);if(input.form)input.form.addEventListener('reset',()=>setTimeout(refresh));
 function check(){const value=input.value.trim();if(!value)return{error:'',notice:'',complete:false};if(!digits())return{error:/^[A-Za-z0-9-]{3,30}$/.test(value)?'':'Ingresa un pasaporte válido: de 3 a 30 letras, números o guiones.',notice:'',complete:true};const result=documentCheck(value,kind());return{...result,complete:value.length===limit()};}
 // El selector toma la altura y la separación reales del campo numérico, para que ambos queden alineados en cualquier formulario y tamaño de pantalla.
 if(window.ResizeObserver){const group=select.nextElementSibling;new ResizeObserver(()=>{const height=input.offsetHeight;if(height){group.style.setProperty('--seg-height',height+'px');group.style.marginTop=getComputedStyle(input).marginTop;}}).observe(input);}
 refresh();return{refresh,check,kind,limit};}
function validEcuadorPhone(value){if(!/^[+0-9 ()-]+$/.test(value))return false;return /^(?:09[0-9]{8}|0[2-7][0-9]{7}|\+?593(?:9[0-9]{8}|[2-7][0-9]{7}))$/.test(value.replace(/[ ()-]/g,''));}
