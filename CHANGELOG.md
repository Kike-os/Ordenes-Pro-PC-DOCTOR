# Registro de cambios — Órdenes Pro | PC-DOCTOR S.A.

Generado desde `local/data/releases.json` con `python local/versioning.py changelog`. No editar a mano.

Numeración semántica: MAYOR (cambios que rompen compatibilidad), MENOR (nuevas funcionalidades compatibles), PARCHE (corrección de errores).

## v1.2.0 — 2026-10-10 23:54 (UTC-05:00)

Notificaciones del sistema, Adi renovada, reserva de citas rediseñada, Centro de operaciones reorganizado y aviso de privacidad.

### Nuevas funcionalidades

- Notificaciones del sistema: campana en el encabezado con lo que requiere atención y la actividad reciente, y avisos emergentes al completar acciones o cuando otra persona registra cambios.
- Notificaciones del sistema en un panel lateral: lo que requiere atención, la actividad reciente y las novedades de versión, con sonido opcional, contador en la pestaña y avisos emergentes.
- Aviso al personal cuando entra una cita nueva desde la agenda en línea.
- Aviso de privacidad publicado en /privacidad y enlazado desde la reserva de citas.

### Mejoras realizadas

- Sistema y actualizaciones rediseñado, con barra de comprobación por etapas y textos más legibles.
- Adi con chat rediseñado, respuestas rápidas, indicador de escritura, aviso de mensajes y respuestas basadas en los horarios, servicios y contacto configurados.
- Reserva pública de citas con nuevo título, pasos, secciones numeradas y confirmación con el código de la cita.
- Agenda de citas interna con barra de navegación y configuración ordenada por secciones.
- Historial de versiones con resumen de cambios por versión y botón para expandir todo.
- Centro de operaciones reorganizado: citas de hoy arriba, entregas junto a mantenimientos, indicadores compactos e iconos más acordes a cada estado.
- Indicadores del Centro de operaciones con un color propio por estado.

### Errores corregidos

- La configuración de la agenda de citas ya se guarda; antes el servidor la rechazaba.
- Los servicios de la agenda muestran su estado activo real en la configuración.

## v1.1.0 — 2026-10-10 22:05 (UTC-05:00)

Mejoras de presentación en el Centro de operaciones, el detalle de la orden, los formularios de clientes y órdenes, el encabezado y el icono de la pestaña.

### Mejoras realizadas

- Centro de operaciones con iconos renovados, indicadores con insignia, títulos de panel con icono y acciones de fila más claras.
- Actividad reciente con tipo de evento, tiempo relativo e iconos por tipo.
- Detalle de la orden con estado destacado, avance por fases, selector de estado etiquetado y acciones en cuadrícula en móvil.
- Etiquetas de estado de las órdenes con indicador de color.
- Registro de clientes con resumen completo, pasos completados marcados y acceso directo a la ficha existente cuando la identificación ya está registrada.
- Nueva orden con opciones de autorización más claras.
- Encabezado con el logotipo original más grande y mejor alineado con el título y el subtítulo.
- Icono oficial de PC-DOCTOR S.A. en la pestaña del navegador para todas las páginas.

### Errores corregidos

- El detalle de la orden muestra el nombre del tipo de equipo y la fecha de entrega con formato.
- El asistente de nueva orden ya no conserva el aviso de error al cambiar de paso.
- El registro de clientes ya no marca como erróneos los campos de ubicación que aún están deshabilitados.
- Los nombres de provincias, cantones y parroquias que empezaban en minúscula (El Oro, Los Ríos, La Troncal…) se muestran con mayúscula inicial.

## v1.0.0 — 2026-10-10 21:27 (UTC-05:00)

Primera versión registrada de Órdenes Pro. Reúne las funciones disponibles en esta fecha; el control de versiones comienza aquí.

### Nuevas funcionalidades

- Recepción de equipos y órdenes de servicio con comprobante, ticket térmico, etiqueta y código QR.
- Registro de clientes y equipos con búsqueda y filtros.
- Centro de operaciones con órdenes que requieren atención, actividad reciente y reportes por estado.
- Agenda de citas pública y agenda de mantenimientos.
- Asistente Adi y centro de atención en vivo.
- Módulo «Sistema y actualizaciones» con versión instalada, historial de versiones y registro de cambios.

### Mejoras realizadas

- Inicio de sesión con foco inicial, aviso de Bloq Mayús y mensajes de error destacados.
- Clima del encabezado en una sola línea y separación corregida en Configuración.
- Longitud mínima de contraseña configurable desde 6 caracteres.

### Errores corregidos

- El formulario de nueva orden ya no avisa de datos sin guardar cuando está vacío.
- La página pública de condiciones cubre toda la pantalla con el fondo corporativo y tiene icono.
- El botón «Acceso al sistema» de la agenda pública usa los colores del panel.

### Actualizaciones de seguridad

- Verificación «No soy un robot» en el inicio de sesión, comprobada en el servidor.
- Bloqueo temporal tras intentos fallidos, protección CSRF y sesiones privadas por rol.
