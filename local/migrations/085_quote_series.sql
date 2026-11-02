-- Varios presupuestos independientes por orden: cada presupuesto pertenece a una serie. Las versiones (P1, P2…) de una misma serie se
-- reemplazan entre sí como hasta ahora; las series distintas conviven (por ejemplo, P1 aprobado y pagado, P2 pendiente, P3 aprobado).
-- Solo agrega una columna: todos los presupuestos existentes quedan en la serie 1, con el mismo comportamiento que tenían.
ALTER TABLE quotes ADD COLUMN series INTEGER NOT NULL DEFAULT 1;
CREATE INDEX quotes_order_series ON quotes(order_id,series,version);
