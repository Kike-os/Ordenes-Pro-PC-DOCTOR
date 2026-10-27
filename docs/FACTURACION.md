# Facturación, caja, inventario y cuentas bancarias (MODO DE PRUEBAS)

> 1.5.206: interfaz rediseñada (pestañas con iconos, indicadores con datos reales, búsqueda y tabla de facturas, ventanas compactas). El inventario se gestiona en el **Centro de Inventario** (ver `docs/INVENTARIO.md`); la pestaña «Inventario» de Facturación muestra un resumen y el acceso.

**Estado:** integrado en Órdenes Pro desde la 1.5.205, en el menú **«Facturación»** (solo administración; hasta la 1.5.205 se llamaba «Facturación Electrónica»). Funciona en **MODO DE PRUEBAS** (`invoicing.TEST_MODE = True`, fijado en el servidor):

- La **emisión real está desactivada** y no se puede activar desde la interfaz. **No hay conexión con el SRI**, ni de pruebas ni de producción. Se activará solo con la firma electrónica y una autorización expresa.
- Todo lo que se registre en el módulo es **de prueba**: facturas, cajas, depósitos, inventario, compras, proveedores, cuentas y datos fiscales.
  - Queda solo en las tablas propias del módulo (migraciones 070 a 072).
  - **Ningún registro existente se modifica**: clientes, órdenes, presupuestos, pagos, licencias ni citas.
- **Los clientes no ven ningún cambio:** los datos bancarios no aparecen en la página ni en el PDF del presupuesto, y el selector de cuenta del presupuesto está oculto (el servidor lo rechaza).
- **La caja solo la usa administración**, como una pestaña del módulo. La dirección antigua `#cash` abre esa pestaña.
- Nada de este módulo mueve dinero, se conecta con bancos ni envía correos.

**Antes de la activación real** (cuando haya firma y autorización):
1. Respaldo verificado de la nube.
2. Vaciar las tablas del módulo con una migración propia (los datos de prueba no se mezclan con los reales).
3. Poner `TEST_MODE = False`. Así se activan los datos bancarios para el cliente y la caja para todo el personal.

## Normativa de referencia
Ficha técnica de comprobantes electrónicos del SRI, esquema offline, **v2.34** (julio de 2026):

- **Consumidor final:** «Si el valor de la factura es mayor a 50 USD se deberá especificar obligatoriamente los datos del adquirente» (9.10). Se identifica con el tipo 07 y el número 9999999999999.
- **Clave de acceso:** 49 dígitos con módulo 11. El ejemplo oficial `41261533` da 6 y es una de las pruebas.
- **IVA:** el 15 % es el código 4 y el 0 % el código 0 (tabla 17).
- **Firma:** XAdES-BES 1.3.2, *enveloped*, RSA-SHA1 con clave de 2048 bits. Pendiente de implementar.
- **Servicios web:** de pruebas, `celcer.sri.gob.ec`, y de producción, `cel.sri.gob.ec`. No se usan todavía.

## Facturas (pestaña «Facturas»)

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
Están en Facturación → «Cuentas bancarias» (administración). En modo de pruebas no se muestran al cliente.

- **Datos:** banco, tipo (corriente o ahorros), número, titular, RUC o identificación y estado (activa o inactiva).
- **Reglas:**
  - no se repite el mismo banco con el mismo número;
  - las cuentas no se eliminan, se desactivan;
  - hay **una sola predeterminada**.
- **Dónde se usan:**
  - **Presupuestos:** selector en el editor. La cuenta aparece en la **página privada del cliente**, con el botón «Copiar datos bancarios», y en el **PDF**. Sin elección, se usa la predeterminada. No se muestra en presupuestos rechazados ni cancelados.
  - **Facturas:** selector en la ventana de la factura. Se muestra en la vista, se puede copiar y viaja en la información adicional del XML («Cuenta para depósito»).
  - **Depósitos de caja:** cuenta de destino.

## Caja (pestaña «Caja»; al activarse, todo el personal)
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

## Inventario, compras y proveedores (pestañas propias)
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

No modifican datos existentes. En producción, Vercel no ejecuta `migrate()`: se aplican con un guion, con respaldo previo y una transacción corta por migración, y se comprueba que las tablas existentes conservan sus recuentos.

## Entornos de trabajo

| Entorno | Dirección | Código | Base |
|---|---|---|---|
| Producción | ordenes-pro.ecuadorpcdoctor.com | `main` | Turso (no se toca) |
| Sistema local | 127.0.0.1:8010 | `main` | `local/var/ordenes.sqlite3` |
| Copia aislada (protegida) | 127.0.0.2:8011 | `main` | `~/OrdenesPro-CopiaLocal` |
| Desarrollo | 127.0.0.3:8012 | rama (`~/Work/OrdenesPro-facturacion`) | `~/OrdenesPro-Desarrollo` (con las migraciones 070 a 072) |

## Volver a la 1.5.204 si surge un inconveniente
Las migraciones 070 a 072 **solo añaden** tablas, índices, disparadores y dos columnas vacías (`quotes.bank_account_id`, `invoices.bank_account_id`). La 1.5.204 funciona con ese esquema. Está comprobado: su batería completa pasa con las migraciones añadidas, y todos sus módulos responden con una copia migrada del respaldo. Por eso **no hace falta revertir la base**.

1. **Código:** en Vercel, promover el despliegue anterior de la 1.5.204.
   - Desde el panel: *Deployments* → despliegue de la 1.5.204 → *Promote to Production*.
   - O desde la raíz del repositorio: `vercel ls` y luego `vercel promote <url-del-despliegue-1.5.204> --yes` (o `vercel rollback`).
   - Comprobar con `curl -s https://ordenes-pro.ecuadorpcdoctor.com/api/public/version`.
2. **Repositorio:** `git revert` del commit de la versión en una rama de pruebas. Nunca `reset --hard` ni `push --force`.
3. **Base:** no se toca. Si alguna vez hiciera falta volver al estado anterior a la migración, existe el respaldo verificado `~/Respaldos-OrdenesPro/ordenes-pro-nube-AAAAMMDD-HHMMSS.sqlite3`, tomado justo antes de migrar. Restaurarlo exige una autorización expresa, porque se perderían los registros posteriores.

## Pendiente (no implementado)
- Firma XAdES-BES y envío al SRI de **certificación**: requiere el certificado .p12, las librerías `cryptography` y `lxml` y una autorización expresa.
- **Proformas** con PDF y logo, envío por correo o WhatsApp con enlace seguro, aprobación o rechazo por el cliente (últimos 4 dígitos de la cédula y código al correo), con evidencia; y conversión de la proforma aprobada en factura.
- Notas de crédito, anticipos y abonos.
- Factura A4 (RIDE en PDF) y ticket térmico de 80 mm (revisar antes `docs/TICKET-TERMICO.md`).
- Botón de factura en las ventas de licencias, notas de crédito, proformas con aprobación del cliente y envío por Mail Pro.
- Descontar existencias automáticamente al facturar o al usar repuestos en una orden (hoy la salida se registra a mano).
- Confirmar con el contador las formas de pago del SRI (tarjeta de crédito, código 19, o de débito, 16) y el tratamiento de los anticipos.

## Políticas comerciales y documentos de la factura (rama `politicas-comerciales`)

**Facturación › Configuración › Políticas Comerciales** administra el documento «Políticas de Venta, Cambios, Devoluciones y Garantías — PC-DOCTOR S.A.».

- **Sin texto incluido:** el texto corporativo no viene con el sistema. Lo carga administración y se usa la versión validada legalmente; Órdenes Pro no redacta condiciones.
- **Versiones:** hay un borrador por alcance, para productos físicos y servicios o para productos digitales (licencias). Para publicarlo se exige:
  - el texto completo (al menos 200 caracteres);
  - el nombre de quien hizo la validación legal;
  - la confirmación expresa de esa validación.
- **Inmutable:** una versión publicada no se modifica ni se elimina (lo impiden disparadores de la base). La anterior pasa a archivada.
- **Asociación:** al emitir una factura se asocia la versión vigente de su alcance; una factura con productos físicos y digitales recibe las dos. Los cambios posteriores no alteran lo ya asociado. Las facturas emitidas antes de publicar una versión quedan sin política: no se reescribe la historia.
- **Formato del texto:** `# Título` para secciones, `1.1 Subtítulo` en una línea corta y `- ` para viñetas.
- **PDF:** incluye el logo original, el título, el código, la versión y la fecha de vigencia, los datos de la factura y del cliente, el contacto, y un pie con la numeración «Página n de N».

**Documentos de cada factura emitida** (en el detalle de la factura):
- **RIDE en PDF:** emisor con el logo, número, autorización, ambiente, clave de acceso con código de barras, comprador, detalle, totales y formas de pago. Mientras no esté autorizado por el SRI en producción, cada página dice «DOCUMENTO DE PRUEBA — SIN VALIDEZ TRIBUTARIA».
- **Políticas asociadas** en PDF.
- **Certificado de garantías:** cada unidad facturada o consumida en la orden, con su nombre, marca, modelo, SKU, código interno, serie original y las dos coberturas por separado con sus fechas. Se toman del Centro de Inventario.

**Envío:**
- **Al cliente:** solo de facturas **autorizadas por el SRI en producción**. Se hace una sola vez por factura, con hasta 3 intentos controlados, y cada resultado queda registrado (no se elimina). Lleva RIDE, XML autorizado, políticas y garantías.
- **Reenvío manual:** solo de facturas autorizadas.
- **Prueba:** solo a la dirección configurada. El asunto empieza por «[PRUEBA — SIN VALIDEZ TRIBUTARIA]».
- **Cómo sale el correo:** por el correo institucional, con copia archivada y seguimiento de entrega.
- **Enganche con el SRI:** `invoice_documents.on_authorized` deja preparado el envío automático. Se conectará cuando exista la autorización real del SRI; mientras la Facturación siga en modo de pruebas, no sale nada al cliente.
