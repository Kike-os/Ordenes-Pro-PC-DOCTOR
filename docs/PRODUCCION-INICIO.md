# Inicio de producción (12/10/2026)

Por autorización expresa de administración se eliminaron los registros de prueba de la base de producción. **La base de clientes no se tocó.**

## Qué se eliminó

- 3 órdenes de prueba (PCD-20261009-0001, PCD-20261011-0001 y PCD-20261011-0002) con su historial (30 movimientos), 1 foto, 5 enlaces de seguimiento, 5 registros de envío de comprobante, 4 consentimientos de acceso, 3 consultas de orden, 1 vínculo de correo y 2 previsiones de mantenimiento.
- 7 citas de prueba con sus 16 eventos, 6 correos y 6 avisos.
- Los 3 equipos de prueba y las 5 conversaciones de ADI (46 mensajes).
- Las marcas de «leído» de eventos, citas y mantenimientos (sus identificadores se reutilizan).

## Qué se conservó, comprobado con huella antes y después

Clientes (189), filas de su importación (190), usuarios (2), condiciones (versión 2026.10.1), configuración, auditoría (162 registros) y secuencias diarias de numeración: idénticos byte a byte.

## Cómo se hizo

1. Respaldo completo `ordenes-pro-nube-20261012-180520.sqlite3` en `~/Respaldos-OrdenesPro`, verificado con prueba de restauración (integridad correcta, sin errores de claves foráneas).
2. Ensayo de la limpieza sobre una copia del respaldo.
3. Limpieza en producción en una sola transacción. Los disparadores que impiden borrar historial y consentimientos se retiraron dentro de esa transacción y se restauraron en ella; siguen activos.
4. Verificación: contadores en cero, clientes idénticos, búsqueda de clientes operativa.

## Numeración

El número de orden lo genera el servidor por día (`PCD-AAAAMMDD-NNNN`) con un contador que nunca retrocede; dos registros simultáneos no pueden obtener el mismo número. Las secuencias de los días 09 y 11 de octubre se conservaron, de modo que los números de las órdenes de prueba no se reutilizarán. La primera orden de cada día es la 0001.

## Recuperación

Todo lo eliminado está en el respaldo indicado. Desde ahora producción contiene datos reales: las pruebas que creen registros se hacen solo en la base temporal de pruebas.
