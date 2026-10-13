-- Feriados: modo de atención (normal, horario especial o cerrado), ámbito (nacional, local u otro), lugar y ocultación de un feriado calculado.
-- Las filas existentes eran «días no laborables»: conservan su efecto (cerrado). No se modifica ninguna cita.
ALTER TABLE appointment_holidays ADD COLUMN mode TEXT NOT NULL DEFAULT 'cerrado' CHECK(mode IN ('normal','especial','cerrado'));
ALTER TABLE appointment_holidays ADD COLUMN open_time TEXT NOT NULL DEFAULT '';
ALTER TABLE appointment_holidays ADD COLUMN close_time TEXT NOT NULL DEFAULT '';
ALTER TABLE appointment_holidays ADD COLUMN scope TEXT NOT NULL DEFAULT 'otro' CHECK(scope IN ('nacional','local','otro'));
ALTER TABLE appointment_holidays ADD COLUMN place TEXT NOT NULL DEFAULT '';
ALTER TABLE appointment_holidays ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1));
