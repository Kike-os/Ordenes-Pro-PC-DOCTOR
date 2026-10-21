# ADI AutoCare Pro (1.5.159 · centro de control 1.5.199)

Monitoreo, diagnóstico y recuperación segura de Órdenes Pro. Reutiliza el motor de estabilidad (`local/stability.py`, ver [ESTABILIDAD.md](ESTABILIDAD.md)): las mismas verificaciones, las mismas tareas programadas de Vercel (01:00, 09:00 y 17:00, Ecuador) y el mismo registro por versión. Panel en **Sistema → ADI AutoCare Pro** (solo administración).

## Verificaciones (solo lectura, sin datos simulados)

| Servicio | Severidad si falla |
| --- | --- |
| Despliegue y registro de versión · Base de datos y migraciones · Datos esenciales · Inicio de sesión y autenticación (cifrado real de una clave aleatoria, cuentas de administración, sesiones) · Archivos de la interfaz · Seguimiento de órdenes · Agenda de citas (servicios y cálculo real de disponibilidad) | Crítica |
| Registro de clientes · Tickets y presupuestos PDF (genera en memoria el ticket de la orden más reciente y el último presupuesto; no guarda nada) | Alta |
| Reportes y saldos · Servicio de correo (en ejecuciones programadas y manuales inicia sesión en el buzón por IMAP) · Errores de ejecución (5 o más en una hora) | Media |
| ADI con inteligencia artificial (configuración; no llama al proveedor para no generar costos; sin proveedor es opcional y no cuenta como fallo) | Baja |

## Errores de ejecución

Toda excepción no controlada (servidor local en POST y capa WSGI de Vercel en GET y POST) se registra en `system_state` → `autocare_errors` (últimos 200) con fecha, versión, método, ruta (números sustituidos por `:id`), módulo, tipo de error, punto del código y severidad/causa probable: crítica (base de datos, autenticación), alta (operación POST de clientes, órdenes, presupuestos, agenda o correo), media (consultas, conexiones externas), baja (interfaz). Nunca se guarda el cuerpo de la petición ni el mensaje del error, que pueden contener datos personales.

## Autorreparación controlada

- Fallos transitorios (conexión, tiempo de espera, base ocupada, red o error temporal del correo): un único reintento tras 1,5 s; si responde, queda registrado como **recuperación automática**.
- No modifica datos de clientes, órdenes, presupuestos, autorizaciones ni registros financieros; no borra información; no reinicia servicios ni cambia código.
- Correcciones de código: rama de pruebas → batería completa → aprobación de administración → publicación con el procedimiento de versiones (cada versión registra fecha, cambios y resultado en `CHANGELOG.md` y en el historial). Reversión: Vercel → Deployments → «Instant Rollback». La creación automática de ramas o solicitudes de cambio en GitHub desde el servidor no está activada: exigiría una credencial con permisos de escritura en Vercel y una decisión expresa de administración.

## Historial y avisos

`autocare_events` (últimos 300): incidencias nuevas, incidencias resueltas, recuperaciones automáticas, primera verificación de cada versión («Versión X instalada. Pruebas completadas correctamente») y revisiones. Avisos en el centro de notificaciones (solo administración), una vez por evento: incidencias según la severidad mínima elegida, recuperaciones y versiones verificadas, configurables en el panel. «Marcar errores como revisados» los retira de las incidencias activas sin borrar el registro.

Rutas (administración): `GET /api/autocare`, `POST /api/autocare/diagnose` (máximo 6 por hora), `POST /api/autocare/settings`, `POST /api/autocare/review`.


## ADI AutoCare Pro 2.0 (1.5.178)

Centro de supervisión técnica del software (no es un módulo de vehículos). Panel en **Sistema → ADI AutoCare Pro** (solo administración).

**Seis indicadores con datos reales** (al pulsarlos abren su detalle): última verificación (origen y responsable), servicios operativos (sin error, con advertencias o sin comprobar), incidencias activas, recuperaciones realizadas, estabilidad y versión, y próxima verificación programada.

**13 servicios verificados individualmente** (solo lectura; resultado Correcto, Advertencia, Error o No comprobado):

| Servicio | Comprobación real | Gravedad |
| --- | --- | --- |
| Conectividad con la base de datos | Responde, tiempo de respuesta y migraciones aplicadas (advertencia si tarda más de 1,5 s) | Crítica |
| Autenticación y sesiones | Cifrado de contraseñas, cuentas de administración activas, sesiones vigentes | Crítica |
| Registro de clientes | Campos obligatorios y consulta | Alta |
| Órdenes de reparación | Seguimiento, ticket PDF de la orden más reciente y contador global (error si quedara por detrás del último número) | Crítica |
| Presupuestos | PDF del presupuesto más reciente | Alta |
| Licencias e inventario | Cifrado de credenciales de ida y vuelta; advertencia si hay licencias con datos inconsistentes | Alta |
| Ventas y pagos | Saldos y coherencia del estado de pago de cada venta con sus pagos confirmados | Alta |
| Agenda y citas | Servicios y cálculo de disponibilidad | Crítica |
| Envío de correos | Configuración; el buzón (IMAP) se comprueba en diagnósticos manuales y programados, en los demás queda «No comprobado» | Media |
| Notificaciones | Centro de avisos y avisos de renovación con error en 24 h | Media |
| Integraciones configuradas | Base de datos, IA de ADI (no se llama para no generar costos) y variables necesarias en Vercel | Baja |
| Servicios internos | Versión, compilación, archivos de interfaz y tareas programadas recientes | Crítica |
| Registros de errores | Errores de ejecución en la última hora (advertencia de 1 a 4, error desde 5) | Media |

**Diagnóstico con progreso real:** «Ejecutar diagnóstico» abre una ventana que ejecuta en el servidor cada comprobación, una tras otra (`/api/autocare/diagnose/start` y `/step`), y registra la ejecución al terminar con el responsable. Solo muestra «Todo correcto» si las 13 son correctas; si hay advertencias, errores o comprobaciones sin verificar, lo dice.

**Incidencias:** código INC-AAAAMMDD-NNN, servicio, descripción, gravedad, fechas y repeticiones, posible causa, acción recomendada y estado (Activa, En revisión, Resuelta). Las de verificación se resuelven solas cuando la comprobación vuelve a ser correcta; los errores de ejecución se agrupan por módulo y tipo. Administración puede marcarlas en revisión, resolverlas (con nota obligatoria) o reabrirlas: queda quién, cuándo y la nota (`/api/autocare/incident`). ADI sugiere, pero no modifica datos ni ejecuta reparaciones.

**Historial técnico** con filtros por fecha, servicio y gravedad: cada diagnóstico (origen, responsable, resultados) y la actividad técnica (incidencias, resoluciones, recuperaciones, versiones, seguimiento).

**Versiones:** instalada, fecha de implementación, estado de estabilidad con la explicación concreta de «En observación» (verificaciones que faltan, horas restantes, fallos no críticos), versión disponible cuando puede verificarse (nunca se instala sola), resultado de la comprobación posterior al despliegue, cambios pendientes de publicar e historial de cambios.

**Avisos configurables** (una vez por evento, sin duplicados): fallos críticos, servicios no disponibles, errores recurrentes (3 o más), problemas de conexión, diagnósticos programados y actualizaciones disponibles, con gravedad mínima.

## Corrección (1.5.179)

- **Tarjetas de servicio** rediseñadas con clases propias (`ac-svc-*`): nombre, estado, descripción completa, tiempo de respuesta y gravedad, sin superposiciones (se retiran los efectos de las reglas antiguas de `.autocare-services`); «Ver detalles» despliega por servicio los tiempos (mediana, p90, umbral), los últimos resultados, la posible causa y la acción recomendada.
- **Licencias e inventario → Ver detalles:** licencias afectadas con su problema y fechas, stock frente a registros individuales (el stock se calcula de los registros: no hay contador que difiera), posibles duplicados (misma terminación de clave dentro de un producto, enmascarada) y recomendaciones. Nada se modifica.
- **Envío de correos:** distingue *fallo real* (el buzón falló en el último diagnóstico manual o programado de 24 h), *prueba omitida* (verificación automática que muestra el último resultado real) y *comprobación pendiente* (ninguna comprobación real en 24 h). «Ver detalles» muestra servidores, cuenta (sin contraseña), última comprobación y envíos fallidos o rebotados de 7 días. Nunca se envían correos de prueba.
- **Indicador «Servicios verificados»:** «N de 13 correctos» (las comprobaciones no ejecutadas no cuentan como correctas) y, aparte, la disponibilidad (los que responden), advertencias y sin comprobar.
- **Rendimiento:** Órdenes y Agenda informan el tiempo de cada paso (seguimiento, ticket PDF, servicios, disponibilidad); el ticket PDF, lo más costoso, solo se genera en diagnósticos manuales y programados. Umbral de advertencia según mediciones reales (doble de la mediana, mínimo 1,5 s); un tiempo alto se señala como «Lento», nunca como Error.
- «Ejecutar diagnóstico» espera y reintenta si hay una verificación automática terminando (antes fallaba con «Ya hay un diagnóstico en curso»).

## Rendimiento (1.5.180)

Medido con los tiempos por paso del primer diagnóstico real (20/10/2026):

- **Ticket PDF (3,1 s):** el 95 % era decodificar el logotipo PNG en Python puro en cada instancia nueva de Vercel. Ahora los píxeles del logo para los anchos de los documentos (384, 416 y 900) están precalculados en `static/logo-original.pixels`, con la huella SHA-256 del PNG: si el logo cambia, el archivo se ignora y se decodifica como antes. Regenerarlo: `python -c 'import document_logo;document_logo.build_cache()'` (una prueba avisa si quedó desactualizado). Resultado idéntico byte a byte.
- **Agenda (2,4 s):** calcular los horarios de un día lanzaba ~460 consultas, casi todas idénticas (horario semanal, feriado, margen, técnicos y sus horarios). Una caché de lecturas que dura un solo cálculo las hace una vez (~100 consultas, las comprobaciones de choque de cada horario siguen una a una). Comprobado: mismos horarios en 480 combinaciones de día, servicio y modo.

## Monitor de errores: detalle exacto, agrupación y resolución

- **Detalle de cada error** (Incidencias → «Detalle técnico del error»):
  - módulo, endpoint, método HTTP y código de estado;
  - usuario, fecha y hora, y registro afectado (número interno);
  - archivo y línea, tipo de error y causa original (por ejemplo, `ConnectionResetError`);
  - operación de base de datos (solo verbo y tabla), mensaje técnico depurado, versión y código interno `ERR-XXXXXX`.
  - Nunca se guardan contraseñas, tokens, valores SQL, correos ni números largos.
- **Agrupación:** los errores iguales forman una sola incidencia con su contador de repeticiones y sus últimas apariciones.
- **Niveles visibles:** Información (baja), Advertencia (media), Error (alta) y Crítico (crítica).
- **Resolución:** se marca como Resuelta con una nota, y el seguimiento conserva el historial. Si el mismo error vuelve a ocurrir, se reabre automáticamente la misma incidencia (mismo código, marcada como «Reabierta»).
- **«Registros de errores»** solo cuenta los errores de incidencias sin resolver. Al marcar la incidencia como resuelta tras corregirla, el panel vuelve a la normalidad sin borrar nada.
- **Causa concreta:** el detalle muestra «Causa detectada» en lugar de una recomendación genérica. Por ejemplo: «Se registraron 2 fallos en el módulo Presupuestos durante operaciones POST (/api/quotes/:id…)» con «Revisar /api/quotes/:id y la operación de base de datos asociada».

## Centro de control (1.5.199)

### Indicadores

Los seis indicadores salen de datos registrados:

- **Última verificación:** fecha, hora, quién la ejecutó y duración.
- **Servicios:** operativos frente a afectados (con error o advertencia). Aparte se muestran los «sin comprobar» y los «no disponibles».
- **Incidencias abiertas:** número total, desglosado por gravedad.
- **Recuperaciones:** automáticas y manuales, la última de ellas y las incidencias resueltas con una verificación correcta.
- **Versión instalada:** estado de estabilidad y comparación con la versión publicada.
- **Próxima comprobación:** la tarea programada del servidor.

### Servicios y estados

Se comprueban 15 servicios. Los nuevos son:

- **Inteligencia artificial de ADI:** consulta el modelo en OpenAI (`GET /v1/models/<modelo>`). Valida la clave y el modelo sin generar texto ni coste, y la clave nunca aparece en el detalle. Solo se hace en los diagnósticos manuales y programados; la verificación automática usa el último resultado de las 24 h anteriores. También incluye los minutos de voz natural usados hoy.
- **Copias de seguridad:** lee el registro que deja `maintenance/backup-cloud.py` (fecha, tamaño, clientes y órdenes). Una copia de más de 7 días da una advertencia; una copia fallida, un error.

«Servicios internos» pasa a llamarse **Servicios internos y tareas programadas**.

Hay cinco estados:

- **Correcto.**
- **Advertencia:** incluye una respuesta más lenta que su límite.
- **Error.**
- **No comprobado.**
- **No disponible:** el servicio no está configurado; por ejemplo, la IA sin clave.

Un servicio «No disponible» solo degrada el estado general si su gravedad es crítica o alta, y no abre incidencias. El correo sin configurar sigue siendo un **Error** (no crítico), como antes: sin correo no salen avisos ni comprobantes.

Cada comprobación tiene un tiempo máximo: correo 20 s, IA 12 s y el resto 8 s. Si se supera, el estado es «Respuesta lenta» (advertencia), nunca Error.

### Reintento por servicio

El botón **Reintentar** de cada tarjeta repite solo esa comprobación, con la prueba de red (`POST /api/autocare/check`).

- Se rechaza si hay otro diagnóstico en curso, para que nunca haya dos a la vez.
- Admite un máximo de 30 reintentos por hora y usuario.
- Si el resultado es correcto, la incidencia de ese servicio se cierra con esa evidencia y queda firmada por quien reintentó. Si sigue fallando, la incidencia continúa abierta.
- El resultado (quién, cuándo, versión y resultado) se guarda en `stability_rechecks` y sustituye en el panel el estado de ese servicio hasta la siguiente verificación completa.
- Las tarjetas con error o advertencia muestran la causa probable y los pasos sugeridos.

### Recuperación segura

Solo hay acciones de una lista cerrada en el servidor (`autocare.ACTIONS`, `POST /api/autocare/action`), sin parámetros libres. Cada una exige la confirmación expresa de administración, queda en el historial con el nombre de quien la ejecutó y termina repitiendo la comprobación del servicio.

| Acción | Qué hace | Copia del cambio |
|---|---|---|
| Liberar un diagnóstico bloqueado | Quita la marca «en curso» si quedó colgada más de 5 minutos. Se rechaza si sigue activa. | No toca datos. |
| Actualizar licencias vencidas del inventario | Pasa a «Vencida» las licencias **sin vender** cuya fecha ya pasó (`licenses.expire`). Las vendidas no cambian. | Los identificadores y su estado anterior («disponible») quedan en el registro, así el cambio es reversible. |

### Historial y exportación

- Cada evento tiene un identificador `EV-XXXXXXXX` y el usuario o proceso que lo originó. Los eventos anteriores reciben un identificador derivado, `EV-Hnnnnn`, y figuran como «ADI AutoCare»: no se inventa quién los hizo.
- Filtros: fechas, servicio, gravedad, versión y usuario.
- **Exportar CSV** (`GET /api/autocare/history.csv`, solo administración) aplica los mismos filtros.
  - Se enmascaran los correos, las claves del tipo `sk-…` y los números largos.
  - Nunca incluye contraseñas, tokens ni datos de clientes.
  - Cada exportación queda en la auditoría.

### Versiones

- **Compilación desplegada:** el commit y la rama que informa Vercel (`VERCEL_GIT_COMMIT_SHA` y `VERCEL_GIT_COMMIT_REF`). En una instalación local se muestra «local».
- **Última versión publicada** frente a la instalada.
- **Migraciones:** las aplicadas frente a las del paquete. Vercel no ejecuta `migrate()`, así que una migración pendiente se muestra como aviso.
- **Comparación:** número de cambios por tipo frente a la versión anterior.
- **Quién registró y quién autorizó:**
  - `versioning.py publish` anota `published_by`, que es el `user.name` de Git.
  - La opción `--autorizado-por "…"` anota `authorized_by`.
  - Las versiones anteriores a la 1.5.199 muestran «no registrado»; no se rellenan a posteriori.

### Avisos

La pestaña Avisos muestra los avisos de los dos últimos días, clasificados en **Crítica, Advertencia, Informativa y Recuperada** y con filtro por tipo. No hay duplicados: son los mismos avisos del centro de notificaciones, con una clave estable por evento.

Las recuperaciones manuales aparecen como «Acción de recuperación ejecutada», no como un problema de conexión.

### Permisos y rendimiento

Todo es solo para administración y se valida en el backend; las acciones envían CSRF.

Hay dos niveles de comprobación:

- **Ligera:** la verificación automática por visitas. No abre el buzón, no llama a OpenAI ni genera el ticket PDF.
- **Profunda:** el diagnóstico manual, el programado y los reintentos.

### Lo que no se automatiza

- **Reparaciones de código o de datos:** no se ejecutan desde el panel. Se preparan en una rama de pruebas y se publican con autorización.
- **Reversión de una versión:** se hace desde Vercel con «Instant Rollback».
- **Respaldo de la base central:** se hace con `maintenance/backup-cloud.py`, que necesita las variables de producción. El panel solo lee su registro y no puede lanzarlo desde Vercel.
- **Quién autorizó las versiones anteriores:** no consta, así que no se muestra.
