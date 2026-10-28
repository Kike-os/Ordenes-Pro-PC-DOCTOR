# Facturación electrónica a través de AZUR

Órdenes Pro emite la factura (secuencial propio y XML de control) y AZUR, mediante su API REST v2, genera el XML oficial, lo firma con el certificado del contribuyente verificado en AZUR, lo envía al SRI y consulta la autorización. Órdenes Pro no guarda el certificado ni su contraseña.

Mientras la emisión real no esté autorizada, todo funciona en el **ambiente de pruebas**.

## Variables de entorno

Se configuran en Vercel (Production) y en el `.env` local. Nunca van en el código, en los registros ni en los mensajes.

| Variable | Contenido |
|---|---|
| `AZUR_API_KEY_EMISION` | `api_key` del **punto de emisión de pruebas** en AZUR. Empieza con `API_`. Se usa solo para emitir. |
| `AZUR_CREDENCIAL` | Credencial de la API v2, `sk_test_…`. Se usa para consultar estado y documentos y para anular. |
| `AZUR_PUNTO_EMISION` | Punto de emisión exclusivo de Órdenes Pro, por ejemplo `001-002`. Debe coincidir con Facturación › Datos fiscales y ser distinto del que usa Mi Negocio. |
| `FACTURACION_MAIL_USERNAME` | Usuario SMTP del buzón facturacion@ordenes-pro.ecuadorpcdoctor.com. Es opcional: sin él, se usa la cuenta institucional. |
| `FACTURACION_MAIL_PASSWORD` | Contraseña SMTP de ese buzón. |
| `AZUR_PRODUCCION_AUTORIZADA` | Vacía. Solo se pone `SI` con autorización expresa de administración. Mientras esté vacía, una credencial `sk_live_` se rechaza. |

## Flujo de una factura

1. **Emitir en pruebas** (Órdenes Pro): se asigna el secuencial propio y se genera el XML de control.
2. **Enviar al SRI (AZUR pruebas)**, con confirmación: AZUR firma y envía.
   - Antes de llamar a AZUR se guardan la clave de idempotencia y el secuencial.
   - Un corte de conexión o un doble clic consulta, no emite otra vez.
   - Si el secuencial ya estaba en AZUR, se recupera ese documento.
3. **Consultar estado**: botón, consulta en vivo al SRI o tarea diaria. Solo el código 4 de AZUR marca la factura como **autorizada**, con el número y la fecha reales.
   - Antes de autorizarla se guardan el PDF de AZUR y los XML firmado y autorizado; después, un comprobante autorizado no se modifica.
   - Si el SRI la rechaza, se guardan sus mensajes y «Reprocesar» vuelve a enviar el mismo comprobante.
4. **Correo**: al autorizarse se envían el RIDE y el XML desde la cuenta de facturación. En pruebas solo van a la dirección de prueba configurada en Facturación › Configuración, nunca al cliente. AZUR no recibe el correo del comprador.
5. **Anular factura**, con motivo y la palabra ANULAR.
   - AZUR no anula en el SRI: primero se solicita la anulación en SRI en línea (Facturación Electrónica › Anulación).
   - Órdenes Pro comprueba con AZUR que consta anulada y la registra aparte, sin modificar la factura autorizada.
   - Si el plazo venció, se corrige con una nota de crédito.

## Controles

- Si AZUR devolviera una clave de acceso de producción (dígito de ambiente 2), la operación se detiene con una alerta.
- Cada operación queda registrada en `azur_operations`, una tabla inmutable sin credenciales.
- Pruebas automáticas: `local/tests/test_azur.py`, contra un AZUR simulado, sin red ni emisión real.
