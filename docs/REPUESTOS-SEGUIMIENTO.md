# Seguimiento de pedidos de repuestos (1.5.238)

Cada orden puede tener varios repuestos. Cada uno lleva sus propias etapas, fechas, evidencias e historial (`order_part_requests` y `order_part_events`, migración 093).

## Etapas y situaciones

- **Etapas:** Solicitado → Confirmado → Preparación → En tránsito → Recibido → Instalación → Finalizado → Listo para entrega.
- **Cómo se avanza:** de una etapa a la siguiente. Saltar o retroceder es una **corrección de administración con motivo**. Una etapa nunca se completa por el paso del tiempo.
- **Situación** (aparte de la etapa): sin novedad, en espera de confirmación, en espera del proveedor, retrasado, incidencia de transporte o cancelado.
  - Requiere motivo y admite una nueva fecha estimada, solo si el proveedor la confirmó.
  - Cancelado es definitivo.
  - Al avanzar de etapa, una espera o un retraso anterior queda resuelto.
- **Colores:** gris pendiente, azul en proceso, amarillo en espera, naranja retraso, verde completado y rojo incidencia o cancelación. El color siempre va con un texto y un icono: ✓ para completado y un punto para la etapa actual.
- **Vencido:** si pasa la fecha estimada sin haberse recibido, se advierte **solo internamente**.

## Datos administrativos

Ninguno es obligatorio salvo el nombre:
- marca, modelo compatible, referencia y cantidad;
- proveedor, línea de compra existente y producto del inventario;
- fecha de compra, llegada estimada y número de pedido;
- transportista, guía y enlace de rastreo (solo https);
- recepción, observaciones internas y técnico responsable.

Cada cambio queda en el historial con el valor anterior.

## Integración sin duplicar

- **Línea de compra:** una línea registrada se asocia a **un solo** pedido de repuesto (índice único). En el selector, las ya asociadas aparecen deshabilitadas con su orden.
- **Sin operaciones automáticas:** cambiar de etapa (incluso a «Recibido») no crea compras, facturas, cobros ni movimientos de inventario. La recepción en inventario y el uso en la orden siguen sus procedimientos. Las series mantienen el control de la 1.5.236.
- **Evidencias:** «Agregar evidencia» abre «Agregar seguimiento» vinculado al repuesto (`order_followups.part_request_id`), con las reglas de la 1.5.237: 10 MB, visibilidad y retiro.

## Cliente

En el enlace público hay un panel «Seguimiento de repuestos».
- **Disposición:** línea horizontal cuando el panel tiene 600 px o más (computadora) y vertical en el teléfono.
- **Lo que muestra:**
  - nombre y marca;
  - etapa, con su fecha por etapa;
  - fechas de solicitud, de llegada estimada (si se registró) y de recepción;
  - última actualización;
  - la situación;
  - los mensajes que el taller **marcó como públicos**.
- **Lo que nunca muestra:** costos, proveedor, número de pedido, compra, guía, transportista, enlaces de rastreo ni observaciones internas.
- **Repuesto oculto:** se puede ocultar un repuesto del enlace.

## Mensajes y notificaciones

- **Plantilla por etapa y situación:** cada una precarga su mensaje en el campo público, que se puede editar. ADI está en modo cliente y la observación interna en modo interno.
- **Guardar y notificar:** abre «Comunicación con el cliente» con el texto para revisarlo. El envío por WhatsApp o correo, su registro y el control de duplicados son los de ese módulo. **Nada se envía automáticamente.**

## Pruebas

- **`test_part_requests.py`:**
  - 8 etapas con fecha, hora y responsable;
  - sin saltos del técnico y corrección de administración con motivo;
  - historial inalterable;
  - 3 repuestos independientes;
  - retraso con nueva fecha, incidencia y cancelación;
  - vencido interno;
  - enlace público sin datos privados;
  - línea de compra sin duplicar y sin movimientos de inventario;
  - cambios de datos en el historial;
  - evidencia vinculada;
  - permisos.
- **Navegador:** 12 comprobaciones (panel, ventanas, colores, notificar, horizontal y vertical, enlace público).

## Diseño «PC-DOCTOR Pro» con vehículo animado (1.5.241)

**Flujo:**
1. `order_part_requests.public()` arma un modelo público, solo con campos permitidos.
2. `order_tracking._parts_section()` lo dibuja.
3. `ticket.css` define colores, disposición y animación.

No hace falta JavaScript. Todo sale de los eventos reales registrados.

| Estado interno | Etapa pública | Vehículo |
|---|---|---|
| solicitado | 1 Solicitud registrada | — |
| confirmado, preparacion | 2 Repuesto confirmado | — |
| transito | 3 En traslado hacia PC-DOCTOR | `transit`: avanza una vez hacia «Recibido»; `stopped` si hay retraso o incidencia, con el tono de la situación |
| recibido | 4 Recibido en el taller | `arrived`: llega, se detiene y muestra la marca ✓ |
| instalacion | 5 Instalación y pruebas | — |
| instalado, listo | 6 Proceso finalizado (completa con «listo») | — |

**Etapas y colores:**
- Las seis etapas siempre se ven.
- El traslado solo se completa si se registró. Si el repuesto llegó sin ese evento (corrección de administración), queda «No registrada» en neutro.
- Sin traslado real no hay vehículo: no se simula movimiento ni se deduce por el tiempo.
- Colores (`--s0`…`--s5` en `.ticket-parts`): azul institucional, azul vivo, turquesa, turquesa verdoso, verde claro y verde intenso.
- Solo las etapas completadas se colorean. La actual tiene un halo y un pulso que se repite tres veces y termina. Las pendientes quedan en `--neutro`.

**Contenido:**
- **Bloque «Estado actual»:** estado, mensaje claro, «N de 6 etapas completadas» con medidor y última actualización.
- **Historial:** cronología del más reciente al más antiguo, con fecha y hora, estado, descripción breve y el mensaje público si existe. Cada punto lleva el color de su etapa o el tono de su novedad.

**Disposición y movimiento:**
- Horizontal desde 440 px de panel. Vertical en el teléfono, con el vehículo junto a la etapa de traslado.
- Animaciones de 0,45 a 1,6 s que se ejecutan una vez.
- Con `prefers-reduced-motion` no hay animaciones y el vehículo queda quieto en su punto real.

**Pruebas:**
- **Unitarias:** 6 etapas; vehículo en tránsito, detenido, llegado y ausente; traslado no registrado.
- **Navegador:** 19 comprobaciones. Incluyen:
  - los 6 estados, un traslado con novedad, un texto largo, con y sin fecha estimada y varios repuestos;
  - alineación de puntos y etiquetas y posición del vehículo;
  - movimiento reducido y anchos de 320 a 1920 px.
