# Gestión de Clientes

Directorio y administración de clientes de PC-DOCTOR S.A. El rediseño de la 1.5.115 **no modifica ningún dato**: no hay migraciones ni escrituras sobre la tabla de clientes.

- **Indicadores** (reales, de toda la base): clientes, fichas completas y por completar. Los dos últimos filtran el listado.
- **Barra de herramientas**: buscador, tipo de cliente, estado de la ficha, orden, Importar y Exportar. En teléfonos, Importar y Exportar pasan al menú «Más».
- **Búsqueda**: por nombre, apellidos, razón social, nombre comercial, cédula o RUC, teléfonos, correo y ciudad o cantón. Ignora tildes y mayúsculas («gomez» encuentra «Gómez», «penafiel» encuentra «Peñafiel»), admite varias palabras en cualquier orden y números con o sin guiones.
- **Tabla**: Cliente (con tipo y nombre comercial), Identificación, Contacto, Ciudad / Cantón, Órdenes y Acciones. Se ordena por nombre, identificación, ciudad u órdenes pulsando el encabezado. En teléfonos cada cliente se muestra como ficha.
- **«Por completar»**: al pulsarlo indica exactamente qué datos obligatorios faltan para registrar órdenes (los opcionales no cuentan) y ofrece completar la ficha.
- **Acciones**: Ver ficha, Editar o Completar (según permisos), Ver sus órdenes (si tiene), WhatsApp o llamada (si hay teléfono) y Correo (si hay dirección).
- **Ficha**: añade las citas técnicas del cliente y la fecha de la última atención, además de órdenes y equipos.
- **Duplicados**: una identificación repetida se rechaza indicando la ficha existente. Un teléfono o correo que ya usa otra ficha no bloquea el guardado (los contactos compartidos son válidos): se avisa para que se revise. Nunca se fusiona ni se elimina nada automáticamente.
- **Importación y exportación** (sin cambios): la importación analiza el archivo, muestra una vista previa con errores y duplicados y solo escribe al confirmar; la exportación es solo para administración y queda auditada.

## Listado compacto, filtros y ficha rápida (1.5.118)

- **Densidad**: vista compacta (filas de unos 56 px) o cómoda; la elección se recuerda en el navegador. En teléfonos, fichas adaptativas sin desplazamiento horizontal.
- **Tamaño de página**: 10, 25 o 50 clientes. El pie indica el rango mostrado, el total y la página; los filtros se conservan al cambiar de página.
- **Filtros**: persona o empresa, estado de la ficha (por completar, completas, con órdenes, sin órdenes, importadas, sin identificación) y ciudad o cantón (lista de las que existen en la base).
- **Orden**: registro más reciente o más antiguo, nombre, ciudad, número de órdenes y última atención.
- **Acciones**: Ver ficha, Editar, Órdenes, Llamar (WhatsApp si es móvil) y Correo. Llamar y Correo aparecen desactivados, con su motivo, cuando no hay un dato válido.
- **Ficha rápida**: al pulsar el nombre se abre un panel lateral con identificación, contactos, dirección, ciudad y cantón, última atención, equipos, órdenes y citas (datos reales de `GET /api/clients/<id>`), con acceso a la ficha completa y a la edición según permisos.
- La búsqueda y los filtros se aplican en el servidor sobre todos los registros, no solo sobre la página visible.

## Tabla con columnas independientes (1.5.125)

- Columnas: Cliente, Identificación, Teléfono, Correo electrónico, Ciudad / Cantón, Órdenes y Acciones. Teléfono y correo ya no comparten celda; el teléfono secundario aparece bajo el principal y los correos largos se recortan con puntos suspensivos (el completo queda en la descripción emergente).
- Acciones en una sola línea, todas de 34 × 34 px: ver ficha, editar (o completar), **crear orden**, llamar o escribir por WhatsApp y enviar correo. Las no disponibles se muestran atenuadas y explican el motivo (ficha por completar, sin teléfono válido, sin correo válido). «Ver sus órdenes» sigue en el contador de la columna Órdenes.
- Cabecera con el total de clientes registrados (o los resultados del filtro sobre el total), vista compacta o cómoda y tamaño de página.
- Entre 761 y 1240 px la tabla se desplaza horizontalmente dentro de su panel; hasta 760 px cada cliente es una tarjeta con sus datos etiquetados y botones de 42 px.
