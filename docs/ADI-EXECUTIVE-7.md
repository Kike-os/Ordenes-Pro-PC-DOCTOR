# ADI Executive Intelligence 7.0

## Estado de la implementación

La versión **1.5.363** incorporó los flujos iniciales de laboratorio. El candidato posterior a **1.5.370** incorpora las funciones nuevas de esta página. La validación con OpenAI y Turso queda pendiente en Preview.

## Flujos implementados

- **Laboratorio por orden.** Personal técnico y administración pueden consultar el historial del mismo equipo, registrar mediciones con unidades y condiciones, y preparar un borrador copiable con mediciones, comprobaciones pendientes y referencias aprobadas. Los borradores quedan separados del diagnóstico oficial hasta que otro técnico autorizado los apruebe.
- **Revisión del diagnóstico.** La propuesta separa hallazgos confirmados, conclusión y comprobaciones pendientes. Otro técnico puede aprobarla o devolverla con un motivo. La aprobación actualiza el diagnóstico interno de la unidad seleccionada y registra autor, revisor y fecha. Una propuesta desactualizada requiere revisión nueva.
- **Centro de conocimiento.** Los extractos incluyen fuente, fecha, versión, categoría y permisos. La aprobación requiere a otro integrante autorizado. Una corrección aprobada sustituye la versión que aparece en la búsqueda y conserva el registro anterior. La búsqueda combina términos y un vocabulario técnico controlado en hasta 300 registros accesibles. Devuelve hasta 15 resultados con el concepto reconocido y el fragmento correspondiente.
- **Firmware.** El formulario comprueba que estén presentes los datos de identificación, compatibilidad y procedencia. El navegador puede calcular SHA-256 de archivos de hasta 64 MiB. La ficha siempre requiere revisión técnica. La aplicación carece de operaciones de escritura de firmware.
- **WhatsApp.** La orden queda protegida por el código de un solo uso. El titular con sesión vigente puede pedir «Enlace de seguimiento». El enlace se entrega en la conversación y se excluye del historial que consulta ADI. El portal solicita los cuatro dígitos del documento al abrir la cuenta.
- **Reincidencias.** El borrador muestra las revisiones del mismo equipo durante los últimos 90 días. El monitor ejecutivo muestra el recuento agregado de equipos con dos o más revisiones.
- **Supervisión.** Executive Live Monitor indica si el laboratorio está instalado. Release Monitor muestra los cambios entre las dos últimas verificaciones de la misma versión, sin mover los umbrales de estabilidad ni incluir ejecuciones de versiones anteriores.

## Motores y dependencias

| Motor solicitado | Evidencia disponible en esta rama |
| --- | --- |
| Smart Core 7.0 | El resumen coordinado consulta plazos, pronóstico y disponibilidad del laboratorio. Indica resultados parciales. La coordinación de los once motores sigue pendiente. |
| Guardian | Controles existentes de autenticación y roles. El laboratorio aplica permisos, límites y auditoría en el servidor. |
| Auto Repair | AutoCare pausa y restaura la redacción asistida, el análisis visual y la búsqueda semántica. La acción requiere autorización administrativa, vista previa y confirmación. Se conserva y audita el ajuste anterior. |
| Predictive AI | Previsión de nuevas órdenes para siete días. Compara dos promedios con 28 días de entrenamiento y 14 días de validación cronológica. Informa el error observado y devuelve un estado de historial insuficiente cuando corresponde. |
| Customer Intelligence | Se conserva el chat actual. El enlace de seguimiento se verifica con Meta simulado. |
| Financial Intelligence | Se conservan las herramientas ejecutivas de finanzas, facturación y cartera. |
| Technical Intelligence PRO | Laboratorio, historial del equipo, mediciones, listas de comprobación y revisión previa de firmware. Análisis de una imagen técnica elegida y autorizada por el usuario. Devuelve observaciones visibles, hipótesis y comprobaciones para revisión del técnico. |
| Business Intelligence | Se conservan Executive Live Monitor e Insights. Los indicadores adicionales requieren fuentes y criterios de aceptación. |
| Data Guardian | Se conserva Database Guardian. El manifiesto incorpora las migraciones aditivas 131 y 132. |
| Release Monitor 3.0 | Comparación verificable de resultados entre ejecuciones. El nombre y los requisitos de estabilidad vigentes se conservan mientras se completa la ampliación. |
| Memory Engine | Extractos revisados y correcciones versionadas. La carga privada de PDF originales está implementada en el candidato con la migración 134. La búsqueda semántica administrativa usa embeddings para clasificar hasta 24 extractos técnicos aprobados de la categoría seleccionada. Devuelve hasta ocho fuentes con sus extractos. |

## Seguridad, archivos y recursos

Los endpoints del laboratorio están en `local/app.py` y sus controles en `local/adi_lab.py`. La interfaz usa `local/static/app.js` y `local/static/app.css`. El envío verificado por WhatsApp está en `local/whatsapp_identity.py`. El comparador usa `local/release_monitor.py`. Las pruebas se encuentran en `local/tests/test_adi_lab.py`, `local/tests/test_release_monitor.py` y `local/tests/test_whatsapp_identity.py`.

Las migraciones aditivas **131** y **132** crean tablas e índices para fuentes, mediciones y revisiones de diagnóstico. En pruebas se aplicó a bases SQLite temporales. Cada medición dispone de una clave de solicitud para evitar duplicados. Las escrituras de laboratorio y las revisiones quedan en auditoría. El buscador usa el extracto autorizado. El PDF original opcional se descarga de forma privada con los permisos de su propuesta y queda ligado a su revisión. La migración 134 guarda los PDF de hasta 1 MB con su SHA-256. Los archivos de firmware permanecen en el navegador.

El borrador y la búsqueda local funcionan sin llamadas a modelos. El análisis visual envía solo la imagen autorizada a OpenAI con almacenamiento de respuesta desactivado. La búsqueda semántica externa solicita confirmación antes de transferir la consulta y los títulos y extractos aprobados. Excluye los PDF y las fuentes reservadas. Un borrador consulta hasta 40 mediciones y 10 órdenes anteriores. Una búsqueda examina hasta 300 extractos de 6.000 caracteres. Son límites de implementación. Una medición local con 300 extractos ficticios de hasta 6.000 caracteres y 20 consultas repetidas redujo la mediana de 251 a 1,5 ms tras reutilizar la normalización. La primera consulta pasó de 247 a 269 ms y, con cuatro hilos, el percentil 95 de la búsqueda pasó de 1.249 a 6,4 ms. Las cifras miden la clasificación en Python con la misma colección de fuentes. Queda medir la latencia del servicio con Vercel y Turso.

## Resultados de pruebas

- El candidato pasó 32 pruebas dirigidas de ADI, AutoCare, batería y Release Monitor con datos ficticios. Las llamadas de visión y embeddings usaron respuestas simuladas.
- El componente Battery Health Premium 4.0 pasó 20 combinaciones en Chromium a 320, 390, 768 y 1440 px. Se comprobó ausencia de desbordamientos en el componente, foco visible y movimiento reducido.

- 5 pruebas del laboratorio. Cubren autenticación, repetición de mediciones y propuestas, revisión de fuentes, bloqueo de escritura de firmware, aprobación por otro técnico y protección de diagnósticos modificados.
- 17 pruebas de identidad por WhatsApp con Meta simulado. Cubren el enlace exclusivo del titular, el vencimiento de sesión y la exclusión del token del historial.
- 5 pruebas del monitor y 15 pruebas de regresión del asistente ejecutivo y por orden.
- Chromium en 320 y 1280 px. Se comprobó el panel, la generación del borrador y el cálculo de SHA-256 con un archivo ficticio. En 320, 768 y 1280 px se comprobó también la revisión de diagnósticos.
- La primera ejecución del monitor detectó el checksum de una revisión anterior de la migración 131 en el manifiesto. Se corrigió la entrada de la migración aún inédita y se repitieron las pruebas. El control de migraciones y las pruebas dirigidas quedaron correctos.

## Producción y reversión

La validación integral requiere documentos técnicos autorizados y un entorno separado de producción para probar el proveedor visual y la búsqueda semántica. Quedan pendientes el diseño claro y oscuro de toda la experiencia y la validación de WhatsApp con una cuenta de prueba.

Para el despliegue, verificar primero un respaldo reciente. Después de promover la compilación autorizada, comprobar que las migraciones 131 y 132 del laboratorio y 133 de batería estén aplicadas y aplicar 134 para habilitar los PDF desde **Sistema → Migraciones** y verificarlas con Database Guardian. Ante un problema, volver a promover la compilación anterior y conservar las tablas aditivas con las mediciones y las revisiones registradas.
