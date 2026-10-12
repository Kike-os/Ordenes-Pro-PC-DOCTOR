# Buscador global

Campo del encabezado. Busca órdenes por número de orden, cliente (nombre, identificación o teléfono), marca, modelo y número de serie (`/api/search`, lógica en `local/order_search.py`).

- Resultados mientras se escribe (desde 2 caracteres, 140 ms después de la última tecla); se muestran hasta 8 y el total real.
- No distingue mayúsculas ni tildes y acepta varias palabras en cualquier orden («hp juan», «pérez lenovo»).
- Tolera errores de escritura: una letra en palabras de 4 a 7 caracteres y dos en las de 8 o más. Los términos con más cifras que letras (teléfonos, cédulas, fechas del código) no se aproximan.
- Si hay coincidencias exactas no se mezclan parecidos. Si solo hay parecidos, se indica «Resultados parecidos» y se ofrece «¿Quisiste decir …?».
- El texto encontrado se resalta en el número, el cliente, el equipo y la serie.
- Teclado: ↑ ↓ recorren, Enter abre, Esc cierra. Solo lectura; requiere sesión.
- Revisa las 3000 órdenes más recientes en cada consulta (≈0,1–0,2 s con esa cantidad).
