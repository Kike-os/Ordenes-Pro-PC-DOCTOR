# Corrección de catálogos y recepción — 9 de octubre de 2026

## Causas comprobadas

El ZIP anterior de cPanel contenía app.py y estáticos antiguos, únicamente la migración 001 y ningún módulo ni archivo del catálogo INEC. Su backend no definía `/api/reception-options` ni `/api/geo/*`; el manejador genérico devolvía HTTP 404 «Recurso no disponible». Subir solo el formulario actualizado deja esas rutas ausentes. No se dispone de acceso al hosting ni a sus registros para afirmar qué versión está ejecutándose allí.

En el frontend, `fetchGeo()` capturaba la excepción sin comunicar el fallo al proceso de apertura. `showOrder()` podía marcar los catálogos como listos aunque fallara provincias. El botón Siguiente comenzaba deshabilitado y dependía de una carga conjunta de catálogos ajenos al paso Cliente. Los errores geográficos se escribían en el mensaje global y no tenían reintento local. Las excepciones WSGI se convertían en HTTP 500 sin registrar el traceback.

## Cambios

- Tipos/marcas y provincias se cargan independientemente. El paso Cliente permite avanzar con sus datos válidos aunque falle otra sección.
- Avisos compactos de carga/error/reintento al lado del catálogo correspondiente. La recuperación limpia el aviso. Una ubicación obligatoria fallida no permite avanzar con datos inválidos.
- Caché por ubicación y deduplicación de solicitudes simultáneas. Los reintentos conservan campos, selección de equipo y marca. Solo cambiar un padre geográfico limpia hijos incompatibles.
- Errores HTTP y respuestas JSON incompatibles se identifican explícitamente. Se mantienen la autenticación y las validaciones frontend/backend.
- Passenger registra excepciones con método/ruta sin volcar datos personales del formulario.
- Paquete cPanel reconstruido con backend, cuatro migraciones, catálogo oficial, QR/PDF, bibliotecas y licencias; sin var/, base de datos, cuentas ni .env privado.
- Eliminada la importación innecesaria del catálogo geográfico anterior: el módulo utiliza INEC 2026 con rutas basadas en __file__.

Archivos de esta corrección: `local/app.py`, `local/reception.py`, `local/passenger_wsgi.py`, `local/static/app.js`, `local/static/app.css`, `local/templates/dashboard.html`, `local/tests/test_wsgi.py`, `docs/CPANEL.md`, `ordenes-pro-cpanel.zip` y evidencias en `revision/`.

## Verificaciones

37 pruebas automatizadas aprobadas. Incluyen validación de cédulas y tipos de RUC, geografía y jerarquías, migraciones/órdenes históricas, concurrencia/idempotencia, medianoche Ecuador, códigos inmutables, consulta privada, QR y PDF. Nueva prueba completa a través de Passenger/WSGI: login, catálogos, guardado, consulta, QR y PDF.

Paquete extraído en un directorio temporal: migración e importación Passenger correctas desde otro directorio de trabajo; respuestas autenticadas HTTP 200 para tipos/marcas (76 marcas), provincias (24), cantones de Azuay (15), parroquias de Cuenca (37) y localidad de ejemplo (1). Ver `verificacion-paquete-cpanel.json`.

Chromium: recorrido completo de los cuatro pasos, identificación, ubicación dependiente, marca, confirmación, guardado de una sola orden ficticia, consulta por código, impresión y descarga PDF. HTTP 404 simulados en tipos/marcas, provincias y cantones: aviso local, reintento exitoso y conservación de datos comprobados. Ver `verificacion-asistente-header.json`. Encabezado probado en siete anchos; asistente en seis tamaños, incluido teléfono horizontal. Sin excepciones JavaScript.

QR leído con zbarimg tanto desde PNG como desde PDF A4: URL HTTPS de la orden PCD-20261009-0001; sin identificación ni otros datos personales. El comprobante de prueba ocupa una página. Inspección visual realizada en escritorio y móvil.

Servicio local reiniciado y activo. Inicio HTTP 200; catálogos sin sesión HTTP 401, correctamente protegidos. Cuatro migraciones aplicadas con respaldos: conteos conservados (1 usuario; 0 clientes/equipos/órdenes en la base local), sin errores de claves foráneas. Todas las órdenes de prueba se crearon en bases temporales.

## Pendiente externo

Actualizar y reiniciar la aplicación real de cPanel siguiendo `docs/CPANEL.md`, conservando var/ y las variables privadas. No se accedió ni publicó en ese hosting. El QR utiliza la URL HTTPS configurada; su consulta desde teléfonos requiere que esta versión esté instalada y accesible allí. La validación matemática no certifica emisión de cédula ni vigencia de RUC; las excepciones oficiales no algorítmicas de RUC se documentan en `docs/RECEPCION.md`.
