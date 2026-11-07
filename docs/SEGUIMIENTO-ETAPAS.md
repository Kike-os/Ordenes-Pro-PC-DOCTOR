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
