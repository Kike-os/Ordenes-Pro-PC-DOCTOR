-- Historial de impresión y descarga de comprobantes (Centro de impresión). Solo crea una tabla: no modifica facturas, pagos ni secuenciales.
-- Registra SOLICITUDES (vista, descarga, impresión, reimpresión): el navegador no puede confirmar que el papel salió impreso.
CREATE TABLE IF NOT EXISTS invoice_print_log (
 id INTEGER PRIMARY KEY,
 invoice_id INTEGER NOT NULL REFERENCES invoices(id),
 user_id INTEGER REFERENCES users(id),
 format TEXT NOT NULL,
 copies INTEGER NOT NULL DEFAULT 1,
 action TEXT NOT NULL CHECK(action IN ('vista','descarga','impresion','reimpresion')),
 result TEXT NOT NULL CHECK(result IN ('solicitada','descargada','enviada_al_dialogo')),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS invoice_print_log_invoice ON invoice_print_log(invoice_id, created_at);
