# Registro de cambios — Órdenes Pro | PC-DOCTOR S.A.

Generado desde `local/data/releases.json` con `python local/versioning.py changelog`. No editar a mano.

Numeración semántica: MAYOR (cambios que rompen compatibilidad), MENOR (nuevas funcionalidades compatibles), PARCHE (corrección de errores).

## v1.5.13 — 2026-10-11 13:04 (UTC-05:00)

Historial de la Orden compacto, seguimiento con textos claros e identificación de equipos por número de serie

### Nuevas funcionalidades

- Identificación inteligente por número de serie en la recepción: reconoce equipos que ya ingresaron al taller y completa marca, modelo y tipo tras confirmar

### Mejoras realizadas

- Historial de la Orden: panel compacto con últimos eventos, ver todos, filtros, detalle expandible y actualización automática
- Seguimiento de Órdenes: cada tarjeta muestra el estado nuevo como título y el estado anterior como detalle

### Errores corregidos

- El historial registra de forma explícita cada cambio de estado, también los hechos al editar la orden, y ya no guarda eventos vacíos «Estado actualizado»

## v1.5.12 — 2026-10-11 12:49 (UTC-05:00)

Avisos de actualización Glass Glow.

### Mejoras realizadas

- Avisos de actualización estilo Glass Glow: toast fino con icono y brillo según el estado (comprobando, actualizado, nueva versión, actualizando y error), con Reintentar, Actualizar ahora y Posponer.

## v1.5.11 — 2026-10-11 12:43 (UTC-05:00)

Seguimiento de órdenes con colores por estado y microanimaciones.

### Mejoras realizadas

- Seguimiento de órdenes con paleta por estado (línea lateral de color), iconos por actividad y efectos discretos al pasar el cursor y al registrarse un movimiento; misma posición y medidas.

## v1.5.10 — 2026-10-11 12:39 (UTC-05:00)

Corrección del título «Centro de Operaciones».

### Errores corregidos

- El título del inicio ahora se escribe «Centro de Operaciones».

## v1.5.9 — 2026-10-11 12:27 (UTC-05:00)

Centro de Actividad, seguimiento de órdenes bajo los indicadores y aviso de versión rediseñado.

### Nuevas funcionalidades

- Centro de Actividad: página nueva con resumen por categoría, pestañas, búsqueda, fecha, filas compactas y panel de detalles; los riesgos de infraestructura permanecen visibles hasta resolverse.

### Mejoras realizadas

- Seguimiento de órdenes reubicado bajo los indicadores: tres últimos movimientos en horizontal, con el cambio real de estado («de X a Y»), responsable y actualización automática.
- Aviso de versión nueva rediseñado (Smart Release): «Nueva versión disponible · Release X · Lista para cargar», con Actualizar ahora, Posponer y contador.
- Indicador Release con icono dinámico por estado: capas, sincronización, flecha de versión nueva, visto de completada y alerta de error.

## v1.5.8 — 2026-10-11 10:36 (UTC-05:00)

Correos devueltos, Centro de Notificaciones compacto por categorías, Estado de actualizaciones y selector múltiple de correo.

### Nuevas funcionalidades

- Mail Pro: detección de correos devueltos y entregas retrasadas analizando los informes de entrega (DSN), con aviso del destinatario afectado y registro único.

### Mejoras realizadas

- Mail Pro: los rechazos del servidor de envío se distinguen (destinatario rechazado, error temporal, rechazo del mensaje) y el envío correcto se informa como «Envío aceptado por el servidor».
- Centro de Notificaciones compacto (Smart Notification Center): mini panel translúcido agrupado por categorías y nueva página «Actividad y notificaciones» con búsqueda, filtros y marcado como leído.
- Tarjeta «Estado de actualizaciones» rediseñada y sincronizada con el indicador Release, con la cuenta regresiva de recarga segura; «Novedades» solo aparece mientras no se haya consultado el historial.
- Mail Pro: selector múltiple compacto con contador y acciones en una fila de altura fija; la lista ya no se desplaza al seleccionar.

## v1.5.7 — 2026-10-11 10:26 (UTC-05:00)

Protección de datos con respaldo diario de la base central y actualización automática segura de las sesiones abiertas.

### Nuevas funcionalidades

- Actualización automática segura: la sesión abierta detecta la versión nueva, muestra una cuenta regresiva de cinco minutos en el indicador Release y se recarga sola solo si no hay trabajo sin guardar; se puede actualizar ahora o posponer.

### Mejoras realizadas

- Ficha de cliente con estado de guardado real (Guardando, Guardado en la nube, Error, Cambios sin guardar) y aviso cuando la instalación usa una base local.
- Centro de Actualizaciones: «Tu sistema está actualizado · Versión: X» con insignia NEW.

### Actualizaciones de seguridad

- Respaldo diario y verificado de la base de datos central, con restauración de prueba y aviso a administración si los respaldos se atrasan.

## v1.5.6 — 2026-10-11 10:12 (UTC-05:00)

Barra de selección de correo con Eliminar siempre visible y aviso para recargar tras una actualización.

### Mejoras realizadas

- Mail Pro: barra de selección con «Eliminar» siempre visible al inicio y el resto de acciones en iconos compactos cuando falta espacio; lista de correos más ancha.
- Si la página quedó abierta con una versión anterior, aparece un aviso para recargar y usar la versión nueva.

## v1.5.5 — 2026-10-11 10:04 (UTC-05:00)

Bandeja de correo estilo Outlook, destinatarios desde Clientes, Centro de Notificaciones flotante y Seguimiento de órdenes.

### Nuevas funcionalidades

- Mail Pro: bandeja estilo Outlook con casillas, selección múltiple, acciones rápidas por mensaje y barra contextual (Leídos, No leídos, Archivar, Mover, Eliminar y menú «Más»), con operaciones reales en el servidor de correo.
- Mail Pro: «Eliminar» mueve a la Papelera con opción «Deshacer»; desde la Papelera se puede restaurar o eliminar definitivamente con confirmación.
- Mail Pro: destinatarios con sugerencias de la base de Clientes, etiquetas, contactos frecuentes y libreta de contactos en Para, CC y CCO.
- Seguimiento de órdenes: línea de tiempo compacta con iconos por proceso, filtros y un historial completo con búsqueda y fechas.

### Mejoras realizadas

- Centro de Notificaciones flotante bajo la campana y avisos más compactos (Micro Notification Premium); ya no cambia el ancho de la página.
- Mail Pro: indicador de conexión real (Conectado, Sincronizando, Reconectando, Sin conexión, Error de autenticación) con reintentos progresivos.

### Errores corregidos

- Mail Pro: la firma corporativa y su logo se ven al leer los correos recibidos; los mensajes HTML se muestran con sus colores sobre fondo claro.
- Mail Pro: el error «Recurso no disponible» al eliminar se debía a un servidor sin reiniciar tras actualizar; ahora el mensaje explica la causa.

## v1.5.4 — 2026-10-11 09:31 (UTC-05:00)

Firma corporativa visible en el redactor de correo, editor con formato y vista previa del mensaje.

### Mejoras realizadas

- Mail Pro: redactor con formato real (negrita, cursiva y listas), vista previa del correo completo y firma en tres columnas: logo original, nombre y cargo, y datos de contacto; preferencias separadas para mensajes nuevos, respuestas y reenvíos.

### Errores corregidos

- Mail Pro: la firma corporativa aparece siempre al abrir «Nuevo mensaje», Responder y Reenviar (se carga desde el servidor al abrir el redactor) y los borradores recuerdan si llevan firma sin duplicarla.

## v1.5.3 — 2026-10-11 09:21 (UTC-05:00)

Nueva orden de recepción técnica con fotos de evidencia, firma corporativa de correo, avisos flotantes bajo la campana y tarjeta «Capacidad del Buzón».

### Nuevas funcionalidades

- Nueva orden de recepción técnica: asistente de cinco pasos con inspección inicial y accesorios por casillas, fotos del equipo como evidencia (arrastrar, cámara, ordenar, foto principal), borrador y resumen con edición por sección.
- Las órdenes muestran sus fotos de recepción en el detalle, con ampliación y opción de añadir más.
- Mail Pro: firma corporativa con el logo original, insertada automáticamente en correos nuevos, respuestas y reenvíos, configurable en «Firmas de correo».

### Mejoras realizadas

- Avisos flotantes bajo la campana con efecto translúcido, animación suave y pausa al pasar el cursor; no desplazan el contenido.
- Mail Pro: tarjeta «Capacidad del Buzón» con barra de color según la ocupación real, estado, detalle y efecto al recibir una medición nueva.

## v1.5.2 — 2026-10-11 08:43 (UTC-05:00)

Mail Pro con almacenamiento en tiempo real, diagnóstico de sonido y borradores sin duplicados.

### Nuevas funcionalidades

- Mail Pro: almacenamiento del buzón siempre al día (cada minuto y al sincronizar), con botón «Actualizar almacenamiento», fuente del dato y conexión opcional a cPanel UAPI de solo lectura.
- Mail Pro: prueba de sonido y notificaciones con diagnóstico del reproductor, aviso en pantalla y aviso de escritorio.

### Errores corregidos

- Mail Pro: al cambiar la cuota del buzón el indicador podía seguir mostrando el valor anterior; ahora explica el motivo técnico cuando no hay datos.
- Mail Pro: reabrir un borrador y guardarlo o enviarlo ya no deja copias duplicadas en Borradores.

## v1.5.1 — 2026-10-11 08:22 (UTC-05:00)

Adi AI rediseñada, chat flotante compacto con atención real de asesores, Mail Pro con avisos de correo nuevo y almacenamiento real, y reloj y clima renovados.

### Nuevas funcionalidades

- Adi AI — Centro de Inteligencia Administrativa: nuevo diseño con estado operativo del taller, conversaciones guardadas por usuario (abrir, buscar, renombrar y eliminar) e indicador de actividad según el estado real de cada consulta.
- Adi AI: sonidos configurables, lectura de respuestas por voz del navegador y dictado opcional con revisión antes de enviar.
- PC-DOCTOR Mail Pro: aviso automático de correo nuevo (emergente, campana y Centro de Notificaciones) sin duplicados, con sonidos configurables y notificación de escritorio opcional.
- Mail Pro: almacenamiento real del buzón informado por el servidor, con alertas al 75 % y 90 %; filtros No leídos, Destacados y Con adjuntos; vista previa de cada mensaje; copia oculta (CCO) y redactor ampliable.

### Mejoras realizadas

- Adi AI: el chat se ajusta a la altura real del navegador y el editor de mensajes es de varias líneas, crece hasta 220 px, envía con Enter y conserva el texto si falla la conexión.
- Chat flotante de Adi rediseñado: ventana compacta, encabezado «Adi · Atención PC-DOCTOR», minimizar y cerrar, editor que crece, contador de mensajes sin leer, sonidos opcionales y repliegue automático ante diálogos, menús y notificaciones.
- Mail Pro rediseñado: tres paneles ajustados a la pantalla, carpetas plegables con iconos unificados, barra de acciones en el lector, sincronización manual y automática con estado visible.
- Reloj y clima del encabezado rediseñados: segundos en vivo con dígitos estables, panel con la fecha completa, iconos del clima animados según la condición real y panel de detalle con sensación térmica, humedad, viento y lluvia prevista.
- Mail Pro: formato básico en el redactor (negrita, cursiva y listas) y preferencias de avisos guardadas en la cuenta.
- El chat de Adi conserva la conversación del cliente durante 30 días en su navegador.

### Errores corregidos

- El chat de Adi muestra el estado real de la atención (Adi, esperando asesor, asesor conectado, finalizada), no duplica solicitudes de asesor y avisa a administración cuando un cliente espera.
- El clima ya no recorta el texto de la condición y, si el proveedor no responde, conserva la última lectura válida marcada como desactualizada.

## v1.5.0 — 2026-10-11 02:50 (UTC-05:00)

Adi administrativa en vivo, indicador Release conectado al registro oficial, botón de Adi compacto y corrección del indicador de carga del acceso.

### Nuevas funcionalidades

- Adi administrativa con indicadores del taller en vivo, conversación con historial, consultas sugeridas y enlaces a cada módulo.

### Mejoras realizadas

- El botón de Adi se recoge a un tamaño compacto y se despliega al acercar el cursor, para no tapar el contenido.
- Indicador «Release» conectado al registro oficial de versiones, con etiqueta de actualización disponible, brillo y barrido de luz al detectarla.

### Errores corregidos

- El botón de iniciar sesión mostraba dos indicadores de carga a la vez; ahora muestra uno solo.

## v1.4.1 — 2026-10-11 02:15 (UTC-05:00)

Etiqueta Smart Release en el encabezado y en el acceso.

### Mejoras realizadas

- Etiqueta «Release» en el encabezado con estado de actualización, aviso de versión nueva y panel con la versión instalada y la publicada.

## v1.4.0 — 2026-10-11 01:55 (UTC-05:00)

PC-DOCTOR Mail Pro, Centro de Configuración y Administración, gestión de cuentas y sesiones, e indicador de versión «Release».

### Nuevas funcionalidades

- Centro de Configuración y Administración con navegación por categorías: perfil, seguridad y sesiones, usuarios y permisos, servicios, políticas, condiciones y estado.
- Cambio de contraseña desde Configuración, cierre de las demás sesiones y activación, desactivación y cambio de rol de las cuentas del equipo.
- Herramienta de pruebas de conexión IMAP y SMTP para PC-DOCTOR Mail Pro (fase 1).
- PC-DOCTOR Mail Pro: correo empresarial integrado con carpetas, lectura segura, redacción, respuestas, reenvío, adjuntos, borradores, búsqueda y vínculo con clientes y órdenes.
- Aviso de correos sin leer en el Centro de Notificaciones y sección de correo en Configuración con pruebas de conexión y firma.

### Mejoras realizadas

- Indicador de versión del acceso con etiqueta «Release» y aviso cuando hay una actualización pendiente.

## v1.3.1 — 2026-10-11 01:14 (UTC-05:00)

Corrige la gestión de solicitudes de cuenta rechazadas.

### Errores corregidos

- Las solicitudes de cuenta rechazadas siguen visibles en Configuración, pueden aprobarse y la persona puede volver a enviarlas.

## v1.3.0 — 2026-10-11 01:00 (UTC-05:00)

Gestión de clientes con importación, solicitud de cuentas, notificaciones por usuario, inicio de sesión rediseñado y Centro de Actualizaciones con comprobación automática.

### Nuevas funcionalidades

- Gestión de clientes: importación desde Excel o CSV con vista previa, detección de duplicados, copia de seguridad e informe; exportación; filtros; ficha con historial técnico y observaciones.
- Solicitud de cuenta desde la pantalla de acceso, con aprobación obligatoria de administración.
- Notificaciones con historial por usuario guardado en el servidor, menú bajo la campana y avisos emergentes con cola, barra de tiempo y pausa al pasar el cursor.
- Historial público de novedades en /novedades y versión del sistema visible en el inicio de sesión.
- Comprobación automática de nuevas versiones al iniciar sesión, una vez por sesión y sin bloquear la carga.

### Mejoras realizadas

- Inicio de sesión rediseñado: tarjeta compacta, encabezado jerárquico, campos y botón uniformes e indicador de carga.
- Verificación «No soy un robot» con nueva presentación y barra de progreso.
- Búsqueda de clientes en la orden por correo y teléfono secundario, con navegación por teclado y aviso de fichas por completar.
- Centro de actualizaciones rediseñado: versión actual destacada, comprobación con estados reales e historial más legible.
- Iconografía unificada con trazos Lucide en la navegación y el centro de actualizaciones.
- Historial de versiones como acordeón compacto con despliegue animado y marca de «Versión actual».
- Centro de notificaciones como panel lateral con recientes y anteriores; la actualización detectada queda registrada hasta instalarse.

### Errores corregidos

- El aviso de campo obligatorio del inicio de sesión ya no aparece antes de intentar enviar el formulario.

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
