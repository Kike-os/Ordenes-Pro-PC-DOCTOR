# Citas sin solapamientos, en línea y sincronizadas

## Reglas de la agenda

- **Duración**: la define cada servicio (múltiplos de 15 minutos; se cambia en la configuración de la agenda).
- **Margen entre citas**: 15 minutos por defecto, configurable de 0 a 60. Cada cita bloquea a su técnico durante la duración más el margen. Con una atención de 45 minutos, una cita a las 10:00 ocupa hasta las 11:00: no se puede reservar a las 10:10, 10:15, 10:30 ni 10:45 con ese técnico, y la siguiente libre es a las 11:00.
- **Horas de inicio**: cada 15 minutos desde la apertura del día (7:45, 8:00, 8:15…). Una hora que no esté en la lista se rechaza.
- **Capacidad**: una cita a la vez por técnico. Con varios técnicos activos y dentro de su horario puede haber citas simultáneas, una por técnico.
- **Estados que bloquean**: solicitada, confirmada y reprogramada. Cancelada, completada y «no asistió» liberan la franja.
- **Franjas**: agenda y horario de cada técnico, hoy iguales al horario oficial de atención presencial (lunes a viernes 7:45–20:30, sábado 9:00–21:00, domingo 10:00–17:00). Feriados y cierres aparte.
- **Hora límite para solicitar citas en línea**: lunes a viernes 23:00, sábado 22:30, domingo 19:30 (Configuración → Horarios y Disponibilidad). Es la hora hasta la que la página acepta solicitudes ese día; no es horario de atención.

## Protección en el servidor

Toda reserva, reprogramación o cancelación se ejecuta dentro de una transacción exclusiva de escritura: la disponibilidad se vuelve a comprobar ahí, de modo que dos solicitudes simultáneas no pueden quedarse con la misma franja. La clave de solicitud evita duplicados por reintentos. Si la hora ya no está libre, la respuesta incluye el aviso «El horario seleccionado ya no está disponible. Puede agendar su cita a las … o seleccionar otro horario» y las alternativas reales.

Se corrigió un fallo latente: reprogramar a una hora ocupada devolvía un valor con formato incorrecto y habría respondido con error interno.

## Sincronización

Vercel ejecuta funciones de corta duración, por lo que no se usan conexiones permanentes (Server-Sent Events o WebSockets). En su lugar hay una señal ligera, `GET /api/public/appointments/pulse`, que cambia cuando cambia la agenda y no contiene datos de citas ni de clientes.

- **Página de reservas**: consulta la señal cada 12 s con la pestaña visible; si cambió, recarga las horas libres, conserva la elegida si sigue disponible y avisa si se ocupó. Muestra «En línea · disponibilidad comprobada a las …» o «Sin conexión · reintentando»; sin respuesta del servidor nunca da una reserva por hecha.
- **Agenda del panel**: consulta la señal cada 10 s y recarga el período visible cuando cambia (con una recarga de respaldo cada minuto).

## ADI

ADI no confirma citas. Lee los horarios vigentes y, cuando el cliente pide una fecha y hora («mañana a las 10:00 a. m.»), comprueba esa hora en la agenda con el mismo cálculo de la página de reservas y responde si está libre o cuáles son las opciones libres más próximas. La reserva se hace y se confirma en `/citas`.

## Pendiente

- Reservar, reprogramar o cancelar desde la conversación de ADI (hoy remite a `/citas`).
- Avisos por WhatsApp (requiere la integración oficial).
- Bloqueos manuales de franjas sueltas en el calendario (hoy: feriados, cierres y horario por técnico).
