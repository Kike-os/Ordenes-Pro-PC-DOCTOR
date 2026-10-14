
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

## Tipo y número de identificación (migración 051)

En «Tus datos» la identificación se pide con dos controles: **Tipo** (botones segmentados Cédula | RUC) y **Número**, con contador (`8/10`, `11/13`).

- Solo se aceptan dígitos; las letras, espacios y símbolos no entran. La cédula admite 10 dígitos y el RUC 13. Los ceros iniciales se conservan.
- Se validan el dígito verificador y las reglas de cédula y RUC, no solo la longitud; el servidor repite la validación.
- Mensajes: «Ingresa tu número de identificación para continuar», «La cédula debe contener exactamente 10 dígitos», «El RUC debe contener exactamente 13 dígitos» y «Verifica el número de identificación ingresado».
- Al cambiar de tipo se actualizan el título, la ayuda, el límite y el contador. El número escrito no se borra ni se recorta: se conserva para editarlo y se valida con las reglas del tipo nuevo. Nunca se guarda un tipo que no corresponda al número.
- La cita guarda tipo y número (`appointments.document_type`), y un cliente nuevo queda registrado con ambos. La respuesta pública de la reserva no devuelve la identificación.

El diálogo «Nueva cita» del personal también permite indicar tipo y número (opcional) cuando el cliente no está en la base; con un cliente elegido de la base no se piden. Recepción y la ficha de cliente ya tenían su selector de tipo de identificación.

## Componente único de identificación (cédula, RUC, pasaporte)

`local/static/form-validation.js` contiene el componente que usan la reserva pública, la ficha de cliente (nueva y edición), la recepción y la cita del personal:

- `segmentedSelect(select)`: muestra un `<select>` como selector segmentado accesible (grupo de radio, flechas, Inicio/Fin). El `<select>` sigue siendo el dato del formulario.
- `identificationControl({select,input,count})`: límite por tipo (10, 13 o 30), teclado numérico, solo dígitos al escribir, pegado que conserva únicamente los dígitos sin superar el límite, ceros iniciales intactos y contador junto a la etiqueta. Cambiar de tipo no borra ni recorta lo escrito. El selector toma la altura y la separación del campo numérico.
- `documentCheck(valor,tipo)`: mismas reglas que `reception.document_check` del servidor; una prueba (`test_identification.py`) ejecuta ambas con los mismos casos y exige resultados idénticos.

Reglas: cédula = provincia (01–24 o 30), tercer dígito 0–5 y dígito verificador (módulo 10). RUC de persona natural = su cédula válida más el establecimiento (no `000`). RUC de entidad pública (tercer dígito 6) o de sociedad (9) = provincia y establecimiento; su dígito verificador (módulo 11) se comprueba, pero si no coincide **solo se avisa**, no se rechaza, para no dejar fuera RUC reales que no lo cumplen. Tercer dígito 7 u 8 no corresponde a ningún tipo. Los errores se muestran al completar el número o al salir del campo, nunca antes.

## Pasaporte en la reserva pública

El selector de identificación de «Agendamiento de Citas Técnicas» admite Cédula, RUC o Pasaporte, para personas sin cédula ecuatoriana. El pasaporte no tiene dígito verificador: se comprueba su forma (de 5 a 20 letras y números, con al menos una cifra, sin espacios) y se guarda en mayúsculas. El cliente se crea o se vincula por ese número igual que con cédula o RUC. La ficha de cliente del panel conserva su regla anterior (3 a 30 caracteres).

## Reactivar una cita cerrada por error

Administración puede devolver a la agenda una cita «No asistió», cancelada o completada sin orden (detalle de la cita o menú de la fila → «Reactivar cita»). Recupera el estado que tenía antes de cerrarse, conserva fecha, hora, cliente, equipo, servicio, código e historial, y añade al historial «Cita reactivada por corrección administrativa de cierre accidental». Antes comprueba que el horario siga libre para el mismo técnico; si no, pide reprogramar. No crea otra cita ni envía avisos al cliente.

El 13/10/2026 se reactivó así, a petición de administración y con respaldo previo, la cita `CIT-20261013-4522DF`.
