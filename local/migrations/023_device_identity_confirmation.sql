ALTER TABLE devices ADD COLUMN identity_confirmed_by INTEGER REFERENCES users(id);
ALTER TABLE devices ADD COLUMN identity_confirmed_at TEXT NOT NULL DEFAULT '';
