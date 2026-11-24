-- ADI Live Support Center 4.0: sesiones de atención con cierre por inactividad calculado en el servidor y registro de eventos.
-- Solo crea tablas: las conversaciones y sus mensajes no cambian ni se borran al cerrarse.
CREATE TABLE IF NOT EXISTS support_sessions (
 conversation_id INTEGER PRIMARY KEY REFERENCES adi_conversations(id),
 channel TEXT NOT NULL DEFAULT 'web',
 opened_at TEXT NOT NULL,
 last_client_at TEXT NOT NULL DEFAULT '',
 last_adi_at TEXT NOT NULL DEFAULT '',
 last_human_at TEXT NOT NULL DEFAULT '',
 last_activity_at TEXT NOT NULL,
 last_activity_by TEXT NOT NULL DEFAULT '',
 expires_at TEXT NOT NULL,
 warned_at TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'activa' CHECK(status IN ('activa','cerrada')),
 closed_at TEXT NOT NULL DEFAULT '',
 effective_close_at TEXT NOT NULL DEFAULT '',
 close_reason TEXT NOT NULL DEFAULT '',
 close_kind TEXT NOT NULL DEFAULT '',
 closed_by INTEGER REFERENCES users(id),
 reopened_count INTEGER NOT NULL DEFAULT 0,
 pause_until TEXT NOT NULL DEFAULT '',
 pause_reason TEXT NOT NULL DEFAULT '',
 paused_by INTEGER REFERENCES users(id),
 processing_until TEXT NOT NULL DEFAULT '',
 first_response_at TEXT NOT NULL DEFAULT '',
 version INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS support_sessions_due ON support_sessions(status, expires_at);
CREATE TABLE IF NOT EXISTS support_events (
 id INTEGER PRIMARY KEY,
 conversation_id INTEGER NOT NULL REFERENCES adi_conversations(id),
 kind TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 user_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 idem TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS support_events_idem ON support_events(idem);
CREATE INDEX IF NOT EXISTS support_events_conv ON support_events(conversation_id, id);
