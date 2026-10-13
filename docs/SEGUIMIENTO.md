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
