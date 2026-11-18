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

## 1.5.288 · Centro de Control Operativo

**Gestionar pendiente.** Cada fila tiene el botón «Gestionar», que abre un panel lateral (diálogo modal: el foco queda dentro, Escape lo cierra y el foco vuelve a la fila). Muestra la identificación, el cliente o la entidad, el estado, la prioridad, el responsable, la fecha de creación y de vencimiento, la última actividad, cuándo se resuelve, el historial del registro de origen, las observaciones internas y las acciones permitidas.

**Las acciones son las de cada módulo.** El panel llama a los mismos endpoints que usan Órdenes, Agenda, Presupuestos, Repuestos, PQRS y ADI AutoCare. El servidor vuelve a comprobar permisos, estado y datos en cada acción:

| Módulo | Acciones en el panel | Endpoint |
|---|---|---|
| Órdenes | Actualizar estado y responsable (administración). Observación técnica. Pasar a «En espera de entrega». Registrar la entrega, con comprobación de saldo. | `/api/order-status`, `/api/pending/action` (`assign`), `/api/orders/{id}/follow-up` |
| Citas | Confirmar, con la autorización real del cliente: aceptación y 4 dígitos. Reprogramar. Cancelar con motivo. Llamar, WhatsApp o correo. Registrar el resultado si ya pasó la hora. | `/api/appointments/{id}` |
| Presupuestos | Registrar la decisión que comunicó el cliente, con nota obligatoria. Reenviar con un enlace nuevo como recordatorio. Cancelar con motivo. | `/api/quotes/{id}` |
| Repuestos | Avanzar a la etapa siguiente. Actualizar la fecha estimada. Registrar o resolver una incidencia. Informar al cliente en el seguimiento. | `/api/orders/{id}/part-requests/{rid}` |
| Mensajes | Responder una PQRS por correo. Asignarla (administración). Enlaces a Atención en vivo y a Mantenimientos. | `/api/pqrs/{id}` |
| Licencias | Consultar o renovar en Licencias Pro. Recordatorio. | — |
| Alertas | Reconocer. Silenciar 1–72 h con motivo, solo advertencias. Registrar la resolución. Incidencias de AutoCare: pasar «En revisión» o «Resuelta». | `/api/pending/action`, `/api/autocare/incident` |

**Resuelto ≠ visto ≠ gestionado.**
- Un pendiente sale de la bandeja solo cuando su módulo de origen lo cierra. Entonces el panel muestra «Pendiente resuelto», y su trazabilidad queda en el módulo y en «Actividad».
- Ni la observación, ni el recordatorio, ni el reconocimiento, ni el silencio, ni la resolución registrada de una alerta lo resuelven.
- Un fallo activo («Crítico»: errores del sistema, almacenamiento y respaldos) no se puede silenciar.

**Registro de gestión (`pending_notes`, migración 105).**
- Es de solo anexado: observaciones, reconocimientos, silencios, recordatorios y resoluciones registradas.
- Se ancla al registro de origen (`orders:12`, `appointments:5`…), no al estado. Por eso una observación sigue con la orden aunque cambie de estado.
- Si la tabla todavía no existe en la base, el centro sigue funcionando y avisa de que esas funciones requieren la actualización de la base.
- Una repetición idéntica en 15 s se ignora, para evitar el doble clic.

**Actividad (`/api/pending/activity`).** Reúne:
- las acciones auditadas de los módulos;
- los cambios de estado de órdenes;
- la gestión del centro;
- las lecturas;
- en administración, los envíos de correo fallidos y sus reintentos, sin destinatario.

Administración ve a todo el equipo; un técnico, solo lo suyo. Se puede filtrar por módulo, tipo, persona, fechas y texto (por defecto, los últimos 30 días, hasta 500 filas). Se exporta a CSV con las fórmulas neutralizadas. La pestaña no se actualiza sola, para no hacer consultas innecesarias.

**Diseño Premium Compact 3.0.**
- Indicadores que filtran: críticos, urgentes, vencidos, requieren decisión, sin ver y silenciadas.
- Tarjetas por módulo más bajas.
- Orden por urgencia, vencimiento, antigüedad o última actividad.
- Acciones rápidas al pasar el cursor; siempre visibles en pantallas táctiles.
- Filtros conservados durante la sesión del navegador.
- Textos en español e inglés.
- Sin animaciones con movimiento reducido.

## 1.5.289 · Centro de Notificaciones y Pendientes Premium 3.0 y flujo de resolución de órdenes

**Indicadores.**
- Pendientes activos: quita el filtro rápido.
- Críticos, Urgentes, Vencidos, Requieren decisión y Sin ver.
- Solucionados hoy: abre «Solucionadas» con la fecha de hoy.
- Silenciadas y Pospuestos solo aparecen cuando existen.

Todos salen de los registros reales.

**Secciones de «Pendientes».** Se combinan con los filtros y la búsqueda; la búsqueda incluye el correo del cliente.
- *Requieren mi atención*: lo asignado a mí o sin responsable. Quedan fuera los pendientes silenciados, los pospuestos y los que esperan al cliente o a un tercero, salvo que requieran una decisión.
- *Críticas y urgentes*.
- *Pendientes de decisión*.
- *Asignadas a otros usuarios*.
- *En seguimiento*: en proceso, en espera, pospuesto, reconocido, con recordatorio o con responsable asignado.
- *Todos*.

La lista se muestra de 60 en 60 («Mostrar más»). La sincronización periódica conserva la posición de lectura.

**Estados operativos.** Se calculan desde el registro de origen y la gestión, y son distintos del estado de la orden:

| Estado | Cuándo |
|---|---|
| Pendiente / En proceso | Según el registro. |
| En espera de cliente | Presupuesto enviado y vigente, o la orden espera aprobación o respuesta del cliente. |
| En espera de tercero | Repuesto pedido o en tránsito sin incidencia, o la orden espera un repuesto. |
| Pospuesto | Aplazamiento vigente. |

Si el plazo venció, deja de considerarse «en espera»: hay que actuar. Resuelto y Cancelado están en «Solucionadas».

**Prioridades y reglas.**
- Las prioridades se muestran como Crítica, Alta, Media y Baja. Las claves internas no cambian.
- Administración ajusta los umbrales de «Reglas de urgencia»: entrega de órdenes, horas para citas, vigencia y respuesta de presupuestos, llegada de repuestos y vencimiento de licencias.
- Se guardan en `system_state` (`pending_rules`), validados por rango y por coherencia (el umbral de prioridad media no puede ser menor que el de alta).
- Los valores iniciales son los criterios anteriores. No cambian ningún registro.
- El plazo de primera respuesta de las PQRS lo sigue fijando su módulo.

**Panel de resolución.** La barra *Resolver | Asignar | Posponer | Abrir módulo | Registrar seguimiento* lleva a la acción real de cada caso. Abre el formulario o enfoca el botón, pero no ejecuta nada por sí sola. Si un destino no existe para ese pendiente, el botón aparece desactivado con su motivo.

Acciones de **órdenes**:
- Falla reportada, diagnóstico y recomendaciones a la vista.
- *Registrar o actualizar diagnóstico*: solo administración, igual que «Editar orden». Usa `/api/pending/action` `diagnosis` con control de revisión y cambia solo `findings` y `recommendations`, nunca importes ni presupuesto. Queda en el historial y en la auditoría (`order_workspace_updated`).
- Presupuestos asociados con su estado.
- *Registrar seguimiento técnico* (`/api/orders/{id}/follow-up`).
- *Actualizar estado*: `/api/order-status` con `from_status`. Si otra persona cambió el estado mientras tanto, responde 409 y no lo pisa.
- Responsable y entrega, con comprobación de saldo.

Un presupuesto solo se aprueba por el enlace del cliente o con la decisión registrada por el personal con nota de cómo la comunicó.

Acciones de **alertas**:
- *Comprobar recuperación*: vuelve a evaluar la condición en el servidor. Solo sale de la bandeja si ya no se detecta.
- Incidencias de entrega de correo: reenviar a una dirección corregida o marcarlas revisadas, con los endpoints de Mail Pro.

**Responsable del seguimiento y aplazamiento (`pending_tracking`, migración 106, solo anexado con disparadores que impiden editar o borrar).**
- *Asignar* (administración) o *Tomar* (un técnico, si el pendiente no tiene responsable).
  - Solo a personas que ya ven ese pendiente: asignar no amplía permisos.
  - Las órdenes y las PQRS se asignan en su módulo. Para las órdenes, el centro anota además la fecha y quién asignó.
  - Si la orden cambia de responsable en su módulo, manda la orden.
- *Posponer*: desde mañana y hasta 90 días, con motivo. Nunca un fallo crítico. Vuelve solo al llegar la fecha o con *Reanudar*.
- Sin la migración, el centro sigue funcionando y lo indica.

**Solucionadas (`/api/pending/resolved`).** Lo que su módulo cerró, con persona, fecha y hora:
- órdenes entregadas;
- citas confirmadas o cerradas;
- presupuestos decididos o cancelados;
- repuestos instalados o cancelados, y cancelaciones decididas;
- PQRS respondidas o cerradas;
- respuestas de mantenimiento gestionadas;
- licencias renovadas;
- incidencias de AutoCare resueltas.

Varias acciones sobre el mismo registro en un día cuentan una vez. Administración ve al equipo; un técnico, lo suyo. Por defecto muestra los últimos 7 días, hasta 92 días por consulta, en páginas de 100.

**Duplicados.**
- *Notificaciones*: las que tienen el mismo título y detalle comparten `thread` y se agrupan con «×N» y un botón para desplegarlas. Por ejemplo, las copias de «Autorización registrada — Orden N.º …» o «Aviso de autorización enviado…» de una misma orden. Se marcan como leídas u ocultas juntas, y nada se borra. Los avisos de distintas órdenes o distintos eventos no se agrupan.
- *Alertas*: las iguales forman un solo pendiente con su cantidad. Cada aviso original conserva su lectura.

**Historial (antes «Actividad»).**
- Carga progresiva de 100 en 100; el CSV exporta hasta 2000 filas.
- Ya no repite la gestión del centro (antes aparecía en el registro y en la auditoría).
- La ruta `#notices?vista=actividad` sigue funcionando.
