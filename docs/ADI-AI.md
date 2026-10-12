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
