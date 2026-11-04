-- Seguimiento de pedidos de repuestos por orden (04/11/2026): cada repuesto con sus 8 etapas, su situación (en espera, retraso, incidencia,
-- cancelación), sus datos administrativos y su historial que no se modifica ni se borra. Una etapa solo cambia por una acción registrada:
-- nunca por el paso del tiempo. Cambiar de etapa no crea compras, facturas, cobros ni movimientos de inventario.
-- SOLO añade tablas y una columna con valor vacío. Reversión (antes de usarlas): DROP TABLE order_part_events; DROP TABLE order_part_requests.
CREATE TABLE order_part_requests (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(id),
 name TEXT NOT NULL CHECK(length(name) BETWEEN 2 AND 160),
 brand TEXT NOT NULL DEFAULT '',
 compatible_model TEXT NOT NULL DEFAULT '',
 reference TEXT NOT NULL DEFAULT '',
 quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity BETWEEN 1 AND 999),
 supplier_id INTEGER REFERENCES suppliers(id),
 purchase_item_id INTEGER REFERENCES purchase_items(id),
 inventory_item_id INTEGER REFERENCES inventory_items(id),
 purchase_date TEXT NOT NULL DEFAULT '',
 eta TEXT NOT NULL DEFAULT '',
 supplier_order TEXT NOT NULL DEFAULT '',
 carrier TEXT NOT NULL DEFAULT '',
 tracking_number TEXT NOT NULL DEFAULT '',
 tracking_url TEXT NOT NULL DEFAULT '',
 received_at TEXT NOT NULL DEFAULT '',
 internal_note TEXT NOT NULL DEFAULT '',
 stage TEXT NOT NULL DEFAULT 'solicitado' CHECK(stage IN ('solicitado','confirmado','preparacion','transito','recibido','instalacion','instalado','listo')),
 situation TEXT NOT NULL DEFAULT 'normal' CHECK(situation IN ('normal','espera_confirmacion','espera_proveedor','retrasado','incidencia_transporte','cancelado')),
 public_visible INTEGER NOT NULL DEFAULT 1 CHECK(public_visible IN (0,1)),
 technician_id INTEGER REFERENCES users(id),
 request_key TEXT UNIQUE,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX order_part_requests_order ON order_part_requests(order_id,id);
-- Una línea de compra ya registrada se asocia a un solo pedido de repuesto: no se crea otro pedido duplicado.
CREATE UNIQUE INDEX order_part_requests_purchase_line ON order_part_requests(purchase_item_id) WHERE purchase_item_id IS NOT NULL;
CREATE TRIGGER order_part_requests_no_delete BEFORE DELETE ON order_part_requests BEGIN SELECT RAISE(ABORT,'Un pedido de repuesto no se elimina: se cancela'); END;
-- Historial de cada repuesto: alta, etapa, situación, cambios de datos y mensajes al cliente. public_note solo se muestra si public=1.
CREATE TABLE order_part_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 request_id INTEGER NOT NULL REFERENCES order_part_requests(id),
 kind TEXT NOT NULL CHECK(kind IN ('alta','etapa','situacion','datos')),
 stage TEXT NOT NULL,
 situation TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT '',
 public_note TEXT NOT NULL DEFAULT '',
 public INTEGER NOT NULL DEFAULT 0 CHECK(public IN (0,1)),
 changes TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX order_part_events_request ON order_part_events(request_id,id);
CREATE TRIGGER order_part_events_no_update BEFORE UPDATE ON order_part_events BEGIN SELECT RAISE(ABORT,'El historial del repuesto no se modifica'); END;
CREATE TRIGGER order_part_events_no_delete BEFORE DELETE ON order_part_events BEGIN SELECT RAISE(ABORT,'El historial del repuesto no se elimina'); END;
-- Evidencias de un repuesto: se registran como un seguimiento de la orden vinculado al pedido (mismas reglas de visibilidad y retiro).
ALTER TABLE order_followups ADD COLUMN part_request_id INTEGER REFERENCES order_part_requests(id);
