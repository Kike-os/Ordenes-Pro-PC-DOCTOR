# Battery Health Premium 6.2 — Advanced Electrical Diagnostics & Smart Measurement Center

La actualización parte de Battery Health Premium 5.0 en Órdenes Pro v1.6.2. La auditoría de `main` y de las ramas disponibles no encontró una implementación 6.1, Battery Replacement Intelligence ni un componente llamado `CorporateSmartSelect`. La versión candidata es **Órdenes Pro v1.6.3**, siguiendo la secuencia de publicación indicada por administración. Producción y `main` remoto estaban en v1.6.2, compilación `b8065f3`, al preparar esta entrega.

## Funciones

- **Diagnóstico.** Salud y desgaste manuales con dos decimales. Cálculo estimado a partir de la capacidad de carga completa y la capacidad de diseño. Las conversiones entre Wh y Ah requieren el voltaje nominal de referencia de esa batería. Un valor superior al diseño requiere confirmación, conserva las lecturas originales y muestra un máximo del 100 % en el indicador. La carga actual tiene un campo propio.
- **Mediciones.** Voltajes de batería y cargador independientes, corriente, ciclos, temperatura y capacidades. Cada lectura registra si se midió, se reportó por software, se suspendió por seguridad, está pendiente, no está disponible o no aplica. La fuente, la fecha, el instrumento y el usuario autenticado documentan la evaluación. Las identificaciones técnicas y las notas se registran por separado.
- **Informes de Windows.** La vista previa deja elegir una batería y corregir sus datos antes de guardar. Cada revisión conserva los metadatos y el historial de capacidad atribuible. Los informes de varias baterías muestran cada conjunto de lecturas por separado. Windows puede incluir un historial agregado sin identificar la batería. En ese caso no se atribuye a ningún conjunto.
- **Seguridad y microelectrónica.** Una alerta persistente suspende nuevas mediciones físicas de riesgo. Se pueden conservar las lecturas anteriores y registrar medidas de seguridad. Los hallazgos distinguen batería, BMS, SMBus, conector, alimentación, cargador y circuito de carga de la placa. Cada uno admite estado y observaciones. Los cortocircuitos sospechados y confirmados activan la alerta.
- **Reemplazo e historial.** Cada instalación recibe una identidad independiente. La batería activa queda pendiente de evaluación tras el reemplazo. Se conservan las revisiones de la retirada, se registra la garantía real y se calcula la diferencia en puntos porcentuales cuando existen ambas mediciones. El gráfico presenta los puntos registrados por batería.
- **ADI.** El informe de situación y el diálogo interpretan las lecturas, los datos faltantes y la evolución registrada. Con una condición peligrosa, las indicaciones de seguridad sustituyen las sugerencias de carga y calibración. La explicación para el cliente se basa en los datos autorizados.
- **Portal.** Solo una sesión verificada de la orden puede consultar la información de batería que seleccionó administración. Los números de serie, informes, fotografías y observaciones internas se conservan en el diagnóstico privado.

## Implementación y seguridad

| Archivos | Cambio |
| --- | --- |
| `local/battery_diagnostics.py` | Reglas de procedencia, cálculo decimal y extracción de texto del informe HTML. |
| `local/order_battery.py`, `local/app.py` | Revisiones, reemplazos, importación con validación de permisos, auditoría y proyección para el portal. |
| `local/adi_order.py`, `local/client_portal.py` | Explicaciones de ADI y presentación en el portal verificado. |
| `local/static/app.js`, `local/static/app.css`, `local/static/ui-select.js`, `local/templates/dashboard.html` | Diálogo de tres pestañas y adaptación del selector corporativo existente al módulo y a pantallas táctiles. |
| `local/migrations/135_battery_diagnostics.sql`, `local/migrations/MANIFEST.json` | Tabla aditiva y huella del manifiesto. |
| `local/tests/test_battery_diagnostics.py`, `local/tests/test_order_battery_visual.py`, `local/tests/test_db_migrations.py` | Pruebas de reglas, integración, regresión visual y aplicación de la migración. |
| `AGENTS.md`, `local/data/releases.json`, `CHANGELOG.md` | Protección permanente del diseño y registro de los cambios pendientes de publicación. |

Se reutilizaron las revisiones y evidencias de la migración 133, el indicador SVG y sus animaciones, el diálogo de órdenes, el selector central, los tokens de diseño y la autenticación del portal. El límite de fotografías sigue en 750 KB. El límite independiente para HTML es 1 MB. El servidor procesa el archivo como texto inerte, valida formato y estructura y descarta etiquetas activas. En la base se guardan los datos extraídos y el nombre base, nunca la ruta de origen ni el HTML. Retirar un informe afecta a la revisión vigente. Las revisiones anteriores conservan su trazabilidad.

La migración 135 añade una tabla vinculada a cada revisión sin reescribir las existentes. La escritura requiere permisos administrativos, protección CSRF y una revisión vigente. Las evaluaciones anteriores siguen disponibles con la migración 133 mientras se habilita la 135. El portal aplica una lista de campos autorizados independiente de la respuesta interna.

## Verificación

Se usan órdenes, usuarios e informes ficticios y bases temporales. Se prueban los extremos 100 %, 85 %, 0,1 % y 0 %, el cálculo automático, conversiones, diseño cero, capacidad superior al diseño, lecturas vacías, importaciones inválidas y HTML activo, series distintas, seguridad, reemplazos y privacidad. Chromium cubre 320, 390, 768 y 1280 px, ambos temas, teclado, foco, contraste, Escape y movimiento reducido. La regresión conserva la geometría y las animaciones del SVG de batería.

Pasaron 36 pruebas focalizadas, incluidas las de migración con respaldo simulado, permisos, portal y regresión visual. También pasaron la validación de migraciones y las comprobaciones de sintaxis. La regresión general se completó por tramos tras interrupciones del entorno. Pasaron 1.198 pruebas, cinco se omitieron y no hubo fallos. Las cuatro pruebas de libSQL omitidas pasaron por separado en un servidor temporal, donde también se verificó la migración 135 sobre una evaluación previa. La prueba de lectura del QR de autenticación de dos pasos quedó omitida por dependencias de rasterización. La publicación de la v1.6.3 recibió autorización administrativa expresa.

## Activación y reversión

1. Confirmar la versión activa y el commit de `main` remoto. Integrar cualquier actualización intermedia antes de registrar la candidata.
2. Obtener autorización administrativa y un respaldo verificado reciente de la base de producción. Registrar la versión y conservar la entrada de v1.6.2.
3. Desplegar el commit aprobado, verificar la versión y la compilación activas y aplicar la migración 135 desde **Sistema → Migraciones** con el respaldo verificado. Comprobar disponibilidad y permisos.
4. Si se debe revertir, desplegar la compilación anterior conservando la tabla aditiva y sus revisiones. Las mediciones 6.2 quedan preservadas para recuperar el módulo. Restaurar un respaldo requiere autorización y evaluación de las escrituras posteriores.
