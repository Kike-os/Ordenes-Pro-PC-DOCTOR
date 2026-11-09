# Seguimiento de reparación en 6 etapas (1.5.252)

## Etapas e iconos

| Etapa | Icono (Lucide, ISC) |
|---|---|
| Recepción | ClipboardCheck |
| Diagnóstico | ScanSearch |
| Reparación | Wrench |
| Pruebas técnicas | ShieldCheck |
| Listo para retirar | PackageCheck |
| Entregado | Handshake |

- **Colores:** verde = completado; azul eléctrico = en curso; ámbar = en espera (presupuesto, respuesta del cliente, repuesto o falla recurrente); gris = pendiente. El estado siempre va escrito: «Completado», «En curso», «En espera», «Pendiente».
- **Fecha y hora:** cada etapa muestra la de su registro real.

## Una sola fuente (`repair_stages.py`)

- **Dónde se usa:** el panel (detalle de la orden), el seguimiento público y la hoja A4 muestran las mismas etapas, calculadas en el servidor.
- **Estados sin cambios:** los estados de la base de datos no cambian; se mapean así:
  - En espera → **Recepción**.
  - Procesando, Esperando respuesta, Aprobación de presupuesto o Revisión por falla recurrente → de **Diagnóstico** a **Pruebas técnicas**, según el último seguimiento técnico registrado:
    - diagnóstico → Diagnóstico;
    - reparación, novedad, repuesto o presupuesto aprobado → Reparación;
    - pruebas de funcionamiento → Pruebas técnicas;
    - sin seguimiento técnico, la orden en proceso está en Diagnóstico.
  - Listo para entregar o En espera de entrega → **Listo para retirar**.
  - Entregado → **todo completo**.
- **Sin avances falsos:**
  - Nada avanza por el paso del tiempo.
  - Un seguimiento que dice más de lo que permite el estado (por ejemplo «servicio finalizado» con la orden aún en proceso) no adelanta nada: manda el estado.
- **Estados especiales:**
  - **Presupuesto pendiente:** la etapa queda en ámbar, con alerta, y la reparación no se marca completada.
  - **Esperando respuesta:** alerta ámbar.
  - **Repuesto en camino:** alerta ámbar «Esperando repuesto», con su seguimiento visible debajo.
  - **Falla recurrente:** alerta ámbar destacada; la etapa operativa vuelve a Diagnóstico y solo cuentan los seguimientos posteriores. El historial anterior se conserva.
- **Privacidad:** el cliente nunca ve notas internas, solo la etapa, su estado y su fecha.

## Actualización automática

- **Cliente:**
  - Cada 30 s, con la pestaña visible, la página consulta solo una huella opaca del estado (`/s/<token>/estado`, sin datos de la orden). Si cambió, se recarga sola.
  - No recarga mientras la persona escribe o tiene una ventana abierta.
  - Ante errores espacia las consultas.
  - Sin JavaScript, se recarga cada 3 minutos.
- **Panel:**
  - Cada 30 s, el detalle de la orden compara la huella (`/api/orders/<id>/stages`). Si cambió, redibuja la barra y el estado sin recargar la página.
- **Qué cambia la huella:** solo un cambio registrado (estado, seguimientos, repuestos o historial).

## Diseño

- **Pantallas grandes:** barra horizontal con conectores que avanzan, pulso ligero y finito en la etapa activa, y confirmación ✓ al completar. Transiciones de 300 ms.
- **Pantallas pequeñas** (menos de 560 px de tarjeta): solo iconos y, debajo, la etapa actual y la siguiente escritas; sin desbordes ni textos encimados.
- **Movimiento reducido:** con «reducir movimiento», sin animaciones.
- **Tarjetas:** equipo, fecha de ingreso, última actualización, estado actual y novedades públicas.
- **Hoja A4:** las mismas 6 etapas, con su estado escrito y su fecha.

## Pruebas

- **Unitarias:** `tests/test_repair_stages.py`, con los 12 casos de aceptación:
  - orden recibida, en diagnóstico, en reparación, esperando presupuesto, esperando repuesto, en pruebas, lista, entregada y con falla recurrente;
  - que no haya avance por tiempo;
  - la huella de sincronización;
  - que pantalla, panel y A4 coincidan, sin notas internas.
- **Navegador:** 30 comprobaciones con datos ficticios:
  - cada estado en el cliente y en el panel;
  - sincronización automática en ambos;
  - de 320 a 1920 px;
  - movimiento reducido;
  - hoja A4;
  - ausencia de errores de consola.

## 1.5.254 — Resumen y avisos con acabado profesional

- **Resumen bajo la barra:**
  - **Etapa actual:** con su icono, su nombre y una etiqueta «En curso», «En espera» o «Proceso completado».
  - **Siguiente etapa:** con su icono y una flecha que la une a la actual.
  - **Avance:** «X de 6 etapas», con un medidor.
  - **Disposición:** en anchos medianos se acomoda en dos columnas y en el teléfono se apila; sin desbordes.
- **Avisos en tarjeta:** icono propio de cada caso, título, explicación y una etiqueta neutral, que también lee el cliente:
  - falla recurrente: «En revisión»;
  - presupuesto: «Pendiente de aprobación»;
  - respuesta del cliente: «Respuesta pendiente»;
  - repuesto: «En camino».
- **Mismo marcado** en el panel y en el seguimiento del cliente. Los datos y la lógica de las etapas no cambian.

## 1.5.255 — Barra única de avisos

- **Qué reemplaza:** las tarjetas de aviso, que ocupaban varias filas, pasan a ser una sola barra horizontal de 34–36 px, debajo del resumen de la etapa actual. Ejemplo: `🔔 Avisos (2) | ⏱ Presupuesto pendiente | 📦 Repuesto en camino` (iconos de Lucide).
- **Presupuesto:** muestra el estado real de la versión vigente.

  | Estado | Color |
  |---|---|
  | Pendiente | ámbar |
  | Aprobado | verde |
  | Aprobado parcialmente | violeta |
  | Rechazado | rojo |
  | En revisión | ámbar |

  Si la orden está en «Aprobación de presupuesto» y no hay presupuesto registrado, aparece «Presupuesto pendiente».
- **Estados especiales:** «Respuesta pendiente» y «Falla recurrente», en ámbar.
- **Repuestos:** cada pedido con su paso real.

  | Paso | Color e icono |
  |---|---|
  | Solicitud registrada | azul |
  | Esperando despacho | ámbar |
  | En tránsito internacional | celeste, avión |
  | En tránsito nacional | azul, camión |
  | En aduana de Ecuador | naranja |
  | En camino a Otavalo | azul, camión |
  | Repuesto recibido | verde |
  | Instalación en proceso | violeta |
  | Pedido cancelado | rojo; estado alternativo, no forma parte de la progresión |

  Con retraso o con novedad, en naranja y escrito. Un repuesto ya instalado deja de avisarse.
- **Varios repuestos:** se agrupan en «Repuestos (N)», que abre la lista con el estado de cada uno y acceso individual a su seguimiento.
- **Acciones:**
  - En el panel, «Presupuesto» abre el presupuesto real de la orden, con el flujo de aprobación de siempre; nada se modifica.
  - En el panel, un repuesto lleva a su tarjeta de seguimiento y la resalta.
  - En la página del cliente, un repuesto lleva a su tarjeta. El presupuesto interno no se abre: el cliente lo recibe por su propio enlace.
- **Orden de prioridad:** rojo, naranja, ámbar, violeta, celeste, azul y verde. Sin avisos activos, la barra no aparece y no deja espacio vacío.
- **Teléfonos** (contenedor de menos de 560 px): un botón «Avisos (N)» de 40 px abre un panel compacto. Escape o un toque fuera lo cierran, sin desplazamiento horizontal.
- **Actualización:** usa la sincronización existente (la huella de 30 s); no agrega consultas. La línea de etapas no se mueve al actualizarse.
- **Fuente:** `repair_stages.notices` (servidor). El cliente solo ve repuestos públicos, con su nombre depurado.

## Command Center Premium 3.0 (1.5.262)

El Centro de Operaciones muestra seis tarjetas, en el orden original:

1. En espera de diagnóstico
2. Reparación en proceso
3. Esperando respuesta del cliente
4. Pendiente de aprobación de presupuesto
5. Listo para entregar
6. Entregado

**Contenido de cada tarjeta:**

- icono iluminado y nombre completo;
- contador real, que se anima solo cuando cambia;
- indicador descriptivo;
- flecha circular;
- línea inferior del color del estado.

**Comportamiento:**

- **Navegación:** la tarjeta y la flecha abren Órdenes con el filtro de su estado.
- **Retrasos:** el indicador cambia a «N con entrega vencida» solo si hay una fecha estimada registrada y vencida.
- **Disposición:** 6 columnas en escritorio amplio, 3 en pantallas medianas, 2 en tableta y celular, y 1 por debajo de 360 px.
- **Movimiento reducido:** se respeta.
