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

- **Presupuesto de la orden:** botón «Cobertura PC-DOCTOR» en cada partida de **repuesto** (categoría «Repuestos y componentes»), también en presupuestos nuevos o partidas sin guardar (1.5.297). Si la partida aún no está guardada, el botón ofrece «Guardar borrador y continuar» (no se envía al cliente) y luego abre el panel. Si el estado no se puede consultar, el botón sigue visible y lo indica. Abre el panel de la cobertura con:
  - estados;
  - cifras internas;
  - proveedor;
  - acciones;
  - pagos;
  - historial.

  Desde la 1.5.299:
  - **Ubicación del botón.** Está en la franja de acciones de la partida, en su propia línea bajo «Duplicar» y «Eliminar», con los mismos estados en todos los anchos.
  - **Confirmación sin guardar.** Se titula «Guardar presupuesto para gestionar cobertura». Sus botones son «Cancelar» y «Guardar borrador y continuar». Guardar no envía correos, WhatsApp ni avisos.
  - **Varios clics.** Un doble clic no abre dos ventanas ni guarda dos veces.
  - **Fallo al guardar.** Muestra un aviso y deja los datos en pantalla.
  - **Mientras consulta.** Muestra «Consultando…».
  - **Datos del panel:**
    - cantidad;
    - quién solicitó (y cuándo);
    - quién autorizó;
    - fecha de compra;
    - recepción;
    - movimiento de inventario (`MOV-n`);
    - motivo de la cobertura (interno);
    - forma de pago y movimiento de caja (`CJM-n`) de cada pago.
  - **Vista del técnico.** Ve el mismo seguimiento sin cifras: cantidad, solicitó, autorizó, compra y recepción.

  Desde la 1.5.300 la cobertura se abre en un panel lateral con tres pestañas, sin otra página:
  - **Gestión.** Cifras, solicitud, autorización y acciones.
  - **Seguimiento.** Las cuatro etapas independientes y los pagos.
  - **Historial.** Solo lectura, con el estado anterior y el nuevo.

  En pantallas de 1400 px o más, el presupuesto queda a la izquierda. Detalle en [PRESUPUESTOS.md](PRESUPUESTOS.md).
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

## Cobertura Empresarial universal: cualquier partida y dos modalidades (1.5.301)

«Cobertura PC-DOCTOR» ya no es solo para repuestos. Aparece en cualquier partida con importe:
- servicios, diagnósticos y BIOS/UEFI;
- mano de obra y mantenimientos;
- productos y repuestos;
- licencias;
- líneas libres.

No hace falta reclasificar un servicio como repuesto. El panel se llama **Cobertura Empresarial PC-DOCTOR**. Cada partida puede tener una cobertura viva de cada modalidad; por ejemplo, un repuesto en garantía puede tener exonerado el precio y, además, asumido su costo.

| | Costo interno | Comercial al cliente |
|---|---|---|
| Qué asume PC-DOCTOR | El costo del proveedor o el costo operativo del servicio | Parte o todo el **precio** de la partida |
| Lo que paga el cliente | El precio de su presupuesto, sin cambios | El precio menos el «Beneficio PC-DOCTOR» |
| Documentos del cliente | Sin datos internos | Muestran el precio, el beneficio (con su motivo) y el importe final, en la página, el PDF y el resumen |
| Factura | Sin cambios | El beneficio viaja como **descuento de la línea**; el IVA se calcula sobre el importe final |
| Dinero | Autorizar no mueve caja. Cada pago real es un egreso de caja | No crea cobros, pagos, ingresos ni egresos |
| Cuándo | En cualquier presupuesto | Solo con el presupuesto en borrador o en revisión. En uno enviado o aprobado no se aplica, modifica ni retira: se crea una versión nueva |

- **Bienes y servicios:**
  - **Bienes** (repuestos, productos, licencias, seguridad): tienen compra, recepción, entrada de inventario y pago al proveedor.
  - **Servicios:** su seguimiento muestra la ejecución de la partida y los «costos asociados», que son opcionales. El pago se registra solo si existe un costo real, como un prestador externo, y necesita a quién se le paga.
- **Motivos:** el motivo es obligatorio. El catálogo es configurable en Caja › Coberturas › «Motivos de cobertura»: se pueden agregar, renombrar, marcar si exigen descripción y desactivar, pero no borrar. Motivos de fábrica:
  - Garantía de reparación.
  - Compensación por inconvenientes.
  - Error técnico interno.
  - Atención comercial.
  - Cortesía empresarial.
  - Retrabajo sin cargo.
  - Reposición de producto.
  - Otro motivo justificado.

  «Compensación», «Error técnico interno» y «Otro» exigen una descripción interna.
- **Cálculo único:** `quotes.line_net` resta del precio el descuento autorizado y luego el beneficio. Lo usan los totales, la página y el PDF del cliente, la aprobación, el saldo de la orden y la factura. Una cobertura comercial solo resta mientras está autorizada y enlazada a su partida. Si el precio cambia en el borrador, el beneficio se recalcula con el mismo porcentaje.
- **Permisos (comprobados en el servidor):**
  - **Técnico:** solicita cualquiera de las dos modalidades, pero no autoriza (403). Nunca ve costos, proveedor, pagos ni margen. Sí ve el beneficio comercial, porque figura en el documento del cliente.
  - **Administración:** autoriza, modifica, retira y configura los motivos.
- **Historial y auditoría:** cada solicitud, autorización, cambio y retiro queda en el historial de la cobertura. El beneficio comercial también queda en el historial del presupuesto.
- **Compatibilidad:** la migración `111_coverage_universal.sql` solo agrega columnas con valor por defecto, un índice y la tabla de motivos. Las coberturas existentes quedan como «costo interno», con sus pagos, inventario e historial intactos.
- **Tratamiento tributario:** el beneficio se factura como descuento de la línea, la forma estándar de un descuento en la factura electrónica. Si en algún caso corresponde otro tratamiento (por ejemplo, una nota de crédito sobre una factura ya emitida, o la normativa sobre transferencias gratuitas), debe confirmarlo el contador. El sistema no emite notas de crédito automáticas por una cobertura.
