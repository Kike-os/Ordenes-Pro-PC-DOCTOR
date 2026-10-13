# Tarjeta Digital de Seguimiento Técnico (rama `tarjeta-seguimiento`, pendiente de aprobación)

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
