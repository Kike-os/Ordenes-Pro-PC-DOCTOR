# Comprobante de recepción con Políticas de Reparaciones y envío por correo — 11/10/2026

## Documento

El comprobante A4 existente (`local/receipt_pdf.py`: logo original, datos de la orden, cliente, equipo, condiciones de recepción, QR) incorpora al final una página propia con las **Políticas de Reparaciones**.

- El texto vive en `local/data/repair-policies.json`, literal, tal como lo entregó PC-DOCTOR S.A. el 11/10/2026, incluida la cláusula 5.2 «Muestras claras de intento de desarme del producto.». No se resume ni se reescribe. Cambiarlo exige una versión nueva aprobada por la empresa.
- Cada documento indica la versión de las políticas y su huella SHA-256.
- Incluir las políticas en el comprobante **no registra aceptación** del cliente. La aceptación sigue dependiendo de las condiciones publicadas por administración (ver `CONDICIONES.md`) o de la firma electrónica cuando exista.
- Revisión jurídica pendiente, sin alterar el texto: la cláusula 2 (retener o rematar el producto a los 3 meses) debería validarse con asesoría legal antes de aplicarse.

## Envío

- Al guardar una orden, la interfaz pide al servidor el envío automático (`POST /api/orders/<id>/receipt-mail`, modo `auto`). El servidor genera el PDF, lo adjunta y lo envía por el SMTP de Mail Pro con la firma corporativa.
- Asunto: «Confirmación de recepción — Orden [NÚMERO] | PC-DOCTOR S.A.».
- Un envío automático por orden; los reenvíos son una acción expresa desde el detalle de la orden (límite de 30 por usuario y hora).
- Sin correo del cliente: «Pendiente de envío — Sin correo electrónico». Sin correo del sistema: no se envía. Si SMTP falla, la orden queda guardada y el error registrado.
- «Enviado» significa que el servidor de correo aceptó el mensaje; no acredita lectura ni recepción.
- Cada intento queda en `order_receipt_mail` (migración 027): modo, destinatario, resultado, detalle, huella del PDF, versión de las políticas, usuario y fecha. El envío correcto también se anota en el historial de la orden.
- Se desactiva en Configuración → «Comprobante de recepción por correo».

## Pendiente

Prueba de envío real a un buzón de prueba (en las pruebas automáticas el SMTP está simulado) y almacenamiento del PDF como archivo: hoy se regenera a partir de los datos de la orden y se conserva su huella.

## Cambios de la 1.5.46

- El envío automático lo hace el **servidor** al guardar la orden (ya no depende de una segunda petición del navegador). La orden se confirma en la base antes de intentar el correo: si el envío falla, la orden permanece y se reenvía desde su detalle.
- Asunto: «Confirmación de recepción de equipo | Orden N.º [NÚMERO]». Texto y firma según lo indicado por PC-DOCTOR S.A. el 11/10/2026.
- El PDF incluye la sección «Autorizaciones registradas» (acceso técnico y operaciones que modifican o eliminan datos) cuando constan en la orden.
- Configuración → «Notificaciones automáticas por correo»: interruptor, «Enviar correo de prueba» (al propio buzón del sistema, nunca a un cliente) e historial de los últimos 30 envíos con sus errores.
- Estados: Pendiente de envío, En proceso, Enviado al servidor de correo, Error de envío. No existe «Entregado»: el SMTP del buzón no informa la entrega; los rebotes se ven en Mail Pro.
- Reintentos: un envío automático por orden; los siguientes son reenvíos expresos (30 por usuario y hora).

## Nombres de archivo y formato A4 (1.5.58)

- El ticket se descarga como `CÓDIGO-TICKET.pdf` y el comprobante como `CÓDIGO-COMPROBANTE-DE-RECEPCION.pdf` (cabecera `Content-Disposition`, vista previa y adjunto del correo).
- El comprobante A4 se compone en dos páginas: datos, autorizaciones y constancia de recepción en la primera; condiciones aceptadas (solo si existen) y Políticas de Reparaciones en dos columnas en la segunda. El texto de las políticas es literal; si no cabe se reduce el cuerpo a 7,5 pt antes de abrir otra página.
