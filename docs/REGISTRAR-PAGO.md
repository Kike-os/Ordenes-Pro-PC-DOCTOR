# Registrar pago (1.5.225)

## Por qué no aparecían las cuentas bancarias

El formulario ya leía las cuentas **activas** del catálogo central (`bank_accounts`, Facturación → Cuentas bancarias), pero en producción
ese catálogo estaba **vacío**: el registro de cuentas había quedado en pausa. Ahora:

- la ventana lo explica («No hay cuentas bancarias activas registradas…») y no deja registrar una transferencia o un depósito sin cuenta
  receptora; administración ve el botón «Abrir Cuentas bancarias»;
- las cinco cuentas de la empresa se registran en producción con el guion `cuentas_225.py`, solo después de autorizar la publicación.
  Usa el mismo módulo que la pantalla de cuentas (`banking.save`): mismas validaciones e historial, y no duplica una cuenta que ya exista
  (mismo banco y número). Quedan «sin verificar» hasta que administración las confirme con su documentación; se pueden usar para cobrar.

No hay una base bancaria aparte: órdenes, ventas, proformas, facturación, abonos, Caja, el historial de pagos y los reportes usan el mismo
catálogo y las mismas transferencias por conciliar.

## La ventana

- Encabezado con el logotipo original de PC-DOCTOR, el número de orden, el cliente y el **saldo pendiente** (cambia con «Aplicar a»).
- Tipo (pago completo o abono), monto y **formas de pago con icono** (efectivo, transferencia, depósito, tarjetas, cheque, otro y pago mixto),
  que se recorren con las flechas del teclado.
- Transferencia o depósito: **banco con su logotipo** (archivos en `local/static/bancos`, procedencia en su README; un banco sin archivo se
  muestra con sus iniciales), **cuentas de ese banco** con tipo, número y titular, referencia y **comprobante bancario** opcional (JPG, PNG o
  PDF, hasta 5 MB).
- Fecha y hora del pago, observaciones y responsable del registro. Ventana de 760 px, de una columna en el teléfono, sin desplazamiento
  horizontal.

## Reglas que se mantienen

- No se registra un pago mayor que el saldo pendiente; un pago completo toma exactamente el saldo.
- Pago mixto: hasta cinco formas de pago que deben sumar el monto; la transferencia o el depósito de un pago mixto también admite comprobante.
- **Doble clic o reintento**: la misma solicitud devuelve el pago ya registrado («Este pago ya estaba registrado»). Antes, una transferencia
  reenviada respondía «Esa referencia ya está registrada»: no duplicaba, pero confundía; ahora se reconoce primero la solicitud.
- Cada transferencia o depósito queda **pendiente de verificar** en Caja → transferencias: un comprobante no es dinero recibido.
- Se guardan fecha y hora, responsable, monto, método, banco, cuenta receptora, referencia y el comprobante (archivo central
  `payment_files`, enlazado a la transferencia). En el historial de pagos de la orden, administración ve «Comprobante».

## Pruebas

- `local/tests/test_payment_proof.py`: cuentas en la orden, transferencia con comprobante y su descarga, doble envío, pago por encima del
  saldo, pago mixto con depósito y comprobante, permisos.
- Navegador con datos ficticios (nombres reales de los cuatro bancos y números ficticios): sin cuentas, logotipo correcto por banco,
  filtro de cuentas, abono por transferencia con comprobante, pago completo en efectivo, teclado y Escape, 820, 390 y 320 px.
