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
// 1.5.276 · ADI (chat flotante): textos fijos del asistente, sus estados, la voz, la consulta de reparación y la reserva en el chat, y los
// mensajes del servidor que muestra. Las respuestas de ADI no pasan por aquí: el servidor ya las redacta en el idioma elegido.
Object.assign(PHRASES,{
 // Encabezado, estados y controles
 'ADI · Asistente Inteligente':'ADI · Intelligent Assistant','ADI · Asistente de PC-DOCTOR':'ADI · PC-DOCTOR Assistant','Abrir asistente ADI':'Open ADI assistant',
 'ADI disponible':'ADI available','Preparando respuesta…':'Preparing response…','Contactando con soporte técnico…':'Contacting Technical Support…','Esperando a un asesor':'Waiting for an advisor',
 'Asesor conectado':'Advisor connected','Conversación finalizada':'Conversation ended','Sin conexión. Reintentando…':'Offline. Reconnecting…','Escuchando…':'Listening…','ADI está hablando':'ADI is speaking',
 'ADI · Disponible para ayudarte':'ADI · Available to help you','Sin conexión · reintentando':'Offline · reconnecting',
 'Solicitud enviada: esperando a soporte técnico':'Request sent: waiting for Technical Support','Contactando…':'Connecting…','Contactar soporte técnico':'Contact Technical Support',
 'Un asesor se unió a la conversación.':'An advisor joined the conversation.','El asesor finalizó la conversación. Si escribes de nuevo, ADI continuará atendiéndote.':'The advisor ended the conversation. If you write again, ADI will continue assisting you.',
 'ADI continúa con la conversación.':'ADI is continuing the conversation.','Asesor':'Advisor','Copiar respuesta':'Copy response','Copiado':'Copied',
 'No se pudo copiar. Selecciona el texto y cópialo manualmente.':'Could not copy. Select the text and copy it manually.','Conexión restablecida.':'Connection restored.','Sin conexión con ADI.':'No connection with ADI.',
 'Enviando…':'Sending…','ADI está procesando tu consulta':'ADI is processing your request','ADI está procesando tu consulta…':'ADI is processing your request…','Hoy':'Today','Ayer':'Yesterday',
 'Más opciones':'More options','Opciones':'Options','Minimizar el chat':'Minimize chat','Minimizar':'Minimize','Cerrar el chat':'Close chat','Efectos de sonido':'Sound effects','Animaciones de la esfera':'Orb animations',
 'Mensajes':'Messages','Consultas frecuentes':'Frequent questions','Acciones rápidas':'Quick actions','Escribe un mensaje':'Type a message','Escribe tu mensaje…':'Type your message…',
 'Enviar mensaje':'Send Message','Enviar (Enter)':'Send (Enter)','Comenzar conversación':'Start Conversation','Hablar con ADI':'Talk to ADI','Opciones sugeridas':'Suggested options',
 'Comprar licencias':'Buy Licenses','Servicios técnicos':'Technical Services','Agendar cita':'Book Appointment','Consultar reparación':'Check Repair Status','Hablar con un asesor':'Talk to an Advisor',
 '¿Qué licencias tienen disponibles?':'What licenses do you have available?','¿Qué servicios técnicos ofrecen?':'What technical services do you offer?','Hola, necesito hablar con un asesor.':'Hello, I need to speak with an advisor.',
 'Solicitud registrada. Te avisaremos aquí cuando un asesor tome la conversación.':'Request registered. We will let you know here when an advisor takes the conversation.',
 'El cliente solicita atención humana.':'The customer requests human assistance.','Cerrar el aviso de ADI':'Close the ADI notice','la Agenda de Citas':'the Appointment Scheduler',
 'Este es el chat de atención a clientes. La consulta de órdenes, presupuestos, citas y licencias con ADI está disponible para administración.':'This is the customer service chat. Querying orders, quotes, appointments and licenses with ADI is available to administrators.',
 // Saludos
 '¡Hola! Soy ADI, tu asistente virtual de PC-DOCTOR S.A. Estoy aquí para ayudarte con citas, servicios técnicos y consultas sobre tus reparaciones. ¿En qué puedo ayudarte hoy?':"Hello! I'm ADI, your virtual assistant at PC-DOCTOR S.A. I'm here to help you book appointments, explore our technical services, and check the status of your repairs. How can I assist you today?",
 'Hola, soy ADI, la asistente virtual de PC-DOCTOR S.A. Puedo orientarte sobre servicios, citas, horarios y el estado de tu orden.':"Hello, I'm ADI, the virtual assistant at PC-DOCTOR S.A. I can guide you on services, appointments, hours and the status of your order.",
 '¡Hola! Soy ADI, tu asistente virtual de PC-DOCTOR. ¿Necesitas ayuda? ¡Puedes hablar conmigo!':"Hi! I'm ADI, your virtual assistant at PC-DOCTOR. Need help? You can talk to me!",
 'Bienvenido a Órdenes Pro. Soy Adi, tu asistente virtual. ¿En qué puedo ayudarte?':"Welcome to Órdenes Pro. I'm Adi, your virtual assistant. How can I help you?",
 'Hola, bienvenido a PC-DOCTOR S.A. Soy ADI, tu asistente virtual de Órdenes Pro. Estoy aquí para ayudarte con tus órdenes de reparación, citas técnicas y consultas.':"Hello, welcome to PC-DOCTOR S.A. I'm ADI, your Órdenes Pro virtual assistant. I'm here to help you with your repair orders, technical appointments and questions.",
 'Así sonaré a esta velocidad.':'This is how I will sound at this speed.',
 // Voz
 'Detener la voz de ADI':'Stop ADI’s voice','Detener el micrófono':'Stop the microphone','Voz de ADI activada. Pulsa para silenciarla':'ADI voice on. Press to mute it',
 'Voz de ADI desactivada. Pulsa para que lea sus respuestas':'ADI voice off. Press to have responses read aloud','Voz de ADI':'ADI voice','Velocidad de voz':'Voice speed','Velocidad de la voz de ADI':'ADI voice speed',
 'Escuchar muestra de voz':'Play voice sample','femenina':'female','masculina':'male',
 'El micrófono está bloqueado. Permite su uso en el candado de la barra de direcciones y vuelve a intentarlo.':'The microphone is blocked. Allow it from the lock icon in the address bar and try again.',
 'No se encontró ningún micrófono conectado.':'No connected microphone was found.','No escuché nada. Pulsa el micrófono y habla de nuevo.':'I didn’t hear anything. Press the microphone and speak again.',
 'No hay conexión para el reconocimiento de voz. Revisa tu internet.':'There is no connection for speech recognition. Check your internet.',
 'Este navegador no permite hablar con ADI. Usa Chrome, Edge o Safari, o escribe tu mensaje.':'This browser does not support talking to ADI. Use Chrome, Edge or Safari, or type your message.',
 'ADI te está escuchando…':'ADI is listening…','No se pudo iniciar el micrófono. Inténtalo de nuevo.':'Could not start the microphone. Try again.',
 'Conversación por voz':'Voice conversation','Finalizar':'End','Silenciar el micrófono':'Mute the microphone','Activar el micrófono':'Unmute the microphone','Finalizar la conversación por voz':'End the voice conversation',
 'Micrófono en pausa':'Microphone paused','ADI está hablando · habla para interrumpirla':'ADI is speaking · speak to interrupt','Procesando…':'Processing…','Te escucho…':'I’m listening…',
 'Escuchando · habla cuando quieras':'Listening · speak whenever you like','Puedes seguir escribiendo.':'You can keep typing.',
 'El micrófono está bloqueado. Permite su uso en el candado de la barra de direcciones para conversar con ADI.':'The microphone is blocked. Allow it from the lock icon in the address bar to talk with ADI.',
 'No se pudo usar el micrófono. Puedes escribir tu mensaje.':'Could not use the microphone. You can type your message.',
 // Consulta de reparación
 'Escribe el número de orden de tu comprobante. Enviaremos un código de verificación al correo registrado en la orden.':'Enter the order number from your receipt. We will send a verification code to the email registered on the order.',
 'Enviar código':'Send Code','Número de orden':'Order number','Escribe el código de 6 dígitos.':'Enter the 6-digit code.','Escribe el número de orden.':'Enter the order number.','Verificando…':'Verifying…',
 'Enviando el código…':'Sending the code…','Código de 6 dígitos':'6-digit code','Código de verificación':'Verification code','Verificar código':'Verify Code',
 'Pendiente':'Pending','En diagnóstico':'In diagnosis','Diagnóstico en proceso':'Diagnosis in progress','En reparación':'In repair','Listo para entrega':'Ready for pickup','Entregado':'Delivered',
 'En espera de entrega':'Awaiting pickup','Esperando respuesta del cliente':'Waiting for customer response','Esperando repuesto':'Waiting for part','Aprobación de presupuesto':'Quote approval',
 'Pruebas técnicas y control de calidad':'Technical testing and quality control','En revisión por falla recurrente':'Under review for a recurring fault',
 // Reserva en el chat
 'Reservar una cita':'Book an Appointment','Cargando servicios y horarios…':'Loading services and times…','Puedes reservar en /citas o pedir un asesor.':'You can book at /citas or ask for an advisor.',
 'Selecciona el servicio':'Select the service','Selecciona el tipo de licencia':'Select the license type','Elige servicio y fecha':'Choose service and date','Cédula':'ID card (cédula)','Pasaporte':'Passport',
 'Selecciona el equipo':'Select the device','Tipo de licencia':'License type','Servicio':'Service','Fecha':'Date','Hora disponible':'Available time','Nombre y apellidos':'Full name','Identificación':'Identification',
 'Número':'Number','Teléfono':'Phone','Correo (opcional)':'Email (optional)','Tipo de equipo':'Device type','Marca y modelo (opcional)':'Brand and model (optional)','Motivo o problema':'Reason or issue',
 'Observaciones (opcional)':'Notes (optional)','He leído el':'I have read the','y autorizo el uso de estos datos para gestionar esta cita.':'and authorize the use of this data to manage this appointment.',
 'aviso de privacidad':'privacy notice','Acepto expresamente los':'I expressly accept the','términos y condiciones del servicio':'terms and conditions of service','vigentes.':'currently in force.',
 'Autorizo comunicaciones sobre esta cita por correo o WhatsApp (opcional).':'I authorize communications about this appointment by email or WhatsApp (optional).',
 'Últimos 4 dígitos de tu identificación':'Last 4 digits of your ID',
 'No hay condiciones vigentes publicadas: la cita no puede confirmarse en línea ahora. Pide un asesor.':'There are no published terms in force: the appointment cannot be confirmed online right now. Ask for an advisor.',
 'Atrás':'Back','Continuar':'Continue','Cancelar':'Cancel','Cerrar':'Close','Consultando horarios…':'Checking times…','Selecciona la hora':'Select the time','Sin horas libres ese día':'No open times that day',
 'Modalidad: retiro del equipo en el taller.':'Mode: device pickup at the shop.','Modalidad: atención presencial en el taller. Si ya eres cliente, te reconocemos por tu identificación.':'Mode: in-person service at the shop. If you are already a customer, we recognize you by your ID.',
 'el servicio':'the service','el tipo de licencia':'the license type','la fecha':'the date','la hora':'the time','tu nombre y apellidos':'your full name','tu identificación':'your ID','tu teléfono':'your phone',
 'el tipo de equipo':'the device type','el motivo':'the reason','Servicio y horario':'Service and time','Tus datos':'Your details','Confirmación':'Confirmation','Confirmar cita':'Confirm Appointment',
 'Fecha y hora':'Date and time','Cliente':'Customer','Contacto':'Contact','Equipo':'Device','Motivo':'Reason','Reserva cancelada. No se registró ninguna cita.':'Booking cancelled. No appointment was registered.',
 'Para confirmar, acepta el aviso de privacidad y los términos y condiciones.':'To confirm, accept the privacy notice and the terms and conditions.','Escribe los últimos 4 dígitos de tu identificación.':'Enter the last 4 digits of your ID.',
 'Guardando tu cita…':'Saving your appointment…','Guarda tu código: lo necesitarás para consultar o cambiar la cita.':'Save your code: you will need it to check or change the appointment.',
 'El taller confirmará tu solicitud. Guarda tu código.':'The shop will confirm your request. Save your code.','No se registró la cita.':'The appointment was not registered.',
 // Servicios de la agenda, tipos de equipo y licencias (valores de fábrica; los que administración cree después se muestran tal como se escribieron)
 'Diagnóstico técnico':'Technical diagnosis','Reparación de portátiles':'Laptop repair','Reparación de computadoras':'Computer repair','Mantenimiento preventivo':'Preventive maintenance',
 'Mantenimiento correctivo':'Corrective maintenance','Programación y recuperación de BIOS':'BIOS programming and recovery','Reparación electrónica':'Electronic repair','Servicio para impresoras':'Printer service',
 'Otros servicios técnicos':'Other technical services','Retiro de Equipos':'Equipment pickup','Servicio de Administración Remota':'Remote administration service','Compra de licencia de software':'Software license purchase',
 'Instalación y configuración de antivirus':'Antivirus installation and setup','Eliminación de virus y malware':'Virus and malware removal','Recuperación y respaldo de datos':'Data recovery and backup',
 'Cambio de pantallas':'Screen replacement','Reparación de bisagras':'Hinge repair','Configuración de redes y Wi-Fi':'Network and Wi-Fi setup','Instalación de Windows y otros sistemas operativos':'Windows and operating system installation',
 'Mantenimiento de consolas PlayStation':'PlayStation console maintenance','Actualización de BIOS':'BIOS update','Recuperación de contraseña de BIOS':'BIOS password recovery','Reparación de BIOS corrupta':'Corrupted BIOS repair','Desbloqueo de BIOS':'BIOS unlock',
 'Portátil (Laptop)':'Laptop','Portátil Gaming':'Gaming laptop','Impresora':'Printer','PC de escritorio':'Desktop PC','Consolas':'Consoles','Celular':'Cell phone','Router / equipo de red':'Router / network device',
 'Servidor':'Server','Teclado':'Keyboard','Disco duro (HDD)':'Hard drive (HDD)','Unidad SSD':'SSD drive','Otro equipo':'Other device',
 'Windows 10 y Windows 11':'Windows 10 and Windows 11','Antivirus Kaspersky, ESET NOD32, McAfee, Norton y otros':'Antivirus Kaspersky, ESET NOD32, McAfee, Norton and others','Otras licencias de software':'Other software licenses',
 // Mensajes del servidor que muestra el chat
 'Sin conexión. Tu mensaje sigue en el editor.':'Offline. Your message is still in the editor.','No se pudo conectar con ADI. Inténtalo de nuevo.':'Could not connect to ADI. Try again.',
 'No se pudo enviar el mensaje.':'Unable to send message.','Espera un momento antes de enviar otro mensaje.':'Please wait a moment before sending another message.',
 'Escribe un mensaje de hasta 3000 caracteres.':'Write a message of up to 3000 characters.','Inicia una conversación con ADI primero.':'Start a conversation with ADI first.',
 'Escribe el número de orden que consta en tu comprobante.':'Enter the order number shown on your receipt.','Demasiadas solicitudes de código. Espera unos minutos e inténtalo de nuevo.':'Too many code requests. Wait a few minutes and try again.',
 'La consulta en línea no está disponible en este momento. Puedes solicitar un asesor.':'Online lookup is not available right now. You can request an advisor.',
 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.':'Too many attempts. Wait a few minutes and try again.','El código no es correcto o ya caducó. Revisa el correo o solicita uno nuevo.':'The code is incorrect or has expired. Check your email or request a new one.',
 'Demasiadas solicitudes de voz. Espera unos minutos.':'Too many voice requests. Wait a few minutes.','La voz natural no está disponible ahora. ADI usa la voz del navegador.':'Natural voice is not available right now. ADI is using the browser voice.',
 'La grabación es demasiado larga. Habla en frases más cortas.':'The recording is too long. Speak in shorter sentences.','Grabación no válida.':'Invalid recording.',
 'OpenAI alcanzó su límite de uso. ADI usa la voz del navegador por ahora.':'The voice service reached its usage limit. ADI is using the browser voice for now.',
 'No se pudo conectar con OpenAI. ADI usa la voz del navegador por ahora.':'Could not connect to the voice service. ADI is using the browser voice for now.',
 'Acepta los términos y condiciones para confirmar la cita.':'Accept the terms and conditions to confirm the appointment.','Confirma el aviso de privacidad para registrar la cita.':'Confirm the privacy notice to register the appointment.',
 'Describe brevemente la falla (3 a 1000 caracteres).':'Briefly describe the fault (3 to 1000 characters).','El RUC debe contener exactamente 13 dígitos.':'The RUC must contain exactly 13 digits.',
 'Ese horario no está disponible. Consulta otros espacios.':'That time is not available. Check other times.','Indica el nombre completo (2 a 150 caracteres).':'Enter the full name (2 to 150 characters).',
 'Ingresa tu nombre y apellidos.':'Enter your full name.','Ingresa tu número de identificación para continuar.':'Enter your ID number to continue.','Ingresa un correo electrónico válido.':'Enter a valid email address.',
 'Ingresa un número de pasaporte válido: de 5 a 20 letras y números, sin espacios.':'Enter a valid passport number: 5 to 20 letters and numbers, no spaces.',
 'Las condiciones se actualizaron. Revisa la versión vigente y vuelve a aceptarla.':'The terms were updated. Review the current version and accept it again.',
 'No hay condiciones del servicio vigentes: la cita no puede autorizarse en este momento.':'There are no service terms in force: the appointment cannot be authorized right now.',
 'Revisa la longitud de marca, modelo u observaciones.':'Check the length of brand, model or notes.','Selecciona el tipo de equipo.':'Select the device type.','Selecciona el tipo de identificación.':'Select the ID type.',
 'Selecciona el tipo de licencia.':'Select the license type.','Selecciona si autorizas comunicaciones de la cita.':'Select whether you authorize appointment communications.',
 'Reintentar':'Retry','Orden':'Order','Estado':'Status','Ingreso':'Received','Entrega estimada':'Estimated delivery','Seguimiento completo':'Full tracking','Cita registrada':'Appointment registered',
 'Cita confirmada correctamente. Su aceptación ha sido registrada con fecha, hora e identificador de autorización.':'Appointment confirmed successfully. Your acceptance has been recorded with date, time and authorization ID.',
 'Solicitud registrada. Su aceptación ha sido registrada con fecha, hora e identificador de autorización; le avisaremos cuando la cita quede confirmada.':'Request registered. Your acceptance has been recorded with date, time and authorization ID; we will let you know when the appointment is confirmed.'
});
const pl=(n,one,many)=>String(n)==='1'?one:many;
const MONTHS=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
const PATTERNS=[
 // ADI (1.5.276)
 [/^Si el número corresponde a una orden con correo registrado, acabamos de enviar un código de 6 dígitos a ese correo\. Caduca en (\d+) minutos\.$/,m=>'If the number matches an order with a registered email, we just sent a 6-digit code to that email. It expires in '+m[1]+' minutes.'],
 [/^Ese día es (.+)\.$/,m=>'That day is '+m[1]+'.'],
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
// 1.5.276 · Otras pestañas de las páginas públicas (acceso, recuperación) siguen el idioma elegido en cualquiera de ellas, sin recargar.
// En el panel manda el idioma guardado en la cuenta, por eso allí no se sigue el cambio de otra pestaña.
if(typeof addEventListener==='function')addEventListener('storage',event=>{if(event.key!==KEY||!LANGS[event.newValue]||event.newValue===lang||document.body?.dataset.page==='dashboard')return;set(event.newValue);});
})();
