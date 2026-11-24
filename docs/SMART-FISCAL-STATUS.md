# Premium Invoice View 5.0 · Smart Fiscal Status 5.0 (1.5.328)

## Ventana de factura (`paintInvoice`, estilos `.piv5`)

- **Encabezado:**
  - logotipo original de PC-DOCTOR;
  - nombre comercial, razón social, RUC, matriz, contabilidad y régimen;
  - barra de acciones siempre visible: **Imprimir** (Centro de impresión), **Ticket 80 mm**, **Descargar PDF** (RIDE A4) y **Descargar XML**. Se desactivan hasta emitir la factura.
- **Estado:**
  - indicador de ambiente (Producción o Pruebas);
  - indicador **Smart Fiscal Status**.
- **Tarjeta del comprobante, con acento rosa corporativo:**
  - número y estado SRI **propio de la factura**;
  - emisión, autorización y ambiente;
  - clave de acceso en grupos de 10 dígitos, con botón **Copiar**.
  - Una factura autorizada indica que su autorización se conserva aunque AZUR o el SRI fallen después.
- **Bloques que se mantienen:**
  - comprador (editable en borrador), cuenta para depósitos o transferencias;
  - tabla de productos con importes alineados a la derecha y en cifras tabulares, formas de pago y resumen con el total destacado;
  - cobro, SRI/AZUR, documentos y envíos, e historial.
  - Las acciones de emitir, nota de crédito y anular siguen igual.
- **Producción:** ya no hay aviso amarillo fijo. En el módulo de facturación lo sustituye una franja compacta con el ambiente y el indicador. En **pruebas** se mantiene el aviso de pruebas.

## Smart Fiscal Status (`local/fiscal_status.py`)

| Nivel | Cuándo |
|---|---|
| Verde · Operativo | La última comprobación con AZUR fue correcta, tiene menos de 2 intervalos de antigüedad (mínimo 15 min), respondió en menos de 3 s, no hubo fallos en la última hora y el SRI no figura como no disponible |
| Amarillo · Advertencia | Respuesta lenta, información desactualizada, intermitencia (fallos en la última hora), SRI «no disponible» según AZUR o advertencia de AZUR |
| Rojo · Incidencia crítica | Sin conexión, credencial rechazada (401/403), AZUR no disponible (5xx) o integración sin configurar |
| Gris · Sin verificar | Todavía no hay ninguna comprobación |

- **Comprobación:** es una consulta de **solo lectura**: `GET /secuenciales` de AZUR, la misma prueba de conexión de Configuración. No emite, no envía ni consume secuenciales.
- **Frecuencia:**
  - el servidor permite como mucho una comprobación por minuto;
  - el botón **Actualizar estado** también tiene un límite por usuario;
  - la comprobación automática sigue el intervalo configurado (5, 10, 15, 30 o 60 minutos; por defecto, 10);
  - solo corre mientras la vista está abierta y la pestaña visible.
- **SRI:** no se consulta directamente. Su estado se infiere de las consultas de facturas a AZUR de las últimas 24 horas («SRI no disponible» = estado 11). Sin datos, aparece como «Sin verificar».
- **Datos guardados:** el estado y el historial de incidencias (las últimas 30, incluida la recuperación) se guardan en `system_state`, sin secretos ni migraciones.
- **Independencia:** el estado del sistema es independiente del de cada factura. Una caída no cambia facturas, secuenciales ni registros (está probado).
- **Rutas** (solo administración):
  - `GET /api/invoicing/fiscal-status`: lo último comprobado;
  - `POST /api/invoicing/fiscal-status`, con las acciones `check` e `interval`.

## Pruebas

**Automáticas:** `local/tests/test_fiscal_status.py`, con AZUR simulado y credenciales ficticias. Cubre:

- gris sin comprobación;
- verde solo con una comprobación correcta;
- respuesta lenta;
- credencial rechazada, sin conexión y AZUR caído;
- integración sin configurar, sin llamar a AZUR;
- el verde se pierde si desaparece la configuración;
- límite de una comprobación por minuto;
- información desactualizada e intermitencia, y su recuperación;
- SRI inferido;
- facturas y secuenciales intactos durante una caída;
- rutas e intervalo.

**Visuales:** 1920, 1366, 1024, 768, 390 y 320 px. Las acciones son visibles, nada se sale de los márgenes, no hay desplazamiento horizontal y no hay errores en la consola.
