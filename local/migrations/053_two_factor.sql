-- Verificación en dos pasos (opcional, por usuario) con aplicación de autenticación (TOTP) y códigos de recuperación de un solo uso.
-- Solo crea tablas nuevas: no cambia usuarios, contraseñas ni sesiones existentes.
CREATE TABLE user_mfa (
 user_id INTEGER PRIMARY KEY REFERENCES users(id),
 secret TEXT NOT NULL,
 confirmed_at INTEGER,
 last_step INTEGER NOT NULL DEFAULT 0,
 recovery TEXT NOT NULL DEFAULT '[]',
 created_at INTEGER NOT NULL
);
CREATE TABLE mfa_challenges (
 token_hash TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id),
 remember INTEGER NOT NULL DEFAULT 0,
 fails INTEGER NOT NULL DEFAULT 0,
 expires INTEGER NOT NULL
);
CREATE INDEX mfa_challenges_expiry ON mfa_challenges(expires);
