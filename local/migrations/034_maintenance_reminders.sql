-- Recordatorios de mantenimiento por etapas (30, 15, 7, 3 y 0 días) y respuestas del cliente desde su enlace seguro.
CREATE TABLE maintenance_reminders (
 id INTEGER PRIMARY KEY,
 maintenance_id INTEGER NOT NULL REFERENCES maintenance(id),
 generation INTEGER NOT NULL,
 stage INTEGER NOT NULL,
 recipient TEXT NOT NULL DEFAULT '',
 result TEXT NOT NULL CHECK(result IN ('processing','sent','failed')),
 detail TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 UNIQUE(maintenance_id,generation,stage)
);
CREATE TABLE maintenance_responses (
 id INTEGER PRIMARY KEY,
 maintenance_id INTEGER NOT NULL REFERENCES maintenance(id),
 action TEXT NOT NULL CHECK(action IN ('confirm','reschedule','decline')),
 note TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 handled_at TEXT NOT NULL DEFAULT '',
 handled_by INTEGER REFERENCES users(id)
);
CREATE INDEX maintenance_responses_open ON maintenance_responses(handled_at,maintenance_id);
