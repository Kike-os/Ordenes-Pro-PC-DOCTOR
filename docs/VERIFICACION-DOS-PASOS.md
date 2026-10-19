# Verificación en dos pasos

Segundo paso opcional al iniciar sesión, para el personal (administración y técnicos). Además de la contraseña se pide un código de 6 dígitos de una aplicación de autenticación (Google Authenticator, Microsoft Authenticator, Authy o cualquier otra compatible con TOTP, RFC 6238). No depende de servicios externos, SMS ni correo. Migración 053; módulo `local/two_factor.py`.

## Para el usuario

- **Activar:** menú de la cuenta → «Verificación en dos pasos» (administración también la tiene en Configuración → Seguridad y sesiones). Pide la contraseña actual, muestra un código QR y la clave escrita, y se activa solo cuando se escribe un código válido de la aplicación. Hasta ese momento no cambia nada en el acceso.
- **Códigos de recuperación:** al activar se muestran 10 códigos, una sola vez. Cada uno sirve una vez y permite entrar si no se tiene el teléfono. Se pueden generar nuevos (los anteriores dejan de valer) con contraseña y código.
- **Iniciar sesión:** tras la contraseña correcta aparece «Verificación en dos pasos». Cinco códigos incorrectos o cinco minutos sin completarla obligan a volver a escribir la contraseña.
- **Desactivar:** pide contraseña y un código vigente.

## Si alguien pierde el teléfono

1. Entrar con un código de recuperación y generar códigos nuevos o desactivar y volver a activar.
2. Sin códigos: otro administrador usa «Quitar verificación en dos pasos» en Configuración → Usuarios y accesos. Cierra las sesiones de esa cuenta; la persona entra con su contraseña y la activa de nuevo.
3. Si es el único administrador y no tiene códigos: desde el servidor, `vercel env run -e production -- python maintenance/second-step-reset.py <usuario> --confirmar`. No cambia la contraseña y queda auditado.

## Seguridad

- La contraseña sigue siendo obligatoria; el código nunca la sustituye. Con contraseña incorrecta la respuesta es la de siempre: no revela si la cuenta tiene segundo paso.
- La contraseña correcta no abre sesión: reserva un intento de corta duración (se guarda solo su huella). La sesión se crea al validar el código.
- Se acepta el código vigente y el inmediato anterior o siguiente (relojes con hasta 30 s de diferencia). Un código ya usado no vuelve a servir.
- Límites: 5 intentos por verificación, 20 por conexión cada 15 minutos, y 12 operaciones de configuración por usuario cada 15 minutos.
- Al activar se cierran las demás sesiones de la cuenta. Todo queda en la auditoría (activación, desactivación, códigos renovados, acceso con código de recuperación, retiro por administración); nunca se registran códigos.
- Los códigos de recuperación se guardan como huella. El secreto de la aplicación se guarda en la base tal cual, porque el algoritmo lo necesita para calcular los códigos: quien tenga acceso de lectura a la base podría generarlos (seguiría necesitando la contraseña). La restauración de un respaldo restaura también ese secreto.

## Límites

- No es obligatoria: cada persona decide activarla. No hay «recordar este equipo»: el código se pide en cada inicio de sesión.
- La recuperación de contraseña por correo no quita el segundo paso.

## Rediseño y refuerzo (1.5.164)

- **Cifrado del secreto TOTP en la base**: valor `enc1:` con nonce aleatorio, cifrado en modo contador con HMAC-SHA256 y autenticación encrypt-then-MAC (biblioteca estándar). La clave maestra está fuera de la base: `MFA_ENCRYPTION_KEY` (secreto de Vercel, solo producción; nunca se muestra) y, en el servidor local, `mfa.key` (0600) en la carpeta de datos. Sin clave en Vercel no se inicia ninguna configuración (aviso claro). Un secreto anterior sin cifrar se lee y se vuelve a guardar cifrado al usarse.
- **Estados reales**: No configurado, Configuración pendiente (se inició sin verificar; continuar genera una clave nueva e invalida la anterior), Protección activa; «Error de verificación» se muestra en el paso 2.
- **Asistente**: paso 1 (QR centrado, aplicaciones compatibles, clave manual oculta con Mostrar/Ocultar y Copiar) y paso 2 (campo de 6 dígitos solo numérico, admite pegar el código completo y verifica al completarlo). La clave solo vive en la memoria de la ventana; nunca en el almacenamiento del navegador. Tras activar no vuelven a mostrarse ni el QR ni la clave.
- **Códigos de recuperación**: se muestran una vez, con Copiar y Descargar (.txt).
- **Auditoría**: se añaden los intentos fallidos al activar (`second_step_confirm_failed`) y al desactivar o renovar códigos (`second_step_check_failed`), además de los ya existentes (activación, desactivación, inicio de sesión con código o con código de recuperación, caducidad).

## Corrección del QR (1.5.165)

- **Causa real**: el QR se generaba como SVG de tamaño fijo (488 × 488 px) **sin `viewBox`**; al mostrarlo en un cuadro de unos 156 px el navegador no lo reducía, lo recortaba (solo se veía la esquina superior izquierda) y no se podía escanear.
- **Corrección**: `two_factor.qr_svg` genera un SVG escalable (con `viewBox`, sin ancho ni alto fijos), negro sobre blanco, corrección de errores M y zona blanca de 4 módulos, con la biblioteca segno; si no sale en formato escalable, el servidor responde con un aviso y la opción de reintentar. El QR general (`reception.qr_image`) también incorpora `viewBox` sin cambiar su tamaño propio.
- **URI**: `otpauth://totp/<emisor>:<cuenta>?secret=…&issuer=…&algorithm=SHA1&digits=6&period=30` (RFC 6238; tolerancia de ±1 intervalo; un código aceptado no sirve dos veces).
- **Regenerar**: «Generar nuevo código QR» crea una clave nueva e invalida la pendiente anterior. Regenerar y confirmar exigen el comprobante de configuración emitido tras la contraseña (15 minutos, solo se guarda su huella); con la verificación ya activa no se puede regenerar ni reiniciar.
- **Pruebas**: el QR se rasteriza a 220 px y se decodifica con `zbarimg`; la URI leída contiene el mismo secreto que el pendiente en el servidor (descifrado), el emisor, la cuenta, 6 dígitos, 30 s y SHA1.
