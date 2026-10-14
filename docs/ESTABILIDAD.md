# Indicador de estabilidad de versiones (1.5.153, automatizado en 1.5.154)

Distintivo «vX.Y.Z · ESTADO» en el acceso (debajo de «Versión del sistema») y en la barra superior, junto al indicador de versión. En celulares, dentro del menú de navegación. Ambos leen `GET /api/public/stability`: la misma información, sincronizada (se actualiza cada 5 minutos y al volver a la pestaña). Al pulsarlo se abre una ventana con versión instalada, fecha de publicación, última verificación, pruebas superadas, incidencias y estado.

## Cómo se determina el estado

Módulo `local/stability.py`. Las verificaciones solo leen; no crean, modifican ni borran datos de clientes:

| Verificación | Crítica |
| --- | --- |
| Despliegue y registro de versión (versión instalada válida, compilación) | Sí |
| Base de datos y migraciones (todas las migraciones del código aplicadas) | Sí |
| Datos esenciales accesibles (usuarios, clientes, órdenes, estados) | Sí |
| Archivos de la interfaz y plantillas | Sí |
| Seguimiento de órdenes (consulta real del tablero) | Sí |
| Agenda de citas (servicios disponibles) | Sí |
| Reportes y saldos | No |
| Servicio de correo configurado | No |

## Ejecución automática en el servidor (1.5.154)

Tres tareas programadas de Vercel (`vercel.json`, compatibles con el plan: una ejecución diaria por tarea):

| Hora UTC | Hora Ecuador | Ruta |
| --- | --- | --- |
| 06:00 | 01:00 | `/api/cron/stability` |
| 14:00 | 09:00 | `/api/cron/reminders` (avisos y, en bloque independiente, estabilidad) |
| 22:00 | 17:00 | `/api/cron/stability-night` |

Las rutas programadas solo responden a la plataforma (cabecera `Authorization: Bearer CRON_SECRET`); sin la clave devuelven 404 y nunca muestran detalles. Además, al consultarse el indicador se verifica como mucho cada 30 minutos. Así, sin depender de visitas, cada versión acumula 3 verificaciones en cualquier período de 24 h.

## Registro

- `stability_runs`: las últimas 60 ejecuciones con el resultado de cada prueba, fecha, hora, versión y origen (`programada` o `automática`).
- `stability_versions`: resumen permanente por versión (ejecuciones, correctas, inicio del período vigente, fallos críticos con fecha). Se conservan las últimas 40 versiones: publicar una versión nueva inicia su propio seguimiento sin perder el historial anterior, visible en «Versiones anteriores».

## Estados

- **No verificada**: la versión instalada aún no tiene ninguna verificación registrada.
- **Verificando**: hay una verificación en curso.
- **En observación**: la última verificación superó todas las pruebas críticas; se muestra el tiempo restante y cuántas verificaciones correctas faltan.
- **Versión estable** (distintivo verde «ESTABLE»): al menos 3 verificaciones correctas y 24 h completas desde el inicio del período, sin fallos críticos. La comparación usa el instante exacto.
- **Requiere atención**: la última verificación tuvo un fallo crítico; se registra como incidencia y el período se reinicia con la siguiente verificación correcta.

## Cómo comprobarlo

1. Pulsar el distintivo (acceso o barra superior): «Período de seguimiento», «Tiempo restante», «Próxima verificación programada» y «Última verificación».
2. `GET /api/public/stability` devuelve los mismos datos (sin datos de clientes).
3. Vercel → proyecto → Settings → Cron Jobs: las tres tareas y su última ejecución.

## Monitor y barra superior (1.5.156)

- Estados y colores: **Verificación pendiente** (azul, sin resultados), **Verificando** (azul), **En observación** (ámbar), **Versión estable** (verde) e **Incidencia detectada** (rojo).
- «Versión estable» exige además que la **última verificación supere todas las pruebas**, también las no críticas (por ejemplo, el correo). Una prueba no crítica fallida no reinicia el período, pero impide declarar la versión estable hasta que se supere.
- La ventana muestra cuenta atrás (anclada a la hora del servidor y al fin del período que calcula el servidor), barra del período, verificaciones completadas y pendientes, última y próxima verificación, pruebas, incidencias y versiones anteriores. Al cumplirse el tiempo vuelve a consultar al servidor, que decide el estado.
- Recargar la página o iniciar sesión no reinicia nada: el período lo fija el servidor con la primera verificación correcta de la versión. Lo que inicia un período nuevo es publicar otra versión.
- Barra superior: el indicador de versión y el de estabilidad son un único componente (`#release-chip`): versión, luz de estado y estado. Al pulsarlo abre «Estabilidad de la versión»; si hay una actualización pendiente o en curso abre el panel de actualizaciones, también accesible desde la ventana de estabilidad. Por debajo de 1000 px el componente va en el menú.
- Buscador: «/» o Ctrl+K enfocan la búsqueda de órdenes, clientes y números de serie.
