# Sistema de versiones

`local/data/releases.json` es la única fuente del número de versión. De ese registro salen la versión instalada que muestra **Sistema → Sistema y actualizaciones**, el historial de versiones y `CHANGELOG.md` (generado; no se edita a mano).

## Numeración

Versionado semántico `MAYOR.MENOR.PARCHE`:

| Tipo | Cuándo | Ejemplo |
| --- | --- | --- |
| `patch` | Corrección de errores | 1.0.0 → 1.0.1 |
| `minor` | Nuevas funcionalidades compatibles | 1.0.1 → 1.1.0 |
| `major` | Cambios que rompen compatibilidad | 1.1.0 → 2.0.0 |

El número se calcula al publicar, nunca al guardar cambios en Git.

## Flujo de trabajo

```bash
# 1. Anotar cada cambio terminado (queda pendiente, sin número de versión)
python local/versioning.py add fixes "Texto del error corregido."
#    Categorías: features, improvements, fixes, security, performance

# 2. Ver la versión instalada y lo pendiente
python local/versioning.py status

# 3. Vista previa del número que se asignaría (no escribe nada)
python local/versioning.py publish patch --resumen "Descripción breve."

# 4. Tras las pruebas y la autorización, registrar la versión
python local/versioning.py publish patch --resumen "Descripción breve." --confirmar

# 5. Confirmar en Git el registro y CHANGELOG.md, y etiquetar la versión
git add local/data/releases.json CHANGELOG.md && git commit -m "Versión 1.0.1"
python local/versioning.py tag
```

`tag` crea la etiqueta `vX.Y.Z` solo en este equipo: no sube nada ni despliega. Subirla (`git push origin vX.Y.Z`) es una decisión aparte.

## Botón «Última versión»

Compara la versión instalada con el registro de versiones publicadas y muestra las novedades pendientes. Solo consulta: no descarga, instala ni modifica archivos.

- Sin `UPDATE_REGISTRY_URL`, compara con el registro incluido en la propia instalación y lo indica en pantalla.
- Con `UPDATE_REGISTRY_URL` (HTTPS), consulta ese registro publicado, por ejemplo el `releases.json` de la rama principal en GitHub. Si no responde o no es válido, informa el fallo y no afirma que el sistema esté actualizado.

## Instalación de actualizaciones

No existe un mecanismo de despliegue autorizado desde la página, por lo que el módulo nunca ofrece instalar: cuando hay una versión más reciente lo informa y explica que la instalación requiere un despliegue seguro, configurado y autorizado. La integración futura (GitHub → cPanel) debe añadirse en `versioning.check()` (`can_update`) junto con pruebas, respaldo previo y autorización explícita.

## Despliegue actual

El proyecto de Vercel publica automáticamente cada subida a `main`. Mientras eso siga así, subir a GitHub equivale a publicar: para separar ambos pasos hay que desactivar el despliegue automático en Vercel o trabajar en otra rama y fusionar a `main` solo con autorización.
