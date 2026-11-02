# Proformas y órdenes de servicio

Desde la 1.5.222 una proforma comercial puede vincularse a una orden de servicio. La relación es la misma en los dos sentidos:
- **Orden → Proforma:** en el detalle de la orden, la sección «Proformas comerciales».
- **Proforma → Orden:** en el detalle de la proforma, el dato «Orden de servicio» y el botón «Ver orden».

En el listado de proformas hay además una columna «Orden» y un filtro «Vinculadas a una orden / Sin orden».

## Qué existía antes y qué faltaba

| Antes de la 1.5.222 | Desde la 1.5.222 |
| --- | --- |
| La base ya tenía la columna `proformas.order_id`, pero la interfaz siempre creaba las proformas «desde el cliente», así que ninguna quedaba vinculada. | Al crear una proforma se puede vincular a una orden, o crearla desde la propia orden. |
| No había forma de vincular una proforma ya enviada o aprobada. | «Vincular a orden» en el detalle de la proforma y «Vincular proforma existente» en la orden. |
| La orden no mostraba proformas, y la decisión del cliente no quedaba en la orden. | La orden lista sus proformas, y cada decisión queda en su historial. |
| No había control de conceptos cobrados dos veces entre el presupuesto técnico y una proforma. | Al facturar se pide una confirmación expresa. |

## Vincular al crear

En «Nueva cotización y proforma» aparece el campo **Vincular a orden (opcional)**:
- Busca por número de orden, cliente, cédula o RUC, o teléfono.
- Al elegir una orden se muestran su número, el cliente, la identificación, el equipo, el estado y la fecha. Si el cliente de la proforma todavía está vacío, se completa con el de la orden.

En la orden, **Crear proforma desde la orden** abre el mismo formulario con la orden ya elegida y su cliente.

Al guardar, la relación se registra automáticamente en el historial de la proforma y en el de la orden.

## Vincular proformas ya creadas

Sirve para las proformas enviadas, vistas, aprobadas (total o parcialmente), rechazadas, vencidas o ya facturadas que corresponden a una orden existente. Hay dos caminos:
- en el detalle de la proforma, **Vincular a orden**;
- en la orden, **Vincular proforma existente**, que lista las proformas sin orden.

Vincular **solo registra la relación**:
- no crea otra proforma;
- no cambia la aprobación, la firma, la evidencia ni su huella;
- no cambia los importes aprobados, las partidas, los anticipos ni la factura;
- conserva el historial anterior.

**Reglas:**
- Si la proforma es de otro cliente, se pide confirmación expresa y un motivo, que quedan registrados.
- Una proforma vinculada a otra orden debe desvincularse primero.
- Desvincular pide un motivo y queda en ambos historiales.
- Una proforma creada desde la orden no se desvincula.
- Vincular y desvincular están reservados a administración.

## Decisión del cliente

Cuando una proforma vinculada se aprueba, se rechaza, se aprueba parcialmente o el cliente pide una modificación, la orden recibe un evento «Proforma comercial» en su historial (filtro «Autorizaciones»). El evento incluye:
- el resultado y quién decidió, sea el cliente con su firma o el personal con el detalle de cómo se confirmó;
- la fecha y la hora;
- los productos y servicios autorizados y el total autorizado.

**El estado técnico de la orden no cambia.**

La sección de la orden muestra la decisión, lo autorizado, los anticipos, el saldo, la factura y el enlace al **documento original (PDF)**. La evidencia completa sigue en la proforma.

El personal recibe un aviso en Notificaciones durante 48 horas, que lleva a la orden o a la proforma.

## Cobros: sin duplicados

- El saldo de la orden sale solo de su presupuesto técnico y de sus pagos. El de la proforma sale de lo aprobado y de sus anticipos. **Nunca se suman entre sí.**
- Si una partida de la proforma ya está autorizada en el presupuesto técnico de la orden (mismo producto del catálogo o misma descripción), se avisa en ambos módulos. Al **generar la factura** se pide una confirmación expresa, que queda registrada en el historial de la proforma.

**Inventario:**
- Una proforma creada desde la orden no descuenta inventario al facturarse, porque los repuestos los descuenta la orden, como antes.
- Una proforma vinculada después sí sale como venta, pero sin descontar lo que la orden ya consumió.

**Centro de Ventas:** cuenta como ventas las proformas convertidas que no se crearon desde una orden.

## Datos y compatibilidad

- **Sin migración.** La relación usa la columna `proformas.order_id`. Su historial queda en `proforma_events` y en `order_history`, que no se modifican ni se borran.
- **Ventas, inventario, caja y facturación funcionan igual.** Las facturas ya emitidas no cambian al vincular su proforma.

## Pruebas

- `local/tests/test_proforma_orders.py`:
  - vincular una proforma aprobada parcialmente con firma, sin alterar nada;
  - otro cliente con confirmación;
  - permisos;
  - creación desde la orden;
  - decisión registrada en la orden sin cambiar su estado;
  - avisos al personal;
  - conceptos repetidos al facturar;
  - búsqueda de órdenes.
- Revisión en el navegador con datos ficticios a 1366, 820, 390 y 320 px.
