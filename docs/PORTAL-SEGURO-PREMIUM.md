# Secure Customer Portal Enterprise Premium 2.0

## Diseño y cobertura

El verificador compartido se construye en `local/public_identity.py` y utiliza `local/static/public-identity.css`, `local/static/public-identity.js` y los tokens corporativos. La tarjeta conserva el tipo de documento registrado, los cuatro dígitos, el teclado numérico y la comprobación desde el servidor. Los portales muestran la conexión segura cuando se abren en HTTPS. El foco, el retroceso, el pegado y las animaciones de progreso comparten el mismo comportamiento.

El portal de cuenta usa encabezado compacto, identificador de orden, formulario centrado, acción principal de ancho completo y enlace de regreso al seguimiento. Los dos pasos corresponden a la comprobación de identidad y el acceso a la cuenta. Presupuestos, autorizaciones con código por correo, licencias y citas conservan sus etapas y factores propios.

Se revisaron proformas, presupuestos, autorizaciones, seguimiento y cancelación de repuestos, citas y licencias. Saldos, recibos, entregas y facturas autorizadas siguen sujetos a la sesión del portal y a los permisos vigentes de cada descarga. Los enlaces por WhatsApp y correo llevan a esas mismas páginas. Los certificados de garantía y demás documentos con flujos propios conservan sus permisos y presentación.

## Sesión

La expiración se obtiene de la fila de sesión validada para la orden y su enlace. Quince minutos es la duración fija. Recargar o consultar un PDF no la amplía. El navegador usa el plazo devuelto por el servidor para mostrar el contador y retira el contenido protegido al vencer. A continuación carga el formulario con un aviso de expiración. Hay una redirección HTML de respaldo cuando JavaScript está desactivado. El servidor comprueba de nuevo la sesión en cada solicitud protegida, incluidas las descargas.

## Validación y publicación

Las pruebas de `local/tests/test_client_portal.py` cubren la expiración exacta, la recarga, el cierre y el acceso a PDF. `local/tests/test_public_identity_visual.py` usa Chromium y datos ficticios para comprobar pantallas de 320, 390, 768 y 1280 px, contraste, teclado, pegado, retroceso, movimiento reducido y retiro del contenido al expirar.

La corrección usa las tablas vigentes y carece de migraciones nuevas. La versión de producción al preparar este cambio era 1.5.359. La 1.5.360 está reservada en una rama separada para Mail Pro. Este cambio se prepara como 1.5.361 y requiere autorización administrativa para publicar.

La compilación final de 1.5.361 incorpora la 1.5.360 de Mail Pro y conserva su entrada en el historial de versiones.
