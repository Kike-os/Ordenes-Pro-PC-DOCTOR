# Recordar mi sesión y dispositivos de confianza

Rama de pruebas `sesion-confianza`. Migración 063 (solo añade columnas a `sessions` y la tabla `trusted_devices`).

## Recordar mi sesión
- Casilla «Recordar mi sesión» en el inicio de sesión. Activada: la sesión dura hasta 30 días (límite de «Recordarme (días)» en
  Configuración, máximo 30), sobrevive al cierre del navegador y **no** caduca por inactividad. Desactivada: sesión de hasta 8 horas,
  que termina al cerrar el navegador y se cierra tras 15 minutos sin actividad (como antes).
- **Cambio de comportamiento:** antes el cierre por inactividad de 15 minutos se aplicaba también a las sesiones recordadas.
- Cookie HttpOnly, SameSite=Strict y Secure con HTTPS. Las contraseñas nunca se guardan en el navegador.
- Recordar la sesión no evita la verificación en dos pasos: la sesión solo se abre después de validar el código.

## Confiar en este equipo
- En el paso del código aparece «Confiar en este equipo durante 30 días». Con el código de la aplicación (no con un código de
  recuperación), el navegador recibe un token aleatorio (cookie HttpOnly, SameSite=Strict, Secure, limitada a `/api/login`); el
  servidor guarda solo su huella SHA-256.
- Ese navegador no vuelve a pedir el código durante 30 días; la contraseña sigue siendo obligatoria. Otros equipos siempre lo piden.
- La confianza se revoca: al cambiar o restablecer la contraseña, al cerrar sesión en todos los dispositivos, al desactivar la
  verificación, cuando administración la revoca (o retira el segundo paso, desactiva la cuenta o cambia su rol), al vencer los 30
  días y si el token llega desde otro navegador o sistema (actividad sospechosa). Máximo 10 equipos de confianza por cuenta.

## Configuración → Seguridad y sesiones
- «Dispositivos de confianza»: nombre del equipo (navegador y sistema), navegador, fecha de autorización, última actividad,
  vencimiento y botón «Revocar confianza».
- «Cerrar sesión en todos los dispositivos» (con confirmación): cierra en el servidor todas las sesiones de la cuenta y revoca todos
  sus equipos de confianza; para volver a entrar se piden usuario, contraseña y código.
- Gestión de usuarios: «Revocar equipos de confianza» para cuentas con verificación en dos pasos.

Se mantienen el límite de cinco intentos fallidos, la recuperación de contraseña, los permisos y las cuentas existentes.
