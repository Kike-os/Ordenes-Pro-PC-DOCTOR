
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

## Indicadores de estado de las citas (1.5.150)

Todos los estados se pintan con una misma píldora de 26 px con icono y texto (`agendaPill` / `agendaBadge` en `app.js`): Nueva, Confirmada, Por confirmar (antes «Solicitada»), Reagendada (antes «Reprogramada»), En atención, No asistió, Cancelada y Completada; los mantenimientos preventivos llevan además la píldora «Preventivo». Es un cambio de presentación: los códigos de estado, las reglas y las citas existentes no se modifican.

## Autorización digital de citas (19/10/2026)

- Para confirmar una cita, el cliente marca la aceptación expresa de las **condiciones del servicio vigentes** (las publicadas por la administración en Configuración) y escribe los **últimos 4 dígitos de su cédula**. El botón «Confirmar y autorizar cita» se habilita solo cuando ambas cosas son válidas. El servidor vuelve a comprobarlo todo.
- Los 4 dígitos deben ser exactamente numéricos y coincidir con la identificación escrita (cédula; en un RUC de persona natural, la cédula que contiene; en un pasaporte, sus últimos 4 dígitos). **No son una firma electrónica ni una prueba de identidad**: solo comprueban la coherencia de los datos.
- Cada aceptación se guarda en `appointment_authorizations` (migración 059): identificador único `AUT-<UUID>`, cita, cliente, fecha y hora con zona `America/Guayaquil`, versión y huella SHA-256 de las condiciones, consentimiento expreso, los 4 dígitos, el canal (en línea o registrada por el personal, con quién la registró) y una copia de los datos de la cita en ese momento. Es inmutable: no se modifica ni se borra, y se conserva aunque la cita se reprograme o edite.
- La base de datos impide que una cita pase a «Confirmada» sin autorización. Las citas automáticas (mantenimiento) y las anteriores a este cambio no reciben autorizaciones retroactivas: para confirmarlas, el personal registra la aceptación del cliente en el diálogo «Autorización del cliente». Una cita antigua que se reactiva vuelve como solicitud.
- Si no hay condiciones vigentes publicadas, no se autoriza ninguna cita (no se fabrica la aceptación).
- Acceso: el detalle de la autorización se ve en la agenda; los 4 dígitos y la copia de la cita, solo la administración.
- Mensaje al cliente: «Cita confirmada correctamente. Su aceptación ha sido registrada con fecha, hora e identificador de autorización.»

## Catálogo de servicios y citas con varios servicios (19/10/2026)

- Servicios agrupados por categoría (Diagnóstico y reparación, Mantenimiento, BIOS, Software, sistemas y licencias, Redes y asistencia remota, Otros servicios), con buscador que no distingue tildes y busca también por palabras clave.
- Servicios nuevos (migración 060, solo si no existía otro con el mismo código o nombre): Compra de licencia de software, Desbloqueo de BIOS, Recuperación de contraseña de BIOS, Actualización de BIOS, Reparación de BIOS corrupta, Instalación de Windows y otros sistemas operativos, Instalación y configuración de antivirus, Eliminación de virus y malware, Recuperación y respaldo de datos, Reparación de bisagras, Cambio de pantallas, Mantenimiento de consolas PlayStation y Configuración de redes y Wi-Fi. Las duraciones iniciales son estimaciones editables en Configuración de la agenda.
- **No se duplicaron** (ya existían con otro nombre; se encuentran por el buscador): «Programación y recuperación de BIOS», «Asistencia técnica remota» = «Servicio de Administración Remota», «Reparación de impresoras» = «Servicio para impresoras» y «Diagnóstico y reparación de placas electrónicas» = «Reparación electrónica».
- Se pueden elegir hasta 5 servicios por cita, sin repetir; la duración de la cita es la suma (máximo 8 horas). El retiro de equipos se agenda solo. La disponibilidad, la prevención de citas simultáneas, los horarios, los feriados y los avisos funcionan igual, con la duración total.
- «Compra de licencia de software» pide el tipo de licencia (Windows 10 y Windows 11; Microsoft Office; Microsoft 365; Antivirus Kaspersky, ESET NOD32, McAfee, Norton y otros; Otras licencias de software) y observaciones opcionales.
- La cita conserva su servicio principal (el primero) y guarda el detalle en `appointment_service_items`; la agenda y los correos muestran el resumen («Diagnóstico técnico + Reparación de bisagras»). Las citas anteriores no cambian.

## Inasistencias y reagendamiento (migración 066, 1.5.174)

**Configuración** (Configuración → Agenda → «Inasistencias y reagendamientos», solo administración): control automático (desactivado por defecto), tolerancia en minutos (5-240, por defecto 15), envío del correo, vigencia del enlace (1-30 días, por defecto 7) y límite de reagendamientos por cita (1-5, por defecto 2).

**Detección automática.** Una cita confirmada o reprogramada, sin llegada registrada ni orden creada, pasa a «No asistió» cuando vence la tolerancia. Solo se revisan citas posteriores al momento en que se activó el control y de las últimas 72 horas: nunca se reescribe el historial anterior. La revisión corre en la tarea diaria (`/api/cron/reminders`) y, como máximo cada 5 minutos, mientras hay usuarios con sesión. Cada inasistencia queda en el historial de la cita (`no_show_auto`). También se puede marcar a mano.

**Enlace privado.** Se genera un enlace `/reagendar/<token>`; en la base solo se guarda la huella SHA-256. Un enlace nuevo anula los anteriores sin usar; se revoca al reprogramar o reactivar la cita desde la Agenda. El correo («PC-DOCTOR S.A. | Reagenda tu cita técnica») sale por Mail Pro con el botón «Reagendar mi cita»; si falla se reintenta hasta 3 veces. Desde la ficha de la cita se puede «Enviar enlace de reagendamiento» o «Enviar rectificación» (cuando la inasistencia fue un error).

**Página pública.** Muestra la cita, el servicio, el equipo y la fecha anterior, y solo los días y horarios realmente libres (se vuelven a comprobar al confirmar). La cita conserva su código, datos e historial; queda marcada como «Reagendada» (morado) y suma un reagendamiento. Al alcanzar el límite, el cliente debe comunicarse por WhatsApp. Un enlace vencido puede pedir uno nuevo si la cita sigue en «No asistió».

«No asistió» es distinto de «Cancelada» y se revierte con «Reactivar cita».
