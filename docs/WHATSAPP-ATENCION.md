# Atención humana real desde WhatsApp · 1.5.321

Código: `local/whatsapp_handoff.py` y `local/whatsapp_adi.py`, más el Centro de Atención (`local/live_support.py`). Migración: `local/migrations/116_whatsapp_handoff.sql`, que solo crea tablas nuevas. Pruebas: `local/tests/test_whatsapp_handoff.py`.

## Qué estaba mal (hasta la 1.5.320)

1. **«ASESOR» no creaba nada.** El mensaje llegaba a la IA, que podía *decir* que transfería al cliente sin que existiera ningún registro.
2. **La respuesta del asesor no salía por WhatsApp.** Se guardaba en el Centro de Atención y solo la veía el chat web.
3. **Los mensajes del cliente se perdían con un asesor activo.** En modo humano se descartaban sin guardarse y el asesor no los veía.
4. **Una solicitud recién creada no figuraba como «esperando».** El último mensaje era la confirmación de ADI y el panel la contaba como ya atendida.
5. **Un error al registrar la solicitud deshacía también la conversación y el control de duplicados.**

## Cómo funciona ahora

- **Pedir un asesor.** Escribir «ASESOR», «HUMANO», «quiero hablar con alguien», «atención personalizada» o similares:
  - crea una **solicitud real** con un código propio (`ATN-AAAAMMDD-NNNN`), una prioridad y un motivo;
  - pasa la conversación a modo humano y ADI deja de responder;
  - la conversación aparece como **esperando** en el Centro de Atención y en las notificaciones del personal.
- **La confirmación es real.** ADI confirma la solicitud con su código **solo después de guardarla**. Si no se puede guardar, lo dice con claridad y no finge la transferencia.
  - Sin la migración 116 aplicada, ADI responde que no puede transferir por ese medio y la IA nunca ve el mensaje.
- **Sin duplicados.** Hay una sola solicitud abierta por conversación (índice único). Los mensajes repetidos solo suben la prioridad.
- **Urgencia.** Hay reglas configurables (`system_state.whatsapp_handoff_rules`):
  - un viaje o la palabra «urgente» pone la prioridad en **urgente**;
  - «no puedo esperar» la pone en **alta**;
  - una **espera larga** o una **queja** crean la solicitud aunque el cliente no pida un asesor.
- **Con el asesor activo.** ADI no responde, pero cada mensaje del cliente **se guarda** para el asesor, y si contiene urgencia sube la prioridad.
- **Lo que hace el personal** en el Centro de Atención:
  - **Tomar:** la solicitud pasa a «En atención» y el cliente recibe «Te atiende … (caso ATN-…)».
  - **Responder:** el texto **sale por WhatsApp**. Si Meta no lo acepta (por ejemplo, porque pasaron más de 24 h desde el último mensaje del cliente), el mensaje queda guardado y marcado «No llegó por WhatsApp», y el asesor ve el motivo.
  - **Transferir:** pasa la conversación a otra persona del personal.
  - **Cerrar o reactivar ADI:** cierra la solicitud y el cliente recibe el aviso de cierre. Su siguiente mensaje lo atiende ADI.
- **Bandeja.** Muestra el canal (WhatsApp o web), el código y la prioridad. Las urgentes aparecen primero.
- **Detalle de la conversación.** Muestra el código, el estado, la prioridad, el tiempo de espera, quién atiende, el motivo y los mensajes que no llegaron.
- **Chat web.** También registra su solicitud de asesor, con el canal «web».

## Consulta de órdenes (verificación de la 1.5.315)

Después de verificar la identidad con el código, ADI muestra:
- el estado y el equipo;
- el **diagnóstico publicado para el cliente**;
- el último avance visible;
- el **presupuesto enviado**, con su estado de aprobación y su total;
- los **repuestos**, cada uno con su etapa;
- la entrega estimada, solo si está registrada;
- la última actualización.

Nunca muestra notas internas, costos ni datos de otros clientes.

Si no hay ninguna actualización publicada, ADI lo dice y ofrece **SOLICITAR**. Eso crea una solicitud para el personal, ligada a la orden verificada.

## Panel de WhatsApp

`GET /api/whatsapp` añade `adi`, con:
- `auto_reply`: si `WHATSAPP_ADI_AUTO_REPLY` está activado;
- `inbound_7d`: los mensajes entrantes de los últimos 7 días, por estado;
- `last_inbound`: la fecha del último mensaje entrante.

No incluye contenido ni números. **Si `auto_reply` es falso, ADI no procesa ningún mensaje de WhatsApp.** Esa es la primera causa a revisar si «las mejoras no aparecen en WhatsApp».

## Seguridad

- Todo se controla en el servidor. Las acciones del Centro de Atención exigen sesión de administración o técnico, y cada una queda en `adi_actions` y en la auditoría.
- Lo que escribe el asesor cuenta en el límite mensual de seguridad de WhatsApp.
- Si las tablas de la 116 no existen, todo lo anterior queda inactivo y nada falla. Hay que aplicar la migración desde **Sistema → Migraciones de la base de datos**.

## Pruebas

`test_whatsapp_handoff.py` usa la API de Meta **simulada** y una base temporal: **no envía ningún mensaje real**. Cubre:

- **Solicitud real:** con su código y visible para el personal.
- **ADI en silencio con el asesor activo:** los mensajes del cliente se conservan y los repetidos no duplican la solicitud.
- **Urgencia:** un viaje la vuelve urgente y una queja crea la solicitud sola.
- **Personal:** tomar, responder por WhatsApp, transferir y cerrar, y que ADI se reactive después.
- **Fallos:**
  - si Meta rechaza la respuesta del asesor, queda registrado y se informa;
  - si falla la base de datos, no hay confirmación falsa.
- **Orden sin diagnóstico publicado:** ADI lo dice y «SOLICITAR» crea la solicitud.
- **Reinicio del proceso:** el estado sobrevive.
- **Sin la migración 116:** nunca se promete una transferencia.
- **Chat web:** también registra su solicitud.

Los escenarios de verificación (orden válida, orden ajena, código vencido, fallo al enviar el código…) están en `test_whatsapp_identity.py`.

## Reversión

1. Revertir con `git revert` los commits de la versión y publicar.
2. Las tablas de la migración 116 pueden quedarse: el código anterior no las usa.
