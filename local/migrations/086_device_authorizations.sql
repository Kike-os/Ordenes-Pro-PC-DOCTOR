-- Autorizaciones aplicables según el tipo de equipo y comprobantes corregidos con trazabilidad.
-- Solo añade tablas y un valor de estado: no modifica órdenes, consentimientos, firmas ni historial.
CREATE TABLE authorization_profile_changes(
    id INTEGER PRIMARY KEY,
    changed_at TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(id),
    reason TEXT NOT NULL,
    previous TEXT NOT NULL,
    current TEXT NOT NULL
);
CREATE TABLE order_data_exceptions(
    order_id INTEGER PRIMARY KEY REFERENCES orders(id),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    note TEXT NOT NULL DEFAULT '',
    actor_id INTEGER REFERENCES users(id),
    updated_at TEXT NOT NULL
);
CREATE TABLE receipt_corrections(
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    revision INTEGER NOT NULL,
    reason TEXT NOT NULL,
    original_sha256 TEXT NOT NULL,
    corrected_sha256 TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE(order_id,revision)
);
-- Las órdenes registradas desde este momento usan el comprobante con autorizaciones por tipo de equipo; las anteriores
-- conservan su comprobante tal como se emitió hasta que el personal genere expresamente una versión corregida.
INSERT OR IGNORE INTO system_state(key,value) VALUES('authorization_layout_since',CAST(strftime('%s','now') AS TEXT));
