# Premium Animated Icons 3.0

Sistema único de iconos animados de Órdenes Pro. Se implanta por fases; cada fase se prueba y se publica como una versión propia.

## Biblioteca elegida

**Lucide** (licencia ISC, incluida en `local/static/lucide-LICENSE`), como SVG en línea. Es la misma familia de iconos que ya usaba el sistema.

Se evaluaron Lucide Animated, Lucide React y Motion for React, y se descartaron. Las tres necesitan React y un empaquetador, pero Órdenes Pro es JavaScript sin framework y su política de seguridad (CSP) solo admite scripts propios. Añadir React solo para los iconos aumentaría el peso de la página y su fragilidad. Las animaciones se hacen con CSS, sin dependencias nuevas.

## Componente `animatedIcon()`

Está en `local/static/app.js`:

```js
animatedIcon(icono, {size, tone, state, motion, label, still, stroke, className})
```

- **icono**: nombre de `PA_ICONS` (`check`, `alert`, `bell`, `wallet`, `refresh`, `arrow`, `plus`, `chevron`, `loader`) o el trazado `d` de Lucide.
- **size**: 14, 16, 18, 20, 22 o 24 px. Sin él, el icono conserva el tamaño que le da su módulo.
- **tone**: color funcional (`gris`, `azul`, `ambar`, `violeta`, `verde`, `turquesa`, `rojo`). Sin él, hereda el color del texto.
- **state**:
  - `success` y `error` reproducen una animación breve una sola vez;
  - `loading` gira solo mientras hay un proceso real.

  `setIconState(svg, estado)` cambia el estado de un icono ya pintado.
- **motion**: movimiento al pasar el cursor. Si no se indica, se deduce del trazado:

  | Valor | Movimiento | Se usa en |
  |---|---|---|
  | `nudge` (por defecto) | el icono sube 1,5 px y crece un 8 % | cualquier icono |
  | `slide` | se desplaza 3 px | flechas |
  | `drop` | baja 2 px | chevrones |
  | `turn` | gira 90° | signo «+» |
  | `spin` | da una vuelta | actualizar |
  | `ring` | se balancea | campana |
  | `none` | sin movimiento | — |
- **label**: etiqueta accesible (`role="img"` y `<title>`). Sin ella, el icono es decorativo (`aria-hidden="true"`).
- **still**: desactiva el movimiento de ese icono.

`systemIcon()` (unos 460 usos) y `operationIcon()` usan este componente, así que todos sus iconos reciben las microinteracciones sin cambiar su tamaño ni su posición.

## Capa de microinteracciones (`local/static/app.css`)

Afecta a los iconos `.pa-icon`, `.field-icon` (plantillas) e `.inv-icon` (Inventario) cuando están dentro de un control: botón, enlace, `summary`, pestaña, opción o elemento de menú.

| Acción | Efecto |
|---|---|
| Hover | movimiento según el tipo (tabla anterior); solo con ratón o lápiz, porque en pantallas táctiles no hay hover |
| Click | el icono se encoge un instante (160 ms) |
| Selección | pulso único cuando el elemento pasa a `aria-current`, `aria-selected` o `aria-pressed` |
| Éxito | aparición con rebote suave (avisos de éxito y `state: 'success'`) |
| Error | vaivén de 2 px, una sola vez (avisos de error y `state: 'error'`) |
| Carga | giro continuo solo con `state: 'loading'`, `data-busy` o `aria-busy`, es decir, con un proceso real |
| Notificaciones | la campana mantiene su animación al llegar un aviso nuevo (`notify-ring`) |

Reglas de diseño:

- Solo se usan animaciones de un disparo con `translate`, `scale` y `rotate`, de 160 a 250 ms. Se suman a los `transform` de cada módulo (por ejemplo, el giro de un chevrón abierto) en lugar de pisarlos, no cambian dimensiones y no empujan el texto.
- El control va dentro de `:where()`, que no suma especificidad: las reglas compiten solo por el icono, y la pulsación, que va después, gana al hover.
- No se añadió ninguna animación infinita.
- Todo está dentro de `@media (prefers-reduced-motion: no-preference)`: con «reducir movimiento» nada se mueve.
- La navegación principal conserva su realce propio, ya aprobado: sube 1 px y brilla. No recibe movimiento adicional.

## Colores de los estados de una orden

Es la misma identidad de color en las tarjetas del Centro de Operaciones, en el selector y los chips de estado (`statusMeta`), en Seguimiento de Órdenes y en las etiquetas de las listas. Solo cambia el tono: los estados, la lógica, los contadores y los datos no cambian.

| Estado | Color |
|---|---|
| En espera de diagnóstico | gris azulado |
| Reparación en proceso | azul (diagnóstico pasa a índigo para distinguirse) |
| Esperando respuesta del cliente | ámbar |
| Pendiente de aprobación de presupuesto | violeta |
| Listo para entregar y En espera de entrega | verde |
| Entregado | turquesa |
| Revisión por falla recurrente (incidencia) | rojo |

**Pago pendiente:** el indicador financiero de la lista de órdenes («Debe $…», «Abonó · debe $…») muestra ahora un icono de cartera, y un check cuando está pagado, en lugar del punto de color. Así no depende solo del color y conserva su etiqueta accesible «Saldo: …».

## Fases

1. **1.5.307:** componente, capa de microinteracciones, navegación y barra, estados de orden e indicador de pago.
2. Órdenes, Presupuestos, Cobertura, Caja y Gastos internos.
3. Clientes, Equipos, Citas, Inventario, Repuestos, Licencias y Facturación.
4. PQRS, Notificaciones, Correo, Atención, Reportes, Configuración y portal público, con la revisión de las animaciones infinitas sin utilidad. El fondo tecnológico y el orbe de ADI forman parte de la identidad y se conservan.

## Comprobación (fase 1)

- **Prueba de navegador:** 14 de 14, en una base temporal con datos ficticios. Cubre:
  - que el CSS se interpreta;
  - el componente;
  - hover, pulsación y selección con el ratón real;
  - movimiento reducido;
  - avisos de éxito y error;
  - colores de estado;
  - el indicador de pago;
  - 13 módulos en 1440, 768 y 390 px, sin desbordes, sin iconos fuera de su botón y sin errores de consola.
- **Regresión de la barra superior (1.5.306):** desplazamiento de diseño 0 en 10 anchos durante F5 y 20 de 20 en los menús.
- **Nota para pruebas automáticas:** Chromium sin interfaz declara que no hay ratón (`hover: none`). Para probar el hover hay que lanzarlo con `--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4`.
