ALTER TABLE maintenance ADD COLUMN appointment_id INTEGER REFERENCES appointments(id);
