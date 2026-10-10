# Corrección de apertura del comprobante — 09/10/2026

## Causa y corrección

La inicialización del frontend interpretaba `/orders/<código>` como una instrucción para ejecutar `showReceipt()` y abrir el modal. Esa URL persistía al actualizar o volver a entrar. No era una nueva recepción ni una duplicación causada por el backend.

Ahora esa ruta muestra el detalle dentro del módulo. Solo el guardado confirmado y la acción explícita «Ver comprobante» abren el modal. Tras guardar se normaliza la URL al listado sin repetir el POST; navegar entre módulos y restaurar la página desde la caché del navegador cierra la confirmación. Se conserva el QR y la consulta autenticada del registro.

También se corrigió la detección de cambios de una casilla: se comprobaba su valor constante `on` en vez de su estado marcado, lo que solicitaba descartar datos aun con un formulario vacío.

## Archivos

- `local/static/app.js`: inicialización, navegación, modal, aceptación y configuración documental.
- `local/templates/dashboard.html`, `local/static/app.css`: aceptación, documentos y estilos de impresión.
- `local/app.py`: endpoints de condiciones, aceptación transaccional y PDF térmico.
- `local/service_terms.py`, `local/document_logo.py`, `local/thermal_pdf.py`, `local/receipt_pdf.py`: versiones, evidencia, logo y documentos.
- `local/migrations/005_service_terms.sql`: migración aditiva e inmutabilidad.
- `local/tests/test_service_terms.py`, `local/tests/test_reception.py`: comprobaciones automatizadas.
- Documentación, ejemplo de entorno y paquete cPanel actualizados.

## Verificación

42 pruebas automatizadas; validación sintáctica JavaScript; navegador real en seis tamaños entre 320 y 1440 px. Guardado fallido sin confirmación; guardado correcto; recargas repetidas tras guardar, en enlace directo y con modal abierto; reingreso mediante enlace directo; apertura explícita; navegación entre módulos. Una sola orden sintética después de las recargas. Sin errores de consola. Evidencia: `verificacion-condiciones-recarga.json`.

PDF A4 de dos páginas y ticket continuo revisados visualmente. QR del ticket decodificado y coincidente con el seguimiento original. Publicación y aceptación probadas exclusivamente con textos ficticios en base temporal. Pruebas de autorización, versión histórica, inmutabilidad, ausencia de aceptación retroactiva y conservación de numeración/QR.

## Pendientes y alcance

Faltan texto completo aprobado, texto compacto aprobado, versión y fecha de vigencia de las condiciones reales. No se publicaron condiciones ficticias en la base utilizada por el sistema ni se imprimieron físicamente. La migración local conserva órdenes y relaciones existentes. No se accedió ni desplegó al hosting remoto; se entrega ZIP actualizado para esa instalación.
