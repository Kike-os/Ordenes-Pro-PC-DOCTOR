# Versión del sistema (pantalla de acceso)

Sustituye al antiguo indicador «Release».

## Qué muestra

- **Versión instalada** y **fecha de publicación**: las del registro incluido en el código desplegado (`local/data/releases.json`), por lo que siempre corresponden al código que realmente se ejecuta.
- **Estado**, pedido al servidor al cargar (`GET /api/public/version`):
  - *Comprobando actualizaciones…* mientras se consulta.
  - *Sistema actualizado* (verde) solo tras comparar con el registro publicado, con la hora de la comprobación.
  - *Actualización disponible* (azul, con la versión nueva).
  - *Actualización importante* (ámbar) cuando lo pendiente incluye cambios de seguridad o una versión mayor o menor.
  - *No se pudo comprobar* con «Reintentar».
  - *Nueva versión desplegada · recarga la página* cuando el servidor ya ejecuta una versión distinta de la que trae la página (por caché), con «Recargar página».
- **Ver novedades**: ventana con versión, fecha, tipo, resumen y notas por categoría (nuevas funcionalidades, mejoras, correcciones, seguridad, rendimiento), compatibilidad y enlace a las versiones anteriores.
- **Historial de versiones**: página pública `/novedades`.

## Funcionamiento

- El servidor compara la versión instalada con el registro oficial publicado (`UPDATE_REGISTRY_URL`, por defecto el del repositorio). La comprobación se guarda 20 minutos; «Reintentar» la repite, con límite de seis cada cinco minutos por dirección.
- No hay instalación desde el navegador ni despliegues iniciados por usuarios: el aviso solo informa. En Vercel la versión cambia cuando termina el despliegue; la página lo detecta y pide recargar.
- Solo se exponen notas de versión ya públicas. Ningún token ni clave llega al navegador.

## Acceso

Tarjeta de 440 px con relleno de 30 px, logo original de 105 px, título de 26 px, campos y botón de 48 px, radio de 16 px y pie compacto con la versión. Centrada cuando hay espacio; en pantallas pequeñas se desplaza en vertical. La verificación antirrobot se comprueba en el servidor en cada inicio de sesión cuando está activa (no puede omitirse desde el navegador).
