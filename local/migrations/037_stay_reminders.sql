-- Avisos de permanencia en taller enviados al cliente: uno por orden y etapa (día del aviso), con su resultado.
CREATE TABLE stay_reminders (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 stage INTEGER NOT NULL,
 recipient TEXT NOT NULL DEFAULT '',
 result TEXT NOT NULL CHECK(result IN ('processing','sent','failed')),
 message_id TEXT NOT NULL DEFAULT '',
 detail TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 UNIQUE(order_id,stage)
);
