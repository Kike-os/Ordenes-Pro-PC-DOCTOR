-- Gestión documental de las condiciones: borrador de trabajo (uno solo, pendiente de aprobación) y registro de cambios de cada versión publicada.
-- No modifica ni borra versiones publicadas ni aceptaciones.
CREATE TABLE service_terms_draft (
 id INTEGER PRIMARY KEY CHECK(id=1),
 full_text TEXT NOT NULL,
 compact_text TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT '',
 updated_by INTEGER REFERENCES users(id),
 updated_at TEXT NOT NULL
);
CREATE TABLE service_terms_changes (
 terms_id TEXT PRIMARY KEY REFERENCES service_terms(id),
 previous_id TEXT REFERENCES service_terms(id),
 note TEXT NOT NULL DEFAULT '',
 added INTEGER NOT NULL DEFAULT 0,
 removed INTEGER NOT NULL DEFAULT 0,
 changed INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL
);
