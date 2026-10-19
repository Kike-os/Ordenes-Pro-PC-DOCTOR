-- Sesiones recordadas y dispositivos de confianza para la verificación en dos pasos. Solo añade columnas y una tabla: las cuentas,
-- contraseñas y sesiones existentes no cambian (las sesiones abiertas siguen como sesiones normales).
ALTER TABLE sessions ADD COLUMN remember INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sessions ADD COLUMN created_at INTEGER;
ALTER TABLE sessions ADD COLUMN device TEXT NOT NULL DEFAULT '';
-- Un navegador en el que la persona eligió «Confiar en este equipo» tras validar su código. El token solo se guarda como huella.
CREATE TABLE trusted_devices (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 token_hash TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL,
 browser TEXT NOT NULL DEFAULT '',
 system TEXT NOT NULL DEFAULT '',
 created_at INTEGER NOT NULL,
 last_used_at INTEGER NOT NULL,
 expires_at INTEGER NOT NULL,
 revoked_at INTEGER,
 revoked_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX trusted_devices_user ON trusted_devices(user_id,revoked_at,expires_at);
