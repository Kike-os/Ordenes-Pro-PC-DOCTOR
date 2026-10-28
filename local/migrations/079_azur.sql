-- Integración con AZUR (API REST v2): AZUR genera el XML, lo firma con el certificado del contribuyente y lo envía al SRI.
-- Columnas nuevas de la factura (sin tocar las existentes) y registro de cada operación con AZUR (sin credenciales ni cuerpos sensibles).
ALTER TABLE invoices ADD COLUMN provider TEXT NOT NULL DEFAULT '';
ALTER TABLE invoices ADD COLUMN provider_id INTEGER;
ALTER TABLE invoices ADD COLUMN provider_state INTEGER;
ALTER TABLE invoices ADD COLUMN provider_request_key TEXT NOT NULL DEFAULT '';
ALTER TABLE invoices ADD COLUMN provider_synced_at TEXT NOT NULL DEFAULT '';
-- Documentos que devuelve AZUR (PDF del RIDE y XML firmado o autorizado), en base64. Uno por tipo y factura; se reemplaza al sincronizar.
CREATE TABLE invoice_provider_files (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 kind TEXT NOT NULL CHECK(kind IN ('pdf','xml_firmado','xml_autorizado')),
 content TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(invoice_id,kind)
);
CREATE TABLE azur_operations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 invoice_id INTEGER REFERENCES invoices(id),
 action TEXT NOT NULL,
 request_key TEXT NOT NULL DEFAULT '',
 http_status INTEGER,
 result TEXT NOT NULL CHECK(result IN ('ok','error','pendiente')),
 code TEXT NOT NULL DEFAULT '',
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX azur_operations_invoice ON azur_operations(invoice_id,id);
CREATE TRIGGER azur_operations_no_update BEFORE UPDATE ON azur_operations BEGIN SELECT RAISE(ABORT,'El registro de operaciones con AZUR no se modifica'); END;
CREATE TRIGGER azur_operations_no_delete BEFORE DELETE ON azur_operations BEGIN SELECT RAISE(ABORT,'El registro de operaciones con AZUR no se elimina'); END;
-- Anulación (confirmada en el SRI): en tabla propia, porque un comprobante autorizado nunca se modifica.
CREATE TABLE invoice_annulments (
 invoice_id INTEGER PRIMARY KEY REFERENCES invoices(id),
 annulled_at TEXT NOT NULL,
 reason TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('usuario','sri')),
 actor_id INTEGER REFERENCES users(id)
);
CREATE TRIGGER invoice_annulments_no_update BEFORE UPDATE ON invoice_annulments BEGIN SELECT RAISE(ABORT,'Una anulación registrada no se modifica'); END;
CREATE TRIGGER invoice_annulments_no_delete BEFORE DELETE ON invoice_annulments BEGIN SELECT RAISE(ABORT,'Una anulación registrada no se elimina'); END;
