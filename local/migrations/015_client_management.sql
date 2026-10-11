ALTER TABLE clients ADD COLUMN phone_secondary TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN notes TEXT NOT NULL DEFAULT '';
ALTER TABLE clients ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0;
ALTER TABLE clients ADD COLUMN import_batch_id INTEGER;
ALTER TABLE clients ADD COLUMN created_at TEXT NOT NULL DEFAULT '';
CREATE TABLE client_import_batches(
 id INTEGER PRIMARY KEY, filename TEXT NOT NULL, file_sha256 TEXT NOT NULL, actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL, total INTEGER NOT NULL, imported INTEGER NOT NULL, merged INTEGER NOT NULL,
 duplicates INTEGER NOT NULL, skipped INTEGER NOT NULL, errors INTEGER NOT NULL, backup_name TEXT NOT NULL DEFAULT '');
-- Valores originales de cada fila del archivo, incluidos los comerciales o de facturación, separados de la ficha de reparación.
CREATE TABLE client_import_rows(
 id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES client_import_batches(id), row_number INTEGER NOT NULL,
 client_id INTEGER REFERENCES clients(id), outcome TEXT NOT NULL, detail TEXT NOT NULL, original TEXT NOT NULL);
CREATE INDEX client_import_rows_batch ON client_import_rows(batch_id);
CREATE INDEX client_import_rows_client ON client_import_rows(client_id);
