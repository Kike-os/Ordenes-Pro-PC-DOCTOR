# Portal seguro del cliente (Premium Billing Center)

**Acceso:** desde el QR de seguimiento de la orden, que aparece en el ticket, los recibos y los comprobantes.
1. La página de seguimiento muestra «Ver mi estado de cuenta y comprobantes».
2. El cliente escribe los **últimos 4 dígitos de su cédula o RUC**.
3. Se abre un acceso de **15 minutos**, solo para esa orden y ese enlace.

**Datos de la sesión:** se guarda solo la huella del token. La cookie es HttpOnly y SameSite=Strict, y se limita a la ruta del enlace.

**Cierre del acceso:** con «Cerrar el acceso», o al vencer los 15 minutos. Si se revoca el enlace de seguimiento, el portal deja de funcionar para ese QR.

**Protección:**
- 6 intentos por enlace cada 15 minutos y 20 por dirección cada hora;
- sin verificar no se muestra ningún dato.

## Qué ve el cliente

Cada parte se puede apagar en Facturación → Configuración → «Portal seguro del cliente».

- Saldo de la orden: total, pagado y saldo, con la hora del cálculo.
- Pagos registrados, con su recibo en PDF.
- Comprobante de entrega, si la orden se entregó.
- Facturas **autorizadas de producción** de la orden, con su RIDE si AZUR ya lo entregó.
- Estado de cuenta del cliente: el documento informativo, sin simulaciones de intereses.

## Seguridad

- **Solo lectura:** nada cambia pagos, órdenes ni facturas.
- **Auditoría:** cada verificación, intento fallido, consulta y descarga queda registrada sin datos personales (`portal_verified`, `portal_failed`, `portal_view` y `portal_download_*`).
- **Aislamiento:** solo se muestran documentos de la orden del enlace. Una sesión no sirve para otra orden.

## Migración

126, aditiva: tabla `client_portal_sessions`. Sin ella, el portal aparece como no disponible.

## Pruebas

**Automáticas:** `local/tests/test_client_portal.py`. Cubre:
- la verificación;
- la cookie;
- las descargas;
- la otra orden;
- que nada cambie;
- la auditoría;
- el cierre;
- el enlace revocado;
- los permisos por acción;
- el portal apagado;
- el límite de intentos;
- que la configuración sea solo de administración.

**Visual:** 390 y 1366 px, sin desbordes.
