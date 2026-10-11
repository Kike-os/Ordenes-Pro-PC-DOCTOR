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

## Avisos de correo nuevo, cuota y preferencias (v2)

- **Detección**: el servidor consulta la bandeja de entrada por IMAP como mucho una vez por minuto y reconoce los mensajes nuevos por su UID (identificador persistente). La primera consulta solo fija el punto de partida: no anuncia el correo que ya existía. Cada mensaje se registra una sola vez en `system_state` (`mail_inbox`, `mail_events`), sin migraciones.
- **Avisos**: cada correo nuevo aparece en el Centro de Notificaciones y, si la persona lo permite, como aviso emergente con remitente, asunto, hora y «Ver correo». Solo los reciben quienes tienen acceso al buzón.
- **Sonidos**: desactivados al inicio. Se configuran en Correo → Preferencias (recibido, enviado, error, volumen, silenciar, probar). El timbre incluido es propio de Órdenes Pro; el audio original de Windows XP no se distribuye. Quien tenga una copia con licencia puede cargarla como archivo propio (WAV, MP3 u OGG de hasta 400 KB), que se guarda solo en su navegador.
- **Almacenamiento**: uso y cuota reales informados por el servidor mediante la extensión QUOTA de IMAP. Sin cuota configurada se muestra «Sin límite configurado»; si el servidor no informa, «Información no disponible». Al llegar al 75 % y al 90 % se genera un aviso. Nunca se eliminan correos automáticamente.
- **Carpetas**: si el servidor tiene dos carpetas con la misma función (por ejemplo `INBOX.spam`, marcada como oficial, e `INBOX.Junk`), se muestran las dos; la adicional conserva su nombre real. No se fusionan ni se mueven mensajes.
- **Pendiente**: consulta por UAPI de cPanel (`Email::get_disk_usage`), que requiere un token de API creado por la administración del hosting; sincronización por Cron; formato enriquecido en el redactor.

## Almacenamiento del buzón: fuentes y diagnóstico

El indicador usa únicamente datos reales, en este orden:

1. **cPanel UAPI** `Email::list_pops_with_disk` (solo lectura, HTTPS por el puerto 2083 con certificado verificado), si existen `CPANEL_HOST`, `CPANEL_USER` y `CPANEL_TOKEN` en el servidor. `CPANEL_USER` es el usuario propietario de cPanel, no la cuenta de correo, y nunca se usa la contraseña del buzón.
2. **Servidor de correo** (extensión QUOTA de IMAP), que informa el uso y la cuota de la misma cuenta.

Se consulta al abrir Mail Pro, cada minuto, al sincronizar y con el botón «Actualizar almacenamiento». El servidor guarda la lectura un minuto para no repetir consultas. Si todo falla, se muestra la última lectura válida de las últimas 24 horas marcada como desactualizada, o el motivo técnico concreto (sin configurar, red, certificado, token rechazado, sin permiso, dominio sin cuentas, cuenta de otro usuario de cPanel, respuesta no reconocida).

Para activar cPanel: cPanel → Seguridad → **Administrar tokens de API** → crear un token; guardar `CPANEL_HOST` (por ejemplo `mail.ecuadorpcdoctor.com`), `CPANEL_USER` y `CPANEL_TOKEN` en `local/.env` y en las variables de Vercel; comprobar en Configuración → Correo y servicios → **Probar almacenamiento (cPanel)**.

## Borradores

Se guardan en la carpeta de borradores del servidor (IMAP). Al reabrir un borrador y guardarlo de nuevo, o al enviarlo, la versión anterior se reemplaza: solo se elimina un mensaje que el servidor tiene marcado como borrador, nunca otro correo.

## Prueba manual de sonido y navegadores

En Correo → Preferencias → «Prueba de sonido y notificaciones»: «Probar sonido» debe mostrar «Motor de audio: en marcha» y «Reproductor invocado»; si no se oye, revisar el volumen del equipo y el silencio de la pestaña. «Probar aviso de escritorio» pide el permiso del navegador la primera vez. Repetir en Chrome, Firefox y Edge.
