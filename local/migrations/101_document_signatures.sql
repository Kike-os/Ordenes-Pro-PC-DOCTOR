-- Firmas de documentos (1.5.271). Solo añade dos tablas nuevas e inmutables; no cambia condiciones, órdenes, aceptaciones ni documentos.
-- Reversión (antes de usarlas): DROP TABLE service_terms_signed; DROP TABLE business_signature_versions.

-- Original firmado electrónicamente (PAdES) de una versión de las condiciones. El archivo se guarda tal cual se recibió, con su huella,
-- los datos del certificado y el resultado de la verificación. Nunca se modifica ni se elimina; una carga nueva queda como otra fila.
CREATE TABLE service_terms_signed (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 terms_id TEXT NOT NULL REFERENCES service_terms(id),
 filename TEXT NOT NULL DEFAULT '',
 data BLOB NOT NULL,
 size INTEGER NOT NULL CHECK(size>0),
 sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 sub_filter TEXT NOT NULL DEFAULT '',
 signer TEXT NOT NULL DEFAULT '',
 signer_id TEXT NOT NULL DEFAULT '',
 issuer TEXT NOT NULL DEFAULT '',
 cert_from TEXT NOT NULL DEFAULT '',
 cert_until TEXT NOT NULL DEFAULT '',
 signed_at TEXT NOT NULL DEFAULT '',
 timestamped INTEGER NOT NULL DEFAULT 0 CHECK(timestamped IN (0,1)),
 verified TEXT NOT NULL CHECK(verified IN ('valida','invalida','no_verificable')),
 verify_detail TEXT NOT NULL DEFAULT '',
 uploaded_by INTEGER NOT NULL REFERENCES users(id),
 uploaded_at TEXT NOT NULL
);
CREATE INDEX service_terms_signed_terms ON service_terms_signed(terms_id,id);
CREATE TRIGGER service_terms_signed_no_update BEFORE UPDATE ON service_terms_signed BEGIN SELECT RAISE(ABORT,'El original firmado no se modifica'); END;
CREATE TRIGGER service_terms_signed_no_delete BEFORE DELETE ON service_terms_signed BEGIN SELECT RAISE(ABORT,'El original firmado no se elimina'); END;

-- Firma visual empresarial: imagen original intacta (data) y sus representaciones de impresión derivadas al cargarla (A4 y ticket de
-- 80 mm en blanco y negro). Es una imagen de identificación, NO una firma electrónica. Cada carga es una versión nueva; las anteriores
-- se conservan. La configuración de uso (activación y documentos) se guarda en system_state ('business_signature').
CREATE TABLE business_signature_versions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 filename TEXT NOT NULL DEFAULT '',
 mime TEXT NOT NULL CHECK(mime IN ('image/png','image/jpeg')),
 data BLOB NOT NULL,
 size INTEGER NOT NULL CHECK(size>0),
 sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 width INTEGER NOT NULL CHECK(width>0),
 height INTEGER NOT NULL CHECK(height>0),
 rgb BLOB,
 alpha BLOB,
 thermal BLOB,
 thermal_width INTEGER NOT NULL DEFAULT 0,
 thermal_height INTEGER NOT NULL DEFAULT 0,
 uploaded_by INTEGER NOT NULL REFERENCES users(id),
 uploaded_at TEXT NOT NULL
);
CREATE TRIGGER business_signature_versions_no_update BEFORE UPDATE ON business_signature_versions BEGIN SELECT RAISE(ABORT,'Una versión de la firma no se modifica'); END;
CREATE TRIGGER business_signature_versions_no_delete BEFORE DELETE ON business_signature_versions BEGIN SELECT RAISE(ABORT,'Una versión de la firma no se elimina'); END;
