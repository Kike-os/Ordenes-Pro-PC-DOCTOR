# Facturación electrónica, cuentas bancarias y caja (rama `facturacion-electronica`, solo pruebas)

**Estado:** en desarrollo, en una rama y un entorno aislado. No está publicado.

- La **emisión real está desactivada** y no se puede activar desde la interfaz.
- **No hay conexión con el SRI:** ni de pruebas ni de producción. Se activará solo con una autorización expresa.
- Nada de este módulo mueve dinero ni se conecta con bancos.

## Normativa de referencia
Ficha técnica de comprobantes electrónicos del SRI, esquema offline, **v2.34** (julio de 2026):

- **Consumidor final:** «Si el valor de la factura es mayor a 50 USD se deberá especificar obligatoriamente los datos del adquirente» (9.10). Se identifica con el tipo 07 y el número 9999999999999.
- **Clave de acceso:** 49 dígitos con módulo 11. El ejemplo oficial `41261533` da 6 y es una de las pruebas.
- **IVA:** el 15 % es el código 4 y el 0 % el código 0 (tabla 17).
- **Firma:** XAdES-BES 1.3.2, *enveloped*, RSA-SHA1 con clave de 2048 bits. Pendiente de implementar.
- **Servicios web:** de pruebas, `celcer.sri.gob.ec`, y de producción, `cel.sri.gob.ec`. No se usan todavía.

## Facturación (menú «Facturación», solo administración)

**Origen:**
- una orden **totalmente pagada** con presupuesto aprobado (botón en «Pagos y saldo» de la orden);
- más adelante, una venta de licencias pagada.

Los datos salen de los módulos existentes: cliente, partidas aprobadas, pagos y catálogo.

**Reglas que aplica el servidor (la interfaz solo las refleja):**
- **Una factura vigente por operación**, con un índice único en la base. Un borrador descartado libera la operación.
- **Consumidor final hasta USD 50,00 inclusive**, con el total con impuestos en centavos. Por encima se bloquea, aunque se intente desde el navegador o directamente en la base: la emisión lo vuelve a comprobar.
- **IVA incluido en los precios:** la base y el IVA se descomponen por línea para que base + IVA redondeado = importe.
  - Alrededor del 13 % de los importes no tienen una base exacta. Se usa la más cercana, se avisa y el ajuste nunca pasa de 1 centavo.
  - **Pendiente:** confirmar con el SRI de pruebas que acepta esa tolerancia.
- **Secuenciales** por ambiente, establecimiento, punto de emisión y tipo, sin repetición. Se asignan **al emitir**, no en el borrador.
- **Protección:** un comprobante autorizado no se modifica ni se elimina, y el historial (`invoice_events`) es inmutable.
- **Solo ambiente de pruebas (1):** `emit()` rechaza cualquier otro ambiente.

**Estados:** Borrador, Pendiente, Enviado, Autorizado, Rechazado y Descartado. Hoy «Emitir en pruebas» deja la factura *Pendiente*, con número, clave de acceso y XML 1.1.0 descargable. La firma y el envío vendrán en una etapa posterior.

**Datos fiscales** (pestaña «Datos fiscales»): RUC validado, razón social, nombre comercial, direcciones, establecimiento, punto de emisión, contabilidad, régimen, contribuyente especial y agente de retención. Nunca se completan solos.

## Cuentas bancarias (catálogo central)
Están en Facturación → «Cuentas bancarias» y en Caja → «Cuentas bancarias» (administración).

- **Datos:** banco, tipo (corriente o ahorros), número, titular, RUC o identificación y estado (activa o inactiva).
- **Reglas:**
  - no se repite el mismo banco con el mismo número;
  - las cuentas no se eliminan, se desactivan;
  - hay **una sola predeterminada**.
- **Dónde se usan:**
  - **Presupuestos:** selector en el editor. La cuenta aparece en la **página privada del cliente**, con el botón «Copiar datos bancarios», y en el **PDF**. Sin elección, se usa la predeterminada. No se muestra en presupuestos rechazados ni cancelados.
  - **Facturas:** selector en la ventana de la factura. Se muestra en la vista, se puede copiar y viaja en la información adicional del XML («Cuenta para depósito»).
  - **Depósitos de caja:** cuenta de destino.

## Caja (menú «Caja», todo el personal)
- **Cierre diario por usuario** (fecha de Ecuador). Cada persona cierra **su** caja con los cobros que registró ese día: pagos y devoluciones de órdenes no anulados, y pagos confirmados de licencias, por forma de pago.
  - Si el efectivo contado no coincide con el esperado, hay que explicar la diferencia.
  - Hay un cierre por persona y día. El cierre guarda la foto de los cobros y no se modifica.
  - Los cobros registrados después del cierre se avisan, sin cambiarlo.
- **Depósitos del efectivo:**
  - **Pendiente de depósito:** se registra la cuenta de destino y el monto. No supera el efectivo contado y un reintento no lo duplica.
  - **Depositado:** solo cuando la persona **lo confirma** con la fecha, el número de comprobante y el archivo (JPG, PNG o PDF de hasta 5 MB).
  - **Conciliado:** solo administración. Después no se modifica.
  - **Anulado:** con motivo obligatorio. Un depósito confirmado solo lo anula administración y uno conciliado no se anula.
  - El mismo comprobante no se registra dos veces en la misma cuenta (índice único).
- **Comprobantes de 5 MB en Vercel:** la plataforma no admite peticiones de más de 4,5 MB. Por eso el archivo viaja **por partes** de unos 1,4 MB. El servidor las recompone y verifica el tamaño (5 MB como máximo), el tipo **real** por su firma de bytes y la huella SHA-256. Las partes se borran al completarse.
- **Historial de cierres** con filtros por persona (administración), estado de los depósitos y fechas, más el historial inmutable de cada cierre (`cash_events`).

## Inventario, compras y proveedores (Facturación, solo administración)
- **Artículos:** se incorporan desde el catálogo (categorías «Repuesto» y «Otro»), como producto, repuesto o accesorio, con código interno opcional y único, existencia mínima y ubicación. No se eliminan: se desactivan.
- **Existencias = suma de movimientos.** Los movimientos no se modifican ni se eliminan; una corrección es otro movimiento.
  - **Entradas:** existencia inicial, compra, devolución del cliente y ajuste.
  - **Salidas:** venta, uso en una orden, devolución al proveedor, ajuste y baja.
  - Una salida **nunca deja existencias negativas**: se comprueba en una transacción exclusiva.
  - Un reintento con la misma clave no duplica el movimiento. Un mismo documento no mueve dos veces el mismo artículo (índice único).
- **Alertas:** un artículo activo en su mínimo o por debajo aparece en el aviso del inventario y en el contador de la pestaña.
- **Costo promedio** ponderado de las entradas con costo, y valor del inventario al costo.
- **Licencias digitales:** se muestran en **solo lectura** (disponibles, reservadas y entregadas). Se gestionan en el módulo Licencias.
- **Proveedores:** RUC o cédula validados y sin repetir. No se eliminan: se desactivan.
- **Compras:** Borrador → **Recibida** (registra las entradas una sola vez) → Anulada.
  - El mismo documento del mismo proveedor no se registra dos veces, salvo que la compra anterior esté anulada.
  - Anular una compra recibida registra la salida de lo que entró. Si ya se usó parte y no alcanzan las existencias, se rechaza sin dejar nada a medias.

## Migraciones (solo aditivas)
- `070_electronic_invoicing.sql`: configuración fiscal, secuenciales, facturas, partidas, formas de pago y eventos.
- `071_bank_accounts_cash_closing.sql`: cuentas bancarias, cierres, depósitos, archivos, partes de subida, eventos, y las columnas `quotes.bank_account_id` e `invoices.bank_account_id`.
- `072_inventory_purchases.sql`: artículos de inventario, movimientos, proveedores, compras, partidas y eventos.

No modifican datos existentes. En producción, Vercel no ejecuta `migrate()`: habrá que aplicarlas con respaldo previo y transacción corta, solo cuando se autorice la publicación.

## Entornos de trabajo

| Entorno | Dirección | Código | Base |
|---|---|---|---|
| Producción | ordenes-pro.ecuadorpcdoctor.com | `main` | Turso (no se toca) |
| Sistema local | 127.0.0.1:8010 | `main` | `local/var/ordenes.sqlite3` |
| Copia aislada (protegida) | 127.0.0.2:8011 | `main` | `~/OrdenesPro-CopiaLocal` |
| **Desarrollo** | **127.0.0.3:8012** | **rama** (`~/Work/OrdenesPro-facturacion`) | `~/OrdenesPro-Desarrollo` (con las migraciones 070 a 072) |

## Pendiente (no implementado)
- Firma XAdES-BES y envío al SRI de **certificación**: requiere el certificado .p12, las librerías `cryptography` y `lxml` y una autorización expresa.
- Factura A4 (RIDE en PDF) y ticket térmico de 80 mm (revisar antes `docs/TICKET-TERMICO.md`).
- Botón de factura en las ventas de licencias, notas de crédito, proformas con aprobación del cliente y envío por Mail Pro.
- Descontar existencias automáticamente al facturar o al usar repuestos en una orden (hoy la salida se registra a mano).
- Confirmar con el contador las formas de pago del SRI (tarjeta de crédito, código 19, o de débito, 16) y el tratamiento de los anticipos.
