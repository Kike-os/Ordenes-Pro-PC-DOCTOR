# Limpieza segura del catálogo (1.5.268)

Configuración → **Catálogo de productos y servicios** permite eliminar productos inactivos que ya no se necesitan, uno a uno o en grupo, **sin perder historial**.

## Regla

Un producto se **elimina definitivamente** solo si:
1. está **inactivo** (los activos nunca se eliminan ni se archivan desde aquí), y
2. no tiene **ninguna referencia que deba conservarse**.

Esas referencias son:
- presupuestos de órdenes técnicas;
- proformas y ventas;
- facturas electrónicas;
- ventas, unidades, compras o historial de licencias;
- ficha de inventario, con sus movimientos, compras a proveedores, unidades y garantías, reservas y repuestos de órdenes;
- historial de precios, que el sistema declara inmutable.

Como red de seguridad, cualquier otra tabla que apunte al catálogo con una clave foránea también protege el producto.

Con referencias, el producto se puede **conservar archivado**: sale del catálogo operativo (presupuestos, ADI, listas) y su historial no cambia. Nunca se modifican facturas, ventas, presupuestos ni movimientos de inventario.

Al eliminar se borran solo los datos propios del producto (su imagen y su ficha o clasificación de licencia sin uso).

## Interfaz

- **Filtros combinables con la búsqueda:**
  - **Estado:** Todos (el catálogo operativo, sin archivados, es la vista predeterminada), Activos, Inactivos y **Archivados**.
  - **Tipo:** Productos, Repuestos y componentes, Servicios, Licencias y Seguridad.
  - Cada filtro muestra cuántos elementos hay, y el resumen indica cuántos archivados están ocultos.
- **Eliminar** (icono Trash2) en cada producto inactivo o archivado. Antes de ejecutar nada, el servidor revisa el producto y la ventana muestra:
  - su nombre y código;
  - si se puede eliminar o qué registros lo protegen, con cantidades;
  - la opción «Conservar archivados los que tienen historial».
- **Selección múltiple:**
  - Hay una casilla en cada producto inactivo y otra en el encabezado para seleccionar todos los visibles (solo inactivos).
  - La barra «N productos seleccionados» lleva a **Eliminar seleccionados**.
  - El resumen previo indica cuántos se eliminan, cuántos se conservan archivados y cuántos activos no se tocan; cada producto se revisa por separado.
- **Restaurar:** devuelve al catálogo operativo (inactivo) un producto archivado desde el catálogo. Activarlo también lo desarchiva.
- **Registro de limpieza:** cada eliminación o archivo, con producto, código, operación, fecha y usuario.
- **Diseño:**
  - En escritorio, filas compactas con las acciones en línea.
  - Bajo 1100 px, tarjetas compactas.
  - En el celular, botones táctiles y sin desplazamiento horizontal.

Los productos archivados por un lote **AR-** de Inventario también cuentan como archivados.

## Servidor y datos

- **Permisos:** solo administración, comprobado en el servidor (403 para técnicos). La operación exige `confirm: true` y tiene un límite de uso.
- **Rutas:**
  - `POST /api/catalog/cleanup` con `action`:
    - `review`: solo lectura;
    - `delete`: con `archive_protected` opcional;
    - `archive`;
    - `restore`.
  - `GET /api/catalog/removals`: el registro de limpieza.
- **Migración 100** (`100_catalog_cleanup.sql`):
  - añade `catalog_items.archived_at` y `archived_by`, vacíos;
  - crea la tabla `catalog_removals`, con código, nombre, categoría, precio, resultado, detalle, lote, usuario y fecha, protegida por disparadores para que no se modifique ni se borre;
  - la auditoría registra `catalog_item_deleted`, `catalog_item_archived` y `catalog_item_restored`;
  - reversión antes de usarla: `DROP TABLE catalog_removals`.
- **Pruebas:** `local/tests/test_catalog_cleanup.py`.
  - Eliminar un producto sin dependencias.
  - Proteger ventas, facturas, licencias e inventario.
  - Proteger productos usados en órdenes técnicas.
  - Proteger el historial de precios.
  - Eliminación masiva parcial con archivo.
  - Activos intocables.
  - Archivados por lote AR-.
  - Permisos y validación.
  - Red de seguridad ante claves foráneas desconocidas.
