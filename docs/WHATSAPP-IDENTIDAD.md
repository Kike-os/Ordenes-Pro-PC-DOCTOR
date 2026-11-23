# Verificación de identidad por WhatsApp antes de que ADI informe sobre una orden · 1.5.315

Conocer el número de orden, el nombre, la cédula o el teléfono **no basta** para recibir información de una orden. ADI solo informa a quien demuestra tener acceso al **teléfono autorizado** de esa orden: el del titular o el de un contacto que administración registró después de comprobar la autorización.

Código: `local/whatsapp_identity.py`. Integración: `local/whatsapp_adi.py`. Migración: `local/migrations/115_whatsapp_identity.sql` (solo crea tablas nuevas). Pruebas: `local/tests/test_whatsapp_identity.py`.

## Flujo

1. El cliente pregunta por su reparación («¿cómo va mi laptop?», «estado de mi orden», un número PCD-…).
2. ADI pide el número de orden.
3. El servidor busca la orden sin revelar ningún dato.
4. ADI ofrece enviar un código al teléfono autorizado mostrando **solo sus dos últimas cifras** (••47) y pregunta si desea recibirlo.
5. El servidor genera un código aleatorio de 6 dígitos con `secrets` y lo envía con la **plantilla de autenticación** aprobada en Meta.
   - El código va siempre al teléfono autorizado. Si quien escribe usa otro número, el código **no llega a ese chat**, y ADI le explica que debe pedírselo al titular.
6. El cliente escribe el código en el chat.
7. El servidor comprueba el código, su vigencia, los intentos y que pertenezca a esa orden y a esa conversación.
8. Con el código correcto se abre una **sesión verificada solo para esa orden**. ADI informa:
   - el estado;
   - el equipo (tipo, marca y modelo);
   - la última actualización;
   - la última observación marcada como visible para el cliente;
   - la entrega estimada.

   ADI nunca informa importes, series, fotos, documentos, enlaces privados ni notas internas.
9. Si la verificación falla, ADI no revela nada del cliente ni del equipo.

Palabras que reconoce el flujo: **SÍ / NO**, **REENVIAR**, **CANCELAR** (también cierra una sesión verificada) y **ASESOR** (personal).

## Reglas de seguridad

| Regla | Valor |
|---|---|
| Código | 6 dígitos, `secrets.randbelow` |
| Vigencia | 5 minutos |
| Intentos por código | 3; después queda bloqueado |
| Uso | Un solo uso; enviar otro anula el anterior |
| Almacenamiento | Solo el HMAC-SHA256 del código, con un valor aleatorio propio y la clave de la aplicación de WhatsApp |
| Sesión | 15 minutos sin actividad; como máximo 60 minutos en total |
| Números de orden consultados | 5 por hora por conversación |
| Envíos de código | 3 por hora por conversación; 3 por hora y 6 por día por orden |
| Verificación a medias | Se descarta a los 30 minutos |

Más reglas:

- **Asociación:** cada código queda ligado a la orden, al destinatario (guardado con HMAC; solo se muestran sus dos últimas cifras), al propósito (`consulta_orden`) y a la conversación.
- **Otra orden con una sesión abierta:** pedir otra orden no da acceso a nada. Hay que verificar esa orden por separado.
- **Números que no existen:** reciben la misma respuesta genérica que una orden sin teléfono autorizado.
- **Cambio de contactos:** si cambia el teléfono del titular o un contacto autorizado, la sesión abierta y los códigos pendientes quedan anulados. Para detectarlo, la sesión guarda una huella de los teléfonos autorizados.
- **Historial de la conversación:** guarda «[código de verificación]» y un resumen neutro en lugar del código y de los datos de la orden. Ese historial se envía al modelo de IA en las preguntas siguientes, así que ni el código ni los datos llegan nunca a OpenAI.
- **Eventos de seguridad** (`wa_identity_events`): se registran sin códigos, sin números completos y sin el texto del cliente.

## Cambio de número

ADI **nunca** cambia un teléfono. Si el cliente dice que cambió de número o que no tiene acceso al registrado, ADI:
- le explica que hace falta comprobar su identidad con el personal (por ejemplo, en el local con su documento y el comprobante);
- registra la solicitud como alerta para administración.

Administración puede:
- actualizar el teléfono del cliente con el procedimiento habitual, o
- agregar un contacto autorizado en la orden, indicando **cómo se comprobó** la autorización y confirmando que se siguió el procedimiento aprobado. Queda registrado quién lo hizo y cuándo.

## Panel en la orden (solo administración)

Tarjeta «Verificación de identidad · WhatsApp», en el detalle de la orden:

- **Estado:** «Verificada ahora», «Sin sesión activa» o «Sin verificar».
- **Avisos de configuración:** si falta configurar WhatsApp o la plantilla del código.
- **Alertas:** código bloqueado, límites alcanzados, solicitud de recuperación de acceso, o varios códigos incorrectos en 24 horas.
- **Datos:** teléfono del titular (solo ••NN), última verificación y reglas vigentes.
- **Contactos autorizados:** con quién y cuándo los agregó o revocó, y cómo se comprobó la autorización. Botones **Agregar contacto** y **Revocar** (pide el motivo).
- **Sesiones de ADI:** activas y terminadas, con el motivo. Botón **Revocar acceso**, que cierra las sesiones y anula los códigos pendientes.
- **Intentos fallidos** y **auditoría** de contactos y accesos.

El servidor comprueba que la persona sea de administración en cada consulta y en cada cambio. Los técnicos reciben «403». Cada acción queda en la auditoría general: `identity_contact_added`, `identity_contact_revoked` e `identity_sessions_revoked`.

## Configuración

1. En WhatsApp Manager, crear una plantilla de categoría **Autenticación**, en español, con el botón **Copiar código**. Por ejemplo, `pcdoctor_codigo`: «*{{1}}* es tu código de verificación. Por tu seguridad, no lo compartas.»
2. En **Configuración → Integraciones → WhatsApp → Plantillas de mensajes**, escribir su nombre en «Plantilla del código de verificación» y su idioma.
3. Las respuestas automáticas de ADI por WhatsApp siguen dependiendo de la variable `WHATSAPP_ADI_AUTO_REPLY=true` en el servidor, que por defecto está apagada.

Sin la plantilla, ADI **no envía códigos ni revela nada**: explica que no puede verificar en ese momento y ofrece un asesor.

Cada código cuenta para el límite mensual de seguridad de WhatsApp (`MAX_MONTHLY_WA_MESSAGES`).

## Pruebas

`local/tests/test_whatsapp_identity.py` usa una base temporal, datos ficticios y la API de Meta **simulada**: no envía ningún mensaje real. Cubre los 13 escenarios obligatorios:

1. Cliente legítimo con el código correcto.
2. Código incorrecto.
3. Código caducado.
4. Reutilización de un código ya usado.
5. Fuerza bruta: bloqueo al tercer intento, y ni el código correcto sirve después.
6. Orden ajena.
7. Número no autorizado: el código va al titular y nunca a ese chat.
8. Cambio del teléfono registrado: la sesión se anula y ADI no cambia el número.
9. Sesión vencida por inactividad.
10. Otra orden durante una sesión válida.
11. Reenvío excesivo, y recorrido de números de orden.
12. Fallo de Meta, y falta de plantilla.
13. Revocación con una sesión abierta.

Además comprueba que:
- el código nunca se guarda en texto plano ni entra en el historial de la IA;
- un contacto autorizado recibe el código en su propio número y, al revocarlo, se cierra su sesión;
- los permisos del panel funcionan como se describe;
- las preguntas no relacionadas siguen llegando a ADI.

Criterio de aceptación: ninguna consulta sin autorización revela información privada ni da acceso a una orden distinta de la verificada.
