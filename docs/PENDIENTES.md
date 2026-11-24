# Pendientes del proyecto (listado persistente)

Cada tarea se marca como hecha solo con evidencia: archivos, pruebas y verificación. Lo que depende de una persona o de una prueba física se
indica como **[Administración]** o **[Prueba física]**.

## PC-DOCTOR — Premium Invoice View 5.0 · Smart Fiscal Status (1.5.328)

Las dos imágenes de referencia **no llegaron** en el mensaje. El diseño se hizo a partir del texto de la orden. Cuando se reciban, se debe
comparar el diseño con ellas.

- [x] **Ventana de factura rediseñada:**
  - logotipo original;
  - encabezado con datos tributarios del emisor;
  - botones Imprimir, Ticket 80 mm, Descargar PDF y Descargar XML;
  - indicador de ambiente;
  - tarjeta con acento rosa: número, estado SRI, fechas y clave de acceso con botón Copiar;
  - comprador, cuenta para depósitos, tabla de productos, formas de pago y total destacado.
- [x] **Monitor Smart Fiscal Status:**
  - AZUR API, servicios del SRI (inferido de AZUR) y autenticación;
  - tiempo de respuesta, última comprobación y última conexión satisfactoria;
  - motivo y estado de la factura;
  - botones Actualizar estado y Ver detalles;
  - historial de incidencias e intervalo configurable.
- [x] **Cuatro estados dinámicos** (verde, amarillo, rojo y gris), con transiciones suaves. Nunca se muestra verde sin una comprobación satisfactoria. Se quitó el aviso amarillo fijo de producción.
- [x] **Conectividad comprobada con consultas seguras:** GET /secuenciales de solo lectura, como máximo una por minuto (`test_fiscal_status.py`).
- [x] **Márgenes de impresión térmica:** 80 mm con contenido de 68 mm (1.5.326).
- [x] **Tamaños de letra del ticket:** 8, 7,5, 8,5, 10, 9 y 12 pt (1.5.326).
- [x] **Impresión A4 y 80 mm, y descarga de PDF y XML:** validadas con datos ficticios. El ticket real 001-010-000000277 se verificó en producción (dos códigos de barras y QR legibles).
- [ ] **[Prueba física]** Imprimir la muestra de calibración en la Epson TM-m30 y medir los márgenes reales.
- [x] **Diseño adaptable:** revisado en 1920, 1366, 1024, 768, 390 y 320 px, sin desbordamiento ni errores.
- [x] **Secuenciales intactos:** prueba automática; en producción el último sigue siendo 277.
- [x] **Pruebas funcionales y capturas.**
- [x] **Versión publicada y verificada en producción.**

## ADI Enterprise AI 3.0

- [x] Fase 1: análisis integral, mensajes por motivo, control previo y retrasos (1.5.326).
- [x] Fase 2: compromisos de pago (1.5.327, migración 119 aplicada).
- [x] Fase 3: tasas legales y simulador de intereses, **solo simulación** (1.5.327, migración 120 aplicada).
- [ ] **[Administración]** Registrar y validar las tasas oficiales del BCE: dos personas distintas, una registra y otra valida.
- [ ] Fase 4: ADI Smart Collections (centro de cartera), expediente económico del cliente y estados de cuenta (A4, 80 mm y vista segura).
- [ ] Fase 5: auditoría de comunicaciones, equipos pendientes de retiro (alertas a los 30, 60, 85 y 90 días) y reglas de seguimiento por eventos. Las campañas automáticas necesitan una aprobación aparte.
- [ ] **[Administración]** Validación jurídica, contable y tributaria antes de cualquier aplicación real de intereses. No está autorizada.

## Premium Billing Center 4.0

- [x] Centro de impresión (1.5.323 a 1.5.326).
- [ ] Reportes y exportación: indicadores anuales, notas de crédito, facturado frente a cobrado, filtro por forma de pago, y Excel, CSV y PDF.
- [ ] Otros comprobantes: recibo de pago, anticipo, entrega y nota de crédito, en A4 y térmico.
- [ ] Portal seguro de consulta con QR y permisos independientes por acción.

## Otros pendientes de administración

- [ ] **[Administración]** Confirmar con el contador que el SRI acepta en el ticket el código de barras de la clave de acceso dividido en partes.
- [ ] **[Administración]** Crear en Meta la plantilla de autenticación de WhatsApp (p. ej., `pcdoctor_codigo`) y configurarla en Integraciones.
- [ ] **[Administración]** Cambiar la contraseña de `admin-red`, que se compartió en el chat.
- [ ] **[Administración]** Pulsar «Obtener RIDE de AZUR» en las facturas 276 y 277.
