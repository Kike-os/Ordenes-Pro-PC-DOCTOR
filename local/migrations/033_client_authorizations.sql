-- Autorización electrónica del cliente por enlace seguro: identidad (últimos dígitos + código temporal), decisiones y evidencia.
CREATE TABLE client_authorizations (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 token_hash TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','signed','rejected','expired','revoked','locked')),
 recipient TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 id_attempts INTEGER NOT NULL DEFAULT 0,
 code_hash TEXT NOT NULL DEFAULT '',
 code_expires TEXT NOT NULL DEFAULT '',
 code_attempts INTEGER NOT NULL DEFAULT 0,
 code_sent INTEGER NOT NULL DEFAULT 0,
 pass_hash TEXT NOT NULL DEFAULT '',
 verified_at TEXT NOT NULL DEFAULT '',
 evidence TEXT NOT NULL DEFAULT '',
 evidence_hash TEXT NOT NULL DEFAULT '',
 signed_at TEXT NOT NULL DEFAULT '',
 mail_result TEXT NOT NULL DEFAULT '',
 notice_result TEXT NOT NULL DEFAULT ''
);
CREATE INDEX client_authorizations_order ON client_authorizations(order_id,id);
