# PC-DOCTOR Mail Pro

Gestor de correo integrado en Órdenes Pro. **Lee el buzón en vivo** desde el servidor de correo (IMAP) y envía por SMTP; los mensajes no se copian a la base de datos. En la base solo se guardan los vínculos con órdenes (`mail_links`), el control de envíos (`mail_outbox`), la firma y el contador de no leídos.

## Servidor

| Dato | Valor |
| --- | --- |
| IMAP | `mail.ecuadorpcdoctor.com`, puerto 993, SSL/TLS |
| SMTP | `mail.ecuadorpcdoctor.com`, puerto 465, SSL/TLS |
| Usuario | dirección completa del buzón |

cPanel muestra `ordenes-pro.ecuadorpcdoctor.com` como servidor, pero ese nombre apunta a Vercel (la página web) y no responde en 993 ni 465. `mail.ecuadorpcdoctor.com` es el mismo servidor de correo y su certificado es válido.

**Pendiente de DNS:** `ordenes-pro.ecuadorpcdoctor.com` no tiene registro MX. Sin él, el correo que llega desde fuera a `…@ordenes-pro.ecuadorpcdoctor.com` se dirige al registro A (Vercel) y no entra al buzón. Crear en Tecnoweb un MX de `ordenes-pro` hacia `mail.ecuadorpcdoctor.com` y revisar SPF/DKIM.

## Variables de entorno

`MAIL_IMAP_HOST`, `MAIL_IMAP_PORT`, `MAIL_SMTP_HOST`, `MAIL_SMTP_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`. Opcional: `MAIL_ALLOW_TECHNICIANS=true` da acceso al buzón a los técnicos (por defecto solo administración). Solo se aceptan 993 y 465/587; la verificación de certificados no se puede desactivar. La contraseña nunca llega al navegador ni a los registros.

## Funciones

- Carpetas reales del buzón, con contador de no leídos y vista «Destacados».
- Lista paginada, búsqueda en la carpeta, lectura con HTML saneado (lista blanca, sin estilos ni scripts) e **imágenes remotas bloqueadas**.
- Adjuntos: descarga autenticada, siempre como archivo binario.
- Redactar, responder, responder a todos y reenviar, con `Message-ID`, `In-Reply-To` y `References`; hasta 3,5 MB de adjuntos y 20 destinatarios.
- Un mensaje solo se da por enviado cuando el servidor SMTP lo acepta; después se guarda copia en Enviados. Una clave por redacción evita envíos duplicados y permite reintentar un fallo. Límite de 40 envíos por hora y usuario.
- Borradores guardados en la carpeta de borradores del servidor.
- Estado de lectura y destacado sincronizados con el servidor.
- Identifica al cliente por el correo del remitente, vincula conversaciones a órdenes y muestra las comunicaciones en el detalle de la orden, desde donde se puede escribir con plantillas.
- Aviso de correos sin leer en el Centro de Notificaciones (consulta al servidor como mucho cada tres minutos).
- En Configuración → Correo y servicios: estado, «Probar IMAP», «Probar SMTP» y firma empresarial.

## No incluido en esta etapa

- Eliminar, mover o archivar mensajes (por decisión: la primera etapa no borra ni mueve originales).
- Varias cuentas con credenciales cifradas en la base; hoy es una cuenta por variables de entorno.
- Sincronización programada: no hace falta porque se lee en vivo; no hay copia local para búsquedas sin conexión.
- Al enviar desde un borrador, el borrador anterior permanece en su carpeta.

## Pruebas desde la terminal

```bash
cd local
python mail_pro.py estado
python mail_pro.py test-imap
python mail_pro.py test-smtp
python mail_pro.py test-smtp --enviar-a destino@autorizado --confirmar
```

## Pruebas reales realizadas (11 de octubre de 2026, instalación local)

Conexión y autenticación IMAP y SMTP; listado de 7 carpetas; lectura de un mensaje existente con 4 adjuntos e imagen remota bloqueada; envío de un mensaje con adjunto a la propia cuenta, recibido en la bandeja y con copia en Enviados; descarga del adjunto; respuesta con cita y cabeceras de hilo; destacado; búsqueda; borrador; vínculo con una orden.

No probado: recepción desde un dominio externo (depende del MX), entrega a un destinatario externo, y el funcionamiento desde Vercel con sesión iniciada.
