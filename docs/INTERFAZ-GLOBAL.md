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
