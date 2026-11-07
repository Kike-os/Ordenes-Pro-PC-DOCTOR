# Seguimiento de reparación: pantalla adaptable e impresión A4 (1.5.248)

## Pantalla (enlace público `/s/<token>`)

- **Ancho:** la tarjeta ocupa el ancho disponible, hasta 1360 px; ya no queda fija en 1040 px. Las columnas dependen del ancho real de la tarjeta (consultas de contenedor). No hay desplazamiento horizontal de 320 a 1920 px.
- **Logo original** (`static/logo-original.png`, 2826 × 2049):
  - El archivo no se modifica, recorta, redibuja ni sustituye.
  - El archivo trae un margen transparente de entre el 7 % y el 16 % por lado. La cabecera deja de mostrar ese margen vacío (recuadro con `overflow:hidden`) y conserva la proporción real del dibujo (2102 × 1596). Así, el logo se ve de **84 px de ancho en escritorio** y 64 px en el teléfono (56 px a 320 px), centrado verticalmente con el título.
- **Cabecera:** el orden visual es:
  1. logo;
  2. «PC-DOCTOR S.A.»;
  3. título «Seguimiento de reparación»;
  4. número de orden, en letra menor que el título;
  5. estado de la orden;
  6. estado del presupuesto («Presupuesto: Aprobado», sin importes);
  7. botón **Imprimir seguimiento A4**, con icono de impresora.
- **Legibilidad:** ningún texto informativo baja de 12 px. Las tarjetas usan 14 px de radio y los bloques internos 10 px. El mapa de ruta no pasa de 920 px de ancho en tarjetas muy anchas.
- **Sin cambios de funcionamiento:** se mantienen etapas, animaciones, cancelación con plazo de 24 horas, avisos y datos.

## Documento A4 (`tracking_print.py` + `static/seguimiento-a4.css`)

- **Formato:** A4 vertical con márgenes de 12 mm y fondo blanco.
- **Colores:** azul corporativo, celeste para la etapa actual, gris para lo pendiente y rojo para las incidencias. El estado siempre va escrito: el color no es la única señal.
- **Tipografía:** cuerpo 9–10 pt, títulos de sección 10,5 pt, título principal 16 pt y pie 8 pt.

| Sección | Contenido |
|---|---|
| A · Cabecera | Logo original (29 mm), PC-DOCTOR S.A., título, «Documento de seguimiento técnico», número de orden, fecha y hora de impresión (hora de Ecuador, al imprimir) y estado general. Lleva una línea azul debajo. |
| B · Equipo | Dos columnas: tipo, marca, modelo · ingreso, última actualización, estado de reparación y de presupuesto. A la derecha van el QR y el código de barras. Se omiten los campos que no existen. |
| C · Progreso | Cuatro etapas numeradas con su estado escrito. Si hay una falla recurrente, la etapa actual se marca como «Incidencia». |
| D · Repuestos | Un bloque por repuesto que no se parte entre hojas. Muestra estado logístico, tipo de envío, fechas, avance, la trayectoria del mapa en versión **estática** (vehículo quieto en su punto real) y las etapas con su fecha. |
| E · Avisos | Presupuesto pendiente, repuesto en transporte, fecha estimada, recibido en el taller, cancelación y plazo de cancelación (vigente o vencido). |
| G · Historial | Tabla «Fecha y hora · Etapa · Estado» en orden cronológico, más la próxima etapa pendiente de cada repuesto. Repite su encabezado en cada hoja y no parte filas. |
| H · Transporte | En la versión pública: tipo de envío, despacho, llegada estimada y recepción. Transportista, guía y país de origen solo aparecen en la versión interna. |
| I · Información técnica | En la versión pública, las novedades publicadas para el cliente. En la interna: observaciones internas, historial de modificaciones de la orden y evidencias documentadas. |
| F · Pie | En cada hoja: PC-DOCTOR S.A., dirección, ciudad, WhatsApp, sitio web, número de orden y «Página n de N» (margen `@page`). Al final del documento hay una línea corporativa por si el navegador no admite esos márgenes. |

### Paginación

- Una orden sin repuestos ocupa **una hoja**; con un repuesto, una o dos.
- Con varios repuestos, el documento sigue en hojas adicionales, sin reducir la letra.
- Al final no queda una hoja casi vacía: los códigos van en la primera.

### Versiones pública e interna

- **Pública:** está en la propia página `/s/<token>`, oculta en pantalla, y es lo único que se imprime (sin botones, formularios ni animaciones). Se construye solo con `order_tracking.lookup`, el mismo modelo seguro de la página. Nunca incluye nombre del cliente, identificación, serie, falla, notas internas, importes, proveedor, transportista, guía, referencia ni país de origen.
- **Interna:** está en `/tarjeta/<id>/a4`, con sesión de **administración o técnico** (otro rol recibe 404).
  - Se abre desde la orden con el botón «Seguimiento A4» o desde «Tarjeta de seguimiento» → «Imprimir seguimiento A4».
  - Añade cliente, serie, técnico responsable, referencia, proveedor, transportista, guía, notas internas, historial de modificaciones y evidencias, con el aviso «Documento interno».
  - En pantalla se ve como una hoja de vista previa, con barra de acciones que no se imprime.
- Las dos versiones solo leen datos: imprimir no cambia estados, historial ni avisos.

### Compatibilidad

- La numeración «Página n de N» y el pie en cada hoja usan los márgenes de página de CSS (`@page` con `@bottom-left` y `@bottom-right`), disponibles en Chrome y Edge desde la versión 131.
- En navegadores sin esa función, el documento se imprime igual y conserva al final la línea corporativa. La numeración la puede añadir el propio diálogo del navegador.
- «Guardar como PDF» se elige en el diálogo de impresión.

## Pruebas

- **Unitarias:** `local/tests/test_tracking_print.py` comprueba:
  - las secciones del documento y que la versión pública no incluya datos privados;
  - que ver o imprimir no cambie nada;
  - los permisos de la versión interna;
  - la hoja de estilos servida;
  - una orden sin repuestos.
- **Navegador:** con datos ficticios y base temporal (42 comprobaciones), se revisan:
  - el logo (archivo, proporción y tamaño);
  - la ausencia de desbordamiento de 320 a 1920 px;
  - la letra de al menos 12 px y el foco con Tab;
  - el PDF en A4 vertical, con pie y numeración en cada hoja y sin hojas vacías;
  - la coincidencia de los datos impresos con la pantalla;
  - la ausencia de datos privados en la versión pública;
  - una hoja para una orden sin repuestos y dos o menos para una con un repuesto;
  - la vista interna;
  - el movimiento reducido;
  - la ausencia de errores de consola.
