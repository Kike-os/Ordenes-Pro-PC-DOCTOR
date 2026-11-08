# Estados de reparación (1.5.257)

Fuente única: `local/repair_status.py`. La usan el panel, el seguimiento público, la hoja A4, los reportes, el tablero de seguimiento, ADI y los avisos.

## Los once estados

| Código | Estado | Tipo |
|---|---|---|
| `pendiente` | En espera de diagnóstico | Etapa |
| `diagnostico` | Diagnóstico en proceso | Etapa (nuevo) |
| `reparacion` | Reparación en proceso | Etapa |
| `presupuesto` | Pendiente de aprobación de presupuesto | Espera |
| `esperando_cliente` | Esperando respuesta del cliente | Espera |
| `esperando_repuesto` | Esperando repuesto | Espera (nuevo) |
| `revision_recurrente` | Revisión por falla recurrente | Incidencia |
| `pruebas` | Pruebas técnicas y control de calidad | Etapa (nuevo) |
| `espera_entrega` | En espera de entrega | Etapa |
| `listo` | Listo para entregar | Etapa |
| `entregado` | Entregado | Cierre |

**Compatibilidad.** Los códigos anteriores no cambian. La migración `096_repair_statuses.sql` solo añade estados, cambia etiquetas, crea dos tablas vacías y una columna. No cambia el estado de ninguna orden. El historial es inmutable y conserva sus etiquetas antiguas («En espera», «Procesando», «Aprobación de presupuesto», …). `repair_status.code_for_label` y `statusCodeOf` (en `app.js`) las reconocen.

## Cambios automáticos (solo por eventos reales)

| Evento registrado | Desde | Pasa a |
|---|---|---|
| Orden registrada | — | En espera de diagnóstico |
| Seguimiento «Diagnóstico técnico» | En espera de diagnóstico | Diagnóstico en proceso |
| Presupuesto enviado al cliente | Etapas técnicas, espera de repuesto o de respuesta | Pendiente de aprobación |
| Presupuesto aprobado (total o parcial) | Pendiente de aprobación o esperando respuesta | La etapa anterior a la espera («Diagnóstico en proceso» si estaba en espera de diagnóstico), o «Esperando repuesto» si falta un repuesto. **No marca la reparación como iniciada.** |
| Repuesto solicitado | En espera, diagnóstico, reparación o revisión | Esperando repuesto |
| Repuesto recibido o cancelado (sin otros en camino) | Esperando repuesto | La etapa anterior a la espera. Además se avisa al técnico responsable. |
| Instalación del repuesto o seguimiento «Reparación» | En espera, diagnóstico o esperando repuesto | Reparación en proceso |
| Seguimiento «Pruebas» o «Servicio finalizado» | Diagnóstico, reparación o revisión | Pruebas técnicas y control de calidad |

«Listo para entregar» y «Entregado» se marcan a mano. «Entregado» mantiene sus reglas de saldo. Nada cambia por el paso del tiempo. La corrección de un seguimiento tampoco mueve el estado.

## Reglas y auditoría

- **Mismo estado sin comentario:** no se registra nada, para evitar duplicados.
- **Cambios que requieren motivo (al menos 10 caracteres):**
  - pasar a «Esperando repuesto» sin un pedido activo;
  - pasar a «Pruebas» desde «En espera de diagnóstico».
- **Reglas que siguen igual:** la falla recurrente exige motivo y técnico, y solo administración puede revertir una entrega.
- **Auditoría (`order_status_log`, inmutable):** guarda el estado anterior y el nuevo, la fecha, el usuario, el motivo y el evento que lo produjo (`manual`, `edicion`, `quote_sent`, `part_received`, …).
- **Dónde se consulta:** en el detalle de la orden, «Auditoría de estados», junto con cada aviso al cliente y su resultado.

## Avisos al cliente

- **Cuándo se avisa:** solo en estos cambios:
  - presupuesto pendiente;
  - respuesta pendiente;
  - espera de repuesto;
  - revisión por falla recurrente;
  - equipo listo.
- **Cuántos avisos:** uno por cambio y por canal (correo o WhatsApp Business, con las mismas reglas de consentimiento y preferencias que los avisos de repuestos).
- **Avisos que se omiten:**
  - el mismo aviso dentro de las 72 horas siguientes;
  - el de «Pendiente de aprobación» cuando el cambio lo produjo el envío del presupuesto, porque el cliente ya recibe el presupuesto con su enlace;
  - el de «listo» si ya se avisó «listo» desde el pedido del repuesto.
- **Estados del envío:**
  - «enviado» significa aceptado por el servidor;
  - «omitido» incluye el motivo;
  - los avisos fallidos se reintentan en la tarea diaria, hasta 3 intentos.
- **Desactivar:** administración puede apagar los avisos automáticos desde la auditoría de la orden.

## Vista para el cliente

El seguimiento público muestra:

- el estado actual con una explicación clara;
- lo que se espera del cliente (aprobar el presupuesto o comunicarse);
- la última actualización;
- la fecha estimada, **solo si el taller la marcó como confirmada** en «Gestión técnica»;
- el historial de estados, solo con etiquetas y fechas.

Nunca muestra notas internas, motivos, proveedores ni costos.

## Mensaje de seguimiento con ADI

El botón «Mensaje con ADI», en la tarjeta de estado, redacta un mensaje para WhatsApp o correo:

- **Datos que usa:** los técnicos de la orden, ya depurados, sin cliente, serie, precios ni credenciales.
- **Lo que pide a ADI:** distinguir lo confirmado de una posibilidad técnica.
- **Sin ADI disponible:** usa la explicación del estado real.
- **Envío:** el mensaje es editable y no se envía desde ahí. «Continuar en Comunicación» abre el envío habitual de la orden.

La calidad del texto con el modelo real solo se puede comprobar en producción, que es donde está la clave.
