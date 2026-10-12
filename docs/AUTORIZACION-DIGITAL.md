# Autorización digital del cliente

El cliente acepta o rechaza las autorizaciones de su orden desde un enlace seguro, sin intervención del técnico. Disponible desde la 1.5.82 (`local/client_authorization.py`, migración 033).

**No es una firma electrónica certificada.** Registra las decisiones del cliente con fecha, hora y el método de verificación empleado, y así lo dicen la página, el aviso y el comprobante. Si un trámite exige firma certificada conforme a la normativa ecuatoriana, hace falta integrar un proveedor acreditado.

## Flujo

1. **Envío.** En el detalle de la orden, «Enviar enlace de autorización» manda al correo del cliente un enlace HTTPS aleatorio y un código QR adjunto. El enlace caduca en 7 días y un enlace nuevo deja sin efecto el anterior. Requiere que el cliente tenga correo e identificación registrados.
2. **Identidad.** La página muestra la identificación enmascarada (dos primeros dígitos y asteriscos) y pide los últimos cuatro. Cinco intentos fallidos bloquean el enlace.
3. **Código.** Se envía al correo registrado un código de seis dígitos que caduca en 10 minutos (cinco intentos por código, cinco códigos por enlace).
4. **Decisiones.** Se muestran las condiciones publicadas (si existe una versión vigente; su aceptación es entonces obligatoria) y cuatro autorizaciones: servicio solicitado, sistema operativo, archivos y respaldos, y formateo o eliminación de datos. Cada una exige elegir «Autorizo» o «No autorizo»; nada viene marcado.
5. **Firma.** «Confirmar y firmar autorización» guarda la evidencia: orden, versión y huella de las condiciones, decisiones, observaciones, fechas de verificación y firma, método, correo verificado, IP y navegador. Se calcula la huella SHA-256 de esa evidencia; cualquier cambio posterior deja de coincidir.
6. **Constancia.** El cliente descarga su comprobante PDF; el personal lo ve en la orden junto con el resultado, y el buzón administrativo recibe un aviso. El historial de la orden registra el envío y la firma.

## Límites y decisiones

- **Apagado por defecto:** registrar una orden no envía nada al cliente. Administración puede activar «Enviar este enlace automáticamente al registrar cada orden nueva» desde el detalle de cualquier orden.
- **Sin WhatsApp:** el aviso llega solo por correo; WhatsApp requiere la API de WhatsApp Business de Meta.
- **Condiciones:** mientras no haya una versión publicada, la autorización no incluye aceptación de condiciones y el comprobante lo indica.
- Las autorizaciones registradas por el técnico en recepción no se modifican; esta es una constancia adicional del propio cliente.
- En la base solo se guardan las huellas del enlace, del código y de la verificación; nunca sus valores.
