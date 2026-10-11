# Gestión de clientes

Las fichas viven en la tabla `clients` de la base del sistema (SQLite local o libSQL/Turso en el hosting), no en archivos ni en el navegador, por lo que sobreviven a actualizaciones y despliegues.

## Importar

Solo administración. **Clientes → Importar** acepta `.xls`, `.xlsx`, tablas HTML guardadas como `.xls` y CSV (máximo 6 MB y 20 000 filas).

1. **Vista previa**: se analiza el archivo sin escribir nada. Muestra las columnas reconocidas, los clientes nuevos, los duplicados, las filas repetidas, las omitidas y las que tienen error.
2. **Duplicados**: una fila cuya cédula o RUC ya existe nunca sobrescribe la ficha. Por cada una se elige *Omitir* o *Completar solo campos vacíos*.
3. **Confirmación**: se crea una copia de seguridad (`local/var/backup-*.sqlite3`) y después se insertan los clientes. Si la copia falla, no se importa nada.
4. **Informe**: queda registrado por fila en `client_import_rows` y se descarga como CSV.

Desde la terminal, con el mismo motor:

```bash
python local/client_import.py preview archivo.xls
python local/client_import.py import archivo.xls --confirmar
```

### Normalización

- Cédulas y RUC: se quitan espacios, puntos y guiones, y se restituye el cero inicial que Excel elimina. Se valida el dígito verificador; si falla, la ficha se importa marcada *Por completar*, no se rechaza.
- Identificaciones con letras u otra longitud se conservan como documento extranjero.
- Teléfonos: se restituye el cero inicial; varios números en una celda se reparten entre teléfono y teléfono secundario.
- Ubicación: los códigos de provincia, cantón y parroquia solo se asignan cuando el nombre coincide de forma inequívoca con el catálogo INEC.
- `9999999999999` (consumidor final) se omite. Una fila sin nombre es un error.
- No se crean órdenes ni equipos durante la importación.

Los valores originales de cada fila, incluidas las columnas comerciales o de facturación que la ficha no usa, se guardan aparte en `client_import_rows.original`.

### Fichas por completar

Una orden exige identificación, teléfono, provincia, cantón, parroquia, ciudad y dirección. Las fichas importadas sin esos datos quedan marcadas *Por completar*: se pueden buscar y consultar, y al elegirlas en una orden nueva el sistema pide completarlas. Técnicos pueden completar una ficha pendiente; el resto de ediciones es de administración.

## Buscar, filtrar y exportar

- La búsqueda (listado y orden nueva) funciona mientras se escribe por nombre o razón social, cédula o RUC, teléfonos, correo y nombre comercial.
- Filtros: estado de la ficha, tipo de cliente y orden alfabético.
- **Exportar** (solo administración) genera un CSV; la acción queda en la auditoría. Las celdas que empiezan por `=`, `+`, `-` o `@` se neutralizan.

## Privacidad

Los archivos de clientes (`*.xls`, `*.xlsx`, `clientes*.csv`) están excluidos de Git y del despliegue. No los subas al repositorio.
