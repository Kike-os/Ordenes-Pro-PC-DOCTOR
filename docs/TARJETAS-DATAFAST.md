# Facturación → Tarjetas y DATAFAST (1.5.232)

Rediseño de la pantalla de configuración de tarjetas. **No cambia ningún factor, combinación, regla ni cálculo**: los factores siguen en la
base (tabla DATAFAST 6.2 de la migración 076), el simulador sigue calculando en el servidor (`card_finance.simulate`) y el recargo comercial
se guarda igual, con su historial. Sin migración.

## Resumen superior (datos reales)

Grupos configurados (con combinaciones activas, de los existentes), bancos habilitados, combinaciones banco · marca · categoría, plazos con
al menos un factor vigente y factores pendientes (por confirmar o sin configurar). Lo calcula `card_finance.factor_table` (`summary`).
Con los datos actuales: 10 de 10 grupos, 8 bancos, 31 combinaciones, 11 de 11 plazos y ningún factor pendiente.

**Grupo J a 36 meses (migración 087, 1.5.233):** quedó pendiente en la 076 porque la cifra no era legible en el texto del PDF. Con la tabla
original DATAFAST 6.2 enviada por administración el 03/11/2026 se confirmó **26,67 %**. La fila pendiente (sin valor) se completó con la
misma versión de la tabla y su nota conserva el estado anterior; un factor pendiente sigue sin poder usarse para cobrar.

## Tabla de factores

- Encabezados A–J fijos al desplazarse en vertical y columna de meses fija al desplazarse en horizontal; la tabla se desplaza dentro de su
  marco (no hace crecer la página). Fila resaltada bajo el cursor, cifras alineadas y líneas discretas.
- Filtros por **grupo**, **plazo** y **banco** (muestra los grupos que contienen ese banco), **búsqueda de porcentaje** (resalta las
  coincidencias y cuenta cuántas hay) y «Limpiar».
- «Pendiente de confirmar» y «Sin configurar» se marcan; ningún valor se rellena: un pendiente no se puede usar para cobrar.

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
