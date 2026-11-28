# Battery Health Premium 6.5.1

La corrección parte de Órdenes Pro v1.6.9, compilación `69e2296`. Se reprodujo en Chromium con órdenes ficticias y los recursos de esa compilación. Los tres recursos CSS y JS comprobados coincidieron con producción y se sirvieron con `Cache-Control: no-store`.

## Causa y corrección

En `local/static/app.css`, la regla `#module-content .equip-battery-card:has(>.equip-tab-select[aria-selected=true])` dibujaba una sombra azul de un píxel alrededor del borde seleccionado. Chromium calculó `rgba(95, 168, 234, 0.25) 0px 0px 0px 1px` antes y `none` después. Se eliminó la sombra de esa misma regla y se conservó el borde y el foco visible por teclado.

La tabla compartida ya clasificaba 45 % como Desgaste elevado. El estado de seguridad reemplazaba el nombre de la clasificación y aplicaba rojo a todo el indicador. Ahora el título y el icono conservan la advertencia roja, mientras que el texto de capacidad conserva su clasificación y color. Para 45 % y 55 % de desgaste, los rellenos son 1, 1, 0,25, 0 y 0. La animación se mantiene suspendida cuando existe una alerta crítica.

El SVG, sus identificadores, geometría, paleta y perfiles de animación permanecen con sus definiciones existentes. El motor utiliza recortes independientes por instancia. No se añade una segunda máscara, animación ni temporizador. El portal y el diálogo identifican el componente como 6.5.1. La corrección no añade migraciones.

## Evidencia

Las capturas anteriores y posteriores, a 320, 390, 768 y 1280 px, y la grabación de Chromium se encuentran en `output/battery-health-6.5.1/`. La reproducción incluye 45 % con y sin alerta, 85 %, 39,9 % y una batería pendiente. La prueba automatizada cubre los límites de los rangos, los cinco rellenos, el foco, la selección de equipo, las pestañas, los indicadores simultáneos, las actualizaciones del portal, la recarga, A4 y las preferencias de movimiento.

Para revertir el código se puede desplegar la compilación anterior, conservando las evaluaciones y los permisos registrados. Smart Link Intelligence corresponde a una actualización separada.
