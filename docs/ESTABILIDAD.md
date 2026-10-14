# Indicador de estabilidad de versiones (1.5.153)

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

Cada ejecución se registra con fecha, hora, versión, origen y resultado de cada prueba (`system_state` → `stability_runs`, últimas 60; sin migración). Se ejecutan como mucho cada 30 minutos al consultarse el indicador y una vez al día con el cron.

- **No verificada**: la versión instalada aún no tiene ninguna verificación registrada.
- **Verificando**: hay una verificación en curso.
- **En observación**: la última verificación superó todas las pruebas críticas, pero no han pasado 24 h desde la primera verificación correcta o hay menos de 3 verificaciones correctas.
- **Estable**: 24 h de seguimiento, al menos 3 verificaciones correctas y ningún fallo crítico desde la primera correcta.
- **Requiere atención**: la última verificación tuvo un fallo crítico. Tras corregirlo la versión vuelve a «En observación», nunca directamente a «Estable».

Un despliegue correcto no basta: cada versión nueva empieza «No verificada» y recorre el ciclo. Las pruebas no críticas fallidas figuran como incidencias sin impedir la estabilidad. La batería de pruebas automáticas previa a cada publicación sigue siendo obligatoria y no se sustituye.
