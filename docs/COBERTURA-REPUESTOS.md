# Cobertura Empresarial de Repuestos — PC-DOCTOR (1.5.296)

PC-DOCTOR puede financiar, total o parcialmente, la compra de un repuesto de un presupuesto. El cliente **no** ve esta cobertura: sigue viendo y pagando el precio de su presupuesto.

**Ejemplo:**

| Concepto | Valor |
|---|---|
| Precio al cliente | $150,00 |
| Costo real | $95,00 |
| Cobertura | 100 % |
| Pago de PC-DOCTOR al proveedor | $95,00 (egreso de caja) |
| Margen bruto estimado | $55,00 |

Los cobros al cliente siguen su camino habitual y se registran aparte.

## Tres cosas que no se mezclan

| Concepto | Qué es | ¿Mueve dinero? |
|---|---|---|
| **Cobertura** (solicitada → autorizada / rechazada / cancelada) | La decisión de que PC-DOCTOR asuma el costo | No |
| **Compra** (pendiente → comprado → recibido) | El pedido o factura del proveedor y la recepción física. Si la partida es un artículo de inventario, la recepción crea **una** entrada (motivo «Compra») con el costo real. | No |
| **Pago al proveedor** (pendiente / parcial / pagado) | Cada pago es un egreso real de caja con el tipo «Compra de repuestos — Cobertura PC-DOCTOR». Se crea en la misma transacción y queda vinculado a la orden, el presupuesto, el repuesto, el proveedor y su comprobante. | Sí |

## Reglas

- **Autorizar no registra ninguna salida de caja.**
- **Pagos al proveedor:**
  - Exigen la caja abierta.
  - Nunca superan lo cubierto.
  - Tienen una clave de solicitud: un doble clic o un reintento no los duplica.
- **El tipo de egreso «Compra de repuestos — Cobertura PC-DOCTOR»** no se elige en el formulario manual de Caja. Solo nace desde la cobertura.
- **Nada se elimina:**
  - las coberturas se cancelan con su motivo;
  - los pagos se **revierten**, solo administración y con motivo.

  Si la caja del pago sigue abierta, el reverso anula el egreso. Si ya se cerró, registra un ingreso compensatorio en la caja abierta de quien revierte.
- **El importe cubierto** no puede quedar por debajo de lo ya pagado.
- **Cancelar una cobertura** requiere que no tenga pagos vigentes ni compra registrada.
- **Presupuesto:**
  - El precio, los totales y la aprobación no cambian. Los presupuestos históricos y los importes aprobados quedan intactos.
  - Al guardar un borrador, la cobertura se vuelve a enlazar con su partida (misma descripción). Si la partida se quitó, queda marcada para revisión.
  - Si se anula el presupuesto, se cancelan las coberturas sin compra ni pagos. Las demás quedan para revisión.

## Permisos (comprobados en el servidor)

| Perfil | Puede |
|---|---|
| Administración | Crear, autorizar, editar, rechazar, cancelar, registrar compra y recepción, pagar, revertir, ver el panel financiero, el CSV y la liquidación interna (A4 y 80 mm). |
| Personal con su caja abierta | Registrar pagos al proveedor. |
| Técnico | Solicitar la cobertura y consultar su estado. Nunca recibe costo, proveedor, pagos, notas ni margen. |
| Cliente | Solo ve su presupuesto, su enlace, el PDF, sus recibos y el portal. Nada de la cobertura. |

Todo queda en el historial financiero de la cobertura (solo anexado) y en la auditoría.

## Dónde está

- **Presupuesto de la orden:** botón «Cobertura PC-DOCTOR» en cada partida de **repuesto** ya guardada. Abre el panel de la cobertura con:
  - estados;
  - cifras internas;
  - proveedor;
  - acciones;
  - pagos;
  - historial.
- **Facturación › Caja › Coberturas** (administración). Panel con indicadores:
  - total cubierto;
  - autorizadas sin pagar;
  - pagado a proveedores;
  - obligaciones;
  - recibidos;
  - margen;
  - compras cubiertas del mes;
  - por revisar.

  Tiene filtros por fecha, proveedor, estado, orden y responsable, y exportación CSV.

## Base de datos

Migración `110_part_coverage.sql`. Solo crea tablas nuevas y vacías:

- `part_coverages`;
- `part_coverage_payments`;
- `part_coverage_events`.

También crea sus índices y protecciones contra borrado y modificación. No cambia presupuestos, caja ni inventario existentes.
