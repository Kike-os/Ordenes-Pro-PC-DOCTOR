-- Configuración general de la caja (una sola fila). La apertura obligatoria queda ACTIVADA: con la caja cerrada no se registran cobros ni se
-- confirman ventas presenciales (borradores, cotizaciones y proformas sin cobro siguen permitidos). Administración puede desactivarla.
-- difference_limit_cents: diferencia de cierre que se acepta sin revisión de administración (0 = toda diferencia va a revisión, como hasta ahora).
CREATE TABLE cash_settings (
 id INTEGER PRIMARY KEY CHECK(id=1),
 default_fund_cents INTEGER NOT NULL DEFAULT 0 CHECK(default_fund_cents BETWEEN 0 AND 10000000),
 require_open INTEGER NOT NULL DEFAULT 1 CHECK(require_open IN (0,1)),
 difference_limit_cents INTEGER NOT NULL DEFAULT 0 CHECK(difference_limit_cents BETWEEN 0 AND 1000000),
 updated_at TEXT NOT NULL DEFAULT '',
 updated_by INTEGER REFERENCES users(id)
);
INSERT INTO cash_settings(id) VALUES (1);
