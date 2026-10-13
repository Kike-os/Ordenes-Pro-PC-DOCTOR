# Horarios y Disponibilidad

Fuente única de los horarios de PC-DOCTOR S.A. (`local/business_hours.py`, guardada en `system_state`). Todas las horas son de America/Guayaquil.

## Horarios oficiales (12/10/2026)

| Días | Atención presencial |
|------|---------------------|
| Lunes a viernes | 7:45 a. m. – 8:30 p. m. |
| Sábado | 9:00 a. m. – 9:00 p. m. |
| Domingo | 10:00 a. m. – 5:00 p. m. |

Atención virtual: «Atención virtual disponible las 24 horas, los 7 días de la semana, mediante ADI, nuestra asistente inteligente.» Los asesores humanos responden en el horario presencial; no se promete atención humana permanente.

## Tres cosas distintas

1. **Atención presencial**: cuándo está abierto el taller. Se edita en Configuración → Horarios y Disponibilidad.
2. **Disponibilidad de citas**: franjas de la agenda y de cada técnico, duración por servicio y feriados (módulo Citas). El servidor solo acepta citas dentro de esas franjas. Cambiar el horario presencial **no** cambia la agenda ni las citas existentes.
3. **Atención virtual**: ADI, a cualquier hora, mientras el servicio esté operativo.

## Quién los usa

- **ADI**: en cada consulta lee los horarios vigentes, el día y la hora de Ecuador, si la atención presencial está abierta ahora y las franjas de la agenda; viajan como contexto validado al proveedor de IA y, sin IA, la respuesta se arma con los mismos datos. No hay horarios escritos en sus instrucciones.
- **Página de citas** (`/citas`): estado actual, horario presencial, mensaje de atención virtual y próximos cierres (`GET /api/public/hours`).
- **Panel**: Configuración → Horarios y Disponibilidad, con el estado actual, los siete días, los mensajes y los cierres extraordinarios. Solo administración guarda (`POST /api/business-hours`, auditado); «Restablecer horarios oficiales» recupera los de esta tabla.

## Hora límite para solicitar citas en línea

Lunes a viernes hasta las 11:00 p. m., sábado hasta las 10:30 p. m. y domingo hasta las 7:30 p. m. Es la hora hasta la que la página de reservas acepta solicitudes ese día; no es horario de atención ni indica que haya técnicos disponibles a esa hora. Se edita en Configuración → Horarios y Disponibilidad y se puede desactivar.

## De dónde salían los horarios antiguos

«Lunes a viernes de 09:00 a 17:00; sábado de 09:00 a 13:00» no estaba escrito en las instrucciones de ADI: eran las franjas guardadas en la agenda de citas y en el horario del técnico, que ADI leía al hablar de citas. El 12/10/2026 esas franjas se pusieron en el horario oficial y ADI dejó de citar las franjas de la agenda como horario: informa el horario presencial, la hora límite de solicitud y la atención virtual, y consulta las horas libres reales.
