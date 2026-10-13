-- Cierre de sesión por inactividad: cada sesión guarda el momento de la última actividad real de la persona.
-- Solo añade una columna; las sesiones abiertas empiezan a contar desde la migración.
ALTER TABLE sessions ADD COLUMN last_activity INTEGER;
UPDATE sessions SET last_activity=CAST(strftime('%s','now') AS INTEGER) WHERE last_activity IS NULL;
