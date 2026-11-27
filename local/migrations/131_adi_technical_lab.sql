CREATE TABLE IF NOT EXISTS adi_lab_knowledge (
 id INTEGER PRIMARY KEY,
 title TEXT NOT NULL,
 source TEXT NOT NULL,
 source_date TEXT NOT NULL,
 version TEXT NOT NULL,
 category TEXT NOT NULL,
 content TEXT NOT NULL,
 visibility TEXT NOT NULL CHECK(visibility IN ('tecnico','administrador')),
 status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','aprobado','descartado','sustituido')),
 supersedes INTEGER REFERENCES adi_lab_knowledge(id),
 created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 reviewed_by INTEGER REFERENCES users(id),
 reviewed_at TEXT,
 review_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS adi_lab_knowledge_status ON adi_lab_knowledge(status,category,id);
CREATE TABLE IF NOT EXISTS adi_lab_measurements (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 point TEXT NOT NULL,
 value TEXT NOT NULL,
 unit TEXT NOT NULL,
 conditions TEXT NOT NULL,
 created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 request_key TEXT NOT NULL,
 UNIQUE(order_id,created_by,request_key)
);
CREATE INDEX IF NOT EXISTS adi_lab_measurements_order ON adi_lab_measurements(order_id,id);
