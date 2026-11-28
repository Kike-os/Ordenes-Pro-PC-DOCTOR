# Customer Device Intelligence 4.0

## Entrega local

Candidata de Órdenes Pro **v1.6.6**, sucesora de v1.6.5. Se verificó v1.6.5 y compilación `d6c70a9` en producción y `main` remoto. El respaldo de código previo se generó desde ese commit. Los cambios locales de navegación administrativa anteriores se conservaron. La batería instalada en el repositorio es Battery Health Premium 6.2.

La captura conceptual se usó para la distribución de cabecera, franja de datos, ficha y diagnóstico en dos columnas, secciones de ADI y reemplazo, historial con seguimiento internacional y bloque de accesos inferiores. El segundo cotejo puso el aviso de presupuesto pendiente sobre las etapas y agrupó el indicador con la fecha, los ciclos y las capacidades disponibles. La advertencia roja permanece visible dentro de la tarjeta. El portal presenta registros reales autorizados. Los datos, la etiqueta Battery Health Premium 6.3 y los recursos gráficos de la maqueta no se trasladaron al sistema. Las capturas de aceptación usan datos ficticios.

## Cambios y límites comprobados

- **Seguimiento.** Cabecera compacta y franja de orden, última actualización, entrega estimada si existe y estado. Se reutiliza la barra de seis etapas, su cálculo a partir de estados reales y los avisos. Historial y repuestos conservan su lógica. El QR, el código de barras y el acceso protegido están agrupados al pie.
- **Ficha verificada.** Ficha técnica con ampliación manual. El centro muestra las acciones que corresponden al diagnóstico, reemplazo, garantía, historial, informe y presupuesto autorizado. Los botones existentes de impresión y documentos siguen disponibles.
- **Presupuesto.** La descarga requiere sesión y autorización por orden. Se reutiliza el PDF comercial y se enmascaran identificación y serie. La aprobación directa desde el seguimiento queda pendiente. Los enlaces de aprobación existentes se guardan como huellas, de modo que un enlace anterior no se puede reconstruir. El cliente sigue aprobando por el enlace original enviado y el flujo oficial conserva su evidencia.
- **Batería y reemplazo.** El indicador compartido presenta salud, desgaste y clasificación junto con la medición autorizada. Una alerta de seguridad no queda oculta por una salud alta. El reemplazo usa el repuesto visible y el presupuesto identificados explícitamente, más la instalación y la evaluación registradas. El estado se deriva de esos datos. La comparación usa el mismo indicador para las dos baterías, bajo los permisos de salud y desgaste. El historial solo incluye revisiones autorizadas individualmente.
- **ADI e informe.** La sección ADI usa el asesor de batería existente y hallazgos confirmados y autorizados. El informe agrupa seguimientos técnicos marcados como visibles, omite correcciones sustituidas y muestra garantía solo si está autorizada. Puede descargarse como HTML y aparecer en A4. No se incorporó un nuevo análisis automático de SSD, RAM o BIOS fuera de los seguimientos autorizados existentes.
- **Sincronización.** La ficha y su sección A4 se actualizan por fragmentos y solo sustituyen el contenido cuando cambia la huella. Una interrupción conserva la última ficha válida y muestra un aviso de datos desactualizados. Si vence o se revoca la sesión, se retira la ficha. El seguimiento logístico conserva la actualización existente que recarga al detectar un cambio real de estado.
- **Configuración.** Los controles residen en **Configuración → Portal del cliente**, con un acceso desde Facturación. La configuración por orden permite autorizar informe y presupuesto y vincular el reemplazo al repuesto y presupuesto existentes. Las comprobaciones de pertenencia y visibilidad se aplican en el servidor.

## Archivos

| Archivos | Cambios |
| --- | --- |
| `local/customer_device.py`, `local/app.py` | Proyección, controles por orden, permisos, informe y consulta de presupuesto. |
| `local/order_followups.py`, `local/battery_diagnostics.py` | Selección de seguimientos públicos vigentes y permiso historial por evaluación. |
| `local/order_tracking.py`, `local/client_portal.py` | Cabecera y orden del portal, acceso verificado, códigos e impresión existentes. |
| `local/static/customer-device.css`, `local/static/customer-device.js`, `local/static/ticket.js` | Diseño acotado y aviso de sincronización con datos anteriores. |
| `local/static/app.js` | Configuración administrativa y autorizaciones por orden. |
| `local/tests/test_client_portal.py`, `local/tests/test_customer_device.py` | Regresión de permisos, descarga, sincronización, A4 y capturas. |
| `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, `local/data/releases.json` | Protección permanente y registro de cambios pendientes. |

No se agrega una migración. Los permisos usan `system_state` y la información de batería reutiliza la migración 135. La consulta de esa migración en producción requiere una sesión administrativa. No se escribió en producción. Se cotejaron el SVG y los estilos de batería, las etapas, el componente internacional y el controlador de animación del avión contra la versión v1.6.5.

## Verificación

Pasaron 41 pruebas focalizadas distintas de portal, privacidad, batería, evidencias, historial, A4, identidad y repuestos. Se volvió a ejecutar la comprobación de impresión pública tras conservar el selector del encabezado. También pasaron las comprobaciones de sintaxis y el cotejo del SVG y la animación. Las capturas de Chromium están en `output/customer-device-intelligence-4/` y usan 1920 × 1080, 1366 × 768, 1280 × 720, tableta 768 × 1024 y móvil 390 × 844. Se incluye el recorrido completo en móvil.

## Publicación y reversión

La publicación de v1.6.6 recibió autorización administrativa expresa. Antes de subirla pasaron 22 pruebas de la regresión final y se verificó el respaldo del código de v1.6.5. Antes de desplegar, comprobar nuevamente el número de versión, la compilación y `main` remoto. Verificar el respaldo de producción y conservar el registro de la versión anterior. Después del despliegue, confirmar versión, compilación y acceso verificado con una sesión autorizada. Para revertir, desplegar la compilación anterior. No borrar registros de configuración ni evaluaciones para revertir el código.


## Ajuste posterior de distribución

La especificación anterior del portal se contrastó con la v1.6.6 publicada. En la siguiente candidata, el equipo y la fecha de ingreso se muestran una sola vez en pantalla cuando la ficha verificada contiene esos campos. Si la ficha se desactiva o la sesión vence, vuelve a mostrarse el resumen público original. La impresión A4 conserva su propia presentación y permisos. El cambio reutiliza la actualización parcial del portal.

## Revisión con Battery Health Premium 6.5

El motor compartido conserva la geometría y los umbrales aprobados. La ficha reemplaza solo los bloques que cambian y conserva el nodo del indicador al actualizar un bloque que lo contiene. El motor restaura la fase visual si el navegador reconstruye una animación CSS durante ese movimiento. La ficha de pantalla y su representación A4 se retiran al vencer o revocarse la sesión.

La evaluación en curso se marca expresamente desde Gestión de batería y se guarda en la revisión del diagnóstico. El estado no produce un porcentaje sin medición. Los hallazgos técnicos admiten resolución registrada y el retiro de una alerta sigue exigiendo confirmación y medidas documentadas. Las explicaciones del asesor se construyen con los campos autorizados en la proyección. La configuración del portal agrupa identidad, batería, reemplazo, ADI y documentación.

No hay migraciones nuevas. La aplicación almacena el estado opcional dentro del diagnóstico avanzado existente. Para revertir la candidata, restaurar los archivos de código de la compilación anterior y conservar la base, las revisiones y los permisos vigentes.

## Revisión de sincronización, seguridad y animación

La candidata de Órdenes Pro v1.6.9 parte de v1.6.8, compilación `183253f`. Agrupa las correcciones de Customer Device Intelligence 4.0 y del indicador compartido.

- **Animación.** El brillo animado desplazaba los límites desde los que Chromium escalaba un segmento parcial. Cada segmento usa su borde izquierdo fijo en el SVG como origen de transformación. Se conservan las formas, los cinco segmentos, el terminal, los colores, los umbrales y los perfiles de animación. La administración usa el mismo indicador en las revisiones medidas del historial y la comparación de reemplazo. A4 lo muestra estático.
- **Seguridad.** La tarjeta de la orden recibe el indicador crítico de la revisión vigente incluso al volver a abrir la orden. El portal mantiene visible el aviso crítico cuando muestra una batería afectada. El nombre del hallazgo requiere autorización de seguridad, también en A4. La información interna del diagnóstico permanece bajo los permisos administrativos existentes.
- **Sincronización.** El portal cancela la consulta tras diez segundos sin respuesta o al perder la conexión. Conserva la última ficha válida, informa el estado y vuelve a consultar en el ciclo normal o al recuperar la conexión. La caducidad y revocación siguen retirando la ficha de pantalla y de impresión.
- **Baterías adicionales.** Cada batería recibe una clave opaca estable cuando se guarda la revisión. Reordenar la lista o autorizar otra batería conserva el vínculo con su indicador. Las revisiones anteriores conservan sus valores y siguen siendo legibles. Se confirma antes de retirar una batería de la revisión actual. El flujo individual de instalación y garantía sigue disponible para la batería principal; las adicionales conservan sus mediciones, permisos e historial y aún carecen de ese flujo independiente.

Los cambios de producción se concentran en `local/battery_diagnostics.py`, `local/customer_device.py`, `local/order_battery.py`, `local/static/app.js`, `local/static/battery-widget.js`, `local/static/battery-widget.css` y `local/static/customer-device.js`. Las regresiones se mantienen en `local/tests/`. Se reutilizaron el indicador, las pestañas, la verificación por orden y el render A4 existentes. El logotipo, las etapas, el componente logístico y el avión siguen en sus archivos originales.

La revisión añade una propiedad opcional al diagnóstico guardado. No requiere migraciones, escrituras de despliegue en la base ni cambios en los registros existentes. El respaldo previo de código se generó desde `183253f`. La reversión consiste en desplegar esa compilación y conservar todos los registros y revisiones.

Pasaron 42 comprobaciones focalizadas distintas de batería, ficha verificada, permisos del portal, impresión e identidad. La prueba de alineación reprodujo el desplazamiento original a 320, 390, 768 y 1280 px y pasó tras la corrección. Chromium verificó los perfiles de animación en las tres pestañas y la reanudación en el portal tras actualizar la ficha. La prueba de estabilidad del indicador corregido mantuvo 14 indicadores durante 90 segundos sin reinicios de fase ni errores. Las capturas y el PDF se generaron con datos ficticios. La suite general es una comprobación separada.
