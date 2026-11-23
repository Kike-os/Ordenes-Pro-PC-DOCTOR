-- Atención humana real desde WhatsApp (docs/WHATSAPP-ATENCION.md). Solo crea tablas nuevas: no modifica conversaciones ni mensajes existentes.

-- Número de WhatsApp de cada conversación de ADI que llegó por ese canal: permite que la respuesta del asesor salga por WhatsApp.
CREATE TABLE IF NOT EXISTS whatsapp_conversations (
 conversation_id INTEGER PRIMARY KEY REFERENCES adi_conversations(id),
 wa_number TEXT NOT NULL,
 created_at TEXT NOT NULL,
 last_client_at TEXT NOT NULL DEFAULT ''
);

-- Solicitudes de atención humana: una abierta por conversación (no se duplican por mensajes repetidos), con código, prioridad y motivo.
CREATE TABLE IF NOT EXISTS adi_handoffs (
 id INTEGER PRIMARY KEY,
 code TEXT NOT NULL UNIQUE,
 conversation_id INTEGER NOT NULL REFERENCES adi_conversations(id),
 channel TEXT NOT NULL DEFAULT 'whatsapp',
 status TEXT NOT NULL CHECK(status IN ('pendiente','asignada','resuelta','cerrada')),
 priority TEXT NOT NULL CHECK(priority IN ('normal','alta','urgente')),
 reason TEXT NOT NULL DEFAULT '',
 signals TEXT NOT NULL DEFAULT '',
 order_id INTEGER REFERENCES orders(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 accepted_at TEXT NOT NULL DEFAULT '',
 accepted_by INTEGER REFERENCES users(id),
 closed_at TEXT NOT NULL DEFAULT '',
 closed_by INTEGER REFERENCES users(id),
 resolution TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS adi_handoffs_one_open ON adi_handoffs(conversation_id) WHERE status IN ('pendiente','asignada');
CREATE INDEX IF NOT EXISTS adi_handoffs_status ON adi_handoffs(status, priority, created_at);

-- Resultado del envío por WhatsApp de cada mensaje del asesor (sin el texto, que ya está en adi_messages).
CREATE TABLE IF NOT EXISTS whatsapp_operator_sends (
 message_id INTEGER PRIMARY KEY REFERENCES adi_messages(id),
 conversation_id INTEGER NOT NULL REFERENCES adi_conversations(id),
 status TEXT NOT NULL CHECK(status IN ('enviado','fallido')),
 provider_id TEXT NOT NULL DEFAULT '',
 detail TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
