// Órdenes Pro 1.5.273 · Idiomas de la interfaz: español de Ecuador (predeterminado) e inglés de Estados Unidos.
// - Catálogos por clave (CATALOG) para los textos fijos de las plantillas: data-i18n="clave" y data-i18n-attr="atributo:clave;…".
// - Frases (PHRASES/PATTERNS) para los textos que llegan en tiempo de ejecución en español (validaciones, mensajes del servidor). Solo se
//   traducen coincidencias exactas o patrones conocidos: los datos escritos por clientes, códigos, números de serie y documentos históricos
//   (notas de versión, condiciones aceptadas) nunca se traducen.
// - La elección se guarda en este navegador (localStorage) y, con sesión iniciada, en la cuenta para sincronizarla entre equipos.
// Se carga sin «defer» en <head> para aplicar el idioma antes de mostrar la tarjeta de acceso (sin parpadeo en español).
(function(){
'use strict';
const KEY='ordenes-pro:idioma',PENDING='ordenes-pro:idioma-cuenta';
const LANGS={'es-EC':{name:'Español',short:'ES',flag:'EC',html:'es-EC'},'en-US':{name:'English',short:'EN',flag:'US',html:'en-US'}};
const DEFAULT='es-EC';
const CATALOG={
 'es-EC':{
  'brand.tagline':'Sistema de Gestión de Reparaciones','brand.logo':'Logotipo oficial PC-DOCTOR',
  'lang.title':'Seleccione su idioma / Select your language','lang.group':'Idioma de la interfaz',
  'login.user':'Usuario o correo electrónico','login.user_ph':'Tu usuario o correo','login.password':'Contraseña','login.password_ph':'Tu contraseña',
  'login.remember':'Recordar mi sesión','login.forgot':'¿Olvidaste tu contraseña?','login.submit':'Iniciar sesión','login.trap':'Sitio web',
  'ip.title':'Software privado · Propiedad intelectual protegida',
  'ip.text':'Órdenes Pro es un sistema desarrollado para uso exclusivo de PC-DOCTOR S.A. Se prohíbe su reproducción, distribución, comercialización, modificación o acceso no autorizado al código fuente.',
  'ip.rights':'© 2026 PC-DOCTOR S.A. | Todos los derechos reservados.',
  'version.title':'Versión del sistema','version.view':'Ver las actualizaciones del sistema','version.checking':'Comprobando actualizaciones…','version.news':'Actualizaciones del sistema',
  'version.retry':'Reintentar','version.reload':'Recargar página','login.book':'Agendar cita',
  'forgot.doc':'Recuperar acceso | Órdenes Pro','forgot.title':'Recuperar acceso','forgot.intro':'Introduce tu correo para solicitar un enlace seguro de restablecimiento.',
  'forgot.email':'Correo electrónico','forgot.email_ph':'nombre@empresa.com','forgot.submit':'Enviar enlace de recuperación','auth.back':'Volver a iniciar sesión',
  'reset.doc':'Nueva contraseña | Órdenes Pro','reset.title':'Crear nueva contraseña','reset.intro':'Utiliza al menos {n} caracteres. Puedes usar una frase larga y tu gestor de contraseñas.',
  'reset.password':'Nueva contraseña','reset.strength':'Fortaleza estimada de contraseña','reset.strength_hint':'Fortaleza estimada; prioriza longitud y palabras poco predecibles.',
  'reset.repeat':'Confirmar contraseña','reset.submit':'Guardar contraseña',
  'nav.main':'Navegación principal','nav.home':'Inicio','nav.orders':'Órdenes','nav.clients':'Clientes','nav.devices':'Equipos','nav.reports':'Reportes','nav.settings':'Configuración',
  'nav.appointments':'Citas','nav.sales':'Ventas','nav.licenses':'Licencias','nav.invoicing':'Facturación','nav.inventory':'Inventario','nav.mail':'Correo','nav.system':'Sistema',
  'nav.assistance':'Asistencia','nav.live':'Atención en vivo','nav.adi':'ADI administrativa',
  'account.open':'Abrir menú de cuenta','account.logout':'Cerrar sesión','account.notifications':'Notificaciones','account.loading':'Cargando…',
  'notify.title':'Centro de notificaciones','notify.read':'Marcar todas como leídas','notify.history':'Ver el historial',
  'pref.title':'Idioma de la interfaz','pref.hint':'Se guarda en tu cuenta y se aplica en todos tus equipos.',
  'pref.scope':'En inglés: inicio de sesión, recuperación de contraseña, navegación principal y menú de cuenta. Los demás módulos siguen en español mientras se completa su traducción. Los datos de clientes, códigos, números de serie y documentos emitidos no se traducen.',
  'pref.saved':'Idioma guardado en tu cuenta.','pref.local':'Idioma aplicado en este navegador. No se pudo guardar en tu cuenta; se intentará de nuevo al volver a entrar.'
 },
 'en-US':{
  'brand.tagline':'Repair Management System','brand.logo':'Official PC-DOCTOR logo',
  'lang.title':'Seleccione su idioma / Select your language','lang.group':'Interface language',
  'login.user':'Username or Email','login.user_ph':'Your username or email','login.password':'Password','login.password_ph':'Your password',
  'login.remember':'Remember me','login.forgot':'Forgot your password?','login.submit':'Sign In','login.trap':'Website',
  'ip.title':'Private software · Protected intellectual property',
  'ip.text':'Órdenes Pro is a system developed for the exclusive use of PC-DOCTOR S.A. Reproduction, distribution, commercialization, modification or unauthorized access to the source code is prohibited.',
  'ip.rights':'© 2026 PC-DOCTOR S.A. | All rights reserved.',
  'version.title':'System Version','version.view':'View system updates','version.checking':'Checking for updates…','version.news':'System Updates',
  'version.retry':'Retry','version.reload':'Reload page','login.book':'Book an Appointment',
  'forgot.doc':'Recover access | Órdenes Pro','forgot.title':'Recover access','forgot.intro':'Enter your email to request a secure reset link.',
  'forgot.email':'Email','forgot.email_ph':'name@company.com','forgot.submit':'Send recovery link','auth.back':'Back to sign in',
  'reset.doc':'New password | Órdenes Pro','reset.title':'Create a new password','reset.intro':'Use at least {n} characters. You can use a long passphrase and your password manager.',
  'reset.password':'New password','reset.strength':'Estimated password strength','reset.strength_hint':'Estimated strength; favor length and unpredictable words.',
  'reset.repeat':'Confirm password','reset.submit':'Save password',
  'nav.main':'Main navigation','nav.home':'Home','nav.orders':'Orders','nav.clients':'Clients','nav.devices':'Devices','nav.reports':'Reports','nav.settings':'Settings',
  'nav.appointments':'Appointments','nav.sales':'Sales','nav.licenses':'Licenses','nav.invoicing':'Invoicing','nav.inventory':'Inventory','nav.mail':'Mail','nav.system':'System',
  'nav.assistance':'Assistance','nav.live':'Live support','nav.adi':'Administrative ADI',
  'account.open':'Open account menu','account.logout':'Sign out','account.notifications':'Notifications','account.loading':'Loading…',
  'notify.title':'Notification center','notify.read':'Mark all as read','notify.history':'View history',
  'pref.title':'Interface language','pref.hint':'Saved to your account and applied on all your devices.',
  'pref.scope':'In English: sign in, password recovery, main navigation and account menu. Other modules remain in Spanish while their translation is completed. Client data, codes, serial numbers and issued documents are not translated.',
  'pref.saved':'Language saved to your account.','pref.local':'Language applied in this browser. It could not be saved to your account; it will be retried next time you sign in.'
 }
};
// Textos en español que llegan en tiempo de ejecución → inglés (coincidencia exacta).
const PHRASES={
 // Validación del acceso
 'El usuario admite hasta 50 caracteres.':'Usernames allow up to 50 characters.','Escribiendo…':'Typing…','Contraseña introducida.':'Password entered.',
 'Formato de correo válido.':'Valid email format.','Completa el correo electrónico.':'Complete the email address.','Revisa el formato del correo electrónico.':'Check the email format.',
 'El usuario no lleva espacios.':'Usernames cannot contain spaces.','Usuario incompleto.':'Incomplete username.','Formato válido.':'Valid format.',
 'Escribe tu usuario o correo electrónico.':'Enter your username or email.','Introduce tu correo electrónico.':'Enter your email address.','Escribe tu contraseña.':'Enter your password.',
 'Completa este campo.':'Complete this field.','Formato de correo correcto.':'Valid email format.','Usa de 3 a 50 letras, números, punto, guion o guion bajo.':'Use 3 to 50 letters, numbers, periods, hyphens or underscores.',
 'Las contraseñas coinciden.':'Passwords match.','Las contraseñas no coinciden.':'Passwords do not match.','Bloq Mayús está activado.':'Caps Lock is on.',
 'Demasiado corta':'Too short','Fortaleza baja':'Low strength','Fortaleza media':'Medium strength','Fortaleza alta':'High strength','Frase o contraseña larga':'Long passphrase or password',
 'Fortaleza estimada; prioriza longitud y palabras poco predecibles.':'Estimated strength; favor length and unpredictable words.',
 'Mostrar contraseña':'Show password','Ocultar contraseña':'Hide password','Mostrar usuario':'Show username','Ocultar usuario':'Hide username',
 // Envío
 'Verificando acceso…':'Verifying access…','Verificando…':'Verifying…','Enviando solicitud…':'Sending request…',
 'Completa la verificación de seguridad para iniciar sesión.':'Complete the security check to sign in.','Comprobando la seguridad del acceso…':'Checking sign-in security…',
 'No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.':'Could not connect to the server. Check your connection and try again.',
 'Acceso confirmado. Entrando…':'Access confirmed. Signing in…','Acceso confirmado':'Access confirmed',
 'Tu sesión se cerró por inactividad. Inicia sesión de nuevo para continuar.':'Your session was closed due to inactivity. Sign in again to continue.',
 'Tu sesión terminó. Inicia sesión de nuevo para continuar.':'Your session has ended. Sign in again to continue.',
 'Tu contraseña se ha actualizado correctamente':'Your password has been updated successfully','Marca «No soy un robot» para enviar la solicitud.':'Check “I am not a robot” to send the request.',
 // Verificación «No soy un robot» y Turnstile
 'No soy un robot':'I am not a robot','Verificado':'Verified','Marca la casilla para continuar':'Check the box to continue','Comprobando tu navegador…':'Checking your browser…',
 'Válida durante unos minutos':'Valid for a few minutes','Acceso protegido':'Protected access','Verificación propia, sin rastreadores ni servicios externos.':'In-house verification, with no trackers or external services.',
 'Si la verificación falla, espera unos minutos o ':'If the check fails, wait a few minutes or ','recupera tu contraseña':'recover your password',
 'No se pudo cargar la verificación.':'The security check could not be loaded.','La verificación no está disponible. Espera o recupera tu contraseña.':'The security check is not available. Wait or recover your password.',
 'No se pudo cargar la verificación. Espera e inténtalo más tarde.':'The security check could not be loaded. Wait and try again later.',
 // Mensajes del servidor (acceso, recuperación y restablecimiento)
 'No pudimos iniciar sesión. Verifica tus credenciales e inténtalo nuevamente.':'We could not sign you in. Check your credentials and try again.',
 'Por seguridad, el acceso está temporalmente limitado. Inténtalo más tarde o recupera tu contraseña.':'For security, access is temporarily limited. Try again later or recover your password.',
 'Por seguridad, el acceso está temporalmente limitado. Inténtalo más tarde.':'For security, access is temporarily limited. Try again later.',
 'La verificación caducó. Vuelve a ingresar tu usuario y contraseña.':'The verification expired. Enter your username and password again.',
 'Si el correo está asociado a una cuenta, recibirás las instrucciones para restablecer tu contraseña.':'If the email is associated with an account, you will receive instructions to reset your password.',
 'Verificación no disponible.':'Verification not available.','La sesión de seguridad no es válida. Recarga la página.':'The security session is not valid. Reload the page.',
 'Introduce un correo electrónico con formato válido.':'Enter a valid email address.','Inicia sesión para continuar.':'Sign in to continue.',
 'Esta contraseña es demasiado común. Elige otra frase de contraseña.':'This password is too common. Choose another passphrase.',
 'El registro de cuentas no está disponible.':'Account registration is not available.','El enlace no es válido o ha caducado.':'The link is invalid or has expired.',
 'El código no es correcto. Revisa tu aplicación de autenticación e inténtalo de nuevo.':'The code is incorrect. Check your authenticator app and try again.',
 'Demasiados intentos. Intenta más tarde.':'Too many attempts. Try again later.','Demasiadas verificaciones. Espera unos minutos e inténtalo de nuevo.':'Too many checks. Wait a few minutes and try again.',
 'Completa un usuario o correo válido y tu contraseña.':'Enter a valid username or email and your password.',
 'Completa la verificación de seguridad. Si falla, puedes esperar o recuperar tu contraseña.':'Complete the security check. If it fails, you can wait or recover your password.',
 'Completa la verificación de seguridad. Puedes esperar e intentarlo más tarde.':'Complete the security check. You can wait and try again later.',
 'Acceso no permitido.':'Access not allowed.','No se pudo completar la operación.':'The operation could not be completed.',
 // Verificación en dos pasos
 'Verificación en dos pasos':'Two-step verification','Ingresa el código de 6 dígitos de tu aplicación de autenticación.':'Enter the 6-digit code from your authenticator app.',
 'Código de verificación':'Verification code','Código de recuperación':'Recovery code','Verificar':'Verify','Cancelar':'Cancel',
 'Usar un código de recuperación':'Use a recovery code','Usar el código de la aplicación':'Use the app code',
 'Ingresa uno de los códigos de recuperación que guardaste al activar la verificación. Cada código sirve una sola vez.':'Enter one of the recovery codes you saved when you enabled verification. Each code works only once.',
 ' Confiar en este equipo durante 30 días':' Trust this device for 30 days',
 'Este navegador no volverá a pedir el código durante 30 días. No lo actives en equipos compartidos.':'This browser will not ask for the code again for 30 days. Do not enable it on shared devices.',
 'Inicio de sesión cancelado. Vuelve a ingresar tus datos.':'Sign-in canceled. Enter your details again.',
 'El código de recuperación tiene 10 caracteres.':'The recovery code has 10 characters.','Escribe los 6 dígitos del código.':'Enter the 6 digits of the code.',
 // Versión y estabilidad
 'Comprobando actualizaciones…':'Checking for updates…','Sistema actualizado':'System Up to Date','Nueva versión':'New version','Importante':'Important',
 'No se pudo comprobar si hay actualizaciones':'Could not check for updates','Actualizaciones del sistema':'System Updates','Actualizaciones del sistema (hay novedades sin leer)':'System Updates (unread news)',
 'Cerrar actualizaciones':'Close updates','Novedades':'What’s new','Historial':'History','Compatibilidad':'Compatibility',
 'Esta versión no tiene notas detalladas registradas.':'This version has no detailed release notes.',
 'Funciona en las versiones actuales de Chrome, Edge, Firefox y Safari, en computadoras y teléfonos. No requiere instalación: basta con recargar la página.':'Works on current versions of Chrome, Edge, Firefox and Safari, on computers and phones. No installation required: just reload the page.',
 'Cargar versiones anteriores':'Load earlier versions','Sin resumen':'No summary','Sin notas detalladas.':'No detailed notes.','No se pudo cargar el historial. Inténtalo de nuevo.':'Could not load the history. Try again.',
 'Las notas de cada versión se publican en español.':'Release notes are published in Spanish.',
 'En observación':'Under Observation','Versión estable':'Stable version','Estable':'Stable','Verificación pendiente':'Verification pending','Pendiente':'Pending','Verificando':'Verifying',
 'Incidencia detectada':'Issue detected','Incidencia':'Issue','Estabilidad de la versión':'Version stability','Cerrar':'Close','Período de observación':'Observation period',
 'Última verificación':'Last check','Próxima programada':'Next scheduled','Pruebas superadas':'Tests passed','Verificaciones de la versión':'Version checks','Sin resultados':'No results',
 'Incidencias':'Issues','Ninguna en esta versión.':'None in this version.','Sin resultados todavía.':'No results yet.','Versiones anteriores':'Earlier versions',
 'Estado de actualizaciones del sistema':'System update status','Completado':'Completed','Tiempo cumplido':'Time completed','Confirmando con el servidor…':'Confirming with the server…',
 'Falta completar las verificaciones':'Checks still to be completed','Período detenido por la incidencia':'Period stopped by the issue','El período empieza con la primera verificación correcta':'The period starts with the first successful check',
 'Pendiente de la próxima verificación para confirmar la estabilidad.':'Waiting for the next check to confirm stability.','Inicio · con la próxima verificación correcta':'Start · with the next successful check',
 'La última verificación tuvo una prueba no crítica fallida: la versión no se declara estable hasta que todas las pruebas se superen.':'The last check had a failed non-critical test: the version is not declared stable until all tests pass.',
 'Superó todas las verificaciones durante el período completo de seguimiento, sin incidencias.':'Passed all checks during the full observation period, with no issues.',
 'Se están ejecutando las verificaciones de esta versión en el servidor.':'The checks for this version are running on the server.',
 'Las comprobaciones del período de seguimiento siguen en curso.':'The observation period checks are still in progress.',
 'La última verificación detectó un fallo crítico. El seguimiento se reinicia con la siguiente verificación correcta.':'The last check detected a critical failure. Observation restarts with the next successful check.',
 'Esta versión todavía no tiene resultados de verificación.':'This version has no check results yet.','Menos de 1 min':'Less than 1 min',' · no crítica':' · non-critical',
 'Sin datos':'No data','Administrador':'Administrator','Técnico':'Technician','Foto de perfil':'Profile photo',
 // Tipos de versión
 'Corrección de errores':'Bug fixes','Nuevas funcionalidades compatibles':'New compatible features','Cambios importantes que rompen compatibilidad':'Breaking changes',
 'Primera versión registrada':'First registered version','Nuevas funcionalidades':'New features','Mejoras realizadas':'Improvements made','Errores corregidos':'Bugs fixed',
 'Actualizaciones de seguridad':'Security updates','Optimización del rendimiento':'Performance optimization'
};
const pl=(n,one,many)=>String(n)==='1'?one:many;
const MONTHS=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
const PATTERNS=[
 [/^Has alcanzado el máximo de (\d+) caracteres\.$/,m=>'You have reached the maximum of '+m[1]+' characters.'],
 [/^Usa al menos (\d+) caracteres\.$/,m=>'Use at least '+m[1]+' characters.'],
 [/^Usa una contraseña de (\d+) a (\d+) caracteres\.$/,m=>'Use a password of '+m[1]+' to '+m[2]+' characters.'],
 [/^Por seguridad, espera (\d+) segundos? antes de volver a intentarlo\.$/,m=>'For security, wait '+m[1]+' '+pl(m[1],'second','seconds')+' before trying again.'],
 [/^Publicada el (\d{2})\/(\d{2})\/(\d{4})$/,m=>'Published on '+m[2]+'/'+m[1]+'/'+m[3]],
 [/^Publicada el (.+)$/,m=>'Published on '+m[1]],
 [/^Cargando la versión v(.+)…$/,m=>'Loading version v'+m[1]+'…'],
 [/^Nueva versión v(.+) lista · recarga para usarla$/,m=>'New version v'+m[1]+' ready · reload to use it'],
 [/^Sistema actualizado · comprobado a las (.+)$/,m=>'System Up to Date · checked at '+m[1]],
 [/^Actualización importante en publicación: v(.+)$/,m=>'Important update being published: v'+m[1]],
 [/^Nueva versión en publicación: v(.+)$/,m=>'New version being published: v'+m[1]],
 [/^Última comprobación: (.*)$/,m=>'Last check: '+m[1].replace(' · compilación ',' · build ')],
 [/^Estabilidad de la versión (\S+): (.+)$/,m=>'Stability of version '+m[1]+': '+tr(m[2].split(' · ')[0])+(m[2].includes(' · ')?' · '+m[2].split(' · ').slice(1).map(part=>part.replace(/^última verificación /,'last check ')).join(' · '):'')],
 [/^Versión (\S+), estabilidad: (.+)\. Ver detalle$/,m=>'Version '+m[1]+', stability: '+tr(m[2])+'. View details'],
 [/^(.+) \(hay novedades sin leer\)$/,m=>tr(m[1])+' (unread news)'],
 [/^Pruebas de la última verificación \((\d+)\/(\d+)\)$/,m=>'Tests from the last check ('+m[1]+'/'+m[2]+')'],
 [/^Incidencias \((\d+)\)$/,m=>'Issues ('+m[1]+')'],
 [/^(\d+) de (\d+) verificaciones correctas(.*)$/,m=>m[1]+' of '+m[2]+' successful checks'+m[3].replace(/ (\d+) pendientes?$/,(x,n)=>' '+n+' pending').replace(' completas',' complete')],
 [/^Período de (\d+) h superado$/,m=>m[1]+' h period completed'],
 [/^restantes del período de (\d+) h$/,m=>'remaining of the '+m[1]+' h period'],
 [/^(\d+) de (\d+)$/,m=>m[1]+' of '+m[2]],
 [/^(\d+) · (\d+) correctas$/,m=>m[1]+' · '+m[2]+' successful'],
 [/^Inicio · (.+)$/,m=>'Start · '+m[1]],[/^Fin · (.+)$/,m=>'End · '+m[1]],
 [/^Período transcurrido: (\d+) %$/,m=>'Elapsed period: '+m[1]+'%'],
 [/^v(\S+) · publicada el (.+)$/,m=>'v'+m[1]+' · published on '+m[2]],
 [/^(\d+) verificaciones · (\d+) correctas(.*)$/,m=>m[1]+' checks · '+m[2]+' successful'+m[3].replace(' · alcanzó estabilidad',' · reached stability')],
 [/^(?:Faltan|Falta) (.+)\.$/,m=>m[0].replace(/^Faltan |^Falta /,'').replace(/ de seguimiento/,' of observation').replace(/ verificaciones correctas/,' successful checks').replace(/ verificación correcta/,' successful check').replace(/ y /,' and ').replace(/\.$/,'')+' remaining.'],
 [/^«Versión estable» exige (\d+) verificaciones correctas y (\d+) h de seguimiento sin incidencias\. .*$/,m=>'“Stable version” requires '+m[1]+' successful checks and '+m[2]+' h of observation without issues. The server checks three times a day (01:00, 09:00 and 17:00) and when this indicator is consulted. The tests only read information.']
];
function read(){try{const value=localStorage.getItem(KEY);if(LANGS[value])return value;}catch{}return DEFAULT;}
let lang=read();
function t(key,vars){const table=CATALOG[lang]||CATALOG[DEFAULT];let text=table[key]??CATALOG[DEFAULT][key]??key;if(vars)for(const[name,value]of Object.entries(vars))text=text.split('{'+name+'}').join(String(value));return text;}
function tr(text){
 if(lang===DEFAULT||typeof text!=='string'||!text)return text;
 if(Object.prototype.hasOwnProperty.call(PHRASES,text))return PHRASES[text];
 const check=/^✓ (.+)$/s.exec(text);if(check){const inner=tr(check[1]);return inner===check[1]?text:'✓ '+inner;}
 for(const[re,make]of PATTERNS){const m=re.exec(text);if(m)return make(m);}
 return text;
}
// Fija un texto (en español) en un nodo y lo mantiene traducido si después cambia el idioma.
function text(node,spanish){if(!node)return;if(spanish===undefined||spanish===null||spanish===''){delete node.dataset.i18nSrc;node.textContent=spanish??'';return;}node.dataset.i18nSrc=spanish;node.textContent=tr(spanish);}
function attr(node,name,spanish){if(!node)return;let map={};try{map=JSON.parse(node.dataset.i18nSrcAttr||'{}');}catch{}map[name]=spanish;node.dataset.i18nSrcAttr=JSON.stringify(map);node.setAttribute(name,tr(spanish));}
function apply(root){
 root=root||document;const html=document.documentElement;html.lang=LANGS[lang].html;html.dataset.lang=lang;
 for(const node of root.querySelectorAll('[data-i18n]')){const vars={};for(const[name,value]of Object.entries(node.dataset))if(name.startsWith('i18nVar'))vars[name.slice(7).toLowerCase()]=value;node.textContent=t(node.dataset.i18n,vars);}
 for(const node of root.querySelectorAll('[data-i18n-attr]'))for(const pair of node.dataset.i18nAttr.split(';')){const at=pair.indexOf(':');if(at>0)node.setAttribute(pair.slice(0,at).trim(),t(pair.slice(at+1).trim()));}
 for(const node of root.querySelectorAll('[data-i18n-src]'))node.textContent=tr(node.dataset.i18nSrc);
 for(const node of root.querySelectorAll('[data-i18n-src-attr]')){let map={};try{map=JSON.parse(node.dataset.i18nSrcAttr);}catch{}for(const[name,value]of Object.entries(map))node.setAttribute(name,tr(value));}
 for(const button of root.querySelectorAll('.lang-option[data-lang]')){const on=button.dataset.lang===lang;button.setAttribute('aria-pressed',String(on));button.classList.toggle('is-active',on);}
}
function set(next,options){
 if(!LANGS[next]||next===lang){if(LANGS[next]&&options?.account)remember(next,options);return lang;}
 lang=next;try{localStorage.setItem(KEY,next);}catch{}
 if(options?.account)remember(next,options);
 apply();document.dispatchEvent(new CustomEvent('i18n:change',{detail:{lang}}));return lang;
}
// Elección hecha sin sesión (pantalla de acceso): se marca para guardarla en la cuenta al entrar.
function remember(next,options){if(options.account==='pending'){try{localStorage.setItem(PENDING,next);}catch{}}}
function pending(){try{const value=localStorage.getItem(PENDING);return LANGS[value]?value:null;}catch{return null;}}
function clearPending(){try{localStorage.removeItem(PENDING);}catch{}}
function locale(){return LANGS[lang].html;}
window.i18n={get lang(){return lang;},LANGS,DEFAULT,t,tr,text,attr,apply,set,pending,clearPending,locale};
// Aplicar lo antes posible: con inglés, la tarjeta de acceso se oculta hasta traducirla (máximo 1,2 s, para no dejarla oculta si algo falla).
const html=document.documentElement;html.lang=LANGS[lang].html;html.dataset.lang=lang;
if(lang!==DEFAULT){html.classList.add('i18n-pending');setTimeout(()=>html.classList.remove('i18n-pending'),1200);}
const ready=()=>{try{apply();}finally{html.classList.remove('i18n-pending');}};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready,{once:true});else ready();
// Selector de idioma en las páginas de acceso (botones .lang-option[data-lang]).
document.addEventListener('click',event=>{const button=event.target.closest?.('.lang-option[data-lang]');if(!button||button.closest('[data-lang-account]'))return;set(button.dataset.lang,{account:'pending'});});
})();
