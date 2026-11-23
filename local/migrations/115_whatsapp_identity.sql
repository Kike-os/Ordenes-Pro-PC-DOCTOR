-- Verificación de identidad por WhatsApp antes de que ADI informe sobre una orden (docs/WHATSAPP-IDENTIDAD.md).
-- Solo crea tablas nuevas: no modifica clientes, órdenes, facturas ni datos existentes. Nunca se guarda un código en texto plano.

-- Contactos autorizados adicionales de una orden (además del teléfono del titular). Los registra administración tras comprobar la
-- identidad por un procedimiento aprobado; nunca ADI. Revocar no borra: deja fecha, autor y motivo.
CREATE TABLE IF NOT EXISTS order_authorized_contacts (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 name TEXT NOT NULL,
 phone TEXT NOT NULL,
 relation TEXT NOT NULL DEFAULT '',
 evidence TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 revoked_by INTEGER REFERENCES users(id),
 revoked_at TEXT NOT NULL DEFAULT '',
 revoke_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS order_authorized_contacts_order ON order_authorized_contacts(order_id, revoked_at);

-- Estado de la conversación de verificación (por conversación de WhatsApp, identificada con HMAC del número).
CREATE TABLE IF NOT EXISTS wa_identity_state (
 conversation_hash TEXT PRIMARY KEY,
 step TEXT NOT NULL CHECK(step IN ('esperando_orden','esperando_confirmacion','esperando_codigo')),
 order_id INTEGER REFERENCES orders(id),
 challenge_id INTEGER,
 updated_at TEXT NOT NULL
);

-- Códigos de un solo uso: solo el HMAC del código, su vigencia, intentos y a quién se envió (últimos dígitos para mostrar).
CREATE TABLE IF NOT EXISTS wa_identity_challenges (
 id INTEGER PRIMARY KEY,
 conversation_hash TEXT NOT NULL,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 recipient_hash TEXT NOT NULL,
 recipient_tail TEXT NOT NULL,
 recipient_kind TEXT NOT NULL CHECK(recipient_kind IN ('titular','contacto')),
 contact_id INTEGER REFERENCES order_authorized_contacts(id),
 purpose TEXT NOT NULL DEFAULT 'consulta_orden',
 nonce TEXT NOT NULL,
 code_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pendiente','verificado','fallido','bloqueado','caducado','envio_fallido','anulado')),
 attempts INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 consumed_at TEXT NOT NULL DEFAULT '',
 send_detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS wa_identity_challenges_order ON wa_identity_challenges(order_id, created_at);
CREATE INDEX IF NOT EXISTS wa_identity_challenges_conv ON wa_identity_challenges(conversation_hash, created_at);

-- Sesiones verificadas: una orden, una conversación. Caducan a los 15 minutos sin actividad, al revocarse o si cambian los contactos.
CREATE TABLE IF NOT EXISTS wa_identity_sessions (
 id INTEGER PRIMARY KEY,
 conversation_hash TEXT NOT NULL,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 challenge_id INTEGER NOT NULL REFERENCES wa_identity_challenges(id),
 recipient_kind TEXT NOT NULL,
 recipient_tail TEXT NOT NULL,
 contacts_fingerprint TEXT NOT NULL,
 created_at TEXT NOT NULL,
 last_activity TEXT NOT NULL,
 ended_at TEXT NOT NULL DEFAULT '',
 end_reason TEXT NOT NULL DEFAULT '',
 revoked_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS wa_identity_sessions_conv ON wa_identity_sessions(conversation_hash, ended_at);
CREATE INDEX IF NOT EXISTS wa_identity_sessions_order ON wa_identity_sessions(order_id, created_at);

-- Eventos de seguridad (sin códigos, sin números completos, sin texto del cliente).
CREATE TABLE IF NOT EXISTS wa_identity_events (
 id INTEGER PRIMARY KEY,
 order_id INTEGER REFERENCES orders(id),
 conversation_hash TEXT NOT NULL DEFAULT '',
 kind TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS wa_identity_events_order ON wa_identity_events(order_id, created_at);
CREATE INDEX IF NOT EXISTS wa_identity_events_conv ON wa_identity_events(conversation_hash, created_at);
