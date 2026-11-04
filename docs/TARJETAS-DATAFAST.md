# Facturación → Tarjetas y DATAFAST (1.5.232)

Rediseño de la pantalla de configuración de tarjetas. **No cambia ningún factor, combinación, regla ni cálculo**: los factores siguen en la
base (tabla DATAFAST 6.2 de la migración 076), el simulador sigue calculando en el servidor (`card_finance.simulate`) y el recargo comercial
se guarda igual, con su historial. Sin migración.

## Resumen superior (datos reales)

Grupos configurados (con combinaciones activas, de los existentes), bancos habilitados, combinaciones banco · marca · categoría, plazos con
al menos un factor vigente y factores pendientes (por confirmar o sin configurar). Lo calcula `card_finance.factor_table` (`summary`).
Con los datos actuales: 10 de 10 grupos, 8 bancos, 46 combinaciones, 11 de 11 plazos y ningún factor pendiente.

**Grupo J a 36 meses (migración 087, 1.5.233):** quedó pendiente en la 076 porque la cifra no era legible en el texto del PDF. Con la tabla
original DATAFAST 6.2 enviada por administración el 03/11/2026 se confirmó **26,67 %**. La fila pendiente (sin valor) se completó con la
misma versión de la tabla y su nota conserva el estado anterior; un factor pendiente sigue sin poder usarse para cobrar.

## Tabla de factores

- Encabezados A–J fijos al desplazarse en vertical y columna de meses fija al desplazarse en horizontal; la tabla se desplaza dentro de su
  marco (no hace crecer la página). Fila resaltada bajo el cursor, cifras alineadas y líneas discretas.
- Filtros por **grupo**, **plazo** y **banco** (muestra los grupos que contienen ese banco), **búsqueda de porcentaje** (resalta las
  coincidencias y cuenta cuántas hay) y «Limpiar».
- Cada celda muestra su estado real (ver «Estados y confirmación»); ningún valor se rellena ni se estima.

## Grupos bancarios

Tarjetas por grupo con su código, número de combinaciones, bancos, marcas y categorías, logos de los bancos (los mismos de «Registrar
pago»; sin logo, sus iniciales), etiquetas por marca (Visa, Mastercard, Diners, Discover, American Express, Pacificard) y dos acciones:
**Combinaciones** (despliega banco → marca → categorías) y **Ver factores** (filtra la tabla a ese grupo). Búsqueda por banco, marca o
categoría y «Expandir todo / Contraer todo».

## Simulador

El simulador de cuotas también está dentro de esta pantalla. Su desglose: valor original, porcentaje y valor del recargo, base de cálculo
de intereses, factor financiero aplicado, valor de intereses, total final y cuota mensual. Es el mismo cálculo que usan las ventas y el
registro de pagos.

## Recargo comercial

Vista de lectura con **Editar** → formulario con **Guardar cambios** (estado «Guardando…») y **Cancelar** (descarta lo escrito). El motivo
del cambio sigue siendo obligatorio y queda en el historial.

## Pruebas

- `test_card_finance.py`: la pantalla recibe exactamente los factores de la tabla DATAFAST (incluido el pendiente) y las 31 combinaciones
  autorizadas en su grupo; el resumen coincide con lo guardado.
- Navegador con la tabla de la migración en una base temporal (13 comprobaciones): resumen, valores exactos, encabezados y columna fijos,
  filtros, búsqueda, grupos, despliegue con teclado, «Ver factores», simulador ($140,00 + 9 % = $152,60; 2,63 % = $4,01; total $156,61 en
  3 cuotas de $52,20), Editar/Cancelar/Guardar del recargo con persistencia, 1440, 1024, 390 y 320 px sin desbordamiento.

## Verificación con la tabla original (03/11/2026, 1.5.233)

Se comparó la tabla DATAFAST 6.2 enviada por administración con la base, celda por celda: los **110 porcentajes coinciden** (10 grupos × 11
plazos, con el 26,67 % del grupo J a 36 meses). Faltaban **15 combinaciones de Banco Diners** que la tabla incluye y la 076 no había cargado
(migración 088, solo añade):

| Categoría (grupo) | Ya estaba | Se añaden |
| --- | --- | --- |
| Corporativa (B), Empresarial (C), PYMES (D) | Diners | Visa Titanium, Mastercard Titanium |
| Minorista (E), Simple (F), Ampliado (G) | Diners | Discover, Visa Titanium, Mastercard |

El asterisco (*) de las categorías corporativas, empresariales y PYMES de la tabla no tiene una nota explicativa en el documento.

## Estados y confirmación administrativa (04/11/2026, 1.5.235)

**Origen del aviso:** la pantalla mostraba siempre una leyenda fija («Pendiente de confirmar», «Sin configurar» y «Ningún valor se
rellena…»), aunque no hubiera ningún factor en esos estados. La auditoría de producción del 04/11/2026 (solo lectura) dio 110 factores
vigentes, 0 pendientes, 0 sin configurar, sin duplicados, todos de la tabla 6.2 vigente desde el 01/10/2026, y las 46 combinaciones con
grupo. Cotejo automático con el PDF original: 107 valores coinciden con el texto, I-6 y J-6 coinciden pero el texto los desplaza de
columna (el 4,59 % de I está impreso en otra línea), y J-36 (26,67 %) se leyó de la imagen.

Estados (los calcula `card_finance.factor_state`; la leyenda muestra los recuentos guardados y filtra la tabla):

| Estado | Significado | ¿Sirve para cobrar? |
|---|---|---|
| Confirmado | Administración lo cotejó y confirmó ese mismo porcentaje (con nombre, fecha y hora) | Sí |
| Verificado · falta confirmar | Cargado de la tabla oficial por migración y cotejado, sin confirmación administrativa registrada | Sí (decisión de administración del 04/11/2026) |
| Pendiente de confirmar | Sin valor (o en revisión) | No: el servidor rechaza el cobro |
| Sin configurar | No existe fila para ese grupo y plazo | No |
| Inactivo | Fuera de su vigencia (`valid_from`/`valid_to`) | No |

Procedimiento (solo administración; el servidor comprueba el permiso, el CSRF, el cotejo marcado y el porcentaje visto):
- **Confirmar un factor:** pulsar la celda → «Confirmar este valor», marcar el cotejo con la tabla original e indicar el documento.
- **Confirmar varios:** filtrar (grupo, plazo, banco, estado) → «Confirmar N factores» → la ventana lista cada porcentaje. Si alguno
  cambió mientras se revisaba, no se confirma ninguno. Los ya confirmados se omiten.
- **Completar / corregir / configurar:** desde la misma ventana. Un pendiente se completa en su fila. Una corrección deja la fila
  anterior «reemplazado» (no se borra) y crea la nueva (versión «6.2 · corr. N»). El nuevo valor queda confirmado por quien lo validó.
- Registro: `card_factor_confirmations` (migración 090, solo añade). No se modifica ni se borra (disparadores). Historial por factor en la ventana.
- Los cobros, proformas y facturas ya emitidos guardan su propio cálculo: corregir un factor no los altera.
- El recargo comercial (9 %) sigue separado del factor financiero. «Diferido sin intereses» usa 0 %.

Pruebas: `test_card_factor_confirm.py` cubre estados, bloqueo de pendientes e inactivos, confirmación individual y por lotes, lote con un
porcentaje desactualizado (no confirma nada), registro inalterable, completar, corregir con historial, proforma emitida intacta y permisos.
