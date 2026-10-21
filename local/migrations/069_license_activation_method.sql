-- Método de activación por producto y archivo de licencia del fabricante.
-- activation_method: clave (clave o serial), cuenta (usuario y contraseña), mixta (clave + cuenta) o archivo (archivo de licencia).
-- Vacío = productos registrados antes de esta migración: el método se sigue deduciendo de los datos guardados, sin cambiar nada.
-- license_files: un archivo por licencia, cifrado igual que las credenciales (sealed). Tabla aparte para que los listados del
-- inventario no lean archivos. Solo se añaden estructuras: ninguna licencia, venta, entrega ni historial existente se modifica.
ALTER TABLE license_products ADD COLUMN activation_method TEXT NOT NULL DEFAULT '' CHECK(activation_method IN ('','clave','cuenta','mixta','archivo'));
CREATE TABLE license_files (
 unit_id INTEGER PRIMARY KEY REFERENCES license_units(id),
 name TEXT NOT NULL,
 mime TEXT NOT NULL,
 size INTEGER NOT NULL CHECK(size>0),
 sha256 TEXT NOT NULL,
 sealed TEXT NOT NULL,
 created_at TEXT NOT NULL,
 created_by INTEGER REFERENCES users(id)
);
