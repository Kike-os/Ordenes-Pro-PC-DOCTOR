-- 1.5.315 · Idempotencia y trazabilidad de respuestas automáticas de ADI por WhatsApp.
CREATE TABLE IF NOT EXISTS whatsapp_adi_inbound (
 wa_message_id TEXT PRIMARY KEY,
 sender TEXT NOT NULL,
 conversation_id INTEGER REFERENCES adi_conversations(id),
 status TEXT NOT NULL CHECK(status IN ('recibido','generando','enviando','enviado','omitido','fallido')),
 received_at TEXT NOT NULL,
 replied_at TEXT NOT NULL DEFAULT '',
 provider_id TEXT NOT NULL DEFAULT '',
 detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS whatsapp_adi_inbound_month ON whatsapp_adi_inbound(received_at,status);
CREATE INDEX IF NOT EXISTS whatsapp_adi_inbound_sender ON whatsapp_adi_inbound(sender,received_at);
