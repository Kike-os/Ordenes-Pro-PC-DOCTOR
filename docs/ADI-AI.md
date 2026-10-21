# Adi AI — asistencia de redacción (Fase 1) — 11/10/2026

## Qué hace

Botón **Mejorar con Adi** junto a los campos de texto de las órdenes: falla reportada, observaciones de recepción e inspección física (nueva orden); descripción de trabajo, observaciones del técnico, hallazgos, recomendaciones y comentario del historial (edición de la orden); y el comentario de seguimiento.

El técnico elige el tipo de mejora (ortografía, redacción, redacción técnica, simplificar, explicación para el cliente), ve la sugerencia con los cambios resaltados y decide **Aplicar mejora**, **Regenerar** o **Cancelar**. Nada se reemplaza sin su aceptación y «Deshacer» recupera el texto original.

## Estado real

- **Proveedor de IA: no configurado.** No hay ninguna clave en el servidor, así que hoy el botón solo explica que falta la conexión. El servicio, las rutas y la interfaz están probados con un proveedor simulado; falta la prueba con un proveedor real.
- Para activarlo: definir `ANTHROPIC_API_KEY` (Claude; modelo por defecto `claude-opus-5-5`, ajustable con `ADI_MODEL`) u `OPENAI_API_KEY` en Vercel y en `local/.env`. La clave nunca llega al navegador.
- Canales: chat web activo (respuestas por reglas); correo según Mail Pro; WhatsApp sin conexión oficial, pendiente.

## Protecciones

- Al proveedor solo viaja el párrafo y el nombre del campo; ningún dato del cliente ni de la orden.
- El texto se envía como dato entre etiquetas y el modelo tiene instrucción de no obedecer lo que contenga.
- Se comprueba que series, códigos, medidas, fechas e importes del original sigan idénticos; si falta alguno, la interfaz lo advierte.
- Solo administración y técnicos; 60 mejoras por usuario y hora; 4000 caracteres por consulta; 25 s de espera.
- Cada uso se registra en `adi_actions` (usuario, tipo, modelo, tokens) sin guardar el texto.
- Se desactiva en Configuración → «Adi — asistencia de redacción».

## Pendiente (fases siguientes)

Fase 2: Mail Pro y mensajes a clientes. Fase 3: respuestas sugeridas con base de conocimiento. Fase 4: atención automática supervisada. Ninguna está implementada; ningún mensaje se envía automáticamente.

## Archivos

`local/adi_ai.py`, rutas `/api/adi/status`, `/api/adi/write`, `/api/adi/settings` en `local/app.py`, `attachAdi` en `local/static/app.js`, pruebas en `local/tests/test_adi_ai.py`.


Desde la 1.5.46 el servidor acepta también la variable `OPEN_API_KEY` (nombre mal escrito frecuente) como clave de OpenAI. El nombre correcto sigue siendo `OPENAI_API_KEY`.

## Asistente ADI en todo el sistema (1.5.48)

- `attachAdi(area, campo, opciones)` es el componente único. Con un `<textarea>` basta; para otros editores se pasan `get`, `set` y `anchor` (así funciona en el cuerpo del correo de Mail Pro).
- `initAdiEverywhere()` observa la página y añade el botón compacto «Adi» a cada área de texto visible, sin tocar cada módulo. Se excluyen el chat de Adi, la respuesta del Centro de Atención, campos de solo lectura y cualquier elemento con `data-no-adi`.
- Panel: encabezado «Asistente ADI», cuadrícula de herramientas, «Aplicar mejora» con indicador de proceso, vista previa con cambios resaltados y «Aceptar cambio», «Regenerar» o «Descartar». El texto original no cambia hasta aceptar; hay «Deshacer».
- Toda consulta pasa por `/api/adi/write` con sesión y CSRF; la clave vive solo en el servidor. Si el proveedor falla se muestra el error real y el texto no se modifica.

## Corrección automática (1.5.50)

- Dos segundos después de dejar de escribir en un área de texto, Adi revisa la ortografía (`/api/adi/write` con `auto: true`; el servidor fuerza el modo «Corregir ortografía»).
- Se aplica sola únicamente una corrección **simple** (`adi_ai.is_simple`): las mismas palabras en el mismo orden, con tildes, mayúsculas, puntuación o una o dos letras corregidas, y sin alterar datos técnicos. El cursor no se mueve y aparece «Texto mejorado · Deshacer».
- Si la propuesta añade, quita o sustituye palabras, no se aplica: la estrellita queda en ámbar y al pulsarla se abre la vista previa para aceptar o descartar.
- Ahorro de consultas: no se envía si el texto no cambió desde la última revisión, si tiene menos de 12 caracteres o más de 1500, ni mientras el panel está abierto. Límite propio de 240 por usuario y hora.
- Una respuesta que llega después de que el texto cambió se descarta.
- No actúa sobre las descripciones de autorizaciones del cliente (allí Adi solo trabaja a petición) ni sobre campos que no son áreas de texto (contraseñas, identificadores, cantidades, precios, códigos).
- Se desactiva desde el propio panel de Adi («Corregir la ortografía automáticamente…»); es una preferencia de cada navegador.
- La redacción profesional (técnica, para el cliente, etc.) nunca es automática: siempre pasa por la vista previa.

## Robustez de «Aplicar mejora» (1.5.52)

- La petición a Adi tiene un tiempo límite de 20 s en el navegador (15 s la automática) y 17 s en el servidor: el botón nunca queda esperando sin fin. Al agotarse se muestra el motivo y «Reintentar»; con errores de autenticación, configuración, saldo o límite no se ofrece reintentar.
- Un solo envío por pulsación; al pedir una mejora a mano se anula la corrección automática en curso y su respuesta se descarta.
- El estado de Adi se consulta una vez por página (antes, una vez por cada campo de texto).
- El panel va en el flujo del formulario (antes heredaba la posición absoluta y el alto fijo del chat flotante) y mide 380 px de ancho con desplazamiento interno.
- Diagnóstico: los errores de JavaScript y los inicios y fallos de las consultas a Adi se anotan en el registro del servidor (`client-log`), con tipo, mensaje y duración, nunca con el texto escrito.

## Voz de ADI en el asistente flotante (1.5.56)

- **Entrada:** botón de micrófono junto al campo de mensaje. Usa el reconocimiento de voz del navegador (`SpeechRecognition`, disponible en Chrome, Edge y Safari; no en Firefox) en español (`es-EC`). El audio lo procesa el navegador; al servidor llega solo el texto reconocido, como un mensaje escrito.
- **Salida:** las respuestas de ADI y del asesor se leen con la síntesis de voz del dispositivo, eligiendo una voz femenina en español cuando existe (Sabina, Helena, Paulina, Dalia, Elena…). La calidad y el timbre dependen de las voces instaladas en cada equipo.
- Interruptor de voz en el encabezado del chat (preferencia de cada navegador). Hablar por el micrófono la activa la primera vez.
- Estados reales en la esfera: escuchando (anillos cian), procesando (pulsos) y hablando (onda violeta).
- Mensajes claros si el micrófono está bloqueado, no hay micrófono, no se escuchó nada, falla la red o el navegador no admite dictado.
- El nombre del asistente se muestra siempre como «ADI».
- Requiere HTTPS (producción lo cumple) y el permiso de micrófono del navegador.

## Corrección automática como propuesta (1.5.60)

Sustituye al comportamiento de la 1.5.50, que aplicaba sola las correcciones simples.

- 1,5 s después de dejar de escribir, ADI revisa la ortografía del campo y muestra «Analizando texto…».
- Si hay cambios, aparece bajo el campo la propuesta con las palabras cambiadas resaltadas y los botones «Aceptar corrección» y «Descartar». El texto del campo no se toca hasta aceptar; después se puede deshacer.
- Si se sigue escribiendo, la revisión en curso se cancela y la propuesta anterior se retira: una respuesta antigua nunca pisa texto nuevo.
- No se repite la consulta para un texto ya revisado, aceptado o descartado.
- Si la revisión falla se indica el motivo junto al botón y el texto queda como estaba.
- Abrir «Mejorar con ADI» retira la propuesta automática; «Cancelar» y la X del asistente solo cierran el asistente.

## Corrección ortográfica automática sin ventanas (1.5.73)

Sustituye a la propuesta con «Aceptar / Descartar» de la 1.5.60, a petición de PC-DOCTOR S.A.

- 1,5 s después de dejar de escribir se revisa la ortografía (tildes, puntuación, errores básicos) y la corrección se aplica sola. Indicador: «ADI revisando…», «Ortografía corregida · Deshacer» o «No se pudo revisar el texto».
- El cursor vuelve a la misma palabra en la que estaba. «Deshacer» recupera el texto anterior mientras no se haya seguido escribiendo.
- Si se escribe durante la revisión, la petición se cancela y su respuesta se descarta. No se repite la consulta de un texto ya revisado.
- Si la respuesta alterase cifras, códigos, series u otros datos protegidos, no se aplica nada.
- Funciona en todas las áreas de texto libre (componente global). No actúa en los textos de autorización del cliente ni en correos que citan a otra persona (desde la 1.5.87 sí corrige la respuesta del chat de atención en vivo, sin enviar nada por sí sola); en el editor de correo se aplica al salir del campo. Los campos estructurados (serie, identificación, teléfono, correo, contraseñas) no son áreas de texto y nunca se envían.
- Se activa o desactiva con «Corrección ortográfica automática» en el panel de ADI; se recuerda en ese navegador.
- Mejorar redacción, simplificar y las demás herramientas siguen mostrando la vista previa y pidiendo aceptación.

## Bloqueo de «Aplicar mejora» (1.5.90)

**Causa encontrada y reproducida:** toda petición que escribe abre una transacción exclusiva en la base. La de ADI (`/api/adi/write`) anotaba el límite de uso y, sin cerrar la transacción, esperaba la respuesta de OpenAI. Mientras tanto ninguna otra escritura podía avanzar: ni otra petición de ADI del mismo usuario (la revisión automática arranca 1,5 s después de escribir, así que casi siempre había una en curso al pulsar «Aplicar mejora»), ni guardar un seguimiento, ni cambiar un estado. Lo mismo ocurría con el chat público de ADI y con las operaciones de correo.

**Corrección:** se confirma la transacción antes de llamar a la IA o al servidor de correo. Prueba `test_adi_lock.py`: con el código anterior la base queda bloqueada mientras la IA «piensa»; con la corrección, otra escritura entra de inmediato.

**Protecciones añadidas:** un vigilante apaga el indicador a los 26 s pase lo que pase y ofrece reintentar; el estado «ADI revisando…» ya no puede quedarse encendido si el texto cambia sin aviso del navegador; cada paso del flujo manual se anota (sin el texto del usuario) en el registro y en la tabla `client_diagnostics` (migración 036, 14 días), para poder investigarlo aunque el registro de Vercel haya caducado.

## Esfera flotante de ADI (aspecto)

- Esfera circular rosa pastel con degradado, brillo y ondas de energía interiores; respira suavemente en reposo. Solo cambia el aspecto de ADI: el resto de la plataforma conserva su identidad.
- Estados ligados a señales reales: **disponible** (respiración), **escuchando** (anillos mientras el reconocimiento de voz está activo, más intensos cuando el navegador detecta voz: `speechstart`/`speechend`), **procesando** (ondas rápidas mientras hay una petición en curso), **hablando** (pulso mientras la síntesis de voz reproduce) y **error** (aro rojo discreto junto al mensaje en el chat).
- Voz: se elige una voz femenina en español del dispositivo, con preferencia por la colombiana; depende de las voces instaladas en cada equipo o teléfono. En el menú «⋯» se puede elegir la voz y pulsar «Escuchar muestra de voz». Saludo de muestra: «Bienvenido a Órdenes Pro. Soy Adi, tu asistente virtual. ¿En qué puedo ayudarte?». La voz nunca se reproduce sola.
- Ventana: detalles rosados, «Comenzar conversación» mientras no hay mensajes, minimizar y cerrar; el historial se conserva.

## Voz de ADI: motor, velocidad y pronunciación

- **Motor**: la síntesis de voz del navegador (Web Speech API). No se usa ningún servicio de voz en la nube; la voz, su acento y su naturalidad dependen de las voces instaladas en cada equipo o teléfono. Se elige una femenina en español, con preferencia por la colombiana.
- **Velocidad**: 1,12× por defecto, ajustable de 0,80× a 1,50× en el menú «⋯» del chat (y en los ajustes de voz del asistente interno). Se guarda en el navegador.
- **Pronunciación**: el texto que se lee pasa por una representación fonética independiente: «PC-DOCTOR S.A.» se pronuncia «Pe ce dóctor, ese a», «ADI» como «Adi» y los números de orden como «orden N». Lo visible, los documentos y los registros conservan el nombre oficial.
- **Fluidez**: la respuesta se lee en cuanto llega con el envío del mensaje (sin una segunda consulta previa) y por frases, de modo que la voz empieza de inmediato y los navegadores no cortan respuestas largas. Se eliminan símbolos que generan pausas.
- **Una sola voz a la vez**: cada lectura cancela la anterior. Mientras ADI habla, el botón de voz la interrumpe sin desactivar la lectura.
- **Muestra**: «Escuchar muestra de voz» lee «Hola, bienvenido a PC-DOCTOR S.A. Soy ADI, tu asistente virtual de Órdenes Pro. Estoy aquí para ayudarte con tus órdenes de reparación, citas técnicas y consultas.»
- **Límites del motor**: no hay audio progresivo del proveedor de IA (la respuesta de texto llega completa, no en flujo) ni control fino de entonación; una voz idéntica en todos los dispositivos requeriría un servicio de voz externo.

## Esfera premium (1.5.98)

- Esfera de cristal rosa (rosa pastel, perlado y fucsia suave) con reflejos, las letras «ADI» centradas y un anillo exterior luminoso de giro lento. 62 px en escritorio y 54 px en móvil; toda en CSS, sin imágenes.
- **Escuchando**: en computadoras, un analizador de audio mide el volumen real del micrófono mientras el reconocimiento escucha y los anillos crecen con él (`--adi-level`). En teléfonos no se abre un segundo uso del micrófono, porque interrumpe el reconocimiento de voz: allí los anillos responden al inicio y fin de voz que informa el navegador.
- **Procesando**: partículas en órbita y anillo más rápido mientras hay una petición en curso.
- **Hablando**: pulso continuo y un latido por cada palabra que informa el motor de voz (`boundary`), cuando el motor lo admite.
- **Desconectada**: sin indicador verde, esfera apagada y sin movimiento. El indicador refleja el estado real de la conexión con el servidor.
- Ventana «ADI · Asistente Inteligente» con botón propio para detener la voz, visible solo mientras ADI habla.
- En equipos modestos (2 núcleos o 2 GB) y con «movimiento reducido» se desactivan desenfoques, ondas y giros.

### Brillo y profundidad (1.5.99)

Halo rosado difuminado que respira con la esfera, cristal con reflejos superior e inferior y canto de luz, dos anillos finos que giran en sentidos opuestos, puntos de energía en órbita lenta, texto «ADI» con resplandor leve e indicador verde con borde oscuro. Al escuchar, el brillo acompaña al volumen medido; al hablar, el halo pulsa. Todo en CSS; en equipos modestos y con movimiento reducido se desactivan halo animado, anillo exterior y puntos.

### Cristal realista y efectos de sonido (1.5.100)

- **Material**: luz principal arriba a la izquierda, bordes más oscuros (efecto Fresnel), neblina luminosa interior, cáustica clara en la parte inferior, brillo especular curvo con un punto secundario, filo fino y sombra de apoyo bajo la esfera. El texto «ADI» queda bajo los reflejos, dentro del cristal. Todo en CSS.
- **Sonidos** (Web Audio, sin archivos ni licencias): al abrir, tono de cristal ascendente (≈0,4 s) con destello y expansión del halo; al cerrar o minimizar, tono descendente breve; al activar el micrófono, señal suave; respuesta lista, señal delicada solo si la voz no va a leerla; error, tono grave. Procesar no suena.
- **Reglas**: se activan o desactivan con «Efectos de sonido» en el menú «⋯» (guardado en el navegador); volumen bajo; un efecto a la vez (el nuevo apaga al anterior); callan mientras ADI habla; el audio solo se inicia tras una interacción real y nunca al cargar la página. Si el navegador no ofrece Web Audio, simplemente no suenan.

## Esfera 3D en WebGL (1.5.103)

- **Motor**: `local/static/adi-orb.js`, un sombreador WebGL propio sin dependencias. Cada píxel traza un rayo contra una esfera de cristal: normal, reflejo de un entorno de estudio que gira despacio, efecto Fresnel, dos brillos especulares, cáustica y refracción; dentro, el rayo recorre una nube de energía con giro propio, un núcleo y cinco partículas en órbita. Se eligió un sombreador propio en lugar de Three.js porque esa biblioteca pesa cientos de KB para un elemento de 62 px y la política de seguridad solo admite guiones propios.
- **Estados reales**: en espera (giro lento y respiración); al tocarla (rebote elástico del radio y destello, con el sonido); escuchando (el núcleo vibra con el volumen medido del micrófono en computadoras; en teléfonos, con el inicio y fin de voz que informa el navegador); procesando (las partículas aceleran y se concentran en el centro); hablando (ondas desde el centro y deformación suave, con una envolvente que sube en cada palabra que informa el motor de voz); sin conexión o error (esfera atenuada y desaturada, indicador hueco o rojo).
- **Límite conocido**: el audio de la síntesis de voz del navegador no se puede analizar, así que al hablar no hay análisis de amplitud real: la animación sigue los eventos de palabra del motor.
- **Indicador de conexión**: punto pequeño (9 px) con el estado real; el título de la esfera dice el estado.
- **Rendimiento**: lienzo de 1,68 veces la esfera, hasta el doble de densidad de píxeles; menos resolución y pasos en teléfonos y equipos modestos, y reducción automática si el dibujo va lento; unos 30 cuadros por segundo en reposo y más al reaccionar; se detiene con la pestaña oculta; con «movimiento reducido» apenas se redibuja.
- **Alternativa**: sin WebGL, o con dibujo por software, queda la esfera CSS (sin anillos decorativos). `localStorage['ordenes-pro:adi-3d']` admite `on` (forzar) y `off` (desactivar) para diagnóstico.
- **Recursos**: al salir de la página se cancela el dibujo y se liberan programa, búfer y contexto; el medidor del micrófono cierra su pista y su contexto de audio al terminar de escuchar.
- **Acceso en teléfonos**: la esfera se coloca arriba a la derecha para no tapar el botón «Iniciar sesión».

### Cómo comprobar cada estado

1. **Espera**: abrir cualquier página con ADI y observar el giro interior.
2. **Toque**: pulsar la esfera (rebote, destello y sonido si «Efectos de sonido» está activo).
3. **Escucha**: abrir el chat y pulsar el micrófono; hablar y ver vibrar el núcleo.
4. **Procesamiento**: enviar un mensaje; mientras llega la respuesta las partículas se concentran.
5. **Habla**: activar la voz (altavoz) y enviar un mensaje; durante la lectura salen ondas del centro. El botón cuadrado la detiene.
6. **Sin conexión**: desconectar la red unos segundos con el chat abierto.

## ADI siempre en espera al cargar (1.5.104)

Al abrir, recargar o cambiar de sección, ADI no se abre, no habla, no suena y no enciende el micrófono: solo se muestra la esfera. Se retiraron la apertura automática junto al acceso, la opción «Abrir el chat al entrar» y la reapertura automática tras cerrarse un diálogo. Solo se guardan preferencias (efectos de sonido, voz y velocidad, animaciones de la esfera), nunca el estado de la conversación, la escucha o la voz. Hay una sola instancia por página y cerrar o minimizar detiene la voz y el micrófono.

## Esfera viva y ventana premium (1.5.105)

- **Sombreador ampliado** (`adi-orb.js`): filamentos de energía (crestas de ruido deformado que circulan y cambian de dirección con giros de frecuencias que no coinciden), núcleo cuya forma varía con la dirección, ondas que perturban la normal de la superficie y, con ella, los reflejos; respiración asimétrica con dos ritmos, levitación mínima, onda expansiva al toque, resplandor moderado y reacción suave al cursor en escritorio (luz, reflejos y centro del núcleo). Sigue siendo un sombreador propio sin dependencias; Three.js y sus materiales físicos no se incorporaron por peso y por la política de guiones propios, y el proyecto no usa React.
- **Tamaño**: 68 px en escritorio y 56 px en móvil.
- **Ventana**: 410 px de ancho y hasta 580 px de alto; encabezado «ADI · Asistente Inteligente» con una esfera 3D pequeña que solo existe mientras la ventana está abierta; estado real bajo el título; mensajes a 14 px con burbujas distintas para la persona y para ADI; hora con fecha completa al pasar el cursor; botón para copiar cada respuesta; «ADI está procesando tu consulta…» mientras hay una petición; aviso de desconexión con «Reintentar».
- **Desplazamiento**: baja al último mensaje solo si la persona ya estaba al final o acaba de enviar.
- **Controles**: campo adaptable (Enter envía, Mayús+Enter añade línea), detener voz (visible solo mientras habla), micrófono y enviar.
- **«Contactar soporte técnico»** sustituye a «Solicitar un asesor» y usa el mismo relevo real al Centro de Atención.
- **Límite que se mantiene**: el audio de la voz del navegador no puede analizarse; al hablar, la esfera sigue los eventos de palabra del motor, no la amplitud real.

## Auditoría del asistente de redacción (1.5.111)

**Arquitectura.** Hay un único componente, `attachAdi`, y `initAdiEverywhere` lo engancha a cualquier área de texto que aparezca en el panel. El correo usa el mismo componente con su editor propio. Toda petición va a `/api/adi/write` en el servidor; la clave del proveedor nunca llega al navegador.

**Ventanas revisadas** (con una IA simulada en base temporal, en 1440 y 390 px): nueva orden (estado físico, falla reportada, diagnóstico inicial, observaciones, notas técnicas, detalle de acceso y de operaciones sobre datos), seguimiento, edición de la orden (falla, notas internas, hallazgos, recomendaciones, comentario), mensaje por WhatsApp, nueva cita, condiciones (texto completo y compacto) y «Nuevo mensaje» de correo. En las 16 áreas funcionaron las cinco herramientas, la vista previa, «Aplicar cambios» y la conservación de series y mediciones.

**Errores encontrados y corregidos.**
- En «Nuevo mensaje» la parte inferior del panel (la casilla de corrección automática y los botones) quedaba tapada por la barra fija «Descartar · Guardar borrador · Enviar». Ahora el panel se coloca por encima de esa barra, en escritorio y en móvil.
- El panel tenía un ancho fijo de 380 px y unos 310 px de alto. Ahora usa el ancho del campo (hasta 680 px), con las herramientas en hasta cuatro columnas (dos en móvil) y unos 233 px de alto.
- El editor del correo empezaba con 212 px de alto; ahora empieza en 132 px y crece con el texto, con una sola barra de desplazamiento.
- La corrección ortográfica automática podía actuar sobre el **texto legal de las condiciones**. Ahora en ese editor ADI solo trabaja a petición y con vista previa.

**Flujo.** Elegir herramienta → «Generar mejora» (indicador de proceso; no admite solicitudes duplicadas) → vista previa con los cambios resaltados → «Aplicar cambios», «Regenerar» o «Cancelar». El texto solo cambia al aplicar; si la persona siguió escribiendo, la respuesta antigua se descarta. Los fallos se muestran como fallos, con «Reintentar» cuando tiene sentido.

**No verificado aquí.** Las respuestas reales del proveedor de IA en producción (no hay clave en el equipo de desarrollo); en producción consta una corrección automática correcta registrada. La respuesta ante el límite de 60 mejoras por hora sí se observó y se muestra como error.

## ADI en campos de nombre (1.5.118)

«Nombres y apellidos / Razón social» y «Nombre comercial» del formulario de clientes tienen el botón ADI. En estos campos **no interviene la IA**: una regla fija normaliza mayúsculas, minúsculas y espacios repetidos (partículas como «de», «del», «la» en minúscula; siglas societarias como S.A. o CÍA. en mayúscula), conserva las tildes escritas y nunca añade, quita ni cambia palabras. Muestra una vista previa y solo se aplica con «Aplicar cambios». No hay herramientas de redacción en cédula, RUC, teléfono, correo, series ni importes.

## ADI Living Orb — Crystal Intelligence (1.5.119)

**Revisión del componente.** La esfera es un sombreador WebGL propio (`local/static/adi-orb.js`); el CSS solo actúa cuando el equipo no tiene aceleración gráfica. Recibe el estado real del asistente en cada cuadro (petición en curso, escucha, voz, conexión, cursor, toque). Problemas encontrados y corregidos en el propio motor:

- El entorno reflejado y la energía interior **giraban de forma constante**. Ahora derivan con oscilaciones lentas de frecuencias distintas, sin rotación tipo «planeta».
- La respiración era lenta (unos 7,5 s). Ahora combina ritmos de 4 y 6 s, por lo que no se repite igual.
- Con el chat abierto había **dos renderizadores**. Ahora hay uno solo: la esfera del encabezado (40 px) copia el cuadro ya dibujado por la flotante.
- No reaccionaba a la cercanía del cursor. Ahora intensifica los reflejos y orienta mínimamente el cristal al acercarse (o al tocarla), y vuelve sola al alejarse.
- El toque solo expandía el halo. Ahora una onda recorre la superficie, con el rebote elástico.
- Se añadió una iridiscencia leve en el borde y se redujo el halo exterior. Las letras «ADI» son más finas.

**Tecnología.** WebGL 1 con GLSL (trazado de rayos sobre una esfera, refracción, Fresnel, ruido procedural). No se incorporó Three.js: para un elemento de 68 px añadiría cientos de KB y no mejora lo que ya calcula el sombreador.

**Voz.** El navegador no permite conectar la síntesis de voz (Web Speech) a un `AnalyserNode`: su audio no pasa por Web Audio. Por eso, al hablar, la esfera sigue los eventos de palabra que emite el propio motor de voz, no la amplitud; no hay temporizadores inventados. Un análisis de amplitud real exigiría generar la voz con un servicio propio que entregue el audio.

**Comprobado a tamaño real** (68 px en escritorio, 56 px en móvil): movimiento continuo con el botón en su sitio, un solo contexto WebGL con y sin el chat abierto, espejo del encabezado dibujado, estados recorridos sin errores, memoria estable y, tras recargar, chat cerrado y sin voz ni micrófono.

## Esfera de cristal rosa y turquesa con estados reales (1.5.128)

**Por qué las versiones anteriores no convencían.** 1) A 56–60 px hay muy pocos píxeles: los filamentos finos y los destellos pequeños se perdían y la esfera se leía como un botón. 2) El interior estaba casi quieto en reposo. 3) Varios estados solo existían en la alternativa CSS (el error hacía temblar el botón; la escucha y el proceso apenas cambiaban el dibujo 3D). 4) En equipos sin aceleración gráfica se ve la alternativa CSS, más plana.

**Qué hace ahora el sombreador (`local/static/adi-orb.js`).** Sigue siendo una esfera trazada por rayos (refracción, Fresnel, reflejo de entorno, cáustica), en rosa luminoso y turquesa, sin texto, con fondo transparente y halo delicado:

- Reposo: respiración de dos ritmos, núcleo luminoso y **ondas internas de energía** (pliegues de luz que avanzan despacio).
- Escucha: ondas turquesa que entran desde la superficie y crecen con el volumen real del micrófono (o con el inicio/fin de voz que informa el reconocimiento cuando no hay medidor).
- Proceso: un anillo de energía que gira alrededor del núcleo y un latido suave.
- Respuesta: ondas desde el núcleo con cada palabra que informa el motor de voz del navegador (no hay acceso a la amplitud del audio de Web Speech, así que no se simula).
- Error: la esfera se apaga un poco y toma un tono coral que late; sin sacudidas.

Los estados son los del asistente (`adi-busy`, `data-voice`, `data-orb`): nunca se muestran si la operación no está ocurriendo. Tamaño minimizado: 60 px (56 px en pantallas pequeñas). Las luces se comprimen para que los estados activos no quemen el cristal.

**Sonidos.** Generados con Web Audio, sin archivos: notas senoidales suaves con ataque lento, filtro que quita aspereza y un eco corto muy bajo. Abrir (tres notas ascendentes), cerrar (dos descendentes), empezar a escuchar (una nota breve), respuesta recibida (dos notas), asesor conectado y error (dos notas graves). Solo suenan tras una interacción de la persona, nunca en bucle ni durante la respiración, callan mientras ADI habla y respetan el interruptor «Sonidos».

**No verificado aquí:** cómo suenan en altavoces reales y cómo se ve en una GPU real (las pruebas usan dibujo por software).

## ADI en el nombre de la reserva pública de citas

En «Agendamiento de Citas Técnicas», el campo «Nombre y apellidos» tiene un botón «ADI» (destellos rosados) en la línea de la etiqueta; no cambia la altura del formulario. Usa la misma integración de ADI (`adi_ai.py`), no un asistente aparte.

- Ruta pública `POST /api/public/adi/name` con `{name}`. Solo acepta nombres escritos con letras (2 a 150 caracteres), con un máximo de 10 revisiones cada 15 minutos por conexión. **No guarda nada**: ni el nombre, ni la propuesta, ni registros.
- Siempre aplica el arreglo local (`tidy_name`): espacios duplicados y mayúsculas iniciales, con «de», «del», «la»… en minúscula. Si hay proveedor de IA y la redacción de ADI está activada, pide además tildes y letras dudosas. La respuesta de la IA solo se acepta si es un retoque (mismas palabras, mismo orden; tildes, mayúsculas o una o dos letras en palabras largas); cualquier otra cosa se descarta. Si la IA falla, queda el arreglo local: la reserva nunca depende de ella.
- El nombre **nunca cambia solo**. El panel «Sugerencia de ADI» muestra el texto original y el sugerido, con «Aplicar sugerencia» y «Conservar original»; Escape o seguir escribiendo lo cierran sin cambios. Si no hay nada que corregir, lo indica y recuerda comprobar el nombre con el documento de identificación.
- Al pulsar el botón, el nombre escrito viaja al proveedor de IA configurado en el servidor (solo ese texto). Sin pulsarlo no se envía nada.

## Ventana flotante de ADI: distribución interna (13/10/2026)

Solo diseño; no cambian funciones, enlaces, voz, esfera ni colores. Los cuatro accesos rápidos van en cuadrícula de 2×2 con botones iguales y 8 px de separación; el campo de mensaje, el micrófono y Enviar miden 44 px y se alinean por la base cuando el texto crece; «Contactar soporte técnico» y «Consultar reparación» ocupan dos columnas iguales; los controles del encabezado miden 32 px. Todos los bloques usan 14 px de margen interior. En pantallas pequeñas la ventana usa el ancho disponible y solo se desplaza el área de mensajes.

Causa de los márgenes desiguales: la regla genérica `.adi-panel{padding:10px 12px}` del asistente de redacción también afectaba a esta ventana. Los componentes nuevos de ADI usan prefijos propios (`name-adi-…`) para no compartir clases; una prueba comprueba que cada página conserva `class="adi-panel" id="adi-panel"`.

## Voz natural y conversación continua (rama `adi-voz`, 21/10/2026)

**Diagnóstico previo:**
- La voz era la del navegador (`speechSynthesis`): depende de las voces instaladas en cada equipo y en Android y Windows suena robótica.
- El micrófono usaba el reconocimiento de voz del navegador por turnos (había que pulsar cada vez y no funcionaba en Firefox).
- El chat usa OpenAI `gpt-4.1-mini` con la clave del servidor (`OPEN_API_KEY`).

**Decisión del propietario:** voz por turnos con OpenAI y un tope diario inicial de **30 minutos**.

**Cómo funciona:**
- **Voz:** `gpt-4o-mini-tts`, con las voces femeninas coral (predeterminada), nova, shimmer y sage.
  - Lleva indicaciones de tono cálido y español latinoamericano.
  - Texto hablado propio: «Pe ce dóctor, ese a», importes en palabras, sin enlaces ni listas, y como máximo unos 600 caracteres (el texto completo queda en pantalla).
  - El audio se reproduce como `blob:` (la CSP añade `media-src 'self' blob:`).
- **Conversación continua:** se pulsa «Hablar con ADI» o el micrófono una sola vez.
  - El navegador detecta el inicio y el final de cada intervención, con calibración del ruido, cancelación de eco y supresión de ruido.
  - Envía solo esa grabación a `/api/public/adi/listen`, que transcribe con `gpt-4o-mini-transcribe`. El audio no se guarda.
  - ADI responde y habla; si la persona habla encima, se interrumpe.
  - Una barra compacta muestra el estado (escuchando, procesando, hablando o en pausa) con los botones Silenciar y Finalizar.
  - Funciona también en Firefox y Safari porque la transcripción la hace el servidor.
- **Seguridad:**
  - `/api/public/adi/speech` solo pronuncia mensajes de ADI o del asesor de la conversación de ese navegador, o el saludo; no es un servicio de texto a voz abierto.
  - Límite de 60 solicitudes de voz cada 10 minutos por conexión y tope diario de minutos.
  - Al alcanzarlo, o si OpenAI falla, se usa la voz del navegador. Una interrupción no cuenta como fallo.
  - La clave nunca llega al navegador.
- **Saludo:** visual y automático en las páginas públicas (configurable). Solo se escucha al iniciar la primera conversación por voz; nunca se pide el micrófono sin una acción del cliente.
- **Personalidad:**
  - respuestas breves y naturales;
  - precios solo de `precios_registrados_iva_incluido` (catálogo disponible y sin IVA pendiente);
  - órdenes solo tras verificar con el código por correo, como antes;
  - ofrece un asesor humano cuando hace falta.
- **Modo administrador:** la ADI administrativa usa la voz natural (`/api/adi/speech`, solo administración) con la del navegador como respaldo.
- **Configuración → Personalidad y Voz de ADI:**
  - voz con muestra, estilo, velocidad, saludo (también se puede escuchar), conversación continua, sensibilidad y pausa;
  - tope diario con el consumo de hoy;
  - estado real de OpenAI y de los modelos.

**Pruebas** (con OpenAI simulado y un micrófono falso de Chromium): la batería del servidor y 19 comprobaciones en el navegador.

**Pendiente de verificar en producción** (requiere la clave real y consume crédito): la naturalidad de las voces, la latencia real y los dispositivos Android e iPhone.

## Voz de ADI estable con Turso (INC-20261021-001, 21/10/2026)

**Síntoma:** `OperationalError` en `POST /api/public/adi/speech` (`remote_db.py:233 · _send`): «interactive transaction was rolled back because the stream was idle for too long».

**Causa:**
- La ruta anotaba el límite por conexión, lo que abre una transacción, y la dejaba abierta mientras OpenAI generaba el audio.
- Turso descarta una transacción cuyo flujo queda inactivo, y la siguiente escritura (el consumo de minutos) fallaba con 503.
- Lo mismo podía ocurrir en `/api/public/adi/listen`, en la muestra de voz, en `/api/adi/speech` y en la ADI administrativa (`/api/adi/admin`).

**Corrección:**
- Se confirma la transacción antes de cada llamada a OpenAI, igual que ya se hacía en el chat y en el correo (sección 1.5.90). El consumo se anota después, en una transacción nueva y breve.
- Defensa en `remote_db`: si Turso responde que el flujo caducó, la conexión se libera y el error indica la operación. La siguiente operación empieza limpia en lugar de arrastrar el flujo caducado.
- Producción (`wsgi_app.py`) usa la misma CSP que la aplicación, con `media-src 'self' blob:`, para que el audio natural se reproduzca en lugar de pasar a la voz del navegador.

**Revisión del mismo patrón en todo el sistema (1.5.191):** se revisaron todas las llamadas externas. Los correos, el chat y la escritura con ADI ya confirmaban antes de llamar. Quedaban tres puntos que dejaban la transacción abierta mientras esperaban, y ahora confirman antes:
- la identificación por número de serie con el servicio del fabricante (límite de consultas y hasta 8 s por petición);
- el correo de prueba de Notificaciones automáticas;
- la verificación Turnstile (Cloudflare) del inicio de sesión y de la recuperación de contraseña.

Prueba: `test_remote_external_calls.py`, que falla con el código anterior y pasa con la corrección.

**Pruebas:** `test_adi_voice_remote.py`. Usa el servidor libSQL de pruebas (`hrana_fake.py`) con caducidad de flujos inactivos y OpenAI simulado y lento. Las pruebas fallan con el código anterior y pasan con la corrección.

## ADI Living Intelligence Pro (21/10/2026)

**Lo que ya existía y se conserva:**
- La esfera 3D en WebGL (`adi-orb.js`), con un sombreador propio y sin bibliotecas: cristal líquido, núcleo luminoso, filamentos de energía, halo volumétrico y ondas de superficie.
- Estados ligados a eventos reales: reposo con respiración asimétrica, escucha según el volumen real del micrófono, pensamiento con un anillo de energía y partículas, voz, error y desconexión.
- Rendimiento: unos 30 fps en reposo, pausa con la pestaña oculta, calidad adaptable, movimiento reducido, liberación del contexto gráfico y una esfera CSS de respaldo sin WebGL.
- Ventana premium con la esfera en el encabezado, voz natural de OpenAI, conversación continua con interrupción, botón para detener la voz y barra de estado de voz.

**Mejoras de esta versión:**
- **Voz sincronizada con el audio real:** al recibir el audio de OpenAI, el navegador lo decodifica aparte (sin tocar la reproducción) y calcula 60 niveles de amplitud por segundo. La esfera pulsa con la amplitud de cada instante. Antes solo recibía un pulso al empezar y luego quedaba fija. Con la voz del navegador, que no da acceso al audio, sigue latiendo con cada palabra.
- **Partículas de profundidad en reposo:** son tenues y giran despacio; al pensar se reúnen alrededor del núcleo y brillan algo más al hablar. No añaden coste: el cálculo ya existía y solo se mostraba al pensar.
- **Atención al escribir:** mientras el cliente escribe, la esfera aumenta su brillo de cercanía.
- **Encabezado con estado de voz:** «ADI te está escuchando…» (turquesa), «ADI está procesando tu voz…» (ámbar) y «ADI está hablando…» (rosa), con un punto que pulsa. Sin pulso con movimiento reducido.
- **Reintentar sin perder la conversación:** si un mensaje no se envía, el aviso de error incluye «Reintentar». El texto se conserva y no se duplica.
- **Sin coste fuera de pantalla:** la esfera deja de dibujar cuando no se ve, salvo que la necesite la copia del encabezado.
- **Horarios ofrecidos por ADI:** los botones «Reservar» quedan seguidos, sin huecos entre ellos.
- **Voz:** pausa ligera después del saludo y entonación ascendente en las preguntas.

**Sin cambios:**
- tamaño y posición de la esfera (62 px en escritorio y 48 px en móvil);
- la integración con OpenAI, la corrección ortográfica, el chat, la agenda y los permisos.

**Pruebas en navegador** (OpenAI simulado, micrófono falso y audio de amplitud variable):
- 13 comprobaciones nuevas: esfera, estados del encabezado, amplitud real, reposo, atención, reintento, pausa fuera de pantalla, movimiento reducido, 320, 390 y 768 px, Escape y ausencia de errores de JavaScript;
- las 12 comprobaciones anteriores de la conversación por voz;
- la prueba de los botones de horario.

## Diseño definitivo de ADI: esfera de filamentos de energía (21/10/2026)

**Referencia:** la imagen aprobada por administración: esfera de filamentos luminosos y velos translúcidos con interior oscuro, rosado neón y magenta arriba a la derecha, violeta en la transición, azul eléctrico y cian abajo a la izquierda, borde orgánico y resplandor suave. No se sustituye por otra propuesta sin autorización.

**Tecnología:** se revisó la implementación existente. `adi-orb.js` ya era WebGL con un sombreador propio, estados reales, límite de FPS, pausa fuera de vista, calidad adaptable, liberación del contexto gráfico y respaldo CSS. Se mantiene esa base y solo se sustituye el sombreador. Three.js (unos 600 KB) no aportaba fidelidad para un elemento de 60 px.

**Cómo se dibuja:**
- **Filamentos:** hilos finos de tres familias entrelazadas, con un halo tenue, y velos anchos y translúcidos. Se calculan sobre una esfera 3D real que gira despacio y sigue levemente al cursor. La cara trasera, más tenue, da profundidad.
- **Silueta y borde:** donde se acumulan los hilos se forma un anillo luminoso, con hilos que rodean el contorno, destellos blanco-rosados arriba a la derecha y cian-blancos abajo a la izquierda. Los velos ondulados que salen del contorno evitan un círculo rígido.
- **Grosor:** los hilos se engrosan en el botón de 60 px para que se vean, y en tamaños mayores son finos.
- **Sin costuras:** el ruido del contorno usa el seno y el coseno del ángulo, no el ángulo directamente.

**Estados (eventos reales):**
- **Reposo:** respiración lenta y filamentos que se desplazan con movimiento orgánico.
- **Escuchando:** el borde ondula y aparecen ondas según el volumen real del micrófono, con más resplandor rosado.
- **Pensando:** las corrientes giran y se reorganizan alrededor del núcleo.
- **Hablando:** luz, tamaño y velocidad siguen la amplitud real del audio de ADI. Nunca hay animación de habla sin audio.
- **Error:** tono apagado y rojizo, discreto. El chat ofrece «Reintentar».
- **Transiciones:** la fase del flujo se integra en JS, así que acelerar o volver al reposo nunca produce saltos.

**Botón:**
- Conserva su tamaño (60 px en escritorio y 48 px en móvil) y su posición.
- El texto «ADI» ya no se superpone a la esfera; el nombre accesible del botón se mantiene.
- La ventana de chat muestra la misma esfera en su encabezado.

**Sin WebGL:** la alternativa CSS usa la misma identidad (interior oscuro y anillo de energía rosado, magenta, violeta y azul con arcos que giran). Se detiene con movimiento reducido.

**Rendimiento:** en dibujo por software, con pantalla de alta densidad y estado activo, cada cuadro cuesta menos de 9 ms y la calidad adaptable no necesitó bajar. Se mantienen unos 30 fps en reposo y la pausa con la pestaña oculta o fuera de la vista.

**Pruebas:**
- Capturas de cada estado comparadas con la referencia.
- Las 13 comprobaciones de ADI Living Intelligence y las 12 de la conversación por voz, en verde.
- Botón con WebGL, con la alternativa CSS y en móvil, sin errores de JavaScript.

## Tareas programadas: corrección de «no se ejecutan»

**Causa:** la tarea solo verificaba si no había habido *ninguna* verificación en los 10 minutos anteriores, y las automáticas por visitas la tapaban sin dejar constancia. Además, el aviso alarmaba a las 12 h.

**Ahora:**
- Cada llamada deja un latido (`cron_heartbeat`) y ejecuta su verificación completa, salvo que haya otra en curso.
- El aviso «no se reciben» aparece tras 18 h sin llamadas. Hay tres tareas diarias separadas 8 h.
