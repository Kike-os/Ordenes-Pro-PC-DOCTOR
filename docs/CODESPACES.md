# Desarrollo en GitHub Codespaces (VS Code en Windows)

Entorno de **desarrollo**. No es producción: usa una base vacía en `local/var/` (dentro del Codespace), sin Turso, sin correo,
sin IA, sin Google Drive y sin facturación. Producción sigue en Vercel y la base central en Turso.

## Qué hay en `.devcontainer/`

| Archivo | Para qué |
|---|---|
| `devcontainer.json` | Imagen ligera de Python 3.12 con Node 22, máquina de 2 núcleos, puertos 8010 y 8011 privados. |
| `preparar.sh` | Se ejecuta al crear el Codespace: instala dependencias y crea la base local vacía. Se detiene si encuentra `TURSO_*`. |
| `iniciar-codespace.sh` | Inicia la app (`--crear-admin` crea el administrador de pruebas, `--pruebas` ejecuta las pruebas). Retira las variables de servicios reales. |
| `servidor-navegador.py` | La misma aplicación en el puerto 8011 para usarla desde el navegador (`https://…-8011.app.github.dev`). |

¿Por qué dos puertos? La app solo acepta peticiones de su propio origen. Desde VS Code de escritorio el puerto 8010 llega
a tu Windows como `http://localhost:8010`; desde el navegador la dirección es `https://<codespace>-8011.app.github.dev`.

## Cuota gratuita (cuenta personal GitHub Free)

- **120 horas-núcleo** de cómputo al mes: con la máquina de 2 núcleos son **60 horas** de Codespace encendido.
- **15 GB-mes** de almacenamiento (cuenta aunque el Codespace esté detenido; este entorno ocupa unos pocos GB).
- La cuota se renueva cada mes. Consumo: github.com/settings/billing/usage.
- Protección contra cobros: sin método de pago y con el presupuesto de Codespaces en **US$0 con «Usage blocked»**.
  Al agotarse la cuota GitHub **bloquea** Codespaces; no cobra. No borres ese presupuesto ni agregues método de pago.
- Suspensión automática: **15 minutos** de inactividad. Detén el Codespace al terminar: no esperes a la suspensión.
- Un solo Codespace para este repositorio. Los detenidos se borran a los 30 días sin uso (GitHub avisa por correo antes).

## Uso diario

1. **Abrir:** VS Code → `Ctrl+Shift+P` → «Codespaces: Connect to Codespace» → elige el de *Ordenes-Pro-PC-DOCTOR*.
   Navegador: github.com/codespaces → «…» → *Open in browser*.
2. **¿Estoy en el Codespace?** Esquina inferior izquierda en verde/azul con **«Codespaces: …»**, título con
   **[Codespaces]**, y la terminal muestra `@Kike-os ➜ /workspaces/Ordenes-Pro-PC-DOCTOR`. Una carpeta local de Windows
   no muestra nada de eso y su ruta empieza con `C:\`.
3. **Iniciar la app:** terminal → `bash .devcontainer/iniciar-codespace.sh`. `Ctrl+C` la detiene.
4. **Guardar ≠ subir.** `Ctrl+S` guarda el archivo **dentro del Codespace** (sobrevive a detenerlo, pero se pierde si se borra
   el Codespace). Solo **commit + push** lo deja en GitHub.
5. **Revisar y subir:** panel *Control de código fuente* (`Ctrl+Shift+G`) → revisa cada archivo → mensaje → *Commit* → *Sync/Push*.
6. **Detener:** `Ctrl+Shift+P` → «Codespaces: Stop Current Codespace» (o github.com/codespaces → «…» → *Stop codespace*).

## Ramas y despliegues (importante)

- Subir a **`main` publica en producción** (Vercel despliega solo; `publicar.sh` hace exactamente eso).
- Subir **cualquier otra rama** crea una **vista previa** en Vercel (no producción, sin tareas programadas).
- Trabaja en una rama propia y pasa a `main` solo cuando decidas publicar.

## Secretos

Ninguno es necesario para desarrollar. Nunca crees secretos de Codespaces con `TURSO_*` ni credenciales reales, y no subas
`.env`. Si algún día hace falta uno de pruebas: github.com/settings/codespaces → *Codespace user secrets*.
