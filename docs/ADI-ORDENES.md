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

## ADI Premium Smart Bar 5.0 (1.5.267)

El panel pasa a ser una **barra compacta** de unos 56 px dentro del detalle de la orden:

- Muestra el icono y el nombre de Adi, el **contador** de pendientes y la **recomendación más importante** (título, referencia y valor), con «+N más».
- Al pulsarla (o con Enter) se despliega el cajón con las cinco herramientas (Generar mensaje, Revisar pendientes, Consultar pagos, Ver seguimiento y Preparar informe) y las recomendaciones en **filas compactas**: icono, título, prioridad, descripción breve, referencia real (orden, presupuesto o repuesto), valor registrado y acción. El título de cada fila abre su detalle sin salir de la orden. Escape contrae el cajón y devuelve el foco a la barra.
- **Prioridad:** el rojo queda reservado para lo **crítico verificable**: un repuesto con la fecha estimada vencida o con retraso o incidencia registrados, o un saldo que impide entregar un equipo listo. «Prioridad alta» se muestra en ámbar, «Pendiente» en azul e «Informativa» en gris.
- **Apertura:**
  - La barra empieza contraída, salvo que haya algo crítico.
  - Si la persona la abre o la cierra, esa preferencia se recuerda en su navegador.
  - Nunca se abre sola al actualizarse.
  - Una novedad hace un efecto breve en el contador y el icono y se anuncia a los lectores de pantalla, sin mover la página.
- Transiciones de 180–240 ms; con «reducir movimiento» no hay animaciones.
- Cada recomendación añade `ref`, `value` y `severity` (`critica`, `alta`, `media` o `info`); el panel informa `critical`, la cantidad de críticas. Las huellas no cambian, así que los descartes siguen vigentes.

## ADI Smart Follow-Up 4.0: mensaje de seguimiento (1.5.267)

Ventana «Mensaje de seguimiento» (`statusMessageDialog`, `status_messages.py`):

- **Estado financiero confirmado** al abrir la ventana, sin usar la IA:
  - Valores: total, pagos y anticipos, saldo, saldo a favor y transferencias por confirmar.
  - Fuente: los registros existentes (`equipment.finance` a través de `adi_order.context`). Si la orden tiene varios equipos, se usa el saldo de toda la orden.
  - Nada se calcula a partir del texto.
- **Párrafo de pago:**
  - Lo escribe el sistema con el importe exacto: «Adicionalmente, le informamos que [, considerando los abonos registrados por $X,] su orden registra un saldo pendiente de $Y. Agradecemos su colaboración para completar el pago correspondiente antes del retiro de su equipo.».
  - La IA nunca recibe importes.
  - Se incluye por defecto solo con un saldo pendiente confirmado. Si hay transferencias por confirmar, el operador debe incluirlo expresamente.
  - Si la orden está pagada, tiene saldo a favor o no tiene cargos, el mensaje no menciona cobros.
  - Si los datos financieros no se pueden verificar, aparece el aviso interno «No se pudo verificar el estado financiero de esta orden.» y el mensaje no habla de dinero.
- **Opciones:**
  - Incluir el pago confirmado.
  - Incluir los avances técnicos: diagnóstico, seguimientos comunicables y trabajos realizados.
  - Incluir la fecha de entrega: solo si está registrada, no pasó y el equipo aún no está listo.
  - Tono: profesional (predeterminado), formal o cercano.
- **Reglas por estado:** la IA recibe qué puede decir según el estado real. Por ejemplo, en pruebas no puede decir que el equipo está listo, y en presupuesto ningún trabajo figura como realizado. Las afirmaciones de trabajos sin registro se señalan como avisos.
- **Anotaciones:**
  - Las notas internas de los seguimientos ya no viajan a la IA; la ventana indica cuántas quedaron fuera.
  - El aviso «ADI omitió estos datos de tus anotaciones» ahora solo revisa lo que escribió el técnico. Antes tomaba como anotaciones las cifras de las instrucciones internas, como «Máximo 70 palabras».
  - La revisión de mensajes ya no toma «cuando su equipo esté listo» como si el equipo estuviera listo.
- **Revisión del contexto:**
  - Avisa si falta el diagnóstico y el equipo ya está en reparación o en una etapa posterior.
  - Avisa si la orden figura lista pero tiene repuestos sin instalar o trabajos aprobados sin marcar como realizados.
  - Avisa si la orden espera un repuesto y no hay ninguno registrado.
  - Avisa si el último seguimiento dice «terminado» y el estado no coincide, o si la fecha estimada ya pasó.
  - Avisa de un recordatorio de pago enviado en las últimas 72 horas y de un mensaje al cliente en las últimas 24 horas.
- **Antes de enviar:**
  - `POST /api/orders/<id>/status-message` con `action: "verify"` compara la huella financiera del momento en que se generó el texto y el importe que aparece en el mensaje.
  - Si algo cambió, la ventana pide «Actualizar mensaje».
  - Si todo coincide, pide confirmación y abre la comunicación de la orden con el texto y el canal elegidos. Allí se confirma el destinatario, se envía y se registra el resultado real. Nada se marca como enviado sin la confirmación del servicio.
- **Diseño:**
  - En el encabezado: número de orden, estado técnico y estado de pago.
  - Columna izquierda: información de la orden, comunicación y opciones.
  - Columna derecha: el editor amplio.
  - Las acciones quedan en un pie fijo.
  - En el celular se apila en una sola columna sin desplazamiento horizontal.

Pruebas: `local/tests/test_adi_followup.py` cubre los casos de pago (sin pagos, anticipo, parciales, pagado, sin cargos, no verificable, transferencia por confirmar, saldo que cambia), los estados (diagnóstico, reparación, pruebas, listo), los canales WhatsApp y correo, las anotaciones, las contradicciones y la severidad del Smart Bar.
