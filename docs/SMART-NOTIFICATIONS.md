# ADI Smart Notifications Premium 3.0

Rediseño de «Avisos al cliente» con un solo componente: `waNoticeList` y `waCounts` en `local/static/app.js`, con estilos `.wan3` y `.wan-counts` en `app.css`.

## Dónde se usa

- **Orden de reparación:** la tarjeta «Avisos al cliente» con los avisos por WhatsApp.
- **Seguimiento de repuestos:** los avisos de cada repuesto.
- **WhatsApp Business:** el historial de envíos.
- **Historial de correos de la orden:** incluye presupuestos, recibos, cobros, facturas y demás correos de la orden.
- **Citas:** los avisos al cliente por correo.

## Estados

Solo se muestran estados reales:
- **WhatsApp:** pendiente, enviando, enviado, entregado, leído, fallido y omitido, según la respuesta y los avisos de Meta.
- **Correo:** solo se sabe si el servidor lo aceptó (enviado) o lo rechazó (fallido). Por eso nunca se muestra «entregado» ni «leído» en un correo.

Los contadores por estado filtran la lista: un clic muestra solo ese estado y otro clic vuelve a mostrar todos.

## Diagnóstico de ADI

Aparece en los avisos fallidos u omitidos y tiene tres partes:
- la **categoría**: configuración, plantilla, número del cliente, autorización, límite, servicio de Meta, conexión, datos, aviso que dejó de corresponder o envío sin confirmar;
- la **causa**, que es la respuesta real del proveedor con su código;
- **qué hacer**, con la acción recomendada.

Si el aviso no trae categoría, se deduce del código de error de Meta. ADI no inventa causas y no reenvía nada por su cuenta.

## Reintentos y duplicados

- **Reintento controlado:** el botón aparece solo si el servidor lo permite (tope de intentos y nunca para números sin WhatsApp). Se desactiva mientras espera la respuesta, para que no haya envíos duplicados.
- **Envíos interrumpidos:** no se reenvían solos, porque no se sabe si Meta los aceptó. Administración puede marcarlos como no enviados.
- **Avisos históricos omitidos:** conservan su estado original y nunca se reenvían automáticamente.

## Historial de intentos

La migración 129 crea `whatsapp_outbox_attempts`, con una fila por intento o respuesta del proveedor: enviado, fallido, omitido, entregado o leído, con su código y su detalle.

Se consulta en «Detalles» de cada aviso (`GET /api/whatsapp/outbox/<id>/attempts`, solo personal). Los avisos anteriores a la versión 1.5.356 solo conservan su último resultado.
