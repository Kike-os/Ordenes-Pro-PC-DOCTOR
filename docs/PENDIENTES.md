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
- [x] Estado de cuenta del cliente disponible en el portal seguro con QR (docs/PORTAL-CLIENTE.md).
- [ ] **[Administración]** Validación jurídica, contable y tributaria antes de cualquier aplicación real de intereses. No está autorizada.

## ADI Smart Collections 3.1 (1.5.332)

- [x] Estados financieros verificables, pago al retirar frente a cartera vencida, conciliación precisa, reclamos, tabla y expediente con pestañas (docs/ADI-CARTERA-3.1.md).

## Database Guardian Pro 1.0 (1.5.331)

- [x] Migraciones verificadas con evidencia, libro, bloqueo, recuperación segura, monitor y control previo a publicar (docs/DATABASE-GUARDIAN.md).
- [ ] **[Administración]** Revisar en Vercel que las vistas previas no usen la base de producción.

## ADI Live Support Center 4.0

- [x] Cierre automático a los 8 minutos en el servidor, bandeja con filtros, contador, pausa, notas internas y configuración con simulación (1.5.333, migración 123).
- [x] **[Administración]** Cierre automático activado en producción el 24/11/2026 tras la simulación (5 conversaciones antiguas cerradas en silencio).
- [ ] **[Administración]** Si se quieren avisos proactivos por WhatsApp al minuto 7: autorizar un programador externo por minuto (`/api/cron/live-support`).

## WhatsApp: límite mensual (1.5.337)

- [x] Causa de «ADI no responde» el 24/11/2026: se llegó al límite de seguridad de 100 respuestas automáticas al mes y los mensajes siguientes quedaban «omitidos», fuera del panel. Ahora el mensaje se guarda y pasa a «Esperan asesor» con prioridad alta.
- [x] Límites subidos por decisión de administración: 300 respuestas de ADI y 500 envíos de WhatsApp al mes.
- [x] Los 11 mensajes omitidos (2 clientes) se pasaron al personal el 24/11/2026 (ATN-20261124-0001 y 0002); su texto no se había guardado.

## Premium Billing Center 4.0

- [x] Centro de impresión (1.5.323 a 1.5.326).
- [x] Reportes y exportación: indicadores anuales, notas de crédito, facturado frente a cobrado, filtro por forma de pago, y Excel, CSV y PDF (docs/FACTURACION-REPORTES.md).
- [x] Otros comprobantes: recibo de pago (A5 y térmico, con QR seguro y factura vinculada), anticipo y entrega (docs/COMPROBANTES.md).
- [ ] Nota de crédito en A4 y térmico: pendiente junto con el envío de notas de crédito al SRI (requiere autorización y revisión contable).
- [x] Portal seguro de consulta con QR y permisos por acción del portal (docs/PORTAL-CLIENTE.md).
- [ ] Permisos independientes por acción para el PERSONAL en Facturación (ver, imprimir, descargar, enviar, reportes).

## Otros pendientes de administración

- [ ] **[Administración]** Desde 1.5.343 el ticket muestra la clave de acceso en un QR (más la clave legible) en lugar de dos códigos de barras. Confirmar con el contador; si exigiera código de barras, se vuelve al formato anterior (KEY_FORMAT='barras' en invoice_ticket.py). El RIDE A4 de AZUR no cambia.
- [x] Plantilla de autenticación `pcdoctor_codigo` creada en Meta el 24/11/2026 desde Integraciones (1.5.341), aprobada al instante y conectada a los códigos de verificación.
- [x] **[Administración]** Contraseña de `admin-red`: administración decidió conservarla (24/11/2026). Recomendación: revisar periódicamente sus inicios de sesión.
- [ ] **[Administración]** Pulsar «Obtener RIDE de AZUR» en las facturas 276 y 277.
