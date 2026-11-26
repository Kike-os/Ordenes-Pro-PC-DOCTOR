-- Smart Catalog & Inventory Pro 3.0: tipos y subcategorías administrables, ciclo de vida de los artículos (temporal o permanente),
-- historial de la depuración y galería de fotografías. Solo crea tablas e índices nuevos (aditiva): catalog_items no cambia y la
-- categoría base (servicio, repuesto, otro, licencia, seguridad) sigue rigiendo inventario, facturación y licencias.
CREATE TABLE IF NOT EXISTS catalog_types(
 code TEXT PRIMARY KEY,
 label TEXT NOT NULL,
 base_category TEXT NOT NULL CHECK(base_category IN ('servicio','repuesto','otro','licencia','seguridad')),
 icon TEXT NOT NULL DEFAULT '',
 fields TEXT NOT NULL DEFAULT 'marca,modelo,foto',
 position INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1,
 custom INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS catalog_subcategories(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 type_code TEXT NOT NULL REFERENCES catalog_types(code),
 name TEXT NOT NULL,
 position INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 updated_by INTEGER REFERENCES users(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_subcategories_name ON catalog_subcategories(type_code, name);
CREATE TABLE IF NOT EXISTS catalog_profiles(
 item_id INTEGER PRIMARY KEY REFERENCES catalog_items(id),
 type_code TEXT NOT NULL DEFAULT '',
 subcategory_id INTEGER REFERENCES catalog_subcategories(id),
 model TEXT NOT NULL DEFAULT '',
 mode TEXT NOT NULL DEFAULT 'permanente' CHECK(mode IN ('temporal','permanente')),
 origin TEXT NOT NULL DEFAULT 'desconocido' CHECK(origin IN ('presupuesto','inventario','catalogo','catalogo_base','desconocido')),
 origin_quote_id INTEGER REFERENCES quotes(id),
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 protected INTEGER NOT NULL DEFAULT 0,
 protected_by INTEGER REFERENCES users(id),
 protected_at TEXT NOT NULL DEFAULT '',
 protect_reason TEXT NOT NULL DEFAULT '',
 cleanup_state TEXT NOT NULL DEFAULT '' CHECK(cleanup_state IN ('','depurado','restaurado')),
 cleaned_at TEXT NOT NULL DEFAULT '',
 cleanup_reason TEXT NOT NULL DEFAULT '',
 restored_at TEXT NOT NULL DEFAULT '',
 restored_by INTEGER REFERENCES users(id),
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_catalog_profiles_mode ON catalog_profiles(mode, cleanup_state);
CREATE TABLE IF NOT EXISTS catalog_cleanup_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 item_id INTEGER NOT NULL REFERENCES catalog_items(id),
 event TEXT NOT NULL,
 detail TEXT NOT NULL DEFAULT '',
 simulated INTEGER NOT NULL DEFAULT 0,
 actor_id INTEGER REFERENCES users(id),
 actor TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_catalog_cleanup_events_item ON catalog_cleanup_events(item_id, id);
CREATE TABLE IF NOT EXISTS catalog_gallery(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 item_id INTEGER NOT NULL REFERENCES catalog_items(id),
 position INTEGER NOT NULL DEFAULT 0,
 mime TEXT NOT NULL,
 size INTEGER NOT NULL,
 width INTEGER NOT NULL DEFAULT 0,
 height INTEGER NOT NULL DEFAULT 0,
 data TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL,
 deleted_at TEXT NOT NULL DEFAULT '',
 deleted_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_catalog_gallery_item ON catalog_gallery(item_id, deleted_at, position);
