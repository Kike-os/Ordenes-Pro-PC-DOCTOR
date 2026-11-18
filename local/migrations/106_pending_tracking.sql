-- 1.5.289 · Centro de Notificaciones y Pendientes Premium 3.0: responsable del seguimiento y pendientes pospuestos.
-- Solo crea una tabla nueva (vacía) con sus índices y protecciones. No cambia ni borra datos existentes.
-- Registro de solo anexado: cada asignación, aplazamiento o reanudación es una fila nueva; la vigente es la última de cada pendiente.
-- Nada de esto resuelve un pendiente: sigue desapareciendo solo cuando su módulo de origen lo cierra.
CREATE TABLE IF NOT EXISTS pending_tracking (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 key TEXT NOT NULL,
 module TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('asignacion','pospuesto','reanudado')),
 assignee_id INTEGER REFERENCES users(id),
 until TEXT NOT NULL DEFAULT '',
 body TEXT NOT NULL DEFAULT '',
 user_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pending_tracking_key ON pending_tracking(key,id);
CREATE INDEX IF NOT EXISTS pending_tracking_created ON pending_tracking(created_at);
CREATE TRIGGER IF NOT EXISTS pending_tracking_no_update BEFORE UPDATE ON pending_tracking BEGIN SELECT RAISE(ABORT,'El seguimiento de pendientes no se modifica'); END;
CREATE TRIGGER IF NOT EXISTS pending_tracking_no_delete BEFORE DELETE ON pending_tracking BEGIN SELECT RAISE(ABORT,'El seguimiento de pendientes no se elimina'); END;
