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
