# Recargo por pago con tarjeta de crédito (1.5.234)

**Decisión de administración del 03/11/2026:** al cobrar con tarjeta de crédito, corriente o diferida, el cliente paga el recargo
comercial configurado (hoy 9 %). Sustituye a la decisión del 27/10/2026, en la que lo asumía la empresa. Se advirtió que en Ecuador
cobrar recargos por pagar con tarjeta puede estar restringido y que conviene confirmarlo con el contador.

## Reglas

- El porcentaje, el valor fijo, quién lo paga, la vigencia y los métodos salen de **Facturación › Tarjetas y DATAFAST › Recargo comercial**.
  Nunca hay un 9 % escrito en el código. Si el recargo lo asume la empresa o no está vigente, no se suma nada.
- Va como **partida aparte, «Recargo por pago con tarjeta de crédito (9 %)», con IVA 15 %**, visible en la venta, la factura y el
  comprobante: lo facturado y lo cobrado coinciden.
- Se calcula sobre **lo que se paga con la tarjeta de crédito** (IVA incluido): el cliente paga importe × 1,09. En un pago mixto, solo la
  parte con tarjeta de crédito. La tarjeta de **débito no lleva recargo**.
- Nunca se duplica: un reintento o un doble clic reconoce el mismo pago, y al editar una cotización el recargo se recalcula.
- El interés del diferido sigue siendo del banco emisor (informativo) y se calcula sobre el importe sin recargo + el recargo, una sola vez.

## Dónde se aplica

| Cobro | Cómo |
| --- | --- |
| Cotización o proforma con forma de pago tarjeta de crédito | El recargo no es una partida que el cliente apruebe: mientras tanto se muestra como información («precio + recargo + intereses») y **al facturar** el servidor añade la partida sobre lo aprobado que se paga con la tarjeta (lo aprobado menos los anticipos pagados por otros medios). |
| Venta directa (Ventas › Nueva venta) | Al confirmar, por cada línea de cobro con tarjeta de crédito: se añade la partida y se suma a esa línea. La ventana avisa el recargo y el total antes de confirmar. |
| Cobros de órdenes («Registrar pago») | El pago con tarjeta de crédito guarda su recargo (`order_card_surcharges`, migración 089): suma al cargo del equipo, el saldo baja como un pago normal y la factura de la orden lo lleva como partida. Anular el pago anula su recargo. |
| Ventas de licencias | El pago con tarjeta pide «crédito» o «débito» (columna `card_kind`). Con crédito: `license_sale_surcharges`, el subtotal y el total de la venta suben en el recargo, y la factura y el comprobante lo llevan como partida. Anular el pago lo revierte. |

Caja cuenta cada cobro con su importe real, recargo incluido; en licencias distingue crédito de débito.

## Pruebas

- `test_card_surcharge.py`: cotización (informativo al guardar; al facturar, el 9 % de lo pendiente con tarjeta tras un anticipo por transferencia, sin duplicar; nada en efectivo ni si lo asume la empresa),
  venta directa mixta (9 % solo sobre la tarjeta, factura = cobros, partida con IVA, reintento sin duplicar, débito sin recargo), órdenes
  (pago de 100,00 → 109,00, saldo, reintento, mixto, débito, factura sin bloqueo, anulación) y licencias (crédito, débito, factura y
  anulación).
- Navegador con datos ficticios: aviso y total con recargo en la venta directa (y sin aviso con débito), factura de $105,40 con la tarjeta en
  $65,40, y «Registrar pago» de una orden con el aviso, la confirmación y el pago de $109,00.
