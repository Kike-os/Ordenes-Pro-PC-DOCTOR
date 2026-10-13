# Varios equipos por orden, identidad del equipo y pagos (1.5.122)

## Modelo

- Cada equipo recibido es un **ingreso propio** (una fila de `orders`) con su fecha y hora de recepción, diagnóstico, fotografías, técnico, presupuesto, estado, pagos, entrega y mantenimiento. Nada de eso se comparte entre equipos.
- Los ingresos de una misma orden se unen a la **orden principal** (`orders.group_id`) y se numeran con `orders.unit_no`: `PCD-20261012-0003-E01`, `-E02`, `-E03`… La orden principal conserva su número original y es el equipo E01; los equipos adicionales llevan el sufijo en su propio código y **no consumen números de orden** del día.
- Cada equipo físico tiene una **identidad permanente** (`devices.code`, `EQ-0001`), independiente de la orden. Se asigna al crear el equipo y un disparador impide cambiarla. Los equipos anteriores recibieron su identificador en la migración 040.
- Migración 040: solo añade columnas, índices, disparadores y la tabla `order_payments`. No modifica ni elimina órdenes, clientes, historiales ni fotografías.

## «+ Agregar equipo»

Sustituye a «Duplicar orden» en el detalle de la orden y en el menú de cada fila, y aparece también en el paso «Equipo» de la recepción:

1. **Registrar equipo nuevo:** formulario en blanco.
2. **Agregar equipo similar:** copia solo tipo, marca, modelo y color de otro equipo del cliente; la serie queda vacía. Siempre crea una unidad física distinta con su propio `EQ-…`, aunque todo sea idéntico y no tenga serie. No copia diagnóstico, fotografías, pagos, reparaciones ni historial. Si se escribe una serie que ya pertenece a otro equipo del cliente, se rechaza.
3. **Seleccionar equipo existente:** reingreso de un equipo ya registrado; conserva su identidad e historial y abre un registro de servicio nuevo. Sus características salen del registro (no del formulario). No se admite si el equipo ya tiene un ingreso abierto.

Desde el detalle de una orden, el equipo se agrega a esa orden (mismo cliente). Cada ingreso pasa por la recepción completa: condiciones del servicio y autorizaciones se registran por equipo; no se copia ninguna aceptación.

## Pagos y entregas

- `order_payments`: importe, forma de pago (efectivo, transferencia, tarjeta, depósito, otro), nota, quién y cuándo. Los pagos no se borran (disparador); administración puede **anularlos con motivo** mientras el equipo no esté entregado.
- Saldo de cada equipo = presupuesto registrado − pagos vigentes. Un pago no puede superar el saldo.
- **No se entrega un equipo con saldo pendiente** (cambio rápido de estado y edición completa). Un equipo sin presupuesto no tiene saldo y se entrega como antes.
- Cada equipo se entrega por separado; la orden muestra el resumen consolidado (presupuesto, pagado, saldo y entregados).

## Dónde se ve

- Detalle de la orden: «Equipos de esta orden» (tarjetas con identificador, características, ingreso, estado, técnico, saldo, «Abrir» y «Etiqueta QR») y «Pagos y saldo».
- Ficha del cliente: «Historial de equipos del cliente», cada equipo con todos sus ingresos, diagnóstico y mantenimiento previsto.
- Etiqueta de servicio: incluye el identificador `EQ-…`; el QR de cada ingreso lleva a su propio registro y exige sesión.

## Límites conocidos

- El sistema no lleva un registro de garantías: el historial muestra órdenes, diagnósticos, entregas y mantenimiento previsto, que son los datos reales disponibles.
- Los pagos son un control interno de saldo; no generan factura ni comprobante tributario.

Pruebas: `local/tests/test_equipment.py`.
