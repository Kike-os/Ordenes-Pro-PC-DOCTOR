-- ADI Smart Message Status · Live Read Receipts 1.0: estado de envío, entrega y lectura de cada mensaje (chat web y WhatsApp).
-- Solo crea una tabla: los mensajes no cambian. Los estados solo avanzan (un evento atrasado nunca hace retroceder un «leído»).
CREATE TABLE IF NOT EXISTS message_receipts (
 message_id INTEGER PRIMARY KEY REFERENCES adi_messages(id),
 conversation_id INTEGER NOT NULL REFERENCES adi_conversations(id),
 channel TEXT NOT NULL DEFAULT 'web',
 direction TEXT NOT NULL CHECK(direction IN ('entrante','saliente')),
 provider_id TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('enviando','enviado','entregado','leido','error','reintentando')),
 sent_at TEXT NOT NULL DEFAULT '',
 delivered_at TEXT NOT NULL DEFAULT '',
 read_at TEXT NOT NULL DEFAULT '',
 failed_at TEXT NOT NULL DEFAULT '',
 error TEXT NOT NULL DEFAULT '',
 read_by TEXT NOT NULL DEFAULT '',
 meta_read_sent INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS message_receipts_provider ON message_receipts(provider_id);
CREATE INDEX IF NOT EXISTS message_receipts_conv ON message_receipts(conversation_id, message_id);
