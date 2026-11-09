-- Recepción técnica estructurada (1.5.262). Solo añade columnas vacías: no cambia órdenes, textos de recepción ni fotos existentes.
-- orders.reception_details: inspección por zonas, cargador y accesorios (JSON). Los textos de siempre (estado físico y accesorios) se siguen
-- guardando para el comprobante, la hoja A4 y las órdenes anteriores.
ALTER TABLE orders ADD COLUMN reception_details TEXT NOT NULL DEFAULT '';
-- Fotos de evidencia: categoría, observación, nombre descriptivo, copia con marcas (el original no cambia) y eliminación sin borrar el
-- historial (quién, cuándo y por qué). Las fotos existentes quedan como «recepción», sin observación ni marcas.
ALTER TABLE order_photos ADD COLUMN category TEXT NOT NULL DEFAULT 'recepcion';
ALTER TABLE order_photos ADD COLUMN subject TEXT NOT NULL DEFAULT '';
ALTER TABLE order_photos ADD COLUMN note TEXT NOT NULL DEFAULT '';
ALTER TABLE order_photos ADD COLUMN filename TEXT NOT NULL DEFAULT '';
ALTER TABLE order_photos ADD COLUMN annotated TEXT NOT NULL DEFAULT '';
ALTER TABLE order_photos ADD COLUMN annotated_by INTEGER REFERENCES users(id);
ALTER TABLE order_photos ADD COLUMN annotated_at TEXT NOT NULL DEFAULT '';
ALTER TABLE order_photos ADD COLUMN deleted_at TEXT NOT NULL DEFAULT '';
ALTER TABLE order_photos ADD COLUMN deleted_by INTEGER REFERENCES users(id);
ALTER TABLE order_photos ADD COLUMN delete_reason TEXT NOT NULL DEFAULT '';
