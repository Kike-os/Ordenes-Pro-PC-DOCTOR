# Comprobantes no tributarios (Premium Billing Center)

**Módulo:** `local/vouchers.py`. El recibo A5 sigue en `local/payment_pdf.py`.

**Reglas comunes:**
- Todos son de **solo lectura**: imprimir o descargar no cambia pagos, anticipos, órdenes ni facturas, ni consume secuenciales.
- Cada documento dice que **no es una factura** ni un comprobante de venta del SRI.
- Solo llevan datos registrados.

| Documento | Formatos | Dónde se descarga |
|---|---|---|
| Recibo de pago, abono o devolución | A5 y ticket de 80 mm | Orden → Pagos → «Recibo» / «Ticket» |
| Comprobante de anticipo | A5 y ticket de 80 mm | Proforma → Anticipos → «Comprobante» / «Ticket» |
| Comprobante de entrega | A4 y ticket de 80 mm | Orden entregada → «Comprobante de entrega» / «Ticket de entrega» |

## Contenido

- **Recibo de pago:**
  - número, fecha y hora;
  - orden y **factura vinculada** (si existe);
  - cliente, identificación y equipo;
  - importe, forma de pago y referencia;
  - quién lo registró;
  - total, pagado y saldo, con la hora del cálculo;
  - aviso de anulación si corresponde;
  - **QR de consulta segura**.
- **Anticipo:**
  - código, fecha y hora;
  - proforma y orden vinculada;
  - cliente e identificación;
  - concepto (partidas de la proforma);
  - valor total acordado, anticipo recibido, forma de pago y referencia;
  - anticipos a la fecha y saldo pendiente (o a favor);
  - quién lo registró;
  - aviso de anulación.
- **Entrega:**
  - número de orden, cliente, marca, modelo y serie;
  - servicio realizado (partidas aprobadas) y diagnóstico;
  - fecha de entrega;
  - estado de pago y factura;
  - garantía;
  - observaciones y quién entregó;
  - **constancia de recepción** con firma, nombre y cédula para completar a mano;
  - QR de seguimiento.
  - Solo existe para órdenes entregadas.

## QR y garantía

- **QR:** es el enlace de seguimiento **activo** de la orden (con token, `/s/…`). Si se revoca, el documento se emite sin QR.
- **Garantía:** solo se muestra la registrada, es decir, los repuestos instalados con sus fechas de garantía de tienda o de fabricante. Si no hay, se indica que la garantía del servicio se rige por las condiciones aceptadas. No se inventan plazos.

## Firma corporativa

«Comprobantes de entrega» ya se puede activar en la configuración de la firma corporativa. Viene desactivada por defecto.

## Pruebas

**Automáticas:** `local/tests/test_vouchers.py`. Cubre:
- el contenido de cada documento;
- el QR solo con seguimiento activo;
- el formato de 80 mm;
- el anticipo anulado;
- la proforma ajena;
- que la orden no entregada no genera comprobante de entrega;
- que no se modifica ningún registro;
- que se exige sesión.
