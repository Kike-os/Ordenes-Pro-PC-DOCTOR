-- Database Guardian Pro 1.0: libro de migraciones (checksum, fecha, duración, resultado, versión y ejecutor de cada aplicación).
-- Solo crea una tabla: no modifica datos. Las migraciones anteriores siguen registradas en `migrations` (sin detalle).
CREATE TABLE IF NOT EXISTS migration_ledger (
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL,
 checksum TEXT NOT NULL,
 applied_at TEXT NOT NULL,
 duration_ms INTEGER NOT NULL DEFAULT 0,
 result TEXT NOT NULL,
 version TEXT NOT NULL DEFAULT '',
 executor TEXT NOT NULL DEFAULT '',
 verified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS migration_ledger_name ON migration_ledger(name, id);
