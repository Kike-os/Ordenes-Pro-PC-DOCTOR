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

El detalle de la orden separa lo cotizado de lo autorizado en dos paneles:

**«Presupuestos pendientes de aprobación»** (acento ámbar; azul si es borrador). Muestra el presupuesto vigente del equipo: código, equipo, estado, total cotizado, partidas pendientes, importe pendiente, emisión, vencimiento, último envío y técnico. Estados:

- *Borrador*: todavía no se envió al cliente (nunca se presenta como enviado).
- *Pendiente de aprobación*: enviado, sin respuesta.
- *En revisión*: solo cuando consta que el cliente abrió y verificó su enlace privado.
- *Vencido*: enviado y con la fecha de validez superada sin decisión.
- *Aprobado parcialmente / Aprobado / Rechazado / Modificación solicitada / Cancelado*.

Acciones: Editar borrador o Abrir presupuesto, Enviar al cliente, Reenviar notificación (administración), Historial y PDF o comprobante.

**«Servicios y productos aprobados»** (acento verde). Solo contiene partidas aprobadas: importes por categoría, total autorizado, listado de partidas (equipo, cantidad, precio final con IVA incluido, fecha de aprobación y estado del equipo como ejecución) y la evidencia: firma del cliente o, si la registró el personal, la indicación de que no consta firma. Debajo, total autorizado, total pagado y saldo pendiente según los pagos reales del equipo. Si no hay nada autorizado se muestra «Todavía no se han autorizado servicios o productos para este equipo» y se explica por qué el total es $0,00 aunque exista un presupuesto cotizado.

Los importes manuales del taller (sin presupuesto aprobado) aparecen aparte como «Importes manuales del taller» y nunca como autorizados.

### Importes fijados por un presupuesto aprobado

Cuando la última versión decidida del presupuesto está aprobada (total o parcialmente), los importes de ese equipo quedan fijados: «Gestión técnica del equipo» los muestra en solo lectura y el servidor rechaza (409) cualquier intento de cambiarlos o borrarlos (`order_workspace.budget_lock`). Para modificarlos se crea una nueva versión del presupuesto; mientras esa versión no se decida, sigue vigente lo que el cliente ya autorizó. El detalle expone `budget_locked` con el código del presupuesto que los fija.

### Equipos de la orden

En «Equipos de esta orden» la información se separa en cuatro niveles: selector de equipos; **Información del equipo** con sus acciones técnicas; **Presupuesto de este equipo** (acento turquesa: estado, total, aprobado, pendiente, pagado y saldo solo de ese equipo; el de otro equipo se gestiona abriendo ese equipo); y **Resumen general de la orden** en tarjetas (presupuesto total, total pagado, saldo pendiente y equipos entregados). El servidor entrega el resumen por equipo en `group.units[].quote` (`quotes.brief`).

### Partidas que el cliente deja por decidir (migración 046)

En su enlace privado el cliente elige, para cada partida, «Apruebo este servicio», «No lo apruebo» o «Lo decidiré después». Debe decidir al menos una. Lo que deja por decidir no se ejecuta, no se cobra y no pasa al panel de aprobados; la página de resultado se lo explica.

Administración lo ve en «Presupuestos pendientes de aprobación» y usa **«Crear versión con las pendientes»**: nace una versión de continuación (`quotes.continues_id`) que contiene solo esas partidas. Al decidirse, lo aprobado se **suma** a lo ya autorizado en la versión anterior; cada partida se cuenta una sola vez (`quotes.approved_lines`). «Nueva versión», en cambio, sigue creando una cotización completa que reemplaza a la anterior cuando el cliente la decide. Cada versión conserva su propia firma y evidencia.

La decisión registrada por el personal (lo que el cliente comunicó por teléfono) se mantiene solo para administración, con nota obligatoria y auditoría, y se muestra siempre como «no consta firma del cliente».

### Estado de ejecución por partida

Cada partida aprobada tiene su avance: Pendiente, En proceso o Realizado (`quote_items.execution`). Lo marca el personal técnico o administración desde «Servicios y productos aprobados»; queda en el historial del presupuesto y en la auditoría. No cambia importes, pagos ni el estado del equipo.

## Clasificación de las partidas (migración 047)

Cada partida de un presupuesto puede llevar una clasificación: **Necesario** (rojo, #DC3545: recomendado para solucionar el problema detectado), **Obligatorio** (ámbar, #F59E0B: indispensable para la intervención) u **Opcional** (azul celeste, #38BDF8: adicional, a elección del cliente). También puede quedar «Sin clasificar», que es como se muestran los presupuestos anteriores.

- Se elige en cada fila del editor, se guarda con la partida (`quote_items.priority`) y se conserva al reabrir y al crear versiones.
- Siempre se muestra con texto y color: en el editor, en la página privada del cliente y en el PDF (con una leyenda).
- Es informativa: no cambia el precio y no autoriza nada. Una partida solo queda aprobada con la decisión del cliente.

## Iconos del catálogo

`local/catalog_icons.py` define 20 iconos propios de trazo simple (pantalla, pantalla gamer, bisagra, PC de escritorio, PC gamer, BIOS, antivirus, sistema operativo, ofimática, licencia, consola, impresora, memoria, almacenamiento, mantenimiento, diagnóstico, repuesto, servicio, producto y genérico). Se definen una sola vez y se usan igual en pantalla y en el PDF.

- El icono se guarda en el elemento (`catalog_items.icon`), ligado a su identificador. Al crear un elemento sin icono se propone uno por categoría y palabras clave; administración puede cambiarlo en el formulario del catálogo.
- Orden de preferencia en pantalla: imagen subida por administración, logotipo de la marca que ya tenga el sistema, icono.
- No son logotipos de marcas. Los logotipos oficiales de Microsoft, Windows, Office, ESET u otros no se dibujan ni se inventan: se muestran cuando administración sube la imagen oficial al elemento.
- Una línea libre del presupuesto recibe el icono propuesto para su categoría y descripción.

## Segunda carga del catálogo e IVA por confirmar

`quotes.ADDITIONS` añade 10 elementos: tres pantallas de portátil en la categoría «Productos» con IVA incluido ($115,00, $150,00 y $280,00) y siete servicios ($32,00, $48,00, $35,00, $48,00, $45,00, $75,00 y $130,00). «Importar catálogo» los registra sin duplicar; el mantenimiento de PC de escritorio actualiza el registro previo equivalente (conserva su identificador y deja el cambio en el historial de precios).

El IVA de los siete servicios está pendiente de confirmación: se guardan con el precio exacto indicado y la marca `tax_pending`. No se les suma ni descuenta impuesto. Mientras la marca siga activa se pueden usar en un borrador (con el aviso «IVA por confirmar»), pero **el presupuesto no se puede enviar**. Administración la quita en el catálogo eligiendo el tratamiento del IVA y marcando la casilla de confirmación.

## Importes en documentos

Los documentos generados (PDF del presupuesto, hoja interna de servicio, página privada y correo del presupuesto) muestran los importes con símbolo de dólar, separador de miles y dos decimales: `$1.250,00` (`quotes.usd`). El formato se aplica al generar el documento; los valores guardados y los cálculos no cambian. Los campos de precio de las ventanas del sistema conservan su formato.

## Cancelar, empezar desde cero y guardar

El editor no tiene autoguardado: solo «Guardar borrador» y «Guardar y enviar al cliente» escriben en el servidor.

- **Presupuesto nuevo.** «Crear presupuesto» abre el editor con una copia en memoria; el presupuesto no existe en el sistema hasta el primer guardado. Antes de crearlo se valida la copia de trabajo.
- **Cancelar.** Cierra sin guardar. Si hay cambios pregunta «¿Descartar los cambios?» (Continuar editando / Descartar cambios); sin cambios cierra directamente. La X, Escape y el cambio de versión usan la misma comprobación.
- **Empezar desde cero.** Tras confirmar, vacía la copia de trabajo: partidas, clasificaciones, descuento, validez, observaciones y la solicitud de documento. No toca el presupuesto guardado, sus versiones ni su historial. Si después se guarda sobre un presupuesto que tenía contenido, se pide confirmar «¿Reemplazar el presupuesto guardado?».
- **Guardar borrador** conserva sin enviar; **Guardar y enviar al cliente** guarda y envía el enlace privado.
- **Cancelar presupuesto** va en una zona aparte y solo aparece en presupuestos ya guardados: cambia su estado a cancelado y queda en el historial. No es salir sin guardar.
