# Gestión técnica del equipo

Es la ventana que antes se llamaba «Editar orden» (mismo componente, `openOrderEditor`). Edita **un equipo**: cada equipo de una orden es un ingreso propio, con su identificador interno, de modo que guardar E02 nunca modifica E01.

## Estructura

- Encabezado fijo: título, código de la orden, código del equipo (`…-E02 · EQ-0008`) y descripción del equipo.
- **Control y seguimiento**: estado, técnico responsable, prioridad y fecha estimada de entrega (catálogos reales del servidor).
- **Informe técnico**: descripción del trabajo actual (obligatoria), observaciones del técnico y hallazgos del diagnóstico. Los dos últimos llevan la marca «Uso interno».
- **Recomendaciones** para el cuidado del equipo.
- **Importes del equipo**: líneas manuales, o solo lectura cuando los fija un presupuesto aprobado (ver `PRESUPUESTOS.md`).
- **Historial**: comentario opcional y las últimas modificaciones con fecha, hora y usuario.
- Pie fijo: indicador «Cambios pendientes», Cancelar y Guardar cambios.

## Comportamiento

- Validación junto al campo antes de enviar; el servidor repite todas las comprobaciones y controla la revisión (si otra persona guardó antes, se avisa).
- Cerrar con cambios sin guardar pide confirmación. El botón de guardar se bloquea mientras envía: un doble clic produce un solo guardado.
- Las notas internas solo aparecen en el documento interno de servicio; no se incluyen en correos, presupuestos ni documentos del cliente.

## ADI en los campos

- La clave del proveedor vive en el servidor; el navegador nunca la recibe. Al proveedor solo viaja el párrafo y el nombre del campo.
- Flujo: elegir herramienta → «Generar mejora» (indicador «Procesando…») → vista previa con cambios resaltados → **Aplicar mejora**, **Editar** (la propuesta se vuelve editable y se aplica lo que quede escrito), **Regenerar** o **Conservar original**.
- Al aplicar, el campo muestra un destello rosado breve (con movimiento reducido, un contorno estático) y el aviso ofrece «Deshacer».
- Si el servicio falla o tarda, se explica el motivo y el texto queda intacto.
- En los campos internos (`internal_notes`, `findings`, `comment`, `technician_notes`) no se ofrece «Explicación para el cliente», y el servidor la rechaza.

## Contacto del cliente en el detalle

El detalle muestra el teléfono y el correo vigentes de la ficha del cliente (los mismos que usan los correos y presupuestos). Si cambiaron desde la recepción, se añade «Contacto al recibir el equipo» con el valor de entonces. Los documentos de recepción conservan su copia original.
