# ADI Premium 4.0 en las órdenes (1.5.265)

ADI ayuda a gestionar cada orden con los **datos registrados** en Órdenes Pro.

- **Solo sugiere.** No cambia estados, presupuestos, pagos, saldos ni registros, y no envía mensajes.
- **Las acciones siguen sus flujos de siempre.** Cada acción abre el flujo habitual, con sus permisos y confirmaciones.
- **Quién lo usa:** administración y técnicos. El servidor comprueba los permisos.

## Panel «Adi — Asistencia inteligente»

Está en el detalle de la orden, debajo de las acciones. Muestra las recomendaciones vigentes agrupadas por prioridad:

- **Requiere acción**
- **Pendiente**
- **Informativo**

Cada recomendación lleva:

- un icono;
- el motivo verificable (el dato y la fecha registrados);
- la acción recomendada;
- un acceso directo a su sección.

### Recomendaciones posibles

Solo aparecen las que se pueden justificar con un dato registrado:

- **Diagnóstico pendiente:** la orden está en espera o en diagnóstico sin un diagnóstico registrado.
- **Presupuesto:** en borrador sin enviar, o enviado y sin aprobar. Con un presupuesto sin aprobar, ADI indica que todavía no corresponde decir que la reparación terminó.
- **Cliente pendiente de respuesta.**
- **Repuestos:**
  - sin recepción, con la etapa registrada, la situación y la fecha estimada (si ya pasó, sube a «Requiere acción»);
  - recibido con la instalación pendiente;
  - avance sin aviso enviado al cliente.
- **Reparación pendiente de finalizar.**
- **Saldo pendiente:** total, pagado y saldo.
  - Si el equipo está listo, la entrega requiere registrar el pago.
  - También avisa de transferencias o depósitos por confirmar en Caja.
- **Equipo listo para entrega:** indica si ya se comunicó al cliente.
- **Documentación:** condiciones del servicio sin aceptación registrada (ADI no registra aceptaciones) o fotos de recepción faltantes.

### Descartar recomendaciones

- Solo las **informativas** se pueden descartar, y solo para quien las descarta.
- No se modifica ningún dato operativo.
- Vuelven a aparecer si cambian los datos que las originaron, por su huella. «Mostrar descartadas» las recupera.

### Botones

- **Generar mensaje:** abre el mensaje de seguimiento (ADI con datos depurados, o la plantilla del estado).
- **Revisar pendientes:** vuelve a calcular las recomendaciones.
- **Consultar pagos:** muestra total, pagado y saldo; los movimientos sin anulados y las transferencias por confirmar; y «Preparar recordatorio de pago».
- **Ver seguimiento:** lleva al historial de la orden.
- **Preparar informe:** prepara un informe interno de situación con lo registrado y lo pendiente, sin conclusiones técnicas nuevas.

### Actualización

- El panel se actualiza con la sincronización que ya tiene la orden, sin consultas adicionales.

## Revisión de mensajes

Mientras se escribe un mensaje para el cliente, ADI lo compara con la orden. Funciona en el mensaje de seguimiento con ADI, en el recordatorio de pago y en «Comunicación con el cliente».

**Avisa de posibles errores:**

- dice que el equipo está listo o terminado, pero el estado no lo es;
- un importe no coincide con ningún valor registrado;
- indica que no hay saldo, pero sí lo hay;
- menciona un vencimiento que no existe;
- dice que el repuesto llegó, está en Ecuador o pasó la aduana, pero no está registrado;
- cita otro número de orden.

**Sugiere lo que falta:**

- el presupuesto pendiente;
- el saldo, si el equipo está listo;
- la confirmación que se espera del cliente;
- un texto más breve para WhatsApp;
- evitar signos repetidos.

**Límites:**

- Como mucho 5 observaciones, sin repetir.
- No se guarda nada ni se registra en la auditoría.

## Recordatorio de pago

- **Valores:** usa los valores reales: total, abonado y saldo (con varios equipos, el saldo de toda la orden). Usa la plantilla «Recordatorio de pago».
- **Sin vencimientos:** no menciona vencimientos, porque no hay una fecha de vencimiento registrada.
- **Sin duplicados:** avisa si ya hubo un recordatorio en las últimas 72 horas.
- **Sin registrar nada:** no registra pagos.
- **Envío:** «Continuar en Comunicación» lo abre con la plantilla «pago» para enviarlo por el flujo de siempre.

## Nombres de archivos

- **Fotos de la orden:** el formato y las reglas están en `docs/RECEPCION-TECNICA.md`.
- **Evidencias de seguimientos:** `PCD-…_HP-240-G7_Diagnostico-Tecnico_01.jpg`.
- **Evidencias de repuestos:** `PCD-…_HP-240-G7_Repuesto-03-Pantalla_En-Transito-Internacional_02.jpg`, con la etapa registrada en el seguimiento.
- **Nombre editable:** se puede escribir otro nombre antes de guardar («Guardar como»).
- **Reglas:**
  - lleva la extensión real del archivo;
  - nunca se repite;
  - no admite el nombre del cliente;
  - el nombre original queda como dato interno.
  - El enlace público del cliente no lo muestra.
- **Pedidos de repuestos:** no tienen un número propio (`PED-…`), así que se usa el número real de la orden y el del repuesto.
- **Contenido de las imágenes:** ADI no analiza lo que muestran. No hay una función de análisis autorizada, y ADI no afirma daños a partir de ellas.

## Datos y auditoría

- **Migración `099_adi_premium.sql`:** solo añade dos columnas y una tabla.
  - `original_name` en `order_photos` y en `order_followup_files`;
  - `adi_dismissals`, con las recomendaciones informativas descartadas.
  - No cambia datos existentes.
- **Auditoría:** se registran el descarte y la restauración de recomendaciones, el recordatorio preparado, el informe preparado y el cambio de nombre de una foto.

## Pruebas

- **Unitarias y de rutas:** `local/tests/test_adi_order.py` y `local/tests/test_reception_details.py`, con datos ficticios y base temporal.
- **Navegador:** 1920, 1366, 1024, 768, 390 y 320 px, más teclado y movimiento reducido.
