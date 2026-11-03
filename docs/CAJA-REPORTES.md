# Reportes de cierre de caja: A4 y ticket de 80 mm

Módulo `local/cash_report.py` (lo usa `cash_sessions.report_pdf`; misma ruta protegida `/api/caja/sessions/<id>/report.pdf`, con
`?formato=termico` para el ticket). Solo lee: no modifica transacciones, saldos ni cierres. Sin migración.

## Errores corregidos

| Error | Causa | Corrección |
| --- | --- | --- |
| RUC vacío («RUC —») | Se buscaba en `corporate.json`, que no tiene ese dato | Se toma de Facturación › Datos fiscales; si falta, el reporte lo dice en rojo y no inventa uno |
| «Turno Mañana» en aperturas nocturnas | El desplegable no proponía turno y quedaba la primera opción | Se propone según la hora de Ecuador (Mañana 05:00–11:59, Tarde 12:00–17:59, Noche desde las 18:00); el cajero puede cambiarlo. Los cierres ya registrados no se modifican |
| Ticket de 77,6 mm (220 pt) | Ancho fijo de 204 pt más márgenes | 72 mm útiles exactos (204,09 pt, el RP80 del PPD de la TM-m30II), margen de 1 mm, altura según el contenido: la Epson lo acepta sin escalar |
| QR cortado al final del ticket | La altura no reservaba su espacio | La altura se calcula después de componer todo; el QR va alineado a la rejilla de 203 ppp con su zona de silencio |
| A4 con media página en blanco | Texto corrido sin estructura | Encabezado, franja de datos, resumen ejecutivo en tres bloques, tablas y firmas |
| Hora de generación del servidor | `datetime.now()` sin zona: en Vercel (UTC) salía 5 h adelantada | Hora de Ecuador |
| Número de cuenta completo en el reporte | Se imprimía la etiqueta de la cuenta tal cual | Solo los 4 últimos dígitos (•••• 2424) |
| Signos «−» y «→» como «?» | La fuente del PDF (Helvetica, WinAnsi) no los tiene | Se usan «-» y «›» |

## Contenido

**A4** (varias páginas cuando hace falta; encabezado reducido y «Página n de N» con la fecha de generación en todas):

1. Logo original sin modificar, razón social y RUC de los datos fiscales, dirección y contactos; título, código del cierre, estado y QR.
2. Franja con caja, turno, cajero, quién abrió, apertura, cierre, quién confirmó y quién autorizó.
3. **Resumen ejecutivo** en tres bloques que no se suman entre sí: *Recaudación del período* (ventas y cobros, otros ingresos, total; por
   medio: efectivo, transferencias, depósitos, tarjetas y otros; egresos), *Movimiento de efectivo* (fondo + entradas − salidas = esperado)
   y *Saldo de caja* (esperado, contado, diferencia con su estado, entregado y fondo reservado).
4. Tablas de **ingresos**, **egresos**, **transferencias y depósitos** (banco, tipo de cuenta, últimos 4 dígitos, referencia, fecha y estado
   de confirmación actual) y **tarjetas** (marca, banco o procesador, tipo, lote, referencia y autorización). Solo las que aplican; cada una
   con su total de control. Los anulados se muestran en gris y no suman.
5. **Arqueo por denominaciones** del conteo guardado al cerrar; si no se registraron, «Desglose no registrado». Esperado, contado,
   diferencia, estado (Cuadrado / Sobrante / Faltante), explicación, observaciones y responsable del conteo.
6. Ajustes posteriores (si hay), **controles de integridad** calculados (suma por medio = total; ventas + otros = total; fondo + entradas −
   salidas = esperado; ninguna operación repetida; contado − esperado = diferencia; entregado + reservado = contado) y firmas, que nunca
   quedan solas en una hoja.

**Ticket de 80 mm**: logo monocromo, empresa y RUC, código, estado, datos del turno, resumen, efectivo del cajón, cada operación (con fecha,
documento y referencia), transferencias y tarjetas, arqueo con denominaciones, estado final, firmas y QR. Letra de 7,2 a 15 pt.

**QR**: la misma ruta protegida del reporte. Sin sesión responde 401 y sin permiso 403 (un técnico no ve la caja de otro).

## Historial: acciones

Menú de tres puntos en dos grupos. **Consultar**: resumen del cierre, movimientos, arqueo y auditoría. **Documentos**: descargar PDF A4,
descargar ticket de 80 mm, imprimir A4 e imprimir ticket. El detalle del cierre tiene los mismos botones de documentos y muestra siempre el
arqueo.

## Pruebas

- `test_cash_rules.py`: réplica de CJ-000002 (valores conservados, controles correctos, cuenta enmascarada, sin denominaciones), RUC de los
  datos fiscales, ticket de 72 mm y una página, permisos y turno propuesto.
- Nueve escenarios ficticios (sin movimientos, efectivo, solo depósito, transferencias, tarjetas, mixto, egresos con faltante, sobrante y 54
  operaciones con nombres y referencias largas): ningún texto fuera de la página, QR leídos con `zbarimg` a 203 ppp y los nueve tickets
  procesados por el controlador real de la Epson TM-m30II con `print-thermal.py --render-only` (sin imprimir).
