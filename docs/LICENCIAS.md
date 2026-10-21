# Licencias Pro — Control de Vigencia y Renovaciones

Módulo «Licencias» del panel (solo administración). Migraciones 062 (inventario) y 064 (Licencias Pro). Rama de pruebas `licencias-pro`.

## Registro
- **«+ Registrar nueva licencia»** crea el producto aunque la marca o el producto no existan en el catálogo (nombre, fabricante, categoría
  Antivirus/Microsoft/Sistema operativo/Ofimática/Utilitarios/Otros, versión o edición, logotipo, descripción, dispositivos, duración,
  tipo Suscripción/Perpetua/Otra, desde cuándo cuenta la vigencia, precio de venta y costo en USD) y registra la primera licencia.
- Activación: clave o serial, usuario y contraseña **opcionales**, código de licencia del fabricante (todo cifrado), enlace oficial e
  instrucciones. Comercial: proveedor, fecha de compra, costo, factura y **comprobante de compra** (PDF o imagen, privado).
- Productos: **Editar | Duplicar producto | Agregar stock** (una o varias licencias; nunca sobrescribe las anteriores) **| Consultar |
  Desactivar** (deja de ofrecerse en presupuestos; licencias e historial se conservan). Los logotipos se cargan o reemplazan con vista previa.
- Una misma clave solo se registra varias veces en productos de **clave compartida** (hasta su número de clientes).

## Vigencia
- Duración mensual, anual, bianual, trianual, perpetua o personalizada (meses). Meses de calendario: 19/10/2026 + 12 meses = 19/10/2027.
- Modalidad por producto: **desde la activación** (sin activación no hay vencimiento: nunca se inventa uno), **desde la compra** o
  **fecha fija del proveedor**. «Activar» registra la fecha real indicada por el personal; Órdenes Pro no afirma que se activó en los
  servidores del fabricante. Las perpetuas no vencen ni generan avisos.
- Estados con colores: Disponible (azul), Reservada (celeste), Entregada pendiente de activación (naranja), Activa (verde), Próxima a
  vencer (amarillo, 30 días o menos), Vencida (rojo), Renovada (turquesa), Anulada (gris). Los días restantes se calculan cada día.

## Ventas, entregas y devoluciones
- Desde Presupuestos: al aprobarse se reservan unidades concretas (un borrador no descuenta). Si faltan existencias, quedan pendientes y
  se reservan al registrar licencias nuevas.
- **La entrega la confirma manualmente administración**, sin depender de la confirmación del pago. Si la orden tiene saldo pendiente hay
  que aceptarlo expresamente y queda registrado. También hay **venta directa** a un cliente (con orden o presupuesto opcional).
- Se registran cliente, licencia, serial (cifrado), fecha y hora, usuario, estado y orden/presupuesto; la entrega queda en el historial
  de la orden. Una licencia entregada no puede entregarse otra vez. **Devolución autorizada**: la licencia queda anulada y no vuelve al
  inventario.
- El cliente consulta sus credenciales con un enlace privado (72 h) + identificación + código de 6 dígitos a su correo. El correo nunca
  lleva claves.

## Renovaciones
- «Renovar licencia»: nuevo período, **fecha efectiva de inicio** (no se asume el día del pago), vencimiento fijo opcional, costo y precio,
  y clave nueva si el fabricante la entrega (se crea otra licencia para el mismo cliente; la anterior queda «Renovada»). Cada renovación
  queda en `license_renewals` con el período anterior; nada se borra. Se suspenden los avisos pendientes del vencimiento anterior.

## Avisos y correos de renovación
- Tarea diaria del servidor (cron de Vercel a las 14:00 UTC = 09:00 de Ecuador): avisos internos (30, 15, 7 y 1 días antes y el día del
  vencimiento) en el panel y la campana, sin duplicados.
- **Notificaciones de renovación** a clientes (desactivadas hasta que administración las active): días configurables, asunto y mensaje
  personalizables, correo de prueba, historial con el resultado real (aceptado por el servidor; «entregado» solo con confirmación del
  proveedor), errores, reenvío manual, reintentos controlados (hasta 3) y clientes excluidos. Plantilla HTML corporativa adaptable a
  móviles con el logo de PC-DOCTOR S.A., el logo del producto y el botón «SOLICITAR RENOVACIÓN» (WhatsApp con mensaje preparado, sin datos
  sensibles). Nunca incluye seriales, contraseñas ni claves. No avisa de perpetuas ni de licencias sin activar.
- ADI responde «¿qué licencias vencen pronto?» con las próximas renovaciones (7 días) y el resultado de los recordatorios.

## «Mis licencias» (ficha del cliente)
- Tarjetas con logo, fabricante, tipo, dispositivos, fechas de entrega, activación y vencimiento, días restantes, estado, orden y
  presupuesto, historial de renovaciones y barra de vigencia (verde, amarillo, rojo; azul si falta la activación).
- Acciones de administración: Ver licencia, Activar, Renovar, Editar, Historial, Enviar información (sin credenciales) y avisos sí/no.
  El personal técnico ve la sección sin credenciales ni acciones.

## Seguridad
- Credenciales cifradas con `LICENSE_ENCRYPTION_KEY` (fuera de la base); ocultas por defecto; solo administración las ve, con registro y
  cierre automático a los 60 s. Búsqueda por serial mediante huella, sin mostrarlo. Historial inmutable con usuario, fecha y hora.

## Pendiente de decisión
- Correo automático de **confirmación de renovación** al cliente (propuesto en el encargo como mejora adicional): no implementado.

## Rediseño (1.5.173)
- **Causa del desplazamiento horizontal y del botón cortado:** el formulario ancho imponía `min-width:min(760px,88vw)` dentro de una
  ventana de 650 px como máximo. Se retiró ese mínimo y las ventanas de licencias tienen ahora encabezado fijo (título y cierre), cuerpo
  con desplazamiento solo vertical y pie fijo con las acciones; dos columnas en escritorio y una en móvil; ningún elemento sobresale.
- **Registrar nueva licencia:** secciones A. Producto (con vista previa del logotipo), B. Configuración, C. Comercial y D. Inventario y
  credenciales (una o varias claves, contador en vivo, aviso de líneas repetidas). Producto nuevo con varias claves en una sola operación.
  Validación inmediata con el mensaje bajo cada campo. Botón «Guardar licencia».
- **Vender o entregar licencia:** 1. Cliente (búsqueda y tarjeta con su correo), 2. Producto (tarjetas con logo, fabricante, duración,
  dispositivos, precio y disponibles; las agotadas no se pueden elegir; clave individual opcional), 3. Comercial (orden con su saldo,
  presupuesto, precio, descuento autorizado, total y estado de pago **informativo**), 4. Entrega y activación (fecha, responsable, estado
  inicial, activación real opcional y vencimiento calculado), 5. Resumen. Precio, descuento y estado de pago se guardan en la entrega
  (migración 065). No se confirma ningún pago.

## Centro de notificaciones (1.5.173)
- Las tarjetas muestran «N sin leer · M en total» por categoría (antes el número grande era el de no leídos sin indicarlo) y el encabezado
  el total general. Filtros: Todas, Sin leer, Licencias, Órdenes, Citas, Correos, Conversaciones y Sistema.
- Cada aviso: icono, título, resumen, fecha, indicador de lectura, «Marcar como leída», «Ocultar» y enlace. «Ver ocultas» permite
  recuperarlas (tabla `notification_hidden`, por persona; los riesgos de almacenamiento y respaldos no se pueden ocultar).
- «Marcar todas como leídas» indica «Todo está leído» cuando no hay pendientes, con contraste legible. Sin pendientes: «No tienes
  notificaciones pendientes». Los contadores salen de la base y se conservan al recargar.

## Ventas de licencias (migración 067, 1.5.176)

**Vender o entregar** abre una venta independiente de las órdenes técnicas: no pide orden, equipo, marca, modelo ni serie. Cada venta pertenece a un cliente y recibe su propio número consecutivo diario **VLIC-AAAAMMDD-0001** (asignado dentro de la transacción de escritura, sin duplicados).

- **Cliente:** buscador por nombre, cédula o RUC, teléfono o correo (sin tildes). «+ Registrar nuevo cliente» abre la ficha de cliente y, al guardarla, lo selecciona en la venta.
- **Carrito:** varios productos con cantidad, precio unitario y descuento autorizado por partida; subtotal, descuentos, total y saldo se calculan en pantalla y se vuelven a validar en el servidor. No se puede pedir más de lo disponible.
- **Reserva:** al registrar la venta se reservan claves concretas (todo o nada). Una clave reservada para una venta no se ofrece a otra ni se puede liberar o anular desde el inventario; solo se libera al cancelar la venta.
- **Pagos:** completos o parciales, con método (efectivo, transferencia, depósito, tarjeta u otro), fecha, referencia y comprobante JPG, PNG o PDF (máx. 1,5 MB, comprobado por su contenido; solo administración lo descarga). Un pago queda «Confirmado» o «Por confirmar»; **solo los confirmados cuentan** para el estado comercial. Los pagos no se borran ni cambian de importe: se anulan con motivo.
- **Estados separados:** comercial (Pendiente de pago, Pago parcial, Pagado) y de entrega (Pendiente de entrega, Entregado). Una venta cancelada queda «Cancelado» en ambos.
- **Entrega:** ahora (en la misma operación) o después desde la pestaña «Ventas». Con saldo pendiente hay que aceptarlo expresamente y queda registrado. Las claves pasan a «Entregada», se genera el enlace privado (identificación + código) y, si se marca, se envía el correo de entrega con número de venta, productos, pagos e instrucciones de activación: **nunca incluye claves**. La activación y el vencimiento se gestionan por licencia («Confirmar activación» en el detalle de la venta).
- **Orden técnica:** solo se vincula si se marca «Vincular a una orden técnica»; debe ser del mismo cliente. Al entregar se añade una línea al seguimiento de esa orden; nunca se modifica su historial.
- **Cancelar:** solo ventas no entregadas y sin pagos vigentes (anúlalos antes, por ejemplo tras un reembolso). Las claves vuelven al inventario; la venta, sus partidas y su historial se conservan.
- **Comprobante:** con el logotipo original, cliente, productos, cantidades, precios, pagos y estados; sin claves. Se imprime en un marco aparte.

Las entregas desde presupuestos aprobados (pestaña «Entregas») siguen funcionando igual.

## Inventario profesional (1.5.177)

- **Indicadores** compactos y uniformes (Disponibles, Reservadas, Activas, Por vencer, Vencidas, Renovaciones realizadas; y «En revisión» solo si hay datos inconsistentes). Al pulsarlos se filtra el inventario.
- **Tres vistas:** *Por cliente* (predeterminada: un encabezado desplegable por cliente con su tabla Cliente · Código LIC · Producto · Estado · Vigencia · Vencimiento · Acciones y aviso «por renovar»; lo no vendido queda en «Inventario general (sin vender)», sin cliente), *Tabla* (Código, Producto, Cliente, Estado, Activación, Vencimiento, Vigencia y Acciones, con orden por columnas, paginación y selección) y *Tarjetas* compactas.
- **Vigencia:** barra de 140 × 6 px que disminuye con los días, con porcentaje y días restantes. Verde: normal; amarillo: menos de la mitad del período; naranja: próxima a vencer (umbral configurable en «Panel de vigencias», 30 días por defecto); rojo: 7 días o menos; vacía: vencida; gris: sin activar. La proporción usa la duración real de cada producto (mensual, anual, bianual…), nunca 365 días supuestos.
- **Menú de acciones** por licencia con solo las válidas según el estado: Ver detalles, Editar, Vender o entregar, Confirmar activación, Renovar, Historial, Enviar información, Anular reserva, Registrar devolución y Anular. Anular y registrar devolución piden motivo y confirmación, y quedan en el historial.
- **Filtros:** búsqueda por cliente, cédula o RUC, código LIC, producto, fabricante, orden, venta o serial exacto (por huella, sin mostrarlo); producto; estado; tipo de fecha (compra, registro, entrega, activación o vencimiento) con desde/hasta; Buscar, Limpiar filtros y **Exportar** (CSV de los filtros o de la selección, sin claves, seriales, usuarios ni contraseñas; queda en la auditoría).
- **Detalle por secciones:** producto (logo, fabricante y características), información comercial (compra, registro, proveedor, factura, costo, cliente, venta y estado del pago), activación y vigencia (entrega, activación real o «Pendiente», vencimiento o «No aplica», días y período), credenciales protegidas (solo administración, cada consulta registrada) e historial con responsable.
- **Fechas reales:** una licencia en inventario ya no puede registrarse ni editarse con fecha de activación; la activación real se registra al entregarla o con «Confirmar activación». Los datos históricos inconsistentes (por ejemplo, licencias disponibles con fecha de activación) se señalan «En revisión» y **no se modifican automáticamente**; al editarlas, administración ve el aviso y, al guardar, el dato se retira y queda en el historial.

## Inventario: revisión, barras premium e iconos (1.5.178)

- **Revisar inconsistencias:** el aviso del inventario abre una ventana con cada licencia afectada, su problema concreto, su estado, sus fechas (compra, registro, entrega, activación y vencimiento registrados) y su historial. La corrección es manual y autorizada: «Retirar activación» (licencia en inventario que figura activada) pide motivo y confirmación y deja en el historial la activación y el vencimiento anteriores, el motivo, la persona y la hora (`retire_activation`, solo administración). Nada se corrige automáticamente.
- **Búsqueda inmediata** por cliente, cédula o RUC, código LIC o producto (sin pulsar Buscar y sin perder el foco); filtros de producto, estado y tipo de fecha sin textos cortados.
- **Vista por cliente** sin la columna «Cliente» (el encabezado ya muestra nombre, identificación y número de licencias, y avisos «por renovar» o «en revisión»).
- **Barra de vigencia premium** (140 × 7 px): se acorta con los días, cambia de color de forma progresiva (verde → amarillo → naranja → rojo), con brillo LED discreto y un punto luminoso en el extremo; junto a ella, porcentaje, días restantes y fecha de vencimiento. Vencida: vacía, «0 % · Vencida». Sin activar no corre la vigencia. Sin animación continua y sin transiciones con movimiento reducido.
- **Acciones con iconos** (Lucide, 16 px, botones de 32 × 32 px y radio de 8 px; 40 px en pantallas táctiles): azul ver detalles, morado enviar información, azul claro editar, verde renovar, rojo anular o registrar devolución (solo si corresponde) y gris «Más opciones» con todas las acciones válidas. El nombre aparece al pasar el cursor o al enfocar.

## Ajustar stock (1.5.178)

En **Productos y catálogo**, junto a «Editar» y «Agregar stock». El inventario no es un contador: son licencias individuales (LIC-…), y las existencias se calculan siempre desde ellas (no hace falta recalcular).

- La ventana muestra el producto, el stock disponible registrado, la cantidad real, la diferencia, el motivo (duplicado, registro incorrecto, clave inválida, devuelta al proveedor, no localizada u otro), observaciones, responsable y la fecha y hora (al confirmar).
- **Disminuir:** hay que elegir exactamente qué licencias disponibles se retiran (código, últimos 4 caracteres de la clave enmascarados, compra, registro, proveedor, factura y vencimiento). Pasan a «Anulada»: no se venden, y sus claves, usuarios, contraseñas e historial se conservan. Cada una registra «Retirada del inventario por ajuste de stock» y el producto un resumen con cantidad anterior y nueva, motivo y responsable.
- **Aumentar:** no se inventan registros; la ventana indica cuántas licencias reales hay que registrar con «Agregar stock».
- Solo administración; pide confirmación; impide cantidades negativas; nunca toca licencias reservadas o entregadas, ventas, pagos ni clientes. Indicadores y catálogo se actualizan al instante (`GET /api/licenses/products/<id>/stock`, `POST /api/licenses/products/adjust`).

## Ventas y Entregas: tarjetas compactas (rama ventas-entregas-pro)

**Ventas.** Cada venta es una tarjeta con número (VLIC-…), cliente, fecha, total, pagado, lo que está por confirmar y el saldo, más las etiquetas de pago (Pagado, Pago parcial, Pendiente de pago, Cancelado) y de entrega (Entregado, Entrega parcial, Pendiente de entrega, Cancelado). «Entrega parcial» es una vista: la venta está entregada, pero alguna licencia se devolvió después. Ese dato no se guarda; se calcula con las unidades. Los productos aparecen en «Ver detalles», que está plegado al principio. Hay una fila por producto con logotipo, cantidad, precio y estado de entrega; si la entrega es parcial, se indica cuántas licencias se entregaron. Los iconos de acción tienen nombre accesible y muestran una etiqueta al pasar el cursor:
- Ver cliente;
- Comprobante;
- Revisar venta;
- Registrar pago, si queda saldo;
- Gestionar entrega.

La búsqueda (número, cliente, cédula o RUC, producto) y los filtros de pago y entrega se combinan entre sí. «+ Nueva venta» permanece visible en la barra superior.

**Entregas.**
- «Licencias reservadas por presupuestos aprobados» solo muestra lo que está pendiente de entrega y viene de un presupuesto. Las ventas independientes vinculadas a una orden se gestionan en Ventas y no se duplican aquí. Cada orden muestra el cliente y el saldo, con una fila por presupuesto y producto: cantidad, fecha de reserva y estado. Las acciones son «Ver presupuesto y orden», «Ver cliente» y «Gestionar entrega». Esta última pide confirmación y, si queda saldo, obliga a aceptarlo de forma expresa. Una orden ya entregada no se puede volver a entregar. Si no hay reservas, aparece un aviso breve con un icono.
- «Historial de entregas» muestra tarjetas con el número de venta (o la orden), el cliente, la fecha y quién entregó, y las licencias agrupadas por producto con su cantidad y las devoluciones. «Ver códigos de licencia» despliega los códigos internos LIC-…, que no son claves. Desde cada tarjeta se abren la tarjeta digital (sin credenciales), un enlace privado nuevo y el «Registro completo»: todos los eventos de la entrega y de sus licencias, con fecha, responsable y detalle (`GET /api/licenses/deliveries/<id>/events`, solo administración).

Nada de esto muestra claves, contraseñas ni credenciales de Microsoft 365. No se borra ni se renumera nada, y no hay migración.

## Tarjeta de Licencias Digitales (rama `licencias-tarjeta`)

**Ventana (administración):**
- Alto máximo del 90 %; encabezado, búsqueda y pie fijos; solo se desplaza la lista.
- Una tarjeta por licencia. Cinco licencias iguales son cinco registros, cada una con su identificador LIC-…, su clave y su cliente. No se fusiona nada.
- Cada tarjeta muestra el logotipo, el nombre completo, el tipo y el método de activación, los dispositivos, la duración, la activación, el vencimiento, los días restantes y el estado.
- **Barra de vigencia:** su largo es proporcional a lo que queda del periodo real (de la activación al vencimiento guardados, así que editar no la reinicia). El color es verde, amarillo (30 días o menos), naranja (15 o menos) o rojo (7 o menos o vencida).
- **Métodos:**
  - **clave de producto:** clave, serial o código de licencia;
  - **cuenta:** usuario y contraseña;
  - **cuenta y clave:** ambos.
  - Solo se muestran los campos guardados, ocultos («••••»). La tarjeta recibe únicamente los *nombres* de los campos (`fields`), nunca sus valores.
- **«Mostrar» y «Copiar»:** consultan la credencial al servidor (`action:'reveal'`, solo administración). Cada consulta queda en el historial de la licencia y en la auditoría, sin el valor. La credencial se oculta sola a los 60 s.
- **Herramientas:** búsqueda por producto, cliente o identificador; filtro por estado; detalles y edición (ficha de la licencia); enviar acceso seguro (enlace privado nuevo por correo); imprimir y PDF público; documento privado.
- **Pie:** PC-DOCTOR S.A., teléfono, correo y sitio web, con el aviso de que las credenciales son personales.

**Documentos:**
- **PDF público** (`GET /api/licenses/deliveries/<id>/card.pdf`): mismos datos sin claves, usuarios ni contraseñas. «Imprimir» imprime esta versión.
- **Documento privado** (`POST …/private-pdf` con `confirm`): solo administración y con una confirmación expresa. Cada licencia registra «Documento privado con credenciales generado por administración».
- **Versión privada del cliente:** sigue siendo su enlace individual, con identificación y código, vencimiento, bloqueo por intentos y revocación al generar uno nuevo.

**Pruebas** (datos ficticios):
- Las pruebas del servidor comprueban siete licencias de un cliente (cinco iguales), sin cruces con otro cliente. Confirman también que ni la tarjeta ni el PDF público (descomprimido) contienen secretos, que el documento privado exige confirmación y queda registrado, y que nada se modifica.
- En el navegador: 17 de 17 comprobaciones en 1366, 1920, 390 y 320 px.

## Inventario y credenciales: método de activación y ADI Duplicate Protection Pro (migración 069, rama `licencias-credenciales`)

**Método de activación por producto:** `license_products.activation_method`.

| Método | Campos | Obligatorios |
|---|---|---|
| Clave de producto o serial | Clave e identificador del fabricante | Clave |
| Usuario y contraseña | Usuario, contraseña e identificador del fabricante | Usuario y contraseña |
| Activación mixta | Clave, usuario, contraseña e identificador del fabricante | Clave, usuario y contraseña |
| Archivo de licencia | Archivo del fabricante e identificador del fabricante | Archivo |

- **Selector:** cuatro tarjetas con iconos Lucide. Solo se muestran, se validan y se envían los campos del método elegido.
- **Cambio de método:** si quedan datos escritos en campos que el nuevo método no usa, se pide confirmación. Lo escrito no se borra del formulario (se recupera volviendo al método anterior), pero no se guarda.
- **Compatibilidad:** los productos anteriores quedan sin método («Según los datos guardados») y funcionan como antes. Al agregar stock se elige su método y queda guardado. Cambiar el método nunca modifica las licencias ya registradas.
- **Archivo de licencia** (tabla `license_files`, una por licencia):
  - Formatos `.lic`, `.key`, `.dat`, `.xml`, `.json`, `.txt`, `.cfg`, `.ini` y `.pdf`, hasta 256 KB.
  - Se rechazan programas, scripts y comprimidos. Los formatos de texto deben ser UTF-8 y los PDF deben ser válidos.
  - Se guarda cifrado con la misma clave que las credenciales, que está fuera de la base. Los listados no lo leen.
  - Administración lo descarga desde el detalle, y la descarga queda en el historial.
  - El cliente lo descarga desde la misma página privada que muestra las credenciales una sola vez.

**Varias licencias por filas:**
- Filas compactas con copiar fila, quitar fila y agregar fila, más «Pegar lista», que convierte líneas en filas.
- Cuenta los registros nuevos y valida cada fila por separado: el error señala la fila y el campo.
- El registro es todo o nada. El formato anterior por líneas se sigue aceptando.

**Protección de duplicados:** se compara siempre en el servidor, por huellas HMAC calculadas con la clave del servidor. Las respuestas y el historial nunca incluyen claves, usuarios ni contraseñas.

| Dato | Nivel | Regla |
|---|---|---|
| Serial o clave | **Rojo** | Normaliza espacios, guiones y mayúsculas. Bloquea siempre, salvo clave compartida con puestos libres (verde). |
| Archivo | **Rojo** | El mismo archivo es la misma licencia. |
| Usuario o correo | **Ámbar** | Una cuenta puede tener varias licencias legítimas. |
| Usuario + contraseña | **Ámbar** | Aviso reforzado. La contraseña registrada no se muestra. |
| Identificador del fabricante | **Ámbar** | Solo si se repite en el mismo producto. |
| Contraseña sola | — | Nunca se marca. |

- **En el formulario:** el aviso aparece debajo de cada campo o fila (gris mientras comprueba, verde, ámbar o rojo), con «Ver registro» del existente.
- **Aviso de ADI:** «Atención: encontré una licencia que podría estar duplicada…», con «Corregir información» y «Cancelar registro». Es solo visual, sin voz.
- **Ámbar:** se puede registrar marcando «Registrar de todas formas», con una justificación de al menos 10 caracteres y una confirmación explícita. Solo administración puede hacerlo. Queda en el historial (`duplicado_autorizado`) con el dato que coincidía, los registros, el usuario, la fecha y el motivo.
- **Rojo:** no se puede saltar.
- **Al guardar se repite la comprobación.** Una repetición dentro de la propia lista responde 400; un conflicto con el inventario, 409.
- **Ediciones:** se comprueban del mismo modo. Lo escrito sustituye a lo guardado y el resto se conserva.

**Entregas:** un serial o archivo ya entregado no se entrega otra vez, salvo clave compartida con puestos libres, tanto en la entrega directa como en las ventas. Autorizar una coincidencia al registrar no permite eludir esta regla. También bloquea los duplicados históricos.

**Revisar duplicados** (Inventario):
- Detecta seriales y archivos repetidos, identificadores del fabricante repetidos, cuentas en productos distintos, entregas en conflicto, posibles errores de stock y credenciales ilegibles.
- Es un informe de solo lectura, sin credenciales, y la consulta queda en la auditoría.

**Pruebas:**
- `test_license_methods.py` (7) y las pruebas de licencias anteriores (40).
- En navegador: 23 comprobaciones de alta, cambio de método, duplicados, filas, ámbar justificado, archivo, informe, teclado y 768, 390 y 320 px. Ventas (27), Entregas (15) y la Tarjeta (17) siguen en verde.
