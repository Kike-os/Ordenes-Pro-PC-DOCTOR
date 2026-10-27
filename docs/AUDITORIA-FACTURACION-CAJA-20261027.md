# Auditoría de Facturación, Caja y Pagos — 27/10/2026

**Alcance:** revisión del código de la versión 1.5.207 (rama `facturacion-caja`), antes de la Fase 1. No se tocó ningún dato de producción.

## Facturación electrónica (`local/invoicing.py`, `local/invoice_documents.py`, `local/sri_xml.py`)

| Función | Estado |
|---|---|
| Borrador desde una orden pagada o una venta de licencias | Implementado. Uno por operación; si se repite, devuelve el mismo |
| Comprador y regla de consumidor final (hasta USD 50,00) | Implementado en el servidor |
| IVA incluido descompuesto por línea (base + impuesto exactos) | Implementado |
| Emisión: secuencial, clave de acceso (módulo 11) y XML sin firmar | Implementado **solo en el ambiente de pruebas** |
| Cuenta bancaria en la factura | Implementado |
| Descarte de borradores e historial inmutable | Implementado (disparadores en la base) |
| Políticas comerciales por versión y asociación al emitir | Implementado; falta el texto validado |
| RIDE en PDF y certificado de garantías | Implementado |
| Envío de documentos | Solo a facturas autorizadas; pruebas solo a la dirección autorizada |
| Firma XAdES-BES, recepción y autorización del SRI | **Pendiente** (falta el certificado) |
| Proformas, notas de crédito, anticipos | **Pendiente** |
| Factura de una orden con saldo pendiente | **Bloqueado hoy:** exige la orden totalmente pagada (pedido: no bloquear el borrador) |
| Factura con productos del inventario o servicios sueltos | **Pendiente:** solo nace de una orden o de una venta de licencias |

## Caja (`local/cash.py`)

| Función | Estado |
|---|---|
| Cierre diario por persona con la foto de los cobros | Implementado; un cierre no se modifica |
| Efectivo contado y diferencia con observación obligatoria | Implementado |
| Depósitos: pendiente → depositado (comprobante y archivo) → conciliado (solo administración) | Implementado; el mismo comprobante no se repite en la misma cuenta |
| Apertura de caja, saldo inicial y sesión identificada | **Pendiente** |
| Egresos (gastos, proveedores, devoluciones) | **Pendiente** |
| Totales por método en el panel de caja, PDF del cierre | **Pendiente** |

## Pagos y saldo de las órdenes (`local/equipment.py`)

| Función | Estado |
|---|---|
| Pago o devolución con importe en centavos exactos | Implementado |
| Sin duplicados por doble clic (clave de solicitud única) | Implementado |
| Pago que supera el saldo | Rechazado |
| Anulación con motivo, sin borrar | Implementado; no se anula un pago de un equipo entregado |
| Pagos generales de la orden y su asignación a equipos | Implementado |
| Bloqueo de entrega con saldo | Implementado |
| Métodos | `efectivo`, `transferencia`, `deposito`, `tarjeta`, `otro`. Los fija una restricción de la tabla; débito/crédito, pago mixto y cuenta receptora necesitan migración |
| Confirmación previa con saldo anterior y nuevo, recibo por correo o WhatsApp | **Pendiente** |
| Movimiento de caja por sesión y cuenta bancaria | **Pendiente:** hoy el cierre lee los pagos del día por persona |

## Cuentas bancarias (`local/banking.py`)

- Catálogo central con banco, tipo, número, titular, identificación, estado y cuenta predeterminada.
- **Pendiente:**
  - logotipos de los bancos;
  - indicadores;
  - historial por cuenta;
  - registro de transferencias con verificación;
  - filtros y exportación.

## Hallazgos de la interfaz (corregidos en la Fase 1)

1. Facturación tenía su propia pestaña «Inventario» con un resumen del inventario antiguo. Duplicaba el Centro de Inventario.
   - **Ahora:** un acceso directo al Centro, con el aviso de existencias.
2. Los 6 indicadores grandes ocupaban la pantalla de Facturas y no distinguían documentos de prueba y reales.
   - **Ahora:** un Panel general compacto con 7 indicadores, documentos de prueba y reales por separado, gráfico mensual (solo con datos), documentos que requieren atención y actividad reciente.
3. Las 8 pestañas no estaban organizadas.
   - **Ahora:** menú lateral agrupado en Facturación, Administración y Configuración, plegable en escritorio y desplegable en móvil.
   - Las funciones aún no construidas se identifican «En desarrollo» y explican lo previsto, sin simular nada.
4. La conexión con el SRI no tenía un lugar propio.
   - **Ahora:** «Integración SRI» muestra el estado real de cada etapa. Solo la generación del XML funciona, y en pruebas.
