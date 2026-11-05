-- Logistics Pro (05/11/2026): tipo de envío (nacional o internacional), país de origen, fecha de despacho, paso logístico detallado dentro
-- del traslado (despacho, tránsito aéreo, aduana, distribución nacional, ruta a Otavalo) e incidencia logística. La etapa general (stage,
-- 8 valores) no cambia: el seguimiento público y los pedidos anteriores siguen igual. SOLO añade columnas vacías.
-- Reversión: las columnas quedan sin uso (SQLite no las elimina sin reconstruir la tabla).
ALTER TABLE order_part_requests ADD COLUMN shipping TEXT NOT NULL DEFAULT '' CHECK(shipping IN ('','nacional','internacional'));
ALTER TABLE order_part_requests ADD COLUMN origin_country TEXT NOT NULL DEFAULT '';
ALTER TABLE order_part_requests ADD COLUMN dispatch_date TEXT NOT NULL DEFAULT '';
ALTER TABLE order_part_requests ADD COLUMN logistics TEXT NOT NULL DEFAULT '';
ALTER TABLE order_part_requests ADD COLUMN incident TEXT NOT NULL DEFAULT '';
ALTER TABLE order_part_events ADD COLUMN logistics TEXT NOT NULL DEFAULT '';
ALTER TABLE order_part_events ADD COLUMN incident TEXT NOT NULL DEFAULT '';
