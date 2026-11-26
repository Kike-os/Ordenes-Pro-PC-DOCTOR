# Smart Catalog & Inventory Pro 3.0

Clasificación profesional de artículos, registro temporal o permanente, fotografías integradas y depuración automática segura de artículos temporales.

- Código del servidor: `local/catalog_smart.py`.
- Migración: `128_smart_catalog.sql` (solo crea tablas nuevas).
- Interfaz: funciones `sc*` en `local/static/app.js`. Estilos `.sc-*` en `local/static/app.css`.

## Clasificación

Hay 8 tipos iniciales, cada uno con icono:
- Servicio técnico;
- Repuesto;
- Producto;
- Consumible;
- Cabezal y repuesto de impresión;
- Accesorio;
- Licencia digital;
- Componente electrónico.

Tienen subcategorías dinámicas (consumibles, impresión, repuestos y componentes electrónicos), según la orden.

- **Administración:** desde **Configuración → Catálogo → Tipos y subcategorías** se pueden agregar, renombrar y desactivar tipos y subcategorías sin tocar el código.
- **Compatibilidad:** cada tipo se apoya en una de las categorías base existentes (`servicio`, `repuesto`, `otro`, `licencia`, `seguridad`), que siguen rigiendo inventario, facturación y licencias. Por ejemplo, Consumible usa `otro` e Impresión usa `repuesto`. Así no cambia ninguna regla fiscal ni de inventario, y los registros anteriores siguen igual.
- **Campos por tipo:** la ventana solo pide lo que corresponde. Un servicio técnico no pide marca, modelo ni fotografía.

## Ventana «Nuevo artículo o servicio»

Se abre desde el presupuesto y pide:
- nombre;
- tipo y subcategoría;
- marca, modelo o referencia;
- precio final con IVA;
- fotografía opcional;
- registro temporal o permanente.

Mientras se escribe el nombre muestra las coincidencias del catálogo; un duplicado exacto se rechaza y se ofrece usar el existente.

El registro por defecto depende del origen:
- desde un presupuesto, **temporal**;
- desde Inventario o el Catálogo, **permanente**.

Cualquier temporal se puede conservar como permanente o proteger.

## Smart Catalog Cleanup

- **Inicio del plazo:** el plazo (30 días por defecto, configurable entre 7 y 365) empieza cuando el artículo ya no tiene presupuestos vigentes ni aprobados. Si vuelve a usarse en un presupuesto vigente, el plazo se suspende y después se recalcula.
- **Qué puede depurarse:** solo un artículo **temporal y sin protección**, cuyas únicas referencias sean presupuestos nunca aprobados y ya terminados (rechazados, cancelados o vencidos).
- **Protección comercial:** lo protegen las referencias a:
  - proformas, ventas o facturas;
  - compras o ficha de inventario (existencias y movimientos);
  - licencias;
  - repuestos de órdenes y coberturas;
  - cualquier tabla desconocida.
- **Depurar es archivar:** el artículo sale del catálogo activo, pero no se borra nada. Los importes y partidas de presupuestos, facturas, ventas y órdenes no cambian, y se puede **restaurar** desde el centro de control. Al restaurarlo queda protegido.
- **Artículos antiguos:** se consideran temporales solo si su origen en un presupuesto se puede verificar, es decir, si se crearon mientras ese presupuesto se preparaba. Los demás se informan como «origen no verificable» y nunca se depuran.
- **Ejecución:** la tarea programada del servidor (`/api/cron/reminders`, diaria) la ejecuta sin depender de ningún equipo de la oficina. También se puede lanzar con «Revisar ahora».
- **Simulación primero:** el modo inicial es **simulación**, que solo registra lo que depuraría. La depuración real exige que administración escriba «ACTIVAR DEPURACION» después de revisar el **reporte de candidatos**, que incluye nombre, tipo, creación, presupuestos, estado, antigüedad, existencias y motivo.

El centro de control está en **Configuración → Catálogo** y tiene:
- indicadores: permanentes, temporales, próximos a vencer, pendientes, depurados, protegidos y recuperables;
- barras regresivas: azul en plazo, ámbar a menos de 7 días, rojo vencido;
- buscador, historial de operaciones, restauración, protección individual y configuración.

## Fotografías

- **Fotografía principal:** en el alta y en el editor del Catálogo. Se aceptan JPG, JPEG, PNG y WEBP de hasta 10 MB; el navegador la optimiza a JPEG de 900 px y como máximo 290 KB. Desde el editor se puede reemplazar o quitar.
- **Galería:** hasta 8 imágenes adicionales por artículo, con selección de archivos, arrastrar y soltar, cámara, vista previa, eliminación y barra de progreso real. Cada imagen se optimiza a 1600 px y como máximo 1,2 MB.
- **Validación:** el servidor comprueba el tipo real del archivo por su firma, el tamaño y los permisos (solo administración).
- **Almacenamiento persistente:** las imágenes se guardan en la base de datos central, así que no se pierden al publicar una versión.
- **Dónde se ven:** en el Catálogo, el selector de presupuestos y la lista del Inventario. Sin fotografía se muestra el icono del tipo.
- **PDF de presupuestos:** opción «Incluir fotografías en los presupuestos impresos y PDF» en la configuración de Smart Catalog. Las fotografías JPEG se incrustan tal cual; las imágenes antiguas en PNG o WEBP muestran el icono.

## Pendiente

- Fotografías en Ventas, Seguimiento de repuestos y Órdenes: se mostrarán donde esos módulos listan artículos del catálogo, en una siguiente entrega.
