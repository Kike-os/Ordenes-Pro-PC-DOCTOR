# Acceso premium — PC-DOCTOR S.A.

Cambios limitados a la presentación del acceso:

- `local/templates/login.html`: identidad, encabezado, formulario compacto, iconos y circuitos SVG decorativos.
- `local/static/app.css`: tarjeta de ancho máximo 410 px, circuitos con pulsos, luces rojas ocasionales, capas y enfoque/hover; adaptación móvil y movimiento reducido.
- `local/static/app.js`: conserva los nodos del botón al finalizar el envío, para mantener su icono después de un error. No cambia solicitudes ni autenticación.

Verificación: 22 pruebas existentes aprobadas, JavaScript válido, logotipo idéntico byte a byte y página principal HTTP 200. En Chromium se comprobaron siete resoluciones, centrado/ancho, ausencia de desbordamiento horizontal, mostrar/ocultar contraseña, error de acceso, inicio de sesión, Recordarme con cookie persistente HttpOnly, cierre de sesión, enlace de recuperación y movimiento reducido. Sin excepciones JavaScript. Los flujos utilizaron un servidor temporal y una base de datos ficticia.

No se modificaron backend, permisos, esquema, datos ni credenciales. No se instalaron dependencias.

Capturas: `acceso-premium-escritorio.png`, `acceso-premium-movil.png`. Evidencia: `verificacion-acceso-premium.json`.
