# Centro de Atención en Tiempo Real

Consola de tres paneles (1.5.45) sobre las conversaciones reales del chat público de Adi.

- **Actualización:** consulta al servidor cada 3 segundos (lista y conversación abierta). No usa WebSocket ni SSE porque el servidor publicado es de funciones sin conexión persistente. El indicador muestra el resultado de la última consulta y «Sin conexión» cuando falla.
- **Estados:** En atención por Adi, Esperando asesor, Tomada por asesor y Cerrada; «Nueva» mientras nadie del personal la haya abierto; contador de mensajes del cliente sin leer.
- **Acciones:** tomar, responder, reactivar a Adi, cerrar (con confirmación) y reabrir. Con un asesor a cargo, Adi no responde. Cada acción queda en `adi_actions` y en auditoría.
- **Vínculo con cliente y orden** (migración 031): se hace por número de orden exacto. Si el cliente escribió un número de orden que existe, se sugiere; nunca se vincula solo. El vínculo se puede retirar.
- Los mensajes se piden de forma incremental (`?after=`) y se identifican por su id: no se duplican.
- Adi, en este chat, responde con sus reglas internas (servicios, citas, seguimiento con orden y cédula). La redacción con IA es otra función y requiere la clave del proveedor en el servidor.

## Bandeja de conversaciones (1.5.62)

- La lista muestra cliente (o «Visitante N»), último mensaje, hora, estado, mensajes sin leer y, si hay orden vinculada, su número y estado actual.
- Búsqueda por cliente, orden o mensaje y filtros: Todas, Sin leer, Esperan asesor, Con ADI, Con asesor (con contador). Se aplican en el navegador sobre la lista recibida del servidor.
- Sin conversación abierta ya no hay paneles vacíos: el panel central muestra el resumen de atención (contadores y «Requieren tu atención», de la que más espera a la más reciente) y el panel de contexto se oculta. La flecha del encabezado de la conversación vuelve al resumen.
- Aviso emergente cuando escribe un cliente que espera a un asesor o una conversación que atiendes tú. Las conversaciones que resuelve ADI no interrumpen.
- La actualización sigue siendo por consulta cada 3 s (no es un canal en vivo).

## ADI en la pantalla de inicio de sesión

- En escritorio (desde 1100 px de ancho) ADI aparece acoplada a la derecha de la tarjeta de acceso, abierta y alineada con ella; en pantallas menores queda como orbe flotante. El formulario de inicio de sesión no cambia y conserva el foco.
- Se carga después del formulario (cuando el navegador está libre) y no consulta al servidor mientras no exista una conversación.
- Acciones rápidas: «Agendar cita» (abre la agenda real en `/citas`), «Consultar reparación», «Servicios técnicos» y «Hablar con un asesor» (relevo real al Centro de Atención).
- La voz es opcional y nunca se reproduce sola. Las claves de IA permanecen en el servidor.

### Consultar reparación (código temporal)

Conocer el número de orden no basta para ver datos:

1. El visitante escribe el número de orden (`POST /api/public/adi/order/request`).
2. Si la orden existe y tiene un correo válido, el sistema envía a ese correo un código de 6 dígitos que caduca en 10 minutos. La respuesta en pantalla es siempre la misma, exista o no la orden, y no muestra el correo.
3. Con el código (`POST /api/public/adi/order/verify`) se muestran solo el estado, el equipo, la fecha de ingreso, la entrega estimada y el enlace de seguimiento vigente. Ningún dato personal.

Protecciones: código de un solo uso, cinco intentos por código, cinco solicitudes por dirección cada 10 minutos y tres por orden cada 30; cada consulta verificada queda en la auditoría (`order_checked_by_client`). El chat ya no entrega el estado a partir del número de orden y la cédula: remite a esta verificación. Tabla `order_checks` (migración 038).

## Centro de Atenciones (panel del inicio, 1.5.116)

- Título «Centro de Atenciones» y subtítulo «Seguimiento de conversaciones y solicitudes pendientes». El encabezado muestra la conexión real («En línea · hora» de la última consulta correcta, o «Sin conexión · reintentando»).
- **Contadores sin solapes** (`live_support.summary`): cada conversación abierta cuenta en una sola categoría.
  - *Esperan respuesta*: con un asesor solicitado y el último mensaje es del cliente.
  - *Transferidas por ADI*: pasadas a un asesor y ya respondidas (en curso).
  - *Nuevas*: atendidas por ADI con mensajes que el personal aún no ha visto.
  Antes una misma conversación podía sumar en las tres.
- **Lista de atenciones** (hasta cinco, primero las que esperan respuesta y, entre ellas, la más antigua): cliente o número de conversación, origen («Transferida por ADI» o «Chat con ADI»), orden vinculada si existe, fecha y hora de ingreso, tiempo de espera y el último mensaje del cliente. Al pulsar una se abre esa conversación. No hay campo de prioridad en las conversaciones, así que no se muestra.
- Un solo botón, «Abrir Centro de Atención» (antes había dos que hacían lo mismo).
- Se actualiza cada 20 s con la pestaña visible (`GET /api/assistance`, solo administración) y avisa cuando aparece un cliente esperando respuesta.
