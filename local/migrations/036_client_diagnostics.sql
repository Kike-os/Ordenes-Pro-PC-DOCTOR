-- Diagnósticos del navegador (pasos de ADI y errores de la página), sin el texto que escribe el usuario. Se conservan pocos días.
CREATE TABLE client_diagnostics (
 id INTEGER PRIMARY KEY,
 user_id INTEGER REFERENCES users(id),
 kind TEXT NOT NULL,
 message TEXT NOT NULL DEFAULT '',
 place TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX client_diagnostics_recent ON client_diagnostics(created_at);
