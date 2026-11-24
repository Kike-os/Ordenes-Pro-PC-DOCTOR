# Centro de impresión — PC-DOCTOR · Premium Billing Center 4.0 (fase 1, 1.5.323)

Código: `local/invoice_ticket.py` (ticket de factura), `local/print_center.py` (formatos, preferencias e historial), rutas en `local/app.py`,
interfaz `printCenter()` en `local/static/app.js`. Migración `118_invoice_print_log.sql` (solo crea una tabla). Pruebas: `local/tests/test_invoice_ticket.py`.

## Qué imprime

| Formato | Contenido |
|---|---|
| **Ticket térmico 80 mm** (predeterminado) | «Tech Retail Invoice 4.0»: 72 mm útiles a 203 dpi (Epson TM-m30II), blanco y negro, una página de altura variable por copia |
| **Ticket térmico 58 mm** | La misma plantilla en 48 mm útiles |
| **Factura A4 (RIDE del sistema)** | El RIDE A4 existente (`invoice_documents.ride_pdf`) |
| **RIDE original de AZUR** | El PDF que genera AZUR; nunca se modifica ni se sustituye. Solo aparece si la factura se envió por AZUR |

Un borrador no se imprime (no tiene número ni clave de acceso): los formatos se muestran no disponibles con el motivo.

### Ticket «Tech Retail Invoice 4.0»

1. **Encabezado:** logotipo original en escala de grises (no se redibuja), nombre comercial, razón social, RUC, matriz, establecimiento, contacto
   y obligaciones (contabilidad, RIMPE, contribuyente especial, agente de retención) según los Datos fiscales.
2. **Identificación tributaria:** FACTURA ELECTRÓNICA, número, fechas de emisión y autorización, ambiente, tipo de emisión y estado. Si no está
   autorizada en producción, cada copia lo dice («DOCUMENTO DE PRUEBA» o «NO AUTORIZADA POR EL SRI — SIN VALIDEZ TRIBUTARIA»).
3. **Cliente:** nombre o CONSUMIDOR FINAL, CI/RUC, dirección y la orden, proforma o venta vinculada (solo si existen).
4. **Detalle:** descripción completa con saltos de línea naturales, cantidad × precio unitario, importe y descuento por partida.
5. **Resumen:** subtotales por tarifa, subtotal sin impuestos, descuentos, IVA por tarifa y TOTAL destacado. Los importes salen tal cual de
   la factura registrada: no se recalculan.
6. **Forma de pago** registrada en la factura (nunca «pagada» sin un pago confirmado).
7. **Autorización:** clave de acceso completa en texto, Code 128 (un punto por módulo, 42,7 mm) y QR con la clave; referencia a
   srienlinea.sri.gob.ec para verificar la validez.
8. **Pie:** «Gracias por confiar en PC-DOCTOR.», «Tecnología que inspira confianza.», portal y «Powered by Órdenes Pro».

**Nunca imprime** usuario ni contraseña (el ticket de Mi Negocio imprimía la cédula como contraseña), claves de activación ni datos internos.

## Centro de impresión

- Vista previa real del PDF (se descarga y se muestra como archivo local, por la política de seguridad que impide incrustar respuestas).
- Formato (flechas del teclado), copias (1–5 en tickets), «Usar como formato predeterminado» (preferencia por usuario; 80 mm por defecto).
- **Imprimir** abre el diálogo nativo del sistema: elige allí la Epson, papel en rollo, escala 100 % y sin márgenes. **Descargar PDF**.
- Botón **Imprimir** siempre visible en cada factura de la tabla y en su detalle (deshabilitado con el motivo si es un borrador).
- **Historial:** vista, descarga, solicitud de impresión y de reimpresión (la segunda impresión de una factura se registra como
  reimpresión), con usuario, fecha, formato y copias. Se registra la **solicitud**: el navegador no puede confirmar el papel, así que nunca
  figura «impreso».

## Garantías

Imprimir, reimprimir, ver o descargar **no** emite, no consume secuenciales, no crea pagos ni movimientos de caja, no toca inventario y no
envía nada (lo comprueban las pruebas contando facturas, eventos, secuenciales, correos y pagos antes y después). Solo administración.
Sin la migración 118 el historial queda inactivo y todo lo demás funciona.

## Pendiente

- **Prueba física en la Epson TM-m30II** (papel, corte y lectura con el escáner del taller): solo se validó digitalmente (PDF a 203 dpi,
  lectura de Code 128 y QR con ZBar).
- Siguientes fases: reportes y exportaciones, recibos/anticipo/entrega/nota de crédito, portal de consulta con QR y permisos por acción.
