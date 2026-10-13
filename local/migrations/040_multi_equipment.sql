-- Varios equipos por orden, identidad permanente de cada equipo y pagos por equipo. Solo añade columnas, índices y una tabla nueva:
-- no modifica ni elimina órdenes, clientes, historiales ni fotografías existentes.
ALTER TABLE devices ADD COLUMN code TEXT;
UPDATE devices SET code='EQ-'||printf('%04d',id) WHERE code IS NULL;
CREATE UNIQUE INDEX devices_code ON devices(code) WHERE code IS NOT NULL;
CREATE TRIGGER devices_code_assign AFTER INSERT ON devices WHEN NEW.code IS NULL
 BEGIN UPDATE devices SET code='EQ-'||printf('%04d',NEW.id) WHERE id=NEW.id; END;
CREATE TRIGGER devices_code_permanent BEFORE UPDATE OF code ON devices WHEN OLD.code IS NOT NULL AND NEW.code IS NOT OLD.code
 BEGIN SELECT RAISE(ABORT,'El identificador del equipo es permanente'); END;
-- Cada equipo de una orden es un ingreso propio (fila de orders) unido a la orden principal por group_id.
ALTER TABLE orders ADD COLUMN group_id INTEGER REFERENCES orders(id);
ALTER TABLE orders ADD COLUMN unit_no INTEGER NOT NULL DEFAULT 1;
CREATE UNIQUE INDEX orders_group_unit ON orders(group_id,unit_no) WHERE group_id IS NOT NULL;
CREATE TABLE order_payments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 method TEXT NOT NULL CHECK(method IN ('efectivo','transferencia','tarjeta','deposito','otro')),
 note TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 voided_at TEXT,
 voided_by INTEGER REFERENCES users(id),
 void_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX order_payments_order ON order_payments(order_id,id);
CREATE TRIGGER order_payments_no_delete BEFORE DELETE ON order_payments
 BEGIN SELECT RAISE(ABORT,'Los pagos no se eliminan: se anulan con motivo'); END;
