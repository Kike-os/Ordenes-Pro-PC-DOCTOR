# Autorizaciones según el tipo de equipo

Desde la 1.5.224, la recepción pide solo las autorizaciones que corresponden al **tipo de equipo registrado**, que es el dato estructurado de la orden y no el texto del modelo. Esto rige en el formulario, en el enlace de autorización del cliente, en el comprobante A4 y en el ticket térmico.

Hay tres apartados:
- **Sistema operativo:** acceso al sistema y pruebas con la sesión iniciada.
- **Archivos y respaldos:** archivos específicos y respaldo de información.
- **Formateo, reinstalación y eliminación de datos.**

## Categorías iniciales

| Categoría | Tipos de equipo | Se piden siempre | Solo si el equipo guarda información |
| --- | --- | --- | --- |
| Computadoras | Portátil, Notebook, Gaming, PC de escritorio, Mini PC, All-in-One, Servidor | Los tres | — |
| Tablets y celulares | Tablet, Celular | Los tres | — |
| Discos HDD y SSD | Disco duro (HDD), Unidad SSD | Archivos y respaldos; formateo | — |
| Consolas | Consolas | — | Los tres |
| Impresoras | Impresora | — | Archivos y respaldos; formateo |
| Mouse, teclado y monitor | Mouse, Teclado, Monitor | — | — |
| Equipos de red | Router | — | Archivos y respaldos; formateo |
| Otros equipos | Otro equipo | Los tres | — |

**Tipos nuevos en el catálogo:** Monitor, Mouse, Teclado, Disco duro (HDD) y Unidad SSD.

«Otros equipos» conserva los tres apartados, porque es preferible pedir una decisión que omitirla. Esta categoría no se puede eliminar.

## Estados

Cada apartado tiene uno de estos estados:
- **AUTORIZADO**
- **NO AUTORIZADO**
- **PENDIENTE**
- **NO APLICA**

«No aplica» nunca equivale a una autorización ni a un rechazo:
- no se pregunta;
- no se registra;
- en los documentos aparece en una sola fila.

Si en un apartado que ya no aplica consta una **autorización expresa** (por ejemplo, porque el tipo de equipo se cambió después), esa autorización se sigue mostrando.

## Excepción de datos

Para impresoras multifunción, consolas, routers y otros equipos con memoria, el técnico marca «El equipo guarda información del cliente…» y puede indicar qué guarda. Entonces se piden los apartados de datos de esa categoría.

La excepción queda registrada en la orden con su responsable y su fecha. Si se marca o se retira después, también queda en el historial.

## Cambios de tipo de equipo y permisos nuevos

- Al cambiar el tipo de equipo se recalcula qué aplica. Las decisiones registradas, sus fechas y sus responsables no cambian.
- Un permiso que pase a aplicar queda **PENDIENTE** hasta que el cliente decida.
- La decisión se registra desde la tarjeta «Autorización de acceso técnico» de la orden, con «Registrar decisión del cliente». La decisión nueva se añade a las anteriores; no las reemplaza.

## Comprobantes de órdenes anteriores

Las órdenes registradas antes de la 1.5.224 conservan su comprobante **tal como se emitió**. El PDF es determinista: se genera con la misma huella SHA-256 que el que recibió el cliente por correo.

Si una de esas órdenes muestra autorizaciones que no aplican a su equipo, la tarjeta de la orden ofrece **«Generar comprobante corregido»**. Lo pueden usar administración y los técnicos, y exige un motivo. Al usarlo:
- **No se crea otra orden** y no cambian el número, el cliente, el equipo, las fechas, el estado, las firmas ni las decisiones.
- Queda registrada la **revisión 2**, con su motivo, responsable, fecha y las huellas del comprobante original y del corregido. Queda constancia en el historial de la orden y en la auditoría.
- La versión corregida se identifica de dos formas:
  - lleva el rótulo «COMPROBANTE CORREGIDO · REVISIÓN 2»;
  - el archivo se llama `…-COMPROBANTE-DE-RECEPCION-R2.pdf`.
- El original sigue disponible con «Comprobante original (PDF)» (`receipt.pdf?original=1`) y conserva su huella.

En la base revisada (respaldo del 02/11/2026), solo la orden **PCD-20261102-0012** (impresora Epson L555) tiene este caso. Las demás son computadoras y su comprobante no cambia.

## Composición de los documentos

**Comprobante A4:**
- Las autorizaciones se muestran como un bloque que no se parte entre páginas, con una fila por apartado aplicable y una fila «NO APLICA».
- El resumen de condiciones pone el número y el texto en el mismo renglón, con el mismo tamaño de letra.
- El título de las condiciones completas ya no queda solo al pie de una página.
- Las condiciones completas aceptadas y las Políticas de Reparaciones siguen ocupando sus páginas: son contenido obligatorio y no se reduce la letra para quitarlas.

**Ticket térmico (80 mm, área útil de 72 mm):**
- Para impresoras, periféricos y otros equipos con apartados que no aplican, muestra una línea «No aplica a …» en lugar de los permisos de computadora.
- El ticket de las computadoras no cambia.
- Sigue siendo una página por copia y no imprime descripciones libres ni claves.

## Configuración

En **Configuración → Autorizaciones por equipo** (solo administración) se puede:
- consultar y cambiar los apartados de cada categoría;
- cambiar la excepción de cada categoría;
- asignar cada tipo de equipo a una categoría;
- crear categorías y retirar las que no tengan tipos asignados.

Cada cambio exige un motivo y queda en el historial (`authorization_profile_changes`) y en la auditoría. La configuración rige para lo que se registre en adelante y **no reescribe autorizaciones históricas**.

## Datos

La migración `086_device_authorizations.sql` solo añade lo siguiente:
- las tablas `authorization_profile_changes`, `order_data_exceptions` y `receipt_corrections`;
- la fila `authorization_layout_since` en `system_state`.

No modifica órdenes, consentimientos, firmas ni historial.

## Pruebas

- `local/tests/test_device_authorizations.py`:
  - laptop, impresora, mouse, teclado y monitor, SSD y HDD;
  - orden anterior corregida en la misma orden, con el original idéntico;
  - cambio de categoría sin consentimientos inventados;
  - páginas del comprobante;
  - enlace del cliente;
  - configuración con permisos y registro de cambios.
- **Navegador**, con datos ficticios en una base temporal:
  - recepción por tipo de equipo, excepción de datos y envío sin lo que no aplica;
  - corrección de una orden como la de la Epson L555;
  - configuración y teclado;
  - Escape y movimiento reducido;
  - sin desbordamiento a 1366, 820, 390 y 320 px.
