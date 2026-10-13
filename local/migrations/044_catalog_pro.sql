-- Catálogo profesional de productos y servicios, historial de precios, imágenes y descuentos autorizados en presupuestos.
-- Solo añade columnas y tablas; los elementos y presupuestos existentes conservan sus valores.
ALTER TABLE catalog_items ADD COLUMN code TEXT;
UPDATE catalog_items SET code='PS-'||printf('%04d',id) WHERE code IS NULL;
CREATE UNIQUE INDEX catalog_items_code ON catalog_items(code) WHERE code IS NOT NULL;
CREATE TRIGGER catalog_items_code_assign AFTER INSERT ON catalog_items WHEN NEW.code IS NULL
 BEGIN UPDATE catalog_items SET code='PS-'||printf('%04d',NEW.id) WHERE id=NEW.id; END;
ALTER TABLE catalog_items ADD COLUMN brand TEXT NOT NULL DEFAULT '';
-- Cómo se escribió el precio: con IVA incluido, como base a la que se agrega el IVA, o sin IVA. price_cents es siempre el precio final.
ALTER TABLE catalog_items ADD COLUMN price_mode TEXT NOT NULL DEFAULT 'incluido' CHECK(price_mode IN ('incluido','agregar','sin_iva'));
ALTER TABLE catalog_items ADD COLUMN entered_cents INTEGER;
ALTER TABLE catalog_items ADD COLUMN license_term TEXT NOT NULL DEFAULT '';
ALTER TABLE catalog_items ADD COLUMN devices TEXT NOT NULL DEFAULT '';
UPDATE catalog_items SET entered_cents=price_cents,price_mode=CASE WHEN taxed=1 THEN 'incluido' ELSE 'sin_iva' END WHERE entered_cents IS NULL;
CREATE UNIQUE INDEX catalog_items_name ON catalog_items(lower(name));
CREATE TABLE catalog_images (
 item_id INTEGER PRIMARY KEY REFERENCES catalog_items(id),
 mime TEXT NOT NULL CHECK(mime IN ('image/png','image/jpeg','image/webp')),
 data BLOB NOT NULL,
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE TABLE catalog_price_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 item_id INTEGER NOT NULL REFERENCES catalog_items(id),
 old_cents INTEGER NOT NULL,
 new_cents INTEGER NOT NULL,
 user_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX catalog_price_history_item ON catalog_price_history(item_id,id);
CREATE TRIGGER catalog_price_history_no_update BEFORE UPDATE ON catalog_price_history BEGIN SELECT RAISE(ABORT,'El historial de precios no se modifica'); END;
CREATE TRIGGER catalog_price_history_no_delete BEFORE DELETE ON catalog_price_history BEGIN SELECT RAISE(ABORT,'El historial de precios no se elimina'); END;
-- Descuento autorizado del presupuesto: solo 0 %, 3 % o 5 %, con quién lo aplicó y cuándo.
ALTER TABLE quotes ADD COLUMN discount_bp INTEGER NOT NULL DEFAULT 0 CHECK(discount_bp IN (0,300,500));
ALTER TABLE quotes ADD COLUMN discount_by INTEGER REFERENCES users(id);
ALTER TABLE quotes ADD COLUMN discount_at TEXT NOT NULL DEFAULT '';
