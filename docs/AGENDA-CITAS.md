
## Reserva desde el chat de ADI

Cuando el cliente pide una cita en el chat, ADI añade los próximos horarios realmente libres (el mismo cálculo de la página de reservas) como botones «Reservar DD/MM · hora». Si pide una fecha y hora concretas, ADI comprueba la agenda y ofrece ese horario o las alternativas más próximas.

El botón abre `/citas?fecha=…&hora=…&servicio=…` con el servicio, la fecha y la hora ya elegidos y un aviso que lo explica. ADI no crea la cita: la persona escribe sus datos y acepta las condiciones en los cuatro pasos de siempre, y el servidor vuelve a comprobar la disponibilidad al confirmar. Si el horario se ocupó o ya no admite reserva en línea, la página lo avisa y muestra los que siguen libres.

Los horarios se añaden desde la agenda, no desde el texto que redacta el modelo, de modo que nunca se ofrece una hora inventada.

## Retiro de Equipos (migración 050)

Nuevo servicio **«Retiro de Equipos · 15 min»** en la reserva pública y en la agenda del personal. La duración se cambia en Citas → Configuración de la agenda, como la de cualquier servicio.

- Al elegirlo aparece el campo opcional «Número de orden de servicio» y la descripción deja de ser obligatoria.
- Si se indica la orden, el servidor comprueba que exista y que sea del mismo cliente (misma cédula o RUC; si la ficha no tiene identificación, mismo teléfono). Una orden inexistente y una orden de otra persona reciben exactamente la misma respuesta, sin revelar nada.
- El retiro solo se agenda si la orden está «Listo para entregar» o «En espera de entrega». Si aún no lo está se muestra «Tu equipo todavía no está listo para el retiro…» y no se confirma; si ya figura entregada, también se rechaza.
- La cita queda vinculada al cliente y a la orden (`appointments.pickup_order_id`); la agenda y el detalle de la cita muestran el código de la orden.
- **Agendar el retiro no entrega el equipo.** La orden no cambia de estado: la entrega se registra aparte, con su comprobación de saldo.

## Datos obligatorios en la reserva pública

«Tus datos» exige nombre y apellidos, cédula o RUC y teléfono; el correo es opcional. Los obligatorios llevan asterisco y la nota «Los campos marcados con * son obligatorios».

- Nada se marca en rojo al abrir. Cada campo se valida al salir de él y al avanzar; el error aparece debajo y desaparece al corregirlo.
- Mensajes: «Ingresa tu nombre y apellidos», «Ingresa una cédula o RUC válido» (se comprueba el dígito verificador, no solo la longitud), «Ingresa un número de contacto válido» (formatos de Ecuador o internacional con +) y «Ingresa un correo electrónico válido» solo si se escribió uno incorrecto.
- El aviso general es compacto y específico: «Hay datos pendientes por completar. Revisa los campos marcados en rojo.» o «Algunos datos necesitan corrección. Verifica la información señalada.»; sin conexión, «No pudimos completar la operación. Comprueba tu conexión e inténtalo nuevamente.»
- El servidor repite todas las validaciones. Sin correo, la cita se agenda y no se intenta ninguna confirmación por ese medio.

## Clientes registrados desde citas

Al guardar una cita, el cliente se busca por cédula o RUC; si no hay coincidencia, por teléfono (comparando el número, no su formato) o correo.

- **Cliente nuevo:** se registra en Clientes con origen «Cita agendada» y la cita queda vinculada. El listado y la ficha muestran la etiqueta «Origen: Cita agendada».
- **Cliente existente:** solo se vincula la cita; no se modifica ningún dato de su ficha.
- **Coincidencia dudosa** (mismo teléfono o correo que un cliente con otra identificación): no se enlaza ni se fusiona nada. Se crea un cliente nuevo con una nota de «posible duplicado» y el aviso queda en el historial de la cita, para que una persona lo revise.
- El personal ve «Cliente registrado correctamente» o «Cita vinculada correctamente» después de que el servidor guarda. La reserva pública no dice si el cliente ya existía.
- Una solicitud repetida no crea otra cita ni otro cliente. La ficha del cliente lista sus citas.
