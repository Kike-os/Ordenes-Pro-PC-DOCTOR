-- Movimientos financieros de la orden: devoluciones, pagos generales (sin equipo asignado) con su distribución por equipo y una clave
-- de solicitud contra registros duplicados. Solo añade columnas, una tabla y disparadores: no modifica pagos ni saldos existentes.
ALTER TABLE order_payments ADD COLUMN kind TEXT NOT NULL DEFAULT 'pago' CHECK(kind IN ('pago','devolucion'));
ALTER TABLE order_payments ADD COLUMN scope TEXT NOT NULL DEFAULT 'equipo' CHECK(scope IN ('equipo','general'));
ALTER TABLE order_payments ADD COLUMN request_key TEXT;
CREATE UNIQUE INDEX order_payments_request ON order_payments(request_key) WHERE request_key IS NOT NULL;
CREATE TRIGGER order_payments_fixed BEFORE UPDATE OF order_id,amount_cents,method,kind,scope,created_by,created_at,request_key ON order_payments
 BEGIN SELECT RAISE(ABORT,'Un movimiento registrado no se modifica: se anula con motivo'); END;
CREATE TABLE order_payment_allocations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 payment_id INTEGER NOT NULL REFERENCES order_payments(id),
 order_id INTEGER NOT NULL REFERENCES orders(id),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX order_payment_allocations_order ON order_payment_allocations(order_id,id);
CREATE INDEX order_payment_allocations_payment ON order_payment_allocations(payment_id);
CREATE TRIGGER order_payment_allocations_no_delete BEFORE DELETE ON order_payment_allocations
 BEGIN SELECT RAISE(ABORT,'La distribución de un pago no se elimina'); END;
CREATE TRIGGER order_payment_allocations_no_update BEFORE UPDATE ON order_payment_allocations
 BEGIN SELECT RAISE(ABORT,'La distribución de un pago no se modifica'); END;
