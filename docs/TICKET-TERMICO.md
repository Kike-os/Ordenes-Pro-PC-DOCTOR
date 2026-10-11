# Ticket térmico y autorización técnica — 10/10/2026

## Resultado aplicado

El ticket utiliza nombre corporativo sin logo gráfico, título, QR superior centrado, número destacado, recepción, cliente, equipo, decisión de acceso, condiciones resumidas, enlace a la versión completa, Code 128 inferior, agradecimiento y contactos oficiales. Una sola página de altura adaptable, blanco y negro, tipografía de 9 pt en contenido y 8 pt en referencias. Los textos extensos se ajustan a líneas completas.

El QR codifica exactamente el `qr_url` existente. Code 128 B/C codifica únicamente `order.code`, con checksum módulo 103, módulos de dos puntos a 203 dpi, altura de 17 mm y zonas de silencio de diez módulos. El buscador abre la orden correspondiente al introducir el código exacto y pulsar Enter, con sesión autenticada.

## Impresora y controlador comprobados

Cola real: `Epson_Red_192_168_128_45`, identificada por CUPS como Epson TM-m30II de red, transporte `socket://192.168.128.45:9100`, controlador `EPSON TM Thermal (203dpi)`, filtro `rastertotmtr`. La impresora predeterminada es una L3150: no se utiliza para la impresión directa del ticket. No se inventó ni modificó ninguna dirección IP.

La cola tenía por defecto RP80x200 y NoCut. El PPD instalado declara RP80 con ancho de página de **204,3 pt, aproximadamente 72 mm útiles**, aunque el rollo físico es de 80 mm. El PDF utiliza 72 mm y un margen interior de 1 mm; la impresora aporta los márgenes físicos del rollo. El QR tiene módulos enteros de cuatro puntos y cuatro módulos de silencio. La muestra tiene 406 mm de largo; textos más extensos generan una página más larga, no páginas adicionales.

La especificación oficial confirma 72 mm/576 puntos y 203 dpi: [guía técnica Epson TM-m30](https://download4.epson.biz/sec_pubs/bs/pdf/TM-m30_trg_en_revL.pdf). Modelo instalado identificado por la cola y por registros de diagnóstico existentes; la identidad física actual no pudo volver a consultarse porque el dispositivo no respondió a la conexión TCP.

### Ruta de impresión integrada

En la vista previa térmica, el botón cambia a **Imprimir en Epson de red** si el servidor encuentra la cola y herramientas locales. La configuración explícita está en `local/data/thermal-printer.json` y contiene el nombre de la cola instalada, sin credenciales. En servidores sin CUPS/Epson se mantiene descarga e impresión manual del PDF.

La impresión directa usa:

1. PDF idéntico en datos y diseño al de vista previa.
2. Ghostscript con página fija, 203 dpi, ancho exacto de 576 puntos, monocromo y altura calculada desde el PDF.
3. PPD real obtenido del CUPS local y filtro `rastertotmtr` con `TmxPaperCut=CutPerJob` y `TmxPaperReduction=Bottom`.
4. Una copia ESC/POS mediante `lp -d <cola explícita> -o raw`.

Se evita el filtro PDF intermedio: las pruebas confirmaron que la cadena CUPS instalada vuelve a A4 con tamaños Custom y recorta el ticket. No se modificaron el PPD ni los valores globales de la cola. El ráster exacto y el filtro Epson generaron una sola página de 576 × 3245 puntos para la muestra y un único comando de corte.

Cada envío exige sesión, CSRF e identificador de solicitud. El servidor reserva la solicitud antes de enviar y conserva su estado. Repetir la misma solicitud no genera otra impresión. Tras confirmarse el envío aparece **Reimprimir otra copia**, que crea un nuevo trabajo de impresión sin crear órdenes, clientes ni números nuevos. Un resultado incierto requiere revisar la cola y no se reenvía automáticamente. “Enviado a la cola” no equivale a confirmar papel impreso.

Comprobación local sin impresión:

```bash
python maintenance/print-thermal.py output/pdf/ticket-pcdoctor-vista-previa.pdf --printer Epson_Red_192_168_128_45 --render-only /tmp/ticket-pcdoctor.prn
```

Para imprimir una copia del PDF descargado, cambiar `--render-only ...` por `--send`. El helper comprueba conexión y no usa la impresora predeterminada. Para impresión manual desde PDF seleccionar la cola térmica, rollo largo RP80x2000, escala 100 %, reducción de papel en ambos extremos y corte por trabajo; se recomienda la ruta directa verificada para evitar diferencias del diálogo del navegador.

## Autorizaciones y condiciones

El paso Recepción exige una decisión explícita de acceso técnico, sin valor preseleccionado. Sistema operativo, pruebas con sesión iniciada, archivos específicos y respaldo son permisos independientes. Archivos/respaldo necesitan descripción y justificación. No se imprimen esos detalles libres ni claves en el ticket.

Reinstalar, formatear o eliminar información es una autorización adicional independiente, sin permiso predeterminado; exige alcance y confirmación propia. El diagnóstico no habilita esas acciones.

La migración `013_technical_access.sql` añade evidencia inmutable con orden, decisión, alcance, fecha/hora del servidor y usuario responsable. Se permiten nuevas decisiones conservando las anteriores. No se añade consentimiento retrospectivo. Las órdenes sin evidencia imprimen **No consta autorización**. Desde el detalle se puede completar el proceso con fecha actual; las condiciones aceptadas originalmente no se modifican.

En esta instalación **no había ninguna versión oficial publicada**. Se actualizó el borrador de ocho cláusulas, eliminando autorizaciones amplias y porcentajes de almacenamiento sin definir. Está listo en Configuración → Condiciones → Cargar borrador para revisión. Deben revisarse los textos completo y compacto, elegir versión/vigencia y confirmar su publicación administrativa. No se publicó automáticamente un documento marcado como aprobado. **Las recepciones nuevas requieren condiciones vigentes y aceptación expresa; hasta su publicación, el servidor impide guardarlas.** Las órdenes existentes se siguen consultando e imprimiendo.

El formulario presenta el texto completo antes de la aceptación. Se conserva versión, hash, mecanismo, cliente, fecha/hora, usuario y orden. El ticket imprime un único resumen informativo de las ocho materias solicitadas, sin repetir el texto compacto completo. La versión íntegra aceptada sigue accesible por su enlace histórico y en el PDF corporativo. `/conditions` permite consultar la versión vigente, una vez publicada. La muestra descargable tiene datos y aceptación ficticios, claramente identificados como vista previa.

## Pruebas y evidencias

- **77 pruebas del servidor aprobadas**: autorización obligatoria, permisos independientes, rechazo de inconsistencias, evidencia inmutable, cambios con revisión, consentimiento posterior sin retroactividad, CSRF, impresión idempotente y resultado incierto, reimpresión sin órdenes nuevas, búsqueda autenticada, más regresiones existentes de QR, comprobantes, sesiones, agenda, estados y presupuestos.
- **21 comprobaciones de navegador**: recepción/autorización, condiciones completas y autorización adicional en 1920, 1440, 1366, 1024, 768, 390 y 320 px. Sin desbordamiento horizontal ni cierre/pie fuera de pantalla. Se guardó una orden ficticia desde el formulario y se abrió mediante su código exacto. Botón nativo y reimpresión comprobados con transporte simulado, sin abrir simultáneamente impresión del navegador.
- PDF revisado visualmente y mediante geometría: muestra, negativa, histórica y textos largos; una página cada uno, cero caracteres fuera de página y un solo resumen de condiciones.
- ZBar decodifica QR y Code 128 desde el PDF rasterizado a 203 dpi y desde el ráster exacto de impresión Epson. También se generó y verificó el ticket de la orden real existente.
- Respaldo previo: `revision/thermal-redesign-20261010/before.sqlite3` y respaldo automático de migración. Comparación antes/después confirma idénticos números, QR, instantáneas y aceptación de las órdenes reales. Cero autorizaciones históricas inventadas y comprobación de claves foráneas sin errores.
- Servicio local reiniciado; página de acceso HTTP 200.

Evidencias en `revision/thermal-redesign-20261010/`: `tests.log`, `browser-checks.json`, `pdf-checks.json`, `scanner-checks.json`, `driver-validation.log`, `real-ticket-checks.json` y huellas antes/después. Vista previa: `output/pdf/ticket-pcdoctor-vista-previa.pdf`.

## Pendientes reales

La Epson no respondió en su conexión configurada. No se envió un trabajo físico ni se afirma haber verificado papel, corte mecánico o lectura con el escáner físico del taller. Faltan esas comprobaciones al conectarla y publicar las condiciones revisadas desde administración. No estuvieron disponibles dos PDF nuevos adjuntos; se inspeccionaron los PDF anteriores del proyecto y el generador existente.

## Archivos principales

`local/thermal_pdf.py`, `local/code128.py`, `local/technical_access.py`, `local/thermal_printing.py`, `local/app.py`, `local/migrations/013_technical_access.sql`, `local/static/app.js`, `local/static/app.css`, `local/data/thermal-printer.json`, `local/data/service-terms-draft.json`, `maintenance/print-thermal.py`, `local/tests/test_thermal_access.py` y ajustes de fixtures/regresión en `test_app.py`, `test_reception.py` y `test_service_terms.py`.

## Actualización 11/10/2026 — Ticket con logo, QR de seguimiento y copias

**Orden del ticket:** logo original en un bit (38 mm, un píxel por punto de impresora), datos del taller, título y copia, número destacado, fecha y hora, cliente, equipo (marca, modelo, serie, accesorios, estado físico y falla informada), QR centrado, autorización y condiciones (mismos textos y evidencia que antes), firma y constancia de recepción, Code 128 y agradecimiento. Sigue siendo blanco y negro, 72 mm útiles y una página de altura variable por copia.

**QR:** módulos de 5 puntos a 203 dpi con zona de silencio de 4 módulos y corrección de errores M. Con el enlace actual mide 28 mm de lado incluida la zona de silencio (símbolo de 23 mm). Si no cabe, baja a 4 o 3 puntos por módulo.

**Seguimiento público (`/s/<token>`):** cada orden nueva recibe un enlace con 128 bits aleatorios (tabla `order_tracking_links`, migración `021_order_tracking.sql`). El enlace no contiene el número de orden ni datos del cliente. La página muestra solo número de orden, estado, tipo/marca/modelo del equipo y fechas de recepción y última actualización; no muestra nombre, identificación, teléfono, serie, falla, notas ni importes. Lleva `noindex`, `no-referrer`, `no-store` y límite de consultas por IP. Un enlace inexistente o desactivado responde con la misma página genérica.

**Revocación:** en el detalle de la orden, «Seguimiento para el cliente» permite copiar el enlace, desactivarlo o generar uno nuevo (el anterior queda revocado). Ambas acciones exigen sesión de administración o técnico, CSRF y quedan en auditoría.

**Órdenes sin enlace activo** (anteriores a esta versión o con el enlace desactivado): el ticket imprime el `qr_url` histórico sin cambios con la leyenda «Uso interno: escanear con sesión autorizada» y no anuncia consulta en línea. El `qr_url` guardado de cada orden no se modifica.

**Copias:** `thermal.pdf?copy=cliente|taller|ambas`. «Ambas» genera un PDF de dos páginas; la impresión directa envía dos trabajos de una página, cada uno con su corte.

**Verificado sin imprimir:** ZBar lee el QR y el Code 128 desde el PDF rasterizado a 203 dpi, con y sin enlace público. **Pendiente real:** impresión física en la Epson TM-m30II y lectura del QR desde teléfonos.
