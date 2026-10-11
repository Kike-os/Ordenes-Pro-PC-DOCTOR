-- PC-DOCTOR Mail Pro: los mensajes viven en el servidor de correo; aquí solo se guardan vínculos y el control de envíos.
CREATE TABLE mail_links(
 id INTEGER PRIMARY KEY, message_id TEXT NOT NULL, folder TEXT NOT NULL, uid INTEGER NOT NULL,
 order_id INTEGER NOT NULL REFERENCES orders(id), subject TEXT NOT NULL DEFAULT '', correspondent TEXT NOT NULL DEFAULT '',
 direction TEXT NOT NULL DEFAULT 'in' CHECK(direction IN ('in','out')), sent_at TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, UNIQUE(message_id,order_id));
CREATE INDEX mail_links_order ON mail_links(order_id);
CREATE TABLE mail_outbox(
 request_key TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), status TEXT NOT NULL CHECK(status IN ('sending','sent','failed')),
 message_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
