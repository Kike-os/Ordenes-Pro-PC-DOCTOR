# Caja → Historial y auditoría (1.5.227)

Rediseño de la pestaña de Facturación → Caja → **Historial y auditoría** y de la ventana de detalle de cada cierre. Sin migración: no se
agregan tablas ni se modifica ningún registro. El aviso «MODO DE PRUEBAS — EMISIÓN REAL DESACTIVADA» sigue visible y nada de esto toca la
emisión ni el SRI.

## Revisión del cierre CJ-000002 (producción, solo lectura, 02/11/2026)

En la captura aparecía «Entradas $142,50 · Esperado $0,00 · Contado $0,00 · Diferencia $0,00». Se consultó el cierre en producción sin
escribir nada:

- Tiene una sola operación: PAG-5, cobro de una orden por **depósito bancario** de $142,50, pendiente de verificar en ese momento.
- Fondo inicial $0,00. El efectivo esperado es fondo + entradas en efectivo − salidas en efectivo = **$0,00**: es correcto.
- La foto guardada al cerrar coincide con las operaciones (ingresos $142,50, todo por depósito) y no tiene ajustes.

**No había error de cálculo**, sino de presentación: la columna «Entradas» sumaba todos los medios de pago junto a un «Esperado» que solo
cuenta efectivo, sin explicarlo. No se modificó ningún importe histórico.

## Errores corregidos

- **Tabla comprimida.** 14 columnas cabían en un mínimo de 640 px (unos 45 px cada una): nombres, fechas y estados se partían en varias
  líneas. En el teléfono heredaba la distribución de la tabla de facturas (7 columnas) y las celdas caían en lugares equivocados.
- **Entradas sin separar.** Ahora cada fila muestra, debajo del total, «Efectivo $X · Electrónico $Y» cuando hay pagos electrónicos.
- **Cifras de cajas cerradas.** El historial recalculaba los totales con las operaciones actuales: anular un cobro después del cierre cambiaba
  lo que se veía del cierre. Ahora usa la **foto guardada al cerrar** (inmutable); lo posterior se ve como ajuste. Además evita recalcular
  cada caja en cada consulta.
- **Signo de los negativos** en Caja: «−$5,00» en lugar de «$-5,00».

## Historial

- **Indicadores** con las mismas filas filtradas: cierres registrados (y en curso), correctos, con diferencias (y pendientes de revisión),
  total de entradas (efectivo y electrónico por separado) y total de salidas, sin cajas anuladas.
- **Filtros**: Desde, Hasta, Estado (incluye «Con ajustes posteriores»), Diferencia, Caja, Cajero (solo administración) y Método de pago.
  Se aplican con **Buscar**; **Limpiar filtros** los quita; **Exportar resultados** descarga un CSV (`/api/caja/history.csv`, separador «;»,
  importes con coma decimal, sin fórmulas al abrir en Excel) con los filtros aplicados. Un cajero solo ve y exporta sus propias cajas.
  En el teléfono los filtros van plegados en su panel.
- **Columnas**: N.º de cierre, Fecha y hora (cierre; debajo, la apertura), Responsable, Caja, Turno, Fondo inicial, Entradas, Salidas,
  Efectivo esperado, Efectivo contado, Diferencia, Estado y Acciones. Importes a la derecha en USD con dos decimales.
- **Estados** con indicador discreto: Cerrada correctamente, Cerrada con diferencia, Pendiente de revisión, Anulada, Caja abierta / en
  arqueo, y la marca **Ajustada** cuando el cierre tiene ajustes posteriores. Salen del estado guardado, no se infieren en la interfaz.
- **Acciones** en un menú de tres puntos: Ver detalle, Descargar PDF, Imprimir comprobante térmico (80 mm), Consultar movimientos y
  Consultar auditoría. Con iconos, descripción emergente y estado de carga; teclado (flechas, Inicio, Fin, Escape) y foco de vuelta al botón.
- **Escritorio**: la tabla se desplaza dentro de su marco (la página no), con el número de cierre fijo a la izquierda y las acciones fijas a la
  derecha. **Tabletas** (721–1180 px): sin Caja, Turno ni Fondo inicial. **Teléfono**: una tarjeta por cierre con número, fecha, responsable,
  entradas, diferencia, estado y «Ver detalles».

## Detalle del cierre

- **Información general**: código, caja y turno, apertura, cierre, cajero, quién abrió, quién confirmó y responsable de autorización.
- **Resumen financiero** en tres bloques: **Efectivo del cajón** (fondo, ventas y cobros, otras entradas, salidas, devoluciones, esperado,
  contado y diferencia), **Pagos electrónicos y otros medios** (transferencias, depósitos, tarjetas, cheques y otros; con los pendientes de
  verificar) y **Entradas y salidas por concepto** (cobros de órdenes —pagos y abonos, que el sistema no distingue—, anticipos, licencias).
- **Arqueo por denominaciones**, **Ajustes posteriores** (con motivo y responsable; el cierre original no cambia) y **Auditoría**: cada
  operación con usuario, fecha y hora, tipo, método, valor, referencia y justificación o estado, más el registro de eventos.

## Reporte PDF de tablas (compartido)

`inventory_center.report_pdf` (transferencias y depósitos, Kardex y reportes de inventario) tenía la línea final dibujada a 10 pt del
comienzo de la última fila: si esa fila ocupaba dos líneas, **tachaba la segunda**. Ahora:

- encabezado en franja, filas alternas y separador **debajo de toda la fila**;
- importes («Costo», «Valor», «Precio», «Importe», «Monto») alineados a la derecha; «Saldo» no, porque en el Kardex son unidades;
- un texto de más de tres líneas termina en «…»; los totales pasan a una hoja nueva si no caben sobre el pie;
- pie con el módulo correcto (antes decía «Centro de Inventario» también en transferencias).

En transferencias: método «Depósito»/«Transferencia» (antes «deposito»), fecha 26/10/2026 21:44, filtros con su nombre y anchos para que el
número de orden no se parta.

## Pruebas

- `test_cash_rules.py`: caso como CJ-000002 (depósito con fondo $0 → esperado $0, entrada electrónica), foto del cierre que no cambia al
  anular un cobro después, filtro «ajustada», método, indicadores, CSV con permisos y PDF de transferencias.
- Navegador con datos ficticios (33 comprobaciones): columnas, formato, indicadores, filtros, exportación, menú con teclado, detalle,
  auditoría, movimientos, 1440, 1280, 1024, 820, 390 y 320 px sin desbordamiento, y movimiento reducido.
