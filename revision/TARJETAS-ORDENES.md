# Tarjetas de órdenes — 09/10/2026

Se adaptó el HTML proporcionado al listado real de órdenes conservando la identidad oscura, búsqueda, filtro, paginación, controles administrativos y los cinco estados existentes. No se añadieron estados de ejemplo ni se modificó la base de datos.

Archivos: `local/static/app.js` y `local/static/app.css`. Tarjetas con código real, cliente, equipo, fecha de Ecuador, falla, estado, PDF térmico, acta A4 y acceso explícito al comprobante. Etiqueta imprimible generada en una ventana separada con código, equipo y el mismo QR autenticado; sin datos personales. El botón de impresión de la etiqueta se habilita únicamente cuando carga el QR. Iconos SVG locales, sin dependencias CDN. Microinteracciones y movimiento reducido.

Verificación: sintaxis JavaScript correcta; Chromium en 1440, 768, 390 y 320 px, dos tarjetas de datos ficticios, seis acciones, rutas documentales correctas, sin desbordamientos ni modal abierto automáticamente y sin excepciones JavaScript. Capturas y `verificacion-tarjetas.json`. No se enviaron impresiones físicas. Paquete cPanel regenerado; hosting remoto no actualizado.
