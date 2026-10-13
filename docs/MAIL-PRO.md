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
- Redactar, responder, responder a todos y reenviar, con `Message-ID`, `In-Reply-To` y `References`; hasta 3,1 MB de adjuntos (límite real de la infraestructura; desde la 1.5.83 también se guardan en los borradores) y 20 destinatarios.
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

## Firma corporativa

Configuración → Correo y servicios → **Firmas de correo**: nombre, cargo, descripción, teléfono, correo, web y dirección del buzón remitente, con vista previa, activación y aplicación a correos nuevos y a respuestas o reenvíos. El HTML de la firma lo compone siempre el servidor a partir de esos datos (tablas y estilos en línea, sin JavaScript); no se acepta HTML libre. El logo es una copia reducida del original (`local/static/logo-firma.png`), incrustada en cada mensaje como imagen relacionada (CID), por lo que no depende de una URL externa. Los mensajes con firma salen como `multipart/alternative` (texto y HTML). En respuestas y reenvíos la firma queda después del texto escrito y antes del mensaje citado. En el redactor se puede desmarcar «Incluir la firma corporativa» para ese envío.

## Envío, rechazos y correos devueltos

- **Al enviar**: «Envío aceptado por el servidor» significa solo que el servidor SMTP lo aceptó, no que llegó al buzón del destinatario. Los rechazos se distinguen: credenciales, destinatario rechazado (5xx), error temporal (4xx) y rechazo del mensaje. El código de respuesta se anota en el registro del servidor, sin datos personales.
- **Devoluciones (DSN)**: al sincronizar, los mensajes nuevos con estructura `multipart/report; report-type=delivery-status` se analizan (`message/delivery-status`): destinatario, acción (fallo o retraso), estado y diagnóstico. No se usa el asunto. Si el informe trae el `Message-ID` original y coincide con un envío de la aplicación, se indica la relación; si no, se avisa de que no pudo relacionarse. Cada informe se registra una sola vez y genera un aviso («Correo devuelto» o «Entrega retrasada»). Nunca se reenvía nada automáticamente.
- **Pendiente**: comprobación DNS/MX del dominio antes de enviar, estado de entrega visible en cada mensaje de Enviados, e indicador de devolución en la ficha del cliente.

## Capacidades IMAP tras el inicio de sesión (1.5.69)

Dovecot/cPanel solo anuncian `MOVE` y `UIDPLUS` después de autenticar. Las versiones de Python anteriores a 3.14 (la de Vercel) conservan la lista previa al login, por lo que en producción el sistema rechazaba mover, archivar y eliminar con «El servidor no permite mover mensajes de forma segura». `open_imap()` pide ahora las capacidades explícitamente tras iniciar sesión (`refresh_capabilities`); si la consulta falla conserva la lista anterior.

Con `MOVE` se usa `UID MOVE`. Sin `MOVE` pero con `UIDPLUS` se copia, y solo si la copia termina bien se retiran exactamente esos UID del origen. Sin ninguna de las dos no se mueve nada y se avisa de que el original permanece en su carpeta.

La eliminación definitiva (solo desde la Papelera) usa un modal propio: no se cierra ni anuncia éxito hasta que el servidor responde, y un fallo se muestra dentro del modal conservando el mensaje. El mensaje abierto tiene botón «Eliminar» (a la Papelera, con Deshacer) y, en la Papelera, «Restaurar» y «Eliminar definitivamente».

## Adjuntos del redactor (1.5.83)

- Lista propia de archivos con icono, formato y tamaño; se quitan uno a uno. Selección múltiple y arrastrar y soltar.
- Barra de capacidad «Archivos adjuntos — X de 3,1 MB» con estados: disponible, cerca del límite (80 %), límite alcanzado y archivo demasiado grande. Un archivo que no cabe no se añade y se explica el motivo.
- **Límite real: 3,1 MB por mensaje.** Vercel no admite peticiones de más de 4,5 MB y los adjuntos viajan en Base64 (un tercio más grandes). El límite anterior de 3,5 MB podía fallar en producción. Para llegar a 25 MB haría falta un almacenamiento externo de archivos.
- «Comprimir en ZIP» (en el navegador, sin bibliotecas ni servicios externos): reúne los archivos en `adjuntos-PC-DOCTOR.zip`, comprime solo lo que no viene ya comprimido (no toca JPEG, PDF, ZIP, etc.) y muestra el tamaño original y el final. No reduce calidad ni altera el contenido. No genera RAR (formato propietario).
- Los adjuntos se guardan con el borrador en el servidor de correo y se recuperan al reabrirlo.

## Bandeja: acciones en su propia columna (rama `correos-adi`, pendiente de aprobación)

Antes, los botones rápidos se dibujaban con posición absoluta encima del asunto y la vista previa al pasar el cursor. Ahora cada fila es una rejilla de tres columnas: selección · remitente, fecha, asunto y vista previa · acciones. Las acciones tienen espacio propio a la derecha y el texto se trunca con puntos suspensivos antes de llegar a ellas.

- A la vista: destacar y eliminar (o restaurar en la Papelera). En listas estrechas y pantallas táctiles solo destacar y «⋯»; eliminar sigue en el menú.
- Menú «⋯»: responder, marcar como leído o no leído, destacar, archivar, mover a carpeta y enviar a la Papelera. Se abre junto al botón, fijado a la ventana (no se recorta dentro de la lista), y hacia arriba cuando no cabe debajo.
- Teclado: el botón anuncia el menú (`aria-haspopup`, `aria-expanded`); flechas, Inicio y Fin recorren las opciones; Escape cierra y devuelve el foco; Tab sale.
- La fecha ya no se oculta al pasar el cursor. Los botones no desplazan nada al aparecer: siempre ocupan su sitio.

Comprobado con correos simulados en 1440, 1180, 1024, 768, 390 y 320 px y con zoom de 80 % y 125 %: sin solapes, botones alineados y acciones operativas (destacar, eliminar, archivar, leído/no leído, mover). No se pudo comprobar en este entorno la variante con ratón (30 px y eliminar a la vista), porque el navegador de pruebas se declara táctil; usa la misma rejilla.
