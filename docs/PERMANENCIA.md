# Permanencia en taller y control de retiro

Mide cuánto tiempo lleva cada equipo en el taller frente a un plazo administrativo.

## Cálculo

- Cuenta días naturales desde la fecha de ingreso registrada (`received_at`; si falta, la de creación) en la hora de Ecuador.
- El contador se detiene únicamente con el estado «Entregado» y queda fijo en el tiempo total. Si la entrega se revierte, vuelve a contar desde el ingreso original.
- Se calcula siempre en el servidor (`local/stay.py`) con las fechas guardadas; el navegador solo refresca los días cada minuto con esa misma fecha.

## Niveles (por defecto)

| Días | Nivel |
|------|-------|
| 0–59 | Dentro del plazo |
| 60–74 | Recordatorio preventivo |
| 75–89 | Próximo al vencimiento |
| 90 o más | Plazo administrativo vencido |

Administración puede cambiar el plazo (15 a 730 días) y los dos tramos previos desde el detalle de cualquier orden, «Configurar plazo». El cambio queda auditado y solo afecta al cálculo: no modifica órdenes.

## Dónde se ve

- **Órdenes**: columna «Permanencia en taller» con días transcurridos, días restantes o excedidos, barra de avance e icono del nivel.
- **Detalle de la orden**: tarjeta con ingreso, plazo, tiempo transcurrido y, si se entregó, fecha de entrega, tiempo total, días sobre el plazo y quién registró la entrega.
- **Centro de Actividad**: alerta cuando hay equipos sin retirar que superaron el plazo.
- **Informe PDF**: `/api/orders/<id>/stay.pdf` («Informe de permanencia»).

## Límites deliberados

- Superar el plazo solo genera avisos. El sistema no cambia el estado de la orden ni dispone del equipo (reciclaje, remate, desecho o transferencia): cualquier decisión es administrativa y manual.
- No se aplican cargos ni procedimientos de forma retroactiva, ni se atribuye al cliente la aceptación de condiciones en borrador.
- Revertir una entrega registrada es una operación exclusiva de administración y queda en la auditoría (`delivery_reverted`) y en el historial de la orden.
