# Varios presupuestos por orden y Resumen de presupuestos

Desde la 1.5.223 una orden de servicio puede tener **varios presupuestos independientes**, cada uno con su propia aprobación, por ejemplo:

| Presupuesto | Estado |
| --- | --- |
| P1 | Aprobado y pagado |
| P2 | Pendiente de aprobación |
| P3 | Aprobado, pendiente de pago |

## Presupuesto independiente o versión nueva

| Acción | Qué hace |
| --- | --- |
| **Nueva versión** | Corrige un presupuesto, como hasta ahora. Copia sus partidas y reemplaza a la versión anterior del mismo presupuesto. |
| **Nuevo presupuesto independiente** | Empieza vacío y convive con los demás, sin reemplazarlos ni cambiar sus aprobaciones o pagos. |

**Datos de cada presupuesto independiente:**
- Pertenece a su propia *serie* (columna `quotes.series`, migración 085). Las versiones de una serie se reemplazan entre sí; las series distintas conviven.
- La numeración P1, P2, P3… sigue siendo una sola por orden.
- El cliente lo aprueba, rechaza o aprueba parcialmente con el **mismo enlace seguro** de siempre (identidad, decisión por partida y firma). Cada aprobación es independiente.

Los presupuestos existentes quedan todos en la serie 1, así que las órdenes antiguas funcionan exactamente igual.

## Importes, pagos y factura

- **Total a cobrar del equipo:** suma lo aprobado vigente de **cada** presupuesto (su última versión decidida), una sola vez. Lo pendiente, rechazado o en borrador no suma.
- **Aprobar no es pagar:** el estado de pago de cada presupuesto (Pagado, Pago parcial, Pendiente de pago, Sin importe autorizado) se calcula con los **pagos reales** del equipo, repartidos del presupuesto aprobado más antiguo al más reciente. No se crea ni se marca ningún pago.
- **Decisiones:** aprobar o rechazar un presupuesto no cambia el estado de los demás. El estado técnico de la orden sigue la regla de siempre: solo pasa a «Procesando» si la orden esperaba esa aprobación.
- **Factura de la orden:** incluye todo lo aprobado. **Pendiente:** si la factura de la orden ya se emitió y después se aprueba otro presupuesto, lo nuevo requiere otra factura; esa facturación por presupuesto todavía no está implementada.

## Resumen de presupuestos (en la orden)

Es una tabla compacta, adaptada a celulares, con:
- **cada presupuesto técnico**, en su versión vigente;
- **cada proforma vinculada**, incluidas las que ya estaban vinculadas antes de esta versión, sin crearlas de nuevo ni cambiar sus datos.

Cada fila muestra:
- el número de orden y el cliente;
- el número del documento y si es presupuesto técnico, presupuesto independiente o proforma;
- la fecha, el importe (autorizado o cotizado) y el estado de aprobación, con quién decidió y cuándo;
- el estado de pago, lo pagado y el saldo.

Los botones de cada fila son **Ver**, **Imprimir** (PDF), **Reenviar** (solo si espera respuesta del cliente) e **Historial**.

Abajo aparecen los totales de los presupuestos técnicos (saldo del equipo) y, aparte, los de las proformas, que **se cobran aparte**: no se suman al saldo de la orden.

El resumen se actualiza solo mientras algún presupuesto o proforma espera la decisión del cliente. Cuando el cliente decide, se refleja sin recargar la página.

El bloque «Resumen del presupuesto» de cada equipo muestra además sus **proformas vinculadas**, con lo aprobado, los anticipos y el saldo.

## Pruebas

- `local/tests/test_quote_series.py`:
  - P1 pagado, P2 pendiente y P3 aprobado sin pagar;
  - rechazo independiente;
  - abono parcial;
  - versión dentro de su serie;
  - órdenes antiguas con un solo presupuesto;
  - proforma vinculada que aparece en el resumen sin duplicarse ni sumarse al saldo.
- Navegador con datos ficticios a 1366, 820, 390 y 320 px.
