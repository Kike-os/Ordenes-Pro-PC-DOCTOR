-- Confirmación administrativa de los factores DATAFAST: quién confirmó cada porcentaje, cuándo y con qué documento.
-- SOLO añade una tabla nueva (registro que no se modifica ni se borra). No cambia ningún factor ni ningún cobro registrado.
-- Un factor «vigente» sin confirmación sigue sirviendo para cobrar (decisión de administración del 04/11/2026); un «pendiente» no.
-- Reversión (antes de usarla): DROP TABLE card_factor_confirmations;
CREATE TABLE card_factor_confirmations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 factor_id INTEGER NOT NULL REFERENCES card_factors(id),
 factor_bp INTEGER NOT NULL CHECK(factor_bp BETWEEN 0 AND 10000),
 previous_bp INTEGER CHECK(previous_bp IS NULL OR previous_bp BETWEEN 0 AND 10000),
 action TEXT NOT NULL CHECK(action IN ('confirmado','corregido','completado','configurado')),
 note TEXT NOT NULL CHECK(length(note) BETWEEN 5 AND 300),
 confirmed_at TEXT NOT NULL,
 confirmed_by INTEGER NOT NULL REFERENCES users(id),
 actor TEXT NOT NULL
);
CREATE INDEX card_factor_confirmations_factor ON card_factor_confirmations(factor_id,id);
CREATE TRIGGER card_factor_confirmations_no_update BEFORE UPDATE ON card_factor_confirmations BEGIN SELECT RAISE(ABORT,'Las confirmaciones de factores no se modifican.'); END;
CREATE TRIGGER card_factor_confirmations_no_delete BEFORE DELETE ON card_factor_confirmations BEGIN SELECT RAISE(ABORT,'Las confirmaciones de factores no se eliminan.'); END;
