-- ADI 3.0 · fase 3: Configuración financiera — Tasas legales Ecuador. Solo crea una tabla. Cada tasa se registra «sin validar»; solo cambia
-- su estado (validada/anulada) con nota y auditoría; una corrección es una fila nueva, así se conserva el historial.
-- Las tasas solo alimentan el SIMULADOR de intereses: no se aplican intereses reales ni cambian saldos, pagos o facturas.
CREATE TABLE IF NOT EXISTS financial_rates (
 id INTEGER PRIMARY KEY,
 kind TEXT NOT NULL CHECK(kind IN ('legal','maxima_convencional')),
 annual_bp INTEGER NOT NULL CHECK(annual_bp > 0 AND annual_bp < 10000),
 effective_from TEXT NOT NULL,
 effective_to TEXT NOT NULL DEFAULT '',
 consulted_at TEXT NOT NULL,
 source_url TEXT NOT NULL,
 evidence TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('sin_validar','validada','anulada')),
 note TEXT NOT NULL DEFAULT '',
 user_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS financial_rates_kind ON financial_rates(kind, effective_from, id);
