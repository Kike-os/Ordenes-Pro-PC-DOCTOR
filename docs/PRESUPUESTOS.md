# Presupuestos profesionales (rama `presupuestos`, pendiente de aprobación)

Requiere la migración 042 (solo crea tablas nuevas). El presupuesto anterior de cada orden (`order_budget`, `order_budget_lines`) no se modifica al migrar.

## Decisiones tomadas con el administrador (13/10/2026)

- IVA 15 %, configurable; cada ítem indica si lleva IVA o tarifa 0 %.
- Los precios del catálogo y de los ítems **incluyen IVA**; el sistema calcula hacia atrás la base y el impuesto.
- Numeración ligada a la orden: `PCD-20261013-0002-P1`, `-P2`…
- El texto de condiciones enviado por el administrador se usa tal cual. **No ha pasado revisión jurídica conocida.**

## Catálogo

Configuración → Catálogo y presupuestos (solo administración): nombre, descripción, categoría (servicios, licencias, seguridad, repuestos, otros), precio final, si lleva IVA y disponibilidad. No se cargó ningún precio: el catálogo empieza vacío. Cada presupuesto copia descripción y precio de sus ítems, así que cambiar el catálogo no altera los ya emitidos. La tarifa de IVA queda fijada en cada presupuesto al crearlo.

## Presupuesto

- Se crea desde la sección «Presupuesto» del detalle de la orden. Ítems desde el catálogo o como línea libre, con cantidad, precio e IVA; vigencia y observaciones. ADI está disponible en las descripciones y observaciones (no interviene en precios).
- **Estados del presupuesto:** borrador, enviado al cliente, aprobado, parcialmente aprobado, rechazado, modificación solicitada, cancelado. **Estado por ítem:** pendiente, aprobado, rechazado, cancelado.
- Muestra total cotizado, total aprobado e importe rechazado, con el desglose de base e IVA.
- Enviado o decidido ya no se edita: «Nueva versión» crea P2 copiando los ítems, cancela la anterior si seguía abierta y revoca su enlace.
- El técnico prepara borradores; enviar, decidir en nombre del cliente, versionar y cancelar son de administración. Todo queda en el historial del presupuesto (no se puede modificar ni borrar) y en la auditoría.

## Aprobación del cliente

1. «Guardar y enviar al cliente» crea un enlace privado (`/presupuesto/<token>`, 15 días) y lo envía al correo registrado con la firma institucional. Si el correo falla, el enlace se muestra una vez a administración para compartirlo por otro medio.
2. El cliente comprueba su identidad con los últimos cuatro dígitos de su cédula o RUC (seis intentos). Antes de eso no ve importes.
3. Decide **cada servicio** (o «Aprobar todo» / «Rechazar todo»), ve los importes definitivos y las condiciones, escribe su nombre, acepta expresamente y firma en el recuadro. También puede pedir una modificación.
4. Se guarda la evidencia: decisiones, importes, condiciones aceptadas, nombre, fecha, método de verificación, origen y la firma como trazos. Lleva una huella SHA-256 y no se puede modificar ni borrar.

La firma es un trazo manuscrito digitalizado; la página y el PDF dicen expresamente que **no es una firma electrónica certificada**.

Administración puede registrar la decisión cuando el cliente la comunicó por otro medio: exige una nota y queda sin firma del cliente.

## Efecto en la orden

- Lo aprobado pasa al total a cobrar de la orden (de ahí salen el saldo y el bloqueo de entrega con saldo pendiente).
- Si la orden ya tiene pagos por más de lo que se aprobaría, la decisión se rechaza con un aviso.
- **La aprobación no cambia el estado de la orden ni inicia trabajos.** Genera un aviso interno y una entrada en el historial de la orden.

## PDF

`/api/quotes/<id>/pdf` (personal) y enlace del cliente (con la identificación parcialmente oculta): logotipo original, datos del cliente y de la orden, ítems con su decisión, desglose de IVA, condiciones y evidencia con la firma.

## No incluido

- Adjuntar documentos de identidad del cliente.
- Imágenes de los productos y precios reales (los proporcionará el administrador).
- El correo del presupuesto todavía no usa la plantilla institucional común (pendiente junto con el resto de correos).

Pruebas: `local/tests/test_quotes.py` y recorrido completo en navegador (catálogo, borrador, envío, aprobación parcial con firma a 390 px, resumen en la orden, 320 px).

## Catálogo profesional, descuentos e historial de precios (rama `presupuestos-catalogo`, pendiente de aprobación)

Requiere la migración 044 (añade columnas a `catalog_items` y `quotes` y crea `catalog_images` y `catalog_price_history`). No hay otro módulo de presupuestos: es el mismo, ampliado.

**Catálogo de productos y servicios** (Configuración). Cada elemento tiene código automático (`PS-0001`), nombre, descripción comercial, categoría, marca, logotipo o imagen, precio, tratamiento del IVA, precio final, duración de la licencia y número de dispositivos (si corresponden) y estado activo o inactivo. Se puede registrar, editar, buscar, filtrar por categoría y estado, y desactivar. No se admiten dos elementos con el mismo nombre.

**Precio e IVA**, con el desglose calculado al escribir:
- *IVA incluido:* $30,00 → base $26,09 · IVA $3,91 · final $30,00.
- *Agregar IVA:* $30,00 → base $30,00 · IVA $4,50 · final $34,50.
- *Sin IVA:* tarifa 0 %, cuando legalmente proceda.

La tarifa (15 % por defecto) se cambia en el mismo panel.

**Imágenes y logotipos.** Se muestra, por este orden: la imagen cargada por administración (PNG, JPG o WebP de hasta 300 KB), el logotipo de la marca del catálogo central o un icono de la categoría. Están disponibles Kaspersky, McAfee, Norton, PlayStation y Epson (Simple Icons 13.21.0, CC0, en el color de cada marca). **No hay logotipo libre de Microsoft, Windows, Office ni ESET, y «Defender Plus» no tiene fabricante identificado**: esos elementos muestran el icono de su categoría hasta que se cargue su imagen oficial desde el catálogo.

**Historial de precios.** Cada cambio del precio final guarda precio anterior, precio nuevo, usuario y fecha; no se puede modificar ni borrar. Los presupuestos ya emitidos conservan el precio con el que se crearon.

**Catálogo inicial.** Botón «Importar catálogo inicial»: registra los 19 productos y servicios entregados por la administración el 13/10/2026, con sus precios finales tal cual (IVA incluido). Es repetible sin duplicar: lo que ya existe por nombre no se crea ni se modifica. Las descripciones no añaden características, compatibilidades, duraciones ni dispositivos que no consten en el nombre.

**Ventana «Seleccionar productos y servicios»** (desde el presupuesto): buscador instantáneo sin distinguir tildes, filtros por categoría y tarjetas con logotipo, nombre, código, descripción, precio final y «Agregar».

**Descuento autorizado.** Tres opciones fijas: sin descuento (0 %), especial (3 %) y máximo (5 %). El sistema solo tiene dos roles, `administrador` y `tecnico`; **no existe otro nivel administrativo**, así que solo `administrador` puede aplicarlo o cambiarlo (lo comprueban el servidor y la interfaz). Queda registrado quién y cuándo, y aparece en el historial del presupuesto. El descuento se aplica por línea con redondeo al centavo, de modo que una aprobación parcial suma exacto; el PDF y la página del cliente muestran el importe antes del descuento y lo descontado. Una versión nueva hereda el descuento.

Pruebas: `local/tests/test_quotes.py` (modos de precio, códigos, duplicados, historial, imágenes, los 19 precios, permisos y límites del descuento) y recorrido en navegador a 1440, 390 y 320 px.

## Documento de identidad al aprobar (opcional)

El documento de identidad **no se pide por defecto**. Administración decide, presupuesto por presupuesto, marcar «Solicitar documento de identidad al aprobar» en el editor. Un técnico puede guardar el borrador, pero no activar ni desactivar esa solicitud.

Cuando se solicita:

- La página privada del cliente muestra el bloque «Documento de identidad» con un aviso que explica para qué se pide, quién lo consulta y que puede pedir su eliminación.
- Se exige únicamente si el cliente aprueba al menos un servicio. Si rechaza todo o pide una modificación, no se le pide nada.
- Se acepta una foto (JPG, PNG, WebP) o un PDF de hasta 700 KB. El servidor comprueba el contenido real del archivo, no su nombre.
- Sin un documento válido la aprobación no se registra.

Custodia:

- El archivo se guarda en la base de datos (tabla `quote_documents`, migración 045), no en disco ni en enlaces públicos. No aparece en la página del cliente, en el PDF ni en los correos.
- La evidencia de aceptación incluye la huella SHA-256 del archivo, de modo que se puede comprobar qué documento acompañó la firma aunque después se elimine.
- Solo administración lo descarga (`/api/quotes/<id>/identity`) y cada consulta queda en la auditoría (`quote_identity_viewed`).
- Administración puede eliminarlo («Eliminar documento») cuando el cliente lo pida o ya no haga falta; se registra en el historial del presupuesto y en la auditoría. El presupuesto, la firma y la evidencia se conservan.
- Una nueva versión del presupuesto no hereda la solicitud: hay que volver a marcarla.

Límites: el sistema no verifica la autenticidad del documento ni lo compara con la identificación registrada; es una copia aportada por el cliente para que administración la revise.

## Presupuesto en la vista de la orden

La orden muestra un único módulo «Presupuesto» (antes eran dos bloques con el mismo título):

- **Encabezado** con subtítulo y una insignia de estado: Sin presupuesto, Borrador, Pendiente de aprobación, Aprobado parcialmente, Aprobado, Rechazado, Modificación solicitada o Cancelado.
- **Presupuesto detallado**: si no existe, un estado vacío con el botón «Crear presupuesto»; si existe, su código, el total cotizado o autorizado, los datos de la decisión y las acciones «Editar/Abrir presupuesto» y «PDF».
- **Resumen financiero**: mano de obra, repuestos, servicios, productos digitales y el Total USD destacado, las líneas registradas y «Agregar línea» (solo administración). Los valores son referenciales y no constituyen una factura.

En «Equipos de esta orden» la información se separa en cuatro niveles:

1. Selector de equipos.
2. **Información del equipo**: código, tipo, marca, modelo, serie, color, técnico, ingreso, entrega y falla, con sus acciones técnicas (Etiqueta QR, Tarjeta de seguimiento, Editar este equipo).
3. **Presupuesto de este equipo** (acento turquesa): estado, total, aprobado, pendiente, pagado y saldo de ese equipo únicamente, con sus propias acciones. El presupuesto de otro equipo se gestiona abriendo ese equipo, para no mezclar importes.
4. **Resumen general de la orden** (tarjetas): presupuesto total, total pagado, saldo pendiente y equipos entregados de toda la orden.

El servidor entrega el resumen por equipo en `group.units[].quote` (`quotes.brief`).
