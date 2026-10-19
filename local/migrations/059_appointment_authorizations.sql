-- Autorización digital de citas: evidencia de que el cliente aceptó expresamente las condiciones vigentes al confirmar su cita.
-- Una por cita; inmutable (no se modifica ni se borra) y conserva una copia de los datos de la cita en ese momento, de modo que la
-- evidencia sigue intacta aunque la cita se reprograme o edite. Los 4 dígitos son una comprobación de coherencia con la identificación
-- escrita, NO una firma electrónica ni una prueba de identidad. Las citas anteriores no reciben autorizaciones retroactivas.
CREATE TABLE appointment_authorizations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 authorization_id TEXT NOT NULL UNIQUE,
 appointment_id INTEGER NOT NULL UNIQUE REFERENCES appointments(id),
 client_id INTEGER REFERENCES clients(id),
 accepted_at TEXT NOT NULL,
 timezone TEXT NOT NULL CHECK(timezone='America/Guayaquil'),
 terms_id TEXT NOT NULL REFERENCES service_terms(id),
 terms_version TEXT NOT NULL,
 terms_hash TEXT NOT NULL,
 express_consent INTEGER NOT NULL CHECK(express_consent=1),
 id_last4 TEXT NOT NULL CHECK(length(id_last4)=4 AND id_last4 GLOB '[0-9][0-9][0-9][0-9]'),
 channel TEXT NOT NULL CHECK(channel IN ('en_linea','personal')),
 recorded_by INTEGER REFERENCES users(id),
 snapshot TEXT NOT NULL
);
CREATE INDEX appointment_authorizations_client ON appointment_authorizations(client_id,id);
CREATE TRIGGER appointment_authorizations_fixed BEFORE UPDATE ON appointment_authorizations
 BEGIN SELECT RAISE(ABORT,'La autorización de la cita no se modifica'); END;
CREATE TRIGGER appointment_authorizations_no_delete BEFORE DELETE ON appointment_authorizations
 BEGIN SELECT RAISE(ABORT,'La autorización de la cita no se elimina'); END;
-- Ninguna cita pasa a «Confirmada» sin una autorización válida registrada.
CREATE TRIGGER appointments_confirm_requires_authorization BEFORE UPDATE OF status ON appointments
 WHEN NEW.status='confirmada' AND OLD.status!='confirmada' AND NOT EXISTS (SELECT 1 FROM appointment_authorizations WHERE appointment_id=NEW.id)
 BEGIN SELECT RAISE(ABORT,'La cita no tiene la autorización del cliente'); END;
