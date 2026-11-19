# Estilos globales de interfaz (1.5.124)

## Barras de desplazamiento

Un único diseño para toda la aplicación, definido al final de `local/static/app.css`: 8 px, pista `#0D1A2D`, barra `#5083B8`, `#70B7F5` al pasar el cursor, bordes redondeados y sin flechas. Chromium, Edge y Safari usan `::-webkit-scrollbar`; Firefox usa `scrollbar-width` y `scrollbar-color` (allí el navegador decide el grosor «thin» y no admite color al pasar el cursor). Se eliminaron las declaraciones sueltas `scrollbar-width:thin` de cada módulo porque en Chromium anulaban el diseño propio. En pantallas táctiles se conserva la barra nativa del sistema. El desplazamiento sigue siendo el nativo: no hay barras simuladas.

## Menús desplegables

`local/static/ui-select.js` sustituye solo la **lista abierta** de cada `<select>` (que los navegadores no permiten estilizar) por una lista con el tema azul: fondo `#0C192D`, opciones `#10233C`, selección `#24558D`, cursor `#1B3B60`, borde `#37618D`, texto `#E3EEFF`. El control cerrado sigue siendo el `<select>` nativo, así que formularios, validaciones, foco y lectores de pantalla no cambian. Teclado: Espacio, F4 o Alt+flecha abren; flechas, Inicio, Fin y escritura rápida recorren; Enter o Tab eligen; Escape cierra. Se aplica automáticamente a cualquier selector presente o futuro (panel y página de citas). En pantallas táctiles se usa el selector nativo del sistema operativo. `data-native="true"` en un `<select>` lo excluye.

## Selectores

Letra de 14 px (16 px en móviles para evitar el zoom de iOS), esquinas de 10 px, texto centrado verticalmente y estados hover/foco uniformes. Las barras de filtros comparten 44 px de alto entre selectores y campos; los selectores dentro de filas de tabla usan 13 px y 36 px.

## Confirmaciones y peticiones de texto

El sistema ya no usa las ventanas nativas del navegador (`confirm`, `prompt`, `alert`). Todas las confirmaciones pasan por el diálogo propio:

- `askConfirm(título, texto, botón, peligro)` devuelve `true` solo si la persona elige continuar. El foco inicial queda en «Cancelar»; Escape y el clic fuera cancelan. Las acciones destructivas (eliminar, desactivar, descartar, cerrar todas las sesiones) muestran el botón en rojo; las demás, en estilo neutro.
- `askText(título, etiqueta, valor, botón)` pide un texto corto (renombrar una conversación de ADI). Enter guarda, Escape cancela y no acepta un texto vacío.
- `confirmClose(...)` sigue siendo la base para los cierres con cambios sin guardar.

Se convirtieron 17 avisos: plantilla y descarte de correo, eliminar foto, cierre de sesiones, cambio de rol, desactivar cuenta, rechazar solicitud, restaurar firma, generar o desactivar el enlace de seguimiento, importar clientes, consentimiento y reenvío de recordatorios, renombrar y eliminar conversaciones y activar el micrófono. Ninguna de esas acciones cambió su comportamiento en el servidor.

## Botones de navegación y botón «Cerrar»

**Cancelar · Anterior · Siguiente** comparten un estilo en la reserva de citas y en el asistente de recepción (clases `nav-cancel`, `nav-back`, `nav-next`): fondo oscuro con borde gris azulado para Cancelar y Anterior (con flecha a la izquierda), azul para Siguiente (con flecha a la derecha), 42 px de alto, radio de 11 px, borde rosado suave al pasar el cursor o recibir el foco y estado deshabilitado claramente apagado. Cancelar queda a la izquierda y Anterior y Siguiente agrupados a la derecha; en teléfonos Anterior y Siguiente comparten una fila y Cancelar ocupa la siguiente. La lógica no cambió: Siguiente valida antes de avanzar y Cancelar sigue pidiendo confirmación si hay datos escritos. El defecto corregido era el fondo blanco de Cancelar y Anterior en la página de citas.

**Cerrar** con texto usa el componente `closeButton()` / clase `close-button`: icono X, sin subrayado, 40 px, mismo estilo oscuro. Se aplica en la reserva de citas, el detalle de reportes, la importación de clientes y el asistente de nombres. Solo cierra su ventana o panel; los botones de eliminar o anular no cambiaron.

## Avisos de validación y error

Los mensajes de formulario comparten un aviso compacto (clase `message` en las ventanas del panel y `appointment-message` en la reserva pública): ancho según su texto, icono, rojo suave para errores y verde para confirmaciones, con animación breve y sin animación con «reducir movimiento». Las notificaciones flotantes siguen pasando por `toast()` / `notify()`, que ya evitan duplicados. Si no hay conexión, cualquier operación responde «No pudimos completar la operación. Comprueba tu conexión e inténtalo nuevamente.» en lugar del error técnico del navegador.

## Barra superior estable al recargar (1.5.306)

**Causa del texto encimado al pulsar F5 o Ctrl + R.** En tableta y móvil (menos de 1000 px), `app.js` mueve al menú desplegable el indicador de versión, el buscador (hasta 860 px), el reloj y el clima (`initHeaderNavigation` → `adapt()` y `initReleaseChip` → `placeChip()`). Ese archivo pesa unos 2 MB y se sirve con `Cache-Control: no-store`, así que se descarga en cada recarga. Mientras llegaba, esos elementos seguían en su posición de escritorio y el CSS móvil no los ocultaba: se montaban sobre el logotipo y el usuario, y la barra medía 103 px en lugar de 76 px. Al terminar la carga saltaban a su sitio.

**Corrección (solo CSS y plantilla, sin cambiar funciones):**

- Por debajo de 1000 px, los elementos que todavía están en la posición de escritorio se ocultan por CSS y el menú desplegable cerrado no se dibuja, sin esperar al script.
- Los textos provisionales falsos («Clima no disponible», las iniciales «PC», «Cargando…», «--:--:--») se sustituyen por esqueletos que ocupan exactamente la altura de línea del dato real.
- El clima muestra «Cargando clima…» (`weather-loading`, `aria-busy`) hasta recibir la respuesta. Si el servicio falla, muestra «Sin datos · Clima no disponible», como antes.
- En escritorio, la fila de módulos reserva su hueco y aparece con un fundido breve cuando se conoce el rol: los módulos de administración ya no empujan «Sistema» y «Asistencia».
- El estado del chip de versión ocupa siempre el ancho de «En observación», y el bloque nombre/rol mide siempre 125 px. Así, el buscador, el reloj y el clima no se desplazan cuando llegan los datos.
- La campana ya viene en la plantilla; el script no la duplica.
- Nombre del usuario: se recorta con «…» y el nombre completo con el rol aparece en un tooltip solo cuando no cabe, o cuando en pantallas estrechas solo se ve el avatar (`accountTip()`, que se recalcula al cambiar el tamaño).
- Clima: las tres líneas de la tarjeta se ajustaron para que «Otavalo, Ecuador» no toque el borde inferior.
- Mientras el menú de cuenta o el de notificaciones está abierto, los avisos flotantes (por ejemplo, «Tienes 4 notificaciones sin leer») se apartan para no tapar el nombre y el rol.

**Caché tras publicar.** `app.css` y `app.js` se sirven con `no-store`, así que después de un despliegue el navegador nunca combina una plantilla nueva con estilos o scripts antiguos.

**Comprobación.** Recarga normal y forzada, y red lenta (350 ms de latencia, de 250 a 700 KB/s), en 1920, 1440, 1366, 1280, 1100, 1024, 860, 768, 390 y 320 px. Resultado: barra de 117 px en escritorio y 76 px en tableta y móvil durante toda la carga, desplazamiento de diseño (CLS) igual a 0 en la barra, sin solapes, sin textos cortados, sin desplazamiento horizontal y sin errores de consola.
