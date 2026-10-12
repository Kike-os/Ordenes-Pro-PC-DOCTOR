# Próximas Entregas

Módulo propio (1.5.47, ruta `#deliveries`) para equipos terminados. No muestra órdenes en reparación, diagnóstico, presupuesto ni espera de respuesta.

- Entran: órdenes en «Listo para entregar», «En espera de entrega» y las entregadas en los últimos 30 días.
- El estado de entrega se calcula en el servidor (`/api/deliveries`) con datos reales: Entregada (orden entregada), Entrega vencida (fecha estimada pasada), Pendiente de retiro (en espera de entrega), Entrega programada (lista con fecha futura) y Lista para entregar.
- No existe «Entrega confirmada por el cliente»: el sistema no registra esa confirmación, así que no se muestra.
- Acciones: ver la orden, entregar el equipo (cambia la orden a Entregado con confirmación y programa su mantenimiento), contactar por WhatsApp, imprimir ticket y comprobante PDF.
- Aviso interno por cada equipo que queda «Listo para entregar» (48 horas) y los avisos de pendientes y vencidas llevan a este módulo.
