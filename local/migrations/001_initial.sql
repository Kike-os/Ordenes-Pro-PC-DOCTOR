CREATE TABLE roles (name TEXT PRIMARY KEY);
INSERT INTO roles VALUES ('administrador'), ('tecnico');
CREATE TABLE users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 email TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL REFERENCES roles(name),
 active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL
);
CREATE TABLE clients (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT, phone TEXT);
CREATE TABLE devices (
 id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id),
 type TEXT NOT NULL CHECK(type IN ('portatil','escritorio')), brand TEXT, model TEXT, serial TEXT
);
CREATE TABLE statuses (code TEXT PRIMARY KEY, label TEXT NOT NULL);
INSERT INTO statuses VALUES ('pendiente','Pendiente'),('diagnostico','En diagnóstico'),
 ('reparacion','En reparación'),('listo','Listo para entrega'),('entregado','Entregado');
CREATE TABLE orders (
 id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL REFERENCES devices(id),
 status TEXT NOT NULL REFERENCES statuses(code), problem TEXT NOT NULL,
 created_by INTEGER NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL
);
CREATE INDEX orders_status ON orders(status);
CREATE INDEX devices_client ON devices(client_id);
CREATE TABLE sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires INTEGER NOT NULL
);
CREATE INDEX sessions_expiry ON sessions(expires);
CREATE TABLE attempts (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE reset_tokens (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires INTEGER NOT NULL);
CREATE TABLE audit (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
 entity_id INTEGER, created_at INTEGER NOT NULL
);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
