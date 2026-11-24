# ADI Live Support Center 4.0 · Enterprise Customer Experience (1.5.333)

## Errores encontrados y su causa

| Error | Causa | Corrección |
|---|---|---|
| Conversaciones antiguas activas para siempre | **No existía ningún cierre por inactividad**: solo se cerraban si el personal pulsaba «Cerrar» | Smart Session Timeout en el servidor: cierre a los 8 minutos de inactividad válida |
| Contador de «activas» inflado | Por la misma causa: las conversaciones abandonadas seguían abiertas | Las cerradas nunca aparecen en «Activas»; hay filtros por estado y canal |
| Cierre que dependía de que alguien tuviera el sistema abierto | No había ningún temporizador en el servidor | Cada sesión guarda `expires_at`; el cierre se aplica de forma atómica con su hora **exacta** en cuanto cualquier evento toca el sistema, y también con las tareas programadas |
| ADI ofrecía repuestos solo por la marca (p. ej., una batería HT03XL) | El prompt no exigía el modelo exacto | Regla nueva: pedir el modelo exacto o el número de parte, consultar el catálogo y el inventario reales y no ofrecer piezas sin confirmar la compatibilidad |

## Cierre automático (servidor, fuente de verdad)

**Tablas:**

- `support_sessions` (migración 123):
  - apertura;
  - último mensaje del cliente, de ADI y del asesor;
  - última actividad válida y quién la hizo;
  - expiración;
  - aviso, cierre efectivo, motivo y tipo;
  - reaperturas;
  - pausa;
  - procesamiento de ADI;
  - versión (control de concurrencia).
- `support_events`: registro idempotente, con una clave única por evento.

**Tiempos predeterminados** (configurables en *Asistencia → Centro de atención → Configuración*):

- 480 s de inactividad máxima;
- advertencia visual al minuto 5;
- aviso al cliente al minuto 7;
- cierre al minuto 8.

**Qué reinicia el contador y qué no:**

- **Sí lo reinicia** una intervención válida: mensaje del cliente, respuesta de ADI o respuesta del asesor (web y WhatsApp).
- **No lo reinician:**
  - las consultas periódicas;
  - las confirmaciones de lectura o entrega;
  - los avisos internos;
  - el propio aviso de cierre;
  - los reintentos y los mensajes duplicados (la misma clave del proveedor).

**Protecciones:**

- **ADI procesando:** no se cierra durante el procesamiento, con un límite de 90 s. Nunca queda abierta indefinidamente.
- **Pausa administrativa:** con motivo y un máximo de 60 minutos.
- **Cliente esperando al personal:** si el último mensaje es del **cliente**, la inactividad es de PC-DOCTOR. **No se cierra**: queda «esperando respuesta del personal», con una alerta y un evento. Una solicitud de asesor (`adi_handoffs`) **nunca** se pierde.
- **Cierre atómico:** `UPDATE … WHERE status='activa' AND version=? AND expires_at<=?`. Si el cliente escribe justo antes, su mensaje gana y la conversación no se cierra.
- **Sin duplicados:** el aviso, el cierre y la reapertura tienen clave de idempotencia.

**Mensajes de aviso y cierre:**

- En el chat web se muestran.
- Por WhatsApp están **desactivados** por defecto: respetan las ventanas y plantillas de Meta, y el cierre interno no es el vencimiento de la ventana de WhatsApp.
- Si no se pueden enviar, la conversación se cierra igual internamente.

**Reapertura:**

- **Automática:** cuando el cliente vuelve a escribir. Se conserva el historial y no se duplica por un mismo mensaje.
- **Manual:** la hace el personal.
- **Identidad:** la verificación de identidad **no** se recupera; ADI Secure Identity la vuelve a exigir según sus propias reglas.

## Activación segura

1. La configuración nace **desactivada**.
2. **Simulación:** muestra cuántas conversaciones se cerrarían, cuántas esperan al personal y cuántas siguen activas. No cambia nada.
3. **Activar** (escribiendo ACTIVAR):
   - las conversaciones antiguas se cierran **en silencio**, sin avisos ni mensajes a clientes;
   - las que esperan al personal no se cierran.

## Tareas programadas

- **Actual:** en el plan de Vercel, las tareas programadas son diarias. El barrido corre en la tarea de estabilidad y, sobre todo, con cada evento:
  - el chat web consulta cada 3 s mientras el cliente tiene la página abierta;
  - el webhook de WhatsApp;
  - el panel del personal.
- **Opcional, requiere autorización:** `GET /api/cron/live-support` con `CRON_SECRET`, llamado **cada minuto** por un programador externo. Solo hace falta para enviar avisos proactivos por WhatsApp en el minuto exacto.

## Interfaz

**Bandeja:**

- **filtros:** todas, sin leer, esperan asesor, con ADI, con asesor, esperando cliente, próximas a cerrar, reabiertas, y entre las cerradas, automáticas y manuales;
- filtro de canal;
- tiempo restante en cada tarjeta.

**Conversación:**

- **contador:**
  - muestra tiempo de inactividad, tiempo restante, barra de progreso y hora de la última actividad;
  - colores: verde activa, amarillo esperando, rojo cierre próximo, gris cerrada;
  - solo **muestra** `expires_at`, no decide.
- **acciones nuevas:**
  - «Pausar cierre», con motivo;
  - «Nota interna», que **nunca** se envía al cliente: `visibility='internal'` y la vista pública solo lee las públicas.

**Resumen:** activas, clientes esperando respuesta, cerradas automática y manualmente, reabiertas, primera respuesta promedio y resolución promedio, a partir de registros reales de 7 días.

**Consulta adaptativa:**

- la conversación abierta, cada 3 s;
- la bandeja, cada 3 s con una conversación abierta y cada 6 s sin ella;
- nada con la pestaña oculta;
- los mensajes se cargan de forma incremental y se conserva la posición de lectura.

## Pruebas

`local/tests/test_live_support_timeout.py` (11 pruebas, con reloj simulado) cubre:

- desactivado por defecto, y simulación sin cambios;
- activación con cierre silencioso de lo antiguo;
- minuto 5, minuto 7 (sin aviso duplicado) y cierre exacto al minuto 8;
- respuesta a los 7:59;
- mensaje tardío: cierre a la hora exacta y una sola reapertura con un mensaje duplicado;
- espera de asesor (no se cierra);
- asesor, ADI procesando con su límite, y pausa con su límite;
- cierre manual, reapertura y conversaciones simultáneas, con cierre idempotente;
- las consultas no reinician el contador;
- reinicio del servidor;
- rutas y permisos.

**Revisión visual:** en 1440, 768, 390 y 320 px, sin desbordamiento. El contador sigue al servidor.

## Pendiente

- **[Administración]** Activar el cierre automático en producción **después** de revisar la simulación.
- **[Administración]** Si quieres avisos proactivos por WhatsApp al minuto 7: autorizar un programador externo por minuto y confirmar la plantilla aprobada en Meta.
- Integración visual completa estilo Zendesk o Intercom: los tres paneles ya existen; el refinamiento visual queda para la siguiente iteración.
