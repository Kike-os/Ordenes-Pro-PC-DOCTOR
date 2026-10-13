-- Tipo de identificación (cédula o RUC) con el que se agendó la cita. Las citas anteriores quedan sin tipo; no se modifica ninguna.
ALTER TABLE appointments ADD COLUMN document_type TEXT NOT NULL DEFAULT '';
