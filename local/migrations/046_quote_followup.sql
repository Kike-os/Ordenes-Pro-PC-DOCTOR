-- Partidas que el cliente deja pendientes: pasan a una versión de continuación que conserva lo ya autorizado en la anterior.
-- Estado de ejecución de cada partida aprobada, marcado por el personal técnico.
ALTER TABLE quotes ADD COLUMN continues_id INTEGER REFERENCES quotes(id);
ALTER TABLE quote_items ADD COLUMN execution TEXT NOT NULL DEFAULT 'pendiente' CHECK(execution IN ('pendiente','proceso','realizado'));
ALTER TABLE quote_items ADD COLUMN execution_by INTEGER REFERENCES users(id);
ALTER TABLE quote_items ADD COLUMN execution_at TEXT NOT NULL DEFAULT '';
