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
