-- Limpieza segura del catálogo (1.5.268). Solo añade dos columnas vacías y una tabla nueva: no cambia productos, precios, presupuestos,
-- proformas, facturas, ventas, inventario ni licencias.
-- archived_at/archived_by: producto conservado como archivado (fuera del catálogo operativo, con su historial intacto) porque tiene
-- referencias que deben conservarse. Vacío = no archivado por esta vía (los lotes AR- de Inventario siguen valiendo como archivo).
ALTER TABLE catalog_items ADD COLUMN archived_at TEXT NOT NULL DEFAULT '';
ALTER TABLE catalog_items ADD COLUMN archived_by INTEGER REFERENCES users(id);
-- Registro inmutable de cada eliminación o archivo: el producto eliminado ya no existe, así que aquí quedan su código, nombre y precio,
-- quién lo hizo, cuándo y el resultado. La tabla audit solo guarda la acción y el id.
-- Reversión (antes de usarla): DROP TABLE catalog_removals; las columnas vacías pueden quedar (o ALTER TABLE ... DROP COLUMN).
CREATE TABLE catalog_removals (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 item_id INTEGER NOT NULL,
 code TEXT NOT NULL DEFAULT '',
 name TEXT NOT NULL,
 category TEXT NOT NULL,
 price_cents INTEGER NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN ('eliminado','archivado')),
 detail TEXT NOT NULL DEFAULT '',
 batch TEXT NOT NULL DEFAULT '',
 user_id INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX catalog_removals_item ON catalog_removals(item_id);
CREATE TRIGGER catalog_removals_no_update BEFORE UPDATE ON catalog_removals BEGIN SELECT RAISE(ABORT,'El registro de limpieza del catálogo no se modifica'); END;
CREATE TRIGGER catalog_removals_no_delete BEFORE DELETE ON catalog_removals BEGIN SELECT RAISE(ABORT,'El registro de limpieza del catálogo no se elimina'); END;
