# Feriados y atención

## Qué hace

- **Feriados nacionales de Ecuador calculados** (`local/holidays.py`): Año Nuevo, Carnaval (lunes y martes), Viernes Santo, Día del Trabajo, Batalla de Pichincha, Primer Grito de Independencia, Independencia de Guayaquil, Día de Difuntos, Independencia de Cuenca y Navidad, con las reglas de traslado de la ley (sábado al viernes, domingo al lunes, martes al lunes, miércoles y jueves al viernes; Año Nuevo, Navidad y Carnaval no se mueven entre semana; el 2 y 3 de noviembre se trasladan como pareja). El resultado de 2026 coincide con el calendario publicado para ese año.
- **Ajustes de administración** (Citas → Configuración de la agenda → «Feriados y atención»): definir cómo se atiende cada feriado, agregar feriados locales por ciudad o cantón, días decretados o fechas propias, y ocultar o restaurar un feriado calculado. Lo que decide administración prevalece sobre lo calculado.
- **Tres modos de atención**: Atención normal (horarios habituales), Horario especial (apertura y cierre propios, en intervalos de 15 minutos) y Cerrado por feriado (sin citas nuevas ese día). Un feriado calculado sobre el que nadie ha decidido se atiende con normalidad y aparece como «sin definir».
- **Nunca se cancela una cita.** Si un día cerrado o un horario especial deja citas vigentes fuera de la atención, se listan como conflictos para que administración las reprograme.
- **Aviso de ADI** en el inicio y en la agenda cuando hoy es feriado, haya o no citas: «ADI informa: Hoy es feriado nacional (…)», con el modo de atención vigente.
- **Agenda**: franja «Próximos feriados» con nombre, fecha y modo, aunque el calendario esté vacío. La página pública de citas nombra el feriado al elegir esa fecha.

Los días no laborables que ya existían conservan su efecto (cerrado). Migración 048: añade columnas a `appointment_holidays`; no toca citas ni horarios.

## Límites

- El cálculo sigue la regla general de la ley. Un decreto puede añadir un día o cambiar un traslado (por ejemplo, un puente adicional): el sistema no lo conoce hasta que administración lo registra. No hay descarga automática de un calendario oficial.
- No incluye una base de feriados cantonales: cada feriado local lo registra administración con su ciudad o cantón.
- En un día con horario especial siguen aplicando los horarios propios de cada técnico.

## Google Calendar

La sincronización con Google Calendar **no está construida**. Requiere un proyecto de Google Cloud con una credencial OAuth 2.0 que solo puede crear la administración; sin ella no es posible ni siquiera probar el inicio de la conexión, y no se entregará como funcional una integración sin pruebas reales contra Google. Pasos previos:

1. En Google Cloud Console, crear un proyecto y habilitar «Google Calendar API».
2. Configurar la pantalla de consentimiento OAuth (tipo interno si la cuenta es de Google Workspace) con el permiso `https://www.googleapis.com/auth/calendar.events`.
3. Crear una credencial «ID de cliente OAuth» de tipo aplicación web con el URI de redirección `https://ordenes-pro.ecuadorpcdoctor.com/api/google/callback`.
4. Cargar en Vercel (nunca en el chat) `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET`.
5. Para las notificaciones en tiempo real (webhooks), verificar el dominio en Google Search Console.

Diseño previsto, compatible con Vercel: tokens cifrados en la base (solo servidor) con renovación automática; un calendario elegido para las citas; cada cita lleva el identificador del evento de Google y cada evento una marca privada de Órdenes Pro, de modo que nunca se tocan eventos ajenos ni se duplican; a Google solo se envía servicio, hora y código de la cita, sin cédula, teléfono ni correo; cambios de Google por webhook más una sincronización de respaldo con el cron diario existente, que también renueva la suscripción antes de que venza.

## Recordatorio de feriados sin definir

Desde siete días antes de un feriado cuya atención nadie ha definido, ADI se lo recuerda a administración en el inicio y en la agenda: «ADI informa: El lunes 2 de noviembre es feriado nacional (Día de Difuntos) y aún no se ha definido la atención. Revisa el decreto oficial y elige atención normal, horario especial o cerrado». El botón «Definir atención» lleva al gestor. El recordatorio desaparece al elegir un modo o al ocultar la fecha, y solo lo ve administración.

## Rediseño de «Feriados y atención» (13/10/2026)

**Causa del texto vertical.** Cada fila repartía el ancho en tres columnas (`118px minmax(0,1fr) auto`). La tercera, con el selector, las horas y los botones, tomaba todo el ancho que pedía y a la del nombre le quedaba un ancho mínimo; con `overflow-wrap:anywhere` el nombre se partía letra por letra. Además, el bloque estaba en una columna estrecha de la configuración.

**Ahora.** El bloque ocupa todo el ancho. Tres zonas: encabezado (año y resumen: feriados, sin definir, sin atención, horario especial, días propios), **feriados nacionales y locales** y **días no laborables propios**. Cada fecha es una tarjeta con la fecha destacada, el nombre completo, tipo, origen y estado; los controles (atención, horas, Guardar, Editar, Quitar) van en su propia zona y no comprimen el texto. En móvil se apilan.

**Guardado.** «Cambios sin guardar» por tarjeta; Guardar se desactiva mientras procesa y no admite doble clic; se conservan la posición y el foco. Antes de guardar un día sin atención o con horario especial se consultan las citas de ese día (`action: check`) y, si alguna queda fuera, se pide confirmación. **Nunca se cancela ni se mueve una cita.**

**Validaciones del servidor.** Cierre posterior a la apertura, en intervalos de 15 minutos y con duración suficiente para la cita más corta que se ofrece. El formulario de alta no pisa una fecha ya registrada ni un feriado calculado.

**Fuente de los feriados.** Los nacionales se calculan en `holidays.national` con las reglas de traslado de la ley; no se consulta ningún servicio externo. Los locales no se suponen: los agrega administración para su localidad. Un decreto puede cambiar fechas: debe ajustarse aquí a mano.
