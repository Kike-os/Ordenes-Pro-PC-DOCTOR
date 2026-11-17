-- 1.5.288 · Centro de Control Operativo: registro de gestión de los pendientes.
-- Solo crea una tabla nueva (vacía). No cambia ni borra datos existentes. Es un registro de solo anexado: las observaciones internas,
-- los reconocimientos y silencios de alertas, los recordatorios y las resoluciones registradas no se editan ni se eliminan (trazabilidad).
-- Nada de esto resuelve un pendiente: cada pendiente sigue desapareciendo solo cuando su módulo de origen lo cierra.
CREATE TABLE IF NOT EXISTS pending_notes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 key TEXT NOT NULL,
 module TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('nota','reconocida','silenciada','recordatorio','resolucion')),
 body TEXT NOT NULL DEFAULT '',
 until TEXT NOT NULL DEFAULT '',
 user_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pending_notes_key ON pending_notes(key,id);
CREATE INDEX IF NOT EXISTS pending_notes_created ON pending_notes(created_at);
