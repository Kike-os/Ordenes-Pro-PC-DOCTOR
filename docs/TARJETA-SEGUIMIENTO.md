# Tarjeta Digital de Seguimiento Técnico (publicado en la versión 1.5.130)

Ticket de dos secciones en azul tecnológico, con los datos reales de la orden, un **QR real** y un **código de barras Code 128 real**.

## Estructura

- **Sección superior:** logo original, «Seguimiento de reparación», número de orden, estado, barra de avance con cuatro etapas y datos (cliente, equipo, fecha de ingreso, última actualización, técnico).
- **Corte punteado** con muescas.
- **Sección inferior:** «Código de seguimiento», QR, código de barras con el número de orden debajo y pie con la identidad de PC-DOCTOR S.A.

## Etapas

Recepción · Diagnóstico y reparación · Listo para retiro · Entrega. Salen del estado real de la orden; una etapa futura nunca aparece como completada. El sistema no distingue diagnóstico de reparación como estados separados («Procesando» cubre ambos), por eso comparten etapa en lugar de marcar una como terminada sin constancia.

## QR y código de barras

- **QR:** generado con Segno (ya incluido en `local/vendor`). Apunta al enlace público de seguimiento de la orden (`/s/<token>`, token aleatorio de 128 bits, revocable). No contiene datos personales.
- **Código de barras:** `local/barcode128.py`, Code 128 juego B, sin dependencias, en SVG vectorial. Codifica el número de orden. Verificado con un lector independiente (`zbarimg`).
- Sin enlace público activo la tarjeta lo indica y no muestra ningún QR.

## Vistas

| Vista | Ruta | Acceso | Contenido |
|---|---|---|---|
| Panel | botón «Tarjeta de seguimiento» en el detalle de la orden, en cada fila del Seguimiento de Órdenes y en el menú de la fila | sesión | completa, con cliente y técnico |
| Imprimir o guardar PDF | `/tarjeta/<id>` | sesión | completa; hoja en modo papel (fondo blanco) |
| Cliente | `/s/<token>` | enlace público | sin nombre, identificación, teléfono, serie, falla ni técnico; se recarga sola cada 3 minutos |

Rutas de apoyo: `/api/orders/<id>/tracking-card`, `/api/orders/<id>/barcode.svg`, `/s/<token>/qr.svg`, `/s/<token>/barcode.svg`.

La página pública anterior (`/s/<token>`) pasa a ser esta tarjeta; los enlaces ya entregados siguen funcionando.

## Límites

- El PDF se obtiene con «Imprimir o guardar como PDF» del navegador; no hay un PDF generado en el servidor para la tarjeta.
- En una captura a 320 px y densidad 1 el código de barras no llega a leerse; en un teléfono real (densidad 2 o 3) y en papel sí tiene resolución suficiente. No se probó con un lector físico.

Pruebas: `local/tests/test_tracking_card.py`.

## Versión compacta (publicado en la versión 1.5.131)

Tarjeta más estrecha y con menos espacio vacío (400 × 633 px en la vista del cliente), logotipo original más grande (136 px de ancho, sin modificarlo), un icono de trazo fino junto a cada dato, QR de 128 px y código de barras más alto. En 320 px los datos pasan a una columna. Se conservan los datos, las rutas y las funciones.

Lectura comprobada con un lector independiente sobre capturas de pantalla: a la densidad de un teléfono (2× y 3×) se leen el QR y el código de barras; a densidad 1 (monitor corriente) el QR se lee y el código de barras no, porque cada barra mide menos de 1,5 píxeles. En papel ambos son vectoriales.

## Seguimiento público ampliado (1.5.240)

**Sin cambios:** la tarjeta conserva su identidad (degradado azul, logo original, corte de ticket, QR y código de barras). La vista interna para imprimir (`/tarjeta/<orden>`) no cambia.

**Contenedor:**
- En escritorio mide hasta 1040 px y en el teléfono, el ancho de la pantalla.
- En escritorio se organiza en dos columnas: novedades y evidencias a un lado, seguimiento de repuestos al otro. En el teléfono, una sola.
- Nada usa alturas fijas ni recorta.

**Barra de avance** (Recepción · Diagnóstico y reparación · Listo para retiro · Entrega):
- Hay un segmento por etapa. Solo las completadas llevan color: azul, turquesa, verde claro y verde intenso. La actual se marca a medias y las pendientes quedan en gris azulado.
- Se rellena una sola vez en unos 0,5 s y respeta «movimiento reducido».
- Los estados de espera **no adelantan el avance**: se muestran como aviso. Son «Presupuesto pendiente de su aprobación», «Esperando su respuesta», «En revisión por falla recurrente» y «Esperando repuesto(s)».

**Repuestos (modelo público seguro, `order_part_requests.public`):**
- **Etapas públicas:** Solicitud registrada, Repuesto confirmado, En traslado hacia PC-DOCTOR, Recibido en el taller, Instalación y pruebas, Proceso finalizado.
  - La de traslado solo aparece si se registró ese evento.
  - Solo las completadas se colorean, de azul a verde.
- **Qué muestra:** descripción del estado real, fechas reales (la disponibilidad estimada solo si existe) e historial público.
- **Datos del proveedor:** nunca se publican el proveedor, los mercados en línea (eBay, Mercado Libre, Amazon y otros), el transportista, la guía, el pedido ni el dominio de rastreo.
  - Al guardar, un mensaje público que los mencione se rechaza.
  - Al mostrar, un mensaje antiguo que los contenga se omite y el nombre se depura.

**Evidencias:**
- Miniaturas uniformes con indicador de carga y aviso si no cargan.
- Las fotos antiguas sin miniatura se muestran con la imagen real, en lugar de «IMG».
- No se muestran nombres de archivo («Fotografía 1», «Documento 1»).
- El visor tiene navegación anterior y siguiente (botones y flechas), contador y zoom.
- Contador antiabuso propio de las evidencias: antes compartían el de la página y una orden con varias fotos podía bloquear la consulta.

**Códigos:**
- QR de 132 px y código de barras de hasta 360 px, en una fila en escritorio y apilados en el teléfono.
- «Actualizar seguimiento» e «Imprimir». La página se recarga sola cada 3 minutos, siempre con datos reales.

**Pruebas:**
- **Navegador:** 24 comprobaciones.
  - Escenarios: recibida, diagnóstico, esperando aprobación, esperando repuestos (3 en estados distintos, uno recibido), lista, entregada, sin evidencias, varias fotos e histórica.
  - Anchos: 320, 375, 430, 768, 1366 y 1920 px.
- **Unitarias:**
  - etapas públicas y colores;
  - rechazo de datos del proveedor;
  - avance sin adelantos;
  - contador de evidencias.
