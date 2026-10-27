-- Centro de Inventario (auditoría del 26/10/2026): alertas por ficha, datos comerciales de cada entrada y correcciones de costo auditadas.
-- Solo AÑADE columnas y una tabla: los movimientos, las unidades y las fichas existentes conservan sus valores.
ALTER TABLE inventory_items ADD COLUMN alerts_enabled INTEGER NOT NULL DEFAULT 1 CHECK(alerts_enabled IN (0,1));
ALTER TABLE inventory_items ADD COLUMN warranty_terms TEXT NOT NULL DEFAULT '';
ALTER TABLE inventory_movements ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id);
ALTER TABLE inventory_movements ADD COLUMN document TEXT NOT NULL DEFAULT '';
ALTER TABLE inventory_movements ADD COLUMN tax_rate_bp INTEGER NOT NULL DEFAULT 0 CHECK(tax_rate_bp>=0);
-- Ventas y precios de la ficha: precio mínimo y descuento autorizado (administración); en cada venta, precio aplicado, descuento, cliente y,
-- si el precio es 0 o menor que el mínimo, la autorización administrativa expresa con su motivo.
ALTER TABLE inventory_items ADD COLUMN min_price_cents INTEGER NOT NULL DEFAULT 0 CHECK(min_price_cents>=0);
ALTER TABLE inventory_items ADD COLUMN max_discount_bp INTEGER NOT NULL DEFAULT 0 CHECK(max_discount_bp BETWEEN 0 AND 10000);
ALTER TABLE inventory_movements ADD COLUMN sale_price_cents INTEGER CHECK(sale_price_cents IS NULL OR sale_price_cents>=0);
ALTER TABLE inventory_movements ADD COLUMN discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents>=0);
ALTER TABLE inventory_movements ADD COLUMN client_id INTEGER REFERENCES clients(id);
ALTER TABLE inventory_movements ADD COLUMN price_authorization TEXT NOT NULL DEFAULT '';
-- Reservas: cliente y vencimiento (una reserva vencida se señala para liberarla; no se libera sola).
ALTER TABLE inventory_reservations ADD COLUMN client_id INTEGER REFERENCES clients(id);
ALTER TABLE inventory_reservations ADD COLUMN expires_at TEXT NOT NULL DEFAULT '';
-- Corrección del costo de una entrada registrada con un costo equivocado (por ejemplo, 0): el movimiento original no cambia; la
-- corrección queda con su motivo, quién y cuándo, y el Kardex valorizado usa el costo corregido. No se modifica ni se elimina.
CREATE TABLE inventory_cost_corrections (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 movement_id INTEGER NOT NULL REFERENCES inventory_movements(id),
 item_id INTEGER NOT NULL REFERENCES inventory_items(id),
 old_cost_cents INTEGER NOT NULL CHECK(old_cost_cents>=0),
 new_cost_cents INTEGER NOT NULL CHECK(new_cost_cents>=0),
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 5 AND 300),
 document TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX inventory_cost_corrections_movement ON inventory_cost_corrections(movement_id,id);
CREATE TRIGGER inventory_cost_corrections_no_update BEFORE UPDATE ON inventory_cost_corrections BEGIN SELECT RAISE(ABORT,'Las correcciones de costo no se modifican'); END;
CREATE TRIGGER inventory_cost_corrections_no_delete BEFORE DELETE ON inventory_cost_corrections BEGIN SELECT RAISE(ABORT,'Las correcciones de costo no se eliminan'); END;
