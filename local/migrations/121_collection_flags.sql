-- ADI 3.0 · fase 4: marcas de gestión de cartera por cliente. Solo crea una tabla: no modifica órdenes, pagos, saldos ni facturas.
-- suspension: suspende los recordatorios de cobranza hasta una fecha; derivacion: el caso pasa a administración; observacion: nota interna.
CREATE TABLE IF NOT EXISTS collection_flags (
 id INTEGER PRIMARY KEY,
 client_id INTEGER NOT NULL REFERENCES clients(id),
 order_id INTEGER REFERENCES orders(id),
 kind TEXT NOT NULL CHECK(kind IN ('suspension','derivacion','observacion','conciliacion')),
 reason TEXT NOT NULL,
 until TEXT NOT NULL DEFAULT '',
 user_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 closed_at TEXT NOT NULL DEFAULT '',
 closed_by INTEGER REFERENCES users(id),
 close_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS collection_flags_client ON collection_flags(client_id, kind, closed_at);
