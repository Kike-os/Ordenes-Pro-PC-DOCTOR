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

## Selector de equipos dentro de la orden (rama `selector-equipos`, pendiente de aprobación)

«Equipos de esta orden» pasa a ser un selector: cada equipo (E01, E02, E03… sin límite) es una tarjeta compacta que se pulsa entera. Al elegirla, un panel dentro de la misma página muestra sus datos: identificador en la orden, `EQ-…`, características, serie, color, técnico, estado, ingreso, entrega, falla reportada y su presupuesto, pagado y saldo propios.

- Seleccionar no navega ni escribe nada en la base; solo cambia lo que se muestra.
- Indicador del equipo activo: borde y franja luminosa; la tarjeta del equipo cuya página está abierta dice «En esta página».
- Acciones del equipo elegido: «Abrir equipo», «Etiqueta QR», «Tarjeta de seguimiento» y, para administración, «Editar este equipo», que abre el formulario de edición en una ventana sobre la misma página y al guardar vuelve a ella con el mismo equipo seleccionado.
- El resumen económico de la orden completa queda aparte, rotulado «Resumen de la orden completa (N equipos)», para no confundirlo con los importes del equipo elegido.
- Teclado: flechas, Inicio y Fin cambian de equipo. En 390 px las tarjetas van en dos columnas y en 320 px en una.

## Progreso y estado por equipo (octubre de 2026)

**Problema.** La barra de progreso y la etiqueta de estado del detalle mostraban siempre el equipo de la página abierta. En una orden con E01 entregado y E02 en proceso, la barra aparecía completa hasta «Entregado» aunque se seleccionara E02, y parecía que toda la orden estaba entregada.

**Corrección.**

- La barra (Recibido, En proceso, Listo para entregar, Entregado) y la etiqueta «Estado de E02» muestran solo el equipo seleccionado en el selector, y cambian al instante al elegir otro, sin recargar. Etapas completadas en verde, la actual en azul y las pendientes en gris. «Entregado» solo se marca cuando ese equipo tiene su entrega registrada.
- Con varios equipos aparece aparte el **estado general de la orden**, calculado en el servidor (`equipment.overall`) con el estado real de cada uno: «Orden completada» (todos entregados), «Entrega parcial» (alguno entregado y otros no), «Atención en curso» (alguno en proceso, o mezcla de recibidos y listos), «Listos para entrega» (todos listos) o «Equipos recibidos». Lleva un resumen del tipo «2 equipos · 1 entregado · 1 en proceso». Nunca dice completada mientras quede un equipo pendiente.
- Cada equipo sigue siendo un ingreso propio: entregar E01 no cambia E02, y la entrega comprueba el saldo de ese equipo.

**Tarjetas de «Equipos de esta orden».** El encabezado resume la orden en fichas (orden, equipos registrados y cuántos hay en cada etapa). Cada tarjeta tiene arriba el icono del tipo de equipo, el código (E01, E02…) y el estado en píldora; debajo, el nombre con protagonismo, el tipo, el identificador y la serie más discretos, y la última actualización. La seleccionada se distingue por borde, brillo, fondo y la etiqueta «Equipo seleccionado», no solo por una línea.
