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

## Rediseño de Horarios y Disponibilidad (21/10/2026)

En Configuración → Horarios y Disponibilidad. Se conservan los datos guardados, la fuente única que usan ADI y las páginas públicas, y la regla del servidor de que la apertura sea anterior al cierre.

- **Indicador en vivo:**
  - Muestra «Abierto» o «Cerrado» con la etiqueta que calcula el servidor (hora de Ecuador, horario y cierres), por ejemplo «Cerrado ahora · abre hoy a las 7:45 a. m.».
  - Indica el motivo si hoy hay un cierre extraordinario y el próximo cierre registrado.
  - Muestra el reloj de Ecuador al segundo. Cada minuto vuelve a consultar el estado al servidor; no lo inventa el navegador.
- **Atención presencial:** tabla compacta Día | Estado | Apertura | Cierre.
  - Interruptores pequeños con «Abierto/Cerrado» y horas de 24 h en pasos de 15 minutos. Una hora guardada fuera de esa rejilla se conserva.
  - Validación en vivo: si la apertura no es anterior al cierre, la fila se marca, se explica el motivo y no se puede guardar.
  - «Restablecer horarios oficiales» carga los valores oficiales, que no se aplican hasta guardar.
- **Tarjetas separadas:**
  - Agenda de citas: hora límite de solicitud y franjas de la agenda, con acceso a su configuración.
  - Atención virtual ADI 24 h.
  - Cierres extraordinarios, sin fechas pasadas al añadir.
- **Cambios pendientes:**
  - La barra cuenta los cambios («2 cambios sin guardar»). Con cambios se fija al pie, con borde rosado, y deja libre la esquina de la esfera de ADI.
  - «Descartar cambios» vuelve a lo guardado. «Guardar cambios» confirma con «Cambios guardados a las …» y un aviso, sin recargar la sección.
  - La actualización automática del sistema no recarga mientras haya cambios sin guardar.
- **Iconos Lucide de 18 a 20 px.** Estilos acotados a `#module-content .hours-pro`. El menú del Centro de Configuración (línea rosada, fondo azul tenue, contraíble) ya existía y no cambia.

**Pruebas en navegador** (base temporal con datos ficticios):
- 18 comprobaciones de la sección: indicador, tabla, horas de 24 h, validación, conteo, descartar, guardar y persistir, cierres, tarjetas, iconos, teclado, actualización automática, 1024, 768, 390 y 320 px, y ausencia de errores de JavaScript;
- 4 comprobaciones de la barra fija frente a la esfera de ADI;
- las 16 comprobaciones anteriores del Centro de Configuración.
