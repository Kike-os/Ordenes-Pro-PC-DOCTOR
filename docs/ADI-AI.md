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
