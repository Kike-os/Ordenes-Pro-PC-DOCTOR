# Customer Device Intelligence 3.0 y corrección Enterprise Compact

## Alcance

Órdenes Pro v1.6.4 es la candidata posterior a v1.6.3. Battery Health Premium conserva la denominación 6.2. Se comprobó que producción y `main` remoto estaban en v1.6.3, compilación `5abbaa6`.

El diálogo anterior heredaba `overflow:auto` y márgenes de `.maintenance-dialog`. Su cuerpo también tenía desplazamiento propio. El indicador se montaba dentro del formulario, mientras que el título se limitaba al nombre de versión. Estas reglas y la estructura del HTML explicaban la doble barra y el aspecto de tarjeta aislada. El código encontrado coincidía con el commit publicado. La revisión no identificó un problema de caché ni una segunda ventana.

## Cambios

- El diálogo ahora tiene encabezado «Gestión de batería», distintivo SVG, subtítulo, resumen horizontal y pestañas con iconos. El encabezado y el pie permanecen accesibles mientras se desplaza el cuerpo. Diagnóstico, Reemplazo e Historial siguen en el mismo diálogo.
- Las alertas son independientes de la salud. Retirar un hallazgo peligroso exige confirmar la resolución técnica y documentarla. La evidencia presenta vista previa, nombre, tamaño, reemplazo y retiro. Conserva el límite de 750 KB y sus revisiones.
- El seguimiento verificado conserva la página original y añade la ficha del equipo y el diagnóstico. Los datos de hardware, la fotografía y las mediciones se publican según la autorización por orden y los controles en Portal seguro del cliente. Los números de serie se enmascaran. Solo se reutilizan fotografías ya autorizadas de esa orden.
- Los portátiles pueden mostrar la evaluación de la batería principal y baterías adicionales procedentes del informe de Windows. Cada batería adicional conserva capacidades, aprobación y estimación propias. La ficha indica batería ausente, pendiente o medición suspendida cuando corresponda.
- El portal muestra el estado, la condición del repuesto, su garantía y la comparación autorizada. ADI aporta una explicación contextual. Las recomendaciones se ocultan ante condiciones peligrosas y se mantiene visible la alerta.
- La actualización consulta únicamente la ficha guardada. El endpoint exige la sesión de identidad de 15 minutos vinculada a la orden y al enlace. Los cambios actualizan también la sección A4 cuando está habilitada. El seguimiento público conserva el enlace de acceso protegido y no recibe la ficha privada.
- La tarjeta de estado de cuenta usa los tokens corporativos. Se conservaron la verificación, los comprobantes, la impresión A4 y los códigos. El historial muestra los cinco estados recientes y permite expandir los demás.

## Archivos y seguridad

| Archivos | Cambios |
| --- | --- |
| `local/customer_device.py`, `local/client_portal.py`, `local/app.py` | Proyección con lista permitida, configuración administrativa por orden y acceso verificado. |
| `local/order_battery.py`, `local/battery_diagnostics.py` | Condición, resolución de alertas, repuesto, datos de evidencia y baterías adicionales. |
| `local/order_tracking.py`, `local/tracking_print.py`, `local/static/ticket.js`, `local/static/seguimiento-a4.css` | Inserción en la página existente, historial, A4 y acceso protegido. |
| `local/static/battery-widget.js`, `local/static/battery-widget.css`, `local/templates/dashboard.html` | Componente compartido de batería. La geometría, los segmentos, los estilos del indicador y la lógica de animación se cotejaron con la versión anterior. |
| `local/static/customer-device.js`, `local/static/customer-device.css`, `local/static/app.js`, `local/static/app.css` | Ficha adaptable, actualización parcial y diálogo compacto. |
| `local/tests/test_customer_device.py`, `local/tests/test_client_portal.py`, `local/tests/test_order_battery_visual.py` | Regresión del portal, permisos, escenarios de batería y capturas. |
| `AGENTS.md`, `CHANGELOG.md`, `local/data/releases.json` | Reglas permanentes y registro de cambios pendientes. |

No se añadió una migración. La ficha usa `system_state` para los permisos y especificaciones por orden. Las nuevas evaluaciones reutilizan los datos estructurados de la migración 135. La configuración de batería avanzada sigue dependiendo de que 135 esté aplicada en el entorno correspondiente. La consulta y la impresión privadas usan una misma proyección. No se abre una sesión distinta ni se amplía su vigencia.

## Verificación y capturas

La regresión focalizada cubre 46 pruebas con bases temporales y datos ficticios. Incluye actualización de una evaluación guardada, dos órdenes independientes, sesión vencida, falta de autorización, enmascaramiento, reemplazos, baterías adicionales, alertas al 100 %, evidencia, permisos, respuesta adaptable, A4, teclado, foco, contraste y movimiento reducido.

Capturas de Chromium en `output/battery-health-6.2-enterprise/`: 1920 × 1080, 1366 × 768, 1280 × 720 y 390 × 844. El adjunto de la solicitud solo contenía el texto. La comparación visual pudo hacerse con los criterios escritos.

## Publicación y reversión

La candidata local requiere autorización administrativa antes de publicar. Confirmar la versión y el remoto inmediatamente antes del despliegue. Para revertir, desplegar de nuevo la compilación anterior. Los datos guardados se conservan en `system_state` y en las revisiones ya existentes. La reversión del código no necesita borrar tablas ni alterar evaluaciones históricas.
