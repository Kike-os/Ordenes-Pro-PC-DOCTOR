# Reportes y exportaciones de facturación (Premium Billing Center)

**Dónde está:** Facturación → Comprobantes → «Reporte de facturación», encima de la tabla. Solo administración.

**Qué no hace:** no emite, no envía nada al SRI, no consume secuenciales y no cambia comprobantes ni pagos.

## Filtros

El reporte usa **los mismos filtros de la lista**:
- búsqueda;
- rango de fechas de emisión;
- estado SRI;
- **forma de pago** (nuevo): efectivo, transferencia, depósito, tarjeta, crédito u otro.

**Ambiente:** el reporte es de un solo ambiente, por omisión el vigente. **Nunca suma pruebas con producción.**

## Indicadores

| Indicador | Cálculo |
|---|---|
| Facturado | Comprobantes emitidos sin rechazo (pendiente, enviado, autorizado). Borradores y rechazados no suman |
| Cobrado | Órdenes y ventas de licencias: sus cobros **actuales** (un pago anulado después de facturar deja saldo). Proformas, ventas de inventario y facturas directas: las formas de pago registradas en la factura, sin el crédito |
| Por cobrar | Facturado menos cobrado |
| Año (sin filtros) | Facturado del año hasta hoy frente al mismo tramo del año anterior. Sin datos del año anterior no se muestra porcentaje |
| Notas de crédito | Las registradas (no descartadas) del ambiente y el rango |
| Formas de pago | Facturado por cada forma de pago declarada en las facturas |

## Exportaciones

| Formato | Contenido |
|---|---|
| Excel (.xlsx) | Importes como números |
| CSV | Separado por punto y coma, UTF-8 |
| PDF | A4 horizontal con logo, filtros, totales y numeración de páginas |

- **Columnas:** comprobante, ambiente, emisión, cliente, identificación, vinculado, estado SRI, formas de pago, importe sin IVA, IVA, total, cobrado, por cobrar y clave de acceso. La clave de acceso y el ambiente no van en el PDF, por ancho.
- **Límite:** 5000 comprobantes, los más recientes. Si hay más, el reporte lo indica.
- **Auditoría:** cada exportación queda registrada con usuario, formato y cantidad de filas, sin datos de clientes.

## Pruebas

**Automáticas:** `local/tests/test_invoice_reports.py`, con base temporal, datos ficticios y solo el ambiente de pruebas. Cubre:
- facturado frente a cobrado, incluido un pago anulado después de facturar;
- filtro por forma de pago;
- ambientes que no se mezclan;
- datos anuales;
- notas de crédito;
- exportaciones con los mismos filtros, con auditoría;
- que nada cambie;
- acceso solo de administración.

**Visual:** de 320 a 1920 px, sin desbordes ni controles superpuestos.
