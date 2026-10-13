# Presupuestos profesionales (rama `presupuestos`, pendiente de aprobación)

Requiere la migración 042 (solo crea tablas nuevas). El presupuesto anterior de cada orden (`order_budget`, `order_budget_lines`) no se modifica al migrar.

## Decisiones tomadas con el administrador (13/10/2026)

- IVA 15 %, configurable; cada ítem indica si lleva IVA o tarifa 0 %.
- Los precios del catálogo y de los ítems **incluyen IVA**; el sistema calcula hacia atrás la base y el impuesto.
- Numeración ligada a la orden: `PCD-20261013-0002-P1`, `-P2`…
- El texto de condiciones enviado por el administrador se usa tal cual. **No ha pasado revisión jurídica conocida.**

## Catálogo

Configuración → Catálogo y presupuestos (solo administración): nombre, descripción, categoría (servicios, licencias, seguridad, repuestos, otros), precio final, si lleva IVA y disponibilidad. No se cargó ningún precio: el catálogo empieza vacío. Cada presupuesto copia descripción y precio de sus ítems, así que cambiar el catálogo no altera los ya emitidos. La tarifa de IVA queda fijada en cada presupuesto al crearlo.

## Presupuesto

- Se crea desde la sección «Presupuesto» del detalle de la orden. Ítems desde el catálogo o como línea libre, con cantidad, precio e IVA; vigencia y observaciones. ADI está disponible en las descripciones y observaciones (no interviene en precios).
- **Estados del presupuesto:** borrador, enviado al cliente, aprobado, parcialmente aprobado, rechazado, modificación solicitada, cancelado. **Estado por ítem:** pendiente, aprobado, rechazado, cancelado.
- Muestra total cotizado, total aprobado e importe rechazado, con el desglose de base e IVA.
- Enviado o decidido ya no se edita: «Nueva versión» crea P2 copiando los ítems, cancela la anterior si seguía abierta y revoca su enlace.
- El técnico prepara borradores; enviar, decidir en nombre del cliente, versionar y cancelar son de administración. Todo queda en el historial del presupuesto (no se puede modificar ni borrar) y en la auditoría.

## Aprobación del cliente

1. «Guardar y enviar al cliente» crea un enlace privado (`/presupuesto/<token>`, 15 días) y lo envía al correo registrado con la firma institucional. Si el correo falla, el enlace se muestra una vez a administración para compartirlo por otro medio.
2. El cliente comprueba su identidad con los últimos cuatro dígitos de su cédula o RUC (seis intentos). Antes de eso no ve importes.
3. Decide **cada servicio** (o «Aprobar todo» / «Rechazar todo»), ve los importes definitivos y las condiciones, escribe su nombre, acepta expresamente y firma en el recuadro. También puede pedir una modificación.
4. Se guarda la evidencia: decisiones, importes, condiciones aceptadas, nombre, fecha, método de verificación, origen y la firma como trazos. Lleva una huella SHA-256 y no se puede modificar ni borrar.

La firma es un trazo manuscrito digitalizado; la página y el PDF dicen expresamente que **no es una firma electrónica certificada**.

Administración puede registrar la decisión cuando el cliente la comunicó por otro medio: exige una nota y queda sin firma del cliente.

## Efecto en la orden

- Lo aprobado pasa al total a cobrar de la orden (de ahí salen el saldo y el bloqueo de entrega con saldo pendiente).
- Si la orden ya tiene pagos por más de lo que se aprobaría, la decisión se rechaza con un aviso.
- **La aprobación no cambia el estado de la orden ni inicia trabajos.** Genera un aviso interno y una entrada en el historial de la orden.

## PDF

`/api/quotes/<id>/pdf` (personal) y enlace del cliente (con la identificación parcialmente oculta): logotipo original, datos del cliente y de la orden, ítems con su decisión, desglose de IVA, condiciones y evidencia con la firma.

## No incluido

- Adjuntar documentos de identidad del cliente.
- Imágenes de los productos y precios reales (los proporcionará el administrador).
- El correo del presupuesto todavía no usa la plantilla institucional común (pendiente junto con el resto de correos).

Pruebas: `local/tests/test_quotes.py` y recorrido completo en navegador (catálogo, borrador, envío, aprobación parcial con firma a 390 px, resumen en la orden, 320 px).
