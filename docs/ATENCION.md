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
