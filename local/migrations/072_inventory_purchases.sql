-- Inventario físico (productos, repuestos y accesorios), proveedores y compras. Solo añade estructuras: el catálogo, las licencias,
-- los presupuestos y las órdenes existentes no se modifican. Las existencias se calculan siempre a partir de los movimientos.
CREATE TABLE inventory_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 catalog_id INTEGER NOT NULL UNIQUE REFERENCES catalog_items(id),
 kind TEXT NOT NULL CHECK(kind IN ('producto','repuesto','accesorio')),
 sku TEXT NOT NULL DEFAULT '',
 min_stock INTEGER NOT NULL DEFAULT 0 CHECK(min_stock>=0),
 location TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id),
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE UNIQUE INDEX inventory_items_sku ON inventory_items(sku) WHERE sku!='';
CREATE TRIGGER inventory_items_no_delete BEFORE DELETE ON inventory_items BEGIN SELECT RAISE(ABORT,'Los artículos de inventario no se eliminan: se desactivan'); END;
-- Movimientos: la única fuente de las existencias. No se modifican ni eliminan; una corrección es otro movimiento.
CREATE TABLE inventory_movements (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 item_id INTEGER NOT NULL REFERENCES inventory_items(id),
 direction INTEGER NOT NULL CHECK(direction IN (1,-1)),
 reason TEXT NOT NULL CHECK(reason IN ('inicial','compra','devolucion_cliente','ajuste_entrada','venta','uso_orden','devolucion_proveedor','ajuste_salida','baja','anulacion_compra')),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 unit_cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(unit_cost_cents>=0),
 reference_kind TEXT NOT NULL DEFAULT '',
 reference_id INTEGER,
 note TEXT NOT NULL DEFAULT '',
 request_key TEXT UNIQUE,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
-- Un mismo documento (compra, factura, orden) no mueve dos veces el mismo artículo en el mismo sentido.
CREATE UNIQUE INDEX inventory_movements_once ON inventory_movements(reference_kind,reference_id,item_id,direction) WHERE reference_kind!='';
CREATE INDEX inventory_movements_item ON inventory_movements(item_id,id);
CREATE TRIGGER inventory_movements_no_update BEFORE UPDATE ON inventory_movements BEGIN SELECT RAISE(ABORT,'Los movimientos de inventario no se modifican'); END;
CREATE TRIGGER inventory_movements_no_delete BEFORE DELETE ON inventory_movements BEGIN SELECT RAISE(ABORT,'Los movimientos de inventario no se eliminan'); END;
CREATE TABLE suppliers (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL CHECK(length(name) BETWEEN 2 AND 300),
 identification TEXT NOT NULL DEFAULT '',
 contact_name TEXT NOT NULL DEFAULT '',
 phone TEXT NOT NULL DEFAULT '',
 email TEXT NOT NULL DEFAULT '',
 address TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id),
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE UNIQUE INDEX suppliers_identification ON suppliers(identification) WHERE identification!='';
CREATE TRIGGER suppliers_no_delete BEFORE DELETE ON suppliers BEGIN SELECT RAISE(ABORT,'Los proveedores no se eliminan: se desactivan'); END;
-- Compras: el borrador no mueve inventario; al RECIBIRLA se registran las entradas (una sola vez).
CREATE TABLE purchases (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
 document_number TEXT NOT NULL CHECK(length(document_number) BETWEEN 1 AND 40),
 issue_date TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'borrador' CHECK(status IN ('borrador','recibida','anulada')),
 subtotal_cents INTEGER NOT NULL DEFAULT 0,
 tax_cents INTEGER NOT NULL DEFAULT 0,
 total_cents INTEGER NOT NULL DEFAULT 0,
 notes TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 received_by INTEGER REFERENCES users(id),
 received_at TEXT NOT NULL DEFAULT '',
 voided_by INTEGER REFERENCES users(id),
 voided_at TEXT NOT NULL DEFAULT '',
 void_reason TEXT NOT NULL DEFAULT ''
);
-- El mismo documento de un proveedor no se registra dos veces.
CREATE UNIQUE INDEX purchases_one_document ON purchases(supplier_id,document_number) WHERE status!='anulada';
CREATE TRIGGER purchases_no_delete BEFORE DELETE ON purchases BEGIN SELECT RAISE(ABORT,'Las compras no se eliminan: se anulan'); END;
CREATE TABLE purchase_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 purchase_id INTEGER NOT NULL REFERENCES purchases(id),
 item_id INTEGER NOT NULL REFERENCES inventory_items(id),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 unit_cost_cents INTEGER NOT NULL CHECK(unit_cost_cents>=0),
 tax_rate_bp INTEGER NOT NULL DEFAULT 0 CHECK(tax_rate_bp>=0)
);
CREATE TRIGGER purchase_items_locked BEFORE UPDATE ON purchase_items WHEN (SELECT status FROM purchases WHERE id=OLD.purchase_id)!='borrador' BEGIN SELECT RAISE(ABORT,'Las partidas de una compra recibida no se modifican'); END;
CREATE TRIGGER purchase_items_no_delete BEFORE DELETE ON purchase_items WHEN (SELECT status FROM purchases WHERE id=OLD.purchase_id)!='borrador' BEGIN SELECT RAISE(ABORT,'Las partidas de una compra recibida no se eliminan'); END;
CREATE TABLE inventory_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 item_id INTEGER REFERENCES inventory_items(id),
 purchase_id INTEGER REFERENCES purchases(id),
 supplier_id INTEGER REFERENCES suppliers(id),
 event TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 actor_id INTEGER REFERENCES users(id),
 actor TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE TRIGGER inventory_events_no_update BEFORE UPDATE ON inventory_events BEGIN SELECT RAISE(ABORT,'El historial de inventario no se modifica'); END;
CREATE TRIGGER inventory_events_no_delete BEFORE DELETE ON inventory_events BEGIN SELECT RAISE(ABORT,'El historial de inventario no se elimina'); END;
