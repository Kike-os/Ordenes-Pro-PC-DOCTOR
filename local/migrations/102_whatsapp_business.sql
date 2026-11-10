-- 1.5.275 · WhatsApp Business (API oficial de Meta): cola propia de avisos y autorizaciones del cliente.
-- Solo crea tablas nuevas: no modifica order_status_notices, order_part_notices, order_messages ni el correo.
CREATE TABLE IF NOT EXISTS whatsapp_outbox (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 dedupe_key TEXT NOT NULL UNIQUE,
 event TEXT NOT NULL,
 source TEXT NOT NULL DEFAULT '',
 order_id INTEGER REFERENCES orders(id),
 client_id INTEGER REFERENCES clients(id),
 appointment_id INTEGER,
 part_request_id INTEGER,
 recipient TEXT NOT NULL DEFAULT '',
 template TEXT NOT NULL DEFAULT '',
 template_lang TEXT NOT NULL DEFAULT '',
 params TEXT NOT NULL DEFAULT '[]',
 preview TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('pendiente','enviando','enviado','entregado','leido','fallido','omitido')),
 detail TEXT NOT NULL DEFAULT '',
 reason_kind TEXT NOT NULL DEFAULT '',
 error_code TEXT NOT NULL DEFAULT '',
 permanent INTEGER NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt_at TEXT NOT NULL DEFAULT '',
 locked_until TEXT NOT NULL DEFAULT '',
 provider_id TEXT NOT NULL DEFAULT '',
 message_id INTEGER REFERENCES order_messages(id),
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 sent_at TEXT NOT NULL DEFAULT '',
 delivered_at TEXT NOT NULL DEFAULT '',
 read_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS whatsapp_outbox_due ON whatsapp_outbox(status,next_attempt_at);
CREATE INDEX IF NOT EXISTS whatsapp_outbox_order ON whatsapp_outbox(order_id,id);
CREATE INDEX IF NOT EXISTS whatsapp_outbox_part ON whatsapp_outbox(part_request_id,id);
CREATE INDEX IF NOT EXISTS whatsapp_outbox_provider ON whatsapp_outbox(provider_id);
CREATE TRIGGER IF NOT EXISTS whatsapp_outbox_no_delete BEFORE DELETE ON whatsapp_outbox BEGIN SELECT RAISE(ABORT,'Un aviso registrado no se elimina'); END;

-- Autorización del cliente para recibir avisos por WhatsApp. Registro inmutable: la decisión vigente es la más reciente de cada número.
CREATE TABLE IF NOT EXISTS whatsapp_consents (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 phone TEXT NOT NULL,
 client_id INTEGER REFERENCES clients(id),
 decision TEXT NOT NULL CHECK(decision IN ('aceptado','rechazado')),
 source TEXT NOT NULL CHECK(source IN ('presencial','telefono','mensaje','formulario','baja')),
 detail TEXT NOT NULL DEFAULT '',
 recorded_at TEXT NOT NULL,
 actor_id INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS whatsapp_consents_phone ON whatsapp_consents(phone,id);
CREATE INDEX IF NOT EXISTS whatsapp_consents_client ON whatsapp_consents(client_id,id);
CREATE TRIGGER IF NOT EXISTS whatsapp_consents_no_delete BEFORE DELETE ON whatsapp_consents BEGIN SELECT RAISE(ABORT,'Una autorización registrada no se elimina'); END;
CREATE TRIGGER IF NOT EXISTS whatsapp_consents_no_update BEFORE UPDATE ON whatsapp_consents BEGIN SELECT RAISE(ABORT,'Una autorización registrada no se modifica'); END;
