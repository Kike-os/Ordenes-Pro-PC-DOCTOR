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
