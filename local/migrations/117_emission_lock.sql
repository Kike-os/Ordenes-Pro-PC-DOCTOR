-- Bloqueo de emisión y envío de comprobantes: mientras está CERRADO, el servidor rechaza emitir en Órdenes Pro, enviar, reprocesar o anular
-- en AZUR, la consulta programada de AZUR y los correos de facturas. Solo crea tablas nuevas (aplicable desde Sistema).
-- Sin tabla o sin fila, el código lo trata como CERRADO (falla cerrado); la fila id=1 la crea el código al primer cambio.
CREATE TABLE IF NOT EXISTS invoicing_emission_lock (
 id INTEGER PRIMARY KEY CHECK(id=1),
 locked INTEGER NOT NULL DEFAULT 1 CHECK(locked IN (0,1)),
 reason TEXT NOT NULL DEFAULT '',
 changed_by INTEGER REFERENCES users(id),
 changed_at TEXT NOT NULL DEFAULT ''
);
-- Historial de cada apertura o cierre (el código solo inserta; además queda en la auditoría general).
CREATE TABLE IF NOT EXISTS invoicing_emission_lock_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 locked INTEGER NOT NULL CHECK(locked IN (0,1)),
 reason TEXT NOT NULL,
 actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
