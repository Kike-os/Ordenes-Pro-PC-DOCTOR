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
