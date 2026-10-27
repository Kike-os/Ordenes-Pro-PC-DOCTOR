# Auditoría del Centro de Inventario — 26/10/2026

**Alcance:** solo lectura sobre una copia del respaldo verificado de producción `ordenes-pro-nube-20261026-224237.sqlite3`: íntegro, sin errores de claves foráneas, 72 migraciones. No se modificó ningún dato de producción.

## Cifras del panel comprobadas

| Indicador | Panel | Comprobación | Resultado |
|---|---|---|---|
| Fichas de productos físicos | 11 | 11 fichas activas en `inventory_items` | Correcto |
| Existencias disponibles | 11 | 9 unidades con serie disponibles y 2 productos a granel con 1 cada uno; ninguna reservada | Correcto |
| Saldo del Kardex | — | 11 movimientos de entrada (6 de inventario inicial y 5 de compra); el saldo de cada ficha coincide con sus movimientos y con sus unidades | Sin diferencias |
| Stock bajo | 11 | Las 11 fichas tienen mínimo 1 y existencia 1 | Ver hallazgo 1 |
| Inventario valorizado | $255,36 | Una sola entrada con costo (SSD WD Green WDS480G3G0A, $255,36); las otras 10 entraron con costo 0 | Ver hallazgos 2 y 3 |
| Licencias disponibles, reservadas y entregadas | 31 / 4 / 8 | Iguales a las del módulo Licencias; además hay 8 anuladas, que no se cuentan como existencias | Correcto |
| Garantías próximas a vencer | 0 | Todavía no hay unidades vendidas ni consumidas | Correcto |

No hay series repetidas, fichas con la misma marca y modelo ni nombres de catálogo duplicados. Las 35 marcas se conservan.

## Hallazgos

1. **Las 11 alertas son «en el mínimo», no stock crítico.** La regla anterior marcaba como «stock bajo» toda existencia menor o igual al mínimo, y el asistente proponía mínimo 1 por defecto.
   - **Corrección en el código:** cuatro estados (agotado = 0; crítico = entre 0 y el mínimo; en mínimo = igual al mínimo; normal = sobre el mínimo) y la opción de desactivar las alertas por ficha.
   - **Datos:** los mínimos no se modifican.
2. **10 fichas tienen costo promedio $0,00.** El formulario mostraba el costo como obligatorio, pero el servidor aceptaba el campo vacío y lo guardaba como 0.
   - **Corrección en el código:** el costo pasa a ser obligatorio al registrar (0 solo si se indica expresamente).
   - **Datos:** los movimientos originales no se modifican. Se añade la **corrección de costo auditada**: con su motivo, queda en el Kardex y recalcula el costo promedio. Los costos reales los debe indicar administración.
3. **$255,36 por un SSD SATA de 480 GB** es un costo inusualmente alto para ese producto: posible error de digitación. Lo debe confirmar administración y, si corresponde, corregirlo con la corrección de costo.
4. **Licencia con duración posiblemente mal registrada:** «Kaspersky Standard – Licencia Antivirus de Duración Ilimitada, 1 dispositivo» tiene en su ficha la duración **Anual**, con 4 disponibles. No se cambia automáticamente; el Centro la marca como «Revisar duración».
5. **Posibles marcas repetidas:** «WD GREEN» y «WD Blue» son líneas de Western Digital, marca que ya existe. Tampoco se cambian; quedan señaladas para revisión.
6. **Licencias sin marca:** «Licencia de Microsoft 365 Empresarial», «Microsoft 365 Education» y «Norton 360 Standard» no tienen marca en el catálogo (sí la tienen en su clasificación).
7. **Productos de licencia sin unidades:** «Kaspersky Standard – Licencia Antivirus de 1 Año» y «Microsoft Office Professional Plus 2024» tienen 0 licencias registradas.
