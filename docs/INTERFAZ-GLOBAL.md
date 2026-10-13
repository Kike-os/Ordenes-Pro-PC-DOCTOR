# Estilos globales de interfaz (1.5.124)

## Barras de desplazamiento

Un único diseño para toda la aplicación, definido al final de `local/static/app.css`: 8 px, pista `#0D1A2D`, barra `#5083B8`, `#70B7F5` al pasar el cursor, bordes redondeados y sin flechas. Chromium, Edge y Safari usan `::-webkit-scrollbar`; Firefox usa `scrollbar-width` y `scrollbar-color` (allí el navegador decide el grosor «thin» y no admite color al pasar el cursor). Se eliminaron las declaraciones sueltas `scrollbar-width:thin` de cada módulo porque en Chromium anulaban el diseño propio. En pantallas táctiles se conserva la barra nativa del sistema. El desplazamiento sigue siendo el nativo: no hay barras simuladas.

## Menús desplegables

`local/static/ui-select.js` sustituye solo la **lista abierta** de cada `<select>` (que los navegadores no permiten estilizar) por una lista con el tema azul: fondo `#0C192D`, opciones `#10233C`, selección `#24558D`, cursor `#1B3B60`, borde `#37618D`, texto `#E3EEFF`. El control cerrado sigue siendo el `<select>` nativo, así que formularios, validaciones, foco y lectores de pantalla no cambian. Teclado: Espacio, F4 o Alt+flecha abren; flechas, Inicio, Fin y escritura rápida recorren; Enter o Tab eligen; Escape cierra. Se aplica automáticamente a cualquier selector presente o futuro (panel y página de citas). En pantallas táctiles se usa el selector nativo del sistema operativo. `data-native="true"` en un `<select>` lo excluye.

## Selectores

Letra de 14 px (16 px en móviles para evitar el zoom de iOS), esquinas de 10 px, texto centrado verticalmente y estados hover/foco uniformes. Las barras de filtros comparten 44 px de alto entre selectores y campos; los selectores dentro de filas de tabla usan 13 px y 36 px.
