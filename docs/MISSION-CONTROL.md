# Technical Mission Control 5.1 · Premium Live Dashboard (1.5.335)

**Dónde está:** Reportes → Centro de Control Técnico.

**Alcance:** se conservan los filtros, los gráficos y los listados existentes; esta versión añade lo siguiente.

## Tarjetas de indicadores

Cada tarjeta tiene:

- icono;
- contador destacado;
- descripción;
- línea de acento con el color de la paleta indicada.

Se distribuyen en 4 columnas en escritorio, 2 en tableta y 1 en móvil, con una altura de unos 158 px.

**Distinción entre periodo y situación actual:**

- **«Periodo»** (recibidas, entregadas, tiempo promedio): se comparan con el **periodo anterior de la misma duración**.
- **«Ahora»** (activas, listas, entregas vencidas, permanencia vencida): describen la situación actual y no se comparan.

**Minigráficos:** solo con historial real (recibidas, entregadas y abiertas por periodo), con la información de cada punto.

**Entregas y permanencia vencidas en cero:** se ven en gris neutro, sin alarma roja.

## Indicadores circulares (servidor; con denominador válido y metodología visible)

| Indicador | Cálculo |
|---|---|
| Cumplimiento de entregas programadas | Órdenes entregadas en el rango que tenían una fecha estimada **confirmada**: entregadas en esa fecha o antes, sobre esa cohorte |
| Entregadas en 7 días o menos | Órdenes entregadas en el rango: entregadas en 7 días o menos, sobre todas las entregadas del rango |
| Avance de órdenes activas | Órdenes activas que están en pruebas, listas o esperando entrega, sobre todas las activas |
| Capacidad operativa del taller | El taller no tiene una capacidad definida, así que no se calcula (gris) |

**Sin denominador** se muestra «—» y nunca un 0 %.

## EN VIVO

- **Colores:**
  - verde: actualizado;
  - amarillo: con retraso;
  - rojo: varias consultas fallidas;
  - azul: actualización en curso;
  - gris: sin información verificada.
- **Muestra:** última comprobación correcta, hora de Ecuador e intervalo de 20 s.
- **Botones:** «Actualizar ahora» y acceso al modo pantalla completa.
- **Regla:** nunca aparece en verde con datos desactualizados.

## Resumen de filtros

Se ve la **agrupación de los gráficos** (diaria, semanal, mensual o anual) por separado del **rango de fechas**, y el estado, el tipo y el técnico activos.

## Resumen de ventas y finanzas (solo administración, `GET /api/reports/summary`)

| Indicador | Fuente |
|---|---|
| Ventas de hoy, del mes y del año | Libro del Centro de Ventas, sin las anuladas |
| Ingresos confirmados | Cobros de órdenes no anulados, sin transferencias por validar ni rechazadas, menos devoluciones |
| Facturación autorizada | Facturas autorizadas por el SRI del ambiente activo. **No implica que estén pagadas** |
| Capital pendiente y cartera vencida | ADI Smart Collections |
| Gastos | Egresos de caja no anulados |
| Rentabilidad | **No se calcula**: faltan los costos completos («Sin datos suficientes») |

**Comparaciones:** con el mismo tramo del periodo anterior (mes hasta hoy frente al mes anterior hasta el mismo día).

**Minigráficos:** los últimos 30 días.

## Mission Control Display

Pantalla completa para un monitor del taller. Muestra:

- indicadores grandes;
- anillos;
- actividad reciente: las órdenes recibidas en el último periodo;
- incidencias prioritarias.

Se actualiza cada 20 s y tiene botones para ocultar los datos financieros y los personales. **Escape** sale.

## Pruebas

**Automáticas:** `local/tests/test_mission_control.py` cubre:

- denominadores válidos y capacidad sin definir;
- cohorte de entregas a tiempo;
- periodo anterior;
- fuentes del resumen;
- rentabilidad no inventada;
- acceso solo de administración.

**Visuales:** 1920, 1366, 1024, 768 y 390 px, sin desbordamiento. Escape cierra el modo pantalla completa.

## Pendiente

- Las imágenes de referencia de la orden **no llegaron**. Si se envían, se ajusta el diseño a ellas.
- La orden 5.0 que esta complementa tampoco llegó.
