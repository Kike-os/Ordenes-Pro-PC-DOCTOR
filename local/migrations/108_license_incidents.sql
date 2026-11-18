-- 1.5.291 · Licencias Digitales Premium Enterprise 3.0: incidencias de activación y reemplazos de licencias.
-- Solo crea una tabla nueva (vacía) con su índice y protecciones. No cambia ni borra datos existentes.
-- Reversión documentada (docs/LICENCIAS.md): mientras no tenga filas, basta con DROP TABLE license_incidents y quitar la fila de migrations.
-- Una incidencia no se borra ni se reescribe: solo se resuelve una vez (resolución, quién, cuándo y, si hubo, la licencia de reemplazo).
CREATE TABLE IF NOT EXISTS license_incidents (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 unit_id INTEGER NOT NULL REFERENCES license_units(id),
 kind TEXT NOT NULL CHECK(kind IN ('activacion','clave_invalida','dispositivos','cliente','otro')),
 detail TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'abierta' CHECK(status IN ('abierta','resuelta')),
 resolution TEXT NOT NULL DEFAULT '',
 replacement_unit_id INTEGER REFERENCES license_units(id),
 opened_by INTEGER REFERENCES users(id),
 opened_at TEXT NOT NULL,
 resolved_by INTEGER REFERENCES users(id),
 resolved_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS license_incidents_unit ON license_incidents(unit_id,id);
CREATE INDEX IF NOT EXISTS license_incidents_open ON license_incidents(status,opened_at);
CREATE TRIGGER IF NOT EXISTS license_incidents_no_delete BEFORE DELETE ON license_incidents BEGIN SELECT RAISE(ABORT,'Las incidencias de licencias no se eliminan'); END;
CREATE TRIGGER IF NOT EXISTS license_incidents_fixed BEFORE UPDATE OF unit_id,kind,detail,opened_by,opened_at ON license_incidents BEGIN SELECT RAISE(ABORT,'Los datos de la incidencia no se modifican'); END;
CREATE TRIGGER IF NOT EXISTS license_incidents_once BEFORE UPDATE ON license_incidents WHEN OLD.status='resuelta' BEGIN SELECT RAISE(ABORT,'La incidencia ya está resuelta'); END;
