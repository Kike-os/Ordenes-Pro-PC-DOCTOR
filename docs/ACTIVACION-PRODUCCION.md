# Activar la facturación electrónica REAL (producción) con AZUR

Punto de emisión decidido: **001-010**, el mismo que usaba el sistema anterior. Órdenes Pro **continúa** su numeración. Última factura del
sistema anterior: **001-010-000000275** (04/11/2026, ambiente 2), así que la primera de Órdenes Pro será la **000000276**.

## Candados (todos deben estar abiertos para emitir una factura real)

1. `FACTURACION_AMBIENTE=produccion` **y** `AZUR_PRODUCCION_AUTORIZADA=SI` en las variables del servidor (Vercel). Con una sola, el
   sistema sigue en pruebas.
2. Una credencial de AZUR de producción (`sk_live_…`) en `AZUR_CREDENCIAL`, junto con la clave de emisión de producción en
   `AZUR_API_KEY_EMISION`. Si la credencial es de pruebas y el servidor está en producción (o al revés), el panel lo marca y no envía.
3. El secuencial inicial fijado en **Facturación → Integración SRI → Secuencial de producción** (`275`, confirmando con
   `FIJAR SECUENCIAL`). Sin ese dato no se emite en producción. Se puede fijar solo mientras no exista ninguna factura de producción en ese
   punto, y queda en la auditoría.
4. El bloqueo de emisión abierto por administración (ver `BLOQUEO-EMISION.md`), con `FACTURACION_EMISION_BLOQUEADA=NO`.

Cada clave de acceso que devuelve AZUR se comprueba en el servidor: si su ambiente no coincide con el del comprobante, se detiene todo y se
avisa.

## Orden recomendado del día del corte

1. Dejar de emitir con el sistema anterior en 001-010 y anotar su **último** número. Si no es el 275, se usa el número real.
2. En AZUR: confirmar que el punto 001-010 de producción existe y que su último secuencial coincide.
3. Crear un respaldo completo desde Configuración → Respaldos.
4. Poner las variables del punto 1 y 2 en Vercel y volver a desplegar.
5. Fijar el secuencial inicial en el panel.
6. Abrir el bloqueo de emisión (motivo y confirmación).
7. Emitir **una** factura real controlada, enviarla al SRI y verificar que queda autorizada antes de seguir.

## Pendiente de decidir antes del corte

El modo de pruebas también limitaba la caja a administración y ocultaba los datos bancarios en presupuestos. Al pasar a producción esas
restricciones se levantan. Los registros de prueba (facturas de ambiente 1, cajas, inventario de prueba) **no** se borran solos. Hay que
decidir si se retiran antes del corte.
