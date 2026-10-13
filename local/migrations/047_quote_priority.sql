-- Clasificación de cada partida del presupuesto (Necesario, Obligatorio, Opcional): informativa, independiente de la aprobación del cliente.
-- Icono del elemento del catálogo y marca de «IVA por confirmar». Solo añade columnas: lo existente conserva sus valores.
ALTER TABLE quote_items ADD COLUMN priority TEXT NOT NULL DEFAULT '' CHECK(priority IN ('','necesario','obligatorio','opcional'));
ALTER TABLE catalog_items ADD COLUMN icon TEXT NOT NULL DEFAULT '';
ALTER TABLE catalog_items ADD COLUMN tax_pending INTEGER NOT NULL DEFAULT 0 CHECK(tax_pending IN (0,1));
