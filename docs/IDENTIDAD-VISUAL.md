# Identidad visual de Órdenes Pro

Los formularios de identidad y las superficies del portal de cuenta comparten los tokens de `local/static/design-tokens.css`. Los valores provienen de los estilos vigentes de presupuesto, seguimiento, citas y portal. Los componentes deben usar las variables de superficie, controles, borde, texto, acción, foco y estado. La tipografía del verificador se hereda de la página.

El tema predeterminado es oscuro. Cuando la página activa explícitamente `data-theme="light"` en el elemento raíz, los mismos componentes heredan la variante clara. Los colores del logotipo, los botones existentes y el tratamiento de documentos impresos se conservan.

La política en `AGENTS.md` aplica a Codex, Claude y cualquier cambio asistido desde ADI. Cambiar la paleta corporativa requiere autorización administrativa expresa. Para una superficie nueva, asigna los tokens existentes antes de considerar un cambio de paleta.

## Regresión visual

Con Python Playwright y Chromium instalados, ejecuta desde la raíz:

```bash
python -m unittest discover -s local/tests -p 'test_public_identity_visual.py'
```

La prueba renderiza plantillas del servidor con datos ficticios. Comprueba la superficie y el contraste de texto y controles en móvil, tableta y escritorio, el tema claro explícito, el foco, el avance entre casillas, el pegado y el modo de movimiento reducido. Los documentos de entrega usan la sesión del portal y su PDF conserva su hoja de estilos.
