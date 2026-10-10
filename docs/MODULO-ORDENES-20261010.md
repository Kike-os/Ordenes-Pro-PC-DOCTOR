# Módulo de órdenes — 10/10/2026

## Correcciones verificadas

- Encabezado con título, subtítulo solicitado y Nueva orden alineada a la derecha en escritorio; se adapta en móvil.
- Búsqueda independiente por número, cliente, identificación, teléfono, nombre comercial, equipo y serie. Un código exacto abre la orden autenticada.
- Una tarjeta de filtros: estado, fechas, cliente, equipo, Solo activas, Aplicar filtros y Limpiar. Aplicar conserva la búsqueda y reinicia la página; Limpiar elimina los filtros avanzados y conserva la búsqueda visible. El servidor rechaza intervalos invertidos.
- Tabla con Orden (equipo secundario), Cliente, Estado, Ingreso, Técnico responsable y Acciones. Badge de estado sin selector dominante.
- Ver orden e Imprimir ticket visibles. Más acciones agrupa edición, cambio de estado, historial, reimpresión, compartir, etiqueta y duplicación. Las operaciones administrativas mantienen su control de permisos.
- Menú con teclado, Escape y restauración del foco, limitado al área visible. Cambio de estado utiliza el endpoint existente y previene envíos simultáneos.
- Contador singular/plural, rango de resultados y Anterior / Página X de Y / Siguiente. El servidor ajusta páginas fuera de rango.
- Filtros adaptables y filas en tarjetas en pantallas pequeñas. Estilos acotados al listado; colores, logo, fondo e identidad conservados.

## Archivos modificados

`local/static/app.js`, `local/static/app.css`, `local/app.py`, `local/tests/test_order_workspace.py`.

No se realizaron migraciones para este rediseño ni cambios en identificadores, datos registrados, QR o impresión.

## Pruebas

78 pruebas de backend aprobadas. Sintaxis JavaScript y compilación Python correctas.

Navegador Chromium: siete anchos (1920, 1440, 1366, 1024, 768, 390 y 320 px), capturas del listado y menú, sin desbordamiento horizontal. Se comprobaron paginación con 55 órdenes ficticias, filtro de estado y singular, Solo activas, limpieza conservando búsqueda, guardado de estado, foco de historial, apertura por código y ausencia de estilos del listado en Clientes. Sin errores graves en consola.

Evidencia: `revision/orders-module-20261010/browser-checks.json`, `tests.log` y capturas PNG. Pruebas funcionales ejecutadas en base temporal independiente, sin modificar órdenes reales. Copias previas de los tres archivos principales en el mismo directorio.

## Límites

Comprobado en navegador con tamaños de pantalla simulados; no en teléfonos físicos. No se efectuaron envíos de correo, mensajería ni impresiones físicas durante esta revisión. Las verificaciones y pendientes del ticket están documentados por separado en `docs/TICKET-TERMICO.md`.
