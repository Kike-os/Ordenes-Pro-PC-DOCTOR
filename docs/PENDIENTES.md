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
- [x] Fase 4: ADI Smart Collections (centro de cartera), expediente económico del cliente, marcas de gestión y estados de cuenta en A4 y 80 mm (1.5.330, migración 121).
- [x] Fase 5: auditoría de comunicaciones, equipos pendientes de retiro (alertas a los 30, 60, 85 y 90 días) y propuestas de seguimiento por eventos, sin envío automático (1.5.330).
- [ ] **[Administración]** Aprobar las reglas de seguimiento antes de cualquier campaña automática. No está autorizado.
- [ ] Enlace público seguro del estado de cuenta para el cliente: queda dentro del portal seguro con QR del Premium Billing Center.
- [ ] **[Administración]** Validación jurídica, contable y tributaria antes de cualquier aplicación real de intereses. No está autorizada.

## ADI Smart Collections 3.1 (1.5.332)

- [x] Estados financieros verificables, pago al retirar frente a cartera vencida, conciliación precisa, reclamos, tabla y expediente con pestañas (docs/ADI-CARTERA-3.1.md).

## Database Guardian Pro 1.0 (1.5.331)

- [x] Migraciones verificadas con evidencia, libro, bloqueo, recuperación segura, monitor y control previo a publicar (docs/DATABASE-GUARDIAN.md).
- [ ] **[Administración]** Revisar en Vercel que las vistas previas no usen la base de producción.

## ADI Live Support Center 4.0

- [x] Cierre automático a los 8 minutos en el servidor, bandeja con filtros, contador, pausa, notas internas y configuración con simulación (1.5.333, migración 123).
- [ ] **[Administración]** Activar el cierre automático en producción después de revisar la simulación.
- [ ] **[Administración]** Si se quieren avisos proactivos por WhatsApp al minuto 7: autorizar un programador externo por minuto (`/api/cron/live-support`).

## Premium Billing Center 4.0

- [x] Centro de impresión (1.5.323 a 1.5.326).
- [x] Reportes y exportación: indicadores anuales, notas de crédito, facturado frente a cobrado, filtro por forma de pago, y Excel, CSV y PDF (docs/FACTURACION-REPORTES.md).
- [ ] Otros comprobantes: recibo de pago, anticipo, entrega y nota de crédito, en A4 y térmico.
- [ ] Portal seguro de consulta con QR y permisos independientes por acción.

## Otros pendientes de administración

- [ ] **[Administración]** Confirmar con el contador que el SRI acepta en el ticket el código de barras de la clave de acceso dividido en partes.
- [ ] **[Administración]** Crear en Meta la plantilla de autenticación de WhatsApp (p. ej., `pcdoctor_codigo`) y configurarla en Integraciones.
- [x] **[Administración]** Contraseña de `admin-red`: administración decidió conservarla (24/11/2026). Recomendación: revisar periódicamente sus inicios de sesión.
- [ ] **[Administración]** Pulsar «Obtener RIDE de AZUR» en las facturas 276 y 277.
