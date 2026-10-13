# Acceso, inactividad y actualizaciones (rama `seguridad-acceso`, pendiente de aprobación)

Estado: implementado y probado en la rama de pruebas. **No está publicado.** Requiere aplicar antes la migración 041 en producción (con respaldo).

## Qué existía ya (no se duplicó)

- Contraseñas con Argon2id (las antiguas en scrypt se actualizan al iniciar sesión).
- Cookie de sesión `HttpOnly`, `SameSite=Strict` y `Secure` bajo HTTPS; token CSRF por sesión; identificador de sesión nuevo en cada inicio.
- Límite de intentos por cuenta y por origen con bloqueo temporal (no permanente) y recuperación por correo.
- Registro de accesos (`login_attempt_events`, `audit`) sin guardar credenciales.
- Detección de versión nueva, recarga protegida (no recarga con formularios en uso) y registro de versiones.

## Qué se añadió

**Campos.** El usuario se muestra con puntos y tiene su propio ojo; sigue siendo un campo de texto con `autocomplete="username"`, así que los gestores de contraseñas lo reconocen. Si el navegador no admite el ocultado por CSS, el campo queda visible y el ojo no se muestra.

**Límites.** Usuario: 50 caracteres. Correo usado como usuario: hasta 254 (un correo válido puede superar los 50). Contraseñas nuevas: 128. En el inicio de sesión se siguen aceptando hasta 256 para no dejar fuera a una cuenta con una contraseña larga ya existente: las contraseñas están cifradas y su longitud no se puede conocer. Nada se trunca.

**Colores.** Azul sin interacción, turquesa con el campo activo o formato válido, rojo con error de formato o acceso rechazado y verde solo cuando el servidor confirma el acceso. El rechazo es un único mensaje genérico.

**«No soy un robot».** Se eliminó la casilla. La protección es:
- Esperas progresivas tras fallos consecutivos: 3 s, 8 s y 20 s; al quinto fallo, bloqueo temporal (el de siempre). Durante la espera el intento no se evalúa.
- Verificación adicional solo con fallos recientes (2 o más) en la cuenta o el origen: una prueba de trabajo de un solo uso que emite el servidor y el navegador resuelve sin intervención. `LOGIN_CAPTCHA=always` la exige siempre; `off` la desactiva.
- Campo trampa invisible: un envío que lo rellena se rechaza con el mensaje genérico y queda auditado.

**Cierre por inactividad.** 15 minutos sin actividad real (teclado, clics, toques, rueda, navegación). El carrusel, las animaciones y las consultas automáticas no cuentan. A los 13 minutos aparece el aviso con cuenta atrás y los botones «Continuar sesión» y «Cerrar sesión ahora». Al cumplirse el tiempo se guarda como borrador una recepción abierta, se invalida la sesión en el servidor y se vuelve al acceso con un aviso. El servidor aplica el mismo límite por su cuenta (con 75 s de margen de sincronización). «Recordarme» sigue alargando la vida máxima de la sesión, pero no evita el cierre por inactividad. Varias pestañas comparten la actividad.

**Versión del sistema.** Icono de actualización de trazo fino en turquesa (solo se anima al detectar una versión nueva), número de versión como acceso directo y una única ventana «Actualizaciones del sistema» con las pestañas Novedades e Historial (`/api/public/versions`, por páginas). Un punto discreto avisa de novedades sin leer y se retira al abrirlas. Indicador: verde fijo (al día), turquesa pulsante (versión nueva), ámbar (pendiente o incidencia).

## No incluido

- Autenticación multifactor: no se activa. Queda pendiente definir primero el método de recuperación de la cuenta administrativa.
- El navegador puede seguir sugiriendo nombres de usuario guardados en su lista de autocompletado; eso lo controla el navegador.

Pruebas: `local/tests/test_login_security.py` y comprobación en navegador (campos, esperas, verificación silenciosa, aviso de inactividad, expiración, botón «Atrás», ventana de actualizaciones, 390 px).

## Botón «Agendar cita» y aviso de ADI en el acceso (rama `acceso-citas-adi`, pendiente de aprobación)

- **Agendar cita:** enlace compacto (150 × 40 px, azul y cian) centrado bajo la tarjeta de acceso. Abre `/citas`, el agendamiento público que ya existía y al que ADI ya remite; no hay módulo nuevo. Un destello lo recorre cada ocho segundos (se desactiva con «movimiento reducido»).
- **Aviso de ADI:** tres segundos después de cargar aparece junto a la esfera «¡Hola! Soy ADI, tu asistente virtual de PC-DOCTOR. ¿Necesitas ayuda? ¡Puedes hablar conmigo!». Se puede cerrar, se retira solo a los ocho segundos y al pulsarlo abre el chat existente. Se muestra una vez por visita (pestaña). No abre el chat, no reproduce sonido ni activa el micrófono por su cuenta. No aparece si el chat ya está abierto o si la persona ya está escribiendo sus credenciales.
- Si a la izquierda de la esfera taparía el botón o la tarjeta, se coloca encima de la esfera. En teléfonos la esfera está arriba a la derecha y el aviso queda bajo ella: durante esos ocho segundos cubre parte del logotipo y del título de la tarjeta, nunca los campos ni los botones.

Comprobado en 1366, 1024, 820, 768, 390 y 320 px: botón centrado, sin desbordes, sin solape con el formulario ni con el botón, cierre manual, cierre automático, no repetición y apertura del chat.
