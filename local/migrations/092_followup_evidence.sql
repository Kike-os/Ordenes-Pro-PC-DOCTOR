-- Seguimiento rediseñado (04/11/2026): evidencias de hasta 10 MiB guardadas en la base por partes (Vercel no admite más de 4,5 MB por
-- petición), miniatura aparte del original, visibilidad y retiro con registro, nuevos campos internos y borrador del seguimiento.
-- SOLO añade tablas y columnas con valores por defecto: los seguimientos y evidencias anteriores (guardados enteros) no cambian.
-- Reversión (antes de usarlas): DROP TABLE order_followup_drafts; DROP TABLE order_followup_file_changes; DROP TABLE order_upload_parts;
-- DROP TABLE order_uploads; las columnas añadidas quedan vacías.

-- Carga de un archivo en partes. «subiendo» → «lista» (verificada: tamaño, SHA-256 y tipo real) → «usada» (ya es una evidencia).
CREATE TABLE order_uploads (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 token TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL,
 size INTEGER NOT NULL CHECK(size BETWEEN 1 AND 10485760),
 sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 parts INTEGER NOT NULL CHECK(parts BETWEEN 1 AND 8),
 mime TEXT NOT NULL DEFAULT '',
 thumb TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'subiendo' CHECK(status IN ('subiendo','lista','usada')),
 file_id INTEGER REFERENCES order_followup_files(id),
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX order_uploads_order ON order_uploads(order_id,status);
CREATE TABLE order_upload_parts (
 upload_id INTEGER NOT NULL REFERENCES order_uploads(id),
 idx INTEGER NOT NULL CHECK(idx BETWEEN 0 AND 7),
 data TEXT NOT NULL,
 PRIMARY KEY(upload_id,idx)
);
-- Las partes de un archivo que ya es evidencia no se modifican ni se borran (las de una carga abandonada sí se limpian).
CREATE TRIGGER order_upload_parts_used_no_delete BEFORE DELETE ON order_upload_parts
 WHEN (SELECT status FROM order_uploads WHERE id=OLD.upload_id)='usada' BEGIN SELECT RAISE(ABORT,'Una evidencia no se elimina'); END;
CREATE TRIGGER order_upload_parts_no_update BEFORE UPDATE ON order_upload_parts BEGIN SELECT RAISE(ABORT,'Una parte de archivo no se modifica'); END;
CREATE TRIGGER order_uploads_used_no_delete BEFORE DELETE ON order_uploads WHEN OLD.status='usada' BEGIN SELECT RAISE(ABORT,'Una evidencia no se elimina'); END;

-- Evidencias: dónde está el contenido («inline» = columna data, como hasta ahora; «partes» = order_upload_parts) y su miniatura.
ALTER TABLE order_followup_files ADD COLUMN storage TEXT NOT NULL DEFAULT 'inline';
ALTER TABLE order_followup_files ADD COLUMN upload_id INTEGER REFERENCES order_uploads(id);
ALTER TABLE order_followup_files ADD COLUMN thumb TEXT NOT NULL DEFAULT '';

-- Cambios posteriores de una evidencia (mostrar u ocultar al cliente, retirar): registro que no se modifica ni se borra.
CREATE TABLE order_followup_file_changes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 file_id INTEGER NOT NULL REFERENCES order_followup_files(id),
 visible INTEGER NOT NULL CHECK(visible IN (0,1)),
 retired INTEGER NOT NULL DEFAULT 0 CHECK(retired IN (0,1)),
 reason TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX order_followup_file_changes_file ON order_followup_file_changes(file_id,id);
CREATE TRIGGER order_followup_file_changes_no_update BEFORE UPDATE ON order_followup_file_changes BEGIN SELECT RAISE(ABORT,'El registro de evidencias no se modifica'); END;
CREATE TRIGGER order_followup_file_changes_no_delete BEFORE DELETE ON order_followup_file_changes BEGIN SELECT RAISE(ABORT,'El registro de evidencias no se elimina'); END;

-- Seguimiento: observaciones y diagnóstico internos (nunca se publican), responsable y recordatorio de la próxima acción.
ALTER TABLE order_followups ADD COLUMN observations TEXT NOT NULL DEFAULT '';
ALTER TABLE order_followups ADD COLUMN diagnosis TEXT NOT NULL DEFAULT '';
ALTER TABLE order_followups ADD COLUMN next_owner_id INTEGER REFERENCES users(id);
ALTER TABLE order_followups ADD COLUMN next_reminder INTEGER NOT NULL DEFAULT 0 CHECK(next_reminder IN (0,1));

-- Borrador del seguimiento de cada usuario en cada orden (sin evidencias). No es un seguimiento: no aparece en el historial.
CREATE TABLE order_followup_drafts (
 order_id INTEGER NOT NULL REFERENCES orders(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 data TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(order_id,user_id)
);
