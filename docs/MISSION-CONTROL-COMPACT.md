# Mission Control Compact · MissionControlTimeBar

**Componente global:** `mcTimeBar(opciones)` en `local/static/app.js`; estilos `.mctb` en `app.css`. Un solo componente para todos los plazos del sistema.

## Diseño

- Barra de **10 segmentos**, de 6 a 9 px de alto según el tamaño: compacto, estándar o ejecutivo.
- **Color progresivo** según el tiempo disponible, sin saltos:

| Tiempo disponible | Color | Estado |
|---|---|---|
| 100 – 76 % | esmeralda | Dentro del plazo |
| 75 – 51 % | lima | Tiempo disponible |
| 50 – 31 % | amarillo | Atención |
| 30 – 16 % | naranja | Próximo a vencer |
| 15 – 1 % | rojo | Tiempo crítico (pulsación discreta) |
| 0 % | rojo | Plazo vencido (el contador sigue visible en rojo) |

- **Contador digital** con números tabulares, **% disponible**, estado y fecha de vencimiento en hora de Ecuador.
- Icono de tiempo. Con movimiento reducido, sin animaciones.
- **Modo compacto (tablas):** solo icono, contador corto y estado; el resto va en la descripción emergente.

## Funcionamiento

- **Solo muestra plazos reales** del servidor: inicio y vencimiento, o porcentaje y días ya calculados. **Nunca reinicia, amplía ni decide** un vencimiento. No hay botón «Reiniciar». Las prórrogas siguen su flujo actual, con permiso y auditoría.
- **Un único reloj** para todas las barras: se detiene cuando no hay barras y se pausa con la pestaña oculta.
- Usa la **hora del servidor** (`clockOffset`): al recargar, en otra pestaña o en otro equipo muestra lo mismo.
- **Procesos detenidos** (entregado, sesión cerrada o pausada): estado fijo, sin contar.

## Dónde se aplica (solo donde hay un plazo definido)

| Módulo | Plazo |
|---|---|
| Órdenes (lista y detalle) | Plazo de retiro / permanencia (ingreso → límite o prórroga) |
| Detalle de la orden | Entrega estimada (recepción → final del día estimado) |
| Presupuestos | Validez del presupuesto enviado (envío → fecha de vencimiento) |
| Centro de Atención | Cierre por inactividad de 8 min (`expires_at` del servidor) |
| Mensajes de la orden | Ventana de 24 h de WhatsApp para texto libre |
| PQRS | Primera respuesta en 48 h (caso abierto sin respuesta) |
| ADI Smart Collections | Compromisos de pago abiertos (acuerdo → fecha comprometida) |
| Licencias digitales | Vigencia (días calculados por el servidor) |

**Sin barra, porque no tienen un plazo con duración:** citas (solo tienen hora), conversaciones administrativas de ADI (no se cierran por inactividad), notificaciones y facturación (sin plazos propios).

## ADI

- **Herramienta `plazos`:** entregas vencidas y próximas (24 h), presupuestos por vencer (2 días) y compromisos próximos (3 días).
- **Alertas en Insights:** «Entregas estimadas en las próximas 24 horas» (media) y «Presupuestos que vencen pronto» (informativa).
- Ninguna envía mensajes.

## Pruebas

- **Automáticas:** `test_adi_executive` (plazos), `test_order_followups` (ventana de WhatsApp), Live Support y regresión.
- **Visuales:**
  - estados por tramo, avance en vivo, liberación del reloj al salir de la pantalla;
  - 1366 y 390 px;
  - recorrido de 20 módulos sin errores.
