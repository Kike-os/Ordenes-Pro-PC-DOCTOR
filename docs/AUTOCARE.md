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
