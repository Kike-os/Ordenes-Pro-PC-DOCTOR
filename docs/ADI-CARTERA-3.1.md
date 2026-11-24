# ADI Smart Collections 3.1 · Premium Financial Management (1.5.332)

## Errores encontrados y su causa

| Error | Causa | Corrección |
|---|---|---|
| Órdenes «Por vencer» con exigibilidad «Al retirar» | Todo saldo de un equipo no entregado se clasificaba como «por vencer», como si tuviera vencimiento | Nuevo estado **«Pago al retirar»** (celeste): no es deuda vencida, no cuenta días de mora y no permite mensajes de regularización |
| «0 días» de atraso sin fecha de exigibilidad | Un valor desconocido se mostraba como cero | Ahora es «No aplica» (valor `null`), y el contador de **días por retirar** va aparte |
| Una orden pagada solo con una transferencia por validar **desaparecía** de la cartera | El saldo descuenta los pagos aunque su transferencia esté pendiente, y la cartera omitía los saldos en cero | Se muestra como **«Pendiente de conciliación»** (violeta), con el importe por validar |
| «Al día» en conciliación | Faltaba de información que no hubiera transferencias pendientes | Estados precisos: «Sin pagos registrados», «Transferencia pendiente de validar», «Pago confirmado», «Pago parcial confirmado», «Conciliación en revisión», «Diferencia detectada» (transferencia rechazada sin anular el pago) |
| «HP HP» | Se unían marca y modelo aunque el modelo ya incluía la marca, y se repetía el mismo equipo | `device_label()` lo corrige; no se cambian los datos históricos |
| Números de orden partidos, filas altas, botones grandes y columnas fuera de pantalla | Tabla con anchos automáticos y acciones de texto | Tabla de ancho fijo por porcentajes, número de orden en una línea con botón Copiar, acciones de icono y tarjetas por debajo de 1280 px |
| Datos de cobertura | — | Revisado: la cobertura comercial ya reduce el precio del presupuesto y la interna no cambia lo que debe el cliente. **No hay duplicidad.** Se muestran en Movimientos como «Beneficio PC-DOCTOR» |

## Estados financieros (servidor, nunca la IA)

| Estado | Color | Regla |
|---|---|---|
| Pago al retirar | celeste | Equipo no entregado, sin compromiso |
| Acuerdo de pago vigente | azul | Compromiso vigente, a más de 3 días |
| Por vencer | azul | Compromiso que vence en 1 a 3 días |
| Vence hoy | amarillo | Compromiso que vence hoy, o entrega hoy con saldo |
| Pago vencido | naranja | Entregado con saldo, de 1 a 90 días |
| Mora superior a 90 días | rojo | Entregado con saldo, más de 90 días |
| Compromiso incumplido | naranja (rojo si supera 90 días) | Compromiso incumplido o parcial |
| Pendiente de conciliación | violeta | Saldo cubierto solo con transferencias por validar |
| En revisión | gris | Reclamo PQRS (queja o reclamo) abierto, transferencia rechazada, compromiso en revisión, derivación o conciliación solicitada |
| Requiere revisión | gris | No hay información suficiente; por ejemplo, entregado sin fecha de entrega. **No se inventan valores** |
| Saldo a favor | verde | El cliente pagó de más |

**Tres estados independientes:**

- el estado técnico (de la orden);
- el estado financiero;
- el estado de conciliación.

**Dos contadores separados:**

- **días por retirar**, desde que el equipo quedó listo;
- **días de atraso**, desde la entrega o la fecha del compromiso, nunca desde el ingreso.

## Indicadores (sin duplicidades)

**Indicadores principales:**

- capital pendiente total;
- pagos condicionados al retiro;
- cartera por vencer;
- cartera vencida, con la parte de más de 90 días como subconjunto;
- compromisos e incumplidos;
- intereses simulados (aparte, no suman al saldo);
- intereses autorizados ($0,00);
- pendiente de conciliación;
- pagos recuperados del mes.

**Control de consistencia:** la suma de los grupos debe igualar el capital total (`consistent`). Si no, aparece «Requiere revisión».

**Filtros:** cliente, orden, factura, estado financiero, exigibilidad (desde y hasta), atraso, compromiso, conciliación y forma de pago.

## Tabla y acciones

**Columnas:**

- Orden (con Copiar; al pulsarla abre el expediente);
- Cliente;
- Equipo;
- Capital pendiente (a la derecha y en cifras tabulares);
- Estado financiero;
- Exigibilidad;
- Días de atraso;
- Compromiso;
- Conciliación;
- Acciones.

**Acciones:**

- **Visibles:** Expediente y ADI.
- **Menú desplegable** (fuera de la tabla, para que nunca quede recortado; se maneja con teclado y se cierra con Escape):
  - Registrar compromiso;
  - Consultar pagos;
  - Estado de cuenta A4 y 80 mm;
  - Simular intereses;
  - Consultar historial;
  - Suspender recordatorios;
  - Derivar a administración.

## Expediente económico

Tiene **seis pestañas**:

- **Resumen:** estado técnico y financiero por orden.
- **Movimientos:** pagos con su conciliación, beneficios PC-DOCTOR y facturas («autorizada» no implica pagada).
- **Compromisos:** con su evidencia, y el historial de acuerdos y reprogramaciones.
- **Intereses:** capital elegible, vencimiento, días, gracia, tasa validada, simulados y autorizados ($0,00).
- **Comunicaciones:** mensajes y respuestas.
- **Auditoría:** acciones con usuario y fecha, y las marcas.

**Estado de cuenta:** A4, 80 mm y el reporte administrativo con simulación. Incluye el estado financiero y «Días de atraso: No aplica» cuando corresponde.

## ADI Smart Communication

**Motivos nuevos:**

- **Aviso de vencimiento:** compromiso que vence en 0 a 3 días.
- **Regularización de saldo:** solo si la obligación está vencida. Nunca con «Pago al retirar».
- **Atención administrativa:** sin importes.

**El análisis integral muestra además:**

- el **estado financiero** del centro de cartera;
- los **reclamos o controversias** (PQRS abiertos).

**Control previo:** un reclamo abierto **bloquea** la cobranza.

**En la ventana de mensaje se ven, antes de generar:**

- el destinatario y la identidad;
- el WhatsApp enmascarado con su autorización;
- el estado financiero;
- los reclamos.

## Pruebas

`local/tests/test_collections_31.py` cubre estos casos:

- pago al retirar (no vencido, con contadores separados y sin regularización);
- retrasos de 89, 90 y 91 días;
- transferencia que cubre el saldo (sigue visible);
- pago parcial confirmado, transferencia rechazada y sin pagos;
- reclamo (en revisión, con la cobranza bloqueada y la propuesta detenida);
- varias órdenes de un cliente y equipos sin repetir;
- estado de cuenta con «No aplica»;
- entrega sin fecha («Requiere revisión»);
- 25 órdenes con consistencia y tiempo.

Además, las suites de cartera, ADI, compromisos e intereses: 65 pruebas correctas.

**Revisión visual:**

- en 1920, 1600, 1440, 1366 y 1281 px la tabla cabe sin desplazamiento;
- por debajo de 1280 px se ve en tarjetas;
- 390 y 320 px sin desbordamiento;
- el menú queda dentro de la pantalla.

## 3.2 · Premium Responsive Financial Interface (1.5.333)

**Error de la 1.5.332, visto en producción con datos reales:**

- encabezados encimados;
- palabras e importes partidos («$195,0 / 0», «No aplic / a», «compro / miso»);
- botones apilados.

**Causa:**

- La tabla de diez columnas usaba un ancho fijo por porcentajes (`table-layout:fixed`) y permitía cortar palabras en cualquier punto (`overflow-wrap:anywhere`).
- Las pruebas visuales usaban nombres ficticios cortos y solo medían el desbordamiento de la página.

**Corrección:**

- **Seis grupos:**
  - cliente y orden;
  - equipo;
  - capital pendiente;
  - estado financiero y exigibilidad;
  - seguimiento y conciliación;
  - acciones.
- **Sin anchos fijos** ni cortes de palabras (`word-break:normal`).
- **Botones** con `flex:none` y `white-space:nowrap`.
- **Cambio de presentación por el ancho real del contenedor** (*container queries*):
  - por encima de 1180 px, tabla con botones con texto;
  - entre 981 y 1180 px, botones solo con icono y descripción emergente;
  - hasta 980 px, tarjetas financieras.
- **Iconos:** FolderOpen (Expediente), Bot (ADI) y Ellipsis (más acciones). El menú se abre en un portal y nunca queda recortado.
- **Indicadores con icono:**
  - capital pendiente;
  - total de obligaciones;
  - pagos al retirar;
  - cartera vencida;
  - compromisos;
  - por conciliar;
  - intereses simulados;
  - intereses autorizados.
- **Paginación** de 25 en 25.
- **Expediente:** pestaña **Pagos** separada de Movimientos.

**Prueba visual automatizada** (`local/tests/visual_collections.py`, con Playwright):

- **Recorrido:**
  - 1920, 1600, 1366, 1280, 1024, 768 y 390 px;
  - zoom del navegador al 80, 100, 125 y 150 %;
  - nombres y modelos largos e importes altos (por ejemplo, $12.345,67);
  - todos los estados.
- **Falla si encuentra:**
  - desbordamiento de la página o dentro de la tabla;
  - botones superpuestos;
  - encabezados recortados o encimados;
  - una palabra o un número de orden partido;
  - texto fuera de su contenedor;
  - el menú fuera de la pantalla.
- **Resultado:** 22 combinaciones, **0 fallos**. Las siete pestañas del expediente caben en 1366 y 390 px.
