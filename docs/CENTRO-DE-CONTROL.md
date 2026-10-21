# Centro de Control Técnico

Tablero del módulo «Reportes». Todo se calcula en el servidor (`local/reports.py`) con las órdenes registradas; no usa datos simulados ni información económica (presupuestos, pagos o ingresos).

## Qué muestra

- **Indicadores:** órdenes recibidas y entregadas en el rango; activas, listas para entregar y con entrega vencida en este momento; tiempo promedio de recepción a entrega.
- **Distribución por estado** (dona): órdenes recibidas en el rango según su estado actual.
- **Órdenes por periodo** (columnas): recibidas y entregadas por día, semana, mes o año.
- **Evolución de órdenes abiertas** (área): órdenes sin entregar al cierre de cada periodo.
- **Productividad por técnico:** órdenes activas y entregadas en el rango por responsable asignado.
- **Tipos de equipo:** órdenes recibidas por tipo.

Las fechas se agrupan en hora de Ecuador. La fecha de entrega solo cuenta si la orden está en estado «Entregado».

## Filtros y detalle

Periodo (diario, semanal, mensual, anual), rango de fechas personalizado, estado, tipo de equipo y técnico. Al pulsar un indicador, un segmento, una barra o una fila de la leyenda se listan las órdenes que lo componen (`/api/reports?group=…&value=…`, máximo 200) con enlace a cada orden.

## Actualización

El tablero vuelve a consultar el servidor cada 20 segundos mientras la pestaña está visible. No es un canal en vivo (Vercel no mantiene conexiones abiertas): un cambio hecho en otra sesión aparece como máximo 20 segundos después. El indicador muestra la hora de la última consulta correcta o avisa de que no hay conexión, conservando los últimos datos.

## Gráficos

Apache ECharts 5.6.0 (licencia Apache 2.0, gratuita), en un paquete reducido con dona, barras y líneas, servido desde `local/static/echarts.min.js`; no se carga nada de servidores externos. Se descarga solo al abrir este módulo. Si no pudiera cargarse, los indicadores, la leyenda por estado y los listados siguen funcionando.

Para regenerar el paquete: `npm install echarts@5.6.0 esbuild`, importar `PieChart`, `BarChart`, `LineChart`, `GridComponent`, `TooltipComponent`, `LegendComponent`, `AriaComponent` y `CanvasRenderer` desde `echarts/core`, asignar `window.echarts` y empaquetar con `esbuild --bundle --minify --format=iife`.

## Centro de Configuración y Administración — diseño Enterprise Pro (rama `configuracion-pro`)

- **Estructura:**
  - menú lateral de 288 a 300 px con los 9 apartados de siempre, en texto completo; el activo se marca con un indicador y un resplandor rosados suaves;
  - panel principal amplio (hasta 1440 px) que entra con una animación breve (200 ms);
  - el apartado elegido se conserva en la dirección (`#settings?tab=…`), al guardar y al recargar.
- **Tableta (641 a 1100 px):** el menú se pliega a iconos, con su nombre al pasar el cursor; «Mostrar nombres» lo despliega.
- **Celular:** un selector desplegable sustituye al menú, los campos van en una sola columna, los botones son cómodos y no hay desplazamiento horizontal.
- **Mi perfil:**
  - tarjeta con avatar (foto real o iniciales), nombre, correo y usuario, y estado real: rol, cuenta activa o inactiva y verificación en dos pasos;
  - nombre visible y correo editables; usuario, rol y permisos de solo lectura;
  - botones **Restablecer** (vuelve a los datos guardados) y **Guardar cambios**. El rol no se cambia desde aquí.
- **ADI:**
  - pasa a ser una barra compacta dentro de «Correo y servicios»: icono, estado real del servidor (proveedor y modelo, o «Sin proveedor de IA»), canales, mejoras del día e interruptor «Mejoras de redacción»;
  - «Más opciones» despliega la prueba de conexión y la Corrección Inteligente;
  - el envío automático del comprobante queda como bloque propio en ese mismo apartado;
  - antes, todo esto aparecía debajo del Centro, fuera de su contenedor.
- Las animaciones duran entre 150 y 220 ms, sin efectos permanentes, y se desactivan con movimiento reducido.

No cambian los endpoints, usuarios, contraseñas, verificación en dos pasos, permisos, correo, horarios, catálogo, condiciones ni la integración de ADI.

## Estado del sistema y corrección del icono gigante (rama `estado-sistema-pro`)

**Causa del icono gigante:**
- `systemIcon()` crea SVG con `viewBox` pero sin ancho ni alto, y la clase `system-icon` solo tenía tamaño en contextos concretos.
- En la 1.5.187 el panel pasó a ser una rejilla: el botón «Abrir el Centro de Actualizaciones» ocupó toda la fila y su icono creció con él (732 × 732 px).

**Corrección de raíz:** tamaño por defecto `:where(svg.system-icon){width:18px;height:18px}`. Al tener especificidad cero, cualquier regla de contexto lo sigue mandando.

**Verificación:**
- Se midieron los 759 iconos de todos los módulos antes y después del cambio. Solo cambió el gigante, más un icono de inicio que medía 28 px frente a los 16 de sus hermanos y ahora mide 16.
- Tras el cambio no queda ningún icono mayor de 40 px, ni en 1366 ni en 390 px (salvo el fondo tecnológico, que es intencionado).

**Nuevo panel:** cinco tarjetas con datos reales.
- **Acceso:** dirección oficial y enlace externo.
- **Seguridad:**
  - autenticación según el último diagnóstico de ADI AutoCare;
  - roles con el número real de cuentas;
  - políticas de sesión configuradas;
  - registro de auditoría con su último evento.
- **Usuarios:** cuentas activas, habilitadas y con verificación en dos pasos.
- **Solicitudes:** pendientes y rechazadas.
- **Centro de Actualizaciones:** versión, fecha y estado según `/api/public/version`. El icono solo gira mientras se consulta.

Las clases llevan el prefijo `sysst-` porque `.status-label` ya existía para los estados de las órdenes. Las tarjetas se reparten en 4 columnas en 1920, 3 en 1366, 2 en tableta y 1 en celular.
