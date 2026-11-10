# WhatsApp Business (API oficial de Meta) · 1.5.275

## Causa del aviso «WhatsApp Business no está configurado»

El servidor de producción (Vercel) no tenía ninguna variable `WHATSAPP_*`. El código de envío ya existía, pero sin credenciales cada aviso se marcaba «Omitido» antes de intentar el envío.

Además, el diseño anterior tenía tres carencias:
- Usaba una sola plantilla para todo.
- No pedía la autorización del cliente.
- No distinguía errores temporales de permanentes.

La 1.5.275 corrige el diseño. **Los envíos no empiezan hasta que administración cargue las credenciales en el servidor**, porque eso solo se puede hacer desde Meta y Vercel.

## Qué hace ahora

- **Cola propia** (`whatsapp_outbox`), independiente del correo. Tiene 7 estados:
  - **Pendiente:** programado para enviarse.
  - **Enviando:** la solicitud está en curso.
  - **Enviado:** la API de Meta lo aceptó y devolvió su identificador.
  - **Entregado / Leído:** solo cuando Meta lo confirma por el webhook firmado.
  - **Fallido:** error real de envío, con el código de Meta y la solución.
  - **Omitido:** no se envió por una condición identificada (sin autorización, sin celular válido, sin plantilla, aviso repetido o que ya no era cierto).
- **Autorización del cliente.** Sin autorización registrada no se envía nada. Se registra en la orden, en «Avisos al cliente → Registrar respuesta», indicando cómo la dio el cliente y con una confirmación expresa. El registro es inmutable y la decisión vigente es la última de cada número. Las citas usan la casilla marcada al reservar («Autorizo comunicaciones sobre esta cita por correo electrónico o WhatsApp»). Si el cliente escribe **BAJA** o **STOP**, queda registrado su rechazo.
- **Sin duplicados.** Hay una clave única por evento. Antes de enviar, el aviso se reclama con un bloqueo. Un envío interrumpido no se repite solo, porque no se sabe si Meta lo aceptó.
- **Avisos verdaderos.**
  - Los cambios de estado esperan 3 minutos y se comprueba de nuevo que la orden siga en ese estado, para que una corrección rápida no llegue al cliente.
  - Un mismo evento no se repite en 72 h.
  - Registro, diagnóstico, inicio y fin de la reparación y entrega se avisan una sola vez por orden.
- **Reintentos inteligentes.**
  - Los errores temporales (red, servicio no disponible, límites de envío) se reintentan solos a los 2, 10, 30 y 120 minutos, hasta 5 intentos.
  - Los errores permanentes no se reintentan solos: número sin WhatsApp, plantilla inexistente o rechazada, token no válido, falta de autorización.
  - **Reintentar envío** aparece solo cuando procede: errores temporales, plantilla o configuración ya corregida, o un aviso omitido cuya causa se resolvió («Enviar ahora»). Nunca aparece para un número sin WhatsApp ni para un aviso ya enviado.
- **Procesamiento de la cola.** La procesa la actividad del personal (como mucho cada minuto), la tarea diaria y el botón «Procesar cola ahora».
- **El correo no cambia.** PC-DOCTOR Mail Pro sigue con sus reglas, su interruptor y su historial. Las filas «WhatsApp · omitido» registradas antes en los avisos de repuestos y de estado se conservan como historial; desde la 1.5.275, WhatsApp ya no escribe en esas tablas.

## Eventos

**Órdenes.** Variables propias: `{{1}}` nombre del cliente, `{{2}}` número de orden, `{{3}}` equipo.
- Orden registrada
- Diagnóstico en proceso
- Diagnóstico terminado: es manual, porque solo el técnico sabe cuándo terminó. Se envía desde la orden.
- Presupuesto pendiente: solo con un presupuesto realmente enviado.
- Presupuesto aprobado
- Presupuesto rechazado
- Esperando respuesta del cliente
- Espera de repuesto: solo con un pedido activo.
- Revisión por falla recurrente
- Reparación iniciada
- Reparación finalizada
- Listo para entregar
- Entregado
- Recordatorio de entrega: a los 3 y 7 días en «Listo» sin retiro; los plazos se pueden cambiar.

**Repuestos.** Variables propias: `{{1}}` nombre del cliente, `{{2}}` número de orden, `{{3}}` repuesto.
- Solicitado, que corresponde al pedido confirmado
- Enviado
- En Ecuador
- En aduana
- Liberado de aduana
- Recibido en PC-DOCTOR
- Retraso
- Solicitud de cancelación recibida
- Pedido cancelado
- Cancelación no aprobada
- Reembolso

**Citas.** Variables propias: `{{1}}` nombre del cliente, `{{2}}` código de la cita, `{{3}}` fecha y hora.
- Registrada
- Confirmada
- Reprogramada
- Cancelada

**Plantilla general.** Cada evento usa su propia plantilla o, si no tiene, la plantilla general, con `{{1}}` nombre del cliente, `{{2}}` número de orden o de cita y `{{3}}` texto del aviso.

Cada evento se puede desactivar en Configuración → Integraciones.

## Lo que debe configurar administración en Meta

1. **Cuenta y aplicación.** Crear o usar una aplicación de tipo «Empresa» en developers.facebook.com, con el producto **WhatsApp**, vinculada a la cuenta de WhatsApp Business (WABA) de PC-DOCTOR S.A.
2. **Número.** Registrar el número de la empresa en la API de Cloud. Ese número no puede seguir usándose al mismo tiempo en la aplicación WhatsApp Business del teléfono.
3. **Verificación del negocio.** Completarla en Meta Business Suite. Sin ella, la cuenta solo envía a números de prueba (error 131030).
4. **Token permanente.** En Meta Business Suite → Configuración del negocio → Usuarios del sistema, crear un usuario del sistema administrador, asignarle la aplicación y la WABA, y generar un token **sin caducidad** con los permisos `whatsapp_business_messaging` y `whatsapp_business_management`.
5. **Método de pago.** Configurarlo en la WABA. Las plantillas de utilidad tienen costo por conversación según la tarifa de Meta.
6. **Plantillas** de categoría **Utilidad** e idioma **español** en WhatsApp Manager. Como mínimo la plantilla general; por ejemplo, `pcdoctor_aviso_orden`:
   > Hola {{1}}, le escribe PC-DOCTOR S.A. sobre su orden {{2}}: {{3}}. Puede consultar el estado en https://ordenes-pro.ecuadorpcdoctor.com. Responda BAJA si no desea recibir estos avisos.
7. **Webhook.** En la aplicación: WhatsApp → Configuración → Webhook.
   - URL de devolución: `https://ordenes-pro.ecuadorpcdoctor.com/api/public/whatsapp/webhook`
   - Token de verificación: el mismo valor que `WHATSAPP_VERIFY_TOKEN`.
   - Suscribir el campo **messages**, que trae los estados y los mensajes del cliente.

## Variables del servidor (Vercel → Settings → Environment Variables → Production)

| Variable | Contenido |
|---|---|
| `WHATSAPP_TOKEN` | Token permanente del usuario del sistema (secreto). |
| `WHATSAPP_PHONE_NUMBER_ID` | Identificador del número (Phone Number ID). |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | Identificador de la WABA. |
| `WHATSAPP_APP_SECRET` | Clave secreta de la aplicación; valida la firma del webhook (secreto). |
| `WHATSAPP_VERIFY_TOKEN` | Texto largo y aleatorio elegido por administración (secreto). |
| `WHATSAPP_API_VERSION` | Opcional. Por defecto `v26.0`, la versión vigente de Graph API. La `v21.0` que usaba el código anterior se retira el 21/01/2027. |

Después de agregarlas hay que **volver a desplegar**. Los valores nunca se muestran en la interfaz ni en los registros: el panel solo indica «presente / falta» y, de los identificadores, los últimos cuatro dígitos.

## Puesta en marcha recomendada

1. Cargar las variables y volver a desplegar.
2. En Configuración → Integraciones, pulsar **Comprobar conexión**. Se revisan desde el servidor:
   - el token y el número;
   - los permisos;
   - las plantillas;
   - la suscripción de la aplicación;
   - el webhook;
   - que cada plantilla configurada exista, esté aprobada y tenga 3 variables.
3. Escribir las plantillas (general o por evento) y guardarlas.
4. Guardar el **número autorizado para pruebas** y hacer un **envío de prueba**. Por defecto usa `hello_world` en `en_US`, la plantilla que Meta crea en cada cuenta.
5. Comprobar que el webhook marque el mensaje de prueba como Entregado y Leído.
6. Registrar la autorización de los clientes que la den.
7. Activar **Envíos automáticos**, que están apagados por defecto.
8. Revisar el historial de envíos durante los primeros días.

## Seguridad

- Las credenciales solo se leen en el servidor. Las llamadas a Graph API salen del servidor con el token en la cabecera y nunca se registra la respuesta completa.
- El webhook solo acepta avisos con una firma `X-Hub-Signature-256` válida. Los rechazados se cuentan y se muestran en el panel.
- La configuración, la comprobación, el envío de prueba y el historial son solo para administración. La autorización del cliente, el envío manual y el reintento desde la orden son para administración y técnicos. Todas estas acciones quedan en la auditoría.
- Las pruebas automáticas usan una API de Meta simulada y nunca envían mensajes reales.
