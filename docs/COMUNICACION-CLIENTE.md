# Seguimiento técnico y comunicación con el cliente

Cada orden tiene un centro de seguimiento (desde la 1.5.215) y una ventana **«Comunicación con el cliente»** (desde la 1.5.216).

## Seguimientos

- Un seguimiento tiene tipo, prioridad, próxima acción, presupuesto relacionado y evidencias (JPG, PNG, WEBP o PDF; máximo 3 de 900 KB).
- Separa siempre dos clases de información:
  - **Solo para el taller** (`internal_note`): nunca se publica, se copia ni se envía.
  - **Para el cliente** (`client_message` y `recommendation`): es lo único que puede comunicarse. Con «Mostrar en el enlace público» aparece además en «Novedades del servicio».
- Los seguimientos, las evidencias y los mensajes registrados no se modifican ni se borran (lo impiden triggers de la base). Para corregir un seguimiento se registra otro que lo referencia (`corrects_id`).

## Ventana «Comunicación con el cliente»

Se abre con «Preparar mensaje al cliente» en el historial de la orden, o con «Preparar mensaje» en un seguimiento.

### Qué se comunica

La opción «Información que desea comunicar» ofrece cuatro modos:

| Modo | Qué hace |
| --- | --- |
| Último seguimiento comunicable | Toma el seguimiento más reciente que tiene mensaje o recomendación para el cliente. Omite los seguimientos que solo tienen nota interna, los de pago y los que fueron corregidos. |
| Seleccionar un seguimiento anterior | Usa un solo seguimiento, elegido de una lista ordenada del más reciente al más antiguo. |
| Seleccionar varias novedades | Usa varios seguimientos. Se redactan en orden cronológico y cada frase aparece una sola vez. |
| Preparar mensaje manual | No usa ningún seguimiento. El borrador lleva un espacio entre corchetes que hay que completar. |

**Registros técnicos anteriores.** Los comentarios técnicos registrados antes de la 1.5.215 están en el historial y eran internos. La lista los muestra como «Interno anterior». Solo se usan si el técnico los elige y confirma; el borrador avisa entonces que hay que revisar lo que se comunica.

**Nunca se usan:**
- los avisos del sistema (correos enviados, enlaces, decisiones de presupuesto);
- los hallazgos internos de la orden, que se muestran solo como referencia.

### Plantillas y costo

Hay diez plantillas: diagnóstico técnico, novedad importante, reparación en proceso, repuesto necesario, presupuesto pendiente, solicitud de autorización, reparación terminada, pruebas realizadas, equipo listo para retirar y recordatorio de retiro.

Cada borrador incluye:
- saludo;
- número de orden, marca y modelo;
- las novedades y recomendaciones elegidas;
- el cierre de la plantilla;
- el enlace de seguimiento, si está activo;
- los datos de contacto.

**Reglas del costo:**
- Por defecto, el costo solo se incluye en «Solicitud de autorización» y «Presupuesto pendiente», y solo si el presupuesto fue enviado y espera respuesta.
- Un presupuesto en borrador o ya aprobado se incluye únicamente si se marca «Incluir el costo en el mensaje». Con un borrador aparece además un aviso.
- Un presupuesto cancelado o rechazado nunca se incluye.

**Edición del texto.** Si el texto se editó a mano, regenerarlo o cambiar la plantilla, la selección o el costo pide confirmación antes de reemplazarlo. Cerrar la ventana con cambios propios también pide confirmación.

### Estados de cada comunicación

| Estado | Significado |
| --- | --- |
| Borrador · sin registrar | El texto está en el editor y todavía no se registró nada. |
| Preparado (copiado, no enviado) | El texto se copió de verdad al portapapeles. Si la copia falla, no se registra. |
| Abierto en WhatsApp (manual, sin confirmación) | Se abrió `wa.me` con el número del cliente. No confirma que el mensaje se haya enviado. |
| Enviado | WhatsApp Business devolvió el identificador del mensaje, o el servidor de correo (Mail Pro) lo aceptó. |
| Entregado / Leído | Solo con el aviso firmado de WhatsApp (webhook). El estado nunca retrocede. |
| Fallido | El proveedor o el servidor rechazaron el envío. Se puede reintentar con el mismo registro, que reenvía el texto registrado y suma un intento, sin crear un mensaje nuevo. |

Cada comunicación registra:
- fecha y hora;
- usuario;
- canal y destinatario;
- asunto;
- el texto exacto;
- los seguimientos usados (`sources`);
- el resultado y el identificador del proveedor.

Las comunicaciones aparecen en el historial de la orden, en el filtro «Comunicación».

**Adjuntos del correo:**
- solo las evidencias marcadas como visibles para el cliente;
- el PDF de un presupuesto ya enviado o decidido (nunca un borrador), con la identificación enmascarada.

## WhatsApp Business (API oficial de Meta)

Variables de entorno (en Vercel, nunca en el código):

| Variable | Uso |
| --- | --- |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Activan el envío. |
| `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` | Permiten verificar y recibir los avisos de entrega y lectura. |
| `WHATSAPP_API_VERSION` | Opcional. Por defecto `v21.0`. |
| `WHATSAPP_TEMPLATE_NAME`, `WHATSAPP_TEMPLATE_LANG` | Opcionales (idioma `es` por defecto). Definen la plantilla aprobada para escribir fuera de la ventana de 24 horas. Debe tener dos variables: `{{1}}` = nombre del cliente y `{{2}}` = número de orden. |

La dirección de avisos que se configura en Meta es `https://<dominio>/api/public/whatsapp/webhook`.

Sin estas variables, la ventana solo ofrece «Abrir WhatsApp», que queda registrado como apertura manual.
