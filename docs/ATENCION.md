# Centro de Atención en Tiempo Real

Consola de tres paneles (1.5.45) sobre las conversaciones reales del chat público de Adi.

- **Actualización:** consulta al servidor cada 3 segundos (lista y conversación abierta). No usa WebSocket ni SSE porque el servidor publicado es de funciones sin conexión persistente. El indicador muestra el resultado de la última consulta y «Sin conexión» cuando falla.
- **Estados:** En atención por Adi, Esperando asesor, Tomada por asesor y Cerrada; «Nueva» mientras nadie del personal la haya abierto; contador de mensajes del cliente sin leer.
- **Acciones:** tomar, responder, reactivar a Adi, cerrar (con confirmación) y reabrir. Con un asesor a cargo, Adi no responde. Cada acción queda en `adi_actions` y en auditoría.
- **Vínculo con cliente y orden** (migración 031): se hace por número de orden exacto. Si el cliente escribió un número de orden que existe, se sugiere; nunca se vincula solo. El vínculo se puede retirar.
- Los mensajes se piden de forma incremental (`?after=`) y se identifican por su id: no se duplican.
- Adi, en este chat, responde con sus reglas internas (servicios, citas, seguimiento con orden y cédula). La redacción con IA es otra función y requiere la clave del proveedor en el servidor.
