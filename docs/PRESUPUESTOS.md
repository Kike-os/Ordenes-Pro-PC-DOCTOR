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

La administración confirmó el 13 de octubre de 2026 que los siete servicios tienen el IVA incluido, igual que el resto del catálogo, y así quedaron en producción.

La marca «IVA por confirmar» (`tax_pending`) sigue disponible para elementos cuyo tratamiento tributario esté pendiente: se pueden usar en un borrador (con el aviso «IVA por confirmar»), pero **el presupuesto no se puede enviar** hasta que administración elija el tratamiento del IVA en el catálogo y marque la casilla de confirmación.

## Importes en documentos

Los documentos generados (PDF del presupuesto, hoja interna de servicio, página privada y correo del presupuesto) muestran los importes con símbolo de dólar, separador de miles y dos decimales: `$1.250,00` (`quotes.usd`). El formato se aplica al generar el documento; los valores guardados y los cálculos no cambian. Los campos de precio de las ventanas del sistema conservan su formato.

## Cancelar, empezar desde cero y guardar

El editor no tiene autoguardado: solo «Guardar borrador» y «Guardar y enviar al cliente» escriben en el servidor.

- **Presupuesto nuevo.** «Crear presupuesto» abre el editor con una copia en memoria; el presupuesto no existe en el sistema hasta el primer guardado. Antes de crearlo se valida la copia de trabajo.
- **Cancelar.** Cierra sin guardar. Si hay cambios pregunta «¿Descartar los cambios?» (Continuar editando / Descartar cambios); sin cambios cierra directamente. La X, Escape y el cambio de versión usan la misma comprobación.
- **Empezar desde cero.** Tras confirmar, vacía la copia de trabajo: partidas, clasificaciones, descuento, validez, observaciones y la solicitud de documento. No toca el presupuesto guardado, sus versiones ni su historial. Si después se guarda sobre un presupuesto que tenía contenido, se pide confirmar «¿Reemplazar el presupuesto guardado?».
- **Guardar borrador** conserva sin enviar; **Guardar y enviar al cliente** guarda y envía el enlace privado.
- **Cancelar presupuesto** va en una zona aparte y solo aparece en presupuestos ya guardados: cambia su estado a cancelado y queda en el historial. No es salir sin guardar.

## Presupuestos por estado y eliminación de borradores (migración 049)

En el detalle de la orden, el panel **«Presupuestos del equipo»** agrupa todas las versiones según su estado real: Borradores, Pendientes de aprobación, Aprobados, Rechazados y Cancelados (este último plegado). Un borrador nunca aparece como si esperara la respuesta del cliente. Cada tarjeta muestra número, estado, total cotizado, partidas, creación, vencimiento, último envío y técnico, y solo las acciones de su estado.

**Eliminar borrador.** Disponible solo en borradores que nunca salieron del taller (sin envío, sin enlace, sin autorización y sin versiones que los continúen). El servidor comprueba el estado real antes de eliminar; la puede ejecutar administración o quien creó el borrador. Es una eliminación lógica (`quotes.deleted_at`): el borrador sale de las listas y ya no se puede abrir, pero su registro y su historial se conservan para auditoría. No afecta a otras versiones ni a otros equipos, y el siguiente presupuesto no reutiliza su número. Un presupuesto enviado o decidido se anula, no se elimina.

**«Autorizaciones del cliente».** Estado calculado con las partidas reales: Sin autorizaciones, Aprobación parcial o Totalmente aprobado. Cada partida aprobada muestra icono, cantidad, precio, fecha, presupuesto de origen y su ejecución; con cuatro o más se separan servicios y productos. Tres tarjetas: Total autorizado (solo partidas aprobadas), Total pagado y Saldo pendiente, o «Saldo a favor» si se pagó más de lo que hay que cobrar. Los cargos manuales del taller van aparte («Agregar cargo manual»); los pagos se registran en «Pagos y saldo».

**«Resumen del presupuesto»** (tarjeta del equipo): número completo, cantidad de productos y servicios, estado, total cotizado destacado con un texto según el estado, avance de autorizaciones (aprobadas, rechazadas y pendientes por separado) y cuatro tarjetas: Autorizado, Pendiente de aprobación, Pagado y Saldo por cobrar. Lo pendiente o rechazado nunca se suma como deuda.

## Ventana Presupuesto: acciones e historial de actividad

- **Acciones del presupuesto**: Salir sin guardar, Empezar de cero, Guardar borrador y Guardar y enviar al cliente, del mismo tamaño y con indicador de carga al guardar o enviar.
- **Anular presupuesto** va aparte, con el aviso «La anulación conservará el registro del presupuesto en el historial» y una confirmación que nombra el presupuesto. Un presupuesto con servicios aprobados no se anula: se crea una nueva versión.
- **Historial de actividad**: plegado al abrir, con contador y línea de tiempo (icono y color por tipo de movimiento, fecha y hora, responsable, número de presupuesto y descripción). Es de solo lectura; el detalle largo se despliega bajo demanda y un movimiento recién registrado se destaca una vez.

En «Gestión técnica del equipo», «Últimas modificaciones» pasó a ser **«Actividad reciente»** con la misma línea de tiempo: tres movimientos a la vista y «Ver historial completo».

## Estructura de la ventana Presupuesto

**Causa de los desbordamientos.** El modal completo era el contenedor con desplazamiento (`.maintenance-dialog{overflow:auto}`): el título no tenía zona propia, las partidas pasaban por debajo de él al desplazar y los botones de guardado quedaban al final del contenido, fuera de la vista.

**Corrección.** El modal es ahora una columna de tres zonas: encabezado fijo con fondo opaco (título, número, estado y selector de versión), cuerpo con desplazamiento propio (`flex:1; min-height:0; overflow-y:auto`) y pie fijo con las acciones, que respeta el área segura inferior del dispositivo. La altura se limita a la pantalla disponible.

- Cada partida muestra sus campos con etiqueta visible: clasificación, descripción, categoría, cantidad, precio unitario, IVA y total.
- Los errores aparecen junto al campo: se marca el control, se explica debajo («Ingresa una descripción para la partida 2 antes de guardar el presupuesto») y el cuerpo se desplaza hasta él. No se borra nada y no se crea el presupuesto.
- El resumen usa «Subtotal gravado», «Subtotal tarifa 0 %», «IVA» y «Total cotizado»; los cálculos no cambiaron.

Comprobado con 0, 1, 5 y 12 partidas, descripciones largas y errores, en 1920×1080, 1440×900, 1366×768, 1366×560, 1024×768, 768×1024, 390×844, 390×560 y 320×640.

## PDF del presupuesto y aprobación con código QR

**Diseño.** Documento A4 sobre fondo blanco con acentos discretos (se imprime sin gastar tinta): encabezado con el logotipo, datos de la empresa, «PRESUPUESTO TÉCNICO», número, estado, emisión y vencimiento; datos del cliente y del equipo; partidas con icono, descripción, clasificación, cantidad, precio unitario, descuento, importe y estado real de autorización; resumen con importe original, descuento, subtotal gravado, subtotal tarifa 0 %, IVA, total cotizado y, si hay decisión, total autorizado, rechazado y por decidir; condiciones; bloque de aprobación en línea; y la evidencia de la decisión. Los saltos de página repiten el encabezado de la tabla.

**Correcciones.** El «?» del descuento era el signo menos tipográfico (U+2212), que la fuente del PDF no tiene: ahora se escribe con guion y cualquier carácter ajeno a la fuente se sustituye antes de dibujarlo. Los importes se alinean a la derecha. El descuento se aplica y se redondea por partida, y el total es la suma de las partidas: para $240,99 con 3 % resultan $96,99 + $136,77 = $233,76 y un descuento de $7,23; base e IVA suman siempre el total. No se recalcula ningún presupuesto guardado.

**Condiciones.** `quotes.CONDITIONS` contiene las siete cláusulas de «Condiciones de aprobación y ejecución» entregadas por la administración el 13 de octubre de 2026, **sujetas a revisión legal**. Cada presupuesto conserva las condiciones con las que se envió; los anteriores no cambian.

**Código QR.** El sistema guarda solo la huella del enlace privado, no el enlace. Por eso el QR se dibuja únicamente cuando quien pide el documento ya tiene el enlace vigente:

- el PDF adjunto al correo del presupuesto;
- el PDF que el cliente descarga desde su enlace;
- «Descargar PDF con código QR» en la ventana «Presupuesto enviado», justo después de enviarlo.

El QR contiene la dirección real de autorización de ese presupuesto y versión; junto a él hay un botón clicable, la vigencia del enlace y una nota de seguridad. Un borrador, un presupuesto decidido o anulado, un enlace vencido, revocado o inventado no producen ningún QR. Escanearlo no aprueba nada: el cliente verifica su identidad y decide cada partida. Una versión nueva revoca el enlace anterior.

**Vigencia del enlace.** Configurable entre 1 y 60 días (por omisión 15) en Configuración → Catálogo, junto a la tarifa de IVA. Aplica a los enlaces que se emitan desde entonces.

## Equipo sin presupuestos

Cuando un equipo no tiene ningún presupuesto, el panel «Presupuestos del equipo» muestra el contador «0 presupuestos» y el mensaje «Sin presupuestos registrados. Este equipo está listo para generar su primer presupuesto», con el botón «Crear presupuesto». El contador sale de las versiones reales que devuelve el servidor (no hay caché en el navegador).

El 13/10/2026, con autorización expresa de administración y respaldo previo, se eliminaron de producción los cinco presupuestos de prueba de `PCD-20261012-0001` (E01 y E02) con sus partidas, eventos, enlace y firma de prueba. No se tocaron órdenes, clientes, historial técnico, pagos ni el correo archivado. Las numeraciones internas no se reiniciaron.

## Catálogo «Premium Técnico» en la ventana de selección (13/10/2026)

**Auditoría del catálogo de producción (29 elementos, solo lectura).** Con logotipo de marca: Kaspersky (2), McAfee, Norton, PlayStation (3) y Epson. Sin logotipo: Microsoft (5 de Office y 3 de Windows), ESET NOD32 y «Defender Plus» (marca no identificada con certeza: no se le asigna logotipo). Ninguna ruta de imagen estaba rota; ningún elemento tiene imagen propia cargada. La correspondencia es por la **marca registrada en el elemento**, no por parecido del nombre.

**Logotipos.** Los de marca salen de `local/static/brands/` (Simple Icons 13.21.0, licencia CC0, sin modificar). Se añadió Bitdefender de esa misma fuente. **Microsoft y ESET no están en ella**, y no se dibujan ni se descargan de otros sitios: esos productos muestran un icono técnico (sistema operativo, ofimática, antivirus) hasta que administración suba el logotipo oficial en Configuración → Catálogo → imagen del elemento.

**Iconos técnicos nuevos** (`local/catalog_icons.py`, mismo dibujo en pantalla y en el PDF): portátil, placa electrónica, limpieza técnica, procesador y refrigeración, y red informática; más reglas para monitor, recuperación de datos, sistema operativo y reparación de portátiles o computadoras.

**Ventana.** Encabezado y pie fijos; solo se desplaza la rejilla (dos columnas en escritorio, una en móvil). Tarjeta: logotipo o icono, nombre y marca · categoría; descripción (tres líneas con «Ver más»), vigencia, dispositivos y código; precio, tratamiento de IVA real del elemento («IVA incluido», «Tarifa 0 %» o «IVA por confirmar») y «Agregar» siempre abajo. Búsqueda sin tildes ni mayúsculas, con varias palabras, sinónimos habituales y combinada con el filtro; el catálogo se carga una sola vez. «Agregar» ignora el doble clic, indica cuántas unidades hay ya en el presupuesto y permite añadir más. Precios, códigos y cálculo de importes no cambian.

## Estados automáticos y sincronización con la orden (1.5.163)

| Estado del presupuesto | Cuándo | Aspecto |
| --- | --- | --- |
| Esperando respuesta | Enviado y el servidor de correo aceptó el mensaje con el enlace privado | Ámbar, reloj |
| Enlace creado · correo no enviado | El enlace existe pero el correo falló o el sistema no tiene correo configurado: **no consta como enviado** | Rojo |
| Aprobado | El cliente aprobó todas las partidas | Verde, verificación |
| Aprobado parcialmente | Aprobó unas y rechazó otras; las que dejó «para después» se ofrecen en una nueva versión, que vuelve a estar «Esperando respuesta» | Azul |
| Rechazado | No aprobó ninguna partida; se conserva el presupuesto y su historial y nada queda autorizado | Rojo |

- Se registran fecha, hora, destinatario y número (historial del presupuesto y Centro de Entrega), la firma y la evidencia de aceptación (procedimiento existente) y el motivo u observación que escriba el cliente.
- Sincronización: el estado técnico de la orden y el comercial del presupuesto son independientes. Única regla automática: si la orden estaba en «Aprobación de presupuesto» y el cliente aprueba (total o parcialmente), pasa a «Procesando» y lo deja escrito en el historial. Nunca se cambian «Listo para entregar», «En espera de entrega» ni «Entregado». Un rechazo deja la orden donde está, con una nota para coordinar la devolución.
- Avisos en el centro de notificaciones: «Presupuesto enviado · Esperando respuesta del cliente» (solo si el correo salió), «Presupuesto aprobado por el cliente», «Presupuesto aprobado parcialmente» y «Presupuesto rechazado por el cliente» (con el motivo, si lo dio). El panel del presupuesto se actualiza solo cada minuto mientras espera respuesta.
- Seguridad (sin cambios): enlace privado con huella y caducidad, verificación con los últimos dígitos de la identificación, decisión procesada en el servidor, enlace revocado tras decidir (no hay respuestas duplicadas) y presupuesto bloqueado para edición después de la decisión.

## Renovación de pasta térmica en portátiles (1.5.179)

Dos servicios en «Servicios técnicos y reparaciones», con precio final con IVA incluido (no se suma de nuevo) e iconos propios (trazo vectorial, iguales en pantalla y PDF):

| Servicio | Precio | Icono |
| --- | --- | --- |
| Renovación de pasta térmica para portátiles sin GPU dedicada | $20,00 | Portátil con procesador y termómetro (`termica_portatil`) |
| Renovación de pasta térmica para portátiles Gamer con GPU dedicada | $65,00 | Portátil gamer con CPU, GPU y ventilador (`termica_gamer`) |

Se crean una sola vez si no existen con ese nombre (`quotes.seed_thermal`; también con «Cargar catálogo»). No modifican otros servicios ni presupuestos existentes. En el selector del presupuesto, el botón para limpiar la búsqueda ya no se monta sobre «Nuevo servicio o repuesto».

## Formateo e instalación de Windows y respaldo de información (1.5.181)

| Servicio | Precio | Icono |
| --- | --- | --- |
| Formateo e Instalación Profesional de Windows — formateo de la unidad, instalación limpia de Windows, configuración inicial y controladores básicos | $15,00 | Portátil con el logotipo de ventanas (`formateo`) |
| Servicio de Respaldo y Protección de Información Digital — respaldo de archivos personales y documentos importantes con verificación de integridad | $20,00 | Unidad de almacenamiento con flecha de copia y verificación (`respaldo`) |

Precio final con IVA incluido (no se suma de nuevo). Se crean una sola vez (`quotes.SEED_BATCHES`, alta por nombre y marca en `system_state`): no se duplican aunque se repita la carga, y no cambian los demás servicios ni los presupuestos existentes. Disponibles en presupuestos (y, por ellos, en las órdenes).

## Guardar y enviar sin errores (incidencia INC-20261020-003)

**Causa real.** En producción, `POST /api/quotes/{id}` (acción «enviar») fallaba con `OperationalError` en `remote_db.py:309 · _post`. El presupuesto ya estaba guardado y marcado como enviado, y el servidor de correo ya había aceptado el mensaje. Pero mientras el sistema hablaba con el servidor de correo (7 y 12 s), Turso cerró la conexión HTTP inactiva. La anotación siguiente («correo aceptado») salía por esa conexión cerrada y no se reintentaba, ni siquiera siendo el primer paso de una transacción nueva. Las dos apariciones fueron dos presupuestos distintos (14:07 y 14:11), no un doble clic.

**Corrección de raíz (`remote_db.py`):**
- Las conexiones inactivas más de 3 s se renuevan antes de usarlas. Es seguro incluso dentro de una transacción, porque el *baton* identifica el flujo, no la conexión.
- El primer envío de una transacción nueva se reintenta si la conexión estaba cortada: nada se confirma sin COMMIT.
- Lo que va dentro de una transacción en curso nunca se repite. Si se pierde la respuesta, la transacción se descarta entera y el error indica la operación (verbo y tabla, sin valores).

**Flujo profesional:**
- **Antes de enviar** se comprueba que haya al menos una partida, que la fecha «Válido hasta» no haya pasado y que las observaciones no superen 1500 caracteres. Cantidades, precios y categorías se validan junto a cada campo, y el servidor vuelve a comprobarlo todo.
- **Guardar y enviar** guarda primero («Guardando…») y después envía («Enviando…»). Mientras dura, todas las acciones del editor quedan bloqueadas.
- **Envíos simultáneos:** el servidor reserva cada envío de forma atómica, con caducidad de 90 s. Un segundo envío simultáneo del mismo presupuesto recibe «Este presupuesto ya se está enviando», así que no se generan dos enlaces ni dos correos.
- **Si falla el correo**, el presupuesto queda guardado y enviado, con su enlace válido, y se ofrece «Reintentar envío» en el resultado y en el presupuesto. Si se guardó pero el envío no llegó a completarse, el editor lo indica y el botón pasa a «Reintentar envío».
- **Al terminar** aparece la notificación «Presupuesto guardado y enviado correctamente al cliente.».
- **Ante un problema temporal de base de datos** se responde 503 con el mensaje «No se pudo guardar el presupuesto por un problema temporal de base de datos. Intente nuevamente.». La operación sin confirmar se descarta, y el error queda en ADI AutoCare con usuario, presupuesto, endpoint, operación SQL, hora, código interno y causa original.
- **Totales:** se calculan siempre desde las partidas guardadas con la misma fórmula en pantalla y en el servidor (descuento por línea, IVA 15 % incluido solo en las partidas gravadas). Al quitar el IVA de una partida, su precio pasa a la base sin impuesto.

## Aprobaciones, estados y orden sincronizados (1.5.201)

**Caso que lo motivó (PCD-20261019-0005).** El cliente firmó el 21/10 a las 19:17 la autorización de servicio (`/autorizar/`): diagnóstico, acceso al sistema, archivos y formateo. Esa firma no aprueba importes.

El presupuesto P1 ($145,35) sigue «Esperando aprobación»:

- su enlace nunca se abrió;
- no tiene firma, aceptación ni decisión.

No se crean aprobaciones a partir de la autorización de servicio. Para recuperarlo hay que pedir al cliente que confirme desde su enlace, o registrar una decisión del personal con una nota, que queda marcada como «sin firma del cliente».

### Estados del presupuesto

| Evento | Estado |
|---|---|
| Creado | Borrador |
| Enviado | Esperando aprobación |
| El cliente aprueba todas las partidas | Aprobado |
| El cliente aprueba algunas | Aprobado parcialmente |
| El cliente rechaza todas | Rechazado |
| El cliente pide cambios | Revisión solicitada |

El estado cambia en la misma transacción en que el servidor registra la decisión, junto con las partidas, la firma y la evidencia. El enlace queda revocado después, así que reenviarlo o abrirlo de nuevo no duplica nada.

### Orden

Si la orden esperaba la decisión («Aprobación de presupuesto» o «Esperando respuesta del cliente»), una aprobación total o parcial la pasa a **Procesando**. El historial dice si fue el cliente o el personal.

- Un rechazo deja la orden donde estaba, para que el taller decida.
- Nunca se toca «Listo», «En espera de entrega» ni «Entregado».
- Nunca se marca el equipo como reparado.

### Sin recargar

Mientras un presupuesto espera respuesta, la orden consulta cada 30 s. Si cambia el estado de un presupuesto, se vuelve a leer la orden de la base de datos y se actualizan:

- «Autorizaciones del cliente»;
- el estado del equipo;
- el saldo.

Aparece también un aviso. El centro de notificaciones ya avisaba de las decisiones.

### «AUTORIZACIÓN CONFIRMADA»

El bloque de autorización se muestra en verde si se aprobó todo y en naranja si la aprobación fue parcial. Incluye:

- presupuesto y estado;
- partidas autorizadas;
- total autorizado, sin mezclarlo con lo pagado;
- fecha real de aprobación;
- estado del proceso;
- si lo aprobó el cliente o se registró por el personal.

Cuando la autorización de servicio está firmada pero el presupuesto sigue pendiente, la orden lo explica. Administración ve además el botón «Pedir al cliente que apruebe …», que reenvía el enlace.
