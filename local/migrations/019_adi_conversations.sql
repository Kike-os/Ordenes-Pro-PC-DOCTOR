-- Conversaciones de Adi AI, privadas de cada usuario.
CREATE TABLE adi_admin_conversations(
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX adi_admin_conversations_user ON adi_admin_conversations(user_id,updated_at);
CREATE TABLE adi_admin_messages(
 id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES adi_admin_conversations(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK(role IN ('user','adi')), content TEXT NOT NULL, links TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL);
CREATE INDEX adi_admin_messages_conversation ON adi_admin_messages(conversation_id);
