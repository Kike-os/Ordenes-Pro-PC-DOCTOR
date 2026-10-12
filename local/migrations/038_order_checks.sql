-- Consulta pública del estado de una orden: reto de un solo uso con código temporal enviado al correo registrado.
CREATE TABLE order_checks (
 id INTEGER PRIMARY KEY,
 token_hash TEXT NOT NULL UNIQUE,
 order_id INTEGER REFERENCES orders(id),
 code_hash TEXT NOT NULL DEFAULT '',
 attempts INTEGER NOT NULL DEFAULT 0,
 expires_at TEXT NOT NULL,
 verified_at TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX order_checks_expiry ON order_checks(expires_at);
