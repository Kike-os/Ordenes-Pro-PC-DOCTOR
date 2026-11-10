# Condiciones y presentación documental

Implementación local, 09/10/2026. **Versión oficial vigente: 2026.10.1, desde el 12/10/2026**, publicada en producción por decisión expresa de administración (Enrique Carlos Martínez Gómez) con el texto de ocho cláusulas del borrador revisado y su resumen para el ticket. Las órdenes anteriores no tienen aceptación registrada y no se les atribuye ninguna; la aceptación se registra en cada orden nueva. Para cambiar el texto se publica una versión nueva (las publicadas son inmutables). Los ejemplos de `revision/*condiciones-prueba*` contienen exclusivamente textos ficticios y no deben entregarse a clientes.

## Publicación

En Configuración, un administrador introduce versión única, fecha de vigencia, texto completo y texto compacto, y confirma que ambos textos han sido aprobados por PC-DOCTOR S.A. Separar cláusulas con una línea vacía; se conservan las numeraciones existentes. El servidor rechaza símbolos incompatibles, párrafos excesivos y versiones duplicadas. Las versiones publicadas son inmutables: los cambios requieren publicar otra versión. Una vigencia futura no reemplaza anticipadamente la versión actual.

La aceptación aparece en el último paso de recepción. El servidor exige una confirmación booleana de la versión vigente, registra fecha y hora de Ecuador, usuario responsable, nombre del aceptante y un identificador de evento. Se conserva la versión y su SHA-256. Es una confirmación en pantalla registrada por el técnico, no una firma electrónica certificada ni una comprobación de identidad del cliente.

Desde la 1.5.35, por decisión de administración (11/10/2026), la falta de condiciones publicadas **no bloquea** el registro de órdenes: el paso Confirmación muestra «Sin condiciones activas», la orden se guarda con su número y QR y no se fabrica ninguna aceptación (los campos de aceptación quedan vacíos aunque el navegador envíe otra cosa). Cuando hay una versión vigente, la aceptación sigue siendo obligatoria. Para volver a exigir condiciones publicadas antes de registrar, definir `REQUIRE_SERVICE_TERMS=true` en el servidor. Las órdenes anteriores mantienen sus datos y no reciben aceptaciones retroactivas.

## Consulta y documentos

El enlace HTTPS `/conditions/<identificador>` muestra solo la versión completa pública, sin datos personales. Configurar `PUBLIC_APP_URL` con el dominio HTTPS real antes de publicar. Consultar órdenes, PDF, tickets y QR sigue requiriendo acceso autorizado. El QR conserva exactamente su URL de seguimiento anterior.

El PDF A4 incorpora el logo original, texto completo y evidencia de aceptación. Conserva los párrafos completos mediante paginación. El ticket térmico incorpora logo monocromático, texto compacto, enlace completo, evidencia y el mismo QR. La aplicación muestra un enlace específico al PDF térmico.

## Epson configurada localmente

Se detectó la cola `Epson_Red_192_168_128_45`, Epson TM-m30II, controlador de 203 dpi. La impresora predeterminada es una L3150: seleccionar expresamente la cola térmica. El PDF utiliza papel de 80 mm y área útil de 72 mm. Imprimir al 100%, sin encabezados del navegador, con rollo largo. El tamaño predeterminado de la cola es 80×200 mm y puede resultar insuficiente.

Para un comprobante real aprobado, pueden seleccionarse por trabajo `PageSize=RP80x2000`, `TmxPaperReduction=Bottom`, `TmxPaperCut=CutPerJob` y escala 100%. No se alteraron las preferencias globales ni se envió una impresión física. La verificación física queda pendiente de disponer de condiciones aprobadas.

## Instalación

La migración `005_service_terms.sql` añade tablas, columnas e índices sin borrar registros, con respaldo previo mediante el migrador existente. Incluir `service_terms.py`, `document_logo.py`, `thermal_pdf.py`, `receipt_pdf.py`, estáticos y plantillas actualizados. Reiniciar los procesos Python/Passenger después de actualizar. El ZIP no contiene la base de datos, archivos `.env` ni credenciales.

Actualización 10/10/2026: el ticket, el consentimiento técnico independiente y la ruta de impresión nativa se documentan en [TICKET-TERMICO.md](TICKET-TERMICO.md). El PPD instalado representa el área útil de 72 mm como tamaño de página para el rollo de 80 mm; la nueva ruta evita el retorno a A4 observado en tamaños personalizados.

## Documento «CONDICIONES DE RECEPCIÓN Y SERVICIOS» (1.5.78)

- **Título oficial:** «CONDICIONES DE RECEPCIÓN Y SERVICIOS». Las versiones que se publiquen a partir de ahora llevan el título «Condiciones de Recepción y Servicios»; las ya publicadas conservan el suyo (cada versión guarda su propio título).
- **PDF A4 en una página:** logotipo y «Servicio Técnico Especializado», título centrado, los ocho apartados con encabezado numerado, cierre «Aceptación y versión» y pie compacto con el contacto oficial. Legible en blanco y negro.
- **Borrador:** recuadro «BORRADOR PARA REVISIÓN · SIN VIGENCIA CONTRACTUAL» y nombre de archivo `BORRADOR - CONDICIONES DE RECEPCIÓN Y SERVICIOS.pdf` (`/api/conditions/draft.pdf`, requiere sesión). El texto del borrador no se ha modificado.
- **Versión publicada:** `/conditions/<identificador>.pdf` (público, sin datos personales), con versión y fecha de vigencia, y nombre `CONDICIONES DE RECEPCIÓN Y SERVICIOS.pdf`. La ruta HTML `/conditions/<identificador>` sigue igual.
- **Aprobación y versiones:** se mantiene el procedimiento de Configuración → Condiciones del servicio (versión única, fecha de vigencia, confirmación de aprobación, versiones inmutables e historial). Publicar exige una decisión administrativa real; nada se publica automáticamente.
- **Preparado para firma digital:** el cierre del documento indica la referencia y la huella SHA-256 del texto; cada aceptación se registra en la orden vinculada a esa versión exacta. El PDF no contiene firmas ni consentimientos, y no se atribuyen aceptaciones a órdenes anteriores.
- **Detalle de la orden:** el enlace abre el PDF de la versión aceptada por esa orden o, si no hay ninguna, el borrador rotulado como tal. El botón pasa a llamarse «Compartir condiciones del servicio» y comparte ese mismo archivo (el comprobante se sigue compartiendo desde «Compartir» en el listado y desde su vista previa).

## Gestión documental automatizada (1.5.108)

Configuración → Condiciones del servicio.

- **Versión vigente**: indicador con número, fecha de vigencia, huella y PDF oficial. La inicial es la **2026.10.1**.
- **Borrador de trabajo** (uno solo): se guarda con «Guardar borrador» sin publicar nada. Mientras exista, administración ve el aviso «Borrador de condiciones pendiente de aprobación» en el Centro de Actividad. Un técnico puede preparar el borrador; solo administración publica o lo descarta.
- **Comparación automática**: «Comparar con la versión vigente» resalta párrafos añadidos, retirados y modificados (estos últimos, palabra a palabra) e indica si cambia el texto compacto del ticket.
- **Publicación**: exige la casilla de aprobación y una confirmación. El número se asigna solo (`AAAA.M.N`: continúa la serie del mes o empieza en 1 al cambiar de mes; nunca se reutiliza). Un texto idéntico al vigente no genera versión. Nada se publica automáticamente.
- **Historial**: cada versión guarda fecha y hora, responsable, motivo y recuento de párrafos cambiados (tabla `service_terms_changes`); «Ver cambios» muestra sus diferencias frente a la anterior. Las versiones publicadas siguen siendo inmutables.
- **Órdenes**: cada orden nueva queda ligada a la versión vigente en el momento de la aceptación, con fecha, hora, responsable y evidencia; publicar después no altera las órdenes anteriores, y sus PDF y tickets siguen usando su versión.
- **Rutas**: `GET /api/conditions` (resumen, solo administración), `POST /api/conditions` (publicar), `POST /api/conditions/draft`, `/draft/discard`, `/compare` y `GET /api/conditions/compare/<id>`. Migración 039.

## Cláusulas, cortes de página y original firmado (1.5.271)

- **Una numeración por cláusula:**
  - Un bloque «N. Título» con su texto debajo abre una cláusula. Los párrafos siguientes, separados por una línea vacía y sin título, son su **continuación** y no reciben otro número.
  - Antes, cada párrafo se numeraba como una cláusula nueva, por ejemplo «2. La orden documentará…».
  - El texto guardado no cambia; las versiones publicadas de un párrafo por cláusula, como la 2026.10.1, se ven igual.
  - Lo mismo se aplica en el PDF A4, el comprobante A4 y la página pública.
- **Cortes de página:**
  - El título de una cláusula nunca queda solo al pie: viaja con al menos dos líneas de su texto.
  - Ninguna página empieza ni termina un párrafo con una línea suelta.
  - Una cláusula extensa continúa en la página siguiente, en lugar de rechazarse.
  - Los párrafos de una misma cláusula se separan de forma uniforme.
- **Original firmado electrónicamente** (Configuración → Condiciones del servicio, en cada versión):
  - **Carga (solo administración):** se carga el PDF firmado fuera de Órdenes Pro (PAdES, Security Data o FirmaEC). Se guarda **tal cual** se recibió, con su SHA-256, y nunca se modifica ni se vuelve a firmar.
  - **Comprobaciones al cargar:**
    - que tenga una firma `/ByteRange`;
    - que la firma cubra todo el archivo;
    - que la huella del contenido coincida con la firma;
    - la firma RSA con el certificado incluido;
    - que el PDF corresponda **a esa versión exacta**: debe contener su número y la huella del texto.
  - **Firmas no válidas o de otra versión:** se rechazan.
  - **Cadena de confianza y revocación:** no se comprueban en el sistema; se indica siempre y deben verificarse en FirmaEC o en Adobe.
  - **Datos que se muestran:** firmante, emisor, vigencia del certificado, fecha de firma y sello de tiempo, además de «Verificar integridad» y la descarga.
  - **Descarga pública:** `/conditions/<id>/firmado.pdf`; la página pública enlaza al original firmado.
  - **Registro:** tabla `service_terms_signed` (migración 101), inmutable y con historial.
- **Estados documentales:**
  - borrador → aprobado y publicado → **firmado electrónicamente**, si tiene original firmado → vigente → sustituido;
  - publicar y firmar son pasos distintos;
  - la versión de un documento no es la versión de la aplicación;
  - las aceptaciones de órdenes anteriores no cambian.
- **Verificación del original de la versión 2026.10.1:** firmado por ENRIQUE CARLOS MARTINEZ GOMEZ con un certificado de UANATACA CA2 2016 (válido del 01/07/2024 al 01/07/2027), el 09/11/2026 a las 22:53, con sello de tiempo. La integridad está verificada.

## Firma empresarial visual (1.5.271)

Se configura en **Configuración → Firma electrónica**, solo por administración.

- **La imagen:**
  - Se carga una imagen PNG o JPEG y se guarda **intacta**: nombre, QR, colores y proporciones se conservan, con su SHA-256 y su versión. Las versiones anteriores se conservan.
  - Se ve una vista previa antes de guardar.
  - Cada carga y cada cambio de configuración quedan en la auditoría.
- **Activación por documento:**
  - Está desactivada por defecto.
  - Puede activarse en el ticket de 80 mm, el comprobante A4, la hoja de servicio, los presupuestos, las proformas, los certificados de garantía y los recibos de pago.
  - Los comprobantes de entrega y los pedidos de repuestos todavía no existen como PDF y aparecen como no disponibles.
- **Tamaño y posición:**
  - Ancho en A4 de 25 a 90 mm, con alineación configurable.
  - Ancho en el ticket de 30 a 72 mm.
  - Se coloca al final del contenido, sin superponerse y en una página nueva si no cabe. En el ticket va en «Firma y constancia de recepción».
- **Ticket de 80 mm:**
  - Representación en blanco y negro derivada al vuelo: promedio por área y umbral, para que el QR conserve bordes nítidos y la transparencia salga en blanco.
  - Se puede omitir en el ticket.
  - El original no se toca.
- **No es una firma electrónica:**
  - Cada documento lleva la leyenda «Firma visual de identificación de PC-DOCTOR S.A. · No constituye firma electrónica de este documento».
  - Ningún PDF con la imagen se presenta como firmado (no se añaden `/ByteRange` ni `/Sig`).
  - El QR de la imagen pertenece a la firma original y no verifica el documento nuevo.
  - Para firmar digitalmente un PDF nuevo hace falta un procedimiento criptográfico independiente.
- **Vistas previas** en A4 y en ticket de 80 mm, sin datos de clientes.

## Firma empresarial a color y ticket térmico (1.5.272)

- **Color en lo digital:**
  - Los PDF A4 (comprobante, hoja de servicio, presupuesto, proforma, garantía y recibo de pago) y el nuevo **Ticket digital** de la orden (`/api/orders/<id>/thermal.pdf?modo=digital`) usan el original a color, con su transparencia y su resolución original, sin suavizado (`Interpolate false`), para que el QR conserve bordes nítidos.
  - El nombre, el QR y el sello verde «Time Stamping Security Data» se ven como en la imagen cargada.
- **Monocromo solo para imprimir:**
  - La representación en blanco y negro se genera al vuelo únicamente para el ticket térmico que se envía a la Epson (botón «Imprimir ticket» e impresión directa).
  - El PNG original nunca se convierte ni se reescribe; las versiones, los documentos ya emitidos y los PDF firmados no cambian.
- **Bloque «Firma y constancia de recepción» compacto:**
  - Dos columnas con líneas finas: «Firma del cliente» a la izquierda (espacio libre, nunca ocupado por la imagen) y «Recibido por / PC-DOCTOR S.A.» a la derecha, sin partir el nombre.
  - En el ticket, la disposición por defecto es **«Junto a "Recibido por" (compacto)»**: la imagen ocupa como máximo 33 mm dentro de la columna derecha, sobre su línea.
  - **«Debajo de las firmas, más grande»** la coloca centrada bajo ambas firmas con el ancho configurado (30 a 72 mm).
  - **«Omitir en el ticket»** no la imprime. El valor antiguo «bn» de la 1.5.271 se interpreta como la disposición compacta.
- **Legibilidad del QR:** la configuración detecta el QR de la imagen por sus patrones de esquina y avisa solo si un módulo quedaría por debajo de 3 puntos de impresora en el ticket o de 0,33 mm en A4. Si no hay aviso, no se muestra nada.
- **Vista previa compacta:** original a color sin cambios y «Formato de salida» con PDF A4 a color, ticket digital a color y simulación del ticket térmico en blanco y negro, cada uno con su PDF de muestra sin datos de clientes (`preview.pdf?doc=a4|ticket-digital|ticket`).
- El aviso amarillo resume que la imagen identifica visualmente a PC-DOCTOR S.A. y no sustituye una firma electrónica criptográfica; el detalle queda en «Ver información sobre firmas electrónicas».
