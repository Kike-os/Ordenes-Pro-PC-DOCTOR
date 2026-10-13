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
