-- 1.5.277 · Idioma en que el cliente hizo la reserva pública (es-EC o en-US). Solo añade una columna; las citas existentes quedan en español,
-- que es el idioma en que se registraron. No cambia estados, autorizaciones, notificaciones ni la integración con el calendario.
ALTER TABLE appointments ADD COLUMN language TEXT NOT NULL DEFAULT 'es-EC';
