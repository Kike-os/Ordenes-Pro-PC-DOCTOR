# ADI 3.0 · fase 2: compromisos de pago (1.5.327)

Se registran en la ventana **Mensaje de seguimiento**, dentro de **Análisis integral de la orden**, en el bloque **Compromiso de pago**.

**Archivos:**

- Módulo: `local/payment_commitments.py`.
- Migración: `119_payment_commitments.sql`. Solo crea las tablas `payment_commitments` y `payment_commitment_events`. Hay que aplicarla desde **Sistema → Migraciones**. Mientras no esté aplicada, el bloque lo indica y el resto funciona igual.
- Ruta: `POST /api/orders/<id>/commitments`, con estas acciones:
  - `create`
  - `reschedule`
  - `cancel`
  - `review`
  - `close_review`

## Qué registra

Cada compromiso guarda estos datos:

- cliente, orden y factura vinculada, si existe;
- saldo al registrarlo;
- importe comprometido;
- fecha del compromiso y fecha acordada;
- forma de pago;
- usuario responsable;
- observaciones;
- evidencia de cómo lo aceptó el cliente: en persona, por llamada, por mensaje, por correo o por WhatsApp, con texto obligatorio;
- estado.

Cada cambio queda en `payment_commitment_events` y en la auditoría.

**El compromiso no modifica nada más:** ni pagos, ni saldos, ni facturas, ni vencimientos, ni la orden.

## Estados (calculados con los pagos confirmados de la orden)

| Estado | Cuándo |
|---|---|
| Pendiente | Vigente, a más de 3 días de la fecha acordada |
| Próximo a vencer | A 3 días o menos |
| Cumplido | Pagos confirmados desde el compromiso ≥ importe, o saldo en cero **sin** transferencias por conciliar |
| Cumplido parcialmente | Vencido con algún pago confirmado, pero menor al importe |
| Incumplido | Vencido sin pagos confirmados |
| En revisión | Marcado por el personal (controversia), o cubierto o vencido solo con una transferencia por conciliar. **Nunca** se declara incumplido mientras haya una transferencia por conciliar |
| Reprogramado / Cancelado | Reemplazado por uno nuevo / cancelado por administración |

## Reglas

- **Cuándo se puede registrar:**
  - Solo con un saldo pendiente confirmado.
  - El importe no puede superar ese saldo.
  - La fecha acordada va desde hoy hasta 180 días.
  - Un plazo de **más de 30 días** cambia las condiciones económicas, así que solo lo registra **administración**.
- **Un solo compromiso vigente** por orden.
- **Reprogramar:** crea un compromiso nuevo enlazado al anterior y exige nueva evidencia del cliente. La fecha nunca se cambia por decisión unilateral.
- **Cancelar o cerrar una revisión:** solo administración, con un motivo obligatorio.
- **ADI:**
  - Puede pedir una fecha estimada; el recordatorio de saldo lo ofrece.
  - Lo que el cliente responda lo registra una persona, con su evidencia.
  - No aprueba acuerdos, descuentos ni condonaciones.

## Integración con ADI (fase 1)

- **«Compromiso de pago»:** confirma el importe y la fecha acordada. Solo está disponible con un compromiso vigente.
- **«Compromiso incumplido»:** es un seguimiento cordial: indica si consta un pago parcial y ofrece hablar con administración.
  - Solo está disponible si el compromiso es incumplido o parcial.
  - No menciona intereses, mora, recargos ni demandas.
- Ambos son de **cobranza**:
  - Horario de lunes a viernes, de 08:00 a 19:00, sin feriados.
  - Como máximo uno al día por cliente.
  - Por WhatsApp sin autorización de avisos, va un mensaje discreto sin importes.
- **Control previo:**
  - Con un compromiso vigente, se bloquea el recordatorio de saldo.
  - Con un compromiso en revisión, se suspende toda la cobranza.

## Pruebas

`local/tests/test_payment_commitments.py` cubre estos casos:

- **Registro:** validaciones (evidencia, importe, fecha, origen), sin saldo y un solo compromiso vigente.
- **Plazo largo:** solo con administración.
- **Estados:** próximo, incumplido, parcial y cumplido con pagos reales; la transferencia por conciliar pasa a revisión.
- **Cambios:** reprogramar (con evidencia y enlace), revisión, cancelación solo por administración y el historial de eventos.
- **Mensajes de ADI:** recordatorio de saldo bloqueado y mensaje discreto por WhatsApp.
- **Sin efectos y sin migración:** no cambia pagos, mensajes ni la orden, y sin la migración el módulo queda inactivo.
