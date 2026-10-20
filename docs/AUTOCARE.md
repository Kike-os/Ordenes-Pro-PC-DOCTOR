# ADI AutoCare Pro (1.5.159)

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
