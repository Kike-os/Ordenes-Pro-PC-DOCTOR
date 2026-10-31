# Sistema de controles de selección

Desde la 1.5.218, casillas, radios, interruptores y tarjetas seleccionables comparten un solo diseño. El estilo se aplica sobre los controles nativos del navegador: nombres, valores, envío de formularios, teclado y lectores de pantalla no cambian.

## Cuándo usar cada control

| Necesidad | Control |
| --- | --- |
| Elegir varios registros u opciones, o confirmar algo | Casilla (`AppCheckbox`) |
| Elegir una opción entre varias excluyentes | Radio (`AppRadioGroup`) |
| Activar o desactivar una función o configuración | Interruptor (`AppSwitch`, o `asSwitch(input)` sobre un control existente) |
| Opción con descripción, icono o precio | Tarjeta (`AppSelectionCard`) |
| Casilla maestra de una tabla, con estado parcial | `AppTableSelection` |

No se usan interruptores para seleccionar registros o productos.

## Dónde está

- **Estilo:** bloque «Sistema de controles de selección» al final de `local/static/app.css`, con las variables `--ctl-*`. `quote.css` y `tracking.css` llevan la misma apariencia para las páginas públicas.
- **Componentes:** `local/static/app.js`, antes de `OF_LOOK`. Deben quedar en el nivel superior del archivo: con `'use strict'`, una función dentro de un bloque no es visible desde fuera.

## Estados y accesibilidad

- Sin marcar, marcada, parcial, deshabilitada, inválida (`aria-invalid`) y con enfoque visible con teclado.
- 18 px con ratón y 22 px en pantallas táctiles, con una zona de toque de al menos 44 px.
- Con movimiento reducido no hay transiciones. En modo de alto contraste de Windows vuelve el control nativo.

## Limitaciones que hay que recordar

- **El visto y el guion se dibujan con CSS.** La política de seguridad del sistema (`img-src`) bloquea las imágenes `data:`: no se pueden usar como fondo.
- **Controles ya ocultos dentro de su propia tarjeta** (`.check-chip`, `label.access-card`, `.agenda-switch`, `.license-method`, `.license-row-file`, `.cjc-denom`, `.cjc-rule`, `.cm-seg`) quedan fuera del estilo general. Si se crea otro, hay que agregarlo a esa lista. `.access-card` sin `label` no se debe excluir: también es el contenedor del formulario de inicio de sesión.
