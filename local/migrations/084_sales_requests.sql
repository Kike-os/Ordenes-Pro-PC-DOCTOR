-- Centro de Ventas: pedidos comerciales (solicitudes de clientes, productos pedidos a proveedores y entregas pendientes).
-- Solo agrega tablas nuevas: no cambia ni borra datos. Un pedido no se elimina (se cancela con motivo) y su historial no se modifica.
CREATE TABLE sales_requests (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL UNIQUE,
 client_id INTEGER NOT NULL REFERENCES clients(id),
 kind TEXT NOT NULL DEFAULT 'producto' CHECK(kind IN ('producto','licencia','servicio','otro')),
 description TEXT NOT NULL CHECK(length(description) BETWEEN 2 AND 300),
 quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity BETWEEN 1 AND 10000),
 inventory_item_id INTEGER REFERENCES inventory_items(id),
 supplier_id INTEGER REFERENCES suppliers(id),
 estimate_cents INTEGER CHECK(estimate_cents IS NULL OR estimate_cents>=0),
 status TEXT NOT NULL DEFAULT 'solicitado' CHECK(status IN ('solicitado','pedido_proveedor','recibido','entregado','cancelado')),
 expected_at TEXT NOT NULL DEFAULT '',
 proforma_id INTEGER REFERENCES proformas(id),
 license_sale_id INTEGER REFERENCES license_sales(id),
 notes TEXT NOT NULL DEFAULT '',
 cancel_reason TEXT NOT NULL DEFAULT '',
 request_key TEXT UNIQUE,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX sales_requests_status ON sales_requests(status,created_at);
CREATE INDEX sales_requests_client ON sales_requests(client_id);
CREATE TRIGGER sales_requests_no_delete BEFORE DELETE ON sales_requests BEGIN SELECT RAISE(ABORT,'Un pedido comercial no se elimina: se cancela con motivo'); END;
CREATE TABLE sales_request_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 request_id INTEGER NOT NULL REFERENCES sales_requests(id),
 status TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX sales_request_events_request ON sales_request_events(request_id);
CREATE TRIGGER sales_request_events_no_update BEFORE UPDATE ON sales_request_events BEGIN SELECT RAISE(ABORT,'El historial del pedido no se modifica'); END;
CREATE TRIGGER sales_request_events_no_delete BEFORE DELETE ON sales_request_events BEGIN SELECT RAISE(ABORT,'El historial del pedido no se elimina'); END;
