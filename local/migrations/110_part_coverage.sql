-- 1.5.296 · Cobertura Empresarial de Repuestos — PC-DOCTOR. Solo crea tablas nuevas (vacías); no cambia presupuestos, caja ni inventario.
-- La cobertura es interna: PC-DOCTOR financia la compra del repuesto, pero el cliente sigue pagando el precio de su presupuesto.
-- Se guarda una copia de la línea (presupuesto, posición, descripción, precio) porque las partidas de un borrador se recrean al guardar:
-- el vínculo se rehace por posición y descripción, sin clave foránea que impida guardar el presupuesto.
CREATE TABLE IF NOT EXISTS part_coverages (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 quote_id INTEGER NOT NULL REFERENCES quotes(id),
 order_id INTEGER NOT NULL REFERENCES orders(id),
 quote_item_id INTEGER,
 line_position INTEGER NOT NULL,
 line_description TEXT NOT NULL,
 catalog_id INTEGER REFERENCES catalog_items(id),
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 999),
 sale_cents INTEGER NOT NULL CHECK(sale_cents>=0),
 cost_cents INTEGER NOT NULL CHECK(cost_cents>0),
 percent INTEGER NOT NULL CHECK(percent BETWEEN 1 AND 100),
 covered_cents INTEGER NOT NULL CHECK(covered_cents>0),
 supplier_id INTEGER REFERENCES suppliers(id),
 status TEXT NOT NULL CHECK(status IN ('solicitada','autorizada','rechazada','cancelada')),
 purchase_status TEXT NOT NULL DEFAULT 'pendiente' CHECK(purchase_status IN ('pendiente','comprado','recibido')),
 supplier_document TEXT NOT NULL DEFAULT '',
 purchased_at TEXT NOT NULL DEFAULT '',
 received_at TEXT NOT NULL DEFAULT '',
 received_by INTEGER REFERENCES users(id),
 inventory_movement_id INTEGER REFERENCES inventory_movements(id),
 notes TEXT NOT NULL DEFAULT '',
 review TEXT NOT NULL DEFAULT '',
 requested_by INTEGER REFERENCES users(id),
 requested_at TEXT NOT NULL,
 authorized_by INTEGER REFERENCES users(id),
 authorized_name TEXT NOT NULL DEFAULT '',
 authorized_at TEXT NOT NULL DEFAULT '',
 closed_by INTEGER REFERENCES users(id),
 closed_at TEXT NOT NULL DEFAULT '',
 close_reason TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS part_coverages_quote ON part_coverages(quote_id,line_position);
CREATE INDEX IF NOT EXISTS part_coverages_order ON part_coverages(order_id);
CREATE UNIQUE INDEX IF NOT EXISTS part_coverages_one_live ON part_coverages(quote_id,line_position,line_description) WHERE status IN ('solicitada','autorizada');
CREATE TRIGGER IF NOT EXISTS part_coverages_no_delete BEFORE DELETE ON part_coverages BEGIN SELECT RAISE(ABORT,'Una cobertura no se elimina: se cancela con su motivo'); END;
-- Pagos al proveedor: cada uno es un egreso real de caja (cash_movements) creado en la misma transacción. No se borran: se revierten.
CREATE TABLE IF NOT EXISTS part_coverage_payments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 coverage_id INTEGER NOT NULL REFERENCES part_coverages(id),
 cash_movement_id INTEGER NOT NULL UNIQUE REFERENCES cash_movements(id),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 method TEXT NOT NULL,
 supplier_document TEXT NOT NULL DEFAULT '',
 reference TEXT NOT NULL DEFAULT '',
 paid_at TEXT NOT NULL,
 paid_by INTEGER NOT NULL REFERENCES users(id),
 request_key TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL DEFAULT 'registrado' CHECK(status IN ('registrado','revertido')),
 reversal_movement_id INTEGER REFERENCES cash_movements(id),
 reversed_by INTEGER REFERENCES users(id),
 reversed_at TEXT NOT NULL DEFAULT '',
 reverse_reason TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS part_coverage_payments_coverage ON part_coverage_payments(coverage_id,id);
CREATE TRIGGER IF NOT EXISTS part_coverage_payments_no_delete BEFORE DELETE ON part_coverage_payments BEGIN SELECT RAISE(ABORT,'Un pago al proveedor no se elimina: se revierte con autorización'); END;
CREATE TRIGGER IF NOT EXISTS part_coverage_payments_fixed BEFORE UPDATE OF coverage_id,cash_movement_id,amount_cents,method,paid_at,paid_by,request_key,created_at ON part_coverage_payments
BEGIN SELECT RAISE(ABORT,'Los datos de un pago al proveedor no se modifican'); END;
-- Historial financiero de cada cobertura (solo anexado).
CREATE TABLE IF NOT EXISTS part_coverage_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 coverage_id INTEGER NOT NULL REFERENCES part_coverages(id),
 event TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS part_coverage_events_coverage ON part_coverage_events(coverage_id,id);
CREATE TRIGGER IF NOT EXISTS part_coverage_events_no_update BEFORE UPDATE ON part_coverage_events BEGIN SELECT RAISE(ABORT,'El historial de la cobertura no se modifica'); END;
CREATE TRIGGER IF NOT EXISTS part_coverage_events_no_delete BEFORE DELETE ON part_coverage_events BEGIN SELECT RAISE(ABORT,'El historial de la cobertura no se elimina'); END;
