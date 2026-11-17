# Centro de notificaciones Premium Compact (1.5.266)

Ventana que se abre con la campana. Se rediseñó su presentación; la lógica no cambió:

- los avisos, su lectura y no lectura, y los contadores siguen igual;
- los permisos y el sonido no cambian;
- el historial completo («Ver el historial», `#notices`) se mantiene igual.

## Diseño

- **Contenedor:**
  - hasta 420 px de ancho y 620 px de alto, según la pantalla;
  - radio de 14 px, borde azul discreto y sombra suave.
- **Encabezado fijo:**
  - icono y título «Centro de notificaciones»;
  - dos insignias: «N sin leer», destacada si hay pendientes, y «N en total»;
  - botones de sonido y cerrar de 34 px.
- **Cuerpo:**
  - desplazamiento interno con barra delgada;
  - los avisos se agrupan por categoría: Órdenes, Presupuestos, Pagos, Seguimientos, Citas, Correos, Conversaciones, Licencias, Sistema y Alertas.
- **Grupos:**
  - cada grupo tiene icono, color de acento y su contador («2 sin leer» o «3 avisos»);
  - solo aparecen los que tienen avisos.
- **Tarjetas de aviso:**
  - acento según la prioridad: azul informativo, ámbar pendiente, verde completado y rojo suave urgente;
  - título fuerte y detalle tenue, cada uno en hasta 2 líneas, con el texto completo al pasar el cursor;
  - hora relativa y flecha de «abrir».
- **Avisos sin leer:** se distinguen por punto, título en negrita y la etiqueta «Sin leer», no solo por el color.
- **Muchos avisos en una categoría:**
  - se muestran 3;
  - «Ver N más» amplía hasta 8;
  - el resto se ve en el historial.
- **Pie fijo:**
  - «Marcar todas como leídas» y «Ver el historial», con icono y 38 px de alto;
  - en móvil se apilan a todo el ancho.

## Categorías

La clasificación más fina es **solo del panel** (`ncpCategory`). Presupuestos, Pagos y Seguimientos se separan de Órdenes según la clave y el icono del aviso. El historial conserva sus pestañas.

## Comportamiento

- Al abrir, animación breve y el foco en el título.
- Cada aviso es un botón: Enter o Espacio lo abre, lo marca como leído y cierra el panel.
- Escape cierra el panel y devuelve el foco a la campana.
- Hover y foco visibles.
- Con «movimiento reducido» no hay animaciones.
- En móvil la ventana ocupa el ancho disponible, a 12 px de cada borde, y es más alta.
- A 320 px el título pasa a dos líneas.

## Pruebas

- **Navegador:** a 1920, 1366, 1024, 768, 390 y 320 px.
- **Casos cubiertos:**
  - apertura;
  - contadores contra el servidor;
  - textos largos;
  - scroll interno;
  - categorías y «Ver más»;
  - teclado (Enter y Escape);
  - marcar todas como leídas;
  - historial;
  - movimiento reducido.
- **Datos:** avisos ficticios.

# Centro de notificaciones y pendientes 2.0 (1.5.287)

El módulo `#notices` («Ver el historial» en la campana) pasa a tener dos vistas:

- **Pendientes** (`#notices?vista=pendientes`): lo que requiere una acción real.
- **Notificaciones** (`#notices?vista=notificaciones`): el historial informativo de siempre, con su lectura y ocultación por persona.

La campana no cambia; su enlace «Ver el historial» abre la vista Notificaciones.

## De dónde salen los contadores

`GET /api/pending` (módulo `local/pending_center.py`) calcula cada pendiente en cada consulta, a partir del estado real de su módulo. No existe una tabla de pendientes ni datos simulados, y el módulo solo lee la base.

| Tarjeta | Cuenta mientras… | Desaparece cuando… |
|---|---|---|
| Órdenes pendientes | la orden no está entregada | se entrega |
| Citas por confirmar | la cita está «solicitada» y no eliminada (también si su fecha ya pasó, marcada como vencida) | se confirma, reprograma, cancela o elimina en la Agenda |
| Presupuestos por aprobar | está «enviado» o el cliente pidió cambios («modificacion») | el cliente decide o el taller lo reemplaza o cancela |
| Repuestos en seguimiento | no está instalado, cancelado ni con la orden entregada; también las cancelaciones por decidir | se instala, se cancela o se decide la solicitud |
| Mensajes por responder | conversación sin revisar o esperando asesor, respuesta de mantenimiento sin gestionar o PQRS sin responder | se atiende en su módulo |
| Licencias por vencer | licencia entregada dentro del umbral «Por vencer» de Licencias Pro, o vencida sin renovar | se renueva o deja de estar vigente |
| Alertas del sistema | incidencias de ADI AutoCare, base local, respaldo atrasado, actualización disponible, buzón casi lleno, correos devueltos, avisos fallidos, cuentas por aprobar o borrador de condiciones | la condición deja de existir |

Cada contador coincide exactamente con los elementos que se listan de ese módulo.

En producción, el 17/11/2026 había 6 citas «solicitada», todas con fecha futura. Coinciden con «6 citas por confirmar»; no se mezclan confirmadas, canceladas ni completadas.

## Cuatro conceptos separados

- **Visto / sin ver:** usa la misma lectura por persona que las notificaciones (`notification_reads`). Marcar como visto no resuelve nada.
- **Visible / oculto:** solo existe para las notificaciones. Un pendiente no se puede ocultar. Ocultar una alerta en Notificaciones no la quita de Pendientes mientras la condición siga activa.
- **Pendiente / en proceso:** lo decide el estado del registro. Por ejemplo, una orden en diagnóstico, reparación o pruebas está «en proceso».
- **Normal / importante / urgente:** prioridad calculada con fechas reales:
  - entrega o vigencia vencida, cita en menos de 24 h o ya pasada, repuesto retrasado o con llegada vencida, licencia a 7 días o menos;
  - prioridad «urgente» de la orden;
  - PQRS sin primera respuesta pasado su plazo de 48 h.

Ninguna acción del centro cambia el estado de una orden, una cita o un presupuesto.

## Acciones

Cada pendiente ofrece su acción directa. Todas abren el registro en su módulo:

- Abrir orden y Ver entregas;
- Confirmar o gestionar cita;
- Revisar presupuesto;
- Ver seguimiento del repuesto;
- Responder conversación o PQRS;
- Consultar licencia;
- Abrir detalle.

Confirmar una cita se hace en la Agenda, porque exige registrar la autorización del cliente (aceptación y últimos 4 dígitos). No hay acciones destructivas en el centro.

## Permisos

- **Administración** ve todo.
- **Un técnico** ve:
  - las órdenes, presupuestos, repuestos y citas asignados a él o todavía sin asignar;
  - sus PQRS asignadas.
- **Licencias y alertas del sistema** son solo de administración.

## Actualización

- La vista consulta `/api/pending` cada 45 s (el mismo ritmo de la campana) mientras la pestaña está visible.
- Envía `since=<revisión>`, y si nada cambió el servidor responde `{"unchanged": true}` sin repetir la lista.
- Ante un fallo conserva los últimos datos, muestra «Sin conexión · reintento automático» y reintenta con espera progresiva, de 30 s hasta 5 min.
- Vuelve a consultar al recuperar la conexión o al volver a la pestaña.
- Los pendientes nuevos se resaltan y se anuncian de forma discreta a los lectores de pantalla. Los avisos emergentes siguen siendo los de la campana.
- No se usan WebSocket ni SSE, porque las funciones de Vercel no mantienen conexiones abiertas.

## Correcciones incluidas

- **Avisos por cita:** antes había un `LIMIT 8` que mezclaba solicitudes con citas ya confirmadas. Con 6 solicitudes y 3 confirmadas se mostraban solo 5 solicitudes, y las confirmadas quedaban como «Nueva cita registrada» sin límite de tiempo. Ahora se listan todas las solicitudes, y las confirmadas solo durante 48 h desde su registro.
- **Marcar como leído y ocultar:** antes solo funcionaban con los 40 primeros avisos. Ahora validan contra la lista completa.

## Pruebas

`local/tests/test_pending_center.py` cubre:

- contadores frente a condiciones reales, por cada estado de cita, presupuesto, orden y repuesto;
- separación de lectura, ocultación y resolución;
- alertas que sobreviven a ocultar el aviso;
- alcance por técnico;
- respuesta «sin cambios»;
- lista completa de solicitudes de cita.
