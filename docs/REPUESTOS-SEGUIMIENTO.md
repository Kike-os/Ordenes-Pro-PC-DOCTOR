# Seguimiento de pedidos de repuestos (1.5.238)

Cada orden puede tener varios repuestos. Cada uno lleva sus propias etapas, fechas, evidencias e historial (`order_part_requests` y `order_part_events`, migración 093).

## Etapas y situaciones

- **Etapas:** Solicitado → Confirmado → Preparación → En tránsito → Recibido → Instalación → Finalizado → Listo para entrega.
- **Cómo se avanza:** de una etapa a la siguiente. Saltar o retroceder es una **corrección de administración con motivo**. Una etapa nunca se completa por el paso del tiempo.
- **Situación** (aparte de la etapa): sin novedad, en espera de confirmación, en espera del proveedor, retrasado, incidencia de transporte o cancelado.
  - Requiere motivo y admite una nueva fecha estimada, solo si el proveedor la confirmó.
  - Cancelado es definitivo.
  - Al avanzar de etapa, una espera o un retraso anterior queda resuelto.
- **Colores:** gris pendiente, azul en proceso, amarillo en espera, naranja retraso, verde completado y rojo incidencia o cancelación. El color siempre va con un texto y un icono: ✓ para completado y un punto para la etapa actual.
- **Vencido:** si pasa la fecha estimada sin haberse recibido, se advierte **solo internamente**.

## Datos administrativos

Ninguno es obligatorio salvo el nombre:
- marca, modelo compatible, referencia y cantidad;
- proveedor, línea de compra existente y producto del inventario;
- fecha de compra, llegada estimada y número de pedido;
- transportista, guía y enlace de rastreo (solo https);
- recepción, observaciones internas y técnico responsable.

Cada cambio queda en el historial con el valor anterior.

## Integración sin duplicar

- **Línea de compra:** una línea registrada se asocia a **un solo** pedido de repuesto (índice único). En el selector, las ya asociadas aparecen deshabilitadas con su orden.
- **Sin operaciones automáticas:** cambiar de etapa (incluso a «Recibido») no crea compras, facturas, cobros ni movimientos de inventario. La recepción en inventario y el uso en la orden siguen sus procedimientos. Las series mantienen el control de la 1.5.236.
- **Evidencias:** «Agregar evidencia» abre «Agregar seguimiento» vinculado al repuesto (`order_followups.part_request_id`), con las reglas de la 1.5.237: 10 MB, visibilidad y retiro.

## Cliente

En el enlace público hay un panel «Seguimiento de repuestos».
- **Disposición:** línea horizontal cuando el panel tiene 600 px o más (computadora) y vertical en el teléfono.
- **Lo que muestra:**
  - nombre y marca;
  - etapa, con su fecha por etapa;
  - fechas de solicitud, de llegada estimada (si se registró) y de recepción;
  - última actualización;
  - la situación;
  - los mensajes que el taller **marcó como públicos**.
- **Lo que nunca muestra:** costos, proveedor, número de pedido, compra, guía, transportista, enlaces de rastreo ni observaciones internas.
- **Repuesto oculto:** se puede ocultar un repuesto del enlace.

## Mensajes y notificaciones

- **Plantilla por etapa y situación:** cada una precarga su mensaje en el campo público, que se puede editar. ADI está en modo cliente y la observación interna en modo interno.
- **Guardar y notificar:** abre «Comunicación con el cliente» con el texto para revisarlo. El envío por WhatsApp o correo, su registro y el control de duplicados son los de ese módulo. **Nada se envía automáticamente.**

## Pruebas

- **`test_part_requests.py`:**
  - 8 etapas con fecha, hora y responsable;
  - sin saltos del técnico y corrección de administración con motivo;
  - historial inalterable;
  - 3 repuestos independientes;
  - retraso con nueva fecha, incidencia y cancelación;
  - vencido interno;
  - enlace público sin datos privados;
  - línea de compra sin duplicar y sin movimientos de inventario;
  - cambios de datos en el historial;
  - evidencia vinculada;
  - permisos.
- **Navegador:** 12 comprobaciones (panel, ventanas, colores, notificar, horizontal y vertical, enlace público).

## Diseño «PC-DOCTOR Pro» con vehículo animado (1.5.241)

**Flujo:**
1. `order_part_requests.public()` arma un modelo público, solo con campos permitidos.
2. `order_tracking._parts_section()` lo dibuja.
3. `ticket.css` define colores, disposición y animación.

No hace falta JavaScript. Todo sale de los eventos reales registrados.

| Estado interno | Etapa pública | Vehículo |
|---|---|---|
| solicitado | 1 Solicitud registrada | — |
| confirmado, preparacion | 2 Repuesto confirmado | — |
| transito | 3 En traslado hacia PC-DOCTOR | `transit`: avanza una vez hacia «Recibido»; `stopped` si hay retraso o incidencia, con el tono de la situación |
| recibido | 4 Recibido en el taller | `arrived`: llega, se detiene y muestra la marca ✓ |
| instalacion | 5 Instalación y pruebas | — |
| instalado, listo | 6 Proceso finalizado (completa con «listo») | — |

**Etapas y colores:**
- Las seis etapas siempre se ven.
- El traslado solo se completa si se registró. Si el repuesto llegó sin ese evento (corrección de administración), queda «No registrada» en neutro.
- Sin traslado real no hay vehículo: no se simula movimiento ni se deduce por el tiempo.
- Colores (`--s0`…`--s5` en `.ticket-parts`): azul institucional, azul vivo, turquesa, turquesa verdoso, verde claro y verde intenso.
- Solo las etapas completadas se colorean. La actual tiene un halo y un pulso que se repite tres veces y termina. Las pendientes quedan en `--neutro`.

**Contenido:**
- **Bloque «Estado actual»:** estado, mensaje claro, «N de 6 etapas completadas» con medidor y última actualización.
- **Historial:** cronología del más reciente al más antiguo, con fecha y hora, estado, descripción breve y el mensaje público si existe. Cada punto lleva el color de su etapa o el tono de su novedad.

**Disposición y movimiento:**
- Horizontal desde 440 px de panel. Vertical en el teléfono, con el vehículo junto a la etapa de traslado.
- Animaciones de 0,45 a 1,6 s que se ejecutan una vez.
- Con `prefers-reduced-motion` no hay animaciones y el vehículo queda quieto en su punto real.

**Pruebas:**
- **Unitarias:** 6 etapas; vehículo en tránsito, detenido, llegado y ausente; traslado no registrado.
- **Navegador:** 19 comprobaciones. Incluyen:
  - los 6 estados, un traslado con novedad, un texto largo, con y sin fecha estimada y varios repuestos;
  - alineación de puntos y etiquetas y posición del vehículo;
  - movimiento reducido y anchos de 320 a 1920 px.

## Panel interno Premium (1.5.243)

«Pedidos de repuestos» de la ficha de la orden, con el mismo lenguaje visual del seguimiento público (`orderPartsPanel` en `app.js`, `.opr*` en `app.css`). Las funciones, las ventanas, las validaciones y los datos no cambian.

**Resumen superior** (de los datos guardados): activos, en camino, con novedad, vencidos y recibidos o más.

**Cada repuesto:**
- **Cabecera:** icono, nombre, marca, modelo y referencia, más los avisos (estado, vencido, no visible para el cliente).
- **Estado actual:**
  - la etapa y la situación;
  - la siguiente etapa o la novedad registrada;
  - «N de 8 etapas completadas» con medidor;
  - la última actualización.
- **Línea de 8 etapas internas:** colores `--p0` a `--p7`, de azul a verde, solo en lo completado. La actual tiene halo y pulso, que se repite tres veces y para.
- **Vehículo SVG:** solo con un traslado real registrado. Avanza en «En tránsito», se detiene si hay novedad y llega con ✓ a «Recibido».
- **Bloques con iconos:** proveedor y pedido, transporte (la guía enlaza al rastreo oficial si existe), fechas, taller y observaciones internas. Un bloque solo aparece si tiene datos.
- **Cronología:** cada evento con el color de su etapa o el tono de su novedad. Los cambios de datos aparecen con nombres claros, por ejemplo «Transportista: — → Tramaco».

**Disposición:**
- Horizontal desde 620 px de panel. Vertical en el teléfono, sin vehículo y sin superposiciones.
- Con movimiento reducido no hay animaciones.

**Prueba de navegador:** 16 comprobaciones, de 320 a 1920 px, con movimiento reducido.

## Logistics Pro: envío nacional e internacional (1.5.245)

Cada pedido puede definir su **tipo de envío** (`shipping`): nacional o internacional. También puede llevar país de origen y fecha de despacho; el transportista y la guía ya existían. Destino fijo: PC-DOCTOR · Otavalo, Imbabura (Ecuador). Migración `094_part_logistics.sql`: solo añade columnas vacías a `order_part_requests` (`shipping`, `origin_country`, `dispatch_date`, `logistics`, `incident`) y a `order_part_events` (`logistics`, `incident`).

**Etapas detalladas** (`FLOWS` en `order_part_requests.py`):
- **Internacional (14):** solicitado, confirmado, preparación, despachado en el país de origen, en tránsito internacional, llegada al país de destino, en revisión aduanera, liberado por aduana, en distribución nacional, en ruta hacia Otavalo, recibido, instalación y pruebas, proceso finalizado y listo para entrega.
- **Nacional (10):** solicitado, confirmado, preparación, despachado, en tránsito nacional, en ruta hacia Otavalo, recibido, instalación y pruebas, proceso finalizado y listo para entrega.
- Los pasos de traslado se guardan en `logistics`; la etapa general (`stage`) sigue siendo una de las 8 de siempre (`transito` durante todo el traslado). Así, informes, resumen y seguimiento público no cambian.
- **Reglas:**
  - Solo se avanza al paso siguiente y cada paso deja su evento con fecha y usuario.
  - Saltar o retroceder es una corrección de administración con motivo. Un paso superado sin evento queda «No registrado», nunca como completado.
  - La aduana nunca se marca liberada sin su evento. Si se salta, el estado aduanero dice «Sin registro de liberación aduanera».
  - Despachado registra `dispatch_date` si estaba vacía.
- **Pedidos anteriores** (sin tipo): conservan sus 8 etapas, sus etiquetas y su panel. Al definir el tipo durante el traslado, continúan en «Despachado» del nuevo flujo. Durante el traslado, solo administración puede cambiar el tipo de un envío que ya lo tenía.

**Ruta por fases** del panel interno, con colores de fase solo en lo completado y en lo actual:

| Fase | Color | Pasos |
|---|---|---|
| Pedido | azul | solicitado a despachado |
| Transporte aéreo (solo internacional) | cian | tránsito internacional, llegada al país |
| Aduana (solo internacional) | ámbar | revisión y liberación |
| Distribución nacional | turquesa | distribución, tránsito nacional, ruta hacia Otavalo |
| Recepción | verde claro | recibido |
| Instalación y entrega | verde intenso | instalación, finalizado y listo |

**Vehículo SVG**, siempre según el paso real registrado (`vehicle_mode`):
- **Avión:**
  - estacionado al despachar;
  - vuela durante el tránsito internacional, con estela y un flotado suave;
  - se detiene, en naranja, con una novedad;
  - aterriza al registrarse la llegada al país.
- **En aduana** no hay vehículo; se muestra el estado aduanero.
- **Vehículo terrestre:**
  - aparece en la distribución nacional (o al despachar un envío nacional);
  - se detiene, en naranja, con una novedad;
  - llega con ✓ al recibirse.
- Con `prefers-reduced-motion` no hay animaciones: todo queda en su punto real.

**Incidencias logísticas** (`INCIDENTS`, desde «Novedad o retraso»): retraso de transporte, vuelo retrasado o reprogramado, retención aduanera, documentación pendiente, cambio de transportista, problema de entrega, extraviado y devuelto.
- Cada una se registra con su situación general (tono amarillo, naranja o rojo) y queda en el historial.
- No avanza la etapa. Al avanzar después, la novedad se resuelve.

**Bloque «Envío»:** tipo, país de origen, destino, despacho, estado aduanero y novedad logística.

**Seguimiento público:**
- Mantiene sus 6 etapas.
- El traslado se ve como un solo «En traslado hacia PC-DOCTOR», sin repetirse por cada paso logístico.
- No muestra país, transportista, guía, aduana, avión ni incidencias internas.
- Al avanzar, solo el despacho propone un mensaje al cliente; los pasos de vuelo y aduana no.

**Pruebas:**
- **Unitarias:** `test_part_logistics.py`. Cubren el flujo internacional completo, la aduana sin liberación automática, las incidencias que no avanzan, el flujo nacional, los pedidos anteriores, el permiso del técnico y la ausencia de fugas al público.
- **Navegador:** 22 comprobaciones con datos ficticios, de 320 a 1920 px, con movimiento reducido. La prueba anterior de repuestos (12 comprobaciones) sigue en verde.

## Ruta animada, cancelaciones y avisos (1.5.246)

### Mapa de ruta

Un solo dibujo (`part_route.py`) a partir de un único modelo (`order_part_requests.route_map`), para el panel interno y para el seguimiento público.

| Envío | Puntos | Tramos |
|---|---|---|
| **Internacional** | Origen (el país solo en el panel interno) · Ecuador y aduana · Otavalo · PC-DOCTOR | Vuelo internacional (arco punteado), traslado terrestre y llegada |
| **Nacional** | Despacho · Otavalo · PC-DOCTOR | Traslado terrestre y llegada |

**El vehículo sale solo del paso real registrado.** Nunca se simulan kilómetros, GPS ni avance por el tiempo:

| Paso | Vehículo |
|---|---|
| Despachado | Avión (internacional) o camión (nacional) detenido en el origen |
| Tránsito internacional | Avión en el arco, a mitad del vuelo |
| Llegada al país | Avión aterrizando en Ecuador |
| Revisión aduanera | Sin vehículo; el punto de la aduana se ilumina en ámbar |
| Liberado por aduana | El avión se sustituye por el camión |
| Distribución nacional y ruta hacia Otavalo | Camión en el tramo terrestre |
| Recibido | El camión llega a PC-DOCTOR con ✓ |
| Instalación en adelante | Sin vehículo; el taller queda iluminado |

**Novedades y cancelación:**
- Con una novedad, el vehículo se detiene en naranja.
- Cancelado: sin vehículo y con la ruta atenuada.

**Animación:**
- **Al cargar:** el vehículo recorre una sola vez el trecho desde el paso anterior (`animateMotion`, 1,6 s, curva suave).
- **Tramo activo:** puntos luminosos.
- **Etapa actual:** pulso suave.
- **Etapa completada:** confirmación ✓ al aparecer.

**Rendimiento y accesibilidad:**
- Las animaciones continuas se pausan fuera de pantalla y con la pestaña oculta (`IntersectionObserver` y `pauseAnimations`).
- Con `prefers-reduced-motion`, nada se mueve y el vehículo queda quieto en su punto real.

**Disposición:**
- **Escritorio y tableta:** ruta horizontal en SVG escalable.
- **Teléfono** (contenedor de menos de 560 px): lista vertical compacta, con el vehículo junto a su tramo.

**Pedidos anteriores sin tipo de envío:** conservan su línea de 8 etapas y su vehículo de siempre.

### Seguimiento público

| Envío | Etapas |
|---|---|
| **Internacional** (8) | Solicitud · Confirmado · Envío internacional · Proceso de aduana · Traslado hacia Otavalo · Recibido · Instalación · Finalizado |
| **Nacional** (6) | El traslado se llama «Traslado nacional hacia Otavalo» |
| **Anterior** | Sus 6 etapas de siempre |

**Lo que se publica:**
- la ruta y la aduana;
- cada paso real del traslado, una sola vez.

**Lo que nunca se publica:**
- el país de origen;
- el transportista, la guía y el proveedor;
- costos y notas internas.

**Cancelación en el enlace del cliente:**
- Se ve su estado y su fecha, sin importes ni motivos internos.
- Mientras procede, aparece «Solicitar cancelación de este repuesto».

### Cancelaciones (`part_cancellations.py`)

**Solicitud:**
- La hace el cliente desde su enlace. Comprueba los últimos 4 dígitos de su cédula o RUC y tiene un límite de intentos por enlace y por IP.
- También la puede registrar el personal en nombre del cliente (teléfono, presencial, correo o WhatsApp).
- **Una solicitud nunca anula el pedido.** Queda «solicitada» (o «en revisión») hasta que administración la aprueba o la rechaza con justificación.
- Solo hay una abierta a la vez, y mientras esté abierta no se avanza de etapa.

**Cancelaciones de administración:** proveedor, falta de disponibilidad, problema de importación, pedido duplicado y administrativa. «Novedad → Pedido cancelado» queda reservado a administración y pasa por aquí.

**Reglas según el punto del pedido:**

| Punto | Regla |
|---|---|
| Sin compra | Se puede aprobar de inmediato |
| Comprado | Exige confirmar que se revisaron los compromisos con el proveedor |
| En tránsito, aduana o transporte nacional | Exige la revisión administrativa del envío |
| Recibido o instalado | No se cancela por aquí: corresponde devolución, garantía o reclamo |

**Al aprobar:**
- El pedido queda «Pedido cancelado» (definitivo), con su evento en el historial.
- No se tocan compras, inventario, reservas, ventas, facturas autorizadas (se corrigen con nota de crédito) ni caja. La ventana lo advierte cuando hay algo vinculado.

**Reembolsos:**
- El estado del reembolso va aparte del estado logístico.
- Administración indica el importe a devolver, que no puede superar lo pagado en la orden.
- Cada reembolso es una **devolución real de la orden**: se registra en ese momento (pasa por caja) o se vincula una ya registrada, una sola vez.
- El estado (pendiente, parcial o completado) sale de esas devoluciones. Nada se reembolsa automáticamente.

**Historial:** todo queda en `order_part_log`, que no se modifica ni se borra, y se muestra junto con el historial del repuesto.

### Avisos automáticos al cliente (`part_notices.py`)

**Eventos que generan aviso:**
- confirmado, despachado, llegada a Ecuador, ingreso y liberación de aduana, recibido y listo;
- retraso;
- cancelación solicitada, aprobada o rechazada;
- reembolso.

Los pasos internos menores no generan avisos.

**Reglas:**
- **Un aviso por evento y canal.** Una clave única impide duplicados, aunque se corrija hacia atrás y se vuelva a avanzar.
- **Correo:** solo con un correo válido y si el cliente no pidió dejar de recibir correos.
- **WhatsApp Business:** solo si está configurado con su plantilla aprobada. Hoy no lo está, así que queda «omitido» con el motivo.
- **«Enviado»** significa aceptado por el servidor de correo o por WhatsApp, nunca «entregado».
- **Comunicación de la orden:** cada envío queda registrado allí (`order_messages`).
- **Reintento controlado:** un aviso fallido se reintenta con el botón del pedido o con la tarea diaria, hasta 3 intentos, con el mismo texto.
- **Interruptor:** administración apaga o enciende los avisos desde el panel («Avisos automáticos al cliente»). Están encendidos por omisión.
- **Personal:** en Notificaciones ve las solicitudes de cancelación pendientes y los avisos fallidos.

### Datos y evidencias

- **Nuevos datos del pedido:**
  - transportista nacional y guía nacional;
  - fechas de ingreso y liberación de aduana, que se registran solas con el evento real si están vacías.
- En el internacional, el transportista y la guía se presentan como «Transporte internacional» y «Número de seguimiento».
- Cada evidencia del repuesto queda asociada a la etapa en la que se registró (`order_followups.part_step`) y se cuenta junto a esa etapa.
- **Migración `095_part_cancellations.sql`:**
  - añade columnas vacías;
  - añade las tablas `order_part_cancellations`, `order_part_refunds`, `order_part_log` y `order_part_notices`, protegidas contra borrado.
- **Pedidos existentes:** sin cambios.

### Pruebas

- **`test_part_cancellations.py`:**
  - modelo del mapa por paso;
  - cancelaciones del personal y del cliente;
  - reglas por etapa;
  - permisos y bitácora inalterable;
  - reembolsos con devoluciones reales;
  - avisos únicos, opt-out, fallo con reintento y apagado;
  - evidencias por etapa y datos nuevos.
- **`test_part_logistics.py`:** actualizada a la nueva ruta pública.
- **Navegador:** 27 comprobaciones, de 320 a 1366 px, con movimiento reducido y con el envío real del formulario público.

## Pulido visual, avance común y plazo de cancelación (1.5.247)

### Vehículos sin superposiciones

- **Corrección del error prioritario:** en el envío nacional despachado, el camión aparecía encima del punto de despacho.
- **Margen de seguridad:** cada tramo tiene un margen (`CLEARANCE`, 58 unidades del lienzo). Al estar despachado, el vehículo queda a la derecha del punto de partida. Al llegar, se detiene **antes** del punto de destino, con ✓.
- **Carril propio:** el camión va sobre la línea de ruta (`LANE`); el avión, sobre el arco.
- **Comprobación en el navegador:** se miden las cajas y en ningún paso el vehículo toca un punto de control ni sus textos, ni sale del recuadro.
- **Recorrido inicial:** empieza sin retardo. Aun con las animaciones en pausa fuera de pantalla, el vehículo nunca aparece fuera de su punto.

### Diseño más compacto

**Mapa:** el lienzo del internacional pasa de 190 a 144 de alto (−24 %) y el nacional, que no tiene arco, a 124 (−35 %).

**Panel interno:**
- las etapas logísticas forman una cuadrícula uniforme;
- etiquetas de estado de igual tamaño;
- marca «Interno» en proveedor, transporte y observaciones;
- guías y enlaces que no desbordan;
- acciones ordenadas: «Avanzar» primero y la cancelación al final, en rojo discreto. En el teléfono se muestran en dos columnas.

**Seguimiento público:**
- menos espacio vertical y etiquetas de estado uniformes;
- las 8 etapas internacionales van en dos filas de 4 en anchos intermedios y en una sola fila desde 760 px de panel;
- el estado actual muestra también el paso logístico real, por ejemplo «Envío internacional · En tránsito internacional».

### Un solo avance para las dos vistas

`order_part_requests.progress()` calcula el avance para el panel y para el seguimiento público.
- **Etapas completadas:** solo las que quedaron atrás **y** tienen su evento. Un paso saltado por corrección no cuenta.
- **Datos que devuelve:** el porcentaje de avance y la última actualización, que incluye cancelaciones y reembolsos.
- **Lo que comparten las dos vistas:** el mismo porcentaje y la misma fecha.
- **Contadores:** el público agrupa las etapas, y cada vista muestra un contador que coincide con lo que marca.

### Cancelación: plazo de 24 horas

**Solicitud ordinaria** (del cliente o del personal en su nombre): solo se acepta mientras `hora del servidor < creación del repuesto + 24 h`.
- La comparación se hace en tiempo absoluto (UTC) y el plazo se muestra en hora de Ecuador.
- La API la rechaza fuera de plazo con «Plazo de cancelación vencido…» y no registra nada.

**Botón «Solicitar cancelación»:**
- icono, rojo discreto y tiempo restante con reloj;
- el contador usa la hora del servidor; la del equipo no cuenta;
- al vencer se bloquea solo, sin recargar la página, con candado y una explicación;
- en el enlace del cliente abre una ventana de confirmación que recuerda que **solicitar no es aprobar**.

**Después del plazo:**
- las solicitudes anteriores, su historial y las pendientes siguen visibles y se resuelven con normalidad;
- nada se cancela automáticamente.

**Excepción:** la **Cancelación excepcional** de administración va aparte del botón del cliente. No tiene plazo, exige justificación y queda auditada y notificada al cliente.

### Pruebas

- **Batería:**
  - margen del vehículo en todos los pasos de ambos flujos;
  - avance común;
  - plazo a las 23 h 59 min (se permite) y a las 24 h exactas (se bloquea, sin registro);
  - rechazo por la API y por el enlace público;
  - solicitud pendiente resuelta después del plazo;
  - excepción de administración.
- **Navegador:** 40 comprobaciones de 320 a 1366 px:
  - sin superposiciones;
  - contadores coherentes y el mismo porcentaje en ambas vistas;
  - ventana de confirmación;
  - bloqueo en vivo sin recargar;
  - candado;
  - movimiento reducido.

## 1.5.249 — Una sola fuente de etapas y avance; hitos en la orden

- **Mismas etapas y mismo avance en todas las vistas.**
  - `order_part_requests.stages()` calcula las etapas que ve el cliente:
    - internacional: 8 etapas;
    - nacional: 6 etapas;
    - sin tipo de envío: 6 etapas.
  - `progress()` cuenta sobre esas mismas etapas.
  - El panel del taller, el seguimiento público y la hoja A4 muestran el mismo «X de Y etapas completadas · avance Z %». El porcentaje es completadas / total.
  - Antes, el cliente veía «2 de 8 · 29 %» y el panel «4 de 14 · 29 %».
  - El panel conserva aparte los **pasos logísticos detallados** («4 de 14» y «paso 5 de 14»).
- **Solo cuenta lo registrado.** Una etapa superada por una corrección de administración, sin su evento real, queda **«No registrada»** y no suma al avance. Esto vale para cualquier etapa, no solo para el traslado.
- **Próxima etapa.**
  - El cliente la ve destacada.
  - El panel muestra el siguiente paso operativo y, si es distinta, la próxima etapa que verá el cliente.
- **Fechas diferenciadas** en la vista pública:
  - **Real:** registrada con su evento (solicitud y recepción).
  - **Confirmada:** confirmación del pedido.
  - **Estimada:** disponibilidad prevista por el taller.
  - El tipo de fecha va escrito, no solo indicado con color.
- **Hitos en el historial de la orden.**
  - Quedan registrados como evento de seguimiento, con usuario y fecha:
    - recepción en el taller, con su fecha;
    - inicio de instalación y pruebas;
    - instalación y pruebas finalizadas;
    - proceso finalizado;
    - cancelación aprobada por administración.
  - El estado de la orden no cambia.
  - Un avance rechazado (repetido, fuera de orden o de un pedido cancelado) no deja huella.
- **Sin cambios:** el inventario sigue sin moverse al recibir un repuesto, como hasta ahora. También se mantienen:
  - las reglas de cancelación, con plazo de 24 horas comprobado en el servidor;
  - los avisos, únicos por evento y canal;
  - la protección del enlace público: un repuesto de otra orden responde «no disponible».

## 1.5.250 — Vehículos 3D corporativos (furgoneta y avión de carga)

- **Dibujo:** los mismos componentes de antes (`part_route.van` y `part_route.plane`, usados por el mapa, la lista del teléfono, la línea sin tipo de envío del panel y del cliente, y la hoja A4).
  - Estilo 3D semirrealista en SVG: degradados, brillos, vidrios con reflejo, aros con radios, sombra al suelo.
  - Colores de PC-DOCTOR: blanco y plata con azul marino y rojo.
  - **Furgoneta:** puertas y manijas, espejo, faro y luz trasera, parachoques y luces de emergencia.
  - **Avión de carga en tres cuartos:** fuselaje, ventanillas y compuerta de carga, ala y estabilizador en perspectiva, turbina con toma de aire, cola corporativa y tren de aterrizaje.
- **Logo original:** es el archivo `static/logo-original.png`, insertado tal cual en la carrocería y el fuselaje.
  - Un SVG anidado solo deja fuera su margen transparente y conserva la proporción real del dibujo (2102 × 1596).
  - No se redibuja, no se recolorea ni se deforma.
  - Su tamaño queda limitado por el del vehículo dentro del mapa: unos 20 px en escritorio en la furgoneta y unos 12 px en el avión.
- **Animaciones**, solo del tramo real registrado (no se inventan posiciones ni tiempos), con una duración de 2,4 s una sola vez al cargar:
  - **Furgoneta:** arranque suave, aceleración y frenado progresivo. Las ruedas giran según la distancia recorrida y hay suspensión durante el trayecto. Se detiene y, al llegar a PC-DOCTOR, aparece la confirmación.
  - **Avión:** despega con el tren abajo y lo recoge en el ascenso, con nubes que se desplazan durante el vuelo. Al aterrizar en Ecuador despliega el tren antes de tocar tierra.
  - **Con una novedad:** el vehículo se detiene con un aviso ámbar y luces de emergencia, sin animación.
- **Rendimiento y accesibilidad:**
  - Las animaciones son SMIL y CSS, sin librerías ni recursos externos.
  - Se pausan fuera de pantalla y con la pestaña oculta.
  - Con «reducir movimiento» se ve el vehículo quieto en su punto real.
  - Si el navegador no anima, el dibujo estático sigue mostrando el estado.
- **Separación:** los vehículos son más grandes, así que la distancia mínima a los puntos de control pasa a 68 unidades (furgoneta) y 80 (avión). La posición se interpola exacta sobre el trazo. Ningún vehículo tapa puntos ni textos.
- **Título:** la página del cliente ahora dice «Seguimiento de Reparación».
- **Validación:** se hizo en la vista previa local (mismo código, base temporal con datos ficticios). El entorno Preview de Vercel comparte la base de datos de producción, así que no se usó para no tocar datos reales.
