-- 1.5.302 · Cobertura Empresarial PC-DOCTOR: importe fijo y gastos internos de la orden. Solo AGREGA columnas con valor por defecto:
-- no cambia ni borra coberturas, pagos, historial, presupuestos, caja ni inventario.
--  · fixed_cents: cobertura por IMPORTE (no por porcentaje). 0 = por porcentaje, como hasta ahora. En la comercial, el beneficio es ese
--    importe (nunca más que el importe de la línea); en la de costo interno, lo que PC-DOCTOR asume del costo (nunca más que el costo).
--  · scope: 'partida' (una línea del presupuesto, como hasta ahora) o 'concepto' (un gasto interno de la orden que no se cobra al
--    cliente: transporte, gastos de terceros…). Un concepto siempre es de costo interno y nunca cambia lo que paga el cliente.
ALTER TABLE part_coverages ADD COLUMN fixed_cents INTEGER NOT NULL DEFAULT 0 CHECK(fixed_cents>=0);
ALTER TABLE part_coverages ADD COLUMN scope TEXT NOT NULL DEFAULT 'partida' CHECK(scope IN ('partida','concepto'));
