# Inventario de Licencias Digitales

Módulo «Licencias» del panel (solo administración). Rama de pruebas `licencias-inventario`; **no publicado**.

## Flujo

Compra → registro de la credencial o serial → logo del producto → inventario disponible → presupuesto → aprobación → reserva →
confirmación de pago completo → autorización administrativa → entrega segura → inventario actualizado.

## Modelo de datos (migración 062, solo tablas nuevas)

- **Producto** = elemento del catálogo con categoría «Licencias» o «Antivirus y seguridad». Nombre, precio de venta y logo siguen en el
  catálogo (`catalog_items`, `catalog_images`). `license_products` añade tipo (Microsoft 365, Windows y Office, Antivirus, Otro),
  proveedor, precio de compra, duración y dispositivos. El logo se registra una sola vez y lo reutilizan todas sus licencias.
- **Unidad** (`license_units`): una fila por cuenta o serial, con su estado (Disponible, Reservada, Entregada, Anulada, Vencida),
  datos visibles según el tipo y la credencial **cifrada**. La cantidad disponible se calcula a partir de las unidades.
- **Compra** (`license_batches`): proveedor, costo unitario, fecha y factura de cada registro.
- **Entrega** (`license_deliveries`): confirmación de pago (quién, cuándo, saldo), autorización (quién, cuándo) y enlace privado.
- **Historial** (`license_events`): inmutable; registro, edición, reserva, anulación, pago, autorización, códigos y consultas.

Protecciones en la base: no se borran unidades; una licencia entregada no cambia de estado, cliente, orden ni credencial; una anulada
no vuelve al inventario; una reservada o entregada siempre está ligada a su partida y su orden.

## Seguridad de las credenciales

- Cifrado autenticado con la clave `LICENSE_ENCRYPTION_KEY` (fuera de la base; en el servidor local, `license.key` 0600 en la carpeta
  de datos). Es una clave distinta de la de la verificación en dos pasos. **Antes de publicar** hay que crearla en Vercel como secreto.
- Para evitar duplicados se guarda una huella HMAC del serial o la cuenta (sin espacios ni guiones, sin distinguir mayúsculas). La
  búsqueda por clave usa esa huella: encuentra la licencia sin guardarla ni mostrarla en claro.
- Las credenciales no aparecen en listados, historial, auditoría ni correos. Administración las consulta una a una («Ver credencial»),
  cada consulta queda registrada y la ventana se cierra sola a los 60 segundos.

## Reservas y existencias

- Un presupuesto en borrador no descuenta nada. Al aprobarse (por el cliente o registrado por el personal) se reservan unidades
  concretas: primero las que vencen antes. Las vencidas no se venden.
- Si no hay existencias suficientes, se reserva lo disponible y el resto queda «pendiente de existencias»; al registrar licencias nuevas
  se reservan automáticamente para las ventas que esperaban, por orden de aprobación.
- Ventas simultáneas: la reserva ocurre en la misma transacción de escritura y con condición de estado; una unidad no se vende dos veces.
- «Anular reserva» devuelve la licencia al inventario solo si no fue activada ni entregada.
- Los productos sin configurar en el inventario siguen funcionando en los presupuestos como hasta ahora (sin reservas).

## Pago y entrega

1. **Confirmar pago**: solo administración y solo si la orden no tiene saldo (pagos parciales no bastan). Agrupa las licencias reservadas.
2. **Autorizar entrega**: acción separada de administración. El servidor vuelve a comprobar presupuesto aprobado, pago confirmado y saldo
   cero; marca las licencias como entregadas al cliente y genera un enlace privado válido 72 horas.
3. El cliente abre el enlace, escribe su identificación y recibe un código de 6 dígitos en su correo registrado (10 minutos, un solo
   uso, 5 intentos fallidos bloquean el enlace hasta generar uno nuevo). La respuesta es la misma coincida o no la identificación.
   Antes de mostrar la tarjeta privada se comprueba otra vez que no haya saldo (por ejemplo, tras anular un pago).
4. El correo al cliente lleva solo el enlace, nunca usuarios, contraseñas ni seriales. Sin correo registrado, el código no puede
   enviarse: registrar el correo o entregar en el taller.

## Presupuestos

El botón pasa a llamarse «Agregar producto, servicio o repuesto». El selector muestra servicios, repuestos y licencias con su logo,
precio y existencias disponibles, y permite crear un servicio o repuesto nuevo sin salir del presupuesto (solo administración: queda
registrado en el catálogo).

## Tarjetas

- Versión pública (panel): logo de PC-DOCTOR S.A., logo y nombre del producto, cliente, duración, dispositivos, fechas y contacto
  (+593 98 746 0591 · licencias-orig@ecuadorpcdoctor.com), sin credenciales.
- Versión privada: la que abre el cliente con su enlace, con las credenciales.

## Pendiente antes de publicar

- Visto bueno de administración.
- Crear `LICENSE_ENCRYPTION_KEY` en Vercel (secreto) y excluir `data/license.key` del paquete de cPanel.
- Configurar cada producto (tipo, proveedor, precio de compra) y subir sus logos originales.
