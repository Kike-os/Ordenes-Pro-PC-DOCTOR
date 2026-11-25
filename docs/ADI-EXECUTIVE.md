# ADI Executive Intelligence 5.0 · Enterprise AI Workspace

**Módulo:** Asistencia → ADI. Solo administración.

**Modo:** solo lectura. ADI consulta y recomienda; **no** ejecuta cambios. En concreto, no modifica órdenes, estados, pagos, facturas, intereses, mensajes a clientes, configuración ni credenciales.

## Motor (servidor)

- **Herramientas ejecutivas** en `local/adi_exec.py`. Reutilizan los módulos existentes:

  | Herramienta | Módulo que reutiliza |
  |---|---|
  | `finanzas` | Technical Mission Control |
  | `facturacion` | Reporte de facturación |
  | `cartera` | ADI Smart Collections |
  | `atencion_clientes` | Live Support y WhatsApp |
  | `repuestos` | Órdenes |
  | `inventario_bajo` | Inventario |
  | `infraestructura` | Database Guardian, Smart Fiscal Status, AZUR, respaldos y estabilidad |
  | `recomendaciones` | Insights |

- **Permisos en el servidor:** a quien no tiene permiso ni siquiera se le ofrece la herramienta; si se invoca igual, devuelve `sin_permiso`. No se depende del prompt.
- **Privacidad:** nunca se devuelven teléfonos, correos, credenciales ni el texto de los mensajes de clientes. Nada escribe en la base.
- **Pasos y fuentes reales:** cada respuesta guarda los pasos **realmente ejecutados**, las fuentes internas y la hora de consulta. No se simulan procesos ni se muestran razonamientos internos.
- **Insights:** `GET /api/adi/admin/insights` devuelve recomendaciones verificables, sin duplicados. Cada una incluye motivo, prioridad, fecha de detección, registros, información utilizada, acción sugerida y módulo.
- **Estado del servicio:** «EN LÍNEA» solo si la última consulta a la IA fue correcta y no hubo un error posterior. Sin IA configurada aparece «Sin IA» y ADI responde solo con datos.
- **Historial** (privado por usuario):
  - favoritas, archivadas, renombrar y eliminar, con auditoría;
  - calificación de respuestas;
  - regenerar repite la misma pregunta sin duplicarla;
  - contraseñas, claves y tokens se quitan **antes** de guardar o de enviar a la IA.
- **Migración 125** (aditiva): `adi_admin_flags`, `adi_admin_meta` y `adi_admin_feedback`. Sin ella, ADI sigue funcionando, pero sin favoritos, metadatos ni calificación.
- **Separación de canales:** el ADI de clientes (web y WhatsApp) no recibe estas herramientas. El cierre por inactividad de 8 minutos no se aplica a las conversaciones administrativas.

## Interfaz

- **Encabezado:**
  - estado verificado del servicio;
  - conexión y última actualización;
  - «Solo lectura»;
  - botones para el historial, el estado e Insights, las preferencias de sonido y voz, y la pantalla completa (sale con Escape).
- **Panel lateral:** nueva conversación, buscador, pestañas Recientes, Favoritas y Archivadas, agrupación por fecha y menú por conversación.
- **Bienvenida:**
  - saludo según el usuario y la hora de Ecuador;
  - sugerencias elegidas a partir de los indicadores reales;
  - accesos por departamento.
- **Estado operativo en vivo:** 8 tarjetas con datos reales que se actualizan cada 30 s, más Insights. En pantallas de 1440 px o más aparecen como columna; en pantallas menores, en un panel desplegable.
- **Respuestas:**
  - formato seguro: títulos, listas y tablas;
  - «Ver gráfico» dibujado con los valores reales de la tabla;
  - enlaces a órdenes;
  - pasos, fuentes y hora de consulta;
  - acciones: copiar, regenerar, exportar en .md, imprimir, escuchar y calificar.
- **Compositor:**
  - unos 90 px de alto, que crecen hasta 200 px;
  - Enter envía y Shift+Enter hace un salto de línea;
  - micrófono si el navegador lo ofrece;
  - «Detener» deja de esperar la respuesta (si llega, queda en el historial).
  - No hay botón de adjuntar, porque ADI todavía no procesa documentos.

## Pruebas

**Automáticas:** `local/tests/test_adi_executive.py`.

**Visuales:**
- 1920, 1600, 1366, 1280 y 1024 px con zoom del 80 %, 100 %, 125 % y 150 %, más 768, 390 y 320 px;
- sin desbordes, controles superpuestos, textos cortados ni doble desplazamiento.

## Pendiente

- La captura mencionada en la orden no llegó.
- Adjuntar documentos queda para una fase futura.
- La tendencia de las tarjetas, cuando exista una serie histórica real.


## 6.0 (Premium Executive)

- **Tres paneles:**
  - historial a la izquierda;
  - conversación en el centro;
  - **Executive Live Monitor** a la derecha, visible desde 1200 px; en pantallas menores es un panel desplegable.
- **Monitor en filas compactas** (icono, número y descripción): sin cortes de palabra y con tooltip. Cada tarjeta abre su módulo.
- **Estados reales de conexión:** «Sincronizando», «Información actualizada», «En línea», «Reconectando», «Sin conexión» y «Servicio temporalmente no disponible». Si falla una consulta, se conserva el **último dato válido** marcado como desactualizado. Una sola consulta cada 30 s, sin repetir mientras hay otra en curso.
- **Skeletons** mientras cargan las tarjetas y las alertas.
- **Insights en 4 niveles** (crítica, alta, media e informativa), con el **departamento** de cada alerta y los registros afectados.
- **11 departamentos** de acceso: operaciones técnicas, finanzas, cartera, presupuestos y ventas, inventario, atención al cliente, WhatsApp, facturación, licencias, seguridad e infraestructura, y administración ejecutiva.
- **Compositor en su propia área**, sin sombra sobre la conversación, y con **borrador conservado** en la sesión del navegador.
- **Cosas que no cambian:**
  - las conversaciones administrativas no se cierran por inactividad;
  - el cierre de 8 minutos sigue solo para el chat de clientes y no se aplica mientras ADI responde;
  - no hay respuesta progresiva, porque la integración actual devuelve la respuesta completa: se indica «Analizando solicitud» y luego los pasos realmente ejecutados.
