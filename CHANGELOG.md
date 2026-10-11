# Registro de cambios — Órdenes Pro | PC-DOCTOR S.A.

Generado desde `local/data/releases.json` con `python local/versioning.py changelog`. No editar a mano.

Numeración semántica: MAYOR (cambios que rompen compatibilidad), MENOR (nuevas funcionalidades compatibles), PARCHE (corrección de errores).

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
