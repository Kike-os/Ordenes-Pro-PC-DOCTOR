# Acceso corporativo — revisión 10 de octubre de 2026

Se revisó la autenticación existente antes de modificarla. Se mantienen SQLite, cuentas, roles, sesiones y compatibilidad con hashes scrypt. La migración 012 añade únicamente la tabla de políticas y el migrador genera su respaldo habitual.

## Pantallas

Acceso, solicitud de recuperación y nueva contraseña comparten logo original, circuitos, azul oscuro y tarjeta de hasta 410 px. Validación local de formato, errores asociados a campos, navegación por teclado, iconos Eye/EyeOff de Lucide, controles mostrar/ocultar independientes y carga con bloqueo de envíos repetidos. La confirmación de formato no consulta cuentas.

## Controles

- Cinco fallos por identificador o IP. Ventana inicial y restricción usan la duración configurada (900–86400 segundos). El quinto fallo inicia una restricción completa. Las peticiones bloqueadas no extienden su vencimiento. La recuperación continúa disponible, con límites propios. Un acceso exitoso no borra el historial de fallos de la IP.
- Configuración administrativa con sesión y CSRF: duración de restricción, sesiones normales (1–8 horas), Recordarme (1–30 días), longitud mínima (12–128 caracteres). Aplica a nuevos accesos/cambios; las sesiones existentes conservan su vencimiento.
- Auditoría de fecha, resultado y contadores con identificadores e IP representados mediante SHA-256; retención de 90 días del registro de intentos. Confirmar esta retención y tratamiento de IP con la política de privacidad del establecimiento.
- SMTP autenticado con STARTTLS y validación de certificado. Correo multipart corporativo, token aleatorio de 256 bits almacenado como SHA-256, uso único, 20 minutos. Fuera de loopback se exige URL HTTPS para enviar el enlace.
- El correo se despacha en un hilo después de confirmar la transacción: la latencia SMTP no revela si existe la cuenta. Se auditan fallos de entrega. Los trabajos son en memoria: si el proceso termina durante un envío, se debe solicitar un nuevo enlace; para hosting con procesos efímeros se recomienda un servicio de trabajos persistentes antes de producción.
- Restablecer revoca todas las sesiones, invalida todos los tokens de la cuenta, limpia restricciones del identificador y envía aviso; no crea una sesión.
- Cookies HttpOnly y SameSite=Strict, Secure automático para APP_URL HTTPS; rotación al autenticar. Contraseñas nunca se almacenan en navegador.
- Instalar `local/requirements.txt` en el entorno del servicio habilita Argon2id (64 MiB, 3 iteraciones, paralelismo 1). Se conservan y verifican hashes scrypt anteriores; se actualizan tras un acceso correcto. Sin la dependencia se conserva scrypt existente (N=32768, r=8, p=3), sin cambiar cuentas.
- `PASSWORD_BLOCKLIST_FILE` permite una lista local de contraseñas comunes, una por línea. No envía contraseñas a servicios externos. Su mantenimiento es responsabilidad administrativa.

## Antibots

Configurar TURNSTILE_SITE_KEY y TURNSTILE_SECRET_KEY en el servidor. Con ambas claves, el inicio de sesión muestra la verificación Turnstile desde el primer intento y cada acceso exige token; con TURNSTILE_LOGIN_MODE=adaptive solo se exige tras dos fallos de IP. El token es verificado exclusivamente en el backend contra Siteverify, con comprobación de hostname y acción. También protege solicitudes reiteradas de recuperación. Las claves privadas nunca llegan al cliente. Sin ambas claves, los límites siguen activos y Configuración informa que antibots está pendiente. Ante fallos se ofrece esperar o recuperar contraseña; no hay bypass de límites.

Referencias: [Cloudflare, validación del token](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/) y [OWASP, autenticación y restricciones](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html).

## Validación y pendientes externos

La batería automatizada usa bases temporales, cuentas ficticias y SMTP simulado. Incluye acceso válido, respuestas genéricas, quinto fallo, vencimiento sin extensión, políticas/permisos/CSRF, token caducado o reutilizado, cambio efectivo de contraseña, revocación y ausencia de sesión automática, cookies y antibots verificado en servidor.

Chromium revisó las tres pantallas a 1440, 390 y 320 px: sin desplazamiento horizontal, etiquetas asociadas, logo original cargado y foco en el primer campo vacío. Capturas en `revision/auth-20261010/`.

La entrega real de correo, la verificación Turnstile con claves reales y TLS del hosting requieren configuración y prueba externa. No se afirma que estén operativos. La instalación local sigue usando HTTP en loopback; no equivale a producción HTTPS. No se modificaron agenda, Adi ni módulos operativos; se agregaron los controles de seguridad a Configuración.
