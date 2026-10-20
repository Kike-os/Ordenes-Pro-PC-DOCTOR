# Registro de cambios — Órdenes Pro | PC-DOCTOR S.A.

Generado desde `local/data/releases.json` con `python local/versioning.py changelog`. No editar a mano.

Numeración semántica: MAYOR (cambios que rompen compatibilidad), MENOR (nuevas funcionalidades compatibles), PARCHE (corrección de errores).

## v1.5.174 — 2026-10-19 19:19 (UTC-05:00)

Inasistencias automáticas y reagendamiento por enlace privado

### Nuevas funcionalidades

- Inasistencias automáticas: las citas confirmadas sin llegada registrada pasan a «No asistió» tras la tolerancia configurada (desactivado por defecto)
- Reagendamiento por enlace privado: correo «Reagenda tu cita técnica» y página pública con días y horarios libres; la cita conserva código e historial y queda marcada como «Reagendada»

### Mejoras realizadas

- Agenda: estado del enlace, envío manual del enlace o de una rectificación y configuración de tolerancia, vigencia y límite de reagendamientos

## v1.5.173 — 2026-10-19 14:44 (UTC-05:00)

Rediseño de Licencias Pro y del Centro de notificaciones

### Mejoras realizadas

- Registrar nueva licencia y Vender o entregar licencia rediseñados por secciones, con resumen comercial, activación y pie fijo; Centro de notificaciones con contadores «sin leer · en total», filtros, ocultar avisos e historial

### Errores corregidos

- Licencias Pro: los formularios ya no tienen desplazamiento horizontal ni botones cortados (la ventana imponía un ancho mínimo mayor que su tamaño)

## v1.5.172 — 2026-10-19 14:04 (UTC-05:00)

Licencias Pro: vigencias, renovaciones, notificaciones y Mis licencias

### Nuevas funcionalidades

- Licencias Pro — Control de Vigencia y Renovaciones: registro de licencias nuevas con logo y comprobante, vigencia por activación, compra o fecha fija, activación, renovaciones con historial, entrega manual, devoluciones y Mis licencias en la ficha del cliente
- Notificaciones de renovación por correo con plantilla corporativa, configurables, con historial, reintentos y exclusión por cliente (desactivadas hasta activarlas)

## v1.5.171 — 2026-10-19 13:20 (UTC-05:00)

Consecutivo diario de órdenes PCD-AAAAMMDD-0001

### Errores corregidos

- Número de orden: vuelve el consecutivo diario PCD-AAAAMMDD-0001 (reinicia cada día en hora de Ecuador), sin duplicados ni saltos por intentos fallidos y con aviso controlado al llegar a 9999

## v1.5.170 — 2026-10-19 13:01 (UTC-05:00)

Corrección de equipos de confianza en producción

### Errores corregidos

- Equipos de confianza en producción: la cookie de confianza y el cierre de sesión en todos los dispositivos llegan correctamente al navegador

## v1.5.169 — 2026-10-19 12:37 (UTC-05:00)

Recordar mi sesión, equipos de confianza y cierre de sesión en todos los dispositivos

### Mejoras realizadas

- Recordar mi sesión: hasta 30 días aunque se cierre el navegador; dispositivos de confianza en Configuración y cierre de sesión en todos los dispositivos

### Actualizaciones de seguridad

- Confiar en este equipo durante 30 días tras la verificación en dos pasos, con tokens guardados solo como huella y revocación automática

## v1.5.168 — 2026-10-19 09:56 (UTC-05:00)

Corrección de estilos de la entrega de licencias

### Errores corregidos

- Página pública de entrega de licencias: su hoja de estilos se publica correctamente (el servidor omitía el archivo license.css)

## v1.5.167 — 2026-10-19 09:52 (UTC-05:00)

Inventario de Licencias Digitales y presupuestos con existencias

### Nuevas funcionalidades

- Inventario de Licencias Digitales: productos con logo, licencias individuales cifradas, registro por lote, reservas al aprobar, confirmación de pago y autorización de entrega separadas, entrega por enlace privado con identificación y código, historial

### Mejoras realizadas

- Presupuestos: botón «Agregar producto, servicio o repuesto» con existencias de licencias y alta rápida de servicios o repuestos

## v1.5.166 — 2026-10-19 09:02 (UTC-05:00)

Consecutivo OP-0001, autorización digital de citas y catálogo de servicios ampliado

### Nuevas funcionalidades

- Autorización digital de citas: aceptación expresa de las condiciones vigentes y últimos 4 dígitos de la cédula, con evidencia inmutable e identificador único
- Catálogo de servicios de la Agenda ampliado: categorías, buscador, 13 servicios nuevos, varios servicios por cita y tipo de licencia

### Mejoras realizadas

- Consecutivo permanente de órdenes OP-0001: no se reinicia por fecha, no reutiliza números y es seguro con registros simultáneos; las órdenes existentes conservan su número

### Errores corregidos

- La consulta pública de estado y la verificación de los 4 dígitos en citas antiguas reconocen correctamente los números y documentos

## v1.5.165 — 2026-10-19 08:08 (UTC-05:00)

Corrección del QR de la autenticación en dos pasos

### Mejoras realizadas

- Autenticación en dos pasos: botón «Generar nuevo código QR» que invalida la clave anterior, cuenta y emisor visibles y botones Cancelar y Continuar alineados

### Errores corregidos

- Autenticación en dos pasos: el código QR se mostraba recortado y no se podía escanear (SVG sin viewBox); ahora se ve completo y se comprueba su lectura

## v1.5.164 — 2026-10-14 14:05 (UTC-05:00)

Verificación en dos pasos reforzada y tarjetas de equipos rediseñadas

### Mejoras realizadas

- Seguridad de mi cuenta: asistente de activación en dos pasos (QR centrado, clave manual oculta con Copiar, campo de 6 dígitos que admite pegar), estados No configurado, Configuración pendiente y Protección activa, y descarga de los códigos de recuperación
- Tarjetas de equipos E01, E02…: cabecera sin superposición, estado compacto «Revisión recurrente» con el nombre completo accesible y selección discreta

### Errores corregidos

- Seguimiento de Órdenes: la etiqueta de revisiones recurrentes ya no corta «Atención en curso»

### Actualizaciones de seguridad

- Verificación en dos pasos: el secreto TOTP se guarda cifrado y autenticado con una clave maestra fuera de la base; se auditan los intentos fallidos

## v1.5.163 — 2026-10-14 13:40 (UTC-05:00)

Estados automáticos de presupuestos sincronizados con la orden

### Mejoras realizadas

- Presupuestos: estados automáticos «Esperando respuesta», «Aprobado», «Aprobado parcialmente» y «Rechazado» con colores e iconos, motivo del cliente y avisos inmediatos
- Al aprobar el cliente un presupuesto, la orden en «Aprobación de presupuesto» pasa sola a «Procesando»; nunca se cambian los estados de entrega

### Errores corregidos

- Un presupuesto cuyo correo no se pudo enviar ya no figura como enviado: se muestra «Enlace creado · correo no enviado»

## v1.5.162 — 2026-10-14 09:45 (UTC-05:00)

Estado «En revisión por falla recurrente» con trazabilidad completa

### Nuevas funcionalidades

- Nuevo estado «En revisión por falla recurrente» (ámbar oscuro): misma orden, motivo y técnico responsable obligatorios, número de revisiones, reingreso trazable de equipos ya entregados y aplicación solo al equipo afectado

## v1.5.161 — 2026-10-14 09:08 (UTC-05:00)

Libreta de direcciones y comunicados a clientes en Mail Pro; Servicio de Administración Remota en la agenda

### Nuevas funcionalidades

- Mail Pro: libreta de direcciones con los clientes del registro (búsqueda, selección individual o de todos, contador y destinatarios en Para, CC o CCO)
- Comunicados a clientes: plantillas con firma y logotipo, personalización con el nombre, vista previa, confirmación expresa, envío individual por lotes, control de duplicados, estados de entrega, historial y baja de comunicados
- Agenda: nuevo servicio «Servicio de Administración Remota»

### Errores corregidos

- Agenda: el selector muestra «Selecciona el Servicio»

## v1.5.160 — 2026-10-14 08:50 (UTC-05:00)

Ticket térmico definitivo: compacto, completo y con QR de condiciones

### Mejoras realizadas

- Ticket térmico: distribución definitiva y más compacta (número, recepción, cliente, equipo, falla, servicio, condiciones, QR y firma), condiciones de recepción en siete puntos breves y QR de las condiciones completas junto al de seguimiento

## v1.5.159 — 2026-10-14 08:35 (UTC-05:00)

ADI AutoCare Pro: monitoreo, diagnóstico y recuperación segura

### Nuevas funcionalidades

- ADI AutoCare Pro: panel en Sistema con estado general, servicios, incidencias activas, recuperaciones, versiones, historial técnico, «Ejecutar diagnóstico» y configuración de avisos

### Mejoras realizadas

- Estabilidad: 13 verificaciones de solo lectura (autenticación, clientes, tickets y presupuestos PDF, correo, agenda, ADI, errores de ejecución) con severidad y un reintento seguro ante fallos transitorios
- Registro de errores de ejecución clasificados por severidad, sin datos personales, con avisos administrativos

## v1.5.158 — 2026-10-14 08:24 (UTC-05:00)

Corrección urgente de la vista previa e impresión de tickets

### Errores corregidos

- Imprimir ticket: la vista previa volvía a quedar bloqueada en producción («ha rechazado la conexión»); ahora se muestra siempre, «Ticket listo» solo cuando el documento está visible y, si algo falla, aviso con «Reintentar»

## v1.5.157 — 2026-10-14 08:13 (UTC-05:00)

Ticket de recepción compacto y nombrado con el número de orden

### Mejoras realizadas

- Ticket de recepción: condiciones del servicio más breves, claras y compactas, en lista legible a 8 pt

### Errores corregidos

- El ticket se guarda y descarga como TICKET-<número de orden>.pdf, también desde el visor de la vista previa

## v1.5.156 — 2026-10-14 07:28 (UTC-05:00)

Monitor de estabilidad profesional y barra superior unificada

### Mejoras realizadas

- Monitor de estabilidad rediseñado: luz de estado, cuenta atrás real, barra del período y verificaciones completadas y pendientes
- Barra superior: versión y estabilidad en un único componente; atajo «/» o Ctrl+K para buscar órdenes, clientes y números de serie

### Errores corregidos

- Estabilidad: una versión con alguna prueba fallida en su última verificación ya no se declara estable

## v1.5.155 — 2026-10-14 07:04 (UTC-05:00)

Historial de estabilidad completo al cambiar de versión

### Errores corregidos

- Estabilidad: «Versiones anteriores» conserva también las versiones verificadas antes del resumen por versión

## v1.5.154 — 2026-10-14 07:00 (UTC-05:00)

Estabilidad de la versión automatizada con tareas programadas del servidor

### Mejoras realizadas

- Estabilidad de la versión automatizada desde el servidor: tres verificaciones programadas al día, historial por versión, tiempo restante, próxima verificación y paso automático a «Versión estable»

### Errores corregidos

- La estabilidad ya no depende de las visitas, no pierde el historial de versiones anteriores y un fallo crítico reinicia el seguimiento en lugar de bloquearlo

## v1.5.153 — 2026-10-14 06:43 (UTC-05:00)

Indicador de estabilidad de versiones con verificaciones automáticas de solo lectura

### Nuevas funcionalidades

- Indicador de estabilidad de versiones en el acceso y en la barra superior: No verificada, Verificando, En observación, Estable o Requiere atención, según verificaciones reales registradas

## v1.5.152 — 2026-10-14 06:27 (UTC-05:00)

Corrección de entregas revertidas por error: sin indicador «Entrega reabierta» y sin fecha de entrega residual

### Errores corregidos

- Entrega revertida por error: la previsión de mantenimiento anulada ya no aparece como «Entrega reabierta» y la orden deja de conservar la fecha de la entrega revertida

## v1.5.151 — 2026-10-13 22:24 (UTC-05:00)

PC-DOCTOR Mail Pro — Seguimiento inteligente de entregas. Se incorporó un centro de seguimiento de correos con estados de envío, entrega, demora y rebote, historial de eventos, alertas administrativas y herramientas para corregir destinatarios y reenviar mensajes.

### Nuevas funcionalidades

- PC-DOCTOR Mail Pro — Seguimiento inteligente de entregas: Centro de Entrega y Seguimiento con estados de envío, entrega, demora y rebote por destinatario, historial de eventos, alertas administrativas y corrección de destinatario con reenvío

### Mejoras realizadas

- Los rebotes y demoras que llegan al buzón se asocian al envío real; los envíos automáticos no se repiten a direcciones declaradas inválidas

## v1.5.150 — 2026-10-13 21:58 (UTC-05:00)

Firma corregida en los correos automáticos, Seguimiento de Órdenes ultracompacto, indicadores de citas modernizados y calendario de feriados en la Agenda

### Mejoras realizadas

- Seguimiento de Órdenes ultracompacto: encabezado en una línea, filas de 54 px, columnas de ancho fijo, acciones alineadas, menú de acciones en tableta y celular y tarjetas resumidas en celulares
- Órdenes con varios equipos en el seguimiento: identificador de la orden, etiqueta del equipo y estado general real (nunca completada con equipos en proceso)
- Modernización de indicadores de citas: píldoras uniformes con icono para todos los estados (Por confirmar, Reagendada, En atención, No asistió…)
- Calendario de Feriados y Atención en la Agenda con tarjetas compactas, estados de disponibilidad y lista ampliable

### Errores corregidos

- Firma corporativa en los correos automáticos: llega con las medidas de la vista previa, cabe completa en el mensaje y no se corta en celulares

## v1.5.149 — 2026-10-13 21:32 (UTC-05:00)

Restauración de firma corporativa original

### Mejoras realizadas

- Citas: una cita marcada «En atención» por error puede volver a agendada desde la agenda («Volver a cita agendada»), sin avisos al cliente y conservando su historial.

### Errores corregidos

- Restauración de firma corporativa original: se corrigió la visualización de la firma corporativa en la configuración y los correos electrónicos, restaurando el logotipo original de PC-DOCTOR y conservando su distribución y diseño institucional.

## v1.5.148 — 2026-10-13 21:17 (UTC-05:00)

Corrección de configuración de feriados y horarios especiales

### Errores corregidos

- Corrección de configuración de feriados y horarios especiales: se corrigió el funcionamiento de los controles Guardar y Quitar en la administración de feriados. Se mejoraron la persistencia de configuraciones, las validaciones de horarios, las confirmaciones y el diseño responsive.

## v1.5.147 — 2026-10-13 21:02 (UTC-05:00)

Firma original en los correos, lector de correo, feriados y atención, catálogo Premium Técnico y reactivación de citas

### Nuevas funcionalidades

- Citas: nueva acción «Reactivar cita» para devolver a la agenda una cita cerrada por error, con confirmación, comprobación del horario y sin avisos al cliente.

### Mejoras realizadas

- Lector de correo rediseñado: el mensaje se muestra con su formato original (tablas, imágenes y firmas) en un área aislada y segura, sin desbordes; encabezado y acciones fijos, opción Ampliar, Imprimir y menú de acciones en pantallas pequeñas.
- Mejora de calendario — Feriados y atención: se rediseñó la administración de feriados y días no laborables, corrigiendo problemas de visualización, alineación y distribución. Se optimizaron los controles de horarios especiales y la gestión de disponibilidad para citas.
- Catálogo Premium Técnico — Mejoras de productos y servicios: se renovó la interfaz de selección de productos y servicios mediante tarjetas profesionales, logotipos de marca, iconos técnicos y una distribución optimizada. Se mejoraron la búsqueda, los filtros, la visualización de precios, la adaptación móvil y la estabilidad general del catálogo.

### Errores corregidos

- Firma corporativa: el sistema ya no reconstruye la firma ni le añade una franja roja. Se puede cargar la firma original como imagen y se envía tal cual en todos los correos, desde un único punto para todos los módulos.

## v1.5.146 — 2026-10-13 20:08 (UTC-05:00)

Recibo de pago en PDF, reporte de saldos por cobrar, saldo en los listados y pasaporte en la reserva de citas

### Nuevas funcionalidades

- Recibo de pago en PDF para cada pago, abono o devolución, con el saldo al emitirlo; se puede abrir para imprimir o enviar al correo registrado del cliente.
- Reportes: nuevo panel «Saldos por cobrar», con el total pendiente, los equipos con saldo y lo cobrado y devuelto en el rango de fechas por forma de pago.

### Mejoras realizadas

- El listado de órdenes y Seguimiento muestran el saldo de cada equipo (debe, abonó, pagado o a favor) sin abrir la orden.
- Agendamiento de citas: se puede reservar con pasaporte, además de cédula o RUC.

## v1.5.145 — 2026-10-13 19:28 (UTC-05:00)

Seguimiento de Órdenes: botón Historial y contadores de tamaño estable

### Mejoras realizadas

- Mejora de interfaz — Seguimiento de Órdenes: se optimizó el diseño de los botones Historial y sus contadores numéricos, garantizando dimensiones uniformes, correcta alineación y estabilidad visual. También se mejoró la distribución de las acciones y la compatibilidad con diferentes tamaños de pantalla.

## v1.5.144 — 2026-10-13 18:58 (UTC-05:00)

Prueba de entrega real de correo al administrador

### Mejoras realizadas

- Configuración: nuevo botón «Enviar prueba a mi correo», que envía un correo de prueba al correo de la cuenta del administrador para comprobar la entrega real.

## v1.5.143 — 2026-10-13 18:48 (UTC-05:00)

Verificación en dos pasos opcional con aplicación de autenticación y códigos de recuperación

### Actualizaciones de seguridad

- Verificación en dos pasos opcional para el personal: código de una aplicación de autenticación al iniciar sesión, diez códigos de recuperación de un solo uso y retiro por administración si alguien pierde el teléfono.

## v1.5.142 — 2026-10-13 18:32 (UTC-05:00)

Tarjeta financiera con saldo real, pagos generales, devoluciones y protección contra pagos duplicados

### Nuevas funcionalidades

- Tarjeta financiera en el detalle de la orden: saldo real con estados automáticos (pendiente, pago parcial, sin saldo, sin cargos y saldo a favor), saldo por equipo y general de la orden, pagos generales con asignación a un equipo y devoluciones.

### Actualizaciones de seguridad

- Pagos: un doble clic o un reintento ya no registran el movimiento dos veces; los movimientos registrados no se editan ni se borran, y el saldo nunca se muestra en cero por un error de conexión.

## v1.5.141 — 2026-10-13 14:36 (UTC-05:00)

Ventana de ADI ordenada: accesos en cuadrícula, márgenes uniformes y controles alineados

### Errores corregidos

- Ventana de ADI: accesos rápidos en cuadrícula de dos columnas, botones uniformes, márgenes interiores iguales, campo de mensaje alineado con el micrófono y Enviar, y accesos inferiores en dos columnas; nada se sale de la ventana en móviles.
- Página de citas: la ventana de ADI recupera su estilo (la versión 1.5.140 le asignó por error una clase de otro componente).

## v1.5.140 — 2026-10-13 14:29 (UTC-05:00)

ADI revisa el nombre en la reserva de citas y nuevo encabezado ejecutivo del comprobante de recepción

### Nuevas funcionalidades

- ADI en el agendamiento público de citas: botón «ADI» junto a «Nombre y apellidos» que revisa mayúsculas, espacios, tildes y letras dudosas, y muestra una sugerencia que el cliente aplica o conserva; el nombre nunca cambia sin su confirmación.

### Mejoras realizadas

- Comprobante de recepción (ticket): encabezado ejecutivo sobre fondo blanco, sin franja negra, con título azul oscuro, copia en rosado («COPIA DEL CLIENTE» y «COPIA DEL ESTABLECIMIENTO») y filete fino.

## v1.5.139 — 2026-10-13 14:13 (UTC-05:00)

Selector de Cédula o RUC rediseñado y validación real por tipo de documento

### Mejoras realizadas

- Validación de cédula y RUC con las reglas de cada tipo y mensajes específicos (provincia, tercer dígito, dígito verificador, establecimiento); un RUC de sociedad o entidad pública cuyo dígito verificador no se puede comprobar se acepta con un aviso.

### Errores corregidos

- Selector de Cédula o RUC rediseñado y unificado en la reserva de citas, la ficha de cliente, la recepción y la cita del personal: botones alineados con el campo, contador junto a la etiqueta y pegado que conserva solo los dígitos.

## v1.5.138 — 2026-10-13 13:56 (UTC-05:00)

Equipos sin presupuestos: contador en cero y mensaje claro para crear el primero

### Mejoras realizadas

- Presupuestos: un equipo sin presupuestos muestra «0 presupuestos» y el mensaje «Sin presupuestos registrados. Este equipo está listo para generar su primer presupuesto».

## v1.5.137 — 2026-10-13 13:43 (UTC-05:00)

Selector de cédula o RUC en las citas, progreso y estado por equipo y tarjetas de equipo rediseñadas

### Nuevas funcionalidades

- Estado general de la orden con varios equipos (entrega parcial, atención en curso, orden completada) y resumen por etapas.

### Mejoras realizadas

- Reserva de citas: selector de tipo de identificación (cédula o RUC) con contador, solo dígitos y validación del dígito verificador; también disponible en la cita registrada por el personal.
- Tarjetas de «Equipos de esta orden» rediseñadas, con icono por tipo, estado en píldora y selección evidente.

### Errores corregidos

- En órdenes con varios equipos, la barra de progreso y el estado muestran el equipo seleccionado; ya no aparece «Entregado» por otro equipo.

## v1.5.136 — 2026-10-13 13:16 (UTC-05:00)

Retiro de equipos en la agenda, datos obligatorios y clientes desde citas, PDF del presupuesto con código QR y recordatorio de feriados

### Nuevas funcionalidades

- Agenda de citas: nuevo servicio «Retiro de Equipos», con comprobación opcional de la orden y sin marcar el equipo como entregado.
- Los clientes nuevos que agendan una cita se registran en Clientes con su origen; los existentes solo quedan vinculados y las coincidencias dudosas no se fusionan.
- ADI recuerda a administración los feriados próximos sin atención definida; la vigencia del enlace de aprobación es configurable.

### Mejoras realizadas

- Reserva de citas: nombre, cédula o RUC y teléfono obligatorios, validación al salir de cada campo y avisos compactos y específicos.
- PDF del presupuesto con diseño empresarial, importes alineados, condiciones por cláusulas y código QR del enlace de aprobación; el correo lo lleva adjunto.
- El panel de Seguimiento muestra cinco órdenes en todas las pantallas.

### Errores corregidos

- El descuento del PDF del presupuesto mostraba un signo «?» en lugar del signo menos.

## v1.5.135 — 2026-10-13 08:58 (UTC-05:00)

Presupuestos por estado y eliminación de borradores, ventana Presupuesto reorganizada, feriados con modos de atención, panel de Seguimiento ajustado y botones uniformes

### Nuevas funcionalidades

- Presupuestos del equipo agrupados por estado, con eliminación segura de borradores que nunca se enviaron.
- Feriados de Ecuador calculados con traslados, modos de atención por feriado, feriados locales y aviso de ADI.

### Mejoras realizadas

- Detalle de la orden: «Autorizaciones del cliente» y «Resumen del presupuesto» con importes autorizados, pagados y por cobrar claramente separados.
- Ventana Presupuesto: encabezado y pie fijos, partidas con etiquetas, errores junto al campo, acciones reorganizadas y anulación aparte.
- Historial de actividad del presupuesto y actividad reciente del equipo en línea de tiempo.
- Botón Historial con contador en insignia; botones Cancelar, Anterior, Siguiente y Cerrar con un mismo estilo.

### Errores corregidos

- Al quitar el IVA de una partida, el precio baja a su valor sin impuesto.
- El panel de Seguimiento de Órdenes ya no reserva altura vacía: mide las órdenes que muestra, hasta cinco.

## v1.5.134 — 2026-10-13 07:50 (UTC-05:00)

Clasificación e iconos en presupuestos, catálogo ampliado, importes con símbolo de dólar, cancelar y empezar desde cero, listado de órdenes adaptable e indicador de progreso

### Nuevas funcionalidades

- Presupuestos: cada partida puede clasificarse como Necesario, Obligatorio u Opcional, con texto y color en el editor, en la página del cliente y en el PDF.
- Catálogo: iconos automáticos por producto o servicio, diez elementos nuevos y marca «IVA por confirmar» que impide enviar un presupuesto hasta confirmarlo.
- Indicador de progreso animado según el estado real de cada orden, con destello único al registrarse la entrega.

### Mejoras realizadas

- Documentos: los importes llevan símbolo de dólar, separador de miles y dos decimales; el PDF del presupuesto muestra icono, clasificación y estado real de cada partida.
- Editor de presupuestos: «Cancelar» cierra sin guardar, «Empezar desde cero» vacía el formulario y un presupuesto nuevo no se crea hasta el primer guardado.
- Seguimiento de Órdenes: listado adaptable con teléfono del cliente, acciones con nombre, menú «Más» en pantallas pequeñas y orden por último movimiento.

### Errores corregidos

- El botón «Seleccionar productos y servicios» mostraba su icono a tamaño gigante.

## v1.5.133 — 2026-10-13 07:17 (UTC-05:00)

Detalle de la Orden renovado, presupuestos con partidas por decidir y ejecución, gestión técnica del equipo y reserva desde el chat de ADI

### Nuevas funcionalidades

- Presupuestos: el cliente puede dejar partidas por decidir, que pasan a una versión de continuación sin perder lo ya autorizado; cada partida aprobada tiene su estado de ejecución.
- ADI ofrece en el chat los próximos horarios libres como botones que abren la Agenda de Citas con fecha y hora ya elegidas.

### Mejoras realizadas

- Detalle de la Orden: paneles «Presupuestos pendientes de aprobación» y «Servicios y productos aprobados», equipos con información técnica, presupuesto propio y resumen general, y encabezado con cliente, equipo, técnico y prioridad.
- «Gestión técnica del equipo» (antes «Editar orden»): ventana por secciones, cambios pendientes, validación junto al campo y ADI con vista previa, edición de la propuesta y destello al aplicar.

### Errores corregidos

- Los importes de un presupuesto aprobado por el cliente ya no se pueden alterar desde la edición de la orden.
- El detalle de la orden muestra el teléfono y el correo vigentes del cliente, no los copiados al recibir el equipo.

## v1.5.132 — 2026-10-13 06:23 (UTC-05:00)

Acciones de Seguimiento, correos institucionales, catálogo profesional de presupuestos, documento de identidad y avisos uniformes

### Nuevas funcionalidades

- Correos institucionales: plantilla común con firma, revisión de redacción de ADI, copia exacta de cada envío e historial de correos por orden.
- Presupuestos: catálogo profesional con códigos, marcas, imágenes, tres modos de IVA, historial de precios, ventana de selección y descuentos autorizados de 0, 3 o 5 %.
- Presupuestos: administración puede solicitar el documento de identidad al aprobar; queda custodiado y solo lo consulta administración.

### Mejoras realizadas

- Seguimiento de Órdenes: cuatro acciones uniformes (Ver, Historial, QR y Ticket) que ya no se cortan en ninguna pantalla.
- Las confirmaciones del sistema usan un diálogo propio y uniforme en lugar de las ventanas del navegador.

## v1.5.131 — 2026-10-13 01:02 (UTC-05:00)

Presupuestos profesionales, selector de equipos y tarjeta de seguimiento compacta

### Nuevas funcionalidades

- Presupuestos profesionales: catálogo de servicios y productos, presupuestos por ítems con IVA incluido y versiones (P1, P2…), estado por servicio, envío al cliente por enlace privado, aprobación con firma manuscrita y evidencia, PDF corporativo y aviso interno al aprobar.

### Mejoras realizadas

- Equipos de esta orden: selector con panel de detalle en la misma página (E01, E02…), acciones por equipo y resumen económico de la orden aparte.
- Tarjeta de seguimiento más compacta, con el logotipo más grande e iconos por dato.

## v1.5.130 — 2026-10-13 00:37 (UTC-05:00)

Tarjeta de seguimiento, identificación por serie, citas en el acceso, bandeja de correo y Corrección Inteligente

### Nuevas funcionalidades

- Tarjeta Digital de Seguimiento Técnico: ticket de dos secciones con QR real al enlace público y código de barras Code 128 del número de orden; se abre desde la orden y el Seguimiento, se imprime o guarda como PDF y es la nueva vista pública del cliente.

### Mejoras realizadas

- Identificación por serie: al reconocer un equipo del historial se completan sus datos (con «Deshacer»), se muestra su tarjeta con logotipo e historial y el ingreso se asocia al equipo existente; logotipo de marca en Equipos, fichas y órdenes.
- Acceso: botón «Agendar cita» bajo el inicio de sesión y aviso de bienvenida de ADI junto a la esfera.
- Correo: las acciones de cada mensaje tienen columna propia y menú «⋯»; ya no tapan el asunto ni la vista previa.
- ADI: configuración «Corrección Inteligente» (revisión automática, sugerencias, formato, mejoras por botón, indicadores) con espera de 700 ms y estrella en turquesa.

## v1.5.129 — 2026-10-12 23:56 (UTC-05:00)

Seguridad del acceso, cierre por inactividad y actualizaciones del sistema

### Mejoras realizadas

- Acceso: usuario oculto con su propio ojo, límites de longitud (usuario 50, contraseñas nuevas 128) y estados en turquesa, rojo y verde.
- Versión del sistema: ventana única «Actualizaciones del sistema» con pestañas Novedades e Historial, aviso de novedades sin leer, icono de actualización e indicador verde, turquesa o ámbar.

### Actualizaciones de seguridad

- Acceso: cierre de sesión por inactividad a los 15 minutos con aviso y cuenta atrás; esperas progresivas tras intentos fallidos; verificación silenciosa solo cuando hay fallos recientes (se retira la casilla «No soy un robot»); campo trampa contra envíos automatizados.

## v1.5.128 — 2026-10-12 23:30 (UTC-05:00)

ADI: esfera con estados reales y sonidos rediseñados

### Mejoras realizadas

- ADI: esfera rosa y turquesa de 60 px con ondas internas de energía y estados diferenciados dibujados en 3D (escucha con el volumen real, proceso con anillo giratorio, respuesta, error discreto en coral); sonidos rediseñados, más suaves y con cola de eco tenue.

## v1.5.127 — 2026-10-12 23:26 (UTC-05:00)

Seguimiento de Órdenes en carrusel de altura fija

### Mejoras realizadas

- Seguimiento de Órdenes: carrusel de altura fija con tres órdenes a la vista, avance automático cada 6 s, pausa al interactuar o buscar, controles manuales, indicador «Mostrando órdenes…» y «Ver todas las órdenes»; búsqueda también por estado.
- Órdenes: el listado completo permite 10, 20 o 50 órdenes por página.

## v1.5.126 — 2026-10-12 23:08 (UTC-05:00)

Validación visual del inicio de sesión

### Mejoras realizadas

- Acceso: los campos muestran su estado con color, icono y texto (sin interacción, escribiendo, formato válido, error), «Verificando acceso…» al enviar y transición verde al confirmar; el rechazo sigue siendo genérico y no se consulta al servidor mientras se escribe.

## v1.5.125 — 2026-10-12 22:59 (UTC-05:00)

Clientes: tabla con columnas independientes y acciones alineadas

### Mejoras realizadas

- Clientes: tabla con columnas separadas de teléfono y correo, acciones alineadas del mismo tamaño (ver, editar, crear orden, llamar, correo) con estados deshabilitados explicados, total de clientes registrados y tarjetas compactas en móviles.

## v1.5.124 — 2026-10-12 22:54 (UTC-05:00)

Barras de desplazamiento, menús desplegables y selectores con el tema azul

### Mejoras realizadas

- Barras de desplazamiento con el tema azul en toda la aplicación (8 px, redondeadas, sin flechas).
- Menús desplegables con lista propia en azul tecnológico, accesible por teclado, para todos los selectores; tipografía y altura uniformes en selectores y filtros.

## v1.5.123 — 2026-10-12 22:45 (UTC-05:00)

ADI: esfera rosa y turquesa sin letras

### Mejoras realizadas

- ADI: esfera de cristal en rosa y turquesa, más realista (sombra interna, reflejos fríos y color más vivo) y sin letras en su interior.

## v1.5.122 — 2026-10-12 22:42 (UTC-05:00)

Varios equipos por orden, identidad del equipo y pagos

### Nuevas funcionalidades

- Recepción: «+ Agregar equipo» (equipo nuevo, similar o existente) sustituye a «Duplicar orden»; una orden admite varios equipos con identificadores propios (E01, E02…), cada uno con su recepción, diagnóstico, fotos, presupuesto, estado y entrega.
- Identidad permanente de cada equipo (EQ-0001), historial de equipos del cliente, pagos por equipo con resumen consolidado y bloqueo de entrega con saldo pendiente.

## v1.5.121 — 2026-10-12 22:24 (UTC-05:00)

ADI: esfera de cristal líquido

### Mejoras realizadas

- ADI: esfera de cristal líquido translúcido (rosa perla, lila, magenta suave e iridiscencia con reflejos cian), centro limpio y luminoso, cáustica interior, letras más finas e indicador de conexión engastado en el borde; la alternativa sin WebGL y el encabezado del chat usan el mismo material.

## v1.5.120 — 2026-10-12 20:08 (UTC-05:00)

Título «Agenda de Citas»

### Mejoras realizadas

- El módulo pasa a titularse «Agenda de Citas».

## v1.5.119 — 2026-10-12 20:06 (UTC-05:00)

ADI Living Orb y etiqueta «Nombres y Apellidos»

### Mejoras realizadas

- ADI Living Orb: movimiento orgánico sin giro constante, respiración irregular de unos 4 segundos, reacción a la cercanía del cursor, onda de superficie al tocarla e iridiscencia leve en el borde.
- La etiqueta pasa a «Nombres y Apellidos» en formularios, ficha del cliente, citas y comprobante.

### Optimización del rendimiento

- La esfera del encabezado del chat reutiliza el cuadro de la esfera flotante: un solo renderizador gráfico.

## v1.5.118 — 2026-10-12 20:01 (UTC-05:00)

Directorio de clientes compacto, ficha rápida y ADI en nombres

### Nuevas funcionalidades

- Ficha rápida del cliente en un panel lateral: contactos, ubicación, equipos, órdenes, citas y última atención, sin salir del listado.
- ADI en «Nombres y apellidos» y «Nombre comercial»: normaliza mayúsculas, minúsculas y espacios con vista previa, sin IA y sin cambiar ninguna palabra.

### Mejoras realizadas

- Directorio de clientes: vista compacta o cómoda (se recuerda), 10, 25 o 50 clientes por página, filtro por ciudad o cantón y por clientes sin órdenes, y orden por fecha de registro y última atención.
- Las acciones Llamar y Correo aparecen desactivadas, con su motivo, cuando el cliente no tiene un dato válido.

## v1.5.117 — 2026-10-12 19:53 (UTC-05:00)

Corrección urgente: consola del Centro de Atención

### Errores corregidos

- La consola del Centro de Atención en vivo vuelve a cargar: un cambio de la versión anterior provocaba un error interno al listar las conversaciones.

## v1.5.116 — 2026-10-12 19:50 (UTC-05:00)

Centro de Atenciones y ficha del equipo

### Mejoras realizadas

- Centro de Atenciones: nuevo título y subtítulo, indicador de conexión real, tres contadores sin solapes, lista de atenciones con hora de ingreso, tiempo de espera y origen, y un solo botón de acceso.
- La ficha del equipo en recepción explica con claridad su estado (identificado, registro manual, datos incompletos o no identificado).

### Errores corregidos

- Los contadores de atención ya no cuentan una misma conversación en varias categorías.

## v1.5.115 — 2026-10-12 19:44 (UTC-05:00)

Gestión de Clientes: directorio rediseñado y búsqueda sin tildes

### Nuevas funcionalidades

- «Por completar» indica exactamente qué datos obligatorios faltan; la ficha del cliente muestra sus citas y la última atención; aviso cuando otra ficha comparte teléfono o correo.

### Mejoras realizadas

- Gestión de Clientes rediseñada: indicadores reales (clientes, fichas completas y por completar), barra de herramientas adaptable, tabla compacta con iconos y orden por columnas, y acciones de contacto (WhatsApp, llamada, correo).
- Búsqueda de clientes sin tildes ni mayúsculas, por varias palabras en cualquier orden y por números con o sin guiones; también busca por cantón.

## v1.5.114 — 2026-10-12 19:09 (UTC-05:00)

ADI comprueba en la agenda la hora pedida

### Errores corregidos

- ADI responde con la comprobación real de la agenda cuando el cliente pide una fecha y hora concretas, sin dejar esa respuesta al modelo de IA.

## v1.5.113 — 2026-10-12 19:05 (UTC-05:00)

Horarios correctos en ADI y agenda sin solapamientos, sincronizada

### Nuevas funcionalidades

- Margen configurable entre citas (15 minutos por defecto): cada cita bloquea a su técnico durante la atención más el margen; horas de inicio cada 15 minutos desde la apertura.
- Hora límite diaria para solicitar citas en línea, separada del horario presencial y configurable.
- Agenda en línea sincronizada: la página de reservas y la agenda del panel se actualizan solas cuando alguien reserva, reprograma o cancela, con indicador de conexión.

### Mejoras realizadas

- Cuando la hora elegida ya no está libre se ofrecen las alternativas reales más próximas.

### Errores corregidos

- ADI ya no responde con horarios antiguos: informa la atención presencial oficial, la hora límite para solicitar citas y la atención virtual, y comprueba en la agenda real la hora que pide el cliente.
- Reprogramar una cita a una hora ocupada muestra el aviso correspondiente en lugar de un error interno.

## v1.5.112 — 2026-10-12 18:49 (UTC-05:00)

Horarios centralizados y ADI con horarios vigentes

### Nuevas funcionalidades

- Horarios centralizados: Configuración → Horarios y Disponibilidad con la atención presencial oficial (lunes a viernes 7:45 a. m.–8:30 p. m., sábado 9:00 a. m.–9:00 p. m., domingo 10:00 a. m.–5:00 p. m.), atención virtual 24/7, mensaje fuera de horario y cierres extraordinarios.

### Mejoras realizadas

- ADI responde los horarios con los datos vigentes del sistema: distingue atención presencial, citas y atención virtual, y dice si el taller está abierto ahora (hora de Ecuador).
- La página de citas muestra el horario presencial, el estado actual y la atención virtual.

## v1.5.111 — 2026-10-12 18:43 (UTC-05:00)

Auditoría del asistente de redacción de ADI

### Mejoras realizadas

- Asistente de redacción de ADI más compacto: usa el ancho del campo, muestra las herramientas en hasta cuatro columnas y la vista previa ofrece «Aplicar cambios», «Regenerar» y «Cancelar».
- El editor de «Nuevo mensaje» empieza más bajo y crece con el texto.

### Errores corregidos

- En «Nuevo mensaje», el panel de ADI ya no queda tapado por la barra de acciones: la casilla y los botones se ven completos en escritorio y móvil.

### Actualizaciones de seguridad

- ADI ya no corrige automáticamente el texto legal de las condiciones: allí solo actúa a petición y con vista previa.

## v1.5.110 — 2026-10-12 18:25 (UTC-05:00)

Actualizaciones automáticas en la pantalla de acceso

### Nuevas funcionalidades

- La pantalla de acceso detecta sola las versiones nuevas: comprueba al abrir, cada cinco minutos y al volver a la pestaña; carga la versión nueva automáticamente si el formulario está vacío (una sola vez, sin bucles) o muestra «Nueva versión» con el botón para recargar.

### Mejoras realizadas

- El manifiesto de versión incluye el identificador de compilación del despliegue y la hora real de la última comprobación.

## v1.5.109 — 2026-10-12 18:21 (UTC-05:00)

Seguimiento de Órdenes en tabla compacta con filtro desde las tarjetas de estado

### Mejoras realizadas

- Seguimiento de Órdenes como tabla compacta: una fila por orden, búsqueda siempre visible, filtros avanzados desplegables con etiquetas retirables e historial bajo cada fila; en teléfonos cada fila se muestra como ficha.
- Las seis tarjetas de estado del inicio filtran la tabla de seguimiento y actualizan sus totales con cada sincronización; se eliminaron los contadores duplicados.

## v1.5.108 — 2026-10-12 18:14 (UTC-05:00)

Gestión documental de las Condiciones y rótulo del inicio

### Nuevas funcionalidades

- Condiciones del servicio con gestión documental: numeración automática de versiones, borrador pendiente de aprobación con aviso a administración, comparación resaltada con la versión vigente e historial con responsable, motivo y cambios de cada versión.

### Mejoras realizadas

- Rótulo del inicio renovado: «PC-DOCTOR S.A. — Plataforma de Gestión Técnica».
- El Seguimiento de Órdenes del inicio ya no repite los contadores que muestran las tarjetas de estado.

## v1.5.107 — 2026-10-12 18:03 (UTC-05:00)

Seguimiento de Órdenes agrupado por orden

### Nuevas funcionalidades

- Seguimiento de Órdenes con contadores reales por estado, línea de etapas basada en el historial, buscador, filtros por estado, técnico y fecha, historial desplegable, paginación y sincronización periódica con aviso de cambios de estado.

### Mejoras realizadas

- Seguimiento de Órdenes rediseñado: una tarjeta por orden con su último movimiento (sin órdenes repetidas), cliente, equipo, estado, técnico responsable, fecha y hora exactas, tiempo transcurrido y prioridad.

## v1.5.106 — 2026-10-12 17:56 (UTC-05:00)

Acceso rediseñado y «Versión del sistema» con comprobación real

### Nuevas funcionalidades

- «Versión del sistema» sustituye a «Release»: versión instalada, fecha de publicación y estado comprobado en el servidor (actualizado, actualización disponible o importante, error con reintento, o recarga necesaria).
- Ventana «Ver novedades» con las notas de la versión por categorías, compatibilidad y acceso al historial de versiones.

### Mejoras realizadas

- Pantalla de acceso con nuevas proporciones: tarjeta de 440 px, logo de 105 px, título de 26 px, campos y botón de 48 px y menos espacios vacíos.
- Se retiró la casilla «Auto» de la ventana de nueva orden.

## v1.5.105 — 2026-10-12 17:49 (UTC-05:00)

Esfera viva y ventana premium de ADI

### Mejoras realizadas

- Esfera de ADI con más vida: filamentos de energía, núcleo que cambia de forma, ondas en la superficie, respiración asimétrica, levitación leve, onda al toque y reacción suave al cursor.
- Ventana de ADI rediseñada: 410 px, esfera 3D en el encabezado, mensajes a 14 px con burbujas diferenciadas, botón para copiar respuestas, indicador «ADI está procesando tu consulta…», aviso de desconexión con «Reintentar» y controles reorganizados.
- «Solicitar un asesor» pasa a llamarse «Contactar soporte técnico»; la conversación ya no salta mientras se relee.

## v1.5.104 — 2026-10-12 17:42 (UTC-05:00)

Registro público cerrado, cuentas por administración y ADI en espera

### Nuevas funcionalidades

- Gestión de Usuarios y Accesos: crear cuentas con invitación por correo y enlace temporal de un solo uso para que cada persona establezca su contraseña, restablecer accesos y registro de creación y activación en la auditoría.

### Mejoras realizadas

- ADI: nueva preferencia «Animaciones de la esfera»; se retira «Abrir el chat al entrar».

### Errores corregidos

- ADI permanece en espera al abrir, recargar o cambiar de sección: no se abre, no habla ni activa el micrófono por sí sola.

### Actualizaciones de seguridad

- Se retiró el registro público de cuentas: desaparecen el enlace «Solicitar acceso», la página pública /registro y el alta por la API. Solo administración crea cuentas, con permisos comprobados en el servidor.

## v1.5.103 — 2026-10-12 17:36 (UTC-05:00)

Esfera 3D de ADI en WebGL y título «Órdenes de Reparación»

### Nuevas funcionalidades

- Esfera de ADI en 3D real (WebGL): cristal rosado con reflejos de entorno, refracción, núcleo de energía y partículas interiores, con giro propio y reacción a cada estado (toque, escucha, procesamiento, habla y desconexión).

### Mejoras realizadas

- ADI sin anillos decorativos, con un indicador de conexión pequeño y discreto; alternativa ligera automática cuando el equipo no tiene aceleración gráfica; en teléfonos la esfera del acceso ya no tapa el botón «Iniciar sesión».
- El módulo pasa a titularse «Órdenes de Reparación».

## v1.5.102 — 2026-10-12 17:27 (UTC-05:00)

Condiciones oficiales vigentes en el detalle de la orden

### Mejoras realizadas

- Condiciones del servicio: publicada la versión oficial 2026.10.1 (vigente desde el 12/10/2026). Las órdenes sin aceptación registrada enlazan a la versión vigente en lugar del borrador, sin atribuirles aceptación.

### Actualizaciones de seguridad

- El proceso programado de avisos solo responde a la llamada autenticada de la plataforma.

## v1.5.101 — 2026-10-12 14:31 (UTC-05:00)

Correo de verificación corporativo, recuperación fiable en Vercel y permanencia vencida

### Nuevas funcionalidades

- Órdenes: filtro «Plazo de permanencia vencido», enlazado desde la alerta; Centro de Control Técnico: indicador «Permanencia vencida».
- Proceso programado diario para los avisos de mantenimiento y de permanencia (no envía nada mientras estén apagados).

### Mejoras realizadas

- Correos con código de verificación con plantilla corporativa: logo, título «Verifica tu correo electrónico», código destacado, validez real, aviso de seguridad y versión en texto plano; asunto «Tu código de verificación | PC-DOCTOR S.A.» y remitente «PC-DOCTOR S.A. · Seguridad».

### Errores corregidos

- El correo de recuperación de contraseña y el aviso de cambio se envían de verdad en Vercel: la función espera al envío antes de responder.

### Actualizaciones de seguridad

- Cada envío de código queda auditado (enviado o fallido) sin guardar el código.

## v1.5.100 — 2026-10-12 14:22 (UTC-05:00)

Esfera de cristal realista y efectos de sonido de ADI

### Nuevas funcionalidades

- Efectos de sonido de ADI: tono de cristal ascendente con destello al abrir, descendente al cerrar, señal al activar el micrófono y aviso de respuesta; se activan o desactivan en «Efectos de sonido» y nunca suenan solos ni sobre la voz.

### Mejoras realizadas

- Esfera de ADI con material de cristal realista: volumen, bordes sombreados, neblina luminosa interior, reflejos de superficie, filo fino y sombra de apoyo; el texto «ADI» queda integrado dentro del cristal.

## v1.5.99 — 2026-10-12 14:16 (UTC-05:00)

Esfera de ADI con más brillo, halo, cristal y anillos

### Mejoras realizadas

- Esfera de ADI más luminosa: halo rosado difuminado, cristal con reflejos y más profundidad, dos anillos finos, puntos de energía en órbita, texto «ADI» más nítido e indicador verde con borde oscuro y resplandor.

## v1.5.98 — 2026-10-12 14:09 (UTC-05:00)

Esfera premium de ADI con anillo, letras y estados reales

### Nuevas funcionalidades

- Ventana «ADI · Asistente Inteligente» con botón para detener la voz mientras ADI habla.

### Mejoras realizadas

- Esfera premium de ADI: cristal rosa con reflejos, letras «ADI» centradas, anillo exterior luminoso de giro lento y tamaño adaptado (62 px en escritorio, 54 px en móvil).
- Animaciones ligadas al estado real: anillos que siguen el volumen del micrófono en computadoras, partículas al procesar, latido por palabra al hablar y esfera apagada sin indicador verde cuando no hay conexión.

## v1.5.97 — 2026-10-12 14:04 (UTC-05:00)

Voz de ADI: velocidad, pronunciación del nombre y fluidez

### Nuevas funcionalidades

- Mientras ADI habla, el botón de voz la interrumpe; nueva frase de muestra de voz y preferencia por voz femenina también en el asistente interno.

### Mejoras realizadas

- Voz de ADI más fluida: velocidad inicial de 1,12× ajustable desde su menú, lectura por frases que empieza en cuanto llega la respuesta y sin pausas por símbolos.

### Errores corregidos

- ADI pronuncia «PC-DOCTOR S.A.» como «Pe ce dóctor, ese a» sin leer guiones; el nombre oficial no cambia en pantalla, documentos ni registros.

## v1.5.96 — 2026-10-12 13:59 (UTC-05:00)

Esfera rosa de ADI con estados reales y muestra de voz

### Nuevas funcionalidades

- Voz de ADI: botón «Escuchar muestra de voz» y nuevo saludo «Bienvenido a Órdenes Pro. Soy Adi, tu asistente virtual. ¿En qué puedo ayudarte?».

### Mejoras realizadas

- ADI estrena esfera rosa pastel: circular, con degradado, brillo, ondas de energía interiores y respiración suave; la ventana de conversación incorpora detalles rosados y el botón «Comenzar conversación».
- Estados de la esfera ligados a señales reales: escuchando (reacciona cuando el micrófono detecta voz), procesando, hablando y error.

## v1.5.95 — 2026-10-12 13:54 (UTC-05:00)

Título «Agendamiento de Citas Técnicas» en la agenda pública

### Mejoras realizadas

- La agenda pública de citas pasa a titularse «Agendamiento de Citas Técnicas» (título de la página y de la pestaña).

## v1.5.94 — 2026-10-12 13:48 (UTC-05:00)

ADI en la pantalla de inicio de sesión y consulta de reparación con código temporal

### Nuevas funcionalidades

- ADI en la pantalla de inicio de sesión: acoplada a la derecha del acceso en escritorio y como orbe flotante en móvil, con acciones rápidas para agendar cita, consultar una reparación, conocer los servicios y hablar con un asesor.

### Actualizaciones de seguridad

- Consultar una reparación desde ADI exige un código temporal de 6 dígitos enviado al correo registrado en la orden: conocer el número de orden ya no basta, y la respuesta no revela si la orden existe.

### Optimización del rendimiento

- ADI se carga después del formulario de acceso y no consulta al servidor mientras no haya conversación.

## v1.5.93 — 2026-10-12 13:37 (UTC-05:00)

Avisos de permanencia por correo, apagados por defecto

### Nuevas funcionalidades

- Avisos de permanencia por correo al cliente (a los 60, 75, 85 y 90 días del ingreso), apagados hasta que administración los activa; antes de activarlos se ve a qué órdenes llegarían.
- Registro de cada aviso de permanencia (etapa, destinatario, resultado e identificador del mensaje) en la orden y en su historial; sin repeticiones y suspendidos al entregar el equipo.

## v1.5.92 — 2026-10-12 13:32 (UTC-05:00)

Permanencia en taller y control de retiro: columna, detalle, alerta e informe

### Nuevas funcionalidades

- Permanencia en taller: nueva columna en Órdenes con días transcurridos y restantes, barra de avance y nivel (dentro del plazo, recordatorio preventivo, próximo al vencimiento, plazo vencido) frente a un plazo administrativo de 90 días configurable.
- Detalle de la orden con tarjeta de permanencia (ingreso, plazo, tiempo total, días sobre el plazo y quién registró la entrega) e informe de permanencia en PDF.
- Centro de Actividad avisa cuando hay equipos sin retirar que superaron el plazo. El estado de la orden nunca cambia por sí solo.

### Actualizaciones de seguridad

- Revertir una entrega registrada queda reservado a administración y se audita.

## v1.5.91 — 2026-10-12 13:19 (UTC-05:00)

Centro de Seguimiento Técnico y efecto rojo al cerrar

### Mejoras realizadas

- El panel del inicio pasa a llamarse «Centro de Seguimiento Técnico», con subtítulo e icono de seguimiento
- Todos los botones de cierre (X) de ventanas, avisos y paneles muestran el mismo efecto rojo al pasar el cursor y al pulsarlos

## v1.5.90 — 2026-10-12 13:14 (UTC-05:00)

Corrección del bloqueo de Aplicar mejora en ADI

### Mejoras realizadas

- ADI: un vigilante impide que el indicador gire sin fin y los pasos del asistente quedan registrados para diagnóstico, sin guardar el texto escrito

### Errores corregidos

- ADI: «Aplicar mejora» ya no queda esperando detrás de la revisión automática; la base de datos se libera antes de llamar a la IA (también en el chat público y en el correo), con lo que tampoco se frenan otros guardados

## v1.5.89 — 2026-10-12 09:18 (UTC-05:00)

Avatar con logo más legible

### Mejoras realizadas

- El avatar con foto o logo luce un aro luminoso y fondo claro circular, para que un logo se lea bien sin cambiar de tamaño

## v1.5.88 — 2026-10-12 09:14 (UTC-05:00)

Correo de recuperación y nuevos tipos de equipo

### Nuevas funcionalidades

- Nuevos tipos de equipo con icono propio: Tablet, Celular, Router / equipo de red y Servidor

### Errores corregidos

- El correo de recuperación de contraseña usa el correo del sistema cuando no hay un SMTP propio; en Configuración deja de aparecer como pendiente

## v1.5.87 — 2026-10-12 09:05 (UTC-05:00)

ADI en el chat de atención

### Mejoras realizadas

- ADI corrige también la ortografía de las respuestas en el chat de atención en vivo, sin enviar nada por sí sola

## v1.5.86 — 2026-10-12 09:00 (UTC-05:00)

Foto de perfil

### Nuevas funcionalidades

- Foto de perfil: cada persona puede poner, cambiar o quitar la suya desde el menú de su cuenta; se muestra en el encabezado

## v1.5.85 — 2026-10-12 08:52 (UTC-05:00)

Recordatorios de mantenimiento para todos los clientes con correo

### Mejoras realizadas

- Los recordatorios de mantenimiento se envían a todos los clientes con correo, salvo a quienes se dieron de baja; cada correo incluye el enlace para dejar de recibirlos

## v1.5.84 — 2026-10-12 08:41 (UTC-05:00)

Recordatorios de mantenimiento con enlace seguro

### Nuevas funcionalidades

- Recordatorios de mantenimiento por correo a 30, 15, 7, 3 y 0 días, con enlace seguro para que el cliente confirme la fecha, pida otro horario o deje de recibirlos

### Mejoras realizadas

- Las respuestas de los clientes sobre su mantenimiento aparecen en Próximos Mantenimientos y en el Centro de Actividad; los recordatorios vienen apagados y solo se envían con consentimiento

## v1.5.83 — 2026-10-12 08:29 (UTC-05:00)

Adjuntos del correo mejorados

### Mejoras realizadas

- Mail Pro: adjuntos con barra de capacidad, lista con quitar, arrastrar y soltar y compresión ZIP opcional en el navegador

### Errores corregidos

- Mail Pro: los borradores ya conservan sus adjuntos, y el límite pasa a 3,1 MB, que es lo que admite realmente la infraestructura (3,5 MB podía fallar)

## v1.5.82 — 2026-10-12 08:23 (UTC-05:00)

Autorización digital del cliente por enlace seguro

### Nuevas funcionalidades

- Autorización digital del cliente por enlace seguro: identificación enmascarada, últimos cuatro dígitos, código temporal por correo, aceptar o rechazar cada autorización, comprobante PDF con huella y aviso al correo administrativo

### Mejoras realizadas

- El envío automático del enlace al registrar una orden viene apagado y solo administración puede activarlo

## v1.5.81 — 2026-10-12 08:12 (UTC-05:00)

Estados visibles en la esfera de ADI

### Mejoras realizadas

- Esfera de ADI: respiración luminosa en reposo, destello al procesar y al responder, y estado de error propio, además de escuchando y hablando

## v1.5.80 — 2026-10-12 08:08 (UTC-05:00)

Botón Próximo mantenimiento

### Errores corregidos

- El botón «Próximo mantenimiento» del detalle de la orden ya no queda con aspecto de carga antes de la entrega: siempre responde y explica cuándo se programa

## v1.5.79 — 2026-10-12 07:59 (UTC-05:00)

Módulo Órdenes: búsqueda, filtros y acciones

### Mejoras realizadas

- Órdenes: buscador mientras se escribe (con lupa y limpiar) que actualiza solo los resultados; filtros en una fila con avanzados desplegables y filtros activos retirables
- Órdenes: acciones compactas (Ver orden, Ticket y menú de tres puntos agrupado que se abre hacia donde hay espacio), columnas ajustadas y paginación compacta

### Errores corregidos

- Órdenes: «Solo activas» filtra al instante al marcar o desmarcar, combinado con los demás filtros

## v1.5.78 — 2026-10-12 07:47 (UTC-05:00)

Documento de condiciones rediseñado

### Nuevas funcionalidades

- PDF oficial de cada versión publicada de las condiciones y nombres de archivo correctos (definitivo y borrador)

### Mejoras realizadas

- Documento «CONDICIONES DE RECEPCIÓN Y SERVICIOS» rediseñado en una página A4, con apartados numerados, aviso de borrador y cierre con versión y huella
- El botón del detalle de la orden pasa a ser «Compartir condiciones del servicio» y comparte el archivo que corresponde

## v1.5.77 — 2026-10-12 07:40 (UTC-05:00)

Botón Volver unificado

### Mejoras realizadas

- El enlace «Volver» de todos los módulos es ahora un botón compacto con flecha, coherente con el tema

## v1.5.76 — 2026-10-12 07:32 (UTC-05:00)

Centro de Actividad pulido

### Mejoras realizadas

- Centro de Actividad con más jerarquía y aire: tarjetas de resumen más claras, secciones separadas, elementos sin leer destacados, ancho completo y microanimaciones suaves (mismo tema)

## v1.5.75 — 2026-10-12 07:28 (UTC-05:00)

Ventana Nuevo mensaje reorganizada

### Mejoras realizadas

- Mail Pro · Nuevo mensaje: CC y CCO en una fila, asunto destacado, barra de formato unida al editor con ADI integrada, firma y adjuntos compactos y botones Enviar siempre visibles

### Errores corregidos

- Mail Pro: la copia oculta (CCO) ya se conserva al guardar un borrador y reabrirlo

## v1.5.74 — 2026-10-12 07:19 (UTC-05:00)

Destello al corregir con ADI

### Mejoras realizadas

- Destello azul celeste breve sobre el campo cuando ADI aplica una corrección ortográfica (respeta movimiento reducido)

## v1.5.73 — 2026-10-12 07:17 (UTC-05:00)

Corrección ortográfica automática de ADI sin ventanas

### Mejoras realizadas

- ADI corrige la ortografía sola 1,5 s después de dejar de escribir, sin ventana de confirmación, conservando el cursor y con «Deshacer»
- ADI no aplica correcciones que alterarían cifras, códigos o series, y no actúa sobre texto citado en los correos

## v1.5.72 — 2026-10-12 07:11 (UTC-05:00)

Equipos con historial técnico

### Nuevas funcionalidades

- Equipos: registro con icono por tipo, órdenes acumuladas y último estado, buscador por serie, cliente, marca o modelo, filtros y botón «Historial técnico» con todas las reparaciones del equipo

### Mejoras realizadas

- Equipos: aviso de números de serie repetidos entre equipos, sin fusionar ni borrar nada
- Nuevo asunto del correo de recepción: «PC-DOCTOR S.A. | Confirmación de recepción — Orden N.º …»

## v1.5.71 — 2026-10-12 07:04 (UTC-05:00)

Distribución compacta del módulo Correo

### Mejoras realizadas

- Mail Pro más compacto y legible con el mismo tema: todas las carpetas visibles sin desplazamiento, capacidad del buzón en una línea y más mensajes a la vista en escritorio y móvil

## v1.5.70 — 2026-10-12 06:59 (UTC-05:00)

Aviso de autorizaciones al correo administrativo

### Nuevas funcionalidades

- Aviso automático al correo administrativo cada vez que se registra una autorización, con el estado real de cada apartado y enlace a la orden; sin duplicados y con constancia del resultado

## v1.5.69 — 2026-10-12 06:52 (UTC-05:00)

Corrección del movimiento y la eliminación de correos

### Mejoras realizadas

- Mail Pro: modal propio «Confirmar eliminación de mensaje» que espera la respuesta del servidor, y avisos claros cuando un mensaje no se puede mover

### Errores corregidos

- Mail Pro: mover, archivar, enviar a Spam o a la Papelera y eliminar vuelven a funcionar en producción (el sistema no leía las capacidades del servidor tras iniciar sesión)

## v1.5.68 — 2026-10-12 06:46 (UTC-05:00)

Eliminar correos desde el mensaje abierto

### Mejoras realizadas

- Mail Pro: la eliminación definitiva se confirma con el diálogo del sistema y la barra del mensaje se acomoda en móvil

### Errores corregidos

- Mail Pro: el mensaje abierto ya tiene botón Eliminar (envía a la Papelera, con Deshacer); en la Papelera permite restaurar o eliminar definitivamente

## v1.5.67 — 2026-10-12 06:37 (UTC-05:00)

Decisión propia para archivos y respaldos

### Nuevas funcionalidades

- Archivos y respaldos tienen su propia decisión en recepción: autorizado, no autorizado (rechazo expreso) o pendiente; se refleja en la confirmación, el detalle, el comprobante A4 y el ticket

## v1.5.66 — 2026-10-12 00:42 (UTC-05:00)

Diagnóstico de ADI en el registro del servidor

### Mejoras realizadas

- Diagnóstico de ADI: el registro del servidor anota cada revisión completada, la propuesta mostrada y su aceptación (sin el texto del usuario)

## v1.5.65 — 2026-10-12 00:38 (UTC-05:00)

Listado de órdenes compacto con iconos de estado

### Mejoras realizadas

- Listado de órdenes más compacto en escritorio, tableta y móvil, con icono propio para cada estado (mismos nombres y colores)

## v1.5.64 — 2026-10-12 00:33 (UTC-05:00)

Autorizaciones con estado visible en recepción y en el comprobante A4

### Mejoras realizadas

- Autorizaciones de recepción en tres apartados con estado visible: AUTORIZADO (verde), NO AUTORIZADO (rojo) y PENDIENTE (gris), sin cambiar lo que se guarda
- El comprobante A4 incluye «Autorizaciones del cliente» con indicadores estáticos legibles en blanco y negro, fecha, hora y responsable

## v1.5.63 — 2026-10-12 00:26 (UTC-05:00)

Iluminación suave al cambiar el estado de una orden

### Mejoras realizadas

- Al cambiar el estado de una orden, su etiqueta se ilumina suavemente una vez (respeta movimiento reducido)

## v1.5.62 — 2026-10-12 00:23 (UTC-05:00)

Bandeja de conversaciones del Centro de Atención

### Mejoras realizadas

- Centro de Atención como bandeja: búsqueda, filtros con contador, orden vinculada con su estado y mensajes sin leer destacados
- Sin conversación abierta se muestra un resumen de atención en lugar de paneles vacíos; aviso cuando escribe un cliente que espera a un asesor

## v1.5.61 — 2026-10-12 00:16 (UTC-05:00)

Buscador global tolerante a errores, con sugerencias y resaltado

### Mejoras realizadas

- Buscador global: resultados al instante por cliente, marca, modelo, serie y número de orden, sin distinguir tildes y con varias palabras en cualquier orden
- El buscador tolera errores de escritura, sugiere «¿Quisiste decir…?» y resalta el texto encontrado

## v1.5.60 — 2026-10-12 00:11 (UTC-05:00)

ADI propone las correcciones de ortografía de forma visible

### Mejoras realizadas

- ADI cancela la revisión en curso si sigues escribiendo, no repite consultas del mismo texto y explica el motivo cuando una revisión falla

### Errores corregidos

- La corrección automática de ADI ahora se ve: avisa «Analizando texto…» y propone la corrección bajo el campo con Aceptar y Descartar, 1,5 s después de dejar de escribir

## v1.5.59 — 2026-10-12 00:03 (UTC-05:00)

Centro de Control Técnico con gráficos y filtros

### Nuevas funcionalidades

- Centro de Control Técnico con gráficos reales: dona por estado, órdenes por periodo, evolución de órdenes abiertas, productividad por técnico y tipos de equipo
- Filtros por periodo, fechas, estado, tipo de equipo y técnico; al pulsar un indicador o segmento se listan sus órdenes

### Mejoras realizadas

- El tablero se actualiza solo cada 20 segundos e indica la última consulta o la falta de conexión

## v1.5.58 — 2026-10-11 23:53 (UTC-05:00)

Comprobante A4 en dos páginas, nombres de PDF y voz de ADI

### Mejoras realizadas

- Comprobante A4 rediseñado en dos páginas, con constancia de recepción y Políticas de Reparaciones en dos columnas (texto literal)
- Los PDF se descargan con nombre automático: CÓDIGO-TICKET.pdf y CÓDIGO-COMPROBANTE-DE-RECEPCION.pdf
- ADI elige una voz femenina en español (preferencia por acento colombiano) y permite escoger la voz desde su menú
- El módulo de reportes se titula CENTRO DE CONTROL TÉCNICO

## v1.5.57 — 2026-10-11 23:37 (UTC-05:00)

Iconos por tipo de equipo y por módulo

### Nuevas funcionalidades

- Iconos por tipo de equipo: portátil, portátil gaming, escritorio, todo en uno, mini PC, impresora, consola y equipo genérico, asignados según el tipo guardado y visibles en el listado, el detalle y la recepción

### Mejoras realizadas

- Cada módulo tiene su propio icono junto al título; el menú resalta el módulo activo e ilumina el icono al pasar el cursor

## v1.5.56 — 2026-10-11 23:34 (UTC-05:00)

Voz de ADI: escucha y responde hablando

### Nuevas funcionalidades

- ADI habla: micrófono para dictar la pregunta y respuesta leída con voz femenina en español, con interruptor de voz y la esfera animada mientras escucha, procesa y habla

### Mejoras realizadas

- El nombre del asistente se muestra siempre como «ADI»; mensajes claros si el micrófono está bloqueado, no hay micrófono o el navegador no admite dictado

## v1.5.55 — 2026-10-11 23:27 (UTC-05:00)

Indicador de estado en la vista previa del ticket

### Mejoras realizadas

- Vista previa de documentos: la franja roja se sustituye por un indicador azul con brillo mientras se genera y verde con visto y «Ticket listo» al terminar; ámbar si falla

## v1.5.54 — 2026-10-11 23:23 (UTC-05:00)

Ticket térmico compacto

### Mejoras realizadas

- Ticket térmico más compacto y moderno: franja de título, QR junto a la fecha y el estado, cliente y equipo en columnas alineadas, párrafos justificados y firmas en un mismo renglón; un 20 % más corto con el mismo contenido

## v1.5.53 — 2026-10-11 23:17 (UTC-05:00)

Avisos emergentes menos intrusivos

### Mejoras realizadas

- Notificaciones: como mucho dos avisos emergentes a la vez y varias novedades juntas se resumen en un solo aviso que abre el panel, para no tapar el encabezado ni los botones

## v1.5.52 — 2026-10-11 23:12 (UTC-05:00)

Adi: «Aplicar mejora» con tiempo límite y panel compacto dentro del formulario

### Mejoras realizadas

- Adi: la corrección automática y la mejora manual ya no se pisan, el estado se consulta una vez por página y los fallos del navegador quedan en el registro del servidor para diagnosticarlos

### Errores corregidos

- Adi: «Aplicar mejora» ya no puede quedarse cargando sin fin: tiempo límite de 20 segundos, un solo envío por pulsación, mensaje de error con reintento y el texto original siempre intacto
- Adi: el panel de redacción heredaba la posición y el alto fijo del chat flotante, se montaba sobre la ventana y recortaba su contenido; ahora va dentro del formulario, mide 380 px y tiene desplazamiento interno

## v1.5.51 — 2026-10-11 22:54 (UTC-05:00)

Rediseño completo de Detalle de la Orden

### Mejoras realizadas

- Detalle de la Orden: secciones compactas y uniformes con icono, datos vacíos atenuados, Seguimiento y Presupuesto en filas etiqueta–valor y acciones de documentos más ordenadas

### Errores corregidos

- Detalle de la Orden: el estado del comprobante por correo aparecía duplicado; el historial de envíos queda plegado. En móvil las secciones y los filtros del historial ya no se salen del ancho

## v1.5.50 — 2026-10-11 22:49 (UTC-05:00)

Corrección ortográfica automática de Adi y estrellita animada

### Nuevas funcionalidades

- Adi: corrección ortográfica automática dos segundos después de dejar de escribir; aplica solo las correcciones simples sin mover el cursor y deja como sugerencia por aprobar lo que cambie el sentido

### Mejoras realizadas

- Adi: la estrellita se ilumina mientras analiza, destella al terminar y muestra «Texto mejorado» con opción de deshacer; más contextos de redacción (citas, mensajes, correo, garantía, servicios)

### Actualizaciones de seguridad

- Adi: una respuesta antigua nunca sobrescribe texto nuevo; la corrección automática tiene su propio límite de uso y no actúa sobre las autorizaciones del cliente

## v1.5.49 — 2026-10-11 22:39 (UTC-05:00)

Detalle de la Orden: recuadro del título corregido y cabecera compacta

### Mejoras realizadas

- Detalle de la Orden: cabecera más compacta, con «Volver a órdenes» como botón y título y subtítulo en un bloque corto

### Errores corregidos

- Detalle de la Orden: al recargar la página con el teclado aparecía un recuadro blanco alrededor del título; era el contorno de foco del encabezado y ya no se dibuja

## v1.5.48 — 2026-10-11 22:36 (UTC-05:00)

Asistente ADI rediseñado y disponible en todos los campos de texto

### Nuevas funcionalidades

- Adi en todo el sistema: cada área de texto (órdenes, citas, WhatsApp, autorizaciones, correo de Mail Pro y demás) tiene su botón para corregir o mejorar el texto

### Mejoras realizadas

- Adi: nuevo panel «Asistente ADI» con herramientas en cuadrícula, «Aplicar mejora» con indicador de proceso, vista previa con cambios resaltados y opciones para aceptar, regenerar o descartar

## v1.5.47 — 2026-10-11 22:30 (UTC-05:00)

Módulo Próximas Entregas

### Nuevas funcionalidades

- Próximas Entregas: módulo propio solo con equipos terminados, resumen por estado de entrega, filtros (estado, técnico, fechas, búsqueda), tarjetas con acciones rápidas y paginación
- Entregas: «Entregar equipo» con confirmación, contacto por WhatsApp, ticket y comprobante desde la tarjeta; aviso interno cuando un equipo queda listo para entregar

## v1.5.46 — 2026-10-11 22:24 (UTC-05:00)

Adi lee la clave de OpenAI y el comprobante se envía desde el servidor

### Nuevas funcionalidades

- Configuración: «Notificaciones automáticas por correo» con correo de prueba al buzón del sistema e historial de envíos con sus errores

### Mejoras realizadas

- Comprobante por correo: el servidor lo envía al guardar la orden, con el nuevo asunto y texto, y el PDF incluye las autorizaciones registradas

### Errores corregidos

- Adi: la clave de OpenAI se había guardado en el servidor con el nombre OPEN_API_KEY y no se leía; ahora se acepta también ese nombre

## v1.5.45 — 2026-10-11 20:05 (UTC-05:00)

Centro de Atención en Tiempo Real

### Nuevas funcionalidades

- Centro de Atención en Tiempo Real: consola de tres paneles con lista de conversaciones y estados reales, conversación con burbujas por autor y panel con el cliente y la orden vinculados
- Atención: vincular una conversación a una orden y su cliente (se sugiere la orden que el cliente menciona), reabrir conversaciones cerradas, pestaña de cerradas e indicador de conexión

### Mejoras realizadas

- Atención: mensajes sin leer, avisos de conversación nueva, acciones con confirmación y textos «Cliente», «Adi» y «Asesor» en lugar de identificadores internos

## v1.5.44 — 2026-10-11 19:58 (UTC-05:00)

Esfera de Adi y mensajes de WhatsApp con número validado

### Nuevas funcionalidades

- Orden: «Mensaje por WhatsApp» con siete mensajes preparados (recepción, diagnóstico, presupuesto, autorización, listo para retirar, recordatorio de pago y seguimiento) que se abren en WhatsApp para revisarlos y enviarlos

### Mejoras realizadas

- Adi: el botón flotante es ahora una esfera holográfica circular, con brillo suave, halo al señalarla y pulsos de luz solo mientras procesa una consulta real

### Errores corregidos

- WhatsApp: el número se normaliza siempre al formato internacional sin duplicar el 593 (09…, +593…, 00593…, con espacios o guiones) y se avisa si falta, está incompleto o es un fijo, en lugar de abrir un enlace inválido

## v1.5.43 — 2026-10-11 19:48 (UTC-05:00)

Autorizaciones de operaciones de riesgo rediseñadas y visibles en el detalle de la orden

### Nuevas funcionalidades

- Orden: el detalle muestra las autorizaciones registradas en la recepción, las operaciones autorizadas una a una y el historial de decisiones

### Mejoras realizadas

- Recepción: la autorización para operaciones que modifican o eliminan datos se elige en tres tarjetas, con operaciones individuales con icono, unidad afectada (tipo, capacidad, partición y descripción) y aceptación expresa propia

### Actualizaciones de seguridad

- Recepción: cada operación de riesgo se guarda por separado y el servidor rechaza operaciones marcadas sin autorización específica o sin aceptación del cliente

## v1.5.42 — 2026-10-11 19:40 (UTC-05:00)

Borradores de Nueva orden en el servidor

### Nuevas funcionalidades

- Nueva orden: los borradores se guardan en el servidor, con las autorizaciones de acceso y el paso donde quedaste; el botón muestra cambios pendientes, guardando, guardado o error, y hay guardado automático opcional

### Mejoras realizadas

- Nueva orden: tarjeta «Borrador disponible» con fecha y resumen, confirmación propia para descartar y aviso antes de reemplazar lo ya escrito o un borrador más reciente de otra sesión

### Errores corregidos

- Nueva orden: el formulario vacío se consideraba con cambios sin guardar por una opción marcada por defecto

## v1.5.41 — 2026-10-11 19:30 (UTC-05:00)

Recepción: autorización de acceso técnico rediseñada y avisos claros

### Mejoras realizadas

- Recepción: autorización de acceso en grupos compactos, alcance sin casillas premarcadas, campo de archivos solo cuando aplica y operaciones de riesgo (reinstalar, formatear, eliminar, restaurar) en un bloque aparte con confirmación propia

### Errores corregidos

- Recepción: el aviso «destructive_action: Registra alcance y confirmación independiente» mostraba un nombre interno; ahora cada requisito se indica junto a su campo con un texto claro

### Actualizaciones de seguridad

- Recepción: el servidor rechaza descripciones vacías o de una palabra («Sí») para archivos autorizados y operaciones de riesgo

## v1.5.40 — 2026-10-11 19:24 (UTC-05:00)

Agenda de citas con el nuevo diseño

### Mejoras realizadas

- Agenda de citas: nuevo encabezado con resumen y «Nueva cita», filtros rápidos en píldoras con contador, buscador y filas con avatar, iconos de equipo y servicio, día de la semana y acciones destacadas

## v1.5.39 — 2026-10-11 19:09 (UTC-05:00)

Alineación del Centro de Operaciones y nuevo panel Atenciones pendientes

### Mejoras realizadas

- Centro de Operaciones: en monitores anchos el contenido se alinea con el borde izquierdo de la barra superior en lugar de quedar centrado; las tarjetas conservan su tamaño
- Inicio: «Atenciones pendientes» con subtítulo, contadores por color que abren el panel, indicador cuando hay clientes esperando y estado vacío

### Errores corregidos

- Inicio: el resumen de mantenimientos decía «Cita confirmada» para citas aún por confirmar

## v1.5.38 — 2026-10-11 19:04 (UTC-05:00)

Citas de Hoy con carrusel, distintivo Nuevo y cancelaciones en rojo

### Nuevas funcionalidades

- Citas de Hoy: con más de tres citas rota grupos de tres cada 8 segundos en orden cronológico, con controles para avanzar y retroceder e indicador de página; se pausa con el cursor, el foco, un diálogo abierto o la pestaña inactiva

### Mejoras realizadas

- Citas de Hoy: distintivo «Nuevo» durante un minuto para las citas recién registradas, y las canceladas se muestran en rojo unos segundos antes de retirarse de la lista

## v1.5.37 — 2026-10-11 18:47 (UTC-05:00)

Citas de Hoy compacto y sincronizado, clima con actualización manual y avisos de cambio

### Mejoras realizadas

- Citas de Hoy: estado vacío compacto en una fila con la próxima cita, máximo tres citas con «Ver todas» y actualización cada 15 segundos, al volver a la ventana y al recuperar conexión
- Clima: hora de la última consulta, botón «Actualizar ahora», actualización al recuperar conexión y aviso discreto cuando cambia la condición o la temperatura varía 4 °C o más
- Nueva Cita: texto de la casilla de avisos con nota secundaria y botón de cierre con respuesta roja

### Errores corregidos

- Inicio: «Agendar cita» abre el formulario interno (que permite agendar para hoy) en lugar de la página pública, que solo acepta fechas desde mañana

## v1.5.36 — 2026-10-11 18:34 (UTC-05:00)

Acciones por cita en la Agenda: editar, cancelar y eliminar con auditoría

### Nuevas funcionalidades

- Agenda: cada cita tiene acciones para ver, editar, reprogramar, cancelar y eliminar. Eliminar (solo administración) retira la cita de la agenda activa y conserva su registro de auditoría

### Mejoras realizadas

- Agenda: confirmación propia al cancelar o eliminar una cita en lugar de la ventana del navegador; las citas canceladas se muestran en rojo

### Errores corregidos

- Agenda: la lista ya incluye las citas de mantenimiento programadas a seis meses

## v1.5.35 — 2026-10-11 18:22 (UTC-05:00)

Órdenes sin condiciones publicadas y vinculación automática de la orden en Mail Pro

### Nuevas funcionalidades

- Mail Pro: al elegir al cliente como destinatario se vincula sola su orden en curso; con varias se elige en un selector y las entregadas nunca se proponen. El servidor valida la orden antes de enviar

### Errores corregidos

- Nueva orden: la falta de condiciones del servicio publicadas ya no impide finalizar; el paso Confirmación lo informa como «Sin condiciones activas» y la orden se registra sin aceptación

## v1.5.34 — 2026-10-11 18:12 (UTC-05:00)

Citas para hoy desde el taller y cita automática del mantenimiento al entregar

### Nuevas funcionalidades

- Al entregar una orden se crea automáticamente la cita del mantenimiento preventivo, pendiente de confirmación, vinculada a la orden, el cliente y el equipo; en día no laborable se propone el siguiente día con horario

### Mejoras realizadas

- Citas de Hoy: estado vacío con la próxima cita y accesos a Nueva cita y Ver agenda; el panel se pone al día con la agenda completa al cargar
- Próximos Mantenimientos: colores según la cercanía de la fecha, barra de avance, estado operativo separado y botón Ver cita cuando ya existe la cita

### Errores corregidos

- Citas de Hoy: el personal ya puede registrar y reprogramar citas para el mismo día; antes el formulario interno solo aceptaba fechas desde mañana y ninguna cita nueva podía aparecer en el panel

## v1.5.33 — 2026-10-11 17:56 (UTC-05:00)

QR del seguimiento para el cliente y firma de correo con fondo claro

### Mejoras realizadas

- Firma corporativa de Mail Pro con fondo claro, tanto en la vista previa como en el correo enviado

### Errores corregidos

- Seguimiento para el cliente: ahora muestra el código QR real del enlace, con descarga, reintento y avisos compactos

## v1.5.32 — 2026-10-11 17:51 (UTC-05:00)

Correos de citas al momento, Citas de Hoy en vivo y campana con aviso

### Nuevas funcionalidades

- Correos de citas al momento por Mail Pro: solicitud recibida, confirmación, reprogramación y cancelación, con plantilla HTML, registro y reintento

### Mejoras realizadas

- Citas de Hoy: filas compactas con estado, contador, sincronización cada 30 segundos y apertura del detalle real
- Campana de notificaciones: oscila una vez con halo azul al llegar un aviso nuevo; el contador no se mueve

### Errores corregidos

- Las pruebas automáticas ya no cargan el archivo de credenciales real

## v1.5.31 — 2026-10-11 17:37 (UTC-05:00)

Comprobante con Políticas de Reparaciones y envío por correo

### Nuevas funcionalidades

- Comprobante de recepción A4 con las Políticas de Reparaciones completas y envío automático por correo al registrar la orden, con registro de cada intento y reenvío desde el detalle

## v1.5.30 — 2026-10-11 17:29 (UTC-05:00)

Correcciones de Nueva Cita y de la validación de órdenes; reserva pública por pasos

### Mejoras realizadas

- Reserva pública de citas en cuatro pasos con acciones siempre visibles, marcas con logotipo y confirmación al salir con datos escritos
- Tipos de equipo «All-in-One» y «Mini PC»; títulos «Detalle de la Orden» y «Agregar seguimiento técnico» con contador; botón de cerrar con realce rojo; prueba de conexión de Adi en Configuración

### Errores corregidos

- Nueva Cita: casilla de autorización de tamaño normal, errores bajo cada campo con foco en el primero, encabezado y pie fijos, y tipo de equipo separado de la marca con su logotipo
- Nueva orden: al finalizar o avanzar se indica el paso, el campo y el motivo exactos en lugar de «Revisa los campos señalados»

## v1.5.29 — 2026-10-11 15:40 (UTC-05:00)

Próximos Mantenimientos automáticos al entregar

### Nuevas funcionalidades

- Próximos Mantenimientos: al entregar una orden se crea al instante la previsión a seis meses, con aviso, filtros, datos completos y «Agendar cita» vinculada a la agenda

### Mejoras realizadas

- Avisos internos de mantenimiento preventivo a 30, 15, 7 y 0 días, una sola vez por plazo

## v1.5.28 — 2026-10-11 15:30 (UTC-05:00)

Adi para redacción y citas con clientes de la base de datos

### Nuevas funcionalidades

- Adi — asistencia de redacción: botón «Mejorar con Adi» en los campos de las órdenes con vista previa, cambios resaltados, aplicar, regenerar y cancelar (requiere configurar la clave del proveedor de IA)
- Agenda: «Nueva cita» registra la reserva eligiendo al cliente desde la base de datos, con horarios realmente disponibles

## v1.5.27 — 2026-10-11 15:20 (UTC-05:00)

Agenda de Mantenimientos de Clientes y confirmación de cierre renovada

### Nuevas funcionalidades

- Agenda de Mantenimientos de Clientes: una sola vista para citas en línea y mantenimientos preventivos, con resumen, lista, día, semana y mes, filtros, detalle de la cita e historial de cambios
- Citas en línea: confirmación automática o manual configurable, servicios administrables, «Mantenimiento correctivo», notificación «Ver cita» y aviso por correo al taller

### Mejoras realizadas

- Confirmación propia al cerrar una orden o ficha con cambios sin guardar, con «Seguir editando», «Guardar borrador y cerrar» y «Descartar y cerrar», y aviso del navegador al recargar
- Identificación por serie: mensaje neutro «Equipo nuevo en tu taller» cuando la serie aún no está registrada

## v1.5.26 — 2026-10-11 14:59 (UTC-05:00)

Campana de notificaciones al extremo derecho

### Mejoras realizadas

- Barra superior: la campana de notificaciones pasa al extremo derecho, con una insignia más discreta y microanimaciones al pasar el cursor

## v1.5.25 — 2026-10-11 14:54 (UTC-05:00)

Fecha del día más legible en el inicio

### Mejoras realizadas

- Inicio: la fecha del día se muestra como etiqueta legible con icono de calendario y el día de la semana destacado

## v1.5.24 — 2026-10-11 14:50 (UTC-05:00)

Separadores finos en la barra superior

### Mejoras realizadas

- Barra superior: separadores finos entre Release, el buscador y el reloj, sin mover ningún componente

## v1.5.23 — 2026-10-11 14:46 (UTC-05:00)

Nuevos tipos de equipo Notebook y Consolas, y Portátil (Laptop)

### Mejoras realizadas

- Tipos de equipo: «Portátil (Laptop)» sustituye a «Computadora portátil» y se añaden «Notebook» y «Consolas»
- Seguimiento de Órdenes: más separación entre el título y el subtítulo

## v1.5.22 — 2026-10-11 14:36 (UTC-05:00)

Buscador de órdenes renovado, identificación automática sin pasos manuales y seguimiento con más contraste

### Mejoras realizadas

- Buscador de órdenes del encabezado: muestra completo el número de orden, lupa y limpiar como botones reales, resultados con cliente, equipo y estado, y navegación con teclado
- Seguimiento de Órdenes: icono principal iluminado, acento de color por proceso en cada tarjeta e iconos de «Procesando» y «En espera de entrega» actualizados

### Errores corregidos

- Se retira «Leer del equipo» de la recepción: la identificación queda automática por número de serie, con acceso a la orden anterior del equipo y a quién confirmó sus datos

## v1.5.21 — 2026-10-11 14:24 (UTC-05:00)

Lectura de datos desde el propio equipo y ficha de identificación con origen

### Nuevas funcionalidades

- Leer del equipo: importa fabricante, modelo, serie, procesador, memoria y disco desde el propio equipo, para cualquier marca y sin servicios externos

### Mejoras realizadas

- Identificación de equipos: mensajes breves, ficha con origen e identificación, quién confirmó cada equipo, aviso de series con marcas distintas y logotipos en su color corporativo

## v1.5.20 — 2026-10-11 14:10 (UTC-05:00)

Enterprise Status Pro, corrección de botones de la nueva orden y ajustes del ticket

### Mejoras realizadas

- Seguimiento de Órdenes con Enterprise Status Pro: un color e icono por estado real, pulso del icono principal al llegar un movimiento nuevo e indicador de sincronización con retraso y error
- Ticket térmico: logo original más pequeño en escala de grises y QR con el número de orden integrado justo debajo del número

### Errores corregidos

- Ficha de cliente abierta desde la orden: «Anterior» vuelve a la orden conservando lo escrito, y «Cambios sin guardar» solo aparece con cambios reales
- Nueva orden: tras guardar ya no queda cargado el cliente anterior ni se reactivan botones que debían seguir bloqueados después de un error

## v1.5.19 — 2026-10-11 13:58 (UTC-05:00)

Identificación de equipos con consulta asistida por fabricante y procedencia de los datos

### Nuevas funcionalidades

- Capa de adaptadores oficiales por fabricante; adaptador de Dell TechDirect listo para activarse con credenciales propias

### Mejoras realizadas

- Identificación de equipos: catálogo de 10 fabricantes con consulta manual asistida en su portal oficial, procedencia de marca y modelo guardada y equipos sin duplicar

## v1.5.18 — 2026-10-11 13:47 (UTC-05:00)

Smart Progress Stepper en la nueva orden de recepción

### Mejoras realizadas

- Barra de pasos de la nueva orden: cada paso cambia de color según la validación real (completado, actual, incompleto, error o pendiente), con iconos y línea de avance por etapas validadas

## v1.5.17 — 2026-10-11 13:39 (UTC-05:00)

Verificación de la serie en la página oficial del fabricante

### Mejoras realizadas

- Identificación por serie: cuando el equipo no está en el historial, explica el motivo y ofrece la página oficial de Dell, Lenovo, HP, Apple y ASUS para verificar la serie

## v1.5.16 — 2026-10-11 13:29 (UTC-05:00)

Ticket térmico con QR de seguimiento, logo y copias; página pública de consulta de la reparación

### Nuevas funcionalidades

- Seguimiento público de la reparación por código QR: enlace aleatorio por orden, sin datos personales y revocable

### Mejoras realizadas

- Ticket térmico con logo original, QR de seguimiento centrado, firma y constancia de recepción, y copias cliente, taller o ambas

## v1.5.15 — 2026-10-11 13:21 (UTC-05:00)

Logotipos de marcas en la ficha del equipo

### Mejoras realizadas

- Logotipos de 21 marcas en la ficha del equipo de la recepción (Dell, HP, Lenovo, ASUS, Acer, Apple, Epson y otras)

## v1.5.14 — 2026-10-11 13:09 (UTC-05:00)

Ficha del equipo con logotipo de la marca en la recepción

### Nuevas funcionalidades

- Ficha del equipo en la recepción con el logotipo de la marca (70 × 70 px) e icono genérico cuando no hay archivo

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
