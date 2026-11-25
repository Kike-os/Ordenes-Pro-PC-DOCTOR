# Cancelación y cierre de órdenes (Smart Cancellation & Closure Management)

Desde la versión 1.5.348. Código: `local/order_cancellations.py`. Migración: `127_order_cancellations.sql` (solo crea tablas nuevas).

## Flujo

1. **Solicitar.** Botón «Cancelar reparación» en la orden (administración o técnico; no aparece en órdenes entregadas). Datos obligatorios:
   - un motivo predefinido;
   - observaciones (10 caracteres como mínimo);
   - verificación de identidad con el mecanismo existente, los últimos 4 dígitos de la cédula o RUC registrados (no se guardan). Si el cliente no tiene identificación, se escribe una nota de cómo se verificó.

   La evidencia es opcional (imagen o PDF de 4 MB como máximo). El cliente también puede solicitarla desde el portal seguro (sesión verificada). **Solicitar no cambia el estado de la orden.**
2. **Confirmar** (solo administración, escribiendo `CANCELAR`). Al confirmar:
   - los presupuestos pendientes se cancelan;
   - la orden pasa a «Espera de entrega» con una entrada en el historial (origen «cancelacion»);
   - se bloquean los cambios de estado manuales y automáticos;
   - se avisa al cliente por WhatsApp (evento `orden_cancelada`).
3. **Liquidar.** Solo se cobran los trabajos que el cliente autorizó; no se generan cobros automáticos. Si hay saldo pendiente, el estado es «Pendiente de liquidación». Si hay saldo a favor, se devuelve desde «Pagos y saldo» → devolución.
4. **Cerrar** (solo administración). Requisitos: saldo 0, sin saldo a favor y el nombre de quien retiró el equipo. La orden pasa a «Entregado» sin programar mantenimiento.
5. **Reabrir** (solo administración, antes del cierre, con un motivo). La orden vuelve a su estado anterior. Si ese estado era «presupuesto» o «esperando cliente» y ya no queda un presupuesto pendiente, vuelve a «diagnóstico».

Estados administrativos: solicitada → cancelada → pendiente de liquidación → pendiente de retiro → cerrada (`anulada` = reabierta).

## Lo que se conserva

No se borra nada:
- fotos;
- diagnóstico;
- presupuestos (quedan como «cancelado»);
- pagos, facturas y documentos tributarios;
- historial, QR y comprobantes.

Las unidades de inventario y los pedidos de repuestos se muestran como tareas pendientes; no se mueven solos.

## Documentos e integraciones

- **Acta de cancelación A4 (PDF):** logo, QR de seguimiento, cliente, equipo, motivo, liquidación y constancia de aceptación con firmas. No es una factura.
- **Portal y seguimiento:** el seguimiento muestra «Reparación cancelada a solicitud del cliente»; el portal muestra el estado o el formulario de solicitud.
- **ADI:** avisos «cancelaciones por confirmar» (alta) y «pendientes de cierre» (media); herramienta `cancelaciones`.
- **Reportes:** panel «Cancelaciones» (solo administración) con totales por estado, motivos frecuentes, valores recuperados, devoluciones y retiros pendientes.
- **WhatsApp:** plantilla de Meta `pcdoctor_cancelacion_reparacion` (UTILITY, es_EC). Se crea desde `POST /api/whatsapp/event-template` con `{"event":"orden_cancelada","action":"create","confirm":"CREAR"}`. Sin la plantilla aprobada, el aviso solo sale dentro de la ventana de 24 horas.

## Auditoría

Cada paso queda en `order_cancellation_events` y en la auditoría general, con usuario, fecha y estado anterior.
