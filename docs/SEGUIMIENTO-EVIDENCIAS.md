# «Agregar seguimiento» y evidencias de 10 MB (1.5.237)

## Ventana

- **Cabecera:** número de orden, estado y técnico responsable.
- **Secciones numeradas:**
  1. **Información general:** tipo, prioridad, presupuesto relacionado, estado de la orden, responsable, y fecha y hora.
  2. **Información interna del taller:** descripción técnica, diagnóstico y observaciones. Nunca se publica ni se envía.
  3. **Comunicación para el cliente:** mensaje, recomendaciones y el interruptor para publicar en el enlace.
  4. **Evidencias.**
  5. **Próximas acciones:** actividad, fecha prevista, responsable y recordatorio.
- **Contenido:** se desplaza dentro de la ventana. El pie con **Cancelar · Guardar borrador · Guardar · Guardar y notificar** queda siempre visible.
- **Comprobado** sin desbordes a 1920 × 1080, 1366 × 768, 768 × 1024 y 390 × 844.
- **Guardar y notificar** guarda y abre «Comunicación con el cliente» para revisar el mensaje. **Nunca envía nada automáticamente.**
- **Guardar borrador** guarda los textos en el servidor, por usuario y orden, sin evidencias. Al reabrir se ofrece recuperarlo. Desaparece al registrar el seguimiento.
- **ADI:** los campos internos usan el modo interno, que no ofrece «explicar para el cliente». Los del cliente usan el modo cliente.
  - Antes, la descripción interna recibía el modo genérico y ADI podía ofrecer redactarla para el cliente.

## Evidencias

**Formatos y límites:**
- Se aceptan JPG, JPEG, PNG, WEBP y PDF, hasta **10 MiB (10.485.760 bytes)** por archivo.
- El máximo es de 3 archivos por seguimiento. Administración puede cambiarlo de 1 a 10 con `POST /api/followups/settings`.

**Validación:**
- El tipo real se comprueba por los primeros bytes, no por el nombre, primero en el navegador y luego en el servidor.
- El tamaño se comprueba en el navegador, al abrir la carga y al terminarla.

**Por qué se sube en partes:** Vercel no admite más de 4,5 MB por petición.
- El navegador calcula el SHA-256 del original y lo sube en partes de 2,5 MiB, con barra de progreso y hasta 3 reintentos por parte.
- Al terminar, el servidor une las partes de una en una y verifica tamaño, SHA-256 y tipo real. Si algo no coincide, la carga se descarta entera.
- Reenviar una parte no la duplica.
- Una carga que no llega a ser evidencia se limpia a las 24 h. Las partes de una evidencia guardada no se pueden borrar ni modificar (disparadores).

**Calidad:**
- El original no se reduce: se guarda y se recupera con su resolución y su SHA-256.
- La miniatura, de 480 px como máximo, la genera el navegador y se guarda aparte.

**Visor:**
- Abre el original armado por partes.
- Tiene zoom con botones, con Ctrl + rueda y arrastrando. Los PDF se ven integrados o en otra pestaña.

**Después de guardar:**
- La evidencia no se modifica.
- **Mostrar u ocultar al cliente** y **Retirar** (con motivo) quedan en `order_followup_file_changes`, que tampoco se modifica ni se borra.
- La ficha de la orden muestra el estado vigente y quién retiró qué.

**Enlace público y correo:**
- El enlace público muestra solo evidencias visibles y no retiradas.
- `/s/<enlace>/files/<n>` verifica, en cada parte, que la evidencia sea de esa orden, esté visible y no esté retirada. Si no, responde «no disponible», también ante un enlace directo.
- Un correo solo adjunta evidencias visibles y no retiradas.

**Evidencias anteriores** (guardadas enteras, 900 KB): se leen igual que antes.

**Almacenamiento:** en la base, por decisión de administración del 04/11/2026, en lugar de un servicio externo. Con 3 fotos de 10 MB, la base crece hasta unos 40 MB por seguimiento (las partes se guardan en base64).

## Migración 092

Solo añade:
- las tablas `order_uploads`, `order_upload_parts`, `order_followup_file_changes` y `order_followup_drafts`;
- en `order_followup_files`, las columnas `storage`, `upload_id` y `thumb`;
- en `order_followups`, las columnas `observations`, `diagnosis`, `next_owner_id` y `next_reminder`.

## Pruebas

- **`test_followup_evidence.py`:**
  - 900 KB, 5 MB, exactamente 10 MiB y 10 MiB + 1 byte;
  - tipo falso y SHA-256 distinto;
  - original intacto y miniatura aparte;
  - privacidad pública y por API;
  - otra orden;
  - ocultar y retirar;
  - corte de una parte y reintento sin duplicar;
  - límite configurable;
  - borrador;
  - evidencias anteriores;
  - permisos.
- **Navegador:** 19 comprobaciones, entre ellas la carga real de 9 MB y de 10 MiB y el visor del original de 1800 × 1650 px.
