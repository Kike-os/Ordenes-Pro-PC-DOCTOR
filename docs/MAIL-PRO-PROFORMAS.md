# Envío de proformas con Mail Pro

Base publicada **1.5.359**. Corrección preparada en **1.5.360**.

## Operación

En **Facturación → Proformas**, genera el enlace y abre **Enviar por correo**. El cuadro usa el remitente corporativo configurado en Mail Pro y el correo de la ficha del cliente. Si cambias la dirección, confirma que el destinatario está autorizado. El asunto identifica la proforma y el mensaje es editable. La vista previa muestra el enlace seguro y el nombre del PDF adjunto.

El servidor genera el PDF de cliente, añade el enlace vigente y envía el mensaje por el transporte SMTP de Mail Pro. El enlace conserva la verificación de identidad y requiere que la migración 130 de la versión anterior esté instalada. Las credenciales se resuelven en el servidor.

## Historial y reintentos

Cada intento se registra en Mail Pro y en la proforma con remitente, destinatario, fecha, usuario, adjunto, identificador de mensaje y estado. El enlace se omite de la copia archivada. La aceptación SMTP y la confirmación de entrega se muestran como estados distintos. La confirmación de entrega requiere evidencia del proveedor.

Una proforma admite un envío aceptado por enlace. Si el servidor rechaza el correo, puedes corregir la dirección y reintentar. Si SMTP interrumpe la transmisión sin confirmar el resultado, el sistema bloquea el reintento y la generación de otro enlace hasta que haya evidencia de estado o se resuelva la incidencia en Mail Pro.

ADI obtiene el estado de configuración y los recuentos de incidencias de las últimas 24 horas desde los registros de entrega. Se utiliza el Centro de Entrega para revisar respuestas SMTP y avisos del proveedor.

## Auditoría de documentos

- Proformas usaban `mailto:` para enviar un documento. El botón ahora utiliza el flujo interno.
- Presupuestos, autorizaciones y comprobantes de las órdenes, facturas, recibos, confirmaciones de citas y avisos de licencias cuentan con flujos de correo del servidor. Se mantuvieron los permisos y las configuraciones de cada uno.
- Los estados de cuenta e informes revisados tienen acciones de descarga. Tampoco se encontró un `mailto:` documental para certificados de garantía. Las referencias `mailto:` restantes corresponden a accesos de contacto, privacidad o firmas.

## Pruebas y publicación

Pasaron 70 pruebas dirigidas de proformas, Mail Pro, seguimiento, ADI y presupuestos. Las pruebas automatizadas usan SQLite temporal, destinatarios ficticios y SMTP simulado. Cubren el contenido MIME, el PDF, el enlace privado, el destinatario alternativo autorizado, el rechazo y reintento, la concurrencia, la falta de confirmación SMTP y la actualización de estado por evidencia de entrega. El formulario se revisó en Chromium a 320, 390, 768 y 1280 px. También se corrigió un fallo del PDF público al omitir la cédula o RUC.

Esta corrección usa las tablas vigentes de Mail Pro y carece de migraciones nuevas. Para validar el transporte real, envía una proforma ficticia exclusivamente a una cuenta de prueba autorizada desde un entorno con Mail Pro configurado. Conserva la versión anterior como destino de reversión hasta verificar ese envío.
