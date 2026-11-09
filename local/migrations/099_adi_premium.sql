-- ADI Premium 4.0 (1.5.265). Solo añade dos columnas vacías y una tabla nueva: no cambia órdenes, fotos, evidencias, pagos ni mensajes.
-- Nombre original del archivo que eligió el usuario, como metadato. El nombre descriptivo sigue en order_photos.filename y order_followup_files.name.
ALTER TABLE order_photos ADD COLUMN original_name TEXT NOT NULL DEFAULT '';
ALTER TABLE order_followup_files ADD COLUMN original_name TEXT NOT NULL DEFAULT '';
-- Recomendaciones informativas de ADI que un usuario descartó en una orden. Se guardan con la huella de los datos que las originaron: si esos
-- datos cambian, la recomendación vuelve a mostrarse. Descartar no modifica ningún dato operativo.
-- Reversión (antes de usarla): DROP TABLE adi_dismissals; las columnas vacías pueden quedar.
CREATE TABLE adi_dismissals (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 order_id INTEGER NOT NULL REFERENCES orders(id),
 rec_key TEXT NOT NULL CHECK(length(rec_key) BETWEEN 2 AND 60),
 fingerprint TEXT NOT NULL CHECK(length(fingerprint) BETWEEN 8 AND 64),
 created_at TEXT NOT NULL,
 UNIQUE(user_id,order_id,rec_key,fingerprint)
);
CREATE INDEX adi_dismissals_order ON adi_dismissals(order_id,user_id);
