-- Portal seguro del cliente (Premium Billing Center): sesiones temporales de consulta abiertas con el enlace de seguimiento de la orden
-- y los últimos 4 dígitos de la identificación. Solo se guarda la huella del token (nunca el token). Solo crea tablas e índices nuevos.
CREATE TABLE IF NOT EXISTS client_portal_sessions(
 token_hash TEXT PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 link_hash TEXT NOT NULL,
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 ip_hash TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS client_portal_sessions_order ON client_portal_sessions(order_id,expires_at);
