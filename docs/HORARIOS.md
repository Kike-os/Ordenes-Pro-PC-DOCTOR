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

## Pendiente de confirmar por administración

Los límites «para agendar citas» comunicados (lunes a viernes hasta las 11:00 p. m., sábado hasta las 10:30 p. m., domingo hasta las 7:30 p. m.) **no se han aplicado a la agenda**: son posteriores al cierre presencial y pueden significar la hora límite para *solicitar* una cita en línea o la hora hasta la que se *atienden* citas. La agenda sigue con sus franjas actuales hasta que se confirme.
