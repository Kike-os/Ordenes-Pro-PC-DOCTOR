# Encabezado definitivo — PC-DOCTOR S.A.

Comparación realizada con `inicio-escritorio.png` y `header-escritorio.png`. La primera versión tenía una barra de una fila y proporciones compactas, pero poca presencia de marca y ninguna herramienta de hora/clima. La segunda incorporó SVG y herramientas, pero aumentó la altura a dos filas y redujo subtítulo, navegación y perfil a tamaños pequeños.

Se combinó la estructura compacta con las herramientas de la segunda versión. Paleta y archivo original del logo conservados. Header de 76 px; logo con contenido visible de 48 px; título 21 px y peso 700; subtítulo 11 px; enlaces 13 px, iconos 18 px y alto 40 px; buscador 200 × 40 px; reloj con icono de 19 px, segundos, números tabulares y a.m./p.m.; clima con icono de 30 px; avatar 36 px y texto de perfil 12/11 px.

El PNG original mide 2826 × 2049; sus píxeles con alfa distinto de cero ocupan 2089 × 1603 desde (320,135). CSS excluye únicamente los márgenes transparentes para aumentar el tamaño visual, sin modificar el PNG ni recortar el contenido. SHA256: c1621de6b1a7e266d67dbd16b834835704e89f6d6274f249c5ed7fb3ccc66f3a.

Tres zonas en escritorio amplio; menú desplegable en resoluciones intermedias. En anchos menores se trasladan reloj/clima y buscador a una zona secundaria accesible desde el menú. En 320 px la búsqueda se abre dentro del menú, conservando título de 21 px, logo y avatar. No hay textos de interfaz reducidos a 6–8 px. Se corrigió una regla heredada que ocultaba el panel de cuenta en teléfonos. Cierre por Escape, selección de navegación y clic fuera; foco visible y retorno de foco al cerrar con Escape. Sin cambios en permisos, endpoints, numeración ni base de datos.

Proveedor MET Norway y atribución conservados; iconos día/noche, carga bajo demanda, deduplicación de solicitud en curso y caché de diez minutos para evitar consultas al abrir repetidamente el menú. El reloj conserva sincronización con el servidor y zona America/Guayaquil. Movimientos discretos de 180 ms y preferencias de movimiento reducido respetadas.

## Verificaciones

- 37 pruebas Python aprobadas.
- Sintaxis JavaScript correcta.
- Chromium en 16 resoluciones: 1920, 1800, 1799, 1600, 1440, 1366, 1280, 1151, 1150, 1024, 900, 860, 768, 390, 375 y 320 px. Header de 76 px, título de una línea a 21 px y logo de 48 px en todas; sin desbordamientos horizontales. Menús y cuenta visibles y dentro de la pantalla.
- Navegación y estado activo, búsqueda, apertura móvil y foco, reloj actualizado cada segundo, clima nocturno y error neutro, atribución, Escape, movimiento reducido y cierre de sesión comprobados.
- Regresión completa del asistente: carga y reintentos de catálogos, validaciones, ubicación dependiente, preservación de datos, guardado único PCD-20261009-0001, consulta, QR, PDF e impresión. Datos exclusivamente ficticios en una base temporal.
- Paquete cPanel regenerado sin datos privados y probado por extracción/importación/migración y endpoints autenticados mediante Passenger.

Evidencia: `verificacion-header-definitivo.json`, `verificacion-asistente-regresion-header.json`, `verificacion-paquete-cpanel.json`; capturas `header-definitivo-grande.png`, `header-definitivo-escritorio.png`, `header-definitivo-movil.png` y `header-definitivo-movil-menu.png`.

Archivos de aplicación modificados: `local/templates/dashboard.html`, `local/static/app.css`, `local/static/app.js`. Documentación y paquete actualizados. No se publicó en el hosting externo: requiere subir el ZIP actualizado y reiniciar Passenger siguiendo `docs/CPANEL.md`.
