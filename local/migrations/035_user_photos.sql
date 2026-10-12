-- Foto de perfil de cada cuenta del equipo (una por usuario), guardada en la base como las fotos de las órdenes.
CREATE TABLE user_photos (
 user_id INTEGER PRIMARY KEY REFERENCES users(id),
 mime TEXT NOT NULL CHECK(mime IN ('image/png','image/jpeg','image/webp')),
 size INTEGER NOT NULL,
 data TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
