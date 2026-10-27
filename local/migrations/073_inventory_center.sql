-- Centro de Inventario: categorías y subcategorías, marcas, familias de licencias, prefijos de códigos internos, unidades con serie,
-- reservas, traslados y garantías. Solo AÑADE estructuras y configuración administrable: clientes, órdenes, presupuestos, facturas,
-- licencias y movimientos existentes no se modifican. Las existencias siguen saliendo de los movimientos (inventory_movements) y las de
-- licencias, de sus unidades (license_units): no hay un segundo contador.
CREATE TABLE inventory_categories (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 parent_id INTEGER REFERENCES inventory_categories(id),
 kind TEXT NOT NULL CHECK(kind IN ('fisico','licencia')),
 name TEXT NOT NULL CHECK(length(name) BETWEEN 2 AND 80),
 prefix TEXT NOT NULL DEFAULT '',
 catalog_category TEXT NOT NULL DEFAULT 'otro' CHECK(catalog_category IN ('repuesto','otro','licencia','seguridad')),
 item_kind TEXT NOT NULL DEFAULT 'producto' CHECK(item_kind IN ('producto','repuesto','accesorio')),
 tracking TEXT NOT NULL DEFAULT 'serie' CHECK(tracking IN ('serie','granel')),
 position INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE UNIQUE INDEX inventory_categories_name ON inventory_categories(kind,COALESCE(parent_id,0),name COLLATE NOCASE);
CREATE TRIGGER inventory_categories_no_delete BEFORE DELETE ON inventory_categories BEGIN SELECT RAISE(ABORT,'Las categorías no se eliminan: se desactivan'); END;
-- Prefijos de códigos internos: únicos y nunca reutilizables. Un prefijo pertenece para siempre a la categoría que lo creó y conserva su
-- numeración aunque la categoría cambie de prefijo (PCD-SSD-000001, PCD-SSD-000002…).
CREATE TABLE inventory_prefixes (
 prefix TEXT PRIMARY KEY CHECK(length(prefix) BETWEEN 2 AND 6 AND prefix NOT GLOB '*[^A-Z0-9]*'),
 category_id INTEGER NOT NULL REFERENCES inventory_categories(id),
 last_number INTEGER NOT NULL DEFAULT 0 CHECK(last_number>=0),
 created_at TEXT NOT NULL
);
CREATE TRIGGER inventory_prefixes_no_delete BEFORE DELETE ON inventory_prefixes BEGIN SELECT RAISE(ABORT,'Los prefijos no se eliminan ni se reutilizan'); END;
CREATE TRIGGER inventory_prefixes_fixed BEFORE UPDATE ON inventory_prefixes WHEN NEW.prefix!=OLD.prefix OR NEW.category_id!=OLD.category_id OR NEW.last_number<OLD.last_number
 BEGIN SELECT RAISE(ABORT,'Un prefijo no cambia de categoría ni retrocede su numeración'); END;
CREATE TABLE inventory_brands (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(name) BETWEEN 1 AND 60),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE TRIGGER inventory_brands_no_delete BEFORE DELETE ON inventory_brands BEGIN SELECT RAISE(ABORT,'Las marcas no se eliminan: se desactivan'); END;
-- Familias de productos de licencia (Categoría → Marca → Familia → Edición). Las ediciones son una lista configurable (una por línea):
-- describen lo que existe, no lo que está a la venta.
CREATE TABLE inventory_families (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 category_id INTEGER NOT NULL REFERENCES inventory_categories(id),
 brand_id INTEGER NOT NULL REFERENCES inventory_brands(id),
 name TEXT NOT NULL CHECK(length(name) BETWEEN 2 AND 80),
 editions TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE UNIQUE INDEX inventory_families_name ON inventory_families(category_id,brand_id,name COLLATE NOCASE);
CREATE TRIGGER inventory_families_no_delete BEFORE DELETE ON inventory_families BEGIN SELECT RAISE(ABORT,'Las familias no se eliminan: se desactivan'); END;
-- Clasificación de los productos de licencia del catálogo. Las existencias siguen en license_units (no se duplican aquí).
CREATE TABLE license_classification (
 item_id INTEGER PRIMARY KEY REFERENCES catalog_items(id),
 category_id INTEGER NOT NULL REFERENCES inventory_categories(id),
 brand_id INTEGER NOT NULL REFERENCES inventory_brands(id),
 family_id INTEGER REFERENCES inventory_families(id),
 edition TEXT NOT NULL DEFAULT '',
 sku TEXT NOT NULL DEFAULT '',
 region TEXT NOT NULL DEFAULT '',
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE UNIQUE INDEX license_classification_sku ON license_classification(sku) WHERE sku!='';
-- Ficha comercial de los productos físicos (modelo): categoría, marca, modelo, control por serie o a granel y garantías.
ALTER TABLE inventory_items ADD COLUMN category_id INTEGER REFERENCES inventory_categories(id);
ALTER TABLE inventory_items ADD COLUMN brand_id INTEGER REFERENCES inventory_brands(id);
ALTER TABLE inventory_items ADD COLUMN model TEXT NOT NULL DEFAULT '';
ALTER TABLE inventory_items ADD COLUMN tracking TEXT NOT NULL DEFAULT 'granel' CHECK(tracking IN ('serie','granel'));
ALTER TABLE inventory_items ADD COLUMN warranty_store_qty INTEGER NOT NULL DEFAULT 0 CHECK(warranty_store_qty BETWEEN 0 AND 3650);
ALTER TABLE inventory_items ADD COLUMN warranty_store_unit TEXT NOT NULL DEFAULT 'meses' CHECK(warranty_store_unit IN ('dias','meses','anios'));
ALTER TABLE inventory_items ADD COLUMN warranty_store_from TEXT NOT NULL DEFAULT 'venta' CHECK(warranty_store_from IN ('venta','entrega'));
ALTER TABLE inventory_items ADD COLUMN warranty_maker_qty INTEGER NOT NULL DEFAULT 0 CHECK(warranty_maker_qty BETWEEN 0 AND 3650);
ALTER TABLE inventory_items ADD COLUMN warranty_maker_unit TEXT NOT NULL DEFAULT 'meses' CHECK(warranty_maker_unit IN ('dias','meses','anios'));
ALTER TABLE inventory_items ADD COLUMN warranty_maker_from TEXT NOT NULL DEFAULT 'venta' CHECK(warranty_maker_from IN ('venta','entrega'));
CREATE INDEX inventory_items_category ON inventory_items(category_id);
-- Unidades individuales de los productos controlados por serie: cada una con su código interno (único) y, si el fabricante la
-- proporciona, su serie original (única). Las garantías de cada unidad se guardan por separado con sus fechas.
CREATE TABLE inventory_units (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 item_id INTEGER NOT NULL REFERENCES inventory_items(id),
 internal_code TEXT NOT NULL UNIQUE,
 serial TEXT NOT NULL DEFAULT '',
 serial_key TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'disponible' CHECK(status IN ('disponible','reservada','vendida','consumida','devuelta','baja')),
 location TEXT NOT NULL DEFAULT '',
 unit_cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(unit_cost_cents>=0),
 entry_movement_id INTEGER REFERENCES inventory_movements(id),
 exit_movement_id INTEGER REFERENCES inventory_movements(id),
 reservation_id INTEGER,
 client_id INTEGER REFERENCES clients(id),
 order_id INTEGER REFERENCES orders(id),
 invoice_id INTEGER REFERENCES invoices(id),
 document TEXT NOT NULL DEFAULT '',
 sold_at TEXT NOT NULL DEFAULT '',
 delivered_at TEXT NOT NULL DEFAULT '',
 store_warranty_from TEXT NOT NULL DEFAULT '',
 store_warranty_to TEXT NOT NULL DEFAULT '',
 maker_warranty_from TEXT NOT NULL DEFAULT '',
 maker_warranty_to TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id),
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE UNIQUE INDEX inventory_units_serial ON inventory_units(serial_key) WHERE serial_key!='';
CREATE INDEX inventory_units_item ON inventory_units(item_id,status);
CREATE TRIGGER inventory_units_no_delete BEFORE DELETE ON inventory_units BEGIN SELECT RAISE(ABORT,'Las unidades no se eliminan: su historial se conserva'); END;
CREATE TRIGGER inventory_units_code_fixed BEFORE UPDATE ON inventory_units WHEN NEW.internal_code!=OLD.internal_code OR NEW.item_id!=OLD.item_id
 BEGIN SELECT RAISE(ABORT,'El código interno y la ficha de una unidad no cambian'); END;
-- Unidades que intervienen en cada movimiento (el Kardex muestra la serie de cada entrada o salida).
CREATE TABLE inventory_movement_units (
 movement_id INTEGER NOT NULL REFERENCES inventory_movements(id),
 unit_id INTEGER NOT NULL REFERENCES inventory_units(id),
 PRIMARY KEY(movement_id,unit_id)
);
CREATE TRIGGER inventory_movement_units_no_update BEFORE UPDATE ON inventory_movement_units BEGIN SELECT RAISE(ABORT,'El Kardex no se modifica'); END;
CREATE TRIGGER inventory_movement_units_no_delete BEFORE DELETE ON inventory_movement_units BEGIN SELECT RAISE(ABORT,'El Kardex no se elimina'); END;
-- Reservas: apartan existencias para una orden, presupuesto o venta sin descontarlas. Se liberan o se consumen (una sola salida).
CREATE TABLE inventory_reservations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 item_id INTEGER NOT NULL REFERENCES inventory_items(id),
 unit_id INTEGER REFERENCES inventory_units(id),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 reference TEXT NOT NULL CHECK(length(reference) BETWEEN 1 AND 80),
 order_id INTEGER REFERENCES orders(id),
 status TEXT NOT NULL DEFAULT 'activa' CHECK(status IN ('activa','liberada','consumida')),
 note TEXT NOT NULL DEFAULT '',
 movement_id INTEGER REFERENCES inventory_movements(id),
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 closed_by INTEGER REFERENCES users(id),
 closed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX inventory_reservations_item ON inventory_reservations(item_id,status);
CREATE TRIGGER inventory_reservations_no_delete BEFORE DELETE ON inventory_reservations BEGIN SELECT RAISE(ABORT,'Las reservas no se eliminan: se liberan'); END;
-- Traslados entre ubicaciones: no cambian las existencias; quedan en el Kardex.
CREATE TABLE inventory_transfers (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 item_id INTEGER NOT NULL REFERENCES inventory_items(id),
 unit_id INTEGER REFERENCES inventory_units(id),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 from_location TEXT NOT NULL DEFAULT '',
 to_location TEXT NOT NULL CHECK(length(to_location) BETWEEN 1 AND 80),
 note TEXT NOT NULL DEFAULT '',
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE TRIGGER inventory_transfers_no_update BEFORE UPDATE ON inventory_transfers BEGIN SELECT RAISE(ABORT,'Los traslados no se modifican'); END;
CREATE TRIGGER inventory_transfers_no_delete BEFORE DELETE ON inventory_transfers BEGIN SELECT RAISE(ABORT,'Los traslados no se eliminan'); END;
ALTER TABLE inventory_events ADD COLUMN unit_id INTEGER REFERENCES inventory_units(id);
-- Configuración inicial administrable (se puede editar, desactivar o ampliar desde el Centro de Inventario).

INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Computadoras','PC','otro','producto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'PC',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Computadoras' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Computadoras'),'fisico','Portátiles','LAP','otro','producto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'LAP',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Portátiles' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Computadoras');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Computadoras'),'fisico','Computadoras de escritorio','','otro','producto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Computadoras'),'fisico','Computadoras gamer','GAM','otro','producto','serie',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'GAM',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Computadoras gamer' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Computadoras');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Computadoras'),'fisico','All-in-One','AIO','otro','producto','serie',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'AIO',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='All-in-One' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Computadoras');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Computadoras'),'fisico','Mini PC','MPC','otro','producto','serie',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'MPC',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Mini PC' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Computadoras');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Almacenamiento','ALM','repuesto','repuesto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'ALM',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Almacenamiento' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento'),'fisico','SSD SATA 2.5"','SSD','repuesto','repuesto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'SSD',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='SSD SATA 2.5"' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento'),'fisico','SSD M.2 SATA','M2S','repuesto','repuesto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'M2S',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='SSD M.2 SATA' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento'),'fisico','SSD M.2 NVMe','NVME','repuesto','repuesto','serie',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'NVME',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='SSD M.2 NVMe' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento'),'fisico','HDD SATA','HDD','repuesto','repuesto','serie',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'HDD',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='HDD SATA' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento'),'fisico','HDD externos','HDE','repuesto','repuesto','serie',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'HDE',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='HDD externos' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento'),'fisico','Memorias USB','USB','repuesto','repuesto','serie',6,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'USB',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Memorias USB' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento'),'fisico','Tarjetas de memoria','TMEM','repuesto','repuesto','serie',7,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'TMEM',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Tarjetas de memoria' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Almacenamiento');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Memorias RAM','RAM','repuesto','repuesto','serie',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'RAM',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Memorias RAM' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Memorias RAM'),'fisico','DDR3','','repuesto','repuesto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Memorias RAM'),'fisico','DDR4','','repuesto','repuesto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Memorias RAM'),'fisico','DDR5','','repuesto','repuesto','serie',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Memorias RAM'),'fisico','RAM para portátiles','','repuesto','repuesto','serie',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Memorias RAM'),'fisico','RAM para PC de escritorio','','repuesto','repuesto','serie',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Placas madre','PLM','repuesto','repuesto','serie',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'PLM',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Placas madre' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Placas madre'),'fisico','Intel','','repuesto','repuesto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Placas madre'),'fisico','AMD','','repuesto','repuesto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Placas madre'),'fisico','Placas para portátiles','','repuesto','repuesto','serie',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Placas madre'),'fisico','Placas para PC de escritorio','','repuesto','repuesto','serie',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Fuentes de alimentación','FUE','repuesto','repuesto','serie',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'FUE',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Fuentes de alimentación' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Fuentes de alimentación'),'fisico','Fuentes ATX','','repuesto','repuesto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Fuentes de alimentación'),'fisico','Fuentes gamer','','repuesto','repuesto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Fuentes de alimentación'),'fisico','Fuentes modulares','','repuesto','repuesto','serie',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Fuentes de alimentación'),'fisico','Fuentes para servidores','','repuesto','repuesto','serie',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Fuentes de alimentación'),'fisico','Adaptadores de alimentación','ADP','repuesto','repuesto','serie',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'ADP',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Adaptadores de alimentación' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Fuentes de alimentación');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Componentes','COMP','repuesto','repuesto','serie',6,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'COMP',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Componentes' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Componentes'),'fisico','Procesadores','CPU','repuesto','repuesto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'CPU',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Procesadores' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Componentes');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Componentes'),'fisico','Tarjetas gráficas','GPU','repuesto','repuesto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'GPU',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Tarjetas gráficas' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Componentes');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Componentes'),'fisico','Refrigeración','REF','repuesto','repuesto','serie',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'REF',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Refrigeración' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Componentes');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Componentes'),'fisico','Ventiladores','VEN','repuesto','repuesto','serie',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'VEN',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Ventiladores' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Componentes');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Componentes'),'fisico','Otros componentes','','repuesto','repuesto','serie',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Impresoras','IMP','otro','producto','serie',7,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'IMP',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Impresoras' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Impresoras'),'fisico','Epson','','otro','producto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Impresoras'),'fisico','HP','','otro','producto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Impresoras'),'fisico','Canon','','otro','producto','serie',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Impresoras'),'fisico','Brother','','otro','producto','serie',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Impresoras'),'fisico','Otras marcas','','otro','producto','serie',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Suministros de impresión','SUM','repuesto','repuesto','granel',8,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'SUM',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Suministros de impresión' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión'),'fisico','Tintas','TIN','repuesto','repuesto','granel',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'TIN',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Tintas' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión'),'fisico','Cartuchos','CAR','repuesto','repuesto','granel',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'CAR',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Cartuchos' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión'),'fisico','Tóner','TON','repuesto','repuesto','granel',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'TON',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Tóner' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión'),'fisico','Cabezales','CAB','repuesto','repuesto','serie',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'CAB',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Cabezales' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión'),'fisico','Rodillos','ROD','repuesto','repuesto','granel',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'ROD',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Rodillos' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión'),'fisico','Unidades de mantenimiento','UMT','repuesto','repuesto','granel',6,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'UMT',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Unidades de mantenimiento' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Suministros de impresión');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Repuestos','REP','repuesto','repuesto','serie',9,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'REP',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Repuestos' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos'),'fisico','Pantallas','PAN','repuesto','repuesto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'PAN',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Pantallas' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos'),'fisico','Baterías','BAT','repuesto','repuesto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'BAT',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Baterías' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos'),'fisico','Teclados','TCL','repuesto','repuesto','serie',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'TCL',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Teclados' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos'),'fisico','Bisagras','BIS','repuesto','repuesto','granel',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'BIS',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Bisagras' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos'),'fisico','Cargadores','CRG','repuesto','repuesto','serie',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'CRG',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Cargadores' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos'),'fisico','Flex','FLX','repuesto','repuesto','granel',6,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'FLX',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Flex' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos'),'fisico','Conectores','CNX','repuesto','repuesto','granel',7,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'CNX',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Conectores' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos'),'fisico','Chips BIOS','BIOS','repuesto','repuesto','granel',8,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'BIOS',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Chips BIOS' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos'),'fisico','Componentes electrónicos','ELE','repuesto','repuesto','granel',9,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'ELE',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Componentes electrónicos' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Repuestos');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Redes','RED','otro','producto','serie',10,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'RED',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Redes' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Redes'),'fisico','Routers','RTR','otro','producto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'RTR',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Routers' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Redes');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Redes'),'fisico','Switches','SWT','otro','producto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'SWT',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Switches' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Redes');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Redes'),'fisico','Adaptadores','','otro','producto','serie',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Redes'),'fisico','Cables','CBL','otro','producto','granel',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'CBL',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Cables' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Redes');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Redes'),'fisico','Conectores','','otro','producto','granel',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Redes'),'fisico','Puntos de acceso','AP','otro','producto','serie',6,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'AP',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Puntos de acceso' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Redes');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Accesorios','ACC','otro','accesorio','granel',11,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'ACC',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Accesorios' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Accesorios'),'fisico','Mouse','','otro','accesorio','granel',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Accesorios'),'fisico','Teclados','','otro','accesorio','granel',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Accesorios'),'fisico','Audífonos','','otro','accesorio','granel',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Accesorios'),'fisico','Cámaras web','','otro','accesorio','granel',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Accesorios'),'fisico','Parlantes','','otro','accesorio','granel',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Accesorios'),'fisico','Adaptadores','','otro','accesorio','granel',6,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'fisico','Consumibles de servicio técnico','CON','repuesto','repuesto','granel',12,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'CON',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='fisico' AND name='Consumibles de servicio técnico' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Consumibles de servicio técnico'),'fisico','Pasta térmica','','repuesto','repuesto','granel',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Consumibles de servicio técnico'),'fisico','Alcohol isopropílico','','repuesto','repuesto','granel',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Consumibles de servicio técnico'),'fisico','Materiales de limpieza','','repuesto','repuesto','granel',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Consumibles de servicio técnico'),'fisico','Estaño','','repuesto','repuesto','granel',4,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='fisico' AND parent_id IS NULL AND name='Consumibles de servicio técnico'),'fisico','Insumos electrónicos','','repuesto','repuesto','granel',5,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'licencia','Antivirus','AV','seguridad','producto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'AV',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='licencia' AND name='Antivirus' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES (NULL,'licencia','Microsoft','MS','licencia','producto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'MS',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='licencia' AND name='Microsoft' AND parent_id IS NULL;
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Microsoft'),'licencia','Sistemas operativos','WIN','licencia','producto','serie',1,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'WIN',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='licencia' AND name='Sistemas operativos' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Microsoft');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Microsoft'),'licencia','Microsoft Office','OFF','licencia','producto','serie',2,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'OFF',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='licencia' AND name='Microsoft Office' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Microsoft');
INSERT INTO inventory_categories(parent_id,kind,name,prefix,catalog_category,item_kind,tracking,position,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Microsoft'),'licencia','Microsoft 365','M365','licencia','producto','serie',3,'2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_prefixes(prefix,category_id,created_at) SELECT 'M365',id,'2026-10-26T00:00:00' FROM inventory_categories WHERE kind='licencia' AND name='Microsoft 365' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Microsoft');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Kaspersky','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Norton','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('McAfee','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('ESET','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Bitdefender','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Microsoft','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Kingston','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Samsung','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Western Digital','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Seagate','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Crucial','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('ADATA','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('HP','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Dell','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Lenovo','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('ASUS','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Acer','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('MSI','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Gigabyte','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Intel','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('AMD','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Epson','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Canon','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Brother','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('TP-Link','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Logitech','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Genius','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Corsair','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_brands(name,created_at,updated_at) VALUES ('Cooler Master','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_families(category_id,brand_id,name,editions,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Antivirus'),(SELECT id FROM inventory_brands WHERE name='Kaspersky'),'Kaspersky','Standard
Plus
Premium
Otras versiones','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_families(category_id,brand_id,name,editions,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Antivirus'),(SELECT id FROM inventory_brands WHERE name='Norton'),'Norton 360','Standard
Deluxe
Otras versiones','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_families(category_id,brand_id,name,editions,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Antivirus'),(SELECT id FROM inventory_brands WHERE name='McAfee'),'McAfee','Plus
Total Protection
Otras versiones','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_families(category_id,brand_id,name,editions,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Antivirus'),(SELECT id FROM inventory_brands WHERE name='ESET'),'ESET','NOD32 Antivirus
Internet Security
Otras versiones','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_families(category_id,brand_id,name,editions,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Antivirus'),(SELECT id FROM inventory_brands WHERE name='Bitdefender'),'Bitdefender','Antivirus Plus
Internet Security
Total Security','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_families(category_id,brand_id,name,editions,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='licencia' AND name='Sistemas operativos' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Microsoft')),(SELECT id FROM inventory_brands WHERE name='Microsoft'),'Windows 11','Home
Pro
Otras versiones','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_families(category_id,brand_id,name,editions,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='licencia' AND name='Microsoft Office' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Microsoft')),(SELECT id FROM inventory_brands WHERE name='Microsoft'),'Microsoft Office','Office 2021
Office 2024
Office Home & Business
Office Professional Plus','2026-10-26T00:00:00','2026-10-26T00:00:00');
INSERT INTO inventory_families(category_id,brand_id,name,editions,created_at,updated_at) VALUES ((SELECT id FROM inventory_categories WHERE kind='licencia' AND name='Microsoft 365' AND parent_id=(SELECT id FROM inventory_categories WHERE kind='licencia' AND parent_id IS NULL AND name='Microsoft')),(SELECT id FROM inventory_brands WHERE name='Microsoft'),'Microsoft 365','Personal
Family
Business
Apps para empresas
Otras suscripciones','2026-10-26T00:00:00','2026-10-26T00:00:00');
