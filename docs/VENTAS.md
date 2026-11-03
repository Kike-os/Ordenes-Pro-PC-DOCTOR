# Centro de Ventas

Desde la 1.5.221 el menú principal tiene la opción **Ventas**, visible solo para administración. El módulo no crea otro sistema de cobro ni de facturación: reúne y abre lo que ya existía.

| Sección | Qué usa |
| --- | --- |
| Panel de ventas | Indicadores calculados sobre las ventas registradas. |
| Nueva venta | Factura directa, venta de licencias, cotizaciones y la factura de una orden técnica. |
| Cotizaciones y proformas | El panel de proformas de Facturación. |
| Pedidos comerciales | Tablas nuevas (migración 084). |
| Historial de ventas | Proformas convertidas sin orden técnica, ventas de licencias (VLIC) y ventas registradas en el inventario. |
| Ventas de licencias | El panel que antes era la pestaña «Ventas» de Licencias. |
| Cobros | «Pagos y anticipos» de Facturación. |
| Reportes | Ventas por día, producto, cliente, usuario o tipo; exportación CSV. |

## Qué cuenta como venta

- **Venta directa:** una factura directa confirmada («Crear factura»). Es una proforma de origen `directa` convertida en factura.
- **Desde cotización:** una cotización aprobada y convertida en factura, sin orden técnica.
- **Licencias:** una venta VLIC.
- **Registrada en inventario:** una salida con motivo «Venta» registrada en el Centro de Inventario, sin factura ni orden.

**Fuera de las ventas:**
- las órdenes técnicas y sus presupuestos, que siguen en Órdenes y Facturación;
- los borradores sin confirmar;
- las asignaciones de licencias sin cobro.

**Estados:**
- *Pagada*.
- *Saldo pendiente*: pagos confirmados menores que el total.
- *Anulada*: borrador de factura descartado o venta de licencias cancelada.
- *Cobro no registrado*: venta del inventario, que no registra pagos.

Una venta anulada sigue en el historial y no suma en el panel ni en los reportes.

## Panel de ventas

| Indicador | Qué cuenta |
| --- | --- |
| Ventas del día y del mes | Ventas no anuladas. |
| Total facturado (mes) | Facturas emitidas de ventas, no de órdenes. Mientras la emisión real esté desactivada, son del ambiente de pruebas. |
| Ventas pendientes | Ventas directas sin confirmar, ventas con factura en borrador, licencias por entregar y pedidos abiertos. |
| Cobros pendientes | Saldo de las ventas no anuladas. |

El panel muestra además los productos más vendidos del mes y las últimas transacciones.

## Nueva venta

### Productos y servicios

Abre la misma ventana que «Nueva factura directa». Tiene:
- cliente;
- productos del inventario con existencias, catálogo o partidas libres;
- formas de pago: efectivo, transferencia o depósito con cuenta receptora y referencia, tarjeta con las reglas DATAFAST (el recargo lo asume la empresa), crédito, cheque y pago mixto de hasta cinco líneas;
- caja abierta obligatoria si así está configurada.

Al confirmar con «Crear factura»:
1. Si hay productos con número de serie, se eligen las unidades que salen. Por omisión se marcan las más antiguas, y hay que marcar exactamente la cantidad vendida.
2. En **una sola transacción** se aprueba la venta, se registran los pagos, se crea el borrador de factura y **sale el inventario**. La salida queda en el Kardex con el motivo «Venta», la factura como referencia, el cliente, el precio cobrado y las fechas de garantía.
3. Si no alcanzan las existencias, o una unidad ya no está disponible, no se registra nada.
4. Repetir el envío (doble clic o reintento) devuelve la misma factura y no descuenta otra vez.

La misma salida se aplica al convertir una cotización aprobada sin orden técnica. Con orden técnica, el inventario lo descuenta la orden, como antes.

> Corrección de la 1.5.221: hasta la 1.5.220 la factura directa **no descontaba el inventario** aunque la partida viniera del Centro de Inventario.

### Licencias digitales

Abre la venta de licencias:
- carrito con licencias disponibles y vigentes, que quedan reservadas;
- pago ahora o después;
- entrega con enlace privado.

Una licencia vendida o reservada no se ofrece a otra venta. La clave solo la ven quienes tienen permiso y nunca aparece en comprobantes ni correos.

### Desde una cotización

Lleva a «Cotizaciones y proformas».

### Desde una orden técnica

Usa el borrador de factura de la orden (`invoicing.draft('orden', …)`). Si ya existe, abre el mismo, de modo que los conceptos no se duplican.

## Anulaciones y devoluciones

Nada se borra.
- **Borrador de factura:** se descarta en Facturación, con motivo. Los productos vuelven al inventario con un movimiento «Devolución del cliente» con las mismas unidades y el mismo costo, una sola vez, y la venta queda *Anulada*.
- **Factura emitida:** se anula con nota de crédito, como hasta ahora.
- **Venta de licencias:** se cancela desde su detalle, como hasta ahora.

## Pedidos comerciales (PED-000001)

Registran lo que un cliente pide y aún no está en existencias:
- cliente, tipo (producto, licencia, servicio u otro), descripción y cantidad;
- valor aproximado, solo informativo;
- fecha estimada y observaciones.

| Estado | Puede pasar a |
| --- | --- |
| Solicitado por el cliente | Pedido al proveedor, Recibido, Entregado o Cancelado |
| Pedido al proveedor | Recibido o Cancelado |
| Recibido · por entregar | Entregado o Cancelado |

**Reglas:**
- «Pedido al proveedor» guarda el proveedor y la fecha estimada.
- «Entregado» puede vincular la venta con que se entregó: una proforma o factura directa (PF-…) o una venta de licencias (VLIC-…). La venta y el cobro se hacen en «Nueva venta».
- Cancelar exige un motivo.
- Un pedido no se elimina y su historial no se modifica (lo impiden triggers de la base).
- Repetir el mismo envío no crea otro pedido.

## Licencias Pro

- **«Asignar o entregar licencia»** reemplaza a «Vender o entregar». Entrega una licencia disponible y vigente a un cliente, o la indicada desde el inventario de licencias, **sin venta, precio ni cobro**. Opcionalmente se vincula a una orden y se indica la fecha real de activación. Queda en «Entregas» y en el historial con el responsable.
- La pestaña «Ventas» pasó al Centro de Ventas, en la sección «Ventas de licencias». El botón «Ventas de licencias» de Licencias lleva allí.
- Se conservan disponibilidad, reservas, activaciones, vencimientos, renovaciones, clientes asignados e historial de entregas. Las ventas anteriores siguen consultables con los mismos datos.

## Seguridad

- Todas las rutas `/api/sales/*` exigen administración; con otro rol responden 403.
- Los POST usan sesión, CSRF y una transacción exclusiva (`BEGIN IMMEDIATE`).
- Las consultas son parametrizadas.
- La facturación electrónica sigue en ambiente de **pruebas**. El Centro de Ventas no emite comprobantes reales.

## Base de datos

La migración `084_sales_requests.sql` solo agrega tablas:
- `sales_requests`, sin borrado;
- `sales_request_events`, sin cambios ni borrado.

No modifica tablas existentes.

## Pruebas

- `local/tests/test_sales_center.py`:
  - venta con series elegidas;
  - venta sin existencias que no factura;
  - líneas repetidas sumadas;
  - descarte que devuelve el inventario;
  - panel, historial, reportes y pedidos;
  - permisos;
  - asignación de licencias sin cobro.
- Revisión en el navegador con datos ficticios a 1366, 820, 390 y 320 px: teclado, Escape, movimiento reducido y desbordamiento.

## Imprimir comprobante (comprobante de venta no tributario)

Botón **«Imprimir comprobante»** en el historial de ventas (icono de impresora y opción del menú de acciones), en el detalle de la venta
directa o desde cotización, en el detalle de la venta de licencias (sustituye al comprobante HTML anterior) y en el aviso de venta
registrada. Sirve para los cuatro tipos del historial: directa, desde cotización, licencias e inventario. Módulo `local/sale_receipt.py`.

- **Ventana** como «Imprimir ticket» de las órdenes: vista previa del PDF real, **formato** (ticket de 80 mm o A4), **copia** (cliente,
  establecimiento o ambas) y botones **Imprimir**, **Descargar PDF** y **Cerrar**. En teléfonos sin visor de PDF se omite la vista previa y los
  botones siguen funcionando. Imprimir y descargar usan exactamente el PDF mostrado.
- **Contenido**: logo original, empresa con RUC y dirección de Facturación › Datos fiscales (si falta, lo dice), número de la venta, fecha y
  hora, quién atendió, cliente, partidas con cantidad, precio unitario, descuento y total, subtotales por tarifa de IVA, IVA y total (con IVA
  incluido, con las mismas reglas que la factura), pagos con método, cuenta enmascarada (•••• 2424), referencia y estado, saldo, estado del
  pago, QR de consulta interna (ruta que exige sesión de administración) y agradecimiento. Las claves de licencias nunca se imprimen.
- **Documento no tributario**, identificado en el encabezado: «DOCUMENTO NO TRIBUTARIO · NO VÁLIDO COMO FACTURA». Si la venta tiene
  factura emitida, el comprobante la menciona y aclara que no la sustituye. Con la factura **autorizada**, la ventana ofrece además el
  **RIDE** (la representación impresa de Facturación, con su clave de acceso y autorización); en el ambiente de pruebas lo indica.
- **Ticket**: 72 mm útiles de la Epson TM-m30II (204,09 pt), margen de 1 mm, logo monocromo, altura según el contenido (una página por copia,
  sin hojas en blanco) y QR alineado a 203 ppp. «Ambas copias» son dos páginas iguales.
- **Reimprimir** solo lee: no crea ventas, cobros, movimientos de caja ni de inventario, facturas ni eventos (lo comprueban las pruebas).
- Ruta: `GET /api/sales/receipt/<directa|cotizacion|licencia|inventario>/<id>` (resumen) y `…/<id>.pdf?formato=termico|a4&copia=cliente|establecimiento|ambas`.
  Solo administración, como el resto de Ventas.

**Pruebas:** `test_sale_receipt.py` (venta directa con varios productos y servicios, descuento, IVA 15 % y 0 %, pago mixto, venta pendiente,
factura autorizada; licencias sin claves y con descuento por partida; inventario con serie; reimpresión sin cambios; permisos) y una prueba de
navegador con datos ficticios (historial, detalle, menú, formatos, copias, RIDE, imprimir, descargar, cerrar y Escape a 1366, 390 y 320 px).
Los tickets se procesaron con el controlador real de la Epson (`print-thermal.py --render-only`, sin imprimir) y los QR se leyeron a 203 ppp.

**Hallazgo pendiente (Facturación, no modificado):** `invoicing._license_source` trata el descuento de una venta de licencias como un
descuento general y bloquea su factura («todavía no se reparte entre las partidas»), aunque ese descuento es la suma de los descuentos por
partida, ya restados en cada línea.
