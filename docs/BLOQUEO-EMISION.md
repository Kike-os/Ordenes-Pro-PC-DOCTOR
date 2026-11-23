# Bloqueo de emisión y envío de comprobantes

Mientras la facturación electrónica se configura, el **servidor** bloquea todo lo que crea, firma o envía un comprobante. No basta con
ocultar botones: el bloqueo se comprueba en el backend y alcanza a la API, la tarea programada y los reintentos.

## Qué bloquea

| Operación | Dónde se comprueba |
|---|---|
| Emitir en Órdenes Pro (asigna secuencial y clave de acceso) | `invoicing.emit` |
| Enviar al SRI, reprocesar y anular en AZUR | `azur_invoicing.send` / `annul` y, por separado, `azur_client._request` (POST a `/factura/emision`, `/anular`, `/reprocesar`) |
| Consulta automática de AZUR (cron 09:00 / 17:00) y correo al autorizarse | `app.py` (cron) e `invoice_autosend` |
| Correos de factura: prueba, cliente y reenvío (incluidos los reintentos) | `invoice_documents.send` |

Las consultas de solo lectura y la vista previa local siguen disponibles. La API responde **423** con el texto
«CONFIGURACIÓN EN CURSO — EMISIÓN Y ENVÍO BLOQUEADOS».

## Dos llaves

1. **Variable de entorno** `FACTURACION_EMISION_BLOQUEADA`: cualquier valor distinto de `NO` (incluida su ausencia) bloquea. Esta llave
   también corta las llamadas de emisión en el cliente de AZUR, aunque la base diga otra cosa.
2. **Base de datos** (`invoicing_emission_lock`, migración 117): arranca **cerrada**. Si la tabla no existe o no tiene fila, cuenta como
   cerrada.

Para emitir hacen falta las dos abiertas.

## Abrir o cerrar (solo administración)

`POST /api/invoicing/emission-lock`

- Cerrar: `{"locked": "1", "reason": "…"}`, siempre permitido.
- Abrir: `{"locked": "0", "confirm": "HABILITAR EMISION", "reason": "motivo de 10 a 300 caracteres"}`.

Cada cambio queda en `invoicing_emission_lock_events` (no se puede modificar ni borrar) y en la auditoría (`emission_lock_opened` /
`emission_lock_closed`). `GET /api/invoicing/emission-lock` devuelve el estado.

Abrir el bloqueo **no** activa la emisión real: siguen vigentes el modo de pruebas (`TEST_MODE`) y el rechazo de credenciales de producción
sin `AZUR_PRODUCCION_AUTORIZADA=SI`.
