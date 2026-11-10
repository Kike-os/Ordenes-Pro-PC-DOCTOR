# Detalle de la orden — Executive Compact 5.0 (1.5.270)

Las secciones que antes se apilaban en la columna derecha del detalle (comunicaciones, historial de correos, comprobante por correo, seguimiento del cliente, autorizaciones y permanencia) pasan a un **panel de dos columnas** con **cuatro módulos plegables**. El panel está justo debajo de las acciones de la orden y de la barra de Adi. Cada módulo muestra un **resumen** aunque esté contraído.

Solo cambia la presentación: el contenido de cada módulo lo construyen las **mismas funciones** de siempre, con los mismos permisos, enlaces, PDF, confirmaciones y registros. No se modifican estados, pagos, presupuestos, correos ni evidencias de autorización.

## Módulos

| Módulo | Resumen contraído | Contenido |
|---|---|---|
| Comunicaciones | cantidad, última fecha, fallidos, sin confirmar, revisados por ADI | historial cronológico único (correo del sistema, buzón, WhatsApp), filtros por canal, «Ver correo», historial completo, comprobante por correo, «Mensaje al cliente», «Escribir al cliente» |
| Seguimiento del cliente | enlace activo o desactivado, fecha de creación, sin caducidad | estado, orden, creación, caducidad, qué ve el cliente, Ver página, Copiar enlace, Generar nuevo, Desactivar enlace, QR compacto (96 px) con «Ampliar QR» y Descargar QR |
| Autorizaciones | acceso técnico (autorizado, no autorizado, no consta o no aplica) y autorización digital (pendiente, firmada…) | autorización de acceso técnico y autorización digital del cliente, completas, con historial de decisiones, comprobantes y acciones |
| Permanencia en taller | día X de Y, días restantes o vencidos, barra de progreso | medidor, fechas, plazo, avisos enviados, informe PDF y «Configurar plazo» |

## Estados de los correos (sin deducir nada)

Cada correo del sistema muestra su estado a partir de lo registrado: la copia archivada (`mail_archive`) y su seguimiento de entrega por destinatario (`mail_deliveries`, vinculado por `archive_id`). Los rebotes ya llegan relacionados con el mensaje original por su Message-ID.

| Estado | Cuándo |
|---|---|
| Registrado | La copia está guardada y todavía no hay respuesta del servidor. |
| Enviado al servidor | El servidor de correo lo aceptó; la entrega final no está confirmada. |
| Entregado | Solo con un informe real de entrega. |
| Fallido / Rebotado | El código y el motivo del rebote se muestran junto al mensaje. |
| Entrega demorada | El servidor informó una demora. |
| Estado desconocido | No consta la respuesta del servidor. |

- **WhatsApp y texto copiado** conservan su estado real; una apertura manual de WhatsApp nunca se presenta como enviada.
- **Correos enviados desde la comunicación de la orden:** no se repiten, porque ya figuran como correo del sistema.

## Comportamiento

- **Apertura automática:** los módulos están contraídos y solo se abren solos ante un **problema verificable**: correos fallidos o rebotados, o permanencia vencida.
- **Avisos sin abrir:** una autorización digital pendiente o una permanencia por vencer se destacan en ámbar sin abrirse.
- **Columnas independientes:** abrir un módulo solo desplaza el de debajo en su misma columna.
- **Teclado:** Enter abre el módulo y Escape lo cierra y devuelve el foco al encabezado.
- **Responsive:** dos columnas en escritorio, una por debajo de 900 px, botones táctiles en el celular y sin desplazamiento horizontal.
- **Movimiento:** transiciones de 200 ms; ninguna con «reducir movimiento».

## Servidor

Solo se añaden dos lecturas, sin escrituras ni migración:
- `mailing.history` incluye `deliveries`, `delivery` y `delivery_label`;
- el detalle de la orden incluye `messages`: los mensajes que no son correo, solo para administración y técnicos.

## Pruebas

- **Servidor:** `local/tests/test_executive_compact.py`, con las reglas de estado y el detalle de la orden, comprobando que la consulta no cambia nada.
- **Navegador:** `ex270`, 19/19 comprobaciones.
