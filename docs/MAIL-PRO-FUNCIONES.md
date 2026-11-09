# Mail Pro: conversaciones, pendientes, etiquetas y ADI (1.5.260)

El código está en `local/mail_features.py`; las rutas, en `local/app.py`.

## Sin responder

- **Qué incluye:** correos de la Bandeja de entrada de los últimos 30 días que el servidor no marca como respondidos.
- **Qué excluye:** los enviados por la propia cuenta y los automáticos (`no-reply`, `mailer-daemon`, avisos de entrega, boletines).
- **Dónde se ve:** en el panel lateral, con su contador, y como filtro «Sin responder». Cada fila muestra cuántos días lleva esperando; desde los 3 días se resalta en ámbar.
- **Cuándo sale de la lista:** al responder desde Mail Pro, que marca el original como respondido, o con el botón «Marcar como respondido».
- **Alcance:** se revisan los 300 mensajes más recientes.

## Conversaciones

- **Cómo se activa:** con el botón «Agrupar por conversación» de la barra de búsqueda. La preferencia se recuerda en el navegador.
- **Cómo agrupa:** por asunto, sin los prefijos «Re:», «RV:», «Fwd:», «AW:», sin las etiquetas entre corchetes y sin distinguir acentos ni mayúsculas.
- **Qué se ve:** cada fila muestra cuántos mensajes tiene la conversación. Al abrirla, el lector la lista y permite ir a cada mensaje.
- **Servidor de correo:** es solo una vista; no cambia nada en él.

## Etiquetas

- **Dónde se guardan:** en la base de datos (migración `097_mail_labels.sql`), por Message-ID. El mensaje conserva sus etiquetas aunque cambie de carpeta.
- **Etiquetas iniciales:** Urgente, Cliente, Proveedor y Facturación.
- **Quién las gestiona:** solo administración puede crear, editar (nombre y color) o eliminar etiquetas.
  - Editar conserva los mensajes asociados.
  - No se permiten nombres repetidos.
  - Eliminar pide confirmación; la etiqueta se quita de los mensajes, pero los correos no cambian.
- **Sección del panel lateral (1.5.264):**
  - encabezado con icono, contador total, «+» para crear y «Editar etiquetas»;
  - se contrae o expande y recuerda el estado en el navegador;
  - lista con desplazamiento propio y nombres que no se recortan.
- **Cómo se usan:**
  - se ponen o quitan desde el lector, con «Etiquetas»;
  - en escritorio se filtra desde el panel lateral;
  - hasta 860 px de ancho, se filtra con las pastillas de la fila de filtros.
- **Son internas:** no se envían a nadie.

## ADI

- **Proponer asunto (redactor):**
  - se basa en el texto del mensaje y la orden indicada;
  - si ADI no está disponible, usa la primera frase, sin agregar nada;
  - el asunto queda escrito y se puede editar.
- **Resumir con ADI (lector):**
  - resume el mensaje o la conversación completa, hasta 8 mensajes, del más antiguo al más reciente;
  - antes de enviar el texto al proveedor oculta correos, teléfonos, identificaciones, credenciales y nombres;
  - el formato es «Resumen», «Puntos clave» y «Pendiente»;
  - sin ADI disponible no hay resumen, para no inventarlo;
  - el resumen no se guarda ni se envía;
  - se avisa si menciona datos que no estaban en los correos.

## Distribución (Mail Pro Premium 3.1, 1.5.264)

- **Escritorio:** los tres paneles usan todo el ancho y llegan al fondo de la ventana, sin desplazamiento horizontal. Columnas: panel izquierdo de 250 a 280 px, lista de unos dos quintos del resto y lector con lo demás.
- **Lista:** se desplaza por su cuenta y conserva la posición al abrir un mensaje y volver, o al actualizar.
- **Tableta:** el panel izquierdo queda contraído.
- **Móvil:** la carpeta, la lista y el lector se muestran por turnos.

## Pruebas

- **Unitarias y de rutas:** `local/tests/test_mail_features.py`, con buzón y ADI simulados.
- **Navegador:** se verifica en 1366, 390 y 320 px con un buzón simulado.
- **Correo:** no se envía ningún correo real.
