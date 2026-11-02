-- Ingreso de mercadería por proveedor: factura electrónica XML, comprobante adjunto o sin factura. Solo AÑADE columnas y tablas: las compras,
-- movimientos y unidades existentes conservan sus valores. El borrador no mueve inventario; lo confirmado se corrige con movimientos, no borrando.
ALTER TABLE purchases ADD COLUMN source TEXT NOT NULL DEFAULT 'manual' CHECK(source IN ('manual','xml','comprobante','sin_factura'));
ALTER TABLE purchases ADD COLUMN access_key TEXT NOT NULL DEFAULT '';
ALTER TABLE purchases ADD COLUMN authorization_number TEXT NOT NULL DEFAULT '';
ALTER TABLE purchases ADD COLUMN authorized_at TEXT NOT NULL DEFAULT '';
ALTER TABLE purchases ADD COLUMN xml_total_cents INTEGER;
-- Ficha completa del proveedor.
ALTER TABLE suppliers ADD COLUMN trade_name TEXT NOT NULL DEFAULT '';
ALTER TABLE suppliers ADD COLUMN whatsapp TEXT NOT NULL DEFAULT '';
ALTER TABLE suppliers ADD COLUMN city TEXT NOT NULL DEFAULT '';
ALTER TABLE suppliers ADD COLUMN province TEXT NOT NULL DEFAULT '';
ALTER TABLE suppliers ADD COLUMN notes TEXT NOT NULL DEFAULT '';
-- La misma factura electrónica no se importa dos veces, aunque cambie el proveedor elegido.
CREATE UNIQUE INDEX purchases_one_access_key ON purchases(access_key) WHERE access_key!='' AND status!='anulada';
ALTER TABLE purchase_items ADD COLUMN description TEXT NOT NULL DEFAULT '';
ALTER TABLE purchase_items ADD COLUMN supplier_code TEXT NOT NULL DEFAULT '';
ALTER TABLE purchase_items ADD COLUMN serials TEXT NOT NULL DEFAULT '[]';
ALTER TABLE purchase_items ADD COLUMN location TEXT NOT NULL DEFAULT '';
ALTER TABLE purchase_items ADD COLUMN discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents>=0);
ALTER TABLE purchase_items ADD COLUMN sale_price_cents INTEGER CHECK(sale_price_cents IS NULL OR sale_price_cents>=0);
ALTER TABLE purchase_items ADD COLUMN movement_id INTEGER REFERENCES inventory_movements(id);
-- Respaldo de un ingreso (XML, foto o PDF) o documento del proveedor. Puede adjuntarse después. Un adjunto equivocado se descarta (queda constancia), no se borra.
CREATE TABLE purchase_files (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
 purchase_id INTEGER REFERENCES purchases(id),
 kind TEXT NOT NULL CHECK(kind IN ('xml','comprobante','respaldo')),
 name TEXT NOT NULL,
 mime TEXT NOT NULL CHECK(mime IN ('application/xml','image/jpeg','image/png','application/pdf')),
 size INTEGER NOT NULL CHECK(size>0),
 sha256 TEXT NOT NULL,
 data BLOB NOT NULL,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 discarded_at TEXT NOT NULL DEFAULT '',
 discarded_by INTEGER REFERENCES users(id),
 discard_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX purchase_files_purchase ON purchase_files(purchase_id);
CREATE INDEX purchase_files_supplier ON purchase_files(supplier_id);
CREATE TRIGGER purchase_files_fixed BEFORE UPDATE OF supplier_id,purchase_id,kind,name,mime,size,sha256,data,created_by,created_at ON purchase_files BEGIN SELECT RAISE(ABORT,'Un adjunto no se modifica: se descarta'); END;
CREATE TRIGGER purchase_files_no_delete BEFORE DELETE ON purchase_files BEGIN SELECT RAISE(ABORT,'Un adjunto no se elimina: se descarta'); END;
-- Código con el que cada proveedor factura un producto: la próxima factura se relaciona sola. Un producto puede tener varios proveedores.
CREATE TABLE supplier_item_codes (
 supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
 code TEXT NOT NULL,
 item_id INTEGER NOT NULL REFERENCES inventory_items(id),
 updated_at TEXT NOT NULL,
 PRIMARY KEY(supplier_id,code)
);
-- Reversos de lo ya confirmado, por partida: el Kardex recibe un movimiento de salida; nada se borra.
CREATE TABLE purchase_reversals (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 purchase_id INTEGER NOT NULL REFERENCES purchases(id),
 purchase_item_id INTEGER NOT NULL REFERENCES purchase_items(id),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 movement_id INTEGER REFERENCES inventory_movements(id),
 reason TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX purchase_reversals_item ON purchase_reversals(purchase_item_id);
CREATE TRIGGER purchase_reversals_no_update BEFORE UPDATE ON purchase_reversals BEGIN SELECT RAISE(ABORT,'Un reverso no se modifica'); END;
CREATE TRIGGER purchase_reversals_no_delete BEFORE DELETE ON purchase_reversals BEGIN SELECT RAISE(ABORT,'Un reverso no se elimina'); END;
