
## Reserva desde el chat de ADI

Cuando el cliente pide una cita en el chat, ADI añade los próximos horarios realmente libres (el mismo cálculo de la página de reservas) como botones «Reservar DD/MM · hora». Si pide una fecha y hora concretas, ADI comprueba la agenda y ofrece ese horario o las alternativas más próximas.

El botón abre `/citas?fecha=…&hora=…&servicio=…` con el servicio, la fecha y la hora ya elegidos y un aviso que lo explica. ADI no crea la cita: la persona escribe sus datos y acepta las condiciones en los cuatro pasos de siempre, y el servidor vuelve a comprobar la disponibilidad al confirmar. Si el horario se ocupó o ya no admite reserva en línea, la página lo avisa y muestra los que siguen libres.

Los horarios se añaden desde la agenda, no desde el texto que redacta el modelo, de modo que nunca se ofrece una hora inventada.
