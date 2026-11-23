-- Bloqueo de emisión y envío de comprobantes (1.5.319): mientras está CERRADO, el servidor rechaza emitir en Órdenes Pro, enviar,
-- reprocesar o anular en AZUR, la consulta programada de AZUR y los correos de facturas. Solo crea tablas nuevas; nada existente cambia.
-- Si esta tabla no existe o no tiene fila, el código lo trata como CERRADO (falla cerrado).
CREATE TABLE invoicing_emission_lock (
 id INTEGER PRIMARY KEY CHECK(id=1),
 locked INTEGER NOT NULL DEFAULT 1 CHECK(locked IN (0,1)),
 reason TEXT NOT NULL DEFAULT '',
 changed_by INTEGER REFERENCES users(id),
 changed_at TEXT NOT NULL DEFAULT ''
);
INSERT INTO invoicing_emission_lock(id,locked,reason,changed_at) VALUES (1,1,'Configuración en curso: emisión y envío bloqueados.','');
-- Historial inmutable de cada apertura o cierre.
CREATE TABLE invoicing_emission_lock_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 locked INTEGER NOT NULL CHECK(locked IN (0,1)),
 reason TEXT NOT NULL,
 actor_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE TRIGGER invoicing_emission_lock_events_no_update BEFORE UPDATE ON invoicing_emission_lock_events BEGIN SELECT RAISE(ABORT,'El historial del bloqueo de emisión no se modifica'); END;
CREATE TRIGGER invoicing_emission_lock_events_no_delete BEFORE DELETE ON invoicing_emission_lock_events BEGIN SELECT RAISE(ABORT,'El historial del bloqueo de emisión no se elimina'); END;
