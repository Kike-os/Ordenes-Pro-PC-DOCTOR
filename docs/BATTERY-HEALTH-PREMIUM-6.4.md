# Battery Health Premium 6.4

## Diagnóstico del problema

El diálogo 6.2 presentaba el estado pendiente en el indicador compartido y en el resumen. Además, agrupaba herramientas y preferencias en una columna de paneles. Una alerta y un formulario normal desplazaban las herramientas inferiores incluso en escritorio.

## Corrección

- El diálogo existente mide hasta 660 × 600 px y se limita a 90dvh. La cabecera, la alerta crítica y las acciones están fuera del área desplazable.
- El resumen muestra un solo estado de evaluación y guiones sin medición. Las proporciones, los cinco segmentos, los colores y la animación del indicador compartido se preservan.
- Las cuatro herramientas se agrupan en una cuadrícula en escritorio y se abren de una en una. Sus contadores reflejan los registros presentes. Motivo y método comparten una fila cuando hay espacio. Reemplazo e Historial conservan los mismos flujos.
- En el pie se controlan la animación y la visibilidad del gráfico de evolución. Las preferencias son locales al navegador. Retirar la evidencia exige confirmar en el diálogo antes de guardar.
- ADI distingue registros de BMS, SMBus, carga de placa y alimentación. Una alerta o medición suspendida por seguridad conserva la instrucción de suspender pruebas de carga y calibración.

## Archivos y verificación

- `local/static/app.js` y `local/static/app.css` implementan el diseño con los componentes y tokens existentes.
- `local/adi_order.py` usa los hallazgos registrados y mantiene las recomendaciones de seguridad.
- `local/tests/test_order_battery_visual.py` cubre las dimensiones, teclado, movimiento reducido, exclusión entre herramientas, acciones fijas y estado pendiente.
- `AGENTS.md` y `CLAUDE.md` protegen de forma permanente el diálogo y el indicador original.

Pasaron 39 pruebas focalizadas. Las ocho pruebas visuales se repitieron tras compactar la fila de evaluación y el control final de los cinco tamaños volvió a pasar. Las capturas se generaron en Chromium con datos ficticios. El directorio `output/battery-health-6.4/antes/` contiene el diálogo anterior. `output/battery-health-6.4/despues/` contiene escritorio de 1920 × 1080, 1366 × 768 y 1280 × 720, tableta de 768 × 1024 y móvil de 390 × 844. El adjunto contenía únicamente la especificación escrita. La comparación se hizo con el diálogo publicado y los criterios escritos.

No se añade una migración. Customer Device Intelligence 4.0 ya está publicado en Órdenes Pro v1.6.6, compilación `1aaa5f3`. El siguiente número candidato es v1.6.7 y necesita autorización expresa para publicarse.
