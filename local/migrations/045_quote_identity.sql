-- Documento de identidad en la aprobación de un presupuesto: solo cuando administración lo solicita para ese presupuesto.
-- El archivo se guarda en la base (no en disco ni en enlaces públicos) y solo lo consulta administración.
ALTER TABLE quotes ADD COLUMN require_id INTEGER NOT NULL DEFAULT 0 CHECK(require_id IN (0,1));
CREATE TABLE quote_documents (
 quote_id INTEGER PRIMARY KEY REFERENCES quotes(id),
 mime TEXT NOT NULL CHECK(mime IN ('image/png','image/jpeg','image/webp','application/pdf')),
 data BLOB NOT NULL,
 sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TRIGGER quote_documents_no_update BEFORE UPDATE ON quote_documents BEGIN SELECT RAISE(ABORT,'El documento recibido no se modifica'); END;
