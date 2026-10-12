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
