-- ADI Smart Notifications 3.0: historial de cada intento de envío de un aviso de WhatsApp y de las respuestas del proveedor (Meta).
-- Solo crea una tabla nueva (aditiva): los avisos anteriores conservan su estado original y no se reenvía nada.
CREATE TABLE IF NOT EXISTS whatsapp_outbox_attempts(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 outbox_id INTEGER NOT NULL REFERENCES whatsapp_outbox(id),
 kind TEXT NOT NULL CHECK(kind IN ('envio','omitido','estado')),
 status TEXT NOT NULL,
 http_code TEXT NOT NULL DEFAULT '',
 error_code TEXT NOT NULL DEFAULT '',
 detail TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_whatsapp_outbox_attempts_outbox ON whatsapp_outbox_attempts(outbox_id, id);
