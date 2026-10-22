# Seguimiento de Órdenes (inicio)

Módulo de solo lectura que muestra **una tarjeta por orden** con su último movimiento. Sustituye a la lista de los tres últimos movimientos, donde una misma orden aparecía repetida. No borra ni modifica historial: todos los eventos siguen en `order_history` y se ven al desplegar cada tarjeta.

- **Contadores** calculados con las órdenes reales: En espera, En proceso, Esperando respuesta (cliente o presupuesto), Listas para entregar y Entregadas. El sistema no tiene un estado «diagnóstico» propio, así que no se muestra un contador con ese nombre. Los de un solo estado sirven también de filtro.
- **Tarjeta**: número de orden, cliente, tipo/marca/modelo, estado con color e icono, etapas, último movimiento con fecha y hora exactas y tiempo transcurrido, técnico responsable, quién registró la última actividad y prioridad (solo si es baja, alta o urgente). Los datos que no existen no se muestran.
- **Etapas** (Recibido → En proceso → Listo → Entregado): la actual, las completadas **solo si constan en el historial**, las anteriores sin evidencia marcadas como «sin registro» (línea discontinua) y las pendientes. No existe un estado «cancelada» en el sistema.
- **Herramientas**: buscador por orden, cliente o equipo; filtros por estado, técnico y fecha del último movimiento; «Ver detalles»; historial cronológico desplegable; paginación de 8 órdenes.
- **Actualización**: consulta cada 30 s mientras el inicio está visible (se detiene con la pestaña oculta o al salir). «En vivo · sincronizado HH:MM» solo aparece si la última consulta funcionó; si falla, indica la hora del último dato. Un movimiento nuevo anima su tarjeta y un cambio de estado genera un aviso.
- **Servidor**: `GET /api/tracking` (una consulta agrupada más los contadores) y `GET /api/tracking/<id>` (historial completo de la orden); requieren sesión. Código en `local/tracking_board.py`.

## Tabla compacta (1.5.109)

- El seguimiento pasa de tarjetas a una **tabla** con una fila por orden: Orden (con equipo), Cliente, Estado (con la línea de etapas), Último movimiento (fecha, tiempo transcurrido y quién lo registró), Técnico (con la prioridad si no es normal) y Acciones («Ver» e «Historial»). En tabletas se oculta la columna Técnico y en teléfonos cada fila se muestra como ficha.
- Se eliminaron los cinco contadores internos, que repetían los indicadores superiores. Las **seis tarjetas de estado** del inicio filtran ahora la tabla al pulsarlas (y dejan de filtrar al pulsarlas otra vez); sus números se actualizan con cada sincronización.
- La búsqueda queda siempre visible; estado, técnico y fechas están en «Filtros», con los filtros activos como etiquetas retirables.
- El historial de cada orden se despliega bajo su fila y se mantiene abierto durante las sincronizaciones. No cambia nada del historial ni de los datos.

## Carrusel de altura fija (1.5.127)

El panel «Seguimiento de Órdenes» del inicio ya no crece con el número de órdenes: muestra **tres órdenes** en una ventana de altura fija (189 px en escritorio) y las secciones inferiores no se desplazan.

- **Avance automático:** una fila cada 6 segundos, con una transición vertical de unos 520 ms. Funciona como una cinta: entra la orden siguiente y sale la primera; el DOM nunca tiene más de las filas visibles y la que entra. Al mostrar las tres últimas vuelve a las tres primeras. No hay botón para activarlo o desactivarlo.
- **Pausas:** con el cursor sobre el panel, con el foco dentro (buscador, botones, filtros), al tocar la tabla (se reanuda 4 s después de soltar), con cualquier ventana abierta (historial, edición, menús), con búsqueda o filtros activos y con la pestaña oculta. Al terminar la interacción se espera el intervalo completo antes de volver a moverse. Con «movimiento reducido» no hay avance automático: quedan los controles manuales.
- **Controles:** flechas discretas para retroceder y avanzar, indicador «Mostrando órdenes 4–6 de 20» y «Ver todas las órdenes», que abre el módulo Órdenes (búsqueda, filtros y 10, 20 o 50 por página).
- **Búsqueda:** por número de orden, cliente, equipo, marca, modelo, serie y **estado**. Al buscar o filtrar el carrusel se detiene y muestra los resultados («Resultados 1–3 de 7») con los mismos controles.
- **Datos:** el navegador pide bloques de 12 órdenes (`/api/tracking?size=12&page=N`) solo cuando hacen falta; funciona igual con miles de órdenes. Cada 30 s se vuelven a pedir las filas visibles: si algo cambió y nadie está interactuando se actualizan en su sitio; si hay una interacción en curso, se aplica al terminar. Nunca se sustituyen filas durante la transición.
- **Historial:** se abre en una ventana («Historial · PCD-…») en lugar de desplegarse bajo la fila, para no alterar la altura del panel.
- Espaciado vertical reducido (filas de 52 px; antes ~58). En pantallas de hasta 860 px cada orden es una tarjeta de 178 px.

Pruebas: `local/tests/test_tracking_board.py` (bloques, búsqueda por estado, tamaños de página) y comprobación en navegador con 1, 2, 3, 5, 20, 45 y 100 órdenes.

## Columna «Acciones» sin cortes (rama `acciones-seguimiento`, pendiente de aprobación)

**Causa del botón cortado:** la tabla usa columnas de ancho fijo y la de acciones tenía el 15 % para tres botones con texto; al añadirse el de la tarjeta, el último sobresalía de la celda y el contenedor (que recorta para mantener la altura fija) lo cortaba.

**Solución:** la columna de acciones tiene un ancho propio en píxeles calculado para sus cuatro botones, y los botones no encogen ni saltan de línea.

- Cuatro acciones del mismo tamaño en una fila: **Ver** (detalle de la orden), **Historial** (movimientos, con su contador), **QR** (tarjeta de seguimiento con el QR y el código de barras) y **Ticket** (ticket de la orden).
- Desde 1600 px de ancho llevan icono y nombre (84 × 32 px); por debajo, solo el icono (32 × 32 px) con el nombre en la descripción emergente y en la etiqueta accesible.
- Entre 861 y 1180 px la tabla se desplaza horizontalmente dentro de su panel si hace falta. Hasta 860 px cada orden es una tarjeta con los cuatro botones en cuadrícula de dos columnas.
- Cliente y técnico muestran el nombre completo en la descripción emergente cuando se truncan.

Comprobado a 1920, 1440, 1280, 1024, 768, 390 y 320 px, y con los visores equivalentes al 125 % y 150 % de zoom en una pantalla de 1920 px: ningún botón cortado ni montado, fila de 52 px, sin desbordes.

## Listado profesional y indicador de progreso (octubre de 2026)

**Columnas.** Orden (código completo, icono y equipo), Cliente (nombre en hasta dos líneas y teléfono), Estado (etiqueta e indicador de progreso), Último movimiento, Técnico y Acciones. Cuando un texto no cabe se recorta con puntos suspensivos y el contenido completo queda en la descripción emergente.

**Acciones según el ancho.**

- 1360 px o más: Ver, Historial (con su contador dentro del botón), QR y Ticket con su nombre.
- 1181–1359 px: «Ver» con nombre y las otras tres como iconos.
- 861–1180 px (tableta): «Ver» y un menú «Más» con Historial, QR y Ticket; el técnico pasa bajo el cliente. Sin desplazamiento horizontal.
- 860 px o menos (teléfono): una tarjeta por orden con «Ver» y «Más».

El menú «Más» se abre anclado al botón, admite flechas, se cierra con Escape, al pulsar fuera o al desplazar, y devuelve el foco.

**Búsqueda y orden.** Se busca por orden, cliente, equipo, marca, estado o número de serie. El encabezado «Último movimiento» invierte el orden (más reciente o más antiguo primero); lo aplica el servidor (`sort=reciente|antiguo`).

**Indicador de progreso.** Cuatro barras (Recibido, En proceso, Listo, Entregado) que reflejan solo el estado real de la orden; no hay avances por tiempo.

- Etapa completada: iluminada. Etapa actual: una luz la recorre tres veces al pintarse y de nuevo al pasar el cursor; no es una animación continua. Pendientes: oscuras. Etapa sin registro en el historial: rayada.
- Listo para entregar o en espera de entrega: verde suave. Entregado: todas las barras en verde y una marca de verificación.
- Cuando el listado detecta que una orden pasó a «Entregado», las barras se llenan de izquierda a derecha y aparece un destello breve con dos estrellas, una sola vez. Si el estado se revierte, el indicador retrocede.
- Con «reducir movimiento» activado no hay animaciones y los estados siguen visibles.

## Altura del panel según las órdenes visibles

**Causa del espacio vacío.** La regla `.tracking-carousel{height:calc(var(--track-head) + 3*var(--track-row) + 2px)}` fijaba la altura del panel a tres filas, hubiera una, dos o ninguna orden; la celda vacía (`td.tracking-empty`) también reservaba tres filas. No intervenían `flex`, `min-height` ni contenedores padres.

**Corrección.** El panel mide exactamente lo que muestra: la altura usa `--track-shown`, que el componente fija con el número real de filas visibles (entre 1 y el máximo). Se muestran las cinco órdenes con movimientos más recientes, en cualquier pantalla. Con más órdenes de las visibles, la altura se mantiene y el recorrido es interno, con las flechas y el avance automático de siempre. Las flechas se ocultan cuando no hay más órdenes que las visibles; el contador y «Ver todas las órdenes» quedan inmediatamente bajo la última fila.

Comprobado en navegador con 0, 1, 2, 5, 10 y 50 órdenes a 1440, 820 y 390 px: separación de 1 px entre la última fila y el borde del panel, y 8 px hasta el pie, en todos los casos.

## Botón «Historial»

Icono de historial (reloj con flecha), texto y contador separados con un espacio uniforme. El contador es una insignia redondeada dentro del botón, con el número real de movimientos de esa orden (hasta tres dígitos sin deformar las acciones; `999+` si hubiera más) y `0` cuando no hay ninguno. Se actualiza solo cuando el listado detecta un movimiento nuevo y muestra entonces un destello rosado, una sola vez. Entre 1181 y 1359 px el texto se omite y quedan icono y contador; en tableta y teléfono la acción está en el menú «Más» con su contador. Al pulsarlo abre el historial de esa orden, nunca el de otra.

## Botón Historial y contador estable (13/10/2026)

El contador del botón «Historial» hacía crecer el botón con dos o más dígitos (de 116 a 134 px con «999+») y descuadraba las demás acciones. Ahora:

- **Contador estable global** (`stableCount` y `countText` en `app.js`, clase `.stable-count`): píldora de 35 × 23 px, cifras tabulares, sin salto de línea. Por encima de 999 muestra «999+»; el valor real queda en `data-count` y en el título. Cada módulo conserva su color con su propia clase.
- **Acciones de Seguimiento**, con tamaños fijos por ancho de pantalla: desde 1360 px, «Historial» mide 146 × 38 px y todos los botones 38 px de alto (QR y Ticket muestran su texto desde 1600 px); entre 1181 y 1359 px, variante compacta de 74 × 34 px con icono y contador; hasta 1180 px las acciones secundarias siguen en el menú «Más».
- Comprobado con 0, 1, 8, 9, 10, 12, 99, 100, 125, 999 y 1000 en 1920, 1440, 1366, 1280, 1024, 820, 390 y 320 px: no cambian el botón, las columnas, la altura de fila ni la posición de los demás botones.

Los otros contadores revisados (avisos, ADI, asistencia en vivo, grupos de presupuestos) ya limitan su texto o no desplazan a sus vecinos; no se modificaron.

## Seguimiento de Órdenes ultracompacto (1.5.150)

- **Encabezado en una línea**: título, indicador «En vivo» discreto y enlace «Historial completo»; buscador y «Filtros» en una fila de 36 px.
- **Filas de 54 px en escritorio** con ancho fijo por columna: el contenido de una columna nunca desplaza a las demás. Cliente, técnico y último movimiento se recortan en una línea; el texto completo queda en la descripción emergente y en el detalle de la orden.
- **Acciones**: Ver, Historial (con contador de ancho estable: 1, 42, 128, 999+), QR y Ticket, alineadas a la derecha. Entre 861 y 1180 px, y en celulares, quedan «Ver» y el menú «Más» con Historial, QR y Ticket (teclado, Escape y foco). No se elimina ninguna función.
- **Estados**: Procesando azul, Entregado verde, Listo para entregar turquesa, pendientes (En espera, respuesta del cliente, presupuesto) ámbar y cancelados rojo, con icono y texto.
- **Órdenes con varios equipos**: cada fila es un equipo. El enlace muestra el identificador de la orden y la etiqueta «Equipo 2/3» el equipo (su código individual está en la descripción emergente). El indicador de la fila es el estado de ese equipo; debajo figura el **estado general de la orden**, calculado por `equipment.overall` con todos sus equipos: nunca dice «Orden completada» mientras quede un equipo sin entregar («Entrega parcial», «Atención en curso»…). El servidor lo entrega en `group` dentro de cada fila de `/api/tracking`.
- **Celulares**: una tarjeta por equipo (orden y equipo, estado, cliente y técnico, último movimiento, acciones), sin desplazamiento horizontal.
- Solo cambia la presentación: no se modifican estados, historiales, clientes, equipos, órdenes, QR, tickets ni la búsqueda.

## Estado «En revisión por falla recurrente» (1.5.162)

- Código `revision_recurrente` (migración `057_recurring_review.sql`), color ámbar oscuro e icono de revisión circular, en el selector de estados, el Seguimiento de Órdenes, el Centro de Seguimiento Técnico (atención), el detalle, la tarjeta y la página pública de seguimiento (etapa «Diagnóstico y reparación» / «En proceso»).
- Misma orden y mismo número: no se crea otra orden. Al elegirlo se pide el **motivo** (obligatorio, mínimo 10 caracteres) y el **técnico responsable** (por omisión, el asignado). También desde la edición completa de la orden (el comentario es el motivo).
- Cada revisión queda en `order_recurrences` (inmutable): número de vez, fecha y hora, técnico, quién la registró, estado anterior y, si el equipo ya estaba entregado, **reingreso** con la fecha de la entrega original. El historial anterior (diagnósticos, reparaciones, estados) no se toca; la entrada del historial dice «Revisión por falla recurrente n.º N · Técnico responsable · Motivo».
- Conteo: «Revisión n.º N» en el Seguimiento de Órdenes y el bloque «Revisiones por falla recurrente» en el detalle. Las observaciones y resultados de pruebas se registran como siempre (seguimiento, hallazgos, recomendaciones).
- Órdenes con varios equipos: cada equipo (E01, E02…) tiene su propio estado, así que solo cambia el equipo afectado y el estado general de la orden se recalcula.
- Después se continúa con los estados normales (Procesando, Listo para entregar, Entregado). Al volver a entregar se registra la nueva entrega y su mantenimiento preventivo.

## Tabla «Seguimiento de Órdenes» · Enterprise Pro (1.5.204)

**Fallos corregidos.** Las celdas tenían una altura fija y se cortaban con puntos suspensivos los nombres de clientes y técnicos, el equipo, el saldo y la fecha del último movimiento. Entre 1024 y 1280 px, además, el estado largo («Esperando respuesta del cliente») se salía de su celda.

**Ahora ningún texto se recorta:**

- Cliente, técnico, equipo, estado, saldo y último movimiento pasan a otra línea si no caben.
- El carrusel (5 filas, giro cada 6 s y botones ▲▼) sigue funcionando. La altura uniforme que necesita para desplazarse una fila exacta la mide `fitRows()` con la fila más alta realmente dibujada. Solo crece mientras gira, para no saltar, y se recalcula al cambiar el ancho de la ventana.

**Columna Estado:**

- Estado de la orden y saldo en la misma línea; debajo, el progreso con etapas reales.
- Debajo del progreso, el **presupuesto vigente** con su estado real: esperando aprobación, aprobado, aprobado parcialmente, rechazado o revisión solicitada.
- Si el presupuesto ya está aprobado y la orden sigue en «Aprobación de presupuesto» o «Esperando respuesta del cliente», se marca «· actualizar estado» con borde discontinuo. La tabla **nunca** cambia el estado por su cuenta: eso lo hace el personal desde la orden.

**Búsqueda:** por orden, cliente, **teléfono** (con o sin espacios ni guiones, a partir de 6 dígitos), marca, modelo, serie, estado y tipo de equipo.

**Sincronización:**

- La tabla se actualiza cada 30 s, y en el acto al volver a la pestaña.
- La firma de cada fila incluye el estado del presupuesto, así que una aprobación redibuja la fila.
- Si la orden esperaba esa decisión, al aprobarse pasa a «Procesando» (lo hace el servidor al registrar la decisión).

**Comprobado:**

- Sin textos cortados ni elementos montados a 1920, 1536, 1440, 1366, 1280, 1100, 1024, 910, 853, 768, 600, 390 y 320 px, con nombres de cliente de hasta 74 caracteres y técnicos con nombres compuestos. Los anchos de 1536, 910 y 853 px equivalen a un zoom del 125 % o del 150 %.
- Botones Ver, Historial (con el número real de movimientos), QR e Imprimir.
- Búsqueda, filtro, ordenación y Escape.
- Aprobación de un presupuesto reflejada sin recargar.
