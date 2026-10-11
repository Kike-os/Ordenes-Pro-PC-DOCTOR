# Agenda de Mantenimientos de Clientes — 11/10/2026

Una sola vista administrativa para las **citas** y los **mantenimientos preventivos**. No hay base de datos nueva: las citas son la misma tabla `appointments` que usa la reserva pública (`/citas`) y los preventivos salen de `maintenance`.

## Flujo

1. El cliente reserva en `/citas`: elige tipo de equipo (categoría) y servicio (intervención), consulta los horarios y confirma.
2. El servidor valida los datos, comprueba otra vez la disponibilidad (horario del taller y de cada técnico, días no laborables, citas existentes) y registra la cita. Una segunda reserva del mismo espacio se rechaza.
3. La cita aparece en la agenda y genera una notificación persistente «Ver cita» (una por cita).
4. El personal la confirma, reprograma o cancela. Cada cambio queda en el historial con usuario y hora.
5. El cliente recibe correo solo cuando la cita queda confirmada, reprogramada o cancelada, y solo si dejó correo y autorizó comunicaciones.
6. Al llegar el equipo, «Crear orden desde la cita» abre la recepción con cliente, tipo, marca y modelo ya cargados y deja la orden vinculada. Ninguna cita se convierte sola en orden.

## Confirmación: automática o manual

Configuración de la agenda → «Confirmación de citas en línea».

- **Automática (valor inicial, como funcionaba antes):** la reserva queda confirmada al instante porque la disponibilidad se verificó en el servidor.
- **Manual:** queda «Pendiente de confirmación» hasta que el taller la confirme.

## Estados de la cita

Pendiente de confirmación (ámbar), Confirmada (verde), Reprogramada (violeta), En atención (cian), Completada (turquesa), Cancelada (gris), No asistió (naranja). Son independientes del estado técnico de la orden. «Nueva» es una etiqueta para las citas creadas en las últimas 24 horas, no un estado.

Los preventivos tienen sus propios estados (programado, con cita, realizado): una fecha sugerida no es una cita confirmada.

## Servicios

Se administran en la configuración: nombre, duración (intervalos de 15 minutos), activo o no, y alta de servicios nuevos. Se añadió «Mantenimiento correctivo» con 90 minutos, igual que el preventivo; ajústalo si no corresponde. No hay precios. «Mantenimiento de laptop/PC/impresora/consola» no se crearon como servicios porque mezclan categoría de equipo e intervención: el formulario ya pide el tipo de equipo por separado.

## Correos

Los envía `local/appointments_cron.py` (cron del servidor) y requieren `SMTP_HOST` y `SMTP_FROM`. El aviso al taller va a `APPOINTMENTS_NOTIFY_TO` o, si no existe, a `SMTP_FROM`; se envía una vez por cita. Si el cron no está programado o SMTP no está configurado, los correos quedan «pendientes de envío» y la agenda y las notificaciones internas siguen funcionando.

## Rutas

- `GET /api/agenda?from=&to=` (personal): citas del período, preventivos y resumen.
- `GET /api/appointments/<id>` (personal): cita con historial y avisos.
- `POST /api/appointments/<id>`: `confirmada`, `presente`, `completada`, `no_asistio`, `cancelada`, `reschedule`.
- `POST /api/appointments/config` (administración): horarios, servicios, modo de confirmación y días no laborables.

## Próximos Mantenimientos (previsión automática a seis meses)

- Al cambiar una orden a **Entregado**, el servidor crea en la misma transacción la previsión para seis meses calendario después (31/08 → 28/02; 15/10 → 15/04). Una sola por orden (`maintenance.order_id` es único): guardar otra vez, repetir la solicitud o recargar no duplica.
- «Listo para entregar» no crea nada. Si la entrega se revierte, la previsión queda cancelada con su historial; si se vuelve a entregar, se reactiva el mismo registro.
- La respuesta del cambio de estado trae la previsión, y la interfaz avisa «Próximo mantenimiento programado» solo tras esa confirmación. La ventana «Próximos Mantenimientos» consulta cada 30 s, así que una entrega hecha en otra sesión aparece sin recargar.
- **No se crea una cita ni se bloquea ningún horario automáticamente.** La previsión aparece también en la Agenda de Mantenimientos de Clientes como «Preventivo · pendiente de confirmación», sin horario asignado. Es el único registro: no hay una segunda fila en otra tabla.
- **Agendar cita** (desde la previsión) abre la reserva con cliente y equipo cargados y los horarios realmente disponibles. Al guardarla queda vinculada (`maintenance.appointment_id`, migración 026) y la previsión pasa a «Con cita». Cancelar esa cita la devuelve a «Programado»; completarla la cierra.
- Filtros: «Todos los programados», «Próximos 30 días», «Vencidos», «Con cita», «Realizados». Una fecha a seis meses no aparece en «Próximos 30 días».
- Avisos internos, una sola vez por plazo: al crearse y al faltar 30, 15, 7 y 0 días.
- Pendiente: recalcular la previsión al corregir una fecha de entrega, el enlace para que el cliente confirme por sí mismo y el envío automático de invitaciones.
