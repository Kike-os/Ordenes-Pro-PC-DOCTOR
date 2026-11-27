# Identidad visual de Órdenes Pro

Responde en español y sigue las reglas de operación de [CLAUDE.md](CLAUDE.md).

- Conserva el logotipo original de PC-DOCTOR S.A., los azules corporativos y la identidad visual del sistema.
- Reutiliza las variables del módulo y, para superficies públicas compartidas, los tokens de [design-tokens.css](local/static/design-tokens.css). Usa la tipografía heredada y los tokens de fondo, borde, contraste y sombra. Conserva los botones existentes.
- El modo oscuro es la presentación predeterminada de las interfaces públicas. Un modo claro debe activarse expresamente mediante el tema del sistema. Los fondos claros de PDF, impresión y contenido incrustado siguen sus reglas propias.
- Codex, Claude y ADI necesitan autorización administrativa expresa para modificar colores corporativos, logotipos o identidad visual. Toda interfaz nueva debe heredar el sistema de diseño centralizado. Reserva los fondos claros para temas explícitos y documentos impresos.
- Al cambiar una interfaz pública, valida escritorio, tableta, móvil, teclado, foco, contraste y movimiento reducido. Ejecuta la regresión visual descrita en [Identidad visual](docs/IDENTIDAD-VISUAL.md) con datos ficticios.
