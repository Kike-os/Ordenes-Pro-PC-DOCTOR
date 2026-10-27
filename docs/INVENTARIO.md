# Centro de Inventario

Módulo de administración de Órdenes Pro para registrar la mercadería física y consultar las licencias digitales de PC-DOCTOR S.A.

Para abrirlo, entra con una cuenta de administración y elige **Inventario** en el menú principal (dirección `#inventory`).

El menú lateral agrupa las secciones en **Resumen** (Panel general, Alertas), **Productos** (Catálogo, Categorías y marcas, Licencias digitales), **Operaciones** (Registrar mercadería, Registrar salida, Inventario inicial, Movimientos, Kardex) y **Control** (Garantías, Reportes, Configuración). En escritorio se puede plegar y el equipo lo recuerda; en tableta y móvil se abre como un menú desplegable que se cierra con Escape.

## Estados de existencias y alertas

| Estado | Condición |
|---|---|
| Agotado | existencias en 0 |
| Crítico | por debajo del mínimo |
| En el mínimo | igual al mínimo |
| Normal | por encima del mínimo |

- Las alertas urgentes (agotado y crítico) cuentan en el aviso del menú; «en el mínimo» queda como pendiente de reposición.
- En **Alertas** se pueden desactivar las alertas de un producto sin reposición automática; se pueden volver a activar en cualquier momento.
- **Revisión de datos** muestra, sin cambiar nada, entradas con costo pendiente, marcas posiblemente duplicadas, licencias sin marca y duraciones por revisar.

## Entorno de pruebas persistente

El entorno de pruebas es la instancia de desarrollo `http://127.0.0.3:8012`:
- Servicio `ordenes-pro-desarrollo`.
- Base `~/OrdenesPro-Desarrollo/ordenes.sqlite3`.

Esa instancia no tiene Turso ni correo, y la conexión con el SRI de producción está bloqueada. Lo que registres ahí se conserva al cerrar sesión y al reiniciar el servicio, y no se mezcla con producción.

La instancia aislada del puerto 8011 y la base de producción no se tocan.

## Tres identificadores

| Identificador | Qué identifica | Dónde vive |
|---|---|---|
| SKU | El modelo comercial | Ficha del producto (opcional, único). |
| Serie original | La unidad, según el fabricante | Unidad (opcional, única). Se detecta aunque cambien los espacios o las mayúsculas. |
| Código interno | La unidad dentro de PC-DOCTOR | Unidad (`PCD-<PREFIJO>-000001`, único y nunca reutilizado). |

Cada categoría tiene su prefijo, por ejemplo SSD, NVME, HDD, RAM, FUE, PLM, LAP, IMP, AV o M365. Una subcategoría sin prefijo propio usa el de su categoría principal.

Un prefijo pertenece para siempre a la categoría que lo creó, y su numeración nunca retrocede. Si una categoría cambia de prefijo y después vuelve al anterior, la numeración continúa donde quedó.

Los productos a granel, como cables o consumibles, se registran por cantidad, sin crear unidades.

## Registrar el primer producto

El registro es un asistente de cinco pasos: **Producto**, **Unidades**, **Datos comerciales**, **Garantías** y **Confirmación**.

1. Abre **Inventario › Inventario inicial**.
2. **Categoría y subcategoría:** por ejemplo, *Almacenamiento › SSD SATA 2.5"*.
3. **Producto:** elige uno existente o pulsa **Producto nuevo**.
   - Escribe la marca y el modelo; el nombre se propone solo.
   - Indica el SKU, el precio de venta y la existencia mínima.
   - Configura las dos garantías: la de PC-DOCTOR y la del fabricante, cada una en días, meses o años y desde la venta o desde la entrega.
4. **Unidades:** con el cursor en el campo de la serie, escanea con el lector USB. El lector escribe la serie y envía Enter, y la unidad se agrega a la lista.
   - Una serie repetida, en la lista o ya registrada, se rechaza y se indica su código interno.
   - Si el fabricante no puso serie, pulsa **Agregar sin serie**.
5. **Costo y ubicación:** costo unitario sin IVA (obligatorio; se puede escribir 0,00 a propósito), proveedor, documento, IVA y ubicación física.
6. **Guardar y generar códigos:** se crea el movimiento de apertura del Kardex y se muestran los códigos internos. Desde ahí puedes **Imprimir etiquetas**.

**Registrar mercadería** funciona igual, con el motivo *Compra* o *Ajuste autorizado*.

**Importar desde Excel o CSV** (en Inventario inicial) muestra una vista previa con las filas válidas y las que tienen error, incluidas las series duplicadas. No importa nada si alguna fila tiene error. La plantilla se descarga desde la misma sección.

## Kardex

- **Costo:** promedio ponderado móvil. Cada entrada se promedia con el saldo que queda y las salidas salen al promedio vigente.
- **Qué registra:** inventario inicial, compras, ventas, consumo en órdenes, devoluciones, ajustes y bajas.
  - Las reservas y los traslados se muestran sin cambiar el saldo.
- **Inmutable:** los movimientos no se modifican ni se eliminan. Una corrección es otro movimiento, trazable.
- **Filtros:** fecha, categoría, marca, producto, serie o código, movimiento y responsable.
- **Período:** Hoy, últimos 7 o 30 días, este mes o personalizado; los indicadores comparan con el período anterior de igual duración.
- **Por producto:** al elegir un producto se muestra su saldo inicial del período, entradas, salidas, ajustes y saldo final.
- **Costo pendiente:** una entrada registrada con costo 0 se marca así. **Corregir costo** (solo entradas manuales, no compras) guarda el costo original, el nuevo, el motivo, el documento, el usuario y la fecha; el movimiento original no se modifica y el promedio se recalcula con la corrección.
- **Exportación:** Excel (.xlsx, columnas numéricas), PDF (logo, fecha, filtros, totales y numeración de páginas) y CSV.
- **Reportes:** Kardex general, por producto, por categoría, entradas y salidas por período, inventario valorizado, productos sin costo, ajustes y correcciones, y movimientos por responsable.

## Ficha de producto y ventas

La ficha tiene cinco pestañas: **Resumen**, **Unidades y series**, **Ventas y precios**, **Garantías** y **Kardex e historial**. Muestra avisos discretos de datos faltantes (precio, costo, garantías, ubicación) sin completarlos por su cuenta.

- **Configurar precios:** precio mínimo y descuento máximo autorizado.
- **Vender producto:** se elige la unidad (o la cantidad), el cliente y el precio con IVA. Un precio de 0,00, por debajo del mínimo o con un descuento mayor al autorizado exige marcar la autorización administrativa y escribir el motivo; queda registrada en el movimiento.
- No se pueden vender unidades agotadas, entregadas ni reservadas para otra operación.
- **Reservar producto:** cliente, motivo y vencimiento; reduce lo disponible, no las existencias.
- Las garantías empiezan a correr con el evento configurado (venta o entrega), nunca antes.

## Salidas sin doble descuento

- Una reserva aparta existencias sin descontarlas. Nadie más puede sacar la unidad reservada hasta que se libere o se use.
- Una venta o un consumo confirmado genera una sola salida. Reintentar el mismo envío no la duplica.
- Una orden técnica no puede descontar dos veces el mismo producto.
- Al facturar una orden, lo que ya se consumió en ella no se vuelve a descontar.
  - Función `inventory_center.invoice_exit`, probada.
  - **No está conectada todavía a la emisión de facturas:** la Facturación sigue en modo de pruebas y una factura de prueba no debe mover el inventario real.

## Garantías

En cada unidad vendida o consumida se guardan por separado las fechas de inicio y fin de las dos coberturas. Si una garantía cuenta desde la entrega, se fecha al registrar la entrega.

El panel **Garantías** muestra para cada cobertura:
- los días restantes;
- la fecha de vencimiento;
- una barra de color: verde con más de la mitad restante, amarilla con más del 20 % y roja con el 20 % o menos;
- el cliente, la orden, la factura o el documento.

Una garantía vencida conserva su historial.

## Licencias digitales

Las licencias siguen registrándose en el módulo **Licencias**, con sus claves cifradas que solo ve administración. El Centro de Inventario no guarda una segunda existencia.

El Centro las clasifica por **Categoría → Marca → Familia → Edición**, por ejemplo *Antivirus › Kaspersky › Kaspersky › Plus* o *Microsoft › Microsoft 365 › Personal*. Muestra las existencias reales: disponibles, reservadas, entregadas y vencidas.

Al registrar una licencia nueva de un producto ya clasificado, recibe el código de su categoría (`PCD-AV-000001`, `PCD-M365-000001`). Las licencias ya registradas conservan su código `LIC-`.

Las familias y ediciones son configurables. Describen lo que existe; no implican que esté a la venta.

## Integraciones

| Integración | Estado |
|---|---|
| Catálogo (presupuestos y facturas) | Operativa: cada ficha crea o enlaza su producto del catálogo. |
| Consumo en órdenes técnicas | Operativa desde **Movimientos › Registrar salida** (con el número de orden). |
| Ventas | Operativa desde **Movimientos › Registrar salida**, con cliente, documento y garantías. |
| Licencias digitales | Operativa: clasificación y existencias desde el módulo Licencias. |
| Compras de Facturación | Operativa: al recibir una compra de un producto por serie se crean sus unidades con código interno (la serie se agrega después). |
| Descuento automático al facturar | Preparada y probada; se conectará al activar la facturación real. |
| Reserva automática desde presupuestos y proformas | Pendiente. |
| Consumo desde la ficha de la orden | Pendiente: por ahora se registra desde el Centro con el número de orden. |

## Licencias digitales en tabla

**Licencias digitales** muestra una tabla por producto con disponibles, reservadas y entregadas, filtros por marca y estado, y nunca las claves. Si el nombre dice «ilimitada» pero la duración registrada es anual, se marca para revisar; no se cambia sola.

## Traslado futuro a producción

**Configuración › Descargar paquete de traslado** genera un JSON con:
- categorías, prefijos, marcas y familias;
- fichas, unidades con sus códigos y series, y todo el Kardex.

No incluye claves de licencias ni datos de clientes. La importación controlada a producción queda **pendiente de autorización** y no se hace automáticamente.

## Pruebas

```bash
python -m unittest discover -s local/tests -p 'test_inventory*.py'
```

Las pruebas usan una base temporal con datos ficticios. Cubren:
- códigos por categoría y prefijos que no se reutilizan;
- series duplicadas y unidades sin serie;
- productos a granel;
- inventario inicial y Kardex valorizado;
- venta, consumo en orden y ausencia de doble descuento (también al facturar);
- reservas y traslados;
- garantías;
- licencias de Kaspersky, Norton, McAfee y Microsoft clasificadas;
- importación;
- etiquetas, exportaciones y permisos;
- estados de existencias, alertas desactivables y costo obligatorio;
- corrección de costo auditada, precios, ventas con autorización y reservas con vencimiento;
- totales del Kardex por período, los 8 reportes y la revisión de datos.
