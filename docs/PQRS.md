# PQRS: peticiones, quejas, reclamos y sugerencias (1.5.278)

Canal oficial para que los clientes presenten peticiones, quejas, reclamos y sugerencias. No necesitan iniciar sesión, y la página funciona en español e inglés.

## Decisiones de administración (11/11/2026)

- **Sedes:** lista configurable. Al principio solo existe «Matriz»; con una sola sede, el formulario la deja elegida.
- **Permisos:**
  - Administración ve y gestiona todas las PQRS.
  - Un técnico solo ve y responde las que tiene asignadas. No puede cerrar, reabrir, asignar, cambiar la prioridad ni exportar.
  - Estas reglas se comprueban en el servidor (`pqrs.py`); la interfaz solo oculta lo que no corresponde.
- **Conservación:** no hay borrado automático. Los casos, su historial, sus adjuntos y sus avisos no se pueden eliminar (disparadores en la base). Los datos que envió el cliente tampoco se pueden modificar. La política queda documentada para revisión del asesor legal (normativa ecuatoriana de protección de datos personales).

## Para el cliente

- **Acceso:** el botón «PQRS» de la página de inicio, junto a «Agendar cita», o la dirección `/pqrs`.
- **Formulario:**
  - Tipo: Petición, Queja, Reclamo o Sugerencia.
  - Datos de contacto: nombre completo, correo y teléfono internacional con bandera y prefijo.
  - Sede, asunto y descripción.
  - Opcional: número de orden e identificación de su titular.
  - Hasta 3 adjuntos.
  - Aceptación de la política de privacidad y tratamiento de datos personales.
  - Autorización opcional de avisos por WhatsApp.
- **Relación con una orden:** solo se establece si la identificación coincide con la del cliente de esa orden. La respuesta es igual coincida o no: conocer un número de orden no revela nada. El personal ve si la orden quedó verificada.
- **Adjuntos:**
  - Formatos: fotografías JPG, PNG o WEBP, o PDF.
  - Hasta 10 MB cada uno, con vista previa.
  - Se suben por partes de 2,5 MiB, porque Vercel limita cada petición a 4,5 MB.
  - Al terminar se comprueban tamaño, huella SHA-256 y tipo real por los primeros bytes. Un ejecutable renombrado como `.pdf` se rechaza.
  - Se guardan en la base, nunca en una carpeta pública, y no se ejecutan.
  - Las cargas que no llegan a enviarse se borran a las 24 h.
- **Al enviar:**
  - **Código y duplicados:** se genera un código único `PQRS-AAAA-NNNN` dentro de la transacción exclusiva de la petición; el código es además único en la base. Un doble envío no crea un duplicado.
  - **Enlace de seguimiento:** el cliente ve su número y un enlace privado de seguimiento, y recibe la confirmación por correo en el idioma en que escribió.
- **Seguimiento (`/pqrs/seguimiento`):**
  - **Acceso:** con el número y el código privado del enlace.
  - **Qué muestra:** estado, fechas, sede, asunto y los mensajes públicos (respuestas del equipo, cierre y reapertura).
  - **Qué nunca muestra:** correo, teléfono, notas internas, responsables ni adjuntos.
  - **Respuesta del cliente:** puede responder o aportar información mientras el caso no esté cerrado; si estaba esperando sus datos, vuelve a «En revisión».

## Para el personal (Órdenes Pro → PQRS)

- **Bandeja:**
  - Indicadores: nuevas, abiertas, sin primera respuesta en más de 48 h, tiempo medio de primera respuesta y tiempo medio de resolución.
  - Contadores por estado.
  - Filtros por tipo, sede, prioridad y fechas, y búsqueda por código, cliente, correo, asunto u orden.
  - El menú muestra cuántas PQRS hay por atender. Las nuevas (o las asignadas, para un técnico) aparecen también en el centro de notificaciones.
- **Detalle:**
  - Solicitud, datos del cliente, orden relacionada y adjuntos. Los adjuntos se abren por partes y solo con sesión autorizada.
  - Historial completo, marcado como visible para el cliente o interno.
  - Avisos con su resultado real.
- **Acciones:** todas quedan en la auditoría.
  - Cambiar el estado: Recibida, En revisión, Asignada, Esperando información del cliente, En proceso de solución y Respondida.
  - Asignar responsable.
  - Fijar la prioridad: baja, normal, alta o urgente.
  - Responder al cliente.
  - Escribir notas internas.
  - Cerrar con la resolución y reabrir con un motivo.
  - Reintentar un aviso fallido.
- **Exportación e impresión:**
  - **CSV:** solo administración, con los filtros aplicados. Las celdas que empiezan por `=`, `+`, `-` o `@` llevan un apóstrofo para que no se ejecuten como fórmulas.
  - **A4:** se imprime una copia limpia, sin menús ni campos, con el logotipo original y la fecha.
- **Sedes:** botón «Sedes» de la bandeja (solo administración).

## Avisos

- **Correo al cliente, en su idioma (español o inglés):**
  - Momentos: recepción, cambios de estado, respuestas y cierre.
  - Cada intento queda registrado (enviado, fallido, correo no configurado o sin correo válido) y se puede reintentar.
  - Si el correo falla, la PQRS sigue registrada.
  - El envío usa Mail Pro, su firma y su registro, sin cambiar su configuración.
- **WhatsApp Business:**
  - Eventos `pqrs_recibida`, `pqrs_actualizada` y `pqrs_respondida`.
  - Solo si el cliente marcó la autorización en el formulario y WhatsApp está configurado con su plantilla. Se registra como autorización de origen «formulario».
  - Usa la misma cola, los mismos reintentos y el mismo panel de Configuración → Integraciones.
- **Personal:** centro de notificaciones y contador del menú.

## Seguridad

- **Validación:** todo se valida en el servidor; el navegador solo ayuda a corregir. Las consultas son parametrizadas y los textos se guardan sin caracteres de control. Se muestran siempre como texto, nunca como HTML, y el correo escapa el HTML.
- **Origen de las peticiones:** los envíos públicos exigen JSON y un origen permitido. Las acciones del personal exigen sesión y CSRF.
- **Límites por conexión:**
  - 6 PQRS por hora.
  - 15 adjuntos por hora.
  - 30 consultas de seguimiento cada 15 minutos.
  - 10 mensajes del cliente por hora.
- **Enlace de seguimiento:** es un HMAC del código con una clave aleatoria propia de PQRS, guardada en la base, no en el código. Solo se guarda su huella.

## Archivos

- **Servidor:** `local/pqrs.py`.
- **Base de datos:** `local/migrations/104_pqrs.sql`, aditiva.
- **Página pública:** `local/templates/pqrs.html` y `local/static/pqrs.js`.
- **Panel:** `local/static/pqrs-admin.js`.
- **Traducciones:** `local/static/i18n.js`.
- **Estilos:** `local/static/app.css`.
- **Integración:** rutas en `local/app.py`, eventos en `local/whatsapp_business.py` y avisos en `local/notifications.py`.
- **Pruebas:** `local/tests/test_pqrs.py`.

## Pendiente

- **WhatsApp:** los avisos por WhatsApp se activan cuando se carguen las credenciales de Meta y la plantilla (ver `docs/WHATSAPP-BUSINESS.md`). Hasta entonces el correo es el canal activo.
- **Correo en producción:** los avisos se envían si Mail Pro está configurado en el servidor.
