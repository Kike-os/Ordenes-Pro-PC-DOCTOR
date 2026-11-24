-- ADI Executive Intelligence 5.0: favoritos y archivo de conversaciones, metadatos verificables de cada respuesta (pasos ejecutados,
-- fuentes y hora de consulta) y calificación de respuestas. Solo crea tablas e índices nuevos (aditiva). Privado por usuario.
CREATE TABLE IF NOT EXISTS adi_admin_flags(
 conversation_id INTEGER PRIMARY KEY REFERENCES adi_admin_conversations(id) ON DELETE CASCADE,
 favorite INTEGER NOT NULL DEFAULT 0 CHECK(favorite IN (0,1)),
 archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
 updated_at TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS adi_admin_meta(
 message_id INTEGER PRIMARY KEY REFERENCES adi_admin_messages(id) ON DELETE CASCADE,
 steps TEXT NOT NULL DEFAULT '[]',
 sources TEXT NOT NULL DEFAULT '[]',
 consulted_at TEXT NOT NULL DEFAULT '',
 origin TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS adi_admin_feedback(
 message_id INTEGER PRIMARY KEY REFERENCES adi_admin_messages(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id),
 rating INTEGER NOT NULL CHECK(rating IN (-1,1)),
 created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS adi_admin_feedback_user ON adi_admin_feedback(user_id,created_at);
