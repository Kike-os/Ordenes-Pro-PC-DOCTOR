-- Eliminación lógica de citas: la fila se conserva con quién, cuándo y por qué se retiró de la agenda activa.
ALTER TABLE appointments ADD COLUMN deleted_at TEXT;
ALTER TABLE appointments ADD COLUMN deleted_by INTEGER REFERENCES users(id);
ALTER TABLE appointments ADD COLUMN delete_reason TEXT NOT NULL DEFAULT '';
-- Decisión administrativa: si se eliminó la cita automática de un mantenimiento, no se vuelve a generar sola.
ALTER TABLE maintenance ADD COLUMN auto_appointment_blocked INTEGER NOT NULL DEFAULT 0;
