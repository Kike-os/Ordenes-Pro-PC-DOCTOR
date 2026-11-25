# ADI Release Monitor 2.0

Ventana de estabilidad de la versión instalada de Órdenes Pro. Se abre desde el indicador de versión, en la barra superior o en la pantalla de acceso.

- Código del servidor: `local/stability.py` (motor y reglas) y `local/release_monitor.py` (comprobaciones nuevas, detalle técnico y avisos).
- Interfaz: `stabilityDetails` y las funciones `rm*` de `local/static/app.js`. Estilos `.rm-*` en `local/static/app.css`.

## Reglas de estabilidad

Las reglas no cambian con esta versión. Una versión es **estable** cuando cumple todos estos requisitos:

1. Lleva 24 h de seguimiento desde la primera verificación correcta.
2. Tiene al menos 3 verificaciones correctas dentro de ese período.
3. La última verificación no tiene fallos que impidan declararla estable.

El fin del temporizador por sí solo nunca la declara estable: decide el servidor.

Un fallo crítico reinicia el período, que vuelve a contar desde la siguiente verificación correcta.

Las verificaciones **manuales** («Verificar estado ahora» o AutoCare) se registran y pueden detectar incidencias. Desde 2.0 no inician el período ni suman verificaciones correctas, así que no permiten eludir los requisitos.

Cuentan para el período las verificaciones **programadas** y las automáticas:

- **Programadas:** tareas de Vercel Cron a las 01:00, 09:00 y 17:00, hora de Ecuador (`SCHEDULE_UTC`).
- **Automáticas:** se ejecutan al consultar el indicador, como máximo cada 30 minutos.

No dependen de que alguien tenga el navegador abierto.

## Estados visuales

| Color | Estado |
|---|---|
| Verde | Versión estable |
| Ámbar | En observación |
| Azul | Verificación en ejecución |
| Naranja | Advertencia: en observación, pero la última verificación tuvo una prueba no crítica con fallos |
| Rojo | Versión inestable (fallo crítico) |
| Gris | Verificación pendiente, o servidor sin conexión |

## Ventana

- **Temporizador regresivo HH:MM:SS.** Se calcula con el fin del período y la hora del servidor, así que no pierde precisión al cerrar la ventana, cambiar de módulo o recargar.
- **Barra de progreso** con el porcentaje real del período.
- **Requisitos** con su estado: tiempo, verificaciones correctas y ausencia de incidencias.
- **Datos:** publicación, última verificación, próxima programada, última sincronización, pruebas superadas y verificaciones de la versión.
- **Actualización automática:** el reloj avanza cada segundo y el estado se vuelve a consultar cada 60 s, sin recargar la página.
- **Solo para administración:**
  - «Verificar estado ahora»: diagnóstico real paso a paso, protegido contra ejecuciones duplicadas en el navegador y en el servidor;
  - «Copiar informe técnico»;
  - detalle de cada comprobación (resultado, tiempo y detalle);
  - incidencias con su resolución;
  - historial de ejecuciones.

  El detalle se sirve desde `GET /api/system/release-monitor`, que exige el rol de administración. La ventana pública solo muestra datos públicos.

## Comprobaciones

Hay 19 comprobaciones y todas son de solo lectura.

Las 15 anteriores son:
- base de datos;
- autenticación;
- clientes;
- órdenes;
- presupuestos;
- licencias e inventario;
- ventas y pagos;
- agenda;
- correo;
- notificaciones;
- integraciones;
- ADI;
- servicios internos y tareas programadas;
- copias de seguridad;
- registros de errores.

Las 4 nuevas son:

| Comprobación | Qué revisa |
|---|---|
| Migraciones | Migraciones publicadas frente a las aplicadas. No aplica nada. |
| Interfaz y archivos estáticos | Que los archivos principales y la plantilla estén desplegados y no vacíos. |
| Facturación electrónica | Ambiente, bloqueo de emisión, comprobantes en trámite, rechazados en 7 días y datos fiscales. No consulta a AZUR ni al SRI y no emite nada. |
| WhatsApp Business | Que esté configurado (sin mostrar credenciales), el uso del mes frente al límite y los envíos fallidos en 24 h. No envía mensajes. |

## Avisos (Centro de Notificaciones)

Cada aviso usa una clave estable, así que no se duplica:

- `release:observing:<versión>`: la versión entra en observación.
- `release:stable:<versión>`: la versión alcanza el estado estable.
- `release:cron-missed:<fecha>`: no llegan las verificaciones programadas (más de 18 h).

Las incidencias relevantes las sigue avisando ADI AutoCare.
