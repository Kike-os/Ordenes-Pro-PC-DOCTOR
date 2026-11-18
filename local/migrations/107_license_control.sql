-- 1.5.290 · Licencias Pro Premium 4.0: seguimiento comercial de renovaciones y dispositivos registrados por licencia.
-- Solo crea tablas nuevas (vacías) con sus índices y protecciones. No cambia ni borra datos existentes.
-- license_followups: un registro por cada gestión comercial del ciclo de vencimiento (licencia + fecha de vencimiento). Solo anexado:
--   el estado vigente del ciclo es el del último registro; «completado» no se guarda: lo da la renovación registrada (renewed_to).
-- license_devices: equipos en los que se instaló la licencia. No se borran: al retirarlos se registra quién, cuándo y por qué.
CREATE TABLE IF NOT EXISTS license_followups (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 unit_id INTEGER NOT NULL REFERENCES license_units(id),
 expires_at TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('sin_contactar','contactado','esperando_respuesta','aceptado','rechazado')),
 channel TEXT NOT NULL DEFAULT '' CHECK(channel IN ('','telefono','whatsapp','correo','presencial','otro')),
 note TEXT NOT NULL DEFAULT '',
 next_contact TEXT NOT NULL DEFAULT '',
 user_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS license_followups_unit ON license_followups(unit_id,id);
CREATE INDEX IF NOT EXISTS license_followups_created ON license_followups(created_at);
CREATE TRIGGER IF NOT EXISTS license_followups_no_update BEFORE UPDATE ON license_followups BEGIN SELECT RAISE(ABORT,'El seguimiento de renovaciones no se modifica'); END;
CREATE TRIGGER IF NOT EXISTS license_followups_no_delete BEFORE DELETE ON license_followups BEGIN SELECT RAISE(ABORT,'El seguimiento de renovaciones no se elimina'); END;
CREATE TABLE IF NOT EXISTS license_devices (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 unit_id INTEGER NOT NULL REFERENCES license_units(id),
 device_id INTEGER REFERENCES devices(id),
 label TEXT NOT NULL,
 serial TEXT NOT NULL DEFAULT '',
 added_by INTEGER REFERENCES users(id),
 added_at TEXT NOT NULL,
 removed_at TEXT NOT NULL DEFAULT '',
 removed_by INTEGER REFERENCES users(id),
 removed_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS license_devices_unit ON license_devices(unit_id,id);
CREATE TRIGGER IF NOT EXISTS license_devices_no_delete BEFORE DELETE ON license_devices BEGIN SELECT RAISE(ABORT,'Los dispositivos de una licencia no se eliminan: se retiran con motivo'); END;
CREATE TRIGGER IF NOT EXISTS license_devices_fixed BEFORE UPDATE OF unit_id,device_id,label,serial,added_by,added_at ON license_devices BEGIN SELECT RAISE(ABORT,'Los datos del dispositivo no se modifican'); END;
CREATE TRIGGER IF NOT EXISTS license_devices_once BEFORE UPDATE OF removed_at ON license_devices WHEN OLD.removed_at!='' BEGIN SELECT RAISE(ABORT,'El dispositivo ya fue retirado'); END;
