# Recepción de equipos, numeración y encabezado

Implementado sobre Python/SQLite y el esquema existente. Las migraciones 002–004 son aditivas, crean respaldos antes de ejecutarse y conservan cuentas, relaciones y códigos anteriores. Reiniciar después de migrar. No sobrescribir `var` ni `.env` al actualizar.

## Formulario y permisos

Asistente de cuatro pasos: cliente, ubicación, equipo y confirmación. Valida antes de avanzar; conserva datos al regresar y pide confirmación antes de descartarlos. Administración y técnicos autenticados pueden recibir equipos. La edición de clientes/equipos, estados y configuración conserva los permisos administrativos anteriores.

Se guardan los datos completos de recepción y una copia histórica inmutable por orden. Cambiar posteriormente los datos del cliente/equipo no cambia el comprobante de recepción. Las órdenes anteriores conservan la información disponible en el momento de migrar; no se inventan datos que no existían.

El catálogo inicial contiene las 52 marcas de computadoras recibidas en el pedido y 24 marcas de impresoras. Se filtra por categoría y permite escribir una nueva; el servidor la incorpora al guardar, sin duplicar por mayúsculas/minúsculas. Todas las categorías de equipos anteriores siguen siendo compatibles.

## Ubicación: fuente oficial

Fuente: INEC, **Códigos DPA 2026**, descargado el 2026-10-09 de:
https://aplicaciones2.ecuadorencifras.gob.ec/SIN/descargas/cdpa2026.xlsx

El archivo derivado `local/data/inec-2026.json` registra versión, URL, fecha de consulta y SHA256 del original. Contiene **24 provincias, 222 cantones, 1.317 entradas parroquiales** (incluye cabeceras, parroquias urbanas y rurales) y **222 cabeceras cantonales** como sugerencias separadas de localidad. La tabla parroquial incluye tanto los códigos DPA_PARROQ como DPA_PARURB, conservando su clase y relaciones. Los datos se importan en tablas SQLite con claves y relaciones.

Provincia, cantón y parroquia se buscan y seleccionan de listas dependientes. Las cabeceras están identificadas por el código parroquial 50; un cantón nunca se convierte automáticamente en ciudad. En parroquias urbanas se sugiere su cabecera. En ubicaciones sin localidad en la fuente se permite texto manual, que se conserva. El backend rechaza combinaciones incompatibles; guarda por separado códigos/nombres, localidad, calles, número y referencia. La fuente no pretende enumerar todos los barrios y recintos del país.

## Identificación

Cédula y RUC se guardan como texto. Se valida longitud, dígitos ASCII, código provincial, estructura, establecimiento y dígito verificador según cédula/persona natural, sociedad privada o entidad pública. El control tiene tipo, contador y estados visuales; valida al completar o al salir, y también en el servidor. No hay consulta automática al Registro Civil ni al SRI; el indicador significa solamente **formato y algoritmo correctos**.

Precisión: el SRI indica que existen RUC emitidos para sociedades y extranjeros que no responden a un algoritmo específico. La comprobación tradicional implementada por pedido no acredita emisión/actividad y puede rechazar esas excepciones. Validarlas requiere un procedimiento o integración autorizada, no asumir que cualquier número de 13 dígitos es válido.
Fuente: https://www.sri.gob.ec/facturacion-electronica

## Numeración y QR

Los nuevos códigos usan `PCD-AAAAMMDD-0001`. Fecha/hora se toman del servidor con `ZoneInfo('America/Guayaquil')`; se guardan ISO 8601 con microsegundos y offset, fecha de numeración y consecutivo diario. `BEGIN IMMEDIATE` y las restricciones UNIQUE protegen los registros concurrentes. Cada día empieza en 0001; después de 9999 continúa en 10000. La secuencia persiste y no disminuye ni se elimina. No se recuperan números por anular/eliminar órdenes. Los códigos anteriores `OP-…` y `ORDE:…` se conservan.

Un identificador de envío evita duplicados al reintentar la misma recepción. Los códigos, fecha de numeración, consecutivo y URL de QR quedan protegidos contra cambios; modificar la fecha de recepción no renumera la orden.

Configurar `PUBLIC_APP_URL` con el origen HTTPS real **antes de registrar órdenes destinadas a uso real**. Se usa por defecto el dominio que ya figuraba en la documentación, `https://ordenes-pro.ecuadorpcdoctor.com`. El QR guarda `/orders/<código>`; no contiene identificación ni contacto. La ruta exige acceso para consultar detalles, PNG y PDF. Vincular por código evita que la reutilización de un ID SQLite tras eliminar un registro conduzca a otra orden. La URL queda almacenada y no cambia si después se modifica la configuración.

La instalación local en HTTP no publica automáticamente la aplicación en ese dominio. La consulta desde teléfonos mediante el QR requiere HTTPS público con esta versión desplegada. No se ha realizado una publicación remota.

El comprobante ofrece consultar, imprimir desde el navegador y descargar PDF/QR PNG. El PDF se genera en el servidor, con QR vectorial y ajuste/paginación para textos extensos. Los datos de identificación y ubicación están disponibles solo tras autenticación.

## Encabezado, hora y clima

Se conserva el logo y la paleta azul oscuro. Navegación con SVG Lucide, buscador, reloj, clima, cuenta y rol. El reloj muestra segundos y `a.m.`/`p.m.`, usa Ecuador y se sincroniza con el servidor. La hora no depende de la zona configurada en el navegador.

El clima usa la API real **MET Norway Locationforecast**, con atribución, iconos por condición/día/noche y caché de diez minutos. Es un pronóstico cercano a la hora actual, no una observación de estación. La consulta solo envía coordenadas del establecimiento, nunca datos del cliente. Hay timeout y estado «Clima no disponible» ante fallos. El header mide 76 px: logo original con 48 px de contenido visible, título de 21 px, subtítulo de 11 px, navegación de 13 px con iconos de 18 px y botones de 40 px. En anchos menores de 1800 px la navegación usa un desplegable. Hasta 1150 px el reloj y clima pasan a la zona secundaria del menú; hasta 860 px también se traslada allí el buscador. En teléfonos se mantienen logo, título, cuenta y botón de menú; desde 380 px hay además un acceso directo al buscador. El menú incluye siempre el buscador en teléfonos, también en 320 px. La cuenta dispone de cierre de sesión y conserva los permisos existentes. Los desplegables cierran al pulsar Escape o fuera de ellos; los iconos y estados respetan movimiento reducido. Configurar WEATHER_CITY, WEATHER_LATITUDE, WEATHER_LONGITUDE y WEATHER_CONTACT; por defecto se utiliza Otavalo. No requiere API key.

Fuentes: https://api.met.no/doc/locationforecast/HowTO y https://api.met.no/

## Producción y dependencias

El aviso de evaluación se oculta únicamente si APP_ENV=production, PRODUCTION_ENABLED=true, APP_URL es HTTPS y SESSION_SECURE=true. El cambio no certifica ni despliega el hosting. La instalación local continúa identificada como evaluación.

Dependencias portables incluidas en `local/vendor`: Segno 1.6.6 (QR) y pydyf 0.11.0 (PDF), con licencias. Métricas Helvetica derivadas de ReportLab 4.4.5 y licencia en `local/data`. Iconos Lucide 0.468.0 y licencia en `local/static`. No se necesita Node, Chromium o pip para ejecutar el sistema; Chromium/Poppler/zbarimg se utilizaron exclusivamente para QA.

## Verificación

`python -m unittest discover -s tests -v` desde `local`, y `node --check static/app.js`.

Pruebas específicas: cédula/RUC, backend, persistencia de campos, jerarquía INEC, localidad manual, historial, medianoche de Ecuador, secuencia diaria, concurrencia con dos técnicos, reintentos, eliminación sin reutilización de códigos, inmutabilidad, consulta privada, PDF y recuperación de órdenes anteriores. Weather: datos reales consultados y pruebas de caché, estados meteorológicos y fallo de conexión. Revisión visual en Chromium, PDF renderizado con Poppler y lectura independiente del QR con zbarimg. Resultados y capturas en `revision`.

## Autorizaciones en tres apartados con estado (1.5.64)

La sección «Autorización de acceso y tratamiento de datos» se presenta en tres apartados: 1) acceso al sistema operativo, 2) acceso a archivos personales y respaldos, 3) formateo, reinstalación y eliminación de datos. Cada uno muestra su estado real:

- **AUTORIZADO** (verde, con visto): el cliente autorizó y hay alcance marcado.
- **NO AUTORIZADO** (rojo): el cliente rechazó expresamente (acceso técnico denegado u operaciones de riesgo rechazadas).
- **PENDIENTE** (gris): no consta decisión; no se interpreta como aceptación ni como rechazo.

Los campos enviados y guardados no cambian (`technical_access`, `access_*`, `destructive_action`, `risk_*`); solo cambia la presentación. Nada viene marcado y las opciones de alcance aparecen al autorizar. El comprobante A4 incluye «Autorizaciones del cliente» con los mismos tres estados en indicadores estáticos (relleno oscuro, contorno o gris con su texto), legibles en blanco y negro, y la fecha, hora y responsable del registro.

### Decisión propia de archivos y respaldos (1.5.67)

El apartado 2 tiene su propia decisión opcional (`files_access`): «Autorizo el acceso a archivos o respaldos» o «No autorizo…». Ninguna viene marcada y «Quitar decisión» la devuelve a pendiente.

- Autorizado: exige marcar archivos específicos, respaldo o ambos, y describir el alcance.
- No autorizado: rechazo expreso; no puede quedar marcada ninguna operación de archivos. Aparece como «NO AUTORIZADO» en la confirmación, el detalle de la orden, el comprobante A4 y el ticket.
- Sin elegir: pendiente; no se guarda ni autorización ni rechazo.

Se guarda dentro del registro inmutable de la decisión de acceso (`permissions.files_decision`), sin migración. Las órdenes anteriores no se modifican: al no tener ese dato siguen mostrándose como pendientes, nunca como rechazo.

## Foto de perfil (1.5.86)

Cada persona del equipo puede poner, cambiar o quitar su foto desde el menú de su cuenta (arriba a la derecha → «Foto de perfil»). El navegador la recorta en cuadrado a 256 × 256 px; el servidor comprueba por su cabecera que sea un PNG, JPG o WebP real, con un máximo de 300 KB, y la guarda en la base (migración 035). Solo se sirve a sesiones iniciadas (`/api/users/<id>/photo`). Sin foto se muestran las iniciales.

## Consecutivo permanente de órdenes OP-0001 (19/10/2026)

- Las órdenes nuevas se numeran `OP-0001`, `OP-0002`… con un contador único y permanente (tabla `order_serial`, migración 058). No se reinicia por fecha, nunca retrocede ni se borra (triggers) y no reutiliza números de órdenes anuladas. Después de `OP-9999` continúa con `OP-10000`.
- El contador arranca después de las órdenes principales que ya existían; los equipos adicionales siguen usando el sufijo `-E02`, `-E03`… y no consumen número.
- El número se reserva dentro de la transacción de escritura (`BEGIN IMMEDIATE`), así que dos registros simultáneos no pueden obtener el mismo. Si un código ya existe (por ejemplo, el provisional `OP-00001` de una orden antigua), se salta al siguiente libre.
- Las órdenes existentes conservan su código `PCD-AAAAMMDD-NNNN`, su QR y sus comprobantes. Las búsquedas, la consulta pública, el chat, ADI, la vinculación de correos y la lectura en voz reconocen los dos formatos.
- La tabla antigua `order_sequence` (migración 002, sin uso) no se reutiliza.

## Vuelta al consecutivo diario PCD-AAAAMMDD-0001 (19/10/2026, 1.5.171)

Por decisión de administración se retira el consecutivo permanente OP-0001 y se restablece el formato diario:

- `PCD-AAAAMMDD-0001`: fecha de recepción en hora de Ecuador (America/Guayaquil) y consecutivo de cuatro dígitos que vuelve a 0001 cada día.
- El número lo genera el servidor dentro de la transacción de escritura (contador `daily_order_sequences`, que nunca retrocede ni se borra),
  con índices únicos sobre el código y sobre (fecha, consecutivo). Registros simultáneos no se duplican.
- Un intento fallido no deja salto: si la conversión de una cita falla porque otra persona ya la convirtió, se deshace todo (antes quedaba
  una orden a medias y el número consumido).
- Al llegar a 9999 en un mismo día se muestra un error controlado y no se registra la orden.
- El número no cambia al editar, consultar, imprimir o actualizar la orden.
- Revisión de las órdenes existentes (producción, 19/10/2026): sin duplicados. Todas las del formato diario terminan en 0001 porque cada
  una fue la primera de su día. La orden **OP-0005** (19/10/2026) se conserva tal cual: el cliente ya recibió ese número por correo, en el
  comprobante y en la autorización, y el QR impreso lo contiene. Se sigue encontrando en búsquedas, correos y chat. La tabla
  `order_serial` queda sin uso y no se borra.

## Consecutivo global PCD-AAAAMMDD-0001 (migración 068, 1.5.177)

Sustituye al consecutivo diario de la 1.5.171, a petición de la administración.

- **Formato:** `PCD` + fecha de ingreso (AAAAMMDD, hora de Ecuador) + consecutivo **global** de cuatro dígitos (desde 10000 sigue con más dígitos). El número **no se reinicia** al cambiar de día, mes ni año: `PCD-20261019-0005`, `PCD-20261020-0006`, `PCD-20261021-0007`…
- **Contador central:** la tabla permanente `order_serial` (no retrocede ni se borra), incrementada dentro de la transacción de escritura (`BEGIN IMMEDIATE`). Dos registros simultáneos no reciben el mismo número; un intento que falla se deshace sin dejar salto. Los equipos adicionales (`-E02`, `-E03`…) usan el número de su orden principal y no consumen otro.
- **El número es permanente:** cambiar de estado (En espera, Procesando, Esperando respuesta del cliente, Listo para entregar, Entregado), registrar pagos, entregar o cerrar nunca genera otro número (disparadores `immutable_order_number` e `immutable_order_qr`).
- **Unificación de las órdenes existentes:** la migración 068 numera las órdenes principales por orden de ingreso, con su **fecha original de recepción**, y deja la tabla de equivalencias `order_renumbering` (no se modifica ni se borra). En producción:

  | Antes | Ahora |
  |---|---|
  | PCD-20261012-0001 (y su -E02) | sin cambio |
  | PCD-20261014-0001 | PCD-20261014-0002 |
  | PCD-20261015-0001 | PCD-20261015-0003 |
  | PCD-20261016-0001 | PCD-20261016-0004 |
  | OP-0005 | PCD-20261019-0005 |

- **Códigos anteriores:** quedan en `order_code_aliases` (permanente). Los QR ya impresos, la búsqueda del listado, la consulta pública, ADI, el chat, la vinculación de correos y Licencias Pro los reconocen y abren la misma orden; el detalle de la orden muestra «Código anterior». Los correos ya enviados, el historial y las citas conservan su texto original.
- Ninguna orden se elimina; clientes, equipos, presupuestos, pagos, licencias, historial y documentos siguen ligados por el identificador interno. Una orden sin fecha real de ingreso conserva su código.
