# Auditoría de formularios — Órdenes Pro

Fecha: 10 de octubre de 2026. Cambios aplicados al código existente y servicio local actualizado. Se conservaron logo, colores y fondo tecnológico.

## Correcciones confirmadas

- **Clientes, alta y edición:** cierre X accesible sin recortes; modal de hasta 810 px y 90 % de altura; encabezado y navegación visibles; cuerpo desplazable; tres pasos compactos; cuadrícula uniforme; errores próximos al campo; botones equilibrados. Persona natural inicia con cédula; empresa utiliza RUC. Se corrigió la conservación accidental del documento del formulario anterior.
- **Órdenes, alta:** cuatro pasos, búsqueda compacta por nombre/identificación/teléfono/nombre comercial, tarjeta de selección y siguiente deshabilitado sin cliente. Equipo dividido en secciones, recepción con fecha/hora y estado, confirmación ampliada. Abrir registro de cliente conserva el borrador de la orden y evita dos modales abiertos.
- **Edición, presupuestos y seguimiento técnico:** estructura común, cierre accesible, campos y navegación adaptables, importes y errores conservados. Se mantiene control de revisión para evitar sobrescrituras concurrentes.
- **Equipos y mantenimientos:** cierre, dimensiones y desplazamiento comunes; confirmación al descartar cambios; Escape y restauración de foco en los modales compartidos. Se mantiene la lógica existente de programación y consentimiento.
- **Citas públicas:** mensajes junto a controles, teléfono/documento validados, bloqueo de envío simultáneo, clave de idempotencia conservada en reintentos con el mismo contenido y protección contra respuestas de disponibilidad obsoletas.
- **Configuración y Adi:** revisión de presentación adaptable y etiqueta accesible de consulta administrativa. Se conservan permisos y funciones existentes; se impiden reenvíos mientras la operación está en curso.
- **Acceso y recuperación:** revisión de presentación; se mantienen validaciones, respuesta de autenticación genérica, bloqueo al quinto fallo, recuperación de uso único y revocación de sesiones previamente implementados.
- **Inicio:** distribución operativa 65/35, actividad limitada a cinco registros, próximas entregas, mantenimientos, citas y atención; navegación agrupada en Asistencia. Sin datos inventados en el sistema real.

## Validaciones y protección de datos

Validación compartida en navegador para cédula/RUC y teléfonos ecuatorianos. El servidor valida documentos según tipo, pasaporte, teléfono, correo, ubicación, relación cliente/orden y campos obligatorios. Se reforzaron también las rutas heredadas de clientes y equipos. Duplicados no sobrescriben fichas existentes. La validación documental es estructural y de dígito verificador; no acredita existencia o estado ante SRI/Registro Civil.

No se realizaron migraciones nuevas para esta auditoría ni modificaciones de clientes, órdenes, números, QR o historial reales. Pruebas funcionales y capturas usan SQLite temporal aislada. Se conservan copias anteriores en `revision/forms-audit-20261010`, `revision/operations-redesign-20261010` y `revision/auth-20261010`.

## Archivos modificados en esta etapa

- `local/static/app.js`: asistentes, modales, estados de selección, presentación del inicio y controles de envío.
- `local/static/app.css`: estilos delimitados de formularios y panel operativo; adaptación móvil y movimiento reducido.
- `local/static/form-validation.js`: validadores puros compartidos, archivo nuevo.
- `local/static/appointments.js`: errores, disponibilidad e idempotencia de reservas.
- `local/templates/dashboard.html`: estructura del inicio y carga de validadores.
- `local/templates/appointments.html`: carga de validadores compartidos.
- `local/app.py`: recursos estáticos, validaciones heredadas y datos operativos del inicio.
- `local/reception.py`, `local/appointments.py`: validación telefónica del servidor.
- `local/tests/test_app.py`, `local/tests/test_operations.py`: datos válidos y regresiones adicionales.

Los cambios anteriores de acceso se documentan separadamente en `ACCESO-SEGURO.md`.

## Pruebas realizadas

1. `python -m unittest discover -s local/tests -v`: **69 pruebas aprobadas**. Incluyen autenticación, CSRF, cookies, cinco intentos, recuperación/caducidad/uso único, revocación, documentos, duplicados, relaciones, guardado, idempotencia, estados, presupuestos, conflictos, historial, QR, permisos, agenda, mantenimiento, comprobantes y WSGI.
2. Chromium con datos ficticios: **56 comprobaciones geométricas** de inicio y pasos de clientes/órdenes, más siete comprobaciones del bloqueo de Siguiente sin cliente.
3. Chromium: **56 comprobaciones adicionales** de edición de cliente, edición/presupuesto, seguimiento, equipo, reprogramación de mantenimiento, configuración, agenda y Adi. Conservación del borrador al abrir/cerrar el registro de cliente verificada.
4. Chromium: acceso, solicitud de recuperación, nueva contraseña y reserva pública revisados a los siete anchos. El enlace inválido se utiliza para la comprobación visual de restablecimiento; el cambio con token válido se comprueba en las pruebas del servidor.
5. Anchos: **1920, 1440, 1366, 1024, 768, 390 y 320 px**. Se comprueban desbordamiento horizontal, modal dentro de pantalla, cierre y pie visibles y ausencia de modales simultáneos. No se detectaron errores JavaScript en las comprobaciones del panel; Chromium emite una recomendación informativa sobre campo de usuario en el formulario de nueva contraseña.
6. Sintaxis JavaScript comprobada con `node --check`. Servicio reiniciado y estado activo confirmado.

Evidencias: `revision/forms-audit-20261010/viewport-checks.json`, `additional-forms-checks.json`, `public-forms-checks.json`, `tests.log` y capturas PNG por formulario y ancho.

## Pendientes y límites de verificación

- No hay SMTP configurado en este entorno: el envío real y recepción del correo corporativo siguen pendientes. Las pruebas comprueban contenido, token y lógica de envío con transporte simulado.
- HTTPS público y Turnstile requieren configuración del alojamiento/proveedor. Las verificaciones actuales usan servicio local.
- Argon2id es opcional y no está instalado aquí; las contraseñas existentes siguen utilizando scrypt seguro compatible. No se cambió ninguna contraseña real.
- No se comprobó una impresión física en Epson TM-m30 ni funcionamiento en dispositivos físicos; se verificaron documentos/rutas y tamaños en Chromium.
- La respuesta remota de Adi depende de la configuración del proveedor; esta auditoría verifica su formulario y conserva su funcionamiento existente.
- La comprobación de formularios extensos corresponde a sus rutas, componentes y casos cubiertos; no equivale a explorar todas las combinaciones posibles de datos o navegadores.
