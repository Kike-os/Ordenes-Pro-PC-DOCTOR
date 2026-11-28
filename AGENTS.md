# Identidad visual de Órdenes Pro

Responde en español y sigue las reglas de operación de [CLAUDE.md](CLAUDE.md).

- Conserva el logotipo original de PC-DOCTOR S.A., los azules corporativos y la identidad visual del sistema.
- Reutiliza las variables del módulo y, para superficies públicas compartidas, los tokens de [design-tokens.css](local/static/design-tokens.css). Usa la tipografía heredada y los tokens de fondo, borde, contraste y sombra. Conserva los botones existentes.
- El modo oscuro es la presentación predeterminada de las interfaces públicas. Un modo claro debe activarse expresamente mediante el tema del sistema. Los fondos claros de PDF, impresión y contenido incrustado siguen sus reglas propias.
- Codex, Claude y ADI necesitan autorización administrativa expresa para modificar colores corporativos, logotipos o identidad visual. Toda interfaz nueva debe heredar el sistema de diseño centralizado. Reserva los fondos claros para temas explícitos y documentos impresos.
- Al cambiar una interfaz pública, valida escritorio, tableta, móvil, teclado, foco, contraste y movimiento reducido. Ejecuta la regresión visual descrita en [Identidad visual](docs/IDENTIDAD-VISUAL.md) con datos ficticios.

## Publicación de versiones

- Comprueba la versión activa en producción y la rama principal remota antes de publicar. Integra la versión anterior y conserva su entrada en el registro y el CHANGELOG.
- Publica en orden, sin saltar una versión pendiente. Verifica la versión y la compilación activas después del despliegue.

## Centro de diagnóstico de batería

- Conserva el SVG aprobado de batería, sus cinco segmentos, forma, contorno, terminal, dimensiones, proporciones, tipografía, colores semánticos y animaciones. Conserva el avión de seguimiento internacional, su trayectoria y animaciones.
- Mantén diagnóstico, reemplazo e historial en un único diálogo. Trata los informes como datos inertes y conserva las mediciones históricas. Las mediciones privadas requieren autorización expresa para aparecer en el portal verificado.
- Ante un hallazgo peligroso, la alerta y la suspensión de mediciones físicas tienen prioridad sobre la salud calculada.

## Seguimiento verificado y diálogo Enterprise Compact

- Conserva el encabezado, las etapas y su animación, el historial, los códigos QR y de barras, los documentos y el diseño A4 del seguimiento. Protege íntegramente el avión, su tamaño, trayectoria, velocidad y movimiento.
- Comparte el mismo componente de batería entre administración, portal y A4. Mantén el encabezado y las acciones del diálogo accesibles, con una sola región de desplazamiento vertical y paneles complementarios cerrados inicialmente.
- Muestra únicamente datos registrados y autorizados. Las alertas críticas prevalecen sobre el indicador de salud y permanecen hasta una resolución técnica registrada.

## Customer Device Intelligence 4.0

- Reutiliza las etapas, la animación de batería y el componente logístico originales. Mantén los controles en el tema corporativo y usa los selectores compartidos cuando corresponda.
- Vincula el reemplazo a registros existentes de la misma orden. Las aprobaciones siguen el flujo oficial de presupuesto. El informe verificado utiliza únicamente información autorizada.
- Si la consulta falla, conserva la última información disponible y avisa que puede estar desactualizada. Retira la ficha de pantalla e impresión cuando caduque o se revoque la sesión.
- Antes de publicar, verifica la regresión de permisos y diseño y registra la autorización administrativa expresa.

## Battery Health Premium 6.4

- Mantén las herramientas en una cuadrícula compacta en escritorio, con paneles cerrados al entrar y una sola herramienta abierta por acción del usuario.
- Muestra el estado de evaluación una sola vez en el resumen. Usa guiones cuando falten mediciones y conserva la alerta crítica visible durante el desplazamiento.
- Mantén las preferencias en el pie y exige confirmación antes de retirar evidencia. Conserva el indicador animado compartido y los datos de revisiones anteriores.
