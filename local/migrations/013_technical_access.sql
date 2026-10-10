CREATE TABLE order_access_consents (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 action TEXT NOT NULL CHECK(action IN ('technical','destructive')),
 decision TEXT NOT NULL CHECK(decision IN ('authorized','denied')),
 permissions TEXT NOT NULL,
 justification TEXT NOT NULL DEFAULT '',
 acceptor TEXT NOT NULL,
 recorded_at TEXT NOT NULL,
 actor_id INTEGER NOT NULL REFERENCES users(id),
 request_key TEXT NOT NULL,
 UNIQUE(order_id,action,request_key)
);
CREATE INDEX order_access_history ON order_access_consents(order_id,id);
CREATE TRIGGER immutable_access_update BEFORE UPDATE ON order_access_consents
 BEGIN SELECT RAISE(ABORT,'Conservar la evidencia de autorización; registrar una nueva decisión'); END;
CREATE TRIGGER immutable_access_delete BEFORE DELETE ON order_access_consents
 BEGIN SELECT RAISE(ABORT,'Conservar el historial de autorizaciones'); END;
CREATE TABLE thermal_print_jobs (
 request_key TEXT PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 actor_id INTEGER NOT NULL REFERENCES users(id),
 state TEXT NOT NULL CHECK(state IN ('pending','submitted','uncertain')),
 created_at TEXT NOT NULL,
 spool_reference TEXT NOT NULL DEFAULT ''
);
