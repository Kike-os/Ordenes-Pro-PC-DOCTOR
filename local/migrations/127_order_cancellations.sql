-- Smart Cancellation & Closure Management: cancelación de reparaciones con estados administrativos, evidencia y auditoría inmutable.
-- Solo crea tablas e índices nuevos (aditiva). La orden conserva todo su historial: nada se borra.
CREATE TABLE IF NOT EXISTS order_cancellations(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 state TEXT NOT NULL CHECK(state IN ('solicitada','cancelada','cerrada','anulada')),
 reason_code TEXT NOT NULL,
 reason_detail TEXT NOT NULL,
 via TEXT NOT NULL DEFAULT 'personal' CHECK(via IN ('personal','portal')),
 identity_method TEXT NOT NULL DEFAULT '',
 previous_status TEXT NOT NULL DEFAULT '',
 requested_at TEXT NOT NULL,
 requested_by INTEGER REFERENCES users(id),
 confirmed_at TEXT NOT NULL DEFAULT '',
 confirmed_by INTEGER REFERENCES users(id),
 closed_at TEXT NOT NULL DEFAULT '',
 closed_by INTEGER REFERENCES users(id),
 reopened_at TEXT NOT NULL DEFAULT '',
 reopened_by INTEGER REFERENCES users(id),
 reopen_reason TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS order_cancellations_order ON order_cancellations(order_id,id);
CREATE INDEX IF NOT EXISTS order_cancellations_state ON order_cancellations(state);
CREATE TABLE IF NOT EXISTS order_cancellation_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 cancellation_id INTEGER NOT NULL REFERENCES order_cancellations(id),
 kind TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 actor_name TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS order_cancellation_events_c ON order_cancellation_events(cancellation_id,id);
CREATE TABLE IF NOT EXISTS order_cancellation_files(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 cancellation_id INTEGER NOT NULL REFERENCES order_cancellations(id),
 name TEXT NOT NULL,
 mime TEXT NOT NULL,
 size INTEGER NOT NULL,
 content TEXT NOT NULL,
 uploaded_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS order_cancellation_files_c ON order_cancellation_files(cancellation_id);
