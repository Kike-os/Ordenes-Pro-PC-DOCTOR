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
7. **Autorización:** clave de acceso completa en texto y QR con la clave (verificado con lector en 30 claves al azar, 80 y 58 mm); referencia a
   srienlinea.sri.gob.ec para verificar la validez. **Sin Code 128 en el ticket (1.5.324):** con 49 dígitos solo cabe a un punto por módulo y el
   lector lo leía en 6 de cada 10 claves; no se imprime un código que no se lee. El RIDE A4 conserva su Code 128.
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

- **Prueba física en la Epson TM-m30II** (papel, corte y lectura del QR con el escáner del taller): solo se validó digitalmente (PDF a 203 dpi
  y lectura del QR con ZBar).
- Siguientes fases: reportes y exportaciones, recibos/anticipo/entrega/nota de crédito, portal de consulta con QR y permisos por acción.


## Epson Precision Print 4.2 (1.5.326)

- **Página y márgenes:** la página del PDF mide lo mismo que el papel, así el controlador no aplica los márgenes dos veces. La altura se calcula con el contenido; bajo el pie quedan solo 2 mm de avance para el corte.

| Papel | Página | Imprimible | Contenido centrado |
|---|---|---|---|
| 80 mm | 80 mm | 72 mm | 68 mm (2 mm de seguridad por lado) |
| 58 mm | 58 mm | 48 mm | 44 mm |

- **Letra:** Helvetica, con las métricas de Arial.
  - Tamaños en 80 mm: texto 8 pt, secundario 7,5 pt, secciones 8,5 pt, título 10 pt, número 9 pt, total 12 pt, pie y clave 7,5 pt.
  - En 58 mm, cada tamaño es 1 pt menor.
  - Interlineado: 1,2.
  - Negrita solo en encabezados, número, estado e importes principales. Las descripciones van en letra normal y con su salto de línea natural.
- **Detalle:** la cantidad, el precio unitario y el importe van en columnas fijas alineadas a la derecha.
- **Logotipo:** el original en escala de grises, centrado: 24 mm en 80 mm y 18 mm en 58 mm.
- **Clave de acceso:**
  - Se imprime completa en texto, en QR y en Code 128 real dividido en partes. En 80 mm son 2 partes (dígitos 1–24 y 25–49); en 58 mm, 3 partes (16, 16 y 17 dígitos).
  - Los módulos miden 2 puntos (0,25 mm), con una zona de silencio de 10 módulos.
  - Un único Code 128 de 49 dígitos no cabe a 2 puntos por módulo: mediría 85 mm, y el cabezal tiene 72 mm. A 1 punto, el lector falló en 4 de cada 10 claves.
  - Prueba: 40 claves al azar a 203 dpi, en 80 y 58 mm, con todas las partes y el QR leídos.
  - **Pendiente de validar:** que el SRI y el contador acepten el código dividido en un ticket. El RIDE A4 conserva un único Code 128.
- **Muestra de calibración:** `GET /api/invoicing/ticket-calibration.pdf?format=80|58`, con datos ficticios.
  - Incluye marcas de los bordes del contenido (68 mm) y del área imprimible (72 mm), arriba y abajo, para medir los márgenes reales en papel.
  - No es una factura y no consume secuenciales.
- **En el diálogo de impresión (Chrome o Edge):**
  - papel en rollo del ancho correspondiente;
  - márgenes «Ninguno»;
  - escala 100 % (tamaño real).
  - Si sobra papel al final, activa en el controlador de Epson la reducción de papel del margen inferior.
