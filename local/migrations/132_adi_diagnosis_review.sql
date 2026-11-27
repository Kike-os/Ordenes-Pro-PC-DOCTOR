CREATE TABLE IF NOT EXISTS adi_lab_diagnoses (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 confirmed TEXT NOT NULL,
 conclusion TEXT NOT NULL,
 pending_checks TEXT NOT NULL DEFAULT '',
 previous_findings TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente','aprobado','devuelto')),
 created_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 reviewed_by INTEGER REFERENCES users(id),
 reviewed_at TEXT,
 review_note TEXT NOT NULL DEFAULT '',
 request_key TEXT NOT NULL,
 UNIQUE(order_id,created_by,request_key)
);
CREATE INDEX IF NOT EXISTS adi_lab_diagnoses_order ON adi_lab_diagnoses(order_id,id DESC);
