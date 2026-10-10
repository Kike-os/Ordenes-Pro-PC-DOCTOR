ALTER TABLE orders ADD COLUMN assigned_to INTEGER REFERENCES users(id);
ALTER TABLE orders ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('baja','normal','alta','urgente'));
ALTER TABLE orders ADD COLUMN estimated_delivery TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN internal_notes TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN recommendations TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN findings TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
CREATE TABLE order_history (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL,
 actor_id INTEGER REFERENCES users(id),
 occurred_at TEXT NOT NULL,
 event TEXT NOT NULL,
 status_label TEXT NOT NULL,
 comment TEXT NOT NULL DEFAULT ''
);
CREATE INDEX order_history_order ON order_history(order_id,id);
CREATE TRIGGER order_history_no_update BEFORE UPDATE ON order_history BEGIN SELECT RAISE(ABORT,'history immutable'); END;
CREATE TRIGGER order_history_no_delete BEFORE DELETE ON order_history BEGIN SELECT RAISE(ABORT,'history immutable'); END;
INSERT INTO order_history(order_id,actor_id,occurred_at,event,status_label,comment)
 SELECT o.id,NULL,strftime('%Y-%m-%dT%H:%M:%S','now','-5 hours')||'-05:00','migration',s.label,'Registro histórico incorporado al nuevo módulo; no representa una nueva recepción.' FROM orders o JOIN statuses s ON s.code=o.status;
UPDATE orders SET assigned_to=created_by;
UPDATE statuses SET label='En espera' WHERE code='pendiente';
UPDATE statuses SET label='Procesando' WHERE code='reparacion';
UPDATE statuses SET label='Listo para entregar' WHERE code='listo';
INSERT INTO statuses VALUES ('esperando_cliente','Esperando respuesta del cliente'),('presupuesto','Aprobación de presupuesto'),('espera_entrega','En espera de entrega');
UPDATE orders SET status='reparacion' WHERE status='diagnostico';
DELETE FROM statuses WHERE code='diagnostico';
CREATE TABLE order_budget (
 order_id INTEGER PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
 labor_cents INTEGER NOT NULL DEFAULT 0 CHECK(labor_cents>=0),
 parts_cents INTEGER NOT NULL DEFAULT 0 CHECK(parts_cents>=0),
 services_cents INTEGER NOT NULL DEFAULT 0 CHECK(services_cents>=0),
 digital_cents INTEGER NOT NULL DEFAULT 0 CHECK(digital_cents>=0)
);
CREATE TABLE order_budget_lines (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
 category TEXT NOT NULL CHECK(category IN ('labor','parts','services','digital')),
 description TEXT NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(amount_cents>=0)
);
CREATE INDEX order_budget_lines_order ON order_budget_lines(order_id,id);
