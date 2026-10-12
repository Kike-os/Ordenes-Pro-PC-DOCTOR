-- Borradores de Nueva orden guardados en el servidor: uno por usuario, con revisión para detectar cambios hechos desde otra sesión.
CREATE TABLE order_drafts (
 id INTEGER PRIMARY KEY,
 user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
 payload TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1,
 status TEXT NOT NULL DEFAULT 'active',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
