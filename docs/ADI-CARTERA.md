# ADI 3.0 · fases 4 y 5: ADI Smart Collections (1.5.330)

Está en **Facturación → Cartera ADI**. Solo lo usa administración.

**Archivos:**

- Módulos: `local/collections_center.py` y `local/account_statement.py`.
- Migración: `121_collection_flags.sql`. Solo crea la tabla `collection_flags`.
- Rutas: `/api/collections…`.

**Límites:** nada de esto registra pagos, cambia saldos, aplica intereses, envía mensajes ni dispone de equipos.

## Fase 4

### Centro de gestión de cartera

- **Fuente única:** los cargos y pagos de cada orden, consolidados una sola vez por orden, como en la tarjeta financiera.
  - Una factura autorizada no cuenta como pagada.
  - Una transferencia por conciliar no se descuenta del saldo ni se da por pagada: se muestra aparte.
- **Exigibilidad** (criterio operativo, revisable jurídicamente):
  - el saldo es exigible desde la **entrega** del equipo o desde la **fecha acordada de un compromiso**;
  - mientras el equipo está en el taller o listo, el saldo está «por vencer»;
  - nunca se cuenta desde la fecha de ingreso.
- **Indicadores:**
  - capital pendiente, cartera vencida y cartera por vencer;
  - intereses simulados (solo con una tasa validada; nunca suman al saldo);
  - intereses autorizados (siempre $0,00);
  - pagos recuperados del mes (cobros posteriores a la entrega);
  - compromisos pendientes e incumplidos;
  - equipos por retirar;
  - casos en revisión.
- **Filtros:** cliente, orden, factura, vencimiento (desde y hasta), forma de pago, antigüedad (por vencer, 1–30, 31–60, 61–90 o más de 90 días), estado del compromiso y conciliación.
- **Cada fila abre** el **Expediente** del cliente o el **Mensaje** de la orden (con el control previo de 12 puntos), sin perder la sección.

### Expediente económico del cliente

**Muestra:**

- obligaciones con saldo;
- órdenes, facturas, presupuestos, y pagos y anticipos (confirmados, por conciliar o anulados);
- compromisos y el historial de acuerdos (con su evidencia);
- notificaciones y respuestas por WhatsApp;
- marcas y observaciones administrativas.

**Acciones:**

- **Estado de cuenta** en A4 y en 80 mm.
- **Revisar liquidación:** versión interna con la simulación, marcada «NO ENTREGAR AL CLIENTE».
- **Marcas** (con motivo obligatorio, auditadas y cerrables):
  - **Suspender recordatorios** hasta una fecha (máximo 180 días);
  - **Derivar a administración** (solo administración la cierra);
  - **Solicitar conciliación**;
  - **Observación administrativa**.
  - Una suspensión, una derivación o una conciliación vigente **bloquean** los mensajes de cobranza en el control previo.
- **Autorizar condonación:** aparece desactivada, porque no hay intereses ni cargos aplicados.
- **Desde «Mensaje» de cada orden:** registrar un compromiso, ampliar el plazo (reprogramar), simular intereses y generar el mensaje.
- **Vista digital segura:** es el propio expediente, dentro de la aplicación y con sesión.
  - El enlace público para el cliente queda para el portal seguro con QR del Premium Billing Center. Está pendiente, porque exige permisos y una migración propios.

### Estado de cuenta (`account_statement.py`)

**Formatos:** PDF A4 (con varias páginas si hace falta) y ticket de 80 mm (contenido de 68 mm y altura según el contenido).

**Incluye:**

- logotipo original y fecha de corte;
- cliente;
- por cada orden: capital original, pagos registrados, transferencias por conciliar (no descontadas), saldo, fecha y base de exigibilidad, y días de vencimiento;
- período de gracia;
- tasa aplicada: «Ninguna»;
- intereses autorizados: $0,00;
- total actualizado;
- datos de consulta.

Dice expresamente: **«Documento informativo: no es una factura ni un comprobante tributario.»**

## Fase 5

### Equipos pendientes de retiro

Es un control **independiente** de la cobranza. Cada equipo muestra:

- desde cuándo está listo y los días transcurridos;
- el primer aviso de retiro y su evidencia (canal y estado);
- el plazo de retiro y las prórrogas con su motivo;
- el estado y el saldo.

**Alertas** a los 30, 60, 85 y 90 días. Desde los 90 días:

- el caso pasa a **revisión administrativa y jurídica**;
- **nunca** se autoriza vender, rematar, eliminar ni disponer del equipo;
- los gastos de almacenamiento no se confunden con intereses.

### Auditoría de comunicaciones

Para cada mensaje registrado muestra:

- fecha, cliente y orden;
- **motivo** (el de ADI, si se preparó con un motivo);
- **fuente** de los datos;
- plantilla, canal, estado y usuario;
- **entrega** (entregado o leído);
- **respuesta** del cliente por WhatsApp en los 7 días siguientes;
- **resultado**: pago registrado, compromiso registrado o sin resultado, en los 7 días siguientes.

No guarda contenido sensible nuevo.

### Propuestas de seguimiento por eventos

**Eventos que generan una propuesta:**

- 3 días antes y el día del vencimiento de un compromiso;
- 7, 15, 30, 60, 85 y 90 días de retraso;
- retiro a los 30, 60, 85 y 90 días.

**Se detienen** con cualquiera de estas condiciones:

- saldo cancelado;
- acuerdo vigente;
- revisión;
- transferencia por conciliar;
- suspensión o derivación;
- una gestión en los últimos 3 días.

**Nada se envía solo:**

- «Preparar mensaje» abre la ventana de seguimiento con el motivo elegido y su control previo, que aplica el horario de lunes a viernes de 08:00 a 19:00, sin feriados, y una gestión de cobranza al día.
- El **envío automático de campañas no está autorizado**: requiere aprobar estas reglas.

## Pruebas

`local/tests/test_collections.py` cubre estos casos:

- fuente única y antigüedad: por vencer → vencida por la entrega → 31–60 días;
- filtros;
- compromiso como vencimiento, con el interés simulado aparte ($0,85 sobre $150 a 120 días, sin sumar al saldo);
- marcas: motivo obligatorio, bloqueo de la cobranza y cierre;
- expediente sin el celular completo;
- estado de cuenta A4 y 80 mm («no es una factura», saldo exacto, sin simulación), sin efectos en pagos, mensajes ni facturas;
- retiro a los 90 días, con revisión y sin disposición;
- hitos y bloqueos de las propuestas;
- auditoría con motivo y resultado;
- acceso solo de administración.
