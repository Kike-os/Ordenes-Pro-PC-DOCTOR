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

## Avisos por correo al cliente

- **Apagados por defecto.** Los activa administración desde «Configurar plazo», donde antes se ve cuántas órdenes recibirían un aviso y cuáles.
- Un aviso por orden y etapa: a los 60, 75, 85 y 90 días con el plazo por defecto (los dos tramos, cinco días antes del plazo y el día del plazo). Nunca se repite una etapa ni se envía una anterior a otra ya enviada.
- Se suspenden en cuanto la orden queda «Entregado». Solo se envían a clientes con un correo válido.
- El texto es informativo: recuerda desde cuándo está el equipo e invita a coordinar el retiro. No anuncia cargos, sanciones ni decisiones sobre el equipo.
- Cada envío queda en la tabla `stay_reminders` (orden, etapa, destinatario, resultado, identificador del mensaje y fecha), en el historial de la orden y en la tarjeta de permanencia del detalle.
- Envío: al cargar el inicio, como mucho cada diez minutos, entre las 08:00 y las 19:00, en tandas de tres (`stay_reminders_tick`), o con «Enviar avisos pendientes ahora».
