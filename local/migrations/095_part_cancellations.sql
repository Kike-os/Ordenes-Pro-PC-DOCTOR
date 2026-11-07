-- Seguimiento de repuestos (06/11/2026): datos del envío internacional, cancelaciones con revisión de administración, reembolsos
-- conciliados con las devoluciones reales de la orden y avisos automáticos al cliente (uno por evento y canal).
-- SOLO añade tablas y columnas vacías: no cambia pedidos, etapas, pagos ni historiales.
-- Reversión (antes de usarlas): DROP TABLE order_part_notices; DROP TABLE order_part_log; DROP TABLE order_part_refunds;
-- DROP TABLE order_part_cancellations; las columnas nuevas quedan sin uso.
ALTER TABLE order_part_requests ADD COLUMN national_carrier TEXT NOT NULL DEFAULT '';
ALTER TABLE order_part_requests ADD COLUMN national_tracking TEXT NOT NULL DEFAULT '';
ALTER TABLE order_part_requests ADD COLUMN customs_in_date TEXT NOT NULL DEFAULT '';
ALTER TABLE order_part_requests ADD COLUMN customs_out_date TEXT NOT NULL DEFAULT '';
-- Evidencia de un repuesto asociada a la etapa en la que se registró.
ALTER TABLE order_followups ADD COLUMN part_step TEXT NOT NULL DEFAULT '';
-- Cancelación de un pedido: la solicita el cliente (enlace de seguimiento) o el personal; la decide administración. Una sola abierta a la vez.
CREATE TABLE order_part_cancellations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 request_id INTEGER NOT NULL REFERENCES order_part_requests(id),
 origin TEXT NOT NULL CHECK(origin IN ('cliente','personal')),
 channel TEXT NOT NULL DEFAULT '',
 reason_code TEXT NOT NULL CHECK(reason_code IN ('cliente_desiste','proveedor','sin_disponibilidad','importacion','duplicado','administrativa')),
 reason TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('solicitada','en_revision','aprobada','rechazada')),
 step_at_request TEXT NOT NULL,
 decision_note TEXT NOT NULL DEFAULT '',
 decided_by INTEGER REFERENCES users(id),
 decided_at TEXT NOT NULL DEFAULT '',
 refund_due_cents INTEGER NOT NULL DEFAULT 0 CHECK(refund_due_cents>=0),
 refund_state TEXT NOT NULL DEFAULT 'no_aplica' CHECK(refund_state IN ('no_aplica','pendiente','parcial','completado')),
 request_key TEXT UNIQUE,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX order_part_cancellations_request ON order_part_cancellations(request_id,id);
CREATE UNIQUE INDEX order_part_cancellations_open ON order_part_cancellations(request_id) WHERE status IN ('solicitada','en_revision');
CREATE TRIGGER order_part_cancellations_no_delete BEFORE DELETE ON order_part_cancellations BEGIN SELECT RAISE(ABORT,'Una cancelación registrada no se elimina'); END;
-- Reembolsos: cada uno es una devolución real de la orden (order_payments, kind=devolucion), registrada una sola vez.
CREATE TABLE order_part_refunds (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 cancellation_id INTEGER NOT NULL REFERENCES order_part_cancellations(id),
 payment_id INTEGER NOT NULL UNIQUE REFERENCES order_payments(id),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE TRIGGER order_part_refunds_no_delete BEFORE DELETE ON order_part_refunds BEGIN SELECT RAISE(ABORT,'Un reembolso registrado no se elimina'); END;
-- Bitácora de cancelaciones, reembolsos y avisos: no se modifica ni se borra.
CREATE TABLE order_part_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 request_id INTEGER NOT NULL REFERENCES order_part_requests(id),
 kind TEXT NOT NULL CHECK(kind IN ('cancelacion','reembolso','aviso')),
 action TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT '',
 data TEXT NOT NULL DEFAULT '',
 origin TEXT NOT NULL CHECK(origin IN ('personal','cliente','sistema')),
 actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX order_part_log_request ON order_part_log(request_id,id);
CREATE TRIGGER order_part_log_no_update BEFORE UPDATE ON order_part_log BEGIN SELECT RAISE(ABORT,'La bitácora del repuesto no se modifica'); END;
CREATE TRIGGER order_part_log_no_delete BEFORE DELETE ON order_part_log BEGIN SELECT RAISE(ABORT,'La bitácora del repuesto no se elimina'); END;
-- Avisos automáticos al cliente: uno por evento y canal (la clave única impide duplicados por reintentos). «enviado» solo cuando el servidor de
-- correo o WhatsApp Business lo aceptó; «omitido» explica por qué no se envió (sin canal, sin consentimiento, sin configurar).
CREATE TABLE order_part_notices (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 request_id INTEGER NOT NULL REFERENCES order_part_requests(id),
 event_key TEXT NOT NULL,
 event TEXT NOT NULL,
 channel TEXT NOT NULL CHECK(channel IN ('correo','whatsapp')),
 status TEXT NOT NULL CHECK(status IN ('pendiente','enviado','fallido','omitido')),
 detail TEXT NOT NULL DEFAULT '',
 attempts INTEGER NOT NULL DEFAULT 0,
 message_id INTEGER REFERENCES order_messages(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(request_id,event_key,channel)
);
CREATE TRIGGER order_part_notices_no_delete BEFORE DELETE ON order_part_notices BEGIN SELECT RAISE(ABORT,'Un aviso registrado no se elimina'); END;
